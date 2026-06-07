from __future__ import annotations

import pytest

from diagnosis_agent.ollama_client import _parse_response


GOOD_RESPONSE = """
ROOT CAUSE:
The user-service is experiencing a memory leak introduced in deployment v2.3.1. Memory grew from 47% baseline to 94.2% peak, causing OOM kills (31 incidents) which cascaded into connection failures.

CONFIDENCE: HIGH

REMEDIATION STEPS:
1. Immediately roll back user-service to v2.2.9 using: kubectl rollout undo deployment/user-service
2. Increase memory limits as a temporary buffer: kubectl set resources deployment/user-service --limits=memory=4Gi
3. Verify recovery by confirming memory_percent drops below 60% in Grafana and error_rate returns to baseline
4. Review the v2.3.1 diff for unbounded cache growth or missing object disposal in the new request handler
"""

SENTENCE_COMPLETION_RESPONSE = """
ROOT CAUSE:
The root cause is an overloaded connection pool on db-proxy, with all 100 slots occupied and 51 requests queuing.

CONFIDENCE: HIGH

REMEDIATION STEPS:
1. Increase the db-proxy connection pool size from 100 to 200 in the config immediately.
2. Restart the heaviest connection consumers (user-service and payment-service) to release stale connections.
3. Monitor db_connections metric until it drops below 80% of the new limit.
4. Set a Prometheus alert at 85% pool utilization to catch this before it reaches 100% again.
"""

LOW_CONFIDENCE_RESPONSE = """
ROOT CAUSE:
The cause is unclear based on available evidence.

CONFIDENCE: LOW

REMEDIATION STEPS:
1. Collect more diagnostic data from all services.
2. Check for infrastructure-level issues.
3. Monitor all metrics for the next 30 minutes.
4. Escalate to senior SRE if no improvement.
"""


class TestParseResponse:
    def test_parses_root_cause(self):
        result = _parse_response(GOOD_RESPONSE)
        assert "memory leak" in result["root_cause"].lower()
        assert "v2.3.1" in result["root_cause"]

    def test_parses_high_confidence(self):
        result = _parse_response(GOOD_RESPONSE)
        assert result["confidence"] == "HIGH"

    def test_parses_low_confidence(self):
        result = _parse_response(LOW_CONFIDENCE_RESPONSE)
        assert result["confidence"] == "LOW"

    def test_parses_four_remediation_steps(self):
        result = _parse_response(GOOD_RESPONSE)
        assert len(result["remediation_steps"]) == 4

    def test_steps_are_non_empty_strings(self):
        result = _parse_response(GOOD_RESPONSE)
        for step in result["remediation_steps"]:
            assert isinstance(step, str)
            assert len(step) > 10

    def test_first_step_is_immediate_action(self):
        result = _parse_response(GOOD_RESPONSE)
        # First step should mention rollback/restart/immediate action
        assert any(word in result["remediation_steps"][0].lower()
                   for word in ["roll", "restart", "scale", "increase", "immediate", "kubectl", "stop"])

    def test_sentence_completion_format_parses_root_cause(self):
        result = _parse_response(SENTENCE_COMPLETION_RESPONSE)
        # "The root cause is" prefix should be stripped or included cleanly
        rc = result["root_cause"]
        assert "db-proxy" in rc or "connection pool" in rc

    def test_sentence_completion_format_parses_steps(self):
        result = _parse_response(SENTENCE_COMPLETION_RESPONSE)
        assert len(result["remediation_steps"]) == 4
        assert "db-proxy" in result["remediation_steps"][0] or "pool" in result["remediation_steps"][0]

    def test_fallback_on_malformed_response(self):
        result = _parse_response("Something went wrong, no structure here")
        assert result["root_cause"]  # fallback populates this
        assert result["confidence"] == "MEDIUM"  # default
        assert result["remediation_steps"] == []

    def test_raw_response_always_returned(self):
        result = _parse_response(GOOD_RESPONSE)
        assert result["raw_response"] == GOOD_RESPONSE

    def test_medium_confidence_parsed(self):
        result = _parse_response("ROOT CAUSE:\nsome cause\nCONFIDENCE: MEDIUM\nREMEDIATION STEPS:\n1. do thing")
        assert result["confidence"] == "MEDIUM"
