from __future__ import annotations

import pytest

from metrics_agent.analyzer import _THRESHOLDS, analyze_metrics
from tests.conftest import make_conn


class TestThresholds:
    @pytest.mark.parametrize("metric,value,expected", [
        ("cpu_percent",    95.0, "critical"),
        ("cpu_percent",    75.0, "warning"),
        ("cpu_percent",    50.0, "ok"),
        ("memory_percent", 92.0, "critical"),
        ("memory_percent", 80.0, "warning"),
        ("memory_percent", 60.0, "ok"),
        ("error_rate",     25.0, "critical"),
        ("error_rate",      6.0, "warning"),
        ("error_rate",      2.0, "ok"),
        ("latency_p95_ms", 1600, "critical"),
        ("latency_p95_ms",  600, "warning"),
        ("latency_p95_ms",  200, "ok"),
        ("db_connections",  96.0, "critical"),
        ("db_connections",  82.0, "warning"),
        ("db_connections",  50.0, "ok"),
    ])
    def test_threshold_classification(self, metric, value, expected):
        thresh = _THRESHOLDS[metric]
        if value >= thresh["critical"]:
            severity = "critical"
        elif value >= thresh["warn"]:
            severity = "warning"
        else:
            severity = "ok"
        assert severity == expected

    def test_all_metrics_have_warn_and_critical(self):
        for metric, thresholds in _THRESHOLDS.items():
            assert "warn" in thresholds, f"{metric} missing 'warn'"
            assert "critical" in thresholds, f"{metric} missing 'critical'"
            assert thresholds["critical"] > thresholds["warn"], (
                f"{metric}: critical must be > warn"
            )


class TestAnalyzeMetrics:
    def _make_metric_row(self, name, avg, maximum, minimum, stddev=1.0, samples=10):
        return {
            "metric_name": name,
            "avg_val": avg,
            "max_val": maximum,
            "min_val": minimum,
            "samples": samples,
            "stddev": stddev,
        }

    def _make_baseline_row(self, name, baseline):
        return {"metric_name": name, "baseline_avg": baseline}

    async def test_empty_metrics_returns_no_anomalies(self):
        conn = make_conn(fetch_results=[], fetchrow_result=None)
        conn.fetch.return_value = []
        result = await analyze_metrics(conn, "user-service", window_minutes=15)
        assert result["anomalies"] == []
        assert result["anomalous"] is False
        assert result["worst_severity"] == "ok"

    async def test_critical_memory_detected(self):
        from tests.conftest import make_records
        current_rows = make_records(self._make_metric_row("memory_percent", 92.0, 94.0, 85.0))
        baseline_rows = make_records(self._make_baseline_row("memory_percent", 47.0))

        conn = make_conn()
        conn.fetch.side_effect = [current_rows, baseline_rows]

        result = await analyze_metrics(conn, "user-service", window_minutes=15)
        assert result["anomalous"] is True
        assert result["worst_severity"] == "critical"
        assert any(a["metric"] == "memory_percent" for a in result["anomalies"])

    async def test_normal_metrics_no_anomalies(self):
        from tests.conftest import make_records
        current_rows = make_records(
            self._make_metric_row("cpu_percent", 30.0, 35.0, 25.0),
            self._make_metric_row("memory_percent", 45.0, 50.0, 40.0),
        )
        baseline_rows = make_records(
            self._make_baseline_row("cpu_percent", 28.0),
            self._make_baseline_row("memory_percent", 44.0),
        )
        conn = make_conn()
        conn.fetch.side_effect = [current_rows, baseline_rows]

        result = await analyze_metrics(conn, "user-service")
        assert result["anomalous"] is False
        assert result["worst_severity"] == "ok"

    async def test_anomalies_sorted_critical_first(self):
        from tests.conftest import make_records
        current_rows = make_records(
            self._make_metric_row("cpu_percent",    92.0, 94.0, 85.0),
            self._make_metric_row("latency_p95_ms", 600,  620,  500),
        )
        baseline_rows = make_records(
            self._make_baseline_row("cpu_percent",    28.0),
            self._make_baseline_row("latency_p95_ms", 80.0),
        )
        conn = make_conn()
        conn.fetch.side_effect = [current_rows, baseline_rows]

        result = await analyze_metrics(conn, "user-service")
        severities = [a["severity"] for a in result["anomalies"]]
        assert severities[0] == "critical"

    async def test_large_pct_change_flags_anomaly(self):
        from tests.conftest import make_records
        # error_rate goes from 0.5 to 2.0 — 300% change, but below warn threshold of 5.0
        current_rows = make_records(self._make_metric_row("error_rate", 2.0, 2.5, 1.5))
        baseline_rows = make_records(self._make_baseline_row("error_rate", 0.5))
        conn = make_conn()
        conn.fetch.side_effect = [current_rows, baseline_rows]

        result = await analyze_metrics(conn, "user-service")
        # 300% change > 50% threshold in code
        assert result["anomalous"] is True
