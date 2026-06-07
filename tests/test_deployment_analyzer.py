from __future__ import annotations

import pytest

from deployment_agent.analyzer import analyze_deployments
from tests.conftest import make_conn


# Realistic deployment records — version strings, commit SHAs, and CI/CD metadata
# match what a real GitOps pipeline would write to the database.

def _deploy(version, status, deployed_by="ci-bot", notes="", deployed_at="2026-06-07 03:30:00",
            commit_sha=None):
    sha = commit_sha or f"a{version.replace('.', '').replace('v', '')}b7c9d{'0' * 20}"[:40]
    return {
        "version":     version,
        "deployed_at": deployed_at,
        "deployed_by": deployed_by,
        "commit_sha":  sha,
        "status":      status,
        "notes":       notes,
    }


class TestDeploymentCorrelation:

    async def test_failed_rollout_scores_95(self):
        # Deployment failed mid-rollout — canary pods crashed, rollout halted
        conn = make_conn(
            fetch_results=[_deploy("v4.2.1", "failed", notes="Canary pods CrashLoopBackOff — ImagePullBackOff on init container")],
            fetchrow_result=_deploy("v4.2.0", "success"),
        )
        result = await analyze_deployments(conn, "payment-service")
        assert result["correlation_score"] == 95
        assert result["deployment_likely_cause"] is True
        assert "v4.2.1" in result["correlation_reason"]

    async def test_automated_rollback_scores_95(self):
        # Argo CD detected degraded health and triggered automatic rollback
        conn = make_conn(
            fetch_results=[_deploy(
                "v3.8.0", "rolled_back",
                deployed_by="argocd-bot",
                notes="Auto-rollback: pod readiness probe failed 3/3 times within 120s",
                commit_sha="f3a8c2e1d09b4567890abcdef1234567890abcde",
            )],
            fetchrow_result=_deploy("v3.7.9", "success"),
        )
        result = await analyze_deployments(conn, "order-service")
        assert result["correlation_score"] == 95
        assert result["deployment_likely_cause"] is True

    async def test_successful_deploy_preceding_incident_scores_70(self):
        # Deploy succeeded but a regression slipped through — correlation, not confirmation
        conn = make_conn(
            fetch_results=[_deploy(
                "v2.3.1", "success",
                deployed_by="github-actions",
                notes="PR #847 — add LRU cache to user profile endpoint",
                commit_sha="9b8a7c6d5e4f3a2b1c0d9e8f7a6b5c4d3e2f1a0b",
            )],
            fetchrow_result=_deploy("v2.3.0", "success"),
        )
        result = await analyze_deployments(conn, "user-service")
        assert result["correlation_score"] == 70
        assert result["deployment_likely_cause"] is True
        assert "v2.3.1" in result["correlation_reason"]

    async def test_no_deployments_in_window_scores_0(self):
        # Nothing deployed in the last 2 hours — deployment is not the cause
        conn = make_conn(fetch_results=[], fetchrow_result=None)
        result = await analyze_deployments(conn, "auth-service")
        assert result["correlation_score"] == 0
        assert result["deployment_likely_cause"] is False
        assert "No deployments" in result["correlation_reason"]

    async def test_failed_deploy_takes_priority_over_earlier_success(self):
        # Two deploys in window — the failed one must drive the score to 95
        conn = make_conn(
            fetch_results=[
                _deploy("v5.1.1", "failed",  deployed_at="2026-06-07 03:40:00",
                        notes="OOMKilled during startup, heap too small for new ML model"),
                _deploy("v5.1.0", "success", deployed_at="2026-06-07 03:10:00"),
            ],
            fetchrow_result=_deploy("v5.0.9", "success"),
        )
        result = await analyze_deployments(conn, "ml-inference-service")
        assert result["correlation_score"] == 95
        assert "v5.1.1" in result["correlation_reason"]

    async def test_last_stable_version_returned_for_rollback_guidance(self):
        # The last stable version is what on-call needs to roll back to
        stable = _deploy("v4.1.8", "success",
                         commit_sha="1a2b3c4d5e6f7a8b9c0d1e2f3a4b5c6d7e8f9a0b")
        conn = make_conn(
            fetch_results=[_deploy("v4.1.9", "failed")],
            fetchrow_result=stable,
        )
        result = await analyze_deployments(conn, "checkout-service")
        assert result["last_stable_version"]["version"] == "v4.1.8"
        assert result["last_stable_version"]["commit_sha"] == stable["commit_sha"]

    async def test_deployment_count_and_failed_list_accurate(self):
        rows = [
            _deploy("v3.3.2", "success",    deployed_at="2026-06-07 03:50:00"),
            _deploy("v3.3.1", "failed",     deployed_at="2026-06-07 03:35:00",
                    notes="kubectl apply timeout after 300s"),
            _deploy("v3.3.0", "rolled_back",deployed_at="2026-06-07 03:15:00",
                    notes="Health check failed: /healthz returned 503 for >60s"),
        ]
        conn = make_conn(fetch_results=rows, fetchrow_result=None)
        result = await analyze_deployments(conn, "api-gateway")
        assert result["deployment_count"] == 3
        failed_statuses = {d["status"] for d in result["failed_deployments"]}
        assert "failed"      in failed_statuses
        assert "rolled_back" in failed_statuses
