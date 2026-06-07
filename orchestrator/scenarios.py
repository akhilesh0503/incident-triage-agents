from __future__ import annotations

from dataclasses import dataclass
from typing import Any

import asyncpg


@dataclass
class Scenario:
    name: str
    label: str
    description: str
    service: str
    alert_description: str
    icon: str


SCENARIOS: dict[str, Scenario] = {
    "memory_leak": Scenario(
        name="memory_leak",
        label="Memory Leak",
        description="user-service memory climbs to 94%, OOM kills cascading",
        service="user-service",
        alert_description="CRITICAL: user-service memory utilization at 94% and rising. OOM killer activated 31 times in the last 10 minutes.",
        icon="🧠",
    ),
    "failed_deployment": Scenario(
        name="failed_deployment",
        label="Failed Deployment",
        description="payment-service v3.1.0 deploy failed, 500s on all endpoints",
        service="payment-service",
        alert_description="ALERT: payment-service returning HTTP 500 on all endpoints. Deployment v3.1.0 was pushed 20 minutes ago.",
        icon="🚨",
    ),
    "high_latency": Scenario(
        name="high_latency",
        label="High Latency",
        description="api-gateway p95 latency spiked to 1.8s from 80ms baseline",
        service="api-gateway",
        alert_description="WARNING: api-gateway p95 latency degraded to 1800ms (baseline: 80ms). SLA breach imminent.",
        icon="⏱️",
    ),
    "database_overload": Scenario(
        name="database_overload",
        label="DB Overload",
        description="db-proxy connection pool exhausted, 95% of slots occupied",
        service="db-proxy",
        alert_description="CRITICAL: db-proxy connection pool at 95% capacity. New connections being refused. Multiple services affected.",
        icon="🗄️",
    ),
    "cpu_spike": Scenario(
        name="cpu_spike",
        label="CPU Spike",
        description="auth-service CPU at 93%, token validation grinding to halt",
        service="auth-service",
        alert_description="WARNING: auth-service CPU utilization sustained at 93% for 8 minutes. Token validation latency increasing.",
        icon="🔥",
    ),
}


async def inject_anomaly(conn: asyncpg.Connection, scenario_name: str) -> None:
    """Insert anomalous metrics/logs/deployments to make the scenario detectable."""
    if scenario_name == "memory_leak":
        await _inject_memory_leak(conn, "user-service")
    elif scenario_name == "failed_deployment":
        await _inject_failed_deployment(conn, "payment-service")
    elif scenario_name == "high_latency":
        await _inject_high_latency(conn, "api-gateway")
    elif scenario_name == "database_overload":
        await _inject_database_overload(conn, "db-proxy")
    elif scenario_name == "cpu_spike":
        await _inject_cpu_spike(conn, "auth-service")


async def _inject_memory_leak(conn: asyncpg.Connection, service: str) -> None:
    # Rising memory — 60% at -12min climbing to 94% at -1min
    for i in range(20):
        age_seconds = (20 - i) * 30  # 600s ago → 0s ago
        memory_val = 60 + (i * 1.8)  # climbs from 60 to 94
        await conn.execute(
            "INSERT INTO metrics_snapshots (service, metric_name, value, unit, recorded_at) "
            "VALUES ($1, 'memory_percent', $2, 'percent', NOW() - ($3 * INTERVAL '1 second'))",
            service, round(memory_val, 1), age_seconds,
        )
        await conn.execute(
            "INSERT INTO metrics_snapshots (service, metric_name, value, unit, recorded_at) "
            "VALUES ($1, 'latency_p95_ms', $2, 'ms', NOW() - ($3 * INTERVAL '1 second'))",
            service, round(50 + i * 30, 1), age_seconds,
        )

    oom_messages = [
        "Out of memory: Kill process 8923 (user-svc) score 892 or sacrifice child",
        "OOM killer invoked: user-service heap at 94% — terminating worker pid 8924",
        "memory_exhausted: failed to allocate 512MB for request handler pool",
        "Out of memory error in user-service request queue, dropping 47 pending requests",
        "GC overhead limit exceeded: heap space exhausted after 3 full GC cycles",
    ]
    for i in range(30):
        msg = oom_messages[i % len(oom_messages)]
        age = (30 - i) * 20
        await conn.execute(
            "INSERT INTO logs (service, level, message, logged_at) "
            "VALUES ($1, 'ERROR', $2, NOW() - ($3 * INTERVAL '1 second'))",
            service, msg, age,
        )


async def _inject_failed_deployment(conn: asyncpg.Connection, service: str) -> None:
    await conn.execute(
        "INSERT INTO deployments (service, version, deployed_at, deployed_by, commit_sha, status, notes) "
        "VALUES ($1, 'v3.1.0', NOW() - INTERVAL '20 minutes', 'ci-bot', 'a1b2c3d4e5f6', 'failed', "
        "'Startup check failed: database migration error on table payments_v2')",
        service,
    )
    error_messages = [
        "Connection refused to db-proxy:5432 — payment-service startup aborted",
        "500 Internal Server Error: POST /api/v1/payments — service not initialized",
        "500 Internal Server Error: GET /api/v1/transactions — null pointer in PaymentHandler",
        "FATAL: database migration failed at step 3/7: column amount_usd already exists",
        "Connection timed out waiting for db-proxy after 30s during startup health check",
    ]
    for i in range(25):
        msg = error_messages[i % len(error_messages)]
        age = (25 - i) * 24
        await conn.execute(
            "INSERT INTO logs (service, level, message, logged_at) "
            "VALUES ($1, 'ERROR', $2, NOW() - ($3 * INTERVAL '1 second'))",
            service, msg, age,
        )


async def _inject_high_latency(conn: asyncpg.Connection, service: str) -> None:
    for i in range(20):
        age_seconds = (20 - i) * 30
        latency = 400 + (i * 72)  # 400ms → 1800ms
        await conn.execute(
            "INSERT INTO metrics_snapshots (service, metric_name, value, unit, recorded_at) "
            "VALUES ($1, 'latency_p95_ms', $2, 'ms', NOW() - ($3 * INTERVAL '1 second'))",
            service, round(latency, 1), age_seconds,
        )
        await conn.execute(
            "INSERT INTO metrics_snapshots (service, metric_name, value, unit, recorded_at) "
            "VALUES ($1, 'error_rate', $2, 'errors/min', NOW() - ($3 * INTERVAL '1 second'))",
            service, round(1.0 + i * 0.4, 1), age_seconds,
        )

    timeout_messages = [
        "Request timed out after 30s: upstream service db-proxy did not respond",
        "Connection timed out to auth-service after 5s during token validation",
        "HTTP 504 Gateway Timeout: upstream user-service exceeded 10s deadline",
        "Request timed out waiting for connection from pool after 5000ms",
        "Downstream timeout: payment-service health check exceeded 3s SLA",
    ]
    for i in range(20):
        msg = timeout_messages[i % len(timeout_messages)]
        age = (20 - i) * 25
        await conn.execute(
            "INSERT INTO logs (service, level, message, logged_at) "
            "VALUES ($1, $2, $3, NOW() - ($4 * INTERVAL '1 second'))",
            service, "ERROR" if i % 3 == 0 else "WARN", msg, age,
        )


async def _inject_database_overload(conn: asyncpg.Connection, service: str) -> None:
    for i in range(20):
        age_seconds = (20 - i) * 30
        db_conns = 70 + (i * 1.4)  # 70 → 96%
        await conn.execute(
            "INSERT INTO metrics_snapshots (service, metric_name, value, unit, recorded_at) "
            "VALUES ($1, 'db_connections', $2, 'count', NOW() - ($3 * INTERVAL '1 second'))",
            service, round(db_conns, 1), age_seconds,
        )
        await conn.execute(
            "INSERT INTO metrics_snapshots (service, metric_name, value, unit, recorded_at) "
            "VALUES ($1, 'error_rate', $2, 'errors/min', NOW() - ($3 * INTERVAL '1 second'))",
            service, round(0.5 + i * 1.2, 1), age_seconds,
        )

    pool_messages = [
        "Too many connections: pool exhausted (max=100, active=97, waiting=43)",
        "Connection refused: db-proxy pool at capacity, rejecting new client",
        "Deadlock detected between transaction TX-881 and TX-882, rolling back TX-882",
        "Too many clients: cannot accept new connection from user-service (limit=100)",
        "Connection pool exhausted: all 100 slots occupied, 51 requests queuing",
    ]
    for i in range(25):
        msg = pool_messages[i % len(pool_messages)]
        age = (25 - i) * 20
        await conn.execute(
            "INSERT INTO logs (service, level, message, logged_at) "
            "VALUES ($1, 'ERROR', $2, NOW() - ($3 * INTERVAL '1 second'))",
            service, msg, age,
        )


async def _inject_cpu_spike(conn: asyncpg.Connection, service: str) -> None:
    for i in range(20):
        age_seconds = (20 - i) * 30
        cpu = 60 + (i * 1.75)  # 60 → 95%
        await conn.execute(
            "INSERT INTO metrics_snapshots (service, metric_name, value, unit, recorded_at) "
            "VALUES ($1, 'cpu_percent', $2, 'percent', NOW() - ($3 * INTERVAL '1 second'))",
            service, round(cpu, 1), age_seconds,
        )
        await conn.execute(
            "INSERT INTO metrics_snapshots (service, metric_name, value, unit, recorded_at) "
            "VALUES ($1, 'latency_p95_ms', $2, 'ms', NOW() - ($3 * INTERVAL '1 second'))",
            service, round(120 + i * 60, 1), age_seconds,
        )

    cpu_messages = [
        "Request timed out: token validation exceeded 5000ms CPU budget",
        "WARN: JWT signature verification taking >2000ms — possible RSA key size issue",
        "Thread pool saturation: all 32 worker threads occupied with crypto operations",
        "WARN: bcrypt hashing taking 3200ms per request — cost factor may be too high",
        "Request timed out: auth-service CPU throttled, validation queue depth=847",
    ]
    for i in range(15):
        msg = cpu_messages[i % len(cpu_messages)]
        age = (15 - i) * 30
        await conn.execute(
            "INSERT INTO logs (service, level, message, logged_at) "
            "VALUES ($1, $2, $3, NOW() - ($4 * INTERVAL '1 second'))",
            service, "WARN" if i % 2 == 0 else "ERROR", msg, age,
        )
