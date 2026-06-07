from __future__ import annotations

import pytest

from deployment_agent.analyzer import analyze_deployments
from tests.conftest import make_conn


class TestDeploymentCorrelation:
    """Verify correlation scoring logic — this is the core non-trivial logic."""

    def _deploy_row(self, version="v2.0.0", status="success", deployed_by="alice",
                    commit_sha="abc123", notes=None, deployed_at="2026-01-01 00:00:00"):
        return {
            "version": version,
            "deployed_at": deployed_at,
            "deployed_by": deployed_by,
            "commit_sha": commit_sha,
            "status": status,
            "notes": notes or "",
        }

    async def test_failed_deployment_scores_95(self):
        conn = make_conn(
            fetch_results=[self._deploy_row(version="v3.1.0", status="failed")],
            fetchrow_result=self._deploy_row(version="v3.0.0"),
        )
        result = await analyze_deployments(conn, "payment-service")
        assert result["correlation_score"] == 95
        assert result["deployment_likely_cause"] is True
        assert "v3.1.0" in result["correlation_reason"]

    async def test_rolled_back_deployment_scores_95(self):
        conn = make_conn(
            fetch_results=[self._deploy_row(version="v2.5.0", status="rolled_back")],
            fetchrow_result=self._deploy_row(version="v2.4.9"),
        )
        result = await analyze_deployments(conn, "api-gateway")
        assert result["correlation_score"] == 95
        assert result["deployment_likely_cause"] is True

    async def test_successful_deployment_scores_70(self):
        conn = make_conn(
            fetch_results=[self._deploy_row(version="v2.3.1", status="success")],
            fetchrow_result=self._deploy_row(version="v2.3.0"),
        )
        result = await analyze_deployments(conn, "user-service")
        assert result["correlation_score"] == 70
        assert result["deployment_likely_cause"] is True

    async def test_no_recent_deployment_scores_0(self):
        conn = make_conn(fetch_results=[], fetchrow_result=None)
        result = await analyze_deployments(conn, "auth-service")
        assert result["correlation_score"] == 0
        assert result["deployment_likely_cause"] is False
        assert "No deployments" in result["correlation_reason"]

    async def test_failed_takes_priority_over_successful_in_same_window(self):
        conn = make_conn(
            fetch_results=[
                self._deploy_row(version="v2.1.0", status="failed"),
                self._deploy_row(version="v2.0.9", status="success"),
            ],
            fetchrow_result=self._deploy_row(version="v2.0.8"),
        )
        result = await analyze_deployments(conn, "payment-service")
        # Failed deployment in list → should score 95
        assert result["correlation_score"] == 95

    async def test_returns_last_stable_version(self):
        stable = self._deploy_row(version="v1.9.0", status="success")
        conn = make_conn(
            fetch_results=[self._deploy_row(version="v2.0.0", status="failed")],
            fetchrow_result=stable,
        )
        result = await analyze_deployments(conn, "user-service")
        assert result["last_stable_version"]["version"] == "v1.9.0"

    async def test_deployment_count_matches_fetched_rows(self):
        rows = [
            self._deploy_row(version="v2.1.0", status="success"),
            self._deploy_row(version="v2.0.9", status="success"),
            self._deploy_row(version="v2.0.8", status="failed"),
        ]
        conn = make_conn(fetch_results=rows, fetchrow_result=None)
        result = await analyze_deployments(conn, "api-gateway")
        assert result["deployment_count"] == 3
        assert len(result["failed_deployments"]) == 1
