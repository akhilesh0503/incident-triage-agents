from __future__ import annotations

import json
import uuid

import pytest

from shared.a2a_models import (
    A2AErrorCode,
    Artifact,
    JSONRPCError,
    JSONRPCRequest,
    JSONRPCResponse,
    Message,
    Part,
    Task,
    TaskState,
    TaskStatus,
)


class TestTask:
    def test_task_gets_unique_id_by_default(self):
        t1 = Task(status=TaskStatus(state=TaskState.SUBMITTED))
        t2 = Task(status=TaskStatus(state=TaskState.SUBMITTED))
        assert t1.id != t2.id
        assert uuid.UUID(t1.id)  # valid UUID

    def test_task_status_state_enum(self):
        for state in TaskState:
            t = Task(status=TaskStatus(state=state))
            assert t.status.state == state

    def test_task_serialises_and_deserialises(self):
        t = Task(
            status=TaskStatus(state=TaskState.WORKING, message="running"),
            messages=[Message(role="user", parts=[Part(type="text", text="hello")])],
        )
        raw = t.model_dump_json()
        restored = Task.model_validate_json(raw)
        assert restored.id == t.id
        assert restored.status.state == TaskState.WORKING
        assert restored.messages[0].parts[0].text == "hello"

    def test_task_with_artifact(self):
        t = Task(
            status=TaskStatus(state=TaskState.COMPLETED),
            artifacts=[Artifact(name="result", parts=[Part(type="data", data={"score": 42})])],
        )
        assert t.artifacts[0].parts[0].data["score"] == 42


class TestJSONRPC:
    def test_request_generates_id_when_omitted(self):
        req = JSONRPCRequest(method="tasks/get")
        assert req.id
        assert uuid.UUID(req.id)

    def test_request_uses_provided_id(self):
        req = JSONRPCRequest(id="my-id-123", method="tasks/get")
        assert req.id == "my-id-123"

    def test_request_params_defaults_to_empty_dict(self):
        req = JSONRPCRequest(method="tasks/get")
        assert req.params == {}

    def test_response_with_result(self):
        resp = JSONRPCResponse(id="1", result={"task_id": "abc"})
        assert resp.result["task_id"] == "abc"
        assert resp.error is None

    def test_response_with_error(self):
        resp = JSONRPCResponse(
            id="1",
            error=JSONRPCError(code=A2AErrorCode.TASK_NOT_FOUND, message="not found"),
        )
        assert resp.error.code == -32001
        assert resp.result is None

    def test_error_codes_are_negative(self):
        assert A2AErrorCode.TASK_NOT_FOUND < 0
        assert A2AErrorCode.METHOD_NOT_FOUND < 0
        assert A2AErrorCode.INVALID_REQUEST < 0


class TestTaskStateTransitions:
    def test_terminal_states(self):
        terminal = {TaskState.COMPLETED, TaskState.FAILED, TaskState.CANCELED}
        non_terminal = {TaskState.SUBMITTED, TaskState.WORKING, TaskState.INPUT_REQUIRED}
        assert terminal | non_terminal == set(TaskState)

    def test_state_values_are_strings(self):
        assert TaskState.SUBMITTED == "submitted"
        assert TaskState.COMPLETED == "completed"
        assert TaskState.FAILED == "failed"
