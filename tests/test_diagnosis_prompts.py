from __future__ import annotations

import pytest

from diagnosis_agent.prompts import build_diagnosis_prompt


SERVICE = "user-service"

FULL_LOG = {
    "error_count": 31,
    "findings": [
        {"pattern": "memory_exhaustion", "count": 31,
         "sample_messages": ["Out of memory: Kill process 8923 (user-svc)"]},
    ],
}
FULL_METRICS = {
    "anomalies": [
        {"metric": "memory_percent", "severity": "critical",
         "current_max": 94.2, "baseline": 47.1, "pct_change": 100.0},
    ],
}
FULL_DEPLOY = {
    "correlation_score": 70,
    "correlation_reason": "Successful deploy of v2.3.1 preceded the incident",
    "recent_deployments": [{"version": "v2.3.1", "status": "success", "deployed_at": "2026-06-07"}],
}


class TestPromptBuilder:
    def test_prompt_contains_service_name(self):
        prompt = build_diagnosis_prompt("alert", SERVICE, FULL_LOG, FULL_METRICS, FULL_DEPLOY)
        assert SERVICE in prompt

    def test_prompt_contains_alert_description(self):
        alert = "CRITICAL: memory at 94%"
        prompt = build_diagnosis_prompt(alert, SERVICE, FULL_LOG, FULL_METRICS, FULL_DEPLOY)
        assert alert in prompt

    def test_prompt_contains_metric_anomaly_values(self):
        prompt = build_diagnosis_prompt("alert", SERVICE, FULL_LOG, FULL_METRICS, FULL_DEPLOY)
        assert "94.2" in prompt
        assert "memory_percent" in prompt
        assert "critical" in prompt

    def test_prompt_contains_log_pattern_and_sample(self):
        prompt = build_diagnosis_prompt("alert", SERVICE, FULL_LOG, FULL_METRICS, FULL_DEPLOY)
        assert "memory_exhaustion" in prompt
        assert "Out of memory" in prompt
        assert "31" in prompt

    def test_prompt_contains_deployment_correlation(self):
        prompt = build_diagnosis_prompt("alert", SERVICE, FULL_LOG, FULL_METRICS, FULL_DEPLOY)
        assert "v2.3.1" in prompt
        assert "70" in prompt

    def test_empty_metrics_shows_normal(self):
        prompt = build_diagnosis_prompt("alert", SERVICE, FULL_LOG, {}, FULL_DEPLOY)
        assert "normal" in prompt.lower() or "within" in prompt.lower()

    def test_empty_logs_handled_gracefully(self):
        prompt = build_diagnosis_prompt("alert", SERVICE, {}, FULL_METRICS, FULL_DEPLOY)
        assert SERVICE in prompt  # should not raise

    def test_empty_deployment_handled_gracefully(self):
        prompt = build_diagnosis_prompt("alert", SERVICE, FULL_LOG, FULL_METRICS, {})
        assert SERVICE in prompt

    def test_prompt_has_root_cause_section(self):
        prompt = build_diagnosis_prompt("alert", SERVICE, FULL_LOG, FULL_METRICS, FULL_DEPLOY)
        assert "ROOT CAUSE" in prompt

    def test_prompt_has_remediation_section(self):
        prompt = build_diagnosis_prompt("alert", SERVICE, FULL_LOG, FULL_METRICS, FULL_DEPLOY)
        assert "REMEDIATION" in prompt or "STEPS" in prompt

    def test_prompt_has_confidence_section(self):
        prompt = build_diagnosis_prompt("alert", SERVICE, FULL_LOG, FULL_METRICS, FULL_DEPLOY)
        assert "CONFIDENCE" in prompt

    def test_multiple_log_patterns_all_appear(self):
        logs = {
            "error_count": 50,
            "findings": [
                {"pattern": "memory_exhaustion", "count": 30, "sample_messages": ["OOM"]},
                {"pattern": "connection_failure", "count": 15, "sample_messages": ["Connection refused"]},
                {"pattern": "timeout",            "count":  5, "sample_messages": ["Timed out"]},
            ],
        }
        prompt = build_diagnosis_prompt("alert", SERVICE, logs, FULL_METRICS, FULL_DEPLOY)
        assert "memory_exhaustion" in prompt
        assert "connection_failure" in prompt
        assert "timeout" in prompt

    def test_prompt_is_reasonable_length(self):
        prompt = build_diagnosis_prompt("alert", SERVICE, FULL_LOG, FULL_METRICS, FULL_DEPLOY)
        # Should be substantive but not bloated
        assert 500 < len(prompt) < 5000
