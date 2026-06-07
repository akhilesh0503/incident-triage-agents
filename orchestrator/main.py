from __future__ import annotations

import asyncio
import json
import os
from typing import Any, Optional

import asyncpg
import redis.asyncio as aioredis
import structlog
from litestar import Litestar, get, post
from litestar.response import Response, Stream
from prometheus_client import Counter, Histogram, generate_latest, CONTENT_TYPE_LATEST

from orchestrator.graph import run_triage, set_redis
from orchestrator.scenarios import SCENARIOS, inject_anomaly
from orchestrator.a2a_client import discover_agent_card

log = structlog.get_logger()

POSTGRES_DSN = os.environ["POSTGRES_DSN"]
REDIS_URL    = os.environ.get("REDIS_URL", "redis://localhost:6379")
PORT         = int(os.environ.get("ORCHESTRATOR_PORT", "8000"))

TRIAGE_TOTAL    = Counter("orchestrator_triage_total",          "Triage pipelines run", ["status"])
TRIAGE_DURATION = Histogram("orchestrator_triage_duration_seconds", "Triage pipeline duration")

_pool: asyncpg.Pool
_redis: aioredis.Redis
_agent_cards: dict[str, Any] = {}


# ── Triage endpoint ────────────────────────────────────────────────────────────

@post("/triage")
async def start_triage(data: dict[str, Any]) -> Response:
    alert_description = data.get("alert_description", "")
    service           = data.get("service", "unknown-service")

    if not alert_description:
        return Response(
            content={"error": "alert_description is required"},
            media_type="application/json",
            status_code=400,
        )

    triage_id_holder: list[str] = []

    async def _run():
        with TRIAGE_DURATION.time():
            try:
                tid, _ = await run_triage(alert_description, service)
                triage_id_holder.append(tid)
                TRIAGE_TOTAL.labels(status="completed").inc()
            except Exception as exc:
                log.exception("triage_failed", error=str(exc))
                TRIAGE_TOTAL.labels(status="failed").inc()

    # Start graph in background, but we need the triage_id immediately.
    # run_triage generates the triage_id before doing any async work,
    # so we invoke the graph directly to get the id synchronously first.
    import uuid
    triage_id = str(uuid.uuid4())

    async def _run_with_id():
        with TRIAGE_DURATION.time():
            try:
                from orchestrator.graph import TRIAGE_GRAPH, TriageState
                initial: TriageState = {
                    "triage_id":           triage_id,
                    "alert_description":   alert_description,
                    "service":             service,
                    "alert_type":          "",
                    "agents_to_run":       [],
                    "log_findings":        None,
                    "metrics_findings":    None,
                    "deployment_findings": None,
                    "diagnosis":           None,
                    "error":               None,
                }
                await TRIAGE_GRAPH.ainvoke(initial)
                TRIAGE_TOTAL.labels(status="completed").inc()
            except Exception as exc:
                log.exception("triage_failed", triage_id=triage_id, error=str(exc))
                TRIAGE_TOTAL.labels(status="failed").inc()

    asyncio.create_task(_run_with_id())
    return Response(
        content={"triage_id": triage_id, "status": "started"},
        media_type="application/json",
        status_code=202,
    )


@get("/triage/{triage_id:str}/events")
async def triage_events(triage_id: str) -> Stream:
    async def generate():
        pubsub = _redis.pubsub()
        await pubsub.subscribe(f"triage:{triage_id}")
        try:
            async for msg in pubsub.listen():
                if msg["type"] != "message":
                    continue
                yield f"data: {msg['data']}\n\n"
                try:
                    event = json.loads(msg["data"])
                    if event.get("stage") in ("complete", "failed"):
                        break
                except (json.JSONDecodeError, AttributeError):
                    pass
        finally:
            await pubsub.unsubscribe(f"triage:{triage_id}")
            await pubsub.aclose()

    return Stream(generate(), media_type="text/event-stream")


# ── Simulation endpoint ────────────────────────────────────────────────────────

@post("/simulate/{scenario_name:str}")
async def simulate_incident(scenario_name: str) -> Response:
    scenario = SCENARIOS.get(scenario_name)
    if not scenario:
        return Response(
            content={"error": f"Unknown scenario '{scenario_name}'. Available: {list(SCENARIOS.keys())}"},
            media_type="application/json",
            status_code=400,
        )
    async with _pool.acquire() as conn:
        await inject_anomaly(conn, scenario_name)

    log.info("scenario_injected", scenario=scenario_name, service=scenario.service)
    return Response(
        content={
            "scenario":          scenario_name,
            "service":           scenario.service,
            "alert_description": scenario.alert_description,
            "message":           f"Anomaly data injected for scenario '{scenario.label}'",
        },
        media_type="application/json",
        status_code=200,
    )


# ── Agent card discovery ───────────────────────────────────────────────────────

@get("/agents")
async def list_agents() -> Response:
    return Response(content=_agent_cards, media_type="application/json")


# ── Observability ──────────────────────────────────────────────────────────────

@get("/metrics")
async def prometheus_metrics() -> Response:
    return Response(content=generate_latest(), media_type=CONTENT_TYPE_LATEST)


@get("/health")
async def health() -> dict:
    return {"status": "ok", "agent": "Orchestrator", "scenarios": list(SCENARIOS.keys())}


# ── UI ─────────────────────────────────────────────────────────────────────────

@get("/", media_type="text/html")
async def ui() -> str:
    ui_path = os.path.join(os.path.dirname(__file__), "static", "index.html")
    with open(ui_path, encoding="utf-8") as f:
        return f.read()


# ── Lifecycle ──────────────────────────────────────────────────────────────────

async def startup() -> None:
    global _pool, _redis

    _pool  = await asyncpg.create_pool(POSTGRES_DSN, min_size=2, max_size=10)
    _redis = aioredis.from_url(REDIS_URL, decode_responses=True)
    set_redis(_redis)

    # Discover agent cards (non-fatal if agents aren't up yet)
    agent_urls = {
        "LogAgent":        os.environ.get("LOG_AGENT_URL",        "http://localhost:8001"),
        "MetricsAgent":    os.environ.get("METRICS_AGENT_URL",    "http://localhost:8002"),
        "DeploymentAgent": os.environ.get("DEPLOYMENT_AGENT_URL", "http://localhost:8003"),
        "DiagnosisAgent":  os.environ.get("DIAGNOSIS_AGENT_URL",  "http://localhost:8004"),
    }
    for name, url in agent_urls.items():
        try:
            card = await discover_agent_card(url)
            _agent_cards[name] = card
            log.info("agent_card_discovered", agent=name)
        except Exception:
            log.warning("agent_card_unavailable", agent=name, url=url)
            _agent_cards[name] = {"name": name, "url": url, "status": "unavailable"}

    log.info("orchestrator_started", port=PORT)


async def shutdown() -> None:
    await _pool.close()
    await _redis.aclose()


app = Litestar(
    route_handlers=[start_triage, triage_events, simulate_incident, list_agents,
                    prometheus_metrics, health, ui],
    on_startup=[startup],
    on_shutdown=[shutdown],
)
