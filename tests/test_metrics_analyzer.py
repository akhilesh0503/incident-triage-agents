from __future__ import annotations

import pytest

from metrics_agent.analyzer import _THRESHOLDS, analyze_metrics
from tests.conftest import make_conn, make_records


# Realistic metric snapshots — values are irregular floats as they'd come from
# a Prometheus-backed aggregation, not round textbook numbers.

def _row(name, avg, maximum, minimum, stddev=None, samples=None):
    return {
        "metric_name": name,
        "avg_val":     avg,
        "max_val":     maximum,
        "min_val":     minimum,
        "samples":     samples or 60,
        "stddev":      stddev or round((maximum - minimum) / 4, 3),
    }

def _baseline(name, avg):
    return {"metric_name": name, "baseline_avg": avg}


class TestThresholds:
    def test_cpu_critical_boundary(self):
        # At exactly the critical threshold
        thresh = _THRESHOLDS["cpu_percent"]
        assert thresh["critical"] <= 90.0, "CPU critical threshold should be ≤ 90%"

    def test_memory_warning_boundary(self):
        thresh = _THRESHOLDS["memory_percent"]
        assert thresh["warn"] < thresh["critical"]

    def test_latency_critical_is_above_1000ms(self):
        # p95 latency > 1s should always be critical — real SLOs break at 1s
        thresh = _THRESHOLDS["latency_p95_ms"]
        assert thresh["critical"] <= 1500, "Critical latency threshold should catch 1.5s degradation"

    def test_all_metrics_have_both_thresholds(self):
        for metric, thresholds in _THRESHOLDS.items():
            assert "warn" in thresholds, f"{metric}: missing 'warn'"
            assert "critical" in thresholds, f"{metric}: missing 'critical'"
            assert thresholds["critical"] > thresholds["warn"], (
                f"{metric}: critical ({thresholds['critical']}) must exceed warn ({thresholds['warn']})"
            )

    @pytest.mark.parametrize("metric,value,expected_at_least_warning", [
        # Values just above warning threshold
        ("cpu_percent",    71.3, True),
        ("memory_percent", 80.7, True),
        ("latency_p95_ms", 502,  True),
        ("db_connections", 81.4, True),
        ("error_rate",     5.3,  True),
        # Values comfortably below warning
        ("cpu_percent",    38.2, False),
        ("memory_percent", 52.1, False),
        ("latency_p95_ms", 143,  False),
    ])
    def test_realistic_values_classified_correctly(self, metric, value, expected_at_least_warning):
        thresh = _THRESHOLDS[metric]
        is_warning = value >= thresh["warn"]
        assert is_warning == expected_at_least_warning, (
            f"{metric}={value}: expected {'≥warning' if expected_at_least_warning else '<warning'}, "
            f"warn={thresh['warn']}"
        )


class TestAnalyzeMetrics:

    async def test_clean_baseline_no_anomalies(self):
        # Healthy pod: CPU 38%, memory 51%, latency 143ms — all well within thresholds
        current = make_records(
            _row("cpu_percent",    38.2, 41.7, 34.1, stddev=1.8),
            _row("memory_percent", 51.4, 53.9, 48.6, stddev=1.2),
            _row("latency_p95_ms",  143,  167,  118,  stddev=12),
        )
        baseline = make_records(
            _baseline("cpu_percent",    36.8),
            _baseline("memory_percent", 50.1),
            _baseline("latency_p95_ms", 138),
        )
        conn = make_conn()
        conn.fetch.side_effect = [current, baseline]
        result = await analyze_metrics(conn, "user-service", window_minutes=15)
        assert result["anomalous"] is False
        assert result["worst_severity"] == "ok"
        assert result["anomalies"] == []

    async def test_memory_leak_progression_detected(self):
        # Memory climbed from 47.3% baseline to 91.8% peak — classic leak pattern
        current = make_records(
            _row("memory_percent", 87.4, 91.8, 74.2, stddev=4.6, samples=60),
        )
        baseline = make_records(
            _baseline("memory_percent", 47.3),
        )
        conn = make_conn()
        conn.fetch.side_effect = [current, baseline]
        result = await analyze_metrics(conn, "user-service", window_minutes=15)
        assert result["anomalous"] is True
        assert result["worst_severity"] == "critical"
        mem = next(a for a in result["anomalies"] if a["metric"] == "memory_percent")
        assert mem["current_max"] == 91.8
        assert mem["baseline"] == 47.3
        assert mem["pct_change"] > 80

    async def test_latency_spike_with_stable_cpu(self):
        # p95 latency went from 94ms baseline to 1847ms — database slowdown pattern
        current = make_records(
            _row("cpu_percent",    44.1, 47.3, 40.8),
            _row("latency_p95_ms", 1412, 1847,  980, stddev=218),
        )
        baseline = make_records(
            _baseline("cpu_percent",    42.7),
            _baseline("latency_p95_ms",  94.0),
        )
        conn = make_conn()
        conn.fetch.side_effect = [current, baseline]
        result = await analyze_metrics(conn, "api-gateway", window_minutes=10)
        assert result["anomalous"] is True
        lat = next(a for a in result["anomalies"] if a["metric"] == "latency_p95_ms")
        assert lat["severity"] == "critical"
        # CPU is fine — anomaly is only latency
        cpu_anomalies = [a for a in result["anomalies"] if a["metric"] == "cpu_percent"]
        assert not cpu_anomalies or cpu_anomalies[0]["severity"] == "ok"

    async def test_cpu_spike_on_batch_job(self):
        # CPU at 94.1% — consistent with a runaway batch process or infinite loop
        current = make_records(
            _row("cpu_percent", 91.7, 94.1, 88.3, stddev=1.4, samples=60),
        )
        baseline = make_records(
            _baseline("cpu_percent", 22.6),
        )
        conn = make_conn()
        conn.fetch.side_effect = [current, baseline]
        result = await analyze_metrics(conn, "worker-service", window_minutes=15)
        assert result["worst_severity"] == "critical"
        cpu = next(a for a in result["anomalies"] if a["metric"] == "cpu_percent")
        assert cpu["pct_change"] > 200

    async def test_db_connections_saturation(self):
        # db_connections at 96.3% — pgbouncer pool nearly full
        current = make_records(
            _row("db_connections", 93.7, 96.3, 89.1, stddev=2.1),
        )
        baseline = make_records(
            _baseline("db_connections", 34.8),
        )
        conn = make_conn()
        conn.fetch.side_effect = [current, baseline]
        result = await analyze_metrics(conn, "db-proxy", window_minutes=5)
        assert result["anomalous"] is True
        db = next(a for a in result["anomalies"] if a["metric"] == "db_connections")
        assert db["severity"] == "critical"

    async def test_multiple_critical_anomalies_sorted_critical_first(self):
        # Both CPU and latency critical — critical must appear before warning
        current = make_records(
            _row("cpu_percent",    92.3, 94.7, 89.1),
            _row("latency_p95_ms", 1623, 1847,  980),
            _row("memory_percent", 74.1, 76.2, 70.8),   # warning only
        )
        baseline = make_records(
            _baseline("cpu_percent",    24.1),
            _baseline("latency_p95_ms",  87.0),
            _baseline("memory_percent",  71.3),
        )
        conn = make_conn()
        conn.fetch.side_effect = [current, baseline]
        result = await analyze_metrics(conn, "payment-service")
        severities = [a["severity"] for a in result["anomalies"]]
        critical_idxs = [i for i, s in enumerate(severities) if s == "critical"]
        warning_idxs  = [i for i, s in enumerate(severities) if s == "warning"]
        if critical_idxs and warning_idxs:
            assert max(critical_idxs) < min(warning_idxs), (
                f"Critical anomalies must come before warnings. Got order: {severities}"
            )

    async def test_large_pct_change_below_threshold_still_flagged(self):
        # error_rate: 0.3% baseline → 2.1% now. Below warn threshold of 5% but 600% change.
        current = make_records(
            _row("error_rate", 1.87, 2.14, 1.51, stddev=0.18),
        )
        baseline = make_records(
            _baseline("error_rate", 0.31),
        )
        conn = make_conn()
        conn.fetch.side_effect = [current, baseline]
        result = await analyze_metrics(conn, "checkout-service")
        # >50% change from baseline should flag anomaly even if below threshold
        assert result["anomalous"] is True

    async def test_no_metrics_in_db(self):
        conn = make_conn()
        conn.fetch.side_effect = [[], []]
        result = await analyze_metrics(conn, "new-service", window_minutes=15)
        assert result["anomalies"] == []
        assert result["anomalous"] is False
        assert result["worst_severity"] == "ok"
