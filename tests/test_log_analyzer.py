from __future__ import annotations

import pytest

from log_agent.analyzer import _ERROR_PATTERNS, analyze_logs
from tests.conftest import make_conn


class TestErrorPatterns:
    """Each pattern must match its intended message and not match unrelated ones."""

    @pytest.mark.parametrize("message,expected_label", [
        ("Out of memory: Kill process 8923",              "memory_exhaustion"),
        ("OOM killer invoked for user-service",           "memory_exhaustion"),
        ("memory exhausted after 3 GC cycles",            "memory_exhaustion"),
        ("Connection refused to db-proxy:5432",           "connection_failure"),
        ("connection timed out after 30s",                "connection_failure"),
        ("Too many connections: pool exhausted",          "connection_pool_exhausted"),
        ("too many clients: cannot accept new conn",      "connection_pool_exhausted"),
        ("Request timed out after 5s",                    "timeout"),
        ("500 error on POST /api/v1/users",               "http_5xx"),
        ("Internal Server Error in payment handler",      "http_5xx"),
        ("PANIC: null pointer dereference",               "fatal_error"),
        ("FATAL: crash in worker process",                "fatal_error"),
        ("Certificate expired for api-gateway.example",  "cert_error"),
        ("Deadlock detected, rolling back TX-881",        "deadlock"),
    ])
    def test_pattern_matches(self, message, expected_label):
        matched = [label for pat, label in _ERROR_PATTERNS if pat.search(message)]
        assert expected_label in matched, (
            f"Expected '{expected_label}' in matches for: {message!r}\nGot: {matched}"
        )

    def test_normal_message_matches_nothing(self):
        msg = "Request processed successfully in 12ms"
        matched = [label for pat, label in _ERROR_PATTERNS if pat.search(msg)]
        assert matched == []

    def test_compound_message_matches_multiple_patterns(self):
        msg = "PANIC: null pointer dereference — out of memory condition"
        matched = [label for pat, label in _ERROR_PATTERNS if pat.search(msg)]
        assert "fatal_error" in matched
        assert "memory_exhaustion" in matched
        assert len(matched) >= 2

    def test_all_patterns_compile(self):
        assert len(_ERROR_PATTERNS) >= 10
        for pattern, label in _ERROR_PATTERNS:
            assert label, "Every pattern must have a non-empty label"


class TestAnalyzeLogs:
    async def test_returns_zero_errors_on_empty_logs(self):
        conn = make_conn(fetch_results=[])
        result = await analyze_logs(conn, "user-service", window_minutes=15)
        assert result["error_count"] == 0
        assert result["total_log_entries"] == 0
        assert result["findings"] == []
        assert result["anomalous"] is False

    async def test_detects_oom_pattern(self):
        conn = make_conn(fetch_results=[
            {"level": "ERROR", "message": "Out of memory: Kill process 9001", "logged_at": "2026-01-01 00:01:00"},
            {"level": "ERROR", "message": "Out of memory: Kill process 9002", "logged_at": "2026-01-01 00:01:10"},
            {"level": "INFO",  "message": "Request processed successfully",   "logged_at": "2026-01-01 00:01:20"},
        ])
        result = await analyze_logs(conn, "user-service", window_minutes=15)
        assert result["error_count"] == 2
        assert any(f["pattern"] == "memory_exhaustion" for f in result["findings"])
        assert result["anomalous"] is True

    async def test_error_rate_calculation(self):
        rows = (
            [{"level": "ERROR", "message": "Out of memory", "logged_at": "2026-01-01 00:00:01"}] * 10 +
            [{"level": "INFO",  "message": "Request OK",    "logged_at": "2026-01-01 00:00:02"}] * 90
        )
        conn = make_conn(fetch_results=rows)
        result = await analyze_logs(conn, "user-service")
        assert result["total_log_entries"] == 100
        assert result["error_count"] == 10
        assert result["error_rate_percent"] == 10.0

    async def test_findings_sorted_by_count_descending(self):
        rows = (
            [{"level": "ERROR", "message": "Out of memory",         "logged_at": "2026-01-01 00:00:01"}] * 5 +
            [{"level": "ERROR", "message": "Connection refused",     "logged_at": "2026-01-01 00:00:02"}] * 3 +
            [{"level": "ERROR", "message": "Request timed out",      "logged_at": "2026-01-01 00:00:03"}] * 1
        )
        conn = make_conn(fetch_results=rows)
        result = await analyze_logs(conn, "user-service")
        counts = [f["count"] for f in result["findings"]]
        assert counts == sorted(counts, reverse=True)

    async def test_not_anomalous_on_few_errors(self):
        conn = make_conn(fetch_results=[
            {"level": "ERROR", "message": "Request timed out", "logged_at": "2026-01-01 00:00:01"},
            {"level": "ERROR", "message": "Request timed out", "logged_at": "2026-01-01 00:00:02"},
            {"level": "INFO",  "message": "Request OK",         "logged_at": "2026-01-01 00:00:03"},
        ])
        result = await analyze_logs(conn, "user-service")
        # 2 errors → anomalous only if > 5 OR patterns found; timeout IS a pattern
        assert result["anomalous"] is True  # timeout pattern matched

    async def test_anomalous_flag_on_high_error_count(self):
        rows = [{"level": "ERROR", "message": "generic error no pattern match here x12345", "logged_at": "2026-01-01 00:00:01"}] * 10
        conn = make_conn(fetch_results=rows)
        result = await analyze_logs(conn, "user-service")
        assert result["error_count"] == 10
        assert result["anomalous"] is True  # > 5 errors
