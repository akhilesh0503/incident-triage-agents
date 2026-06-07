from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Any, Optional

import asyncpg


@dataclass
class LogFinding:
    level: str
    pattern: str
    count: int
    sample_messages: list[str]
    first_seen: Optional[str] = None
    last_seen: Optional[str] = None

    def to_dict(self) -> dict[str, Any]:
        return {
            "level": self.level,
            "pattern": self.pattern,
            "count": self.count,
            "sample_messages": self.sample_messages,
            "first_seen": self.first_seen,
            "last_seen": self.last_seen,
        }


_ERROR_PATTERNS = [
    (re.compile(r"(?i)out.of.memory|oom|memory\s+exhausted"),        "memory_exhaustion"),
    (re.compile(r"(?i)connection\s+(refused|timed?\s*out|reset)"),    "connection_failure"),
    (re.compile(r"(?i)too\s+many\s+(connections|clients)"),           "connection_pool_exhausted"),
    (re.compile(r"(?i)timeout|timed?\s+out"),                         "timeout"),
    (re.compile(r"(?i)null\s*pointer|nullpointer|attribute\s+error"), "null_reference"),
    (re.compile(r"(?i)5[0-9]{2}\s+error|internal\s+server\s+error"), "http_5xx"),
    (re.compile(r"(?i)disk\s+(full|space|quota)"),                    "disk_full"),
    (re.compile(r"(?i)certificate\s+(expired?|invalid|error)"),       "cert_error"),
    (re.compile(r"(?i)deadlock"),                                     "deadlock"),
    (re.compile(r"(?i)panic|fatal|crash"),                            "fatal_error"),
]


async def analyze_logs(
    conn: asyncpg.Connection,
    service: str,
    window_minutes: int = 15,
) -> dict[str, Any]:
    rows = await conn.fetch(
        """
        SELECT level, message, logged_at::text
        FROM logs
        WHERE service = $1
          AND logged_at >= NOW() - ($2 * INTERVAL '1 minute')
        ORDER BY logged_at DESC
        LIMIT 500
        """,
        service,
        window_minutes,
    )

    total = len(rows)
    level_counts: dict[str, int] = {}
    pattern_hits: dict[str, list[dict]] = {}

    for row in rows:
        lvl = row["level"]
        msg = row["message"]
        level_counts[lvl] = level_counts.get(lvl, 0) + 1

        for pattern, label in _ERROR_PATTERNS:
            if pattern.search(msg):
                if label not in pattern_hits:
                    pattern_hits[label] = []
                pattern_hits[label].append({"message": msg, "level": lvl, "logged_at": row["logged_at"]})

    findings: list[dict] = []
    for label, hits in pattern_hits.items():
        hits_sorted = sorted(hits, key=lambda h: h["logged_at"])
        findings.append(LogFinding(
            level="ERROR",
            pattern=label,
            count=len(hits),
            sample_messages=[h["message"] for h in hits[:3]],
            first_seen=hits_sorted[0]["logged_at"],
            last_seen=hits_sorted[-1]["logged_at"],
        ).to_dict())

    error_count = level_counts.get("ERROR", 0) + level_counts.get("CRITICAL", 0)

    return {
        "service": service,
        "window_minutes": window_minutes,
        "total_log_entries": total,
        "level_counts": level_counts,
        "error_count": error_count,
        "error_rate_percent": round(error_count / total * 100, 1) if total else 0,
        "findings": sorted(findings, key=lambda f: f["count"], reverse=True),
        "anomalous": error_count > 5 or bool(findings),
    }
