from __future__ import annotations

from typing import Any

import asyncpg


async def analyze_deployments(
    conn: asyncpg.Connection,
    service: str,
    window_minutes: int = 60,
) -> dict[str, Any]:
    # Recent deploys within the window
    recent = await conn.fetch(
        """
        SELECT version, deployed_at::text, deployed_by, commit_sha, status, notes
        FROM deployments
        WHERE service = $1
          AND deployed_at >= NOW() - ($2 * INTERVAL '1 minute')
        ORDER BY deployed_at DESC
        """,
        service,
        window_minutes,
    )

    # Last successful deploy before window (for comparison)
    last_stable = await conn.fetchrow(
        """
        SELECT version, deployed_at::text, deployed_by, commit_sha
        FROM deployments
        WHERE service = $1
          AND status = 'success'
          AND deployed_at < NOW() - ($2 * INTERVAL '1 minute')
        ORDER BY deployed_at DESC
        LIMIT 1
        """,
        service,
        window_minutes,
    )

    recent_list = [dict(r) for r in recent]
    failed = [r for r in recent_list if r["status"] in ("failed", "rolled_back")]
    successful = [r for r in recent_list if r["status"] == "success"]

    correlation_score = 0
    correlation_reason = ""

    if recent_list:
        # High correlation if there was a recent deploy + the incident followed
        if failed:
            correlation_score = 95
            correlation_reason = f"Failed deployment of {failed[0]['version']} detected in window"
        elif successful:
            correlation_score = 70
            correlation_reason = f"Successful deploy of {successful[0]['version']} preceded the incident"
    else:
        correlation_reason = "No deployments in incident window — deployment not a likely cause"

    return {
        "service": service,
        "window_minutes": window_minutes,
        "recent_deployments": recent_list,
        "failed_deployments": failed,
        "last_stable_version": dict(last_stable) if last_stable else None,
        "deployment_count": len(recent_list),
        "correlation_score": correlation_score,
        "correlation_reason": correlation_reason,
        "deployment_likely_cause": correlation_score >= 70,
    }
