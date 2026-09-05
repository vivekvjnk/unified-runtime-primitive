import asyncio
import pytest
from urp import (
    AbstractURPAgent,
    AgentDescriptor,
    AgentContext,
    MessageEnvelope,
    AgentStatus,
    ProcessResult,
    LastTaskOutcome,
    ProcessResultPayload,
)

class MockAgent(AbstractURPAgent):
    def _on_initialize(self, context):
        self.initialized_called = True

    async def process(self, message: MessageEnvelope) -> ProcessResult:
        await self.emit(MessageEnvelope(
            type="ECHO",
            payload=message.payload,
            sender=self.descriptor.agent_id,
            context_id=message.context_id,
            task_id=message.task_id
        ))
        return ProcessResult(
            outcome=LastTaskOutcome.TASK_COMPLETED,
            text=f"Processed: {message.payload}",
            artifacts=[{"name": "test_artifact", "path": "test.txt"}]
        )

@pytest.mark.asyncio
async def test_agent_lifecycle():
    descriptor = AgentDescriptor(
        agent_id="test-agent",
        name="Test Agent",
        version="0.1.0",
        description="A test agent",
        capabilities=["echo"],
        accepted_message_types=["QUERY"]
    )
    
    # Verify A2A AgentCard export
    card = descriptor.to_agent_card()
    assert card["name"] == "Test Agent"
    assert card["description"] == "A test agent"
    assert "echo" in card["capabilities"]
    
    agent = MockAgent(descriptor)
    assert agent._state.status == AgentStatus.UNINITIALIZED
    
    events = []
    def emit_callback(event):
        events.append(event)
        
    context = AgentContext(workspace_path="/tmp/test", custom_param="active")
    agent.initialize(context, emit_callback)
    assert agent._state.status == AgentStatus.INITIALIZED
    assert agent.initialized_called
    assert agent.context.workspace_path == "/tmp/test"
    assert agent.context.custom_param == "active"
    
    await agent.start()
    assert agent._state.status == AgentStatus.WAITING
    
    # Send a message with context_id and task_id
    msg = MessageEnvelope(
        type="QUERY",
        payload="Hello URP",
        sender="tester",
        receiver="test-agent",
        context_id="ctx-123",
        task_id="task-456"
    )
    await agent.send(msg)
    
    # Wait for processing
    timeout = 5
    start_time = asyncio.get_event_loop().time()
    while len(events) < 3 and (asyncio.get_event_loop().time() - start_time) < timeout:
        await asyncio.sleep(0.1)
    
    # Events: 1. AGENT_STARTED, 2. ECHO, 3. TASK_COMPLETED
    assert len(events) >= 3
    assert any(e.type == "AGENT_STARTED" for e in events)
    echo_event = next(e for e in events if e.type == "ECHO")
    assert echo_event.payload == "Hello URP"
    assert echo_event.context_id == "ctx-123"
    assert echo_event.task_id == "task-456"
    
    # Check ProcessResult properties & backward compatibility
    last_res = agent.state["last_process_result"]
    assert last_res.outcome == LastTaskOutcome.TASK_COMPLETED
    assert last_res.text == "Processed: Hello URP"
    assert last_res.payload.text == "Processed: Hello URP"  # Backward compatibility check
    assert len(last_res.artifacts) == 1
    
    await agent.shutdown()
    assert agent._state.status == AgentStatus.TERMINATED

def test_process_result_compatibility():
    # Test setting direct text
    res1 = ProcessResult(outcome=LastTaskOutcome.TASK_COMPLETED, text="direct text")
    assert res1.text == "direct text"
    assert res1.payload is not None
    assert res1.payload.text == "direct text"

    # Test setting legacy payload
    res2 = ProcessResult(
        outcome=LastTaskOutcome.TASK_COMPLETED,
        payload=ProcessResultPayload(text="legacy payload text")
    )
    assert res2.payload.text == "legacy payload text"
    assert res2.text == "legacy payload text"

