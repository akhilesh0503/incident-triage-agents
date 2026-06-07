from __future__ import annotations

import os
import re
from typing import Any

import httpx


_OLLAMA_BASE_URL = os.environ.get("OLLAMA_BASE_URL", "http://localhost:11434")
_OLLAMA_MODEL    = os.environ.get("OLLAMA_MODEL", "qwen2.5:3b")

_ROOT_CAUSE_RE       = re.compile(r"ROOT CAUSE:\s*(.+?)(?=\nCONFIDENCE:|\Z)", re.DOTALL)
_CONFIDENCE_RE       = re.compile(r"CONFIDENCE:\s*(HIGH|MEDIUM|LOW)")
_REMEDIATION_RE      = re.compile(r"REMEDIATION STEPS:\s*(.+)", re.DOTALL)
_REMEDIATION_ITEM_RE = re.compile(r"^\d+\.\s+(.+)", re.MULTILINE)


async def call_ollama(prompt: str, timeout: float = 120.0) -> dict[str, Any]:
    payload = {
        "model": _OLLAMA_MODEL,
        "prompt": prompt,
        "stream": False,
        "options": {"temperature": 0.2, "num_predict": 512},
    }
    async with httpx.AsyncClient(timeout=timeout) as client:
        resp = await client.post(f"{_OLLAMA_BASE_URL}/api/generate", json=payload)
        resp.raise_for_status()
        raw_text: str = resp.json()["response"]

    return _parse_response(raw_text)


def _parse_response(text: str) -> dict[str, Any]:
    root_cause = ""
    m = _ROOT_CAUSE_RE.search(text)
    if m:
        root_cause = m.group(1).strip()

    confidence = "MEDIUM"
    m = _CONFIDENCE_RE.search(text)
    if m:
        confidence = m.group(1)

    remediation_steps: list[str] = []
    m = _REMEDIATION_RE.search(text)
    if m:
        block = m.group(1)
        remediation_steps = _REMEDIATION_ITEM_RE.findall(block)

    if not root_cause:
        # Fallback: use first non-empty line of the raw text
        root_cause = next((l.strip() for l in text.splitlines() if l.strip()), text[:200])

    return {
        "root_cause": root_cause,
        "confidence": confidence,
        "remediation_steps": remediation_steps,
        "raw_response": text,
    }
