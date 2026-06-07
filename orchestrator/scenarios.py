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
    "disk_full": Scenario(
        name="disk_full",
        label="Disk Full",
        description="order-service disk at 97%, write operations failing",
        service="order-service",
        alert_description="CRITICAL: order-service disk utilization at 97%. Write operations failing. Order creation and invoice generation blocked.",
        icon="💾",
    ),
    "cert_expiry": Scenario(
        name="cert_expiry",
        label="Cert Expiry",
        description="api-gateway TLS certificate expired, all HTTPS requests failing",
        service="api-gateway",
        alert_description="ALERT: api-gateway TLS certificate expired 2 hours ago. All inbound HTTPS connections returning SSL handshake errors. Mobile and web clients unable to reach API.",
        icon="🔐",
    ),
    "service_crash": Scenario(
        name="service_crash",
        label="Service Crash",
        description="checkout-service CrashLoopBackOff after v2.4.0 deploy",
        service="checkout-service",
        alert_description="CRITICAL: checkout-service pods in CrashLoopBackOff — 23 restarts in 15 minutes. Deployment v2.4.0 rolled out 45 minutes ago.",
        icon="💥",
    ),
    "db_deadlock": Scenario(
        name="db_deadlock",
        label="DB Deadlock",
        description="transaction-service: 45 deadlocks/min, connection pool at 89%",
        service="transaction-service",
        alert_description="CRITICAL: transaction-service reporting 45 database deadlocks per minute. Connection pool at 89% capacity. Payment transactions rolling back.",
        icon="🔒",
    ),
    "rollback_incident": Scenario(
        name="rollback_incident",
        label="Rollback",
        description="inventory-service v2.8.0 auto-rolled-back, errors persisting",
        service="inventory-service",
        alert_description="ALERT: inventory-service deployment v2.8.0 was automatically rolled back 10 minutes ago. HTTP 500s on stock-check endpoint continuing despite rollback.",
        icon="↩️",
    ),
    "traffic_spike": Scenario(
        name="traffic_spike",
        label="Traffic Spike",
        description="recommendation-service CPU 94%, latency 1800ms from marketing event",
        service="recommendation-service",
        alert_description="WARNING: recommendation-service CPU at 94%, p95 latency degraded to 1800ms. Spike coincides with email marketing campaign sending 2M emails.",
        icon="📈",
    ),
    "connection_storm": Scenario(
        name="connection_storm",
        label="Conn Storm",
        description="notification-service: 200 connection failures to smtp-relay",
        service="notification-service",
        alert_description="WARN: notification-service unable to connect to smtp-relay and sms-gateway. 200 connection failures in the last 5 minutes. Alert delivery pipeline blocked.",
        icon="🌩️",
    ),
    "gradual_degradation": Scenario(
        name="gradual_degradation",
        label="Gradual Leak",
        description="cache-service memory at 78% and climbing over 6 hours",
        service="cache-service",
        alert_description="WARNING: cache-service memory at 78% and climbing steadily over the last 6 hours. Pattern is consistent with a memory leak. Not yet critical but trending toward OOM.",
        icon="🐌",
    ),
    "null_pointer_storm": Scenario(
        name="null_pointer_storm",
        label="NPE Storm",
        description="product-service: 89 NullPointerExceptions in 5 minutes",
        service="product-service",
        alert_description="ERROR: product-service throwing NullPointerException on product catalog lookup. 89 errors in 5 minutes. Product pages returning 500 for 30% of requests.",
        icon="⚠️",
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
    elif scenario_name == "disk_full":
        await _inject_disk_full(conn, "order-service")
    elif scenario_name == "cert_expiry":
        await _inject_cert_expiry(conn, "api-gateway")
    elif scenario_name == "service_crash":
        await _inject_service_crash(conn, "checkout-service")
    elif scenario_name == "db_deadlock":
        await _inject_db_deadlock(conn, "transaction-service")
    elif scenario_name == "rollback_incident":
        await _inject_rollback_incident(conn, "inventory-service")
    elif scenario_name == "traffic_spike":
        await _inject_traffic_spike(conn, "recommendation-service")
    elif scenario_name == "connection_storm":
        await _inject_connection_storm(conn, "notification-service")
    elif scenario_name == "gradual_degradation":
        await _inject_gradual_degradation(conn, "cache-service")
    elif scenario_name == "null_pointer_storm":
        await _inject_null_pointer_storm(conn, "product-service")


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


async def _inject_disk_full(conn: asyncpg.Connection, service: str) -> None:
    # error_rate spikes as write operations start failing
    for i in range(18):
        age_seconds = (18 - i) * 30
        await conn.execute(
            "INSERT INTO metrics_snapshots (service, metric_name, value, unit, recorded_at) "
            "VALUES ($1, 'error_rate', $2, 'errors/min', NOW() - ($3 * INTERVAL '1 second'))",
            service, round(0.2 + i * 1.3, 1), age_seconds,
        )
    disk_messages = [
        "disk full: no space left on device — /var/lib/order-service/data (97% used)",
        "write failed: disk quota exceeded writing to /data/invoices/2026/06/07",
        "IOError: [Errno 28] No space left on device: '/var/log/order-service/app.log'",
        "FATAL: cannot write WAL segment — disk full on /var/lib/postgresql/data",
        "disk full: failed to flush write-ahead log, database integrity at risk",
    ]
    for i in range(22):
        msg = disk_messages[i % len(disk_messages)]
        age = (22 - i) * 22
        await conn.execute(
            "INSERT INTO logs (service, level, message, logged_at) "
            "VALUES ($1, 'ERROR', $2, NOW() - ($3 * INTERVAL '1 second'))",
            service, msg, age,
        )


async def _inject_cert_expiry(conn: asyncpg.Connection, service: str) -> None:
    # High error_rate from SSL handshake failures
    for i in range(15):
        age_seconds = (15 - i) * 30
        await conn.execute(
            "INSERT INTO metrics_snapshots (service, metric_name, value, unit, recorded_at) "
            "VALUES ($1, 'error_rate', $2, 'errors/min', NOW() - ($3 * INTERVAL '1 second'))",
            service, round(15 + i * 2.1, 1), age_seconds,
        )
    cert_messages = [
        "certificate expired: SSL certificate for api-gateway.prod.example.com expired 2026-06-07T01:00:00Z",
        "TLS handshake failed: certificate has expired (notAfter=2026-06-07T01:00:00Z)",
        "500 Internal Server Error: upstream SSL certificate verification failed for api-gateway",
        "certificate error: peer certificate cannot be verified — expired cert in chain",
        "500 error on POST /api/v2/checkout — upstream TLS certificate is not valid",
    ]
    for i in range(20):
        msg = cert_messages[i % len(cert_messages)]
        age = (20 - i) * 25
        await conn.execute(
            "INSERT INTO logs (service, level, message, logged_at) "
            "VALUES ($1, 'ERROR', $2, NOW() - ($3 * INTERVAL '1 second'))",
            service, msg, age,
        )


async def _inject_service_crash(conn: asyncpg.Connection, service: str) -> None:
    await conn.execute(
        "INSERT INTO deployments (service, version, deployed_at, deployed_by, commit_sha, status, notes) "
        "VALUES ($1, 'v2.4.0', NOW() - INTERVAL '45 minutes', 'github-actions', "
        "'f3a8c2e1d09b4567890abcdef1234567890ab00', 'failed', "
        "'Pod CrashLoopBackOff on startup — SIGSEGV in native library libcheckout.so')",
        service,
    )
    crash_messages = [
        "FATAL: segmentation fault (core dumped) in libcheckout.so — null pointer in CartSerializer::serialize()",
        "panic: runtime error: invalid memory address or nil pointer dereference in checkout/cart.go:142",
        "FATAL crash in worker process pid=29847 — OOM or illegal instruction, restarting",
        "kernel: checkout-service[29847]: segfault at 0 ip 00007f3a2c1ff700 sp 00007ffc3a1e2880 error 4",
        "FATAL: process exited with signal 11 (SIGSEGV) after 3s uptime — pod restarting (backoff: 10s)",
    ]
    for i in range(23):
        msg = crash_messages[i % len(crash_messages)]
        age = (23 - i) * 28
        await conn.execute(
            "INSERT INTO logs (service, level, message, logged_at) "
            "VALUES ($1, 'ERROR', $2, NOW() - ($3 * INTERVAL '1 second'))",
            service, msg, age,
        )


async def _inject_db_deadlock(conn: asyncpg.Connection, service: str) -> None:
    for i in range(20):
        age_seconds = (20 - i) * 30
        db_conns = 65 + (i * 1.25)  # 65 → 89%
        await conn.execute(
            "INSERT INTO metrics_snapshots (service, metric_name, value, unit, recorded_at) "
            "VALUES ($1, 'db_connections', $2, 'count', NOW() - ($3 * INTERVAL '1 second'))",
            service, round(db_conns, 1), age_seconds,
        )
        await conn.execute(
            "INSERT INTO metrics_snapshots (service, metric_name, value, unit, recorded_at) "
            "VALUES ($1, 'error_rate', $2, 'errors/min', NOW() - ($3 * INTERVAL '1 second'))",
            service, round(0.3 + i * 2.1, 1), age_seconds,
        )
    deadlock_messages = [
        "deadlock detected: process 47823 waits for ShareLock on transaction 3881; blocked by process 47891",
        "ERROR: deadlock detected between TX-4471 (UPDATE accounts) and TX-4472 (UPDATE ledger) — rolling back TX-4471",
        "deadlock: lock wait timeout exceeded trying to acquire row-level lock on accounts (tx_id=98234)",
        "too many connections: deadlock recovery causing connection pool exhaustion (active=89/100)",
        "deadlock detected on table transactions — 45 rollbacks in last 60 seconds",
    ]
    for i in range(28):
        msg = deadlock_messages[i % len(deadlock_messages)]
        age = (28 - i) * 18
        await conn.execute(
            "INSERT INTO logs (service, level, message, logged_at) "
            "VALUES ($1, 'ERROR', $2, NOW() - ($3 * INTERVAL '1 second'))",
            service, msg, age,
        )


async def _inject_rollback_incident(conn: asyncpg.Connection, service: str) -> None:
    await conn.execute(
        "INSERT INTO deployments (service, version, deployed_at, deployed_by, commit_sha, status, notes) "
        "VALUES ($1, 'v2.8.0', NOW() - INTERVAL '25 minutes', 'argocd-bot', "
        "'9b8a7c6d5e4f3a2b1c0d9e8f7a6b5c4d3e2f1a0b', 'rolled_back', "
        "'Auto-rollback: /healthz returned 503 for 90s post-deploy — stock-check query plan regressed')",
        service,
    )
    rollback_messages = [
        "500 Internal Server Error: GET /api/v1/stock-check — query plan regressed after schema migration",
        "500 error on POST /api/v1/reserve-stock — inventory lock table missing index (dropped in v2.8.0)",
        "500 Internal Server Error: batch stock sync failed — migration left stock_counts in inconsistent state",
        "connection timed out: stock-check query taking >30s after v2.8.0 migration dropped composite index",
        "500 Internal Server Error: /api/v1/warehouse/sync — null foreign key after data migration step 4",
    ]
    for i in range(20):
        msg = rollback_messages[i % len(rollback_messages)]
        age = (20 - i) * 26
        await conn.execute(
            "INSERT INTO logs (service, level, message, logged_at) "
            "VALUES ($1, 'ERROR', $2, NOW() - ($3 * INTERVAL '1 second'))",
            service, msg, age,
        )


async def _inject_traffic_spike(conn: asyncpg.Connection, service: str) -> None:
    # Both CPU and latency spike simultaneously — classic traffic surge pattern
    for i in range(20):
        age_seconds = (20 - i) * 30
        cpu = 55 + (i * 2.0)          # 55 → 95%
        latency = 180 + (i * 90)       # 180ms → 1980ms
        await conn.execute(
            "INSERT INTO metrics_snapshots (service, metric_name, value, unit, recorded_at) "
            "VALUES ($1, 'cpu_percent', $2, 'percent', NOW() - ($3 * INTERVAL '1 second'))",
            service, round(cpu, 1), age_seconds,
        )
        await conn.execute(
            "INSERT INTO metrics_snapshots (service, metric_name, value, unit, recorded_at) "
            "VALUES ($1, 'latency_p95_ms', $2, 'ms', NOW() - ($3 * INTERVAL '1 second'))",
            service, round(latency, 1), age_seconds,
        )
    spike_messages = [
        "Request timed out: recommendation model inference exceeded 5000ms under load (queue depth=1247)",
        "WARN: worker thread pool saturated — all 64 threads active, 847 requests queuing",
        "Request timed out: feature vector fetch from Redis exceeded 3000ms (cache pressure from traffic spike)",
        "WARN: CPU throttling detected — container CPU limit (2.0 cores) exceeded, requests being delayed",
        "timeout: collaborative filter model taking >4000ms per request at current concurrency (847 RPS)",
    ]
    for i in range(18):
        msg = spike_messages[i % len(spike_messages)]
        age = (18 - i) * 28
        await conn.execute(
            "INSERT INTO logs (service, level, message, logged_at) "
            "VALUES ($1, $2, $3, NOW() - ($4 * INTERVAL '1 second'))",
            service, "WARN" if i % 3 != 0 else "ERROR", msg, age,
        )


async def _inject_connection_storm(conn: asyncpg.Connection, service: str) -> None:
    for i in range(16):
        age_seconds = (16 - i) * 35
        await conn.execute(
            "INSERT INTO metrics_snapshots (service, metric_name, value, unit, recorded_at) "
            "VALUES ($1, 'error_rate', $2, 'errors/min', NOW() - ($3 * INTERVAL '1 second'))",
            service, round(1.0 + i * 2.4, 1), age_seconds,
        )
    conn_messages = [
        "connection refused: smtp-relay.internal:587 — max_connections=50 exceeded, notification delivery failing",
        "connection timed out to sms-gateway.prod.svc:8080 after 10s — gateway overloaded",
        "connection refused: push-notification-service:9090 — upstream connection pool exhausted",
        "connection reset by peer: smtp-relay closed connection after 0 bytes — rate limit hit (500/min)",
        "connection timed out: email delivery to smtp-relay failed after 3 retries — backlog=2847 messages",
    ]
    for i in range(24):
        msg = conn_messages[i % len(conn_messages)]
        age = (24 - i) * 20
        await conn.execute(
            "INSERT INTO logs (service, level, message, logged_at) "
            "VALUES ($1, 'ERROR', $2, NOW() - ($3 * INTERVAL '1 second'))",
            service, msg, age,
        )


async def _inject_gradual_degradation(conn: asyncpg.Connection, service: str) -> None:
    # Slow memory climb over 6 hours — reaches warning level, not yet critical
    for i in range(24):
        age_seconds = (24 - i) * 900  # 6h window, 15min intervals
        memory_val = 52 + (i * 1.08)  # 52% → 78% — warning but not critical
        await conn.execute(
            "INSERT INTO metrics_snapshots (service, metric_name, value, unit, recorded_at) "
            "VALUES ($1, 'memory_percent', $2, 'percent', NOW() - ($3 * INTERVAL '1 second'))",
            service, round(memory_val, 1), age_seconds,
        )
    # Sparse logs — early stage, not yet causing failures
    leak_messages = [
        "WARN: heap usage at 71% — object cache growing unbounded, possible reference leak in CacheManager",
        "WARN: GC pause time increasing (p99=340ms) — heap fragmentation growing, last 3 full GCs took >1s",
        "WARN: memory usage trend: +0.8% per hour over last 6h — projected OOM in ~3 hours at current rate",
    ]
    for i in range(9):
        msg = leak_messages[i % len(leak_messages)]
        age = (9 - i) * 1800
        await conn.execute(
            "INSERT INTO logs (service, level, message, logged_at) "
            "VALUES ($1, 'WARN', $2, NOW() - ($3 * INTERVAL '1 second'))",
            service, msg, age,
        )


async def _inject_null_pointer_storm(conn: asyncpg.Connection, service: str) -> None:
    for i in range(18):
        age_seconds = (18 - i) * 25
        await conn.execute(
            "INSERT INTO metrics_snapshots (service, metric_name, value, unit, recorded_at) "
            "VALUES ($1, 'error_rate', $2, 'errors/min', NOW() - ($3 * INTERVAL '1 second'))",
            service, round(0.5 + i * 4.7, 1), age_seconds,
        )
        await conn.execute(
            "INSERT INTO metrics_snapshots (service, metric_name, value, unit, recorded_at) "
            "VALUES ($1, 'latency_p95_ms', $2, 'ms', NOW() - ($3 * INTERVAL '1 second'))",
            service, round(95 + i * 38, 1), age_seconds,
        )
    npe_messages = [
        "java.lang.NullPointerException: Cannot invoke \"Product.getVariants()\" because \"product\" is null\n\tat com.example.ProductService.lookupVariants(ProductService.java:247)",
        "AttributeError: 'NoneType' object has no attribute 'sku' in product_catalog.py:183 — product not found in cache",
        "NullPointerException in ProductCatalogHandler.buildResponse() — missing variant data for product_id=null after cache miss",
        "null pointer dereference: product.getCategory() returned null for product_id=38471 — category deleted without cascade",
        "AttributeError: 'NoneType' object has no attribute 'price' — pricing service returned null for SKU-38471",
    ]
    for i in range(22):
        msg = npe_messages[i % len(npe_messages)]
        age = (22 - i) * 18
        await conn.execute(
            "INSERT INTO logs (service, level, message, logged_at) "
            "VALUES ($1, 'ERROR', $2, NOW() - ($3 * INTERVAL '1 second'))",
            service, msg, age,
        )
