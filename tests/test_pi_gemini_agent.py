import asyncio
import os
import pytest
from urp.agents.pi_gemini_agent import PiGeminiAgent
from urp.core import AgentContext, AgentDescriptor, MessageEnvelope, LastTaskOutcome

@pytest.mark.asyncio
async def test_pi_gemini_agent_real_invocation(tmp_path):
    """
    Test real headless invocation of PiGeminiAgent using Google Vertex Gemini 3.8 Flash.
    Verifies that the agent initializes, runs through the URP lifecycle, and produces a valid response.
    """
    descriptor = AgentDescriptor(
        agent_id="test.pi.gemini.v1",
        name="Test Pi Gemini Agent",
        version="1.0.0",
        capabilities=["READ", "BASH"],
        accepted_message_types=["MESSAGE", "TASK"],
    )

    agent = PiGeminiAgent(descriptor=descriptor)

    context = AgentContext(
        workspace_path=str(tmp_path),
        configuration={
            "workspace_dir": str(tmp_path),
            "provider": "google-vertex",
            "model": "gemini-3.8-flash",
            "thinking_level": "medium",
            "no_session": True,
            "settlement_timeout": 60.0,
        }
    )

    events = []
    task_done = asyncio.Event()

    def on_emit(event: MessageEnvelope):
        events.append(event)
        if event.type in (LastTaskOutcome.TASK_COMPLETED.value, "TASK_FAILED"):
            task_done.set()

    agent.initialize(context=context, emit_callback=on_emit)
    await agent.start()

    msg = MessageEnvelope(
        type="MESSAGE",
        payload={"text": "Answer with the single word 'URP_GEMINI_SUCCESS' and nothing else."},
        sender="tester"
    )

    await agent.send(msg)
    await asyncio.wait_for(task_done.wait(), timeout=60.0)

    result = agent.state["last_process_result"]
    assert result is not None
    assert result.outcome == LastTaskOutcome.TASK_COMPLETED
    assert "URP_GEMINI_SUCCESS" in (result.text or "")

    await agent.shutdown()
