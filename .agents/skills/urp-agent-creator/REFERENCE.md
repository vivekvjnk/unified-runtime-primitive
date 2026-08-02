# URP Agent Implementation Reference

## 1. Agent Implementation Template

Use this boilerplate for a standard URP Agent using the OpenHands SDK.

```python
import asyncio
import os
import uuid
import logging
from typing import Any, Optional
from pathlib import Path

from openhands.sdk import (
    LLM, Agent, Conversation, Message, TextContent, Tool, Event, LLMConvertibleEvent
)
from openhands.sdk.conversation.state import ConversationExecutionStatus
from openhands.tools.file_editor import FileEditorTool
from openhands.tools.terminal import TerminalTool

from urp.abstract_urp import AbstractURPAgent
from urp.data_types import (
    AgentDescriptor, MessageEnvelope, ProcessResult, ProcessResultPayload, 
    LastTaskOutcome, FailureCategory
)

logger = logging.getLogger("urp.my_agent")

class MyURPAgent(AbstractURPAgent):
    def __init__(self, descriptor: Optional[AgentDescriptor] = None):
        if not descriptor:
            descriptor = AgentDescriptor(
                agent_id="vhl.myagent.v1",
                name="My Agent",
                version="1.0",
                capabilities=["TERMINAL", "FILE_EDITOR"],
                accepted_message_types=["MESSAGE"]
            )
        super().__init__(descriptor=descriptor)
        self.llm = None
        self.agent = None
        self.conversation = None
        self.workspace_path = None
        self.llm_messages = []
        self._loop = None

    def _conversation_callback(self, event: Event):
        # Process event dict
        event_dict = event.model_dump() if hasattr(event, "model_dump") else str(event)
        
        if isinstance(event, LLMConvertibleEvent):
            self.llm_messages.append(event.to_llm_message())
        
        # Filter and summarize for UI
        summary = ""
        event_source = str(event.source).lower() if hasattr(event, "source") else ""
        if "agent" in event_source:
            # Skip noise
            if event.__class__.__name__ == "ObservationEvent":
                return
            if hasattr(event, "summary") and event.summary:
                summary = event.summary
            elif isinstance(event_dict, dict) and event_dict.get("summary"):
                summary = event_dict.get("summary")
        
        # Emit to URP-HF Bus
        if self._emit_callback and self._loop:
            self._loop.call_soon_threadsafe(
                lambda: asyncio.create_task(self.emit(MessageEnvelope(
                    type="AGENT_PROGRESS",
                    payload={
                        "event": event_dict, 
                        "text": f"{summary if summary else event.__class__.__name__}"
                    },
                    sender=self.descriptor.agent_id
                )))
            )

    def _on_initialize(self, context: Any) -> None:
        self._loop = asyncio.get_running_loop()
        config = context.configuration
        self.workspace_path = config.get("workspace_path", os.path.join(os.getcwd(), "agent_workspace"))
        os.makedirs(self.workspace_path, exist_ok=True)
        
        # LLM Config
        llm_config = config.get("llm_config", {})
        self.llm = LLM(
            model=llm_config.get("model", os.getenv("LLM_MODEL", "gpt-4o")),
            api_key=llm_config.get("api_key", os.getenv("LLM_API_KEY")),
        )

        # Agent Tools
        tools = [Tool(name=FileEditorTool.name), Tool(name=TerminalTool.name)]
        self.agent = Agent(llm=self.llm, tools=tools, system_prompt="Your instructions here")

        # Conversation setup
        conv_id_str = config.get("conversation_id")
        conversation_id = uuid.UUID(conv_id_str) if conv_id_str else uuid.uuid4()

        self.conversation = Conversation(
            agent=self.agent,
            workspace=self.workspace_path,
            callbacks=[self._conversation_callback],
            persistence_dir=os.path.join(self.workspace_path, ".conversation"),
            conversation_id=conversation_id,
        )

    async def process(self, message: MessageEnvelope) -> ProcessResult:
        user_message = message.payload.get("text", "") if isinstance(message.payload, dict) else str(message.payload)
        self.conversation.send_message(Message(role="user", content=[TextContent(text=user_message)]))
        
        await asyncio.to_thread(self.conversation.run)

        # Map Outcome
        status = self.conversation.state.execution_status
        outcome = LastTaskOutcome.TASK_COMPLETED if status == ConversationExecutionStatus.FINISHED else LastTaskOutcome.TASK_FAILED
        
        return ProcessResult(outcome=outcome, payload=ProcessResultPayload(text="Task finished"))
```

## 2. Registration Example (`web_server.py`)

```python
# 1. Import
from .my_agent import MyURPAgent

# 2. Add to create_host
elif agent_type == "myagent":
    descriptor = AgentDescriptor(
        agent_id="vhl.myagent.v1",
        name="My Agent",
        version="1.0",
        capabilities=["TERMINAL", "FILE_EDITOR"],
        accepted_message_types=["MESSAGE"]
    )
    host = URPHost(agent_class=MyURPAgent, descriptor=descriptor)
```
