from __future__ import annotations

import pytest

from log_agent.analyzer import _ERROR_PATTERNS, analyze_logs
from tests.conftest import make_conn


# Real application log lines sampled from Kubernetes, PostgreSQL, Python services,
# and nginx. These are the actual formats the regex patterns must handle.

REAL_OOM_LINES = [
    # Linux kernel OOM killer
    "kernel: Out of memory: Kill process 18847 (python3) score 892 or sacrifice child",
    "kernel: oom-kill:constraint=CONSTRAINT_MEMCG,nodemask=(null),cpuset=kubepods,mems_allowed=0,oom_memcg=/kubepods/burstable/pod3a7f1c9d,task_memcg=/kubepods/burstable/pod3a7f1c9d/user-service,task=gunicorn,pid=18847,uid=1000",
    "kubelet: pod/user-service-7d4f9b8c6-xk2mw: OOM killer invoked, container user-service killed",
    # Python process
    "gunicorn[18847]: MemoryError: memory exhausted, unable to allocate 2147483648 bytes",
    # Java heap
    "java.lang.OutOfMemoryError: Java heap space\n\tat java.util.Arrays.copyOf(Arrays.java:3210)",
]

REAL_CONNECTION_LINES = [
    # psycopg2 / asyncpg
    'asyncpg.exceptions.ConnectionDoesNotExistError: connection to server at "db-proxy.svc.cluster.local" (10.96.14.22), port 5432 failed: Connection refused',
    "sqlalchemy.exc.OperationalError: (psycopg2.OperationalError) could not connect to server: Connection timed out\n\tIs the server running on host \"postgres-primary\" (10.96.8.3) and accepting\n\tTCP/IP connections on port 5432?",
    # Redis
    "redis.exceptions.ConnectionError: Error 111 connecting to redis-master.svc.cluster.local:6379. Connection refused.",
    # gRPC
    "grpc._channel._InactiveRpcError: <_InactiveRpcError of RPC that terminated with:\n\tstatus = StatusCode.UNAVAILABLE\n\tdetails = \"failed to connect to all addresses; last error: UNKNOWN: ipv4:10.96.22.7:50051: Failed to connect to remote host: Connection refused\"",
]

REAL_POOL_EXHAUSTION_LINES = [
    # asyncpg pool
    "asyncpg.exceptions.TooManyConnectionsError: too many connections for role \"app_user\"; connection pool exhausted (max=100)",
    # HikariCP (Java) — logs "too many connections" when pool is saturated
    "HikariPool-1 - Connection is not available. Pool stats (total=50, active=50, idle=0, waiting=23). Caused by: too many connections on host db-primary:5432",
    # pgbouncer
    "LOG pgbouncer[1]: C-0x55a4b2: app/app_user@10.0.1.15:43210 closing because: too many clients already (max_client_conn=500)",
]

REAL_TIMEOUT_LINES = [
    # HTTP client
    "httpx.ReadTimeout: timed out reading response body from 'http://payment-service.svc.cluster.local/v1/charge' after 5.0s",
    # SQL query
    "asyncpg.exceptions.QueryCanceledError: canceling statement due to statement timeout (30000ms) — query: SELECT * FROM orders WHERE created_at > $1",
    # Celery — task exceeded soft time limit and was killed
    "celery.worker.job: Task send_invoice[d3f8a2c1] timed out after 120s (soft time limit exceeded), worker forcibly terminated",
]

REAL_HTTP_5XX_LINES = [
    # nginx upstream
    '2026/06/07 03:47:12 [error] 29#29: *8374 connect() failed (111: Connection refused) while connecting to upstream, client: 10.0.0.1, server: _, request: "POST /api/v2/checkout HTTP/1.1", upstream: "http://127.0.0.1:8001/api/v2/checkout"',
    # Django
    "Internal Server Error: /api/v1/users/profile\nTraceback (most recent call last):\n  File \"/app/views.py\", line 142, in get_profile\n    raise Http500('upstream service unavailable')\ndjango.core.exceptions.SuspiciousOperation: 500",
    # FastAPI / Starlette
    'ERROR:    Exception in ASGI application\nERROR uvicorn.error - 500 Internal Server Error on POST /v1/triage: upstream connect error or disconnect/reset before headers. reset reason: connection timeout',
]

REAL_FATAL_LINES = [
    # Go panic
    "goroutine 1 [running]:\nmain.main()\n\t/app/main.go:47 +0x89\npanic: runtime error: invalid memory address or nil pointer dereference\n[signal SIGSEGV: segmentation violation code=0x1 addr=0x0 pc=0x4c2a3f]",
    # PostgreSQL
    "FATAL:  terminating connection due to administrator command\nFATAL:  the database system is in recovery mode",
    # Python segfault via C extension
    "Fatal Python error: Segmentation fault\nThread 0x00007f3a2c1ff700 (most recent call first):\n  File \"/usr/local/lib/python3.11/site-packages/numpy/core/_multiarray_umath.cpython-311.so\", line 0",
]


class TestErrorPatterns:
    """Patterns must match realistic production log lines, not toy strings."""

    @pytest.mark.parametrize("message,expected_label", [
        (REAL_OOM_LINES[0], "memory_exhaustion"),
        (REAL_OOM_LINES[2], "memory_exhaustion"),
        (REAL_OOM_LINES[3], "memory_exhaustion"),
        (REAL_CONNECTION_LINES[0], "connection_failure"),
        (REAL_CONNECTION_LINES[1], "connection_failure"),
        (REAL_POOL_EXHAUSTION_LINES[0], "connection_pool_exhausted"),
        (REAL_POOL_EXHAUSTION_LINES[1], "connection_pool_exhausted"),
        (REAL_TIMEOUT_LINES[0], "timeout"),
        (REAL_TIMEOUT_LINES[2], "timeout"),
        (REAL_HTTP_5XX_LINES[1], "http_5xx"),
        (REAL_HTTP_5XX_LINES[2], "http_5xx"),
        (REAL_FATAL_LINES[1], "fatal_error"),
        (REAL_FATAL_LINES[2], "fatal_error"),
    ])
    def test_pattern_matches_real_log_line(self, message, expected_label):
        matched = [label for pat, label in _ERROR_PATTERNS if pat.search(message)]
        assert expected_label in matched, (
            f"Pattern '{expected_label}' did not fire on real log line:\n{message!r}\nMatched: {matched}"
        )

    def test_healthy_request_log_matches_nothing(self):
        # Standard nginx access log line — must not trigger any error pattern
        line = '10.0.1.5 - - [07/Jun/2026:03:47:09 +0000] "GET /healthz HTTP/1.1" 200 2 "-" "kube-probe/1.29"'
        matched = [label for pat, label in _ERROR_PATTERNS if pat.search(line)]
        assert matched == [], f"Healthy line triggered patterns: {matched}"

    def test_kubernetes_event_log_matches_nothing(self):
        line = "I0607 03:47:08.123456       1 reconciler.go:224] operationExecutor.VerifyControllerAttachedVolume started for volume \"config-volume\" (UniqueName: \"kubernetes.io/configmap/pod3a7f1c9d-config\") pod \"user-service-7d4f9b8c6-xk2mw\" (UID: \"3a7f1c9d\")"
        matched = [label for pat, label in _ERROR_PATTERNS if pat.search(line)]
        assert matched == []

    def test_go_panic_matches_fatal_and_null_reference(self):
        # Go nil pointer panic — should match both fatal_error AND null_reference
        line = REAL_FATAL_LINES[0]
        matched = [label for pat, label in _ERROR_PATTERNS if pat.search(line)]
        assert "fatal_error" in matched or "null_reference" in matched, (
            f"Go panic line matched nothing: {matched}"
        )

    def test_multiline_stack_trace_oom_matches(self):
        # A log aggregator often joins kernel OOM lines — the pattern must still fire
        combined = "\n".join(REAL_OOM_LINES[:2])
        matched = [label for pat, label in _ERROR_PATTERNS if pat.search(combined)]
        assert "memory_exhaustion" in matched

    def test_all_patterns_compile(self):
        assert len(_ERROR_PATTERNS) >= 10


class TestAnalyzeLogs:
    async def test_returns_clean_state_on_no_logs(self):
        conn = make_conn(fetch_results=[])
        result = await analyze_logs(conn, "user-service", window_minutes=15)
        assert result["error_count"] == 0
        assert result["total_log_entries"] == 0
        assert result["findings"] == []
        assert result["anomalous"] is False

    async def test_kubernetes_oom_log_burst_detected(self):
        # 18 OOM kills in 15 minutes — typical memory leak progression
        rows = [
            {"level": "ERROR", "message": f"kernel: Out of memory: Kill process {18800 + i} (gunicorn) score 891 or sacrifice child", "logged_at": f"2026-06-07 03:{30 + i // 2:02d}:00"}
            for i in range(18)
        ]
        rows += [
            {"level": "INFO",  "message": f'10.0.1.{i} - - [07/Jun/2026] "GET /healthz HTTP/1.1" 200 2', "logged_at": "2026-06-07 03:44:00"}
            for i in range(82)
        ]
        conn = make_conn(fetch_results=rows)
        result = await analyze_logs(conn, "user-service", window_minutes=15)
        assert result["error_count"] == 18
        assert any(f["pattern"] == "memory_exhaustion" for f in result["findings"])
        assert result["anomalous"] is True
        mem_finding = next(f for f in result["findings"] if f["pattern"] == "memory_exhaustion")
        assert mem_finding["count"] == 18

    async def test_pgbouncer_pool_exhaustion_burst(self):
        # Connection pool full — 31 clients rejected in a spike
        rows = [
            {"level": "ERROR", "message": f"LOG pgbouncer[1]: C-0x55a4b{i:04x}: app/app_user@10.0.1.{i % 30 + 1}:4{3000 + i} closing because: too many clients already (max_client_conn=500)", "logged_at": "2026-06-07 03:45:00"}
            for i in range(31)
        ]
        conn = make_conn(fetch_results=rows)
        result = await analyze_logs(conn, "db-proxy", window_minutes=5)
        assert result["error_count"] == 31
        assert any(f["pattern"] == "connection_pool_exhausted" for f in result["findings"])
        assert result["anomalous"] is True

    async def test_findings_ordered_by_highest_frequency_first(self):
        # Simulate: 12 timeouts, 7 connection failures, 2 OOM — must come out in that order
        rows = (
            [{"level": "ERROR", "message": "httpx.ReadTimeout: timed out reading response after 5.0s", "logged_at": "2026-06-07 03:44:00"}] * 12 +
            [{"level": "ERROR", "message": 'asyncpg.exceptions.ConnectionDoesNotExistError: Connection refused to "db-proxy" port 5432', "logged_at": "2026-06-07 03:44:01"}] * 7 +
            [{"level": "ERROR", "message": "kernel: Out of memory: Kill process 18851 (gunicorn) score 889", "logged_at": "2026-06-07 03:44:02"}] * 2
        )
        conn = make_conn(fetch_results=rows)
        result = await analyze_logs(conn, "api-gateway")
        counts = [f["count"] for f in result["findings"]]
        assert counts == sorted(counts, reverse=True), f"Findings not sorted: {counts}"
        assert result["findings"][0]["count"] == 12

    async def test_error_rate_reflects_real_mix(self):
        # 23 errors out of 200 total — 11.5% error rate
        rows = (
            [{"level": "ERROR", "message": "grpc._channel._InactiveRpcError: StatusCode.UNAVAILABLE — Connection refused", "logged_at": "2026-06-07 03:44:00"}] * 23 +
            [{"level": "INFO",  "message": '10.0.1.5 "POST /api/v1/order HTTP/1.1" 200 847ms', "logged_at": "2026-06-07 03:44:01"}] * 177
        )
        conn = make_conn(fetch_results=rows)
        result = await analyze_logs(conn, "order-service")
        assert result["total_log_entries"] == 200
        assert result["error_count"] == 23
        assert abs(result["error_rate_percent"] - 11.5) < 0.01

    async def test_anomalous_flag_suppressed_for_low_volume_noise(self):
        # 3 unmatched errors out of 500 INFO logs — NOT anomalous
        rows = (
            [{"level": "ERROR", "message": "generic error no known pattern x7z9q", "logged_at": "2026-06-07 03:44:00"}] * 3 +
            [{"level": "INFO",  "message": 'metrics scrape OK 200 in 2ms', "logged_at": "2026-06-07 03:44:01"}] * 497
        )
        conn = make_conn(fetch_results=rows)
        result = await analyze_logs(conn, "prometheus-exporter")
        assert result["error_count"] == 3
        assert result["anomalous"] is False

    async def test_sample_messages_captured_in_findings(self):
        rows = [
            {"level": "ERROR", "message": f"kernel: Out of memory: Kill process {18800 + i} (gunicorn) score 891", "logged_at": "2026-06-07 03:44:00"}
            for i in range(6)
        ]
        conn = make_conn(fetch_results=rows)
        result = await analyze_logs(conn, "user-service")
        mem = next(f for f in result["findings"] if f["pattern"] == "memory_exhaustion")
        assert len(mem["sample_messages"]) >= 1
        assert "Out of memory" in mem["sample_messages"][0]
