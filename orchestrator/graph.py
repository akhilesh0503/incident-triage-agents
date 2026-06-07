from __future__ import annotations

import asyncio
import json
import os
import uuid
from typing import Any, Optional

import redis.asyncio as aioredis
import structlog
from langgraph.graph import END, StateGraph
from typing_extensions import TypedDict

from orchestrator.a2a_client import send_task_and_wait
from orchestrator.classifier import ALERT_ROUTING, classify_alert

log = structlog.get_logger()

LOG_AGENT_URL        = os.environ.get("LOG_AGENT_URL",        "http://localhost:8001")
METRICS_AGENT_URL    = os.environ.get("METRICS_AGENT_URL",    "http://localhost:8002")
DEPLOYMENT_AGENT_URL = os.environ.get("DEPLOYMENT_AGENT_URL", "http://localhost:8003")
DIAGNOSIS_AGENT_URL  = os.environ.get("DIAGNOSIS_AGENT_URL",  "http://localhost:8004")

_redis: Optional[aioredis.Redis] = None


def set_redis(r: aioredis.Redis) -> None:
    global _redis
    _redis = r


async def _publish(triage_id: str, event: dict[str, Any]) -> None:
    if _redis:
        await _redis.publish(f"triage:{triage_id}", json.dumps(event))


class TriageState(TypedDict):
    triage_id: str
    alert_description: str
    service: str
    alert_type: str
    agents_to_run: list[str]
    log_findings: Optional[dict]
    metrics_findings: Optional[dict]
    deployment_findings: Optional[dict]
    diagnosis: Optional[dict]
    error: Optional[str]


# ── Nodes ─────────────────────────────────────────────────────────────────────

async def classify_alert_node(state: TriageState) -> dict:
    triage_id = state["triage_id"]
    await _publish(triage_id, {
        "stage": "classifying",
        "message": "Classifying alert type via LLM...",
    })
    try:
        alert_type = await classify_alert(state["alert_description"])
        agents_to_run = ALERT_ROUTING.get(alert_type, ["log", "metrics", "deployment"])
        agent_names = [{"log": "LogAgent", "metrics": "MetricsAgent", "deployment": "DeploymentAgent"}[a]
                       for a in agents_to_run]
        await _publish(triage_id, {
            "stage": "classified",
            "alert_type": alert_type,
            "agents_to_run": agents_to_run,
            "message": f"Classified as [{alert_type}] — routing to: {', '.join(agent_names)}",
        })
        log.info("alert_classified", triage_id=triage_id, alert_type=alert_type, agents=agents_to_run)
        return {"alert_type": alert_type, "agents_to_run": agents_to_run}
    except Exception as exc:
        await _publish(triage_id, {"stage": "failed", "message": f"Classification failed: {exc}"})
        return {"error": str(exc), "alert_type": "unknown", "agents_to_run": ["log", "metrics", "deployment"]}


async def _call_specialist(
    name: str,
    triage_id: str,
    base_url: str,
    payload: dict,
) -> tuple[str, dict]:
    await _publish(triage_id, {
        "stage": "agent_started",
        "agent": name,
        "message": f"{name}: starting analysis...",
    })
    try:
        result = await send_task_and_wait(base_url, payload, timeout=45.0)
        summary = _summarize_findings(name, result)
        await _publish(triage_id, {
            "stage": "agent_done",
            "agent": name,
            "anomalous": result.get("anomalous", False),
            "message": f"{name}: {summary}",
        })
        return name, result
    except Exception as exc:
        await _publish(triage_id, {
            "stage": "agent_error",
            "agent": name,
            "message": f"{name}: failed — {exc}",
        })
        return name, {"error": str(exc), "anomalous": False}


def _summarize_findings(agent_name: str, result: dict) -> str:
    if agent_name == "LogAgent":
        count = result.get("error_count", 0)
        patterns = [f["pattern"] for f in result.get("findings", [])[:2]]
        pat_str = ", ".join(patterns) if patterns else "no critical patterns"
        return f"found {count} errors — {pat_str}"
    elif agent_name == "MetricsAgent":
        severity = result.get("worst_severity", "ok")
        anomalies = result.get("anomalies", [])
        if anomalies:
            top = anomalies[0]
            return f"{top['metric']} at {top['current_max']} [{severity}]"
        return "all metrics normal"
    elif agent_name == "DeploymentAgent":
        score = result.get("correlation_score", 0)
        reason = result.get("correlation_reason", "")
        return f"correlation {score}/100 — {reason[:60]}"
    return "analysis complete"


async def run_specialists_node(state: TriageState) -> dict:
    triage_id = state["triage_id"]
    service = state["service"]
    agents_to_run = state.get("agents_to_run", ["log", "metrics", "deployment"])

    await _publish(triage_id, {
        "stage": "investigating",
        "agents": agents_to_run,
        "message": f"Dispatching {len(agents_to_run)} specialist agent(s) in parallel...",
    })

    _agent_map = {
        "log":        ("LogAgent",        LOG_AGENT_URL,        {"service": service, "window_minutes": 15}),
        "metrics":    ("MetricsAgent",    METRICS_AGENT_URL,    {"service": service, "window_minutes": 15}),
        "deployment": ("DeploymentAgent", DEPLOYMENT_AGENT_URL, {"service": service, "window_minutes": 60}),
    }

    coros = [
        _call_specialist(name, triage_id, url, payload)
        for key in agents_to_run
        for name, url, payload in [_agent_map[key]]
    ]

    results = await asyncio.gather(*coros)

    updates: dict[str, Any] = {}
    for agent_name, findings in results:
        key = agent_name.lower().replace("agent", "_findings")
        updates[key] = findings

    return updates


async def run_diagnosis_node(state: TriageState) -> dict:
    triage_id = state["triage_id"]
    await _publish(triage_id, {
        "stage": "diagnosing",
        "message": "DiagnosisAgent: synthesizing evidence with LLM...",
    })
    try:
        payload = {
            "service":            state["service"],
            "alert_description":  state["alert_description"],
            "log_findings":       state.get("log_findings") or {},
            "metrics_findings":   state.get("metrics_findings") or {},
            "deployment_findings": state.get("deployment_findings") or {},
        }
        diagnosis = await send_task_and_wait(DIAGNOSIS_AGENT_URL, payload, timeout=120.0)
        await _publish(triage_id, {
            "stage": "complete",
            "diagnosis": diagnosis,
            "message": f"Triage complete — root cause identified (confidence: {diagnosis.get('confidence', '?')})",
        })
        log.info("triage_complete", triage_id=triage_id, incident_id=diagnosis.get("incident_id"))
        return {"diagnosis": diagnosis}
    except Exception as exc:
        await _publish(triage_id, {"stage": "failed", "message": f"Diagnosis failed: {exc}"})
        return {"error": str(exc)}


async def mark_failed_node(state: TriageState) -> dict:
    await _publish(state["triage_id"], {
        "stage": "failed",
        "message": state.get("error", "Triage pipeline failed"),
    })
    return {}


def route_after_classify(state: TriageState) -> str:
    return "mark_failed" if state.get("error") else "run_specialists"


# ── Graph compilation ──────────────────────────────────────────────────────────

def build_graph():
    g = StateGraph(TriageState)
    g.add_node("classify_alert",  classify_alert_node)
    g.add_node("run_specialists", run_specialists_node)
    g.add_node("run_diagnosis",   run_diagnosis_node)
    g.add_node("mark_failed",     mark_failed_node)

    g.set_entry_point("classify_alert")
    g.add_conditional_edges(
        "classify_alert",
        route_after_classify,
        {"run_specialists": "run_specialists", "mark_failed": "mark_failed"},
    )
    g.add_edge("run_specialists", "run_diagnosis")
    g.add_edge("run_diagnosis",   END)
    g.add_edge("mark_failed",     END)

    return g.compile()


TRIAGE_GRAPH = build_graph()


async def run_triage(alert_description: str, service: str) -> tuple[str, dict]:
    triage_id = str(uuid.uuid4())
    initial_state: TriageState = {
        "triage_id":          triage_id,
        "alert_description":  alert_description,
        "service":            service,
        "alert_type":         "",
        "agents_to_run":      [],
        "log_findings":       None,
        "metrics_findings":   None,
        "deployment_findings": None,
        "diagnosis":          None,
        "error":              None,
    }
    final_state = await TRIAGE_GRAPH.ainvoke(initial_state)
    return triage_id, final_state
