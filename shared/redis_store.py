from __future__ import annotations

import json
import uuid
from typing import Any, AsyncIterator, Optional

import redis.asyncio as redis

from shared.a2a_models import Artifact, Message, Part, Task, TaskState, TaskStatus

_TASK_TTL = 3600
_TASK_PREFIX = "task:"
_EVENTS_PREFIX = "task_events:"


class TaskStore:
    def __init__(self, redis_url: str) -> None:
        self._url = redis_url
        self._redis: redis.Redis

    async def connect(self) -> None:
        self._redis = redis.from_url(self._url, decode_responses=True)

    async def disconnect(self) -> None:
        await self._redis.aclose()

    # ------------------------------------------------------------------
    # Core persistence
    # ------------------------------------------------------------------

    async def save(self, task: Task) -> None:
        key = f"{_TASK_PREFIX}{task.id}"
        await self._redis.setex(key, _TASK_TTL, task.model_dump_json())
        await self._redis.publish(f"{_EVENTS_PREFIX}{task.id}", task.model_dump_json())

    async def get(self, task_id: str) -> Optional[Task]:
        raw = await self._redis.get(f"{_TASK_PREFIX}{task_id}")
        if raw is None:
            return None
        return Task.model_validate_json(raw)

    # ------------------------------------------------------------------
    # High-level helpers
    # ------------------------------------------------------------------

    async def create(self, agent_name: str, message_text: str) -> Task:
        task = Task(
            id=str(uuid.uuid4()),
            status=TaskStatus(state=TaskState.SUBMITTED),
            messages=[
                Message(role="user", parts=[Part(type="text", text=message_text)])
            ],
            metadata={"agent": agent_name},
        )
        await self.save(task)
        return task

    async def update_status(
        self, task_id: str, state: TaskState, message: Optional[str] = None
    ) -> Optional[Task]:
        task = await self.get(task_id)
        if task is None:
            return None
        task.status = TaskStatus(state=state, message=message)
        await self.save(task)
        return task

    async def complete_task(self, task_id: str, result: Any) -> Optional[Task]:
        task = await self.get(task_id)
        if task is None:
            return None
        task.status = TaskStatus(state=TaskState.COMPLETED)
        task.artifacts = [
            Artifact(
                name="result",
                parts=[Part(type="data", data=result)],
            )
        ]
        await self.save(task)
        return task

    async def fail_task(self, task_id: str, error: str) -> Optional[Task]:
        task = await self.get(task_id)
        if task is None:
            return None
        task.status = TaskStatus(state=TaskState.FAILED, message=error)
        await self.save(task)
        return task

    async def cancel_task(self, task_id: str) -> Optional[Task]:
        task = await self.get(task_id)
        if task is None:
            return None
        task.status = TaskStatus(state=TaskState.CANCELED)
        await self.save(task)
        return task

    # ------------------------------------------------------------------
    # SSE streaming
    # ------------------------------------------------------------------

    async def subscribe(self, task_id: str) -> AsyncIterator[Task]:
        pubsub = self._redis.pubsub()
        await pubsub.subscribe(f"{_EVENTS_PREFIX}{task_id}")
        try:
            async for msg in pubsub.listen():
                if msg["type"] != "message":
                    continue
                task = Task.model_validate_json(msg["data"])
                yield task
                if task.status.state in (
                    TaskState.COMPLETED,
                    TaskState.FAILED,
                    TaskState.CANCELED,
                ):
                    break
        finally:
            await pubsub.unsubscribe(f"{_EVENTS_PREFIX}{task_id}")
            await pubsub.aclose()
