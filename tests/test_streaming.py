"""Tests for URP first-class streaming support."""

import asyncio
import pytest
from typing import List

from urp.core import AbstractURPAgent, AgentContext, AgentDescriptor, MessageEnvelope, ProcessResult, LastTaskOutcome


class StreamingEchoAgent(AbstractURPAgent):
    """Reference agent that emits progressive chunks during execution."""

    def _on_initialize(self, context: AgentContext) -> None:
        pass

    async def process(self, message: MessageEnvelope) -> ProcessResult:
        text = message.payload.get("text", "")
        words = text.split()

        # Emit progressive words as streaming chunks
        for word in words:
            await self.emit_chunk(f"{word} ", event_type="TEXT_DELTA")
            await asyncio.sleep(0.01)

        return ProcessResult(
            outcome=LastTaskOutcome.TASK_COMPLETED,
            text=f"Echo: {text}",
        )


@pytest.mark.asyncio
async def test_streaming_enabled_emits_chunks():
    descriptor = AgentDescriptor(
        agent_id="test.streamer",
        name="Streaming Agent",
        capabilities=["STREAMING"],
        accepted_message_types=["MESSAGE"],
    )
    agent = StreamingEchoAgent(descriptor)

    emitted_events: List[MessageEnvelope] = []

    async def on_event(evt: MessageEnvelope):
        emitted_events.append(evt)

    agent.initialize(AgentContext(), on_event)
    await agent.start()

    # Send message with streaming=True
    msg = MessageEnvelope(
        type="MESSAGE",
        payload={"text": "alpha beta gamma"},
        sender="test_client",
        context_id="ctx-1",
        task_id="task-1",
        streaming=True,
    )
    await agent.send(msg)

    # Wait for completion
    for _ in range(50):
        if any(e.type == "TASK_COMPLETED" for e in emitted_events):
            break
        await asyncio.sleep(0.05)

    await agent.shutdown()

    # Verify that TEXT_DELTA events were emitted
    delta_events = [e for e in emitted_events if e.type == "TEXT_DELTA"]
    assert len(delta_events) == 3
    assert delta_events[0].payload["delta"] == "alpha "
    assert delta_events[1].payload["delta"] == "beta "
    assert delta_events[2].payload["delta"] == "gamma "
    assert delta_events[0].task_id == "task-1"
    assert delta_events[0].context_id == "ctx-1"

    # Verify terminal completion
    comp_events = [e for e in emitted_events if e.type == "TASK_COMPLETED"]
    assert len(comp_events) == 1
    assert comp_events[0].payload.text == "Echo: alpha beta gamma"


@pytest.mark.asyncio
async def test_streaming_disabled_suppresses_chunks():
    descriptor = AgentDescriptor(
        agent_id="test.streamer",
        name="Streaming Agent",
        capabilities=["STREAMING"],
        accepted_message_types=["MESSAGE"],
    )
    agent = StreamingEchoAgent(descriptor)

    emitted_events: List[MessageEnvelope] = []

    async def on_event(evt: MessageEnvelope):
        emitted_events.append(evt)

    agent.initialize(AgentContext(), on_event)
    await agent.start()

    # Send message with streaming=False (default)
    msg = MessageEnvelope(
        type="MESSAGE",
        payload={"text": "one two three"},
        sender="test_client",
        context_id="ctx-2",
        task_id="task-2",
        streaming=False,
    )
    await agent.send(msg)

    # Wait for completion
    for _ in range(50):
        if any(e.type == "TASK_COMPLETED" for e in emitted_events):
            break
        await asyncio.sleep(0.05)

    await agent.shutdown()

    # Verify that NO TEXT_DELTA events were emitted
    delta_events = [e for e in emitted_events if e.type == "TEXT_DELTA"]
    assert len(delta_events) == 0

    # Terminal completion must still arrive
    comp_events = [e for e in emitted_events if e.type == "TASK_COMPLETED"]
    assert len(comp_events) == 1
    assert comp_events[0].payload.text == "Echo: one two three"
