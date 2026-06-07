from __future__ import annotations

import pytest

from diagnosis_agent.ollama_client import _parse_response


# These are actual output patterns from qwen2.5:3b, captured during development.
# The model frequently deviates from the template — these tests verify the parser
# handles real model behavior, not an idealized format.

# ── Actual model outputs ───────────────────────────────────────────────────────

# Clean output — model followed the template closely
QWEN_MEMORY_LEAK = """\
ROOT CAUSE:
The root cause is a memory leak in user-service introduced with deployment v2.3.1, where \
an unbounded in-process cache in the request handler grew from 47.3% baseline to 91.8% peak \
over 15 minutes, triggering 18 OOM kills by the Linux kernel and cascading connection failures \
to downstream services.

CONFIDENCE: HIGH

REMEDIATION STEPS:
1. Roll back user-service to v2.2.9 immediately: kubectl rollout undo deployment/user-service -n production
2. Patch the cache in v2.3.2: add a max-size eviction policy (LRU, max=10000) to the request context cache
3. Confirm recovery by watching memory_percent drop below 60% in Grafana — dashboard: "user-service / Resources"
4. Add a Prometheus alert rule: memory_percent > 85% for 5m → page on-call before the next OOM event
"""

# Model added preamble before the template — common with qwen2.5:3b
QWEN_WITH_PREAMBLE = """\
Based on the evidence provided, here is my diagnosis:

ROOT CAUSE:
The root cause is connection pool exhaustion on db-proxy. All 100 pgbouncer slots are occupied \
(db_connections peaked at 96.3%), with 51 client requests queuing. The spike correlates with \
deployment v3.1.4 which doubled the connection limit on checkout-service without adjusting \
pgbouncer's max_client_conn.

CONFIDENCE: HIGH

REMEDIATION STEPS:
1. Increase pgbouncer max_client_conn from 500 to 1000 in /etc/pgbouncer/pgbouncer.ini and reload: pgbouncer -R
2. Restart checkout-service pods to release stale held connections: kubectl rollout restart deployment/checkout-service
3. Watch db_connections metric — alert clears when it drops below 80% of the new limit
4. Review v3.1.4 connection config — set pool_size per service to 25 max, not unlimited
"""

# Model used "Immediate:" / "Short-term:" labels instead of numbers — was a real bug
QWEN_LABEL_FORMAT = """\
ROOT CAUSE:
The root cause is a CPU spike on worker-service caused by a runaway Celery beat task \
(send_weekly_digest) that entered an infinite retry loop after a Redis timeout. CPU \
climbed from 22.6% baseline to 94.1%, consuming all 4 vCPUs.

CONFIDENCE: HIGH

REMEDIATION STEPS:
Immediate: Kill the runaway Celery worker pod: kubectl delete pod worker-service-beat-7f8d9c-xk2mw -n production
Short-term: Add max_retries=3 and exponential backoff to send_weekly_digest in tasks/digest.py
Monitoring: Watch cpu_percent in Grafana until it returns below 40% over a 5-minute window
Prevention: Set a Celery task time limit of 300s on all beat tasks to prevent infinite retry loops
"""

# Model output truncated mid-sentence — happens when num_predict limit is hit
QWEN_TRUNCATED = """\
ROOT CAUSE:
The root cause is high latency on api-gateway caused by N+1 database queries in the \
GET /api/v1/users/orders endpoint. Each order record triggers a separate SELECT on the \
payments table, causing latency to spike from 94ms baseline to 1847ms p95 under load.

CONFIDENCE: HIGH

REMEDIATION STEPS:
1. Add SELECT ... JOIN payments ON payments.order_id = orders.id to eliminate the N+1 — see orders/views.py:142
2. Add a covering index on payments(order_id, status, amount) to support the"""
# truncated here — parser must handle this gracefully

# Model output with extra "Note:" section appended
QWEN_WITH_NOTE = """\
ROOT CAUSE:
The root cause is a failed schema migration in deployment v4.0.1 that dropped the \
idx_orders_created_at index, causing full table scans on the 47M-row orders table \
and exhausting db_connections (96.3%) as queries piled up waiting for locks.

CONFIDENCE: HIGH

REMEDIATION STEPS:
1. Roll back v4.0.1 immediately: kubectl rollout undo deployment/order-service
2. Recreate the index concurrently on the replica first: CREATE INDEX CONCURRENTLY idx_orders_created_at ON orders(created_at)
3. Verify query times drop: watch pg_stat_activity for queries > 5s on orders table
4. Add pre-deployment migration validation to CI: run EXPLAIN ANALYZE on the 3 most expensive queries

Note: This diagnosis is based on the correlation between the failed deployment and the db_connections spike. The root cause may differ if the migration was not the only change in v4.0.1.
"""

# Completely garbled — model produced no recognisable structure
QWEN_GARBLED = "I cannot determine the root cause from the available evidence. Please provide more information."


class TestParseRealModelOutputs:

    def test_clean_memory_leak_output_parsed_correctly(self):
        result = _parse_response(QWEN_MEMORY_LEAK)
        assert "memory leak" in result["root_cause"].lower()
        assert "v2.3.1" in result["root_cause"]
        assert result["confidence"] == "HIGH"
        assert len(result["remediation_steps"]) == 4

    def test_preamble_before_template_does_not_break_parser(self):
        result = _parse_response(QWEN_WITH_PREAMBLE)
        rc = result["root_cause"]
        assert "db-proxy" in rc or "connection pool" in rc, (
            f"Root cause missed despite preamble: {rc!r}"
        )
        assert result["confidence"] == "HIGH"
        assert len(result["remediation_steps"]) == 4

    def test_rollback_step_appears_in_first_remediation_step(self):
        result = _parse_response(QWEN_MEMORY_LEAK)
        step1 = result["remediation_steps"][0].lower()
        assert any(w in step1 for w in ["rollout", "roll back", "rollback", "kubectl", "restart"]), (
            f"Step 1 is not an immediate action: {step1!r}"
        )

    def test_label_format_steps_root_cause_still_extracted(self):
        # "Immediate:" / "Short-term:" labels — the parser only handles numbered steps,
        # so steps will be empty. The fix lives upstream: the prompt uses sentence-completion
        # forcing ("1.", "2.", ...) so the model no longer produces this format.
        # This test documents the parser's behavior, not a desired outcome.
        result = _parse_response(QWEN_LABEL_FORMAT)
        # Root cause must still be extracted even if steps are empty
        rc = result["root_cause"].lower()
        assert "cpu" in rc or "celery" in rc or "worker" in rc, (
            f"Root cause not extracted from label-format output: {rc!r}"
        )
        # Parser returns empty for label-format — expected, handled upstream
        assert isinstance(result["remediation_steps"], list)

    def test_truncated_output_does_not_raise(self):
        result = _parse_response(QWEN_TRUNCATED)
        assert "root_cause" in result
        assert result["confidence"] == "HIGH"
        # Partial steps are acceptable — must not crash or return None
        assert isinstance(result["remediation_steps"], list)
        assert result["raw_response"] == QWEN_TRUNCATED

    def test_trailing_note_section_does_not_corrupt_steps(self):
        result = _parse_response(QWEN_WITH_NOTE)
        assert len(result["remediation_steps"]) == 4
        # The "Note:" section must not bleed into step 4
        step4 = result["remediation_steps"][3].lower()
        assert "note:" not in step4, f"Note section leaked into step 4: {step4!r}"

    def test_garbled_output_falls_back_gracefully(self):
        result = _parse_response(QWEN_GARBLED)
        assert result["root_cause"]           # populated with raw text as fallback
        assert result["confidence"] == "MEDIUM"   # default when not found
        assert result["remediation_steps"] == []
        assert result["raw_response"] == QWEN_GARBLED

    def test_sentence_completion_prefix_stripped_from_root_cause(self):
        # Prompt uses "The root cause is" prefix — parser must strip or include cleanly
        output = "ROOT CAUSE:\nThe root cause is a memory leak in user-service.\n\nCONFIDENCE: HIGH\n\nREMEDIATION STEPS:\n1. Restart the pod\n2. Review the heap dump\n3. Watch memory_percent\n4. Add alert at 85%\n"
        result = _parse_response(output)
        rc = result["root_cause"]
        # Should not start with "The root cause is" — should be the actual content
        # OR include the whole sentence — either is acceptable, but content must be there
        assert "memory leak" in rc.lower() or "user-service" in rc.lower()

    def test_confidence_medium_parsed(self):
        output = "ROOT CAUSE:\nInsufficient evidence to determine a single cause.\n\nCONFIDENCE: MEDIUM\n\nREMEDIATION STEPS:\n1. Collect heap dumps\n2. Increase log verbosity\n3. Run load test\n4. Escalate to team lead\n"
        result = _parse_response(output)
        assert result["confidence"] == "MEDIUM"

    def test_confidence_low_parsed(self):
        output = "ROOT CAUSE:\nUnknown — no clear signal in logs or metrics.\n\nCONFIDENCE: LOW\n\nREMEDIATION STEPS:\n1. Gather more data\n2. Check upstream services\n3. Review recent changes\n4. Page senior SRE\n"
        result = _parse_response(output)
        assert result["confidence"] == "LOW"

    def test_raw_response_always_preserved(self):
        for output in [QWEN_MEMORY_LEAK, QWEN_WITH_PREAMBLE, QWEN_GARBLED, QWEN_TRUNCATED]:
            result = _parse_response(output)
            assert result["raw_response"] == output
