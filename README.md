# Autonomous Incident Triage System

A production-grade multi-agent system that automatically classifies production alerts, routes them to specialist agents in parallel, and synthesizes an LLM-powered root cause diagnosis — all in real time.

![Incident Triage System UI](screenshot.png)

---

## Overview

When a production alert fires, the system:

1. **Classifies** the alert type using a local LLM (Ollama qwen2.5:3b)
2. **Routes** to the relevant specialist agents based on alert type (deterministic routing table)
3. **Runs specialists in parallel** — LogAgent, MetricsAgent, DeploymentAgent
4. **Synthesizes a diagnosis** — root cause, confidence level, and 4-step remediation plan
5. **Streams everything live** to the UI via SSE (Server-Sent Events)
6. **Persists the incident** to PostgreSQL for audit and trend analysis

---

## Architecture

```
                        ┌─────────────────────────────────┐
                        │         OrchestratorAgent        │
                        │   LangGraph StateGraph (A2A)     │
                        │                                  │
                        │  classify_alert                  │
                        │       ↓                          │
                        │  route_after_classify            │
                        │       ↓                          │
                        │  run_specialists (parallel)      │
                        │   ├── LogAgent                   │
                        │   ├── MetricsAgent               │
                        │   └── DeploymentAgent            │
                        │       ↓                          │
                        │  run_diagnosis → DiagnosisAgent  │
                        └─────────────────────────────────┘
```

### Agent Routing (core intelligence)

| Alert Type         | Agents Called                        |
|--------------------|--------------------------------------|
| `memory_leak`      | LogAgent + MetricsAgent              |
| `high_latency`     | LogAgent + MetricsAgent              |
| `deployment_failure` | LogAgent + DeploymentAgent         |
| `database_issue`   | LogAgent + MetricsAgent + DeploymentAgent |
| `cpu_spike`        | MetricsAgent + LogAgent              |
| `unknown`          | All three                            |

---

## Agents

| Agent | Responsibility |
|-------|---------------|
| **OrchestratorAgent** | LLM alert classification, LangGraph routing, SSE streaming, UI |
| **LogAgent** | Regex pattern matching across 10 error categories, anomaly detection |
| **MetricsAgent** | Threshold analysis + baseline comparison (3× prior period) |
| **DeploymentAgent** | Deployment correlation scoring — failed/rolled-back = 95, recent deploy = 70 |
| **DiagnosisAgent** | Ollama qwen2.5:3b — grounded root cause + 4-step remediation |

---

## Tech Stack

| Layer | Technology |
|-------|-----------|
| Agent framework | [LangGraph](https://github.com/langchain-ai/langgraph) StateGraph |
| Agent protocol | A2A (JSON-RPC 2.0 + SSE task lifecycle) |
| Web framework | [Litestar](https://litestar.dev/) 2.23.0 |
| LLM | [Ollama](https://ollama.com/) qwen2.5:3b (free, local) |
| Database | PostgreSQL 16 + asyncpg |
| Cache / SSE | Redis 7 pub/sub |
| Observability | Prometheus + Grafana (auto-provisioned dashboard) |
| Tests | pytest-asyncio — 100 tests, all passing |

---

## Incident Scenarios

Five injectable scenarios — each writes realistic anomaly data to PostgreSQL and fires a real triage run:

| Scenario | What's injected | Expected routing |
|----------|----------------|-----------------|
| `memory_leak` | 30 OOM log entries + rising memory metrics (60→94%) | Log + Metrics |
| `failed_deployment` | 1 failed deploy + 25 error logs | Log + Deployment |
| `high_latency` | 20 timeout logs + rising latency (400→1800ms) | Log + Metrics |
| `database_overload` | 25 connection pool logs + db_connections (70→96%) | Log + Metrics + Deployment |
| `cpu_spike` | 15 timeout logs + rising CPU (60→95%) | Metrics + Log |

---

## Running Locally

**Prerequisites:** Docker Desktop, [Ollama](https://ollama.com/) with `qwen2.5:3b` pulled

```bash
# Pull the model
ollama pull qwen2.5:3b

# Start everything
docker compose up --build

# UI
open http://localhost:8000

# Grafana dashboards
open http://localhost:3000   # admin / admin

# Run all 5 scenarios end-to-end and verify routing
python run_traffic.py
```

---

## Tests

```bash
cd orchestrator
pip install pytest pytest-asyncio
pytest ../tests/ -v
# 100 passed in ~4s
```

Covers: A2A protocol models, log pattern matching, metrics threshold analysis, deployment correlation scoring, prompt builder output, Ollama response parser, LangGraph routing table and conditional edge logic.

---

## Project Structure

```
.
├── orchestrator/          # LangGraph router + UI + SSE streaming
│   └── static/index.html  # Dark-theme real-time dashboard
├── log_agent/             # Regex log analysis (10 error patterns)
├── metrics_agent/         # Threshold + baseline comparison
├── deployment_agent/      # Deployment correlation scoring
├── diagnosis_agent/       # Ollama root cause synthesis
├── shared/                # A2A protocol models + Redis TaskStore
├── tests/                 # 100-test pytest suite
├── run_traffic.py         # End-to-end integration harness
├── docker-compose.yml     # 9-service stack
└── init.sql               # PostgreSQL schema + 2h baseline seed data
```
