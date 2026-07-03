import asyncio
import pytest
from urp import (
    AbstractURPAgent,
    AgentDescriptor,
    AgentContext,
    MessageEnvelope,
    AgentStatus,
)

class MockAgent(AbstractURPAgent):
    def _on_initialize(self, context):
        self.initialized_called = True

    async def process(self, message: MessageEnvelope):
        await self.emit(MessageEnvelope(
            type="ECHO",
            payload=message.payload,
            sender=self.descriptor.agent_id
        ))

@pytest.mark.asyncio
async def test_agent_lifecycle():
    descriptor = AgentDescriptor(
        agent_id="test-agent",
        name="Test Agent",
        version="0.1.0",
        capabilities=["echo"],
        accepted_message_types=["QUERY"]
    )
    
    agent = MockAgent(descriptor)
    assert agent._state.status == AgentStatus.UNINITIALIZED
    
    events = []
    def emit_callback(event):
        events.append(event)
        
    context = AgentContext()
    agent.initialize(context, emit_callback)
    assert agent._state.status == AgentStatus.INITIALIZED
    assert agent.initialized_called
    
    await agent.start()
    assert agent._state.status == AgentStatus.WAITING
    
    # Send a message
    msg = MessageEnvelope(
        type="QUERY",
        payload="Hello URP",
        sender="tester",
        receiver="test-agent"
    )
    await agent.send(msg)
    
    # Wait for processing
    timeout = 5
    start_time = asyncio.get_event_loop().time()
    while len(events) < 2 and (asyncio.get_event_loop().time() - start_time) < timeout:
        await asyncio.sleep(0.1)
    
    # Events: 1. AGENT_STARTED, 2. ECHO
    assert len(events) >= 2
    assert any(e.type == "AGENT_STARTED" for e in events)
    echo_event = next(e for e in events if e.type == "ECHO")
    assert echo_event.payload == "Hello URP"
    
    await agent.shutdown()
    assert agent._state.status == AgentStatus.TERMINATED
