from __future__ import annotations

from typing import Any

import asyncpg


_THRESHOLDS: dict[str, dict[str, float]] = {
    "cpu_percent":     {"warn": 70.0,  "critical": 90.0},
    "memory_percent":  {"warn": 75.0,  "critical": 90.0},
    "error_rate":      {"warn": 5.0,   "critical": 20.0},
    "latency_p95_ms":  {"warn": 500.0, "critical": 1500.0},
    "db_connections":  {"warn": 80.0,  "critical": 95.0},
}


async def analyze_metrics(
    conn: asyncpg.Connection,
    service: str,
    window_minutes: int = 15,
) -> dict[str, Any]:
    rows = await conn.fetch(
        """
        SELECT metric_name,
               AVG(value)   AS avg_val,
               MAX(value)   AS max_val,
               MIN(value)   AS min_val,
               COUNT(*)     AS samples,
               STDDEV(value) AS stddev
        FROM metrics_snapshots
        WHERE service = $1
          AND recorded_at >= NOW() - ($2 * INTERVAL '1 minute')
        GROUP BY metric_name
        """,
        service,
        window_minutes,
    )

    # Baseline from the previous window (for comparison)
    baseline_rows = await conn.fetch(
        """
        SELECT metric_name, AVG(value) AS baseline_avg
        FROM metrics_snapshots
        WHERE service = $1
          AND recorded_at BETWEEN NOW() - ($2 * INTERVAL '1 minute') * 3
                              AND NOW() - ($2 * INTERVAL '1 minute')
        GROUP BY metric_name
        """,
        service,
        window_minutes,
    )
    baseline = {r["metric_name"]: float(r["baseline_avg"]) for r in baseline_rows}

    metrics: dict[str, Any] = {}
    anomalies: list[dict] = []

    for row in rows:
        name = row["metric_name"]
        avg = float(row["avg_val"])
        maximum = float(row["max_val"])
        base = baseline.get(name, avg)

        pct_change = ((avg - base) / base * 100) if base else 0
        severity = "ok"

        thresh = _THRESHOLDS.get(name)
        if thresh:
            if maximum >= thresh["critical"]:
                severity = "critical"
            elif maximum >= thresh["warn"]:
                severity = "warning"

        metrics[name] = {
            "avg": round(avg, 2),
            "max": round(maximum, 2),
            "min": round(float(row["min_val"]), 2),
            "baseline_avg": round(base, 2),
            "pct_change_from_baseline": round(pct_change, 1),
            "samples": int(row["samples"]),
            "severity": severity,
        }

        if severity in ("warning", "critical") or abs(pct_change) > 50:
            anomalies.append({
                "metric": name,
                "severity": severity,
                "current_max": round(maximum, 2),
                "baseline": round(base, 2),
                "pct_change": round(pct_change, 1),
            })

    anomalies.sort(key=lambda a: {"critical": 0, "warning": 1}.get(a["severity"], 2))

    return {
        "service": service,
        "window_minutes": window_minutes,
        "metrics": metrics,
        "anomalies": anomalies,
        "anomalous": bool(anomalies),
        "worst_severity": anomalies[0]["severity"] if anomalies else "ok",
    }
