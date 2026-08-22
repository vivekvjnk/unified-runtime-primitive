import asyncio
import os
from pathlib import Path
import pytest

from urp.data_types import AgentDescriptor, AgentContext, MessageEnvelope, LastTaskOutcome
from examples.host import URPHost
from examples.layout_engineer.layout_engineer_agent import LayoutEngineerURPAgent

FAKE_PI_SCRIPT = str(Path(__file__).resolve().parent / "fixtures" / "fake_pi_rpc.py")


@pytest.mark.asyncio
async def test_layout_engineer_hosted_execution(tmp_path):
    """Test URPHost initializing, sending placement messages, and receiving events from LayoutEngineerURPAgent."""
    descriptor = AgentDescriptor(
        agent_id="vhl.layout_engineer.v1",
        name="Layout Engineer Agent",
        version="1.0.0",
        capabilities=["pcb_placement", "layout_optimization", "netlist_analysis"],
        accepted_message_types=["LAYOUT_PLACEMENT_TASK", "TASK"],
    )

    host = URPHost(agent_class=LayoutEngineerURPAgent, descriptor=descriptor)

    context = AgentContext(
        configuration={
            "workspace_dir": str(tmp_path),
            "no_session": True,
            "executable_path": FAKE_PI_SCRIPT,
        }
    )

    # 1. Initialize and start agent via host
    agent = await host.initialize_and_start(context)
    assert agent is not None
    assert agent.pi_client is not None
    assert agent.pi_client.is_running is True

    # 2. Send placement message via host
    msg_id = await host.send_message(
        message_type="LAYOUT_PLACEMENT_TASK",
        payload={"text": "Place MCU U1 at board center (X:0, Y:0)."},
        sender="standalone_host"
    )
    assert msg_id is not None

    # 3. Await outcome event emitted to host queue
    outcome_event = None
    while True:
        evt = await host.get_next_event(timeout=10.0)
        if evt.type in (LastTaskOutcome.TASK_COMPLETED.value, LastTaskOutcome.TASK_FAILED.value):
            outcome_event = evt
            break

    assert outcome_event is not None
    assert outcome_event.type == LastTaskOutcome.TASK_COMPLETED.value
    assert "Mock layout placement result" in (outcome_event.payload.payload.text or "")

    # Acknowledge outcome on agent
    agent.acknowledge_outcome()

    # 4. Shutdown host
    await host.shutdown()
    assert host.agent is None
