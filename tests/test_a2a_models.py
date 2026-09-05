"""Unit tests for urp.a2a models and bidirectional translator."""

import pytest
from uuid import uuid4

from urp.a2a.models import (
    AgentCard,
    Artifact,
    Message as A2AMessage,
    Part,
    Role,
    SendMessageRequest,
    StreamResponse,
    TaskState,
    TaskStatus,
    TaskStatusUpdateEvent,
)
from urp.a2a.translator import A2ATranslator
from urp.core.data_types import (
    AgentDescriptor,
    LastTaskOutcome,
    MessageEnvelope,
    ProcessResult,
)


def test_a2a_message_creation_and_text_extraction():
    msg = A2AMessage.from_text(
        text="Hello A2A world!",
        role=Role.ROLE_USER,
        context_id="ctx-123",
        task_id="task-456",
    )
    assert msg.get_text() == "Hello A2A world!"
    assert msg.role == Role.ROLE_USER
    assert msg.context_id == "ctx-123"
    assert msg.task_id == "task-456"

    # Multiple parts
    msg.parts.append(Part(text="Second line of text"))
    assert msg.get_text() == "Hello A2A world!\nSecond line of text"


def test_a2a_message_serialization():
    msg = A2AMessage.from_text("Analyze repo", role=Role.ROLE_USER, context_id="ctx-1")
    dumped = msg.model_dump(by_alias=True)
    assert "messageId" in dumped
    assert dumped["contextId"] == "ctx-1"
    assert dumped["parts"][0]["text"] == "Analyze repo"
    assert dumped["parts"][0]["mediaType"] == "text/plain"


def test_translator_a2a_message_to_envelope():
    msg = A2AMessage.from_text(
        text="Run unit tests",
        context_id="session-1",
        task_id="task-99",
    )
    envelope = A2ATranslator.a2a_message_to_envelope(msg, sender="external_client")

    assert isinstance(envelope, MessageEnvelope)
    assert envelope.type == "MESSAGE"
    assert envelope.sender == "external_client"
    assert envelope.context_id == "session-1"
    assert envelope.task_id == "task-99"
    assert envelope.payload["text"] == "Run unit tests"
    assert len(envelope.payload["parts"]) == 1


def test_translator_envelope_to_a2a_message():
    envelope = MessageEnvelope(
        type="MESSAGE",
        payload={"text": "Tests completed successfully"},
        sender="agent_kernel",
        context_id="session-1",
        task_id="task-99",
    )
    a2a_msg = A2ATranslator.envelope_to_a2a_message(envelope, role=Role.ROLE_AGENT)

    assert a2a_msg.role == Role.ROLE_AGENT
    assert a2a_msg.context_id == "session-1"
    assert a2a_msg.task_id == "task-99"
    assert a2a_msg.get_text() == "Tests completed successfully"


def test_translator_stream_response_events():
    # 1. Tool execution event
    tool_env = MessageEnvelope(
        type="AGENT_TOOL_START",
        payload={"toolName": "bash", "args": {"command": "pytest"}},
        sender="agent_kernel",
        context_id="session-1",
        task_id="task-1",
    )
    stream_resp = A2ATranslator.envelope_to_stream_response(tool_env)
    assert stream_resp is not None
    assert stream_resp.status_update is not None
    assert stream_resp.status_update.status.state == TaskState.TASK_STATE_WORKING
    assert stream_resp.status_update.metadata["toolName"] == "bash"

    # 2. Terminal completion event
    comp_env = MessageEnvelope(
        type="TASK_COMPLETED",
        payload={"text": "Done!", "artifacts": [{"name": "report.txt", "content": "All passed"}]},
        sender="agent_kernel",
        context_id="session-1",
        task_id="task-1",
    )
    stream_resp_comp = A2ATranslator.envelope_to_stream_response(comp_env)
    assert stream_resp_comp is not None
    assert stream_resp_comp.status_update is not None
    assert stream_resp_comp.status_update.status.state == TaskState.TASK_STATE_COMPLETED
    assert "Done!" in stream_resp_comp.status_update.status.message.get_text()


def test_translator_process_result_to_task():
    res = ProcessResult(
        outcome=LastTaskOutcome.TASK_COMPLETED,
        text="Created output file",
        artifacts=[{"id": "art-1", "name": "result.json", "content": '{"ok": true}'}],
        metadata={"cost": 0.02},
    )
    task = A2ATranslator.process_result_to_task("t-123", "c-456", res)

    assert task.id == "t-123"
    assert task.context_id == "c-456"
    assert task.status.state == TaskState.TASK_STATE_COMPLETED
    assert task.status.message.get_text() == "Created output file"
    assert len(task.artifacts) == 1
    assert task.artifacts[0].name == "result.json"
    assert task.metadata["cost"] == 0.02


def test_translator_descriptor_to_agent_card():
    desc = AgentDescriptor(
        agent_id="test.coder.v1",
        name="Test Coder",
        version="1.2.0",
        capabilities=["CODE_GENERATION", "BASH"],
        accepted_message_types=["MESSAGE"],
    )
    card = A2ATranslator.descriptor_to_agent_card(desc, base_url="http://localhost:8000")

    assert isinstance(card, AgentCard)
    assert card.name == "Test Coder"
    assert card.version == "1.2.0"
    assert len(card.supported_interfaces) == 1
    assert card.supported_interfaces[0].protocol_binding == "HTTP+JSON"
    assert len(card.skills) == 2
    skill_names = [s.name for s in card.skills]
    assert "CODE_GENERATION" in skill_names
