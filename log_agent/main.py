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
    Task, TaskState,
)
from shared.redis_store import TaskStore
from log_agent.analyzer import analyze_logs

log = structlog.get_logger()

POSTGRES_DSN = os.environ["POSTGRES_DSN"]
REDIS_URL    = os.environ.get("REDIS_URL", "redis://localhost:6379")
PORT         = int(os.environ.get("LOG_AGENT_PORT", "8001"))

TASKS_TOTAL   = Counter("a2a_tasks_total",          "Tasks processed", ["agent", "status"])
TASK_DURATION = Histogram("a2a_task_duration_seconds", "Task duration", ["agent"])

_task_store: TaskStore
_pool: asyncpg.Pool

AGENT_CARD = AgentCard(
    name="LogAgent",
    description="Queries PostgreSQL logs table and detects error patterns for a given service",
    url=f"http://localhost:{PORT}",
    version="1.0.0",
    capabilities=AgentCapabilities(streaming=True),
    skills=[
        AgentSkill(
            id="analyze_logs",
            name="Analyze Logs",
            description="Scans recent log entries for a service and returns structured findings",
            input_modes=["application/json"],
            output_modes=["application/json"],
        )
    ],
)


async def _process(task_id: str, service: str, window_minutes: int) -> None:
    with TASK_DURATION.labels(agent="log_agent").time():
        try:
            await _task_store.update_status(task_id, TaskState.WORKING, "Querying logs...")
            async with _pool.acquire() as conn:
                result = await analyze_logs(conn, service, window_minutes)
            await _task_store.complete_task(task_id, result)
            TASKS_TOTAL.labels(agent="log_agent", status="completed").inc()
            log.info("log_analysis_done", task_id=task_id, service=service, anomalous=result["anomalous"])
        except Exception as exc:
            log.exception("log_analysis_failed", task_id=task_id, error=str(exc))
            await _task_store.fail_task(task_id, str(exc))
            TASKS_TOTAL.labels(agent="log_agent", status="failed").inc()


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
        payload = parts[0].get("content", {}) if parts else {}
        if isinstance(payload, str):
            try:
                payload = json.loads(payload)
            except Exception:
                payload = {}

        service        = payload.get("service", "user-service")
        window_minutes = int(payload.get("window_minutes", 15))

        task = await _task_store.create(
            agent_name="LogAgent",
            message_text=f"Analyze logs for {service}",
        )
        asyncio.create_task(_process(task.id, service, window_minutes))
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
async def metrics() -> Response:
    return Response(content=generate_latest(), media_type=CONTENT_TYPE_LATEST)


@get("/health")
async def health() -> dict:
    return {"status": "ok", "agent": "LogAgent"}


async def startup() -> None:
    global _task_store, _pool
    _pool = await asyncpg.create_pool(POSTGRES_DSN, min_size=2, max_size=10)
    _task_store = TaskStore(REDIS_URL)
    await _task_store.connect()
    log.info("log_agent_started", port=PORT)


async def shutdown() -> None:
    await _pool.close()
    await _task_store.disconnect()


app = Litestar(
    route_handlers=[agent_card, task_events, handle_rpc, metrics, health],
    on_startup=[startup],
    on_shutdown=[shutdown],
)
