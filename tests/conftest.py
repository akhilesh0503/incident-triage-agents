from __future__ import annotations

import os
import sys
from typing import Any
from unittest.mock import AsyncMock, MagicMock

import pytest

sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))

# ── asyncpg record fake ────────────────────────────────────────────────────────

class FakeRecord(dict):
    """Minimal asyncpg.Record stand-in: supports row["column"] access."""
    pass


def make_records(*rows: dict) -> list[FakeRecord]:
    return [FakeRecord(r) for r in rows]


# ── asyncpg connection mock ────────────────────────────────────────────────────

def make_conn(fetch_results=None, fetchrow_result=None):
    conn = AsyncMock()
    conn.fetch.return_value    = make_records(*(fetch_results or []))
    conn.fetchrow.return_value = FakeRecord(fetchrow_result) if fetchrow_result else None
    return conn


# ── pytest markers ─────────────────────────────────────────────────────────────

def pytest_configure(config):
    config.addinivalue_line(
        "markers",
        "integration: requires running docker-compose stack (postgres, redis, agents)",
    )
