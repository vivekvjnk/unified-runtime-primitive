import asyncio
import os
from pathlib import Path
import pytest

from urp.data_types import (
    AgentDescriptor,
    AgentContext,
    AgentStatus,
    MessageEnvelope,
    LastTaskOutcome,
    FailureCategory,
    ProcessResult,
)
from urp.pi_harness import (
    PiURPAgent,
    PiRpcClient,
)

FAKE_PI_SCRIPT = str(Path(__file__).resolve().parent / "fixtures" / "fake_pi_rpc.py")


class DummyPiURPAgent(PiURPAgent):
    """Concrete subclass of PiURPAgent for integration testing."""
    def __init__(self, descriptor: AgentDescriptor = None):
        if descriptor is None:
            descriptor = AgentDescriptor(
                agent_id="test.pi_agent.v1",
                name="Test Pi Agent",
                version="1.0.0",
                capabilities=["test"],
                accepted_message_types=["TASK"],
            )
        super().__init__(descriptor)


class FailingPreconditionAgent(DummyPiURPAgent):
    async def _check_preconditions(self, message: MessageEnvelope) -> tuple[bool, str]:
        return False, "Precondition artificially failed for test"


class FailingPostconditionAgent(DummyPiURPAgent):
    async def _check_postconditions(self, message: MessageEnvelope, result: ProcessResult) -> tuple[bool, str]:
        return False, "Postcondition artificially failed for test"


@pytest.fixture
def agent_context(tmp_path):
    return AgentContext(
        configuration={
            "workspace_dir": str(tmp_path),
            "no_session": True,
            "executable_path": FAKE_PI_SCRIPT,
        }
    )


@pytest.mark.asyncio
async def test_pi_urp_agent_lifecycle(agent_context):
    """Test 1: Full URP lifecycle state transitions and subprocess binding."""
    agent = DummyPiURPAgent()
    emitted = []

    def emit_cb(msg: MessageEnvelope):
        emitted.append(msg)

    assert agent.state["status"] == AgentStatus.UNINITIALIZED

    agent.initialize(agent_context, emit_cb)
    assert agent.state["status"] == AgentStatus.INITIALIZED
    assert agent.pi_client is not None

    await agent.start()
    assert agent.state["status"] == AgentStatus.WAITING
    assert agent.pi_client.is_running is True

    await agent.shutdown()
    assert agent.state["status"] == AgentStatus.TERMINATED


@pytest.mark.asyncio
async def test_pi_urp_agent_mailbox_execution(agent_context):
    """Test 2: Mailbox message processing, outcome emission, and acknowledgment hold."""
    agent = DummyPiURPAgent()
    emitted = []
    task_done_event = asyncio.Event()

    def emit_cb(msg: MessageEnvelope):
        emitted.append(msg)
        if msg.type in (LastTaskOutcome.TASK_COMPLETED.value, "TASK_FAILED"):
            task_done_event.set()

    agent.initialize(agent_context, emit_cb)
    await agent.start()

    msg = MessageEnvelope(
        type="TASK",
        payload={"text": "Say EXACTLY 'VHL_PI_URP_TEST_OK' and nothing else."},
        sender="workflow_controller"
    )

    await agent.send(msg)

    await asyncio.wait_for(task_done_event.wait(), timeout=15.0)

    assert agent.state["last_process_result"] is not None
    assert agent.state["last_process_result"].outcome == LastTaskOutcome.TASK_COMPLETED
    assert "VHL_PI_URP_TEST_OK" in (agent.state["last_process_result"].payload.text or "")

    await agent.shutdown()


@pytest.mark.asyncio
async def test_pi_urp_agent_telemetry_emission(agent_context):
    """Test 3: Progress telemetry and tool event emission from Pi to URP emit callback."""
    agent = DummyPiURPAgent()
    emitted = []
    task_done_event = asyncio.Event()

    def emit_cb(msg: MessageEnvelope):
        emitted.append(msg)
        if msg.type == LastTaskOutcome.TASK_COMPLETED.value:
            task_done_event.set()

    agent.initialize(agent_context, emit_cb)
    await agent.start()

    msg = MessageEnvelope(
        type="TASK",
        payload={"text": "Run bash command 'echo telemetry_vhl_test' using your tools."},
        sender="workflow_controller"
    )

    await agent.send(msg)
    await asyncio.wait_for(task_done_event.wait(), timeout=20.0)

    emitted_types = [m.type for m in emitted]
    assert "AGENT_PROGRESS_UPDATE" in emitted_types or "AGENT_TOOL_START" in emitted_types

    await agent.shutdown()


@pytest.mark.asyncio
async def test_pi_urp_agent_conditions_validation(agent_context):
    """Test 4: Precondition and postcondition failure enforcement."""
    # 1. Failing Precondition
    fail_pre_agent = FailingPreconditionAgent()
    emitted_pre = []
    pre_done_event = asyncio.Event()

    def pre_cb(msg: MessageEnvelope):
        emitted_pre.append(msg)
        if msg.type == "TASK_PRECONDITIONS_VIOLATED":
            pre_done_event.set()

    fail_pre_agent.initialize(agent_context, pre_cb)
    await fail_pre_agent.start()

    msg = MessageEnvelope(type="TASK", payload={"text": "Hello"}, sender="controller")
    await fail_pre_agent.send(msg)
    await asyncio.wait_for(pre_done_event.wait(), timeout=10.0)

    assert fail_pre_agent.state["last_process_result"].category == FailureCategory.PRECONDITION_FAILURE
    await fail_pre_agent.shutdown()

    # 2. Failing Postcondition
    fail_post_agent = FailingPostconditionAgent()
    emitted_post = []
    post_done_event = asyncio.Event()

    def post_cb(msg: MessageEnvelope):
        emitted_post.append(msg)
        if msg.type == "TASK_POSTCONDITIONS_VIOLATED":
            post_done_event.set()

    fail_post_agent.initialize(agent_context, post_cb)
    await fail_post_agent.start()

    msg = MessageEnvelope(type="TASK", payload={"text": "Say 'Hi'"}, sender="controller")
    await fail_post_agent.send(msg)
    await asyncio.wait_for(post_done_event.wait(), timeout=30.0)

    assert fail_post_agent.state["last_process_result"].category == FailureCategory.POSTCONDITION_FAILURE
    await fail_post_agent.shutdown()


@pytest.mark.asyncio
async def test_pi_urp_agent_infrastructure_failure(agent_context):
    """Test 5: Subprocess crash during execution resulting in INFRASTRUCTURE_FAILURE."""
    agent = DummyPiURPAgent()
    emitted = []
    task_done_event = asyncio.Event()

    def emit_cb(msg: MessageEnvelope):
        emitted.append(msg)
        if msg.type == "TASK_FAILED":
            task_done_event.set()

    agent.initialize(agent_context, emit_cb)
    await agent.start()

    if agent.pi_client and agent.pi_client._process:
        agent.pi_client._process.terminate()
        await agent.pi_client._process.wait()

    msg = MessageEnvelope(type="TASK", payload={"text": "This should fail"}, sender="controller")
    await agent.send(msg)

    await asyncio.wait_for(task_done_event.wait(), timeout=10.0)

    assert agent.state["last_process_result"].outcome == LastTaskOutcome.TASK_FAILED
    assert agent.state["last_process_result"].category == FailureCategory.INFRASTRUCTURE_FAILURE

    await agent.shutdown()


@pytest.mark.asyncio
async def test_pi_urp_agent_multiturn_loop(agent_context):
    """Test 6: Multi-turn mailbox loop processes consecutive tasks cleanly."""
    agent = DummyPiURPAgent()
    emitted = []
    done_counter = 0

    def emit_cb(msg: MessageEnvelope):
        nonlocal done_counter
        emitted.append(msg)
        if msg.type == LastTaskOutcome.TASK_COMPLETED.value:
            done_counter += 1

    agent.initialize(agent_context, emit_cb)
    await agent.start()

    msg1 = MessageEnvelope(type="TASK", payload={"text": "Turn 1: Say 'FIRST'"}, sender="controller")
    msg2 = MessageEnvelope(type="TASK", payload={"text": "Turn 2: Say 'SECOND'"}, sender="controller")

    await agent.send(msg1)
    await agent.send(msg2)

    timeout = 15.0
    start_time = asyncio.get_event_loop().time()
    while done_counter < 2 and (asyncio.get_event_loop().time() - start_time) < timeout:
        await asyncio.sleep(0.1)

    assert done_counter == 2
    await agent.shutdown()


@pytest.mark.asyncio
async def test_pi_urp_agent_timeout_handling(tmp_path):
    """Test 7: Configurable settlement timeout aborts agent run and returns AGENTIC_FAILURE."""
    context = AgentContext(
        configuration={
            "workspace_dir": str(tmp_path),
            "no_session": True,
            "executable_path": FAKE_PI_SCRIPT,
            "settlement_timeout": 0.5,
        }
    )

    agent = DummyPiURPAgent()
    emitted = []
    task_done_event = asyncio.Event()

    def emit_cb(msg: MessageEnvelope):
        emitted.append(msg)
        if msg.type == "TASK_FAILED":
            task_done_event.set()

    agent.initialize(context, emit_cb)
    await agent.start()

    msg = MessageEnvelope(
        type="TASK",
        payload={"text": "SLOW_PROMPT: Perform exhaustive 3D component layout optimization for 50 ICs."},
        sender="controller"
    )

    await agent.send(msg)
    await asyncio.wait_for(task_done_event.wait(), timeout=10.0)

    result = agent.state["last_process_result"]
    assert result is not None
    assert result.outcome == LastTaskOutcome.TASK_FAILED
    assert result.category == FailureCategory.AGENTIC_FAILURE
    assert "timed out after 0.5 seconds" in result.payload.text

    await agent.shutdown()
