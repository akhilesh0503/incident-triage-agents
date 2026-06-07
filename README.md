# Autonomous Incident Triage System

**5/5 scenarios · 101 tests passing in 3.2s · HIGH confidence diagnosis on all runs · parallel specialist agents in <1s · 0 routing mismatches across 5 alert types**

A production-grade multi-agent system that classifies production alerts with an LLM, routes to specialist agents in parallel via the A2A protocol, and synthesizes a grounded root cause diagnosis with a 4-step remediation plan — streamed live to the UI.

![Incident Triage System](screenshot.png)

---

## Architecture

```
POST /triage
     │
  OrchestratorAgent  (LangGraph StateGraph)
     │
  classify_alert  ──  Ollama qwen2.5:3b (temperature=0.0)
     │
  route_after_classify  ──  ALERT_ROUTING table (deterministic)
     │
  run_specialists  ──  asyncio.gather() — parallel fan-out
  ├── LogAgent        (regex pattern matching, 10 error categories)
  ├── MetricsAgent    (threshold analysis + 3× baseline comparison)
  └── DeploymentAgent (correlation scoring — failed=95, success=70)
     │
  run_diagnosis  ──  DiagnosisAgent → Ollama (temperature=0.2)
     │
  SSE stream  →  browser EventSource  →  real-time UI update
  PostgreSQL  →  incident persisted (root cause + remediation + agents consulted)
```

### Routing Table (core intelligence)

Each alert type routes to a precise subset of agents — no agent runs unnecessarily.

| Alert Type | LogAgent | MetricsAgent | DeploymentAgent | Why |
|---|---|---|---|---|
| `memory_leak` | ✓ | ✓ | — | OOM is a metrics + log signal, not a deploy artifact |
| `high_latency` | ✓ | ✓ | — | Latency is measurable; deployment rarely the cause |
| `deployment_failure` | ✓ | — | ✓ | Error logs + deploy history; metrics aren't the signal |
| `database_issue` | ✓ | ✓ | ✓ | Could be a bad schema migration — needs all three |
| `cpu_spike` | ✓ | ✓ | — | CPU is a metrics signal; logs confirm what's consuming it |
| `unknown` | ✓ | ✓ | ✓ | Insufficient signal — run everything |

---

## Agents

| Agent | Port | Responsibility |
|---|---|---|
| **OrchestratorAgent** | 8000 | LLM classification, LangGraph routing, SSE streaming, UI |
| **LogAgent** | 8001 | 10-pattern regex scan, multi-match per message, anomaly detection |
| **MetricsAgent** | 8002 | 5-metric threshold analysis + 3× baseline window comparison |
| **DeploymentAgent** | 8003 | Deployment correlation scoring against incident window |
| **DiagnosisAgent** | 8004 | Grounded root cause + 4-step remediation via Ollama |

---

## Stack

| Layer | Tech |
|---|---|
| Agent protocol | A2A (JSON-RPC 2.0 + SSE task lifecycle) |
| Agent framework | LangGraph StateGraph |
| Web framework | Litestar 2.23.0 |
| LLM | Ollama qwen2.5:3b (free, local) |
| Database | PostgreSQL 16 + asyncpg |
| SSE streaming | Redis 7 pub/sub |
| Observability | Prometheus + Grafana (auto-provisioned) |
| Tests | pytest-asyncio — 100 tests |
| Infra | Docker Compose (9 services) |

---

## Build Phases

- [x] **Phase 1** — Project scaffold, GitHub repo, A2A protocol models, Redis TaskStore
- [x] **Phase 2** — LogAgent (10 regex patterns), MetricsAgent (thresholds + baseline), DeploymentAgent (correlation scoring)
- [x] **Phase 3** — DiagnosisAgent: Ollama client, grounded prompt builder, response parser
- [x] **Phase 4** — OrchestratorAgent: LLM classifier, LangGraph StateGraph, parallel fan-out, SSE streaming, dark-theme UI
- [x] **Phase 5** — Docker Compose (9 services), Dockerfiles, Prometheus scrape config, Grafana dashboard
- [x] **Phase 6** — 100-test pytest suite + run_traffic.py end-to-end integration harness

---

## Test Results

### End-to-End Traffic Test (`run_traffic.py`)

5 incident scenarios fired against the live stack — each injects realistic anomaly data into PostgreSQL, triggers a full triage run, streams SSE events, and verifies routing correctness.

**Run summary (2026-06-07, model: `qwen2.5:3b`):**

| Metric | Result |
|---|---|
| Scenarios | 5 |
| Completed | 5 / 5 |
| Routing mismatches | 0 |
| Confidence level | HIGH on all 5 runs |
| Incidents recorded in DB | 5 |

**Per-scenario results:**

| Scenario | Classified As | Agents Used | Confidence | Time |
|---|---|---|---|---|
| `memory_leak` | memory_leak | Metrics + Log | HIGH | 21.3s |
| `failed_deployment` | deployment_failure | Log + Deployment | HIGH | 9.8s |
| `high_latency` | high_latency | Metrics + Log | HIGH | 9.8s |
| `database_overload` | database_issue | Log + Metrics + Deployment | HIGH | 12.9s |
| `cpu_spike` | cpu_spike | Log + Metrics | HIGH | 8.6s |

To reproduce:
```bash
python run_traffic.py
```

### Unit Tests (100 tests, 4.07s)

```bash
cd orchestrator
pip install pytest pytest-asyncio
pytest ../tests/ -v
# 101 passed in 3.16s
```

| File | Tests | What it covers |
|---|---|---|
| `test_shared_models.py` | 14 | A2A protocol — JSONRPCRequest, Task lifecycle, Artifact, TaskState transitions |
| `test_log_analyzer.py` | 13 | Real kernel OOM messages, asyncpg/gRPC/pgbouncer/nginx error formats, multi-pattern matching |
| `test_metrics_analyzer.py` | 16 | Realistic float values (87.4%, 1847ms), threshold boundaries, baseline delta flagging |
| `test_deployment_analyzer.py` | 7 | Correlation scoring with real CI/CD metadata, ArgoCD rollbacks, commit SHAs |
| `test_diagnosis_prompts.py` | 13 | Prompt builder output — metric values, log samples, version numbers, section headers |
| `test_ollama_parser.py` | 11 | Actual qwen2.5:3b output patterns — preamble text, truncated responses, trailing Note sections, label-format edge case |
| `test_graph_routing.py` | 14 | Full ALERT_ROUTING table, conditional edge logic, LangGraph node structure |

---

## Incident Scenarios

Each scenario writes anomaly data to PostgreSQL, then a real triage run fires against it.

| Scenario | What's Injected | Agents Expected |
|---|---|---|
| `memory_leak` | 30 OOM log entries + memory metrics rising 60% → 94% | Log + Metrics |
| `failed_deployment` | 1 failed deploy record + 25 error logs | Log + Deployment |
| `high_latency` | 20 timeout logs + latency rising 400ms → 1800ms | Log + Metrics |
| `database_overload` | 25 connection pool exhaustion logs + db_connections 70% → 96% | Log + Metrics + Deployment |
| `cpu_spike` | 15 timeout logs + CPU rising 60% → 95% | Metrics + Log |

---

## Prometheus Metrics

10 metrics across 5 agents — unique names per agent to avoid registry collisions.

| Metric | Type | Agent |
|---|---|---|
| `log_agent_tasks_total` | Counter | LogAgent |
| `log_agent_task_duration_seconds` | Histogram | LogAgent |
| `metrics_agent_tasks_total` | Counter | MetricsAgent |
| `metrics_agent_task_duration_seconds` | Histogram | MetricsAgent |
| `deployment_agent_tasks_total` | Counter | DeploymentAgent |
| `deployment_agent_task_duration_seconds` | Histogram | DeploymentAgent |
| `diagnosis_agent_tasks_total` | Counter | DiagnosisAgent |
| `diagnosis_agent_task_duration_seconds` | Histogram | DiagnosisAgent |
| `orchestrator_triage_total` | Counter | Orchestrator |
| `orchestrator_triage_duration_seconds` | Histogram | Orchestrator |

---

## API Reference

| Method | Path | Description |
|---|---|---|
| `POST` | `/triage` | Submit alert for triage — returns `triage_id`, background run starts (202) |
| `GET` | `/triage/{id}/events` | SSE stream — real-time stage events until complete/failed |
| `POST` | `/simulate/{scenario}` | Inject anomaly data and return `alert_description` for `/triage` |
| `GET` | `/` | Single-page frontend UI |

**A2A agent endpoints (each agent, ports 8001–8004):**

| Method | Path | Description |
|---|---|---|
| `GET` | `/.well-known/agent.json` | Agent card — name, capabilities, skills |
| `POST` | `/` | JSON-RPC 2.0 task dispatch |
| `GET` | `/tasks/{id}/events` | SSE stream for per-task progress |

---

## Running Locally

**Prerequisites:** Docker Desktop, [Ollama](https://ollama.com/) with `qwen2.5:3b`

```bash
# Pull the model
ollama pull qwen2.5:3b

# Start all 9 services
docker compose up --build

# UI
open http://localhost:8000

# Grafana
open http://localhost:3000   # admin / admin

# Run all 5 scenarios and verify routing
python run_traffic.py
```

---

## Key Design Decisions

- **Deterministic routing over LLM routing** — alert type → agent list is a static dict, not an LLM decision. Routing is testable, auditable, and never hallucinates.
- **Parallel fan-out with `asyncio.gather`** — all specialist agents start at the same timestamp. Both agents complete within 1 second in live tests; neither waits for the other.
- **Grounded diagnosis prompts** — the Ollama prompt passes actual metric values, error counts, sample log messages, and deployment version numbers from PostgreSQL. The LLM cannot hallucinate evidence that wasn't in the database.
- **Sentence-completion forcing** — the prompt pre-fills `The root cause is` and numbered step prefixes (`1.`, `2.`, etc.). qwen2.5:3b fills in the blank rather than echoing or skipping, which produced empty remediation steps with a templated prompt format.
- **Redis pub/sub for SSE** — the orchestrator publishes to `triage:{id}` at each LangGraph node. The browser EventSource subscribes to the same channel. No polling, no WebSockets, no long-polling.
- **Unique Prometheus metric names per agent** — sharing a name like `a2a_tasks_total` across 5 agents in one Python process causes `ValueError: Duplicated timeseries`. Each agent owns its own counter names.
- **A2A task lifecycle** — every inter-agent call follows `submitted → working → completed/failed`. The TaskStore in Redis tracks state and publishes updates; the SSE endpoint subscribes and forwards to the browser.
