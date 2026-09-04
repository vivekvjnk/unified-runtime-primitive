# Guide: Testing & Verification

This document outlines patterns and best practices for writing automated unit and integration tests for URP agents and runtimes.

---

## 1. Unit Testing Lifecycle Contracts

When testing custom `AbstractURPAgent` implementations, verify:
1. `UNINITIALIZED -> INITIALIZED` transition upon `initialize()`.
2. Guard preventing duplicate initialization.
3. `AGENT_STARTED` emission upon `start()`.
4. Mailbox message consumption and `AGENT_TERMINATED` emission upon `shutdown()`.

```python
import pytest
import asyncio
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

class SampleAgent(AbstractURPAgent):
    def _on_initialize(self, context):
        pass

    async def process(self, message: MessageEnvelope) -> ProcessResult:
        return ProcessResult(
            outcome=LastTaskOutcome.TASK_COMPLETED,
            payload=ProcessResultPayload(text=f"Handled {message.type}")
        )

@pytest.mark.asyncio
async def test_agent_lifecycle_flow():
    descriptor = AgentDescriptor(
        agent_id="test.agent.v1",
        name="Test Agent",
        version="1.0.0",
        capabilities=["TEST"],
        accepted_message_types=["QUERY"]
    )
    agent = SampleAgent(descriptor)
    assert agent.state["status"] == AgentStatus.UNINITIALIZED

    events = []
    agent.initialize(AgentContext(), emit_callback=lambda e: events.append(e))
    assert agent.state["status"] == AgentStatus.INITIALIZED

    await agent.start()
    assert agent.state["status"] == AgentStatus.WAITING

    # Dispatch message
    msg = MessageEnvelope(type="QUERY", payload={"test": True}, sender="test-runner")
    await agent.send(msg)

    # Wait for processing
    await asyncio.sleep(0.1)
    assert len(events) >= 2  # AGENT_STARTED + TASK_COMPLETED
    assert any(e.type == "TASK_COMPLETED" for e in events)

    await agent.shutdown()
    assert agent.state["status"] == AgentStatus.TERMINATED
```

---

## 2. Testing Precondition & Postcondition Violations

```python
@pytest.mark.asyncio
async def test_precondition_violation():
    descriptor = AgentDescriptor(
        agent_id="test.guard.v1",
        name="Guard Agent",
        version="1.0.0",
        capabilities=["GUARD"],
        accepted_message_types=["TASK"]
    )
    
    class GuardAgent(SampleAgent):
        async def _check_preconditions(self, message):
            if "required_key" not in message.payload:
                return False, "Missing required_key"
            return True, "OK"

    agent = GuardAgent(descriptor)
    events = []
    agent.initialize(AgentContext(), emit_callback=lambda e: events.append(e))
    await agent.start()

    # Send invalid message
    await agent.send(MessageEnvelope(type="TASK", payload={}, sender="tester"))
    await asyncio.sleep(0.1)

    violation_event = next((e for e in events if e.type == "TASK_PRECONDITIONS_VIOLATED"), None)
    assert violation_event is not None
    assert violation_event.payload.category.name == "PRECONDITION_FAILURE"

    await agent.shutdown()
```
