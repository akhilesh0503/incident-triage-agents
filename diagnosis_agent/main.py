from __future__ import annotations

import asyncio
import json
import os
from typing import Any

import asyncpg
import structlog
from litestar import Litestar, get, post
from litestar.response import Response, Stream
from prometheus_client import Counter, Histogram, generate_latest, CONTENT_TYPE_LATEST

from shared.a2a_models import (
    AgentCapabilities, AgentCard, AgentSkill,
    JSONRPCRequest, JSONRPCResponse, JSONRPCError, A2AErrorCode,
    TaskState,
)
from shared.redis_store import TaskStore
from diagnosis_agent.prompts import build_diagnosis_prompt
from diagnosis_agent.ollama_client import call_ollama

log = structlog.get_logger()

POSTGRES_DSN = os.environ["POSTGRES_DSN"]
REDIS_URL    = os.environ.get("REDIS_URL", "redis://localhost:6379")
PORT         = int(os.environ.get("DIAGNOSIS_AGENT_PORT", "8004"))

TASKS_TOTAL   = Counter("diagnosis_agent_tasks_total",          "Tasks processed by DiagnosisAgent", ["status"])
TASK_DURATION = Histogram("diagnosis_agent_task_duration_seconds", "DiagnosisAgent task duration")

_task_store: TaskStore
_pool: asyncpg.Pool

AGENT_CARD = AgentCard(
    name="DiagnosisAgent",
    description=(
        "Synthesizes evidence from LogAgent, MetricsAgent, and DeploymentAgent "
        "using an LLM to produce root cause analysis and actionable remediation steps"
    ),
    url=f"http://localhost:{PORT}",
    version="1.0.0",
    capabilities=AgentCapabilities(streaming=True),
    skills=[
        AgentSkill(
            id="diagnose_incident",
            name="Diagnose Incident",
            description=(
                "Accepts structured evidence from specialist agents, calls Ollama qwen2.5:3b, "
                "returns root cause + remediation steps, writes record to incidents table"
            ),
            input_modes=["application/json"],
            output_modes=["application/json"],
        )
    ],
)


async def _write_incident(
    conn: asyncpg.Connection,
    service: str,
    alert_description: str,
    root_cause: str,
    confidence: str,
    remediation_steps: list[str],
    agents_consulted: list[str],
) -> int:
    row = await conn.fetchrow(
        """
        INSERT INTO incidents
            (service, alert_description, root_cause, confidence,
             remediation, agents_consulted, status)
        VALUES ($1, $2, $3, $4, $5::jsonb, $6::jsonb, 'open')
        RETURNING id
        """,
        service,
        alert_description,
        root_cause,
        confidence,
        json.dumps(remediation_steps),
        json.dumps(agents_consulted),
    )
    return row["id"]


async def _process(task_id: str, payload: dict[str, Any]) -> None:
    with TASK_DURATION.time():
        try:
            await _task_store.update_status(task_id, TaskState.WORKING, "Building diagnosis prompt...")

            service           = payload.get("service", "unknown-service")
            alert_description = payload.get("alert_description", "Unknown alert")
            log_findings      = payload.get("log_findings", {})
            metrics_findings  = payload.get("metrics_findings", {})
            deployment_findings = payload.get("deployment_findings", {})

            prompt = build_diagnosis_prompt(
                alert_description=alert_description,
                service=service,
                log_findings=log_findings,
                metrics_findings=metrics_findings,
                deployment_findings=deployment_findings,
            )

            await _task_store.update_status(task_id, TaskState.WORKING, "Calling Ollama for root cause analysis...")
            llm_result = await call_ollama(prompt)

            agents_consulted = [
                a for a, d in [
                    ("LogAgent",        log_findings),
                    ("MetricsAgent",    metrics_findings),
                    ("DeploymentAgent", deployment_findings),
                ] if d
            ]

            async with _pool.acquire() as conn:
                incident_id = await _write_incident(
                    conn,
                    service=service,
                    alert_description=alert_description,
                    root_cause=llm_result["root_cause"],
                    confidence=llm_result["confidence"],
                    remediation_steps=llm_result["remediation_steps"],
                    agents_consulted=agents_consulted,
                )

            result = {
                "incident_id": incident_id,
                "service": service,
                "alert_description": alert_description,
                "root_cause": llm_result["root_cause"],
                "confidence": llm_result["confidence"],
                "remediation_steps": llm_result["remediation_steps"],
                "agents_consulted": agents_consulted,
                "evidence_summary": {
                    "log_error_count": log_findings.get("error_count", 0),
                    "log_patterns_found": len(log_findings.get("findings", [])),
                    "metrics_worst_severity": metrics_findings.get("worst_severity", "ok"),
                    "metrics_anomaly_count": len(metrics_findings.get("anomalies", [])),
                    "deployment_correlation_score": deployment_findings.get("correlation_score", 0),
                },
            }

            await _task_store.complete_task(task_id, result)
            TASKS_TOTAL.labels(status="completed").inc()
            log.info(
                "diagnosis_complete",
                task_id=task_id,
                incident_id=incident_id,
                service=service,
                confidence=llm_result["confidence"],
            )

        except Exception as exc:
            log.exception("diagnosis_failed", task_id=task_id, error=str(exc))
            await _task_store.fail_task(task_id, str(exc))
            TASKS_TOTAL.labels(status="failed").inc()


@get("/.well-known/agent-card.json")
async def agent_card() -> dict:
    return AGENT_CARD.model_dump()


@get("/tasks/{task_id:str}/events")
async def task_events(task_id: str) -> Stream:
    async def generate():
        async for updated in _task_store.subscribe(task_id):
            yield f"data: {updated.model_dump_json()}\n\n"
    return Stream(generate(), media_type="text/event-stream")


@post("/", status_code=200)
async def handle_rpc(data: dict[str, Any]) -> Response:
    req = JSONRPCRequest(**data)

    if req.method == "tasks/send":
        params = req.params or {}
        message = params.get("message", {})
        parts = message.get("parts", [{}])
        raw = parts[0].get("content", {}) if parts else {}
        if isinstance(raw, str):
            try:
                raw = json.loads(raw)
            except Exception:
                raw = {}

        task = await _task_store.create(
            agent_name="DiagnosisAgent",
            message_text=f"Diagnose incident for {raw.get('service', 'unknown')}",
        )
        asyncio.create_task(_process(task.id, raw))
        resp = JSONRPCResponse(id=req.id, result=task.model_dump())

    elif req.method == "tasks/get":
        task_id = (req.params or {}).get("id", "")
        task = await _task_store.get(task_id)
        if not task:
            resp = JSONRPCResponse(
                id=req.id,
                error=JSONRPCError(code=A2AErrorCode.TASK_NOT_FOUND, message="Task not found"),
            )
        else:
            resp = JSONRPCResponse(id=req.id, result=task.model_dump())

    elif req.method == "tasks/cancel":
        task_id = (req.params or {}).get("id", "")
        await _task_store.cancel_task(task_id)
        resp = JSONRPCResponse(id=req.id, result={"cancelled": True})

    else:
        resp = JSONRPCResponse(
            id=req.id,
            error=JSONRPCError(code=A2AErrorCode.METHOD_NOT_FOUND, message=f"Unknown method: {req.method}"),
        )

    return Response(content=resp.model_dump(), media_type="application/json")


@get("/metrics")
async def prometheus_metrics() -> Response:
    return Response(content=generate_latest(), media_type=CONTENT_TYPE_LATEST)


@get("/health")
async def health() -> dict:
    return {"status": "ok", "agent": "DiagnosisAgent"}


async def startup() -> None:
    global _task_store, _pool
    _pool = await asyncpg.create_pool(POSTGRES_DSN, min_size=2, max_size=10)
    _task_store = TaskStore(REDIS_URL)
    await _task_store.connect()
    log.info("diagnosis_agent_started", port=PORT)


async def shutdown() -> None:
    await _pool.close()
    await _task_store.disconnect()


app = Litestar(
    route_handlers=[agent_card, task_events, handle_rpc, prometheus_metrics, health],
    on_startup=[startup],
    on_shutdown=[shutdown],
)
