#!/usr/bin/env python3
"""
run_traffic.py — fires all 5 incident scenarios through the triage pipeline
and prints a summary table.

Usage:
    python run_traffic.py [--base-url http://localhost:8000] [--delay 5]
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
    duration_s:   float = 0.0
    status:       str  = "pending"   # completed | failed | timeout


def _run_scenario(base_url: str, scenario_name: str, timeout: int = 120) -> TriageResult:
    result = TriageResult(scenario=scenario_name, service="", triage_id="")

    with httpx.Client(base_url=base_url, timeout=30) as client:
        # 1. Inject anomaly
        sim = client.post(f"/simulate/{scenario_name}")
        sim.raise_for_status()
        sim_data = sim.json()
        result.service = sim_data["service"]
        alert_description = sim_data["alert_description"]

        # 2. Start triage
        triage = client.post("/triage", json={
            "alert_description": alert_description,
            "service":           result.service,
        })
        triage.raise_for_status()
        result.triage_id = triage.json()["triage_id"]

    # 3. Stream SSE events until complete/failed
    t0 = time.monotonic()
    deadline = t0 + timeout

    with httpx.Client(base_url=base_url, timeout=timeout) as client:
        with client.stream("GET", f"/triage/{result.triage_id}/events") as resp:
            for line in resp.iter_lines():
                if time.monotonic() > deadline:
                    result.status = "timeout"
                    break
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

                elif stage == "complete":
                    diag = event.get("diagnosis", {})
                    result.confidence  = diag.get("confidence", "")
                    result.root_cause  = diag.get("root_cause", "")[:120]
                    result.incident_id = diag.get("incident_id")
                    result.status      = "completed"
                    break

                elif stage == "failed":
                    result.status = "failed"
                    break

    result.duration_s = round(time.monotonic() - t0, 1)
    return result


def _print_summary(results: list[TriageResult]) -> None:
    print()
    print("=" * 90)
    print("  INCIDENT TRIAGE TRAFFIC RESULTS")
    print("=" * 90)

    completed = [r for r in results if r.status == "completed"]
    failed    = [r for r in results if r.status != "completed"]

    print(f"  {len(completed)}/{len(results)} scenarios completed successfully\n")

    fmt = "  {:<22} {:<20} {:<18} {:<8} {:<7}"
    print(fmt.format("SCENARIO", "ALERT TYPE", "AGENTS USED", "CONF", "TIME"))
    print("  " + "-" * 80)

    for r in results:
        agents_str = "+".join(a.replace("Agent", "") for a in r.agents_ran) or "—"
        status_marker = "" if r.status == "completed" else f" [{r.status.upper()}]"
        print(fmt.format(
            r.scenario[:22],
            r.alert_type[:20],
            agents_str[:18],
            r.confidence[:8],
            f"{r.duration_s}s{status_marker}",
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
    print("=" * 90)

    # Verify routing correctness
    print()
    print("  ROUTING VERIFICATION:")
    routing_checks = {
        "memory_leak":        ({"Log", "Metrics"},             {"Deployment"}),
        "failed_deployment":  ({"Log", "Deployment"},          {"Metrics"}),
        "high_latency":       ({"Log", "Metrics"},             {"Deployment"}),
        "database_overload":  ({"Log", "Metrics", "Deployment"}, set()),
        "cpu_spike":          ({"Metrics", "Log"},             {"Deployment"}),
    }
    all_routing_ok = True
    for r in results:
        if r.status != "completed":
            continue
        expected_present, expected_absent = routing_checks.get(r.scenario, (set(), set()))
        actual = set(a.replace("Agent", "") for a in r.agents_ran)
        missing  = expected_present - actual
        surprise = expected_absent & actual
        if missing or surprise:
            print(f"  ROUTING MISMATCH [{r.scenario}]: missing={missing}, unexpected={surprise}")
            all_routing_ok = False
        else:
            print(f"  OK [{r.scenario}]: {sorted(actual)}")
    if all_routing_ok:
        print()
        print("  All routing rules verified correctly.")
    print()


def main() -> int:
    parser = argparse.ArgumentParser(description="Fire all incident scenarios through triage pipeline")
    parser.add_argument("--base-url", default="http://localhost:8000")
    parser.add_argument("--delay",    type=int, default=3,
                        help="Seconds to wait between scenarios (default: 3)")
    parser.add_argument("--timeout",  type=int, default=120,
                        help="Per-scenario timeout in seconds (default: 120)")
    args = parser.parse_args()

    scenarios = [
        "memory_leak",
        "failed_deployment",
        "high_latency",
        "database_overload",
        "cpu_spike",
    ]

    print(f"Running {len(scenarios)} scenarios against {args.base_url}")
    print()

    results: list[TriageResult] = []
    for i, scenario in enumerate(scenarios, 1):
        print(f"  [{i}/{len(scenarios)}] {scenario}...", end=" ", flush=True)
        try:
            result = _run_scenario(args.base_url, scenario, timeout=args.timeout)
            results.append(result)
            print(f"{result.status} ({result.duration_s}s, alert_type={result.alert_type})")
        except Exception as exc:
            print(f"ERROR: {exc}")
            results.append(TriageResult(scenario=scenario, service="", triage_id="", status="error"))

        if i < len(scenarios):
            time.sleep(args.delay)

    _print_summary(results)

    failed_count = sum(1 for r in results if r.status != "completed")
    return 1 if failed_count else 0


if __name__ == "__main__":
    sys.exit(main())
