# Guide: Authoring Custom URP Agents

This guide provides step-by-step instructions for implementing custom agent subclasses of `AbstractURPAgent`.

---

## 1. Subclassing `AbstractURPAgent`

To create an agent, subclass `AbstractURPAgent` and implement the mandatory methods:
1. `_on_initialize(self, context)`
2. `async def process(self, message: MessageEnvelope) -> ProcessResult`

Optionally implement safety verification hooks:
* `async def _check_start_preconditions(self) -> tuple[bool, str]`
* `async def _check_preconditions(self, message: MessageEnvelope) -> tuple[bool, str]`
* `async def _check_postconditions(self, message: MessageEnvelope, result: ProcessResult) -> tuple[bool, str]`
* `async def _on_shutdown(self) -> None`

---

## 2. Minimal Concrete Example

```python
import asyncio
from urp import (
    AbstractURPAgent,
    AgentDescriptor,
    AgentContext,
    MessageEnvelope,
    ProcessResult,
    ProcessResultPayload,
    LastTaskOutcome,
    FailureCategory,
)

class TextProcessingAgent(AbstractURPAgent):
    """Simple agent performing text transformation and analysis."""

    def _on_initialize(self, context: AgentContext) -> None:
        self.config = context.configuration
        self.workspace = context.workspace_handle

    async def _check_preconditions(self, message: MessageEnvelope) -> tuple[bool, str]:
        # Validate that message payload contains 'text'
        if not isinstance(message.payload, dict) or "text" not in message.payload:
            return False, "Payload must be a dictionary with a 'text' key."
        return True, "Preconditions valid."

    async def process(self, message: MessageEnvelope) -> ProcessResult:
        text = message.payload["text"]

        # 1. Emit intermediate progress event
        await self.emit(MessageEnvelope(
            type="PROCESSING_STARTED",
            payload={"length": len(text)},
            sender=self.descriptor.agent_id,
            correlation_id=message.correlation_id
        ))

        # 2. Perform work
        await asyncio.sleep(0.2)
        transformed = text.upper()

        # 3. Return structured outcome
        return ProcessResult(
            outcome=LastTaskOutcome.TASK_COMPLETED,
            payload=ProcessResultPayload(text=f"Processed: {transformed}")
        )

    async def _check_postconditions(self, message: MessageEnvelope, result: ProcessResult) -> tuple[bool, str]:
        # Assert that result payload is populated
        if not result.payload or not result.payload.text:
            return False, "Output text cannot be empty."
        return True, "Postconditions verified."
```

---

## 3. Integrating Complex Engines (OpenHands SDK Example)

For full LLM agent loops with terminal and file tools, wrap the engine inside `process()` (as seen in `urp.sdk_agent.SDKURPAgent`):

```python
from openhands.sdk import LLM, Agent, Conversation, Message, TextContent, Tool
from openhands.tools.file_editor import FileEditorTool
from openhands.tools.terminal import TerminalTool

class MyCustomSDKAgent(AbstractURPAgent):
    def _on_initialize(self, context: AgentContext) -> None:
        llm = LLM(model="gpt-4o")
        tools = [Tool(name=FileEditorTool.name), Tool(name=TerminalTool.name)]
        agent = Agent(llm=llm, tools=tools, system_prompt="You are a helpful coding assistant.")
        self.conversation = Conversation(
            agent=agent,
            workspace=context.configuration.get("workspace_path", "./workspace")
        )

    async def process(self, message: MessageEnvelope) -> ProcessResult:
        user_text = message.payload.get("text", "")
        self.conversation.send_message(Message(role="user", content=[TextContent(text=user_text)]))
        
        # Execute conversation in thread pool
        await asyncio.to_thread(self.conversation.run)
        
        return ProcessResult(
            outcome=LastTaskOutcome.TASK_COMPLETED,
            payload=ProcessResultPayload(text="Execution finished.")
        )
```
