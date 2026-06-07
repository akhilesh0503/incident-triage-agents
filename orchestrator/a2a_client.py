from __future__ import annotations

import asyncio
import uuid
from typing import Any

import httpx


async def send_task_and_wait(
    base_url: str,
    payload: dict[str, Any],
    timeout: float = 60.0,
) -> dict[str, Any]:
    """Send a tasks/send JSON-RPC call and poll until the task completes."""
    rpc_payload = {
        "jsonrpc": "2.0",
        "id": str(uuid.uuid4()),
        "method": "tasks/send",
        "params": {
            "message": {
                "role": "user",
                "parts": [{"type": "data", "content": payload}],
            }
        },
    }

    async with httpx.AsyncClient(timeout=timeout) as client:
        resp = await client.post(base_url, json=rpc_payload)
        resp.raise_for_status()
        body = resp.json()
        if body.get("error"):
            raise RuntimeError(f"tasks/send error: {body['error']}")
        task_id = body["result"]["id"]

        deadline = asyncio.get_event_loop().time() + timeout
        while asyncio.get_event_loop().time() < deadline:
            await asyncio.sleep(0.5)
            resp = await client.post(base_url, json={
                "jsonrpc": "2.0",
                "id": str(uuid.uuid4()),
                "method": "tasks/get",
                "params": {"id": task_id},
            })
            resp.raise_for_status()
            body = resp.json()
            if body.get("error"):
                raise RuntimeError(f"tasks/get error: {body['error']}")
            task = body["result"]
            state = task["status"]["state"]

            if state == "completed":
                artifacts = task.get("artifacts", [])
                if artifacts:
                    return artifacts[0]["parts"][0]["data"]
                return {}
            if state in ("failed", "canceled"):
                msg = task["status"].get("message", "unknown error")
                raise RuntimeError(f"Task {task_id} ended with {state}: {msg}")

        raise TimeoutError(f"Task {task_id} timed out after {timeout}s")


async def discover_agent_card(base_url: str, timeout: float = 5.0) -> dict[str, Any]:
    async with httpx.AsyncClient(timeout=timeout) as client:
        resp = await client.get(f"{base_url}/.well-known/agent-card.json")
        resp.raise_for_status()
        return resp.json()
