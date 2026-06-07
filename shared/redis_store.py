from __future__ import annotations

import logging
from typing import AsyncIterator, Optional

import redis.asyncio as redis

from shared.a2a_models import Task, TaskState, TaskStatus

logger = logging.getLogger(__name__)

_TASK_TTL = 3600
_TASK_PREFIX = "task:"
_EVENTS_PREFIX = "task_events:"


class TaskStore:
    def __init__(self, redis_client: redis.Redis) -> None:
        self._redis = redis_client

    async def save(self, task: Task) -> None:
        key = f"{_TASK_PREFIX}{task.id}"
        await self._redis.setex(key, _TASK_TTL, task.model_dump_json())
        await self._redis.publish(f"{_EVENTS_PREFIX}{task.id}", task.model_dump_json())

    async def get(self, task_id: str) -> Optional[Task]:
        raw = await self._redis.get(f"{_TASK_PREFIX}{task_id}")
        if raw is None:
            return None
        return Task.model_validate_json(raw)

    async def update_status(
        self, task_id: str, state: TaskState, message: Optional[str] = None
    ) -> Optional[Task]:
        task = await self.get(task_id)
        if task is None:
            return None
        task.status = TaskStatus(state=state, message=message)
        await self.save(task)
        return task

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
