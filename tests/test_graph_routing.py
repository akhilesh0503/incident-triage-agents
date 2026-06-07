from __future__ import annotations

import os

import pytest

os.environ.setdefault("POSTGRES_DSN", "postgresql://agent:agent_pass@localhost:5433/triage_db")
os.environ.setdefault("REDIS_URL", "redis://localhost:6379")

from orchestrator.classifier import ALERT_ROUTING
from orchestrator.graph import TRIAGE_GRAPH, TriageState, route_after_classify


class TestAlertRouting:
    """Routing table is the core intelligence — every rule must be verified."""

    def test_memory_leak_routes_to_log_and_metrics_only(self):
        agents = ALERT_ROUTING["memory_leak"]
        assert "log" in agents
        assert "metrics" in agents
        assert "deployment" not in agents, "Memory leaks don't need deployment history"

    def test_high_latency_routes_to_log_and_metrics_only(self):
        agents = ALERT_ROUTING["high_latency"]
        assert "log" in agents
        assert "metrics" in agents
        assert "deployment" not in agents

    def test_deployment_failure_routes_to_log_and_deployment_not_metrics(self):
        agents = ALERT_ROUTING["deployment_failure"]
        assert "log" in agents
        assert "deployment" in agents
        assert "metrics" not in agents, "Deployment failures don't need metric baseline comparison"

    def test_database_issue_routes_to_all_three_agents(self):
        agents = ALERT_ROUTING["database_issue"]
        assert "log" in agents
        assert "metrics" in agents
        assert "deployment" in agents, "DB issues need full picture — could be a bad schema migration"

    def test_cpu_spike_routes_to_metrics_and_log(self):
        agents = ALERT_ROUTING["cpu_spike"]
        assert "metrics" in agents
        assert "log" in agents

    def test_unknown_routes_to_all_three(self):
        agents = ALERT_ROUTING["unknown"]
        assert "log" in agents
        assert "metrics" in agents
        assert "deployment" in agents

    def test_all_known_alert_types_covered(self):
        expected_types = {"memory_leak", "high_latency", "deployment_failure",
                          "database_issue", "cpu_spike", "unknown"}
        assert set(ALERT_ROUTING.keys()) == expected_types

    def test_all_agent_values_are_valid_keys(self):
        valid_agents = {"log", "metrics", "deployment"}
        for alert_type, agents in ALERT_ROUTING.items():
            for a in agents:
                assert a in valid_agents, f"Unknown agent '{a}' in routing for '{alert_type}'"

    def test_all_routing_lists_are_non_empty(self):
        for alert_type, agents in ALERT_ROUTING.items():
            assert len(agents) > 0, f"Empty routing for '{alert_type}'"


class TestConditionalEdge:
    def test_no_error_routes_to_run_specialists(self):
        state: TriageState = {
            "triage_id": "test", "alert_description": "test", "service": "svc",
            "alert_type": "memory_leak", "agents_to_run": ["log", "metrics"],
            "log_findings": None, "metrics_findings": None, "deployment_findings": None,
            "diagnosis": None, "error": None,
        }
        assert route_after_classify(state) == "run_specialists"

    def test_error_routes_to_mark_failed(self):
        state: TriageState = {
            "triage_id": "test", "alert_description": "test", "service": "svc",
            "alert_type": "unknown", "agents_to_run": [],
            "log_findings": None, "metrics_findings": None, "deployment_findings": None,
            "diagnosis": None, "error": "Ollama timed out",
        }
        assert route_after_classify(state) == "mark_failed"


class TestGraphStructure:
    def test_graph_has_expected_nodes(self):
        nodes = set(TRIAGE_GRAPH.nodes.keys())
        assert "__start__"      in nodes
        assert "classify_alert" in nodes
        assert "run_specialists" in nodes
        assert "run_diagnosis"  in nodes
        assert "mark_failed"    in nodes

    def test_graph_entry_point_is_classify(self):
        # __start__ should connect to classify_alert
        assert "__start__" in TRIAGE_GRAPH.nodes
