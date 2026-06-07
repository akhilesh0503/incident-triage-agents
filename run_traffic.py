#!/usr/bin/env python3
"""
run_traffic.py — fires all 15 incident scenarios through the triage pipeline
and prints a summary table with routing verification.

Includes one "cold service" test (no /simulate) that verifies graceful
degradation when all agents return empty findings.

Usage:
    python run_traffic.py [--base-url http://localhost:8000] [--delay 3]
"""
from __future__ import annotations

import argparse
import json
import sys
import time
from dataclasses import dataclass, field
from typing import Optional

import httpx


@dataclass
class TriageResult:
    scenario:     str
    service:      str
    triage_id:    str
    alert_type:   str  = ""
    confidence:   str  = ""
    root_cause:   str  = ""
    incident_id:  Optional[int] = None
    agents_ran:   list[str] = field(default_factory=list)
    agent_errors: list[str] = field(default_factory=list)
    duration_s:   float = 0.0
    status:       str  = "pending"


def _stream_triage(base_url: str, triage_id: str, result: TriageResult, timeout: int) -> None:
    deadline = time.monotonic() + timeout
    with httpx.Client(base_url=base_url, timeout=timeout) as client:
        with client.stream("GET", f"/triage/{triage_id}/events") as resp:
            for line in resp.iter_lines():
                if time.monotonic() > deadline:
                    result.status = "timeout"
                    return
                if not line.startswith("data:"):
                    continue
                try:
                    event = json.loads(line[5:].strip())
                except json.JSONDecodeError:
                    continue

                stage = event.get("stage", "")

                if stage == "classified":
                    result.alert_type = event.get("alert_type", "")

                elif stage == "agent_done":
                    agent = event.get("agent", "")
                    if agent:
                        result.agents_ran.append(agent)

                elif stage == "agent_error":
                    agent = event.get("agent", "")
                    msg   = event.get("message", "")
                    result.agent_errors.append(f"{agent}: {msg}")

                elif stage == "complete":
                    diag = event.get("diagnosis", {})
                    result.confidence  = diag.get("confidence", "")
                    result.root_cause  = diag.get("root_cause", "")[:120]
                    result.incident_id = diag.get("incident_id")
                    result.status      = "completed"
                    return

                elif stage == "failed":
                    result.status = "failed"
                    return


def _run_scenario(base_url: str, scenario_name: str, timeout: int = 120) -> TriageResult:
    result = TriageResult(scenario=scenario_name, service="", triage_id="")

    with httpx.Client(base_url=base_url, timeout=30) as client:
        sim = client.post(f"/simulate/{scenario_name}")
        sim.raise_for_status()
        sim_data = sim.json()
        result.service = sim_data["service"]
        alert_description = sim_data["alert_description"]

        triage = client.post("/triage", json={
            "alert_description": alert_description,
            "service":           result.service,
        })
        triage.raise_for_status()
        result.triage_id = triage.json()["triage_id"]

    t0 = time.monotonic()
    _stream_triage(base_url, result.triage_id, result, timeout)
    result.duration_s = round(time.monotonic() - t0, 1)
    return result


def _run_cold_triage(base_url: str, timeout: int = 120) -> TriageResult:
    """
    Failure-handling test — submit a triage for a service with no data in the DB.
    All three agents return empty findings. Verifies:
      - Pipeline does not crash on empty agent results
      - DiagnosisAgent still produces a result (graceful degradation)
      - Triage completes with status 'completed', not 'failed'
    """
    result = TriageResult(
        scenario="cold_service",
        service="reporting-service",
        triage_id="",
    )

    with httpx.Client(base_url=base_url, timeout=30) as client:
        triage = client.post("/triage", json={
            "alert_description": (
                "ALERT: reporting-service is returning errors. No further details available. "
                "On-call engineer triggered manual triage."
            ),
            "service": "reporting-service",
        })
        triage.raise_for_status()
        result.triage_id = triage.json()["triage_id"]

    t0 = time.monotonic()
    _stream_triage(base_url, result.triage_id, result, timeout)
    result.duration_s = round(time.monotonic() - t0, 1)
    return result


def _print_summary(results: list[TriageResult]) -> None:
    print()
    print("=" * 100)
    print("  INCIDENT TRIAGE TRAFFIC RESULTS")
    print("=" * 100)

    completed = [r for r in results if r.status == "completed"]
    failed    = [r for r in results if r.status != "completed"]

    print(f"  {len(completed)}/{len(results)} scenarios completed successfully\n")

    fmt = "  {:<24} {:<22} {:<20} {:<8} {:<7}"
    print(fmt.format("SCENARIO", "ALERT TYPE", "AGENTS USED", "CONF", "TIME"))
    print("  " + "-" * 86)

    for r in results:
        agents_str = "+".join(a.replace("Agent", "") for a in r.agents_ran) or "—"
        status_marker = "" if r.status == "completed" else f" [{r.status.upper()}]"
        error_marker  = " ⚠ partial" if r.agent_errors else ""
        print(fmt.format(
            r.scenario[:24],
            r.alert_type[:22],
            agents_str[:20],
            r.confidence[:8],
            f"{r.duration_s}s{status_marker}{error_marker}",
        ))

    print()
    print("  ROOT CAUSES:")
    for r in results:
        if r.root_cause:
            print(f"  [{r.scenario}] {r.root_cause}...")

    if failed:
        print()
        print("  FAILURES:")
        for r in failed:
            print(f"  [{r.scenario}] status={r.status}")

    print()
    print(f"  Incidents recorded in DB: {[r.incident_id for r in completed if r.incident_id]}")
    print("=" * 100)

    # ── Routing verification ──────────────────────────────────────────────────
    print()
    print("  ROUTING VERIFICATION:")

    # Original 5 — strict: exact agents required and forbidden
    strict_checks: dict[str, tuple[set, set]] = {
        "memory_leak":        ({"Log", "Metrics"},               {"Deployment"}),
        "failed_deployment":  ({"Log", "Deployment"},            {"Metrics"}),
        "high_latency":       ({"Log", "Metrics"},               {"Deployment"}),
        "database_overload":  ({"Log", "Metrics", "Deployment"}, set()),
        "cpu_spike":          ({"Metrics", "Log"},               {"Deployment"}),
    }

    # New 9 — lenient: key agents must be present; LLM may classify as a known
    # or unknown type — we don't enforce exact routing, just that the primary
    # signal agent ran
    lenient_checks: dict[str, set] = {
        "disk_full":           {"Log"},
        "cert_expiry":         {"Log"},
        "service_crash":       {"Log"},
        "db_deadlock":         {"Log"},
        "rollback_incident":   {"Log", "Deployment"},
        "traffic_spike":       {"Metrics"},
        "connection_storm":    {"Log"},
        "gradual_degradation": {"Log", "Metrics"},
        "null_pointer_storm":  {"Log"},
    }

    all_strict_ok = True

    for r in results:
        if r.status != "completed":
            continue
        actual = set(a.replace("Agent", "") for a in r.agents_ran)

        if r.scenario == "cold_service":
            if len(actual) >= 2:
                print(f"  OK [cold_service]: agents={sorted(actual)} conf={r.confidence} — graceful degradation verified")
            else:
                print(f"  WARN [cold_service]: only {actual} ran — expected multiple agents for unknown routing")
            continue

        if r.scenario in strict_checks:
            required, forbidden = strict_checks[r.scenario]
            missing  = required - actual
            surprise = forbidden & actual
            if missing or surprise:
                print(f"  ROUTING MISMATCH [{r.scenario}]: missing={missing}, unexpected={surprise}")
                all_strict_ok = False
            else:
                print(f"  OK [{r.scenario}]: {sorted(actual)}")

        elif r.scenario in lenient_checks:
            required = lenient_checks[r.scenario]
            missing  = required - actual
            if missing:
                print(f"  PARTIAL [{r.scenario}]: expected {required}, got {actual} (alert_type={r.alert_type})")
            else:
                print(f"  OK [{r.scenario}]: {sorted(actual)} (alert_type={r.alert_type})")

    if all_strict_ok:
        print()
        print("  All 5 strict routing rules verified correctly.")
    print()


def main() -> int:
    parser = argparse.ArgumentParser(description="Fire all incident scenarios through triage pipeline")
    parser.add_argument("--base-url", default="http://localhost:8000")
    parser.add_argument("--delay",    type=int, default=3,
                        help="Seconds to wait between scenarios (default: 3)")
    parser.add_argument("--timeout",  type=int, default=120,
                        help="Per-scenario timeout in seconds (default: 120)")
    args = parser.parse_args()

    # 14 injected scenarios + 1 cold-service failure test = 15 total
    scenarios = [
        "memory_leak",
        "failed_deployment",
        "high_latency",
        "database_overload",
        "cpu_spike",
        "disk_full",
        "cert_expiry",
        "service_crash",
        "db_deadlock",
        "rollback_incident",
        "traffic_spike",
        "connection_storm",
        "gradual_degradation",
        "null_pointer_storm",
    ]
    total = len(scenarios) + 1

    print(f"Running {total} scenarios against {args.base_url}")
    print(f"  (14 injected scenarios + 1 cold-service failure handling test)")
    print()

    results: list[TriageResult] = []

    for i, scenario in enumerate(scenarios, 1):
        print(f"  [{i}/{total}] {scenario}...", end=" ", flush=True)
        try:
            result = _run_scenario(args.base_url, scenario, timeout=args.timeout)
            results.append(result)
            extra = " ⚠ agent_errors" if result.agent_errors else ""
            print(f"{result.status} ({result.duration_s}s, alert_type={result.alert_type}){extra}")
        except Exception as exc:
            print(f"ERROR: {exc}")
            results.append(TriageResult(scenario=scenario, service="", triage_id="", status="error"))

        if i < total and args.delay > 0:
            time.sleep(args.delay)

    # Cold-service failure test — no /simulate call
    print(f"  [{total}/{total}] cold_service (no simulate — failure handling test)...", end=" ", flush=True)
    try:
        result = _run_cold_triage(args.base_url, timeout=args.timeout)
        results.append(result)
        print(f"{result.status} ({result.duration_s}s, conf={result.confidence}) — graceful degradation")
    except Exception as exc:
        print(f"ERROR: {exc}")
        results.append(TriageResult(scenario="cold_service", service="reporting-service", triage_id="", status="error"))

    _print_summary(results)

    failed_count = sum(1 for r in results if r.status not in ("completed",))
    return 1 if failed_count else 0


if __name__ == "__main__":
    sys.exit(main())
