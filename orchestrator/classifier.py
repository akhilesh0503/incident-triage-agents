from __future__ import annotations

import os

import httpx

_OLLAMA_BASE_URL = os.environ.get("OLLAMA_BASE_URL", "http://localhost:11434")
_OLLAMA_MODEL    = os.environ.get("OLLAMA_MODEL", "qwen2.5:3b")

_VALID_TYPES = frozenset([
    "memory_leak",
    "high_latency",
    "deployment_failure",
    "database_issue",
    "cpu_spike",
    "unknown",
])

_PROMPT = """\
You are an SRE alert classifier. Classify the following alert into exactly one category.

Categories:
- memory_leak: high memory usage, OOM errors, memory growing over time
- high_latency: slow response times, timeouts, high p95/p99 latency
- deployment_failure: errors after a deployment, startup failures, rollback needed
- database_issue: connection pool exhausted, slow queries, database unreachable
- cpu_spike: unusually high CPU utilization, CPU-bound process
- unknown: does not clearly fit any category above

Alert: {alert_description}

Respond with EXACTLY ONE WORD from the category list above. No explanation."""

# Deterministic routing: each alert type maps to which specialist agents run
ALERT_ROUTING: dict[str, list[str]] = {
    "memory_leak":        ["log", "metrics"],
    "high_latency":       ["log", "metrics"],
    "deployment_failure": ["log", "deployment"],
    "database_issue":     ["log", "metrics", "deployment"],
    "cpu_spike":          ["metrics", "log"],
    "unknown":            ["log", "metrics", "deployment"],
}


async def classify_alert(alert_description: str, timeout: float = 30.0) -> str:
    prompt = _PROMPT.format(alert_description=alert_description)
    payload = {
        "model": _OLLAMA_MODEL,
        "prompt": prompt,
        "stream": False,
        "options": {"temperature": 0.0, "num_predict": 10},
    }
    try:
        async with httpx.AsyncClient(timeout=timeout) as client:
            resp = await client.post(f"{_OLLAMA_BASE_URL}/api/generate", json=payload)
            resp.raise_for_status()
            raw = resp.json()["response"].strip().lower().split()[0]
            # Normalize to known categories
            if raw in _VALID_TYPES:
                return raw
            # Fuzzy fallback
            for t in _VALID_TYPES:
                if t.startswith(raw) or raw.startswith(t[:5]):
                    return t
            return "unknown"
    except Exception:
        return "unknown"
