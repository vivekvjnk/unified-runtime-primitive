import argparse
import os

TEMPLATE = """import asyncio
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

logger = logging.getLogger("urp.{logger_name}")

class {class_name}(AbstractURPAgent):
    \"\"\"
    {agent_name} implementation using openhands-agent-sdk.
    \"\"\"

    def __init__(self, descriptor: Optional[AgentDescriptor] = None):
        if not descriptor:
            descriptor = AgentDescriptor(
                agent_id="{agent_id}",
                name="{agent_name}",
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
        try:
            event_dict = event.model_dump() if hasattr(event, "model_dump") else str(event)
        except Exception:
            event_dict = str(event)
        
        if isinstance(event, LLMConvertibleEvent):
            self.llm_messages.append(event.to_llm_message())
        
        summary = ""
        event_source = str(event.source).lower() if hasattr(event, "source") else ""
        if "agent" in event_source:
            if event.__class__.__name__ == "ObservationEvent":
                return
            if hasattr(event, "summary") and event.summary:
                summary = event.summary
            elif isinstance(event_dict, dict) and event_dict.get("summary"):
                summary = event_dict.get("summary")
        
        if self._emit_callback and self._loop:
            self._loop.call_soon_threadsafe(
                lambda: asyncio.create_task(self.emit(MessageEnvelope(
                    type="AGENT_PROGRESS",
                    payload={{
                        "event": event_dict, 
                        "text": f"{{summary if summary else event.__class__.__name__}}"
                    }},
                    sender=self.descriptor.agent_id
                )))
            )

    def _on_initialize(self, context: Any) -> None:
        self._loop = asyncio.get_running_loop()
        config = context.configuration
        self.workspace_path = config.get("workspace_path", os.path.join(os.getcwd(), "agent_workspace"))
        os.makedirs(self.workspace_path, exist_ok=True)
        
        llm_config = config.get("llm_config", {{}})
        self.llm = LLM(
            model=llm_config.get("model", os.getenv("LLM_MODEL", "gpt-4o")),
            api_key=llm_config.get("api_key", os.getenv("LLM_API_KEY")),
            base_url=llm_config.get("base_url", os.getenv("LLM_BASE_URL")),
        )

        tools = [Tool(name=FileEditorTool.name), Tool(name=TerminalTool.name)]
        self.agent = Agent(
            llm=self.llm,
            tools=tools,
            system_prompt="You are {agent_name}. Assist the user with their circuit design tasks."
        )

        conv_id_str = config.get("conversation_id")
        if conv_id_str:
            try:
                conversation_id = uuid.UUID(conv_id_str)
            except ValueError:
                conversation_id = uuid.uuid4()
        else:
            conversation_id = uuid.uuid4()

        self.conversation = Conversation(
            agent=self.agent,
            workspace=self.workspace_path,
            callbacks=[self._conversation_callback],
            persistence_dir=os.path.join(self.workspace_path, ".conversation"),
            conversation_id=conversation_id,
        )

    async def process(self, message: MessageEnvelope) -> ProcessResult:
        user_message = ""
        if isinstance(message.payload, dict) and "text" in message.payload:
            user_message = message.payload["text"]
        else:
            user_message = str(message.payload)

        self.conversation.send_message(
            Message(role="user", content=[TextContent(text=user_message)])
        )

        await asyncio.to_thread(self.conversation.run)

        status = self.conversation.state.execution_status
        if status == ConversationExecutionStatus.PAUSED:
            process_outcome = LastTaskOutcome.WAITING_FOR_USER_INPUT
        elif status == ConversationExecutionStatus.FINISHED:
            process_outcome = LastTaskOutcome.TASK_COMPLETED
        elif status in [ConversationExecutionStatus.STUCK, ConversationExecutionStatus.ERROR]:
            process_outcome = LastTaskOutcome.TASK_FAILED
        else:
            process_outcome = LastTaskOutcome.NONE

        response = "Task processing completed."
        if self.llm_messages:
            last_msg = self.llm_messages[-1]
            text = "".join([c.text for c in last_msg.content if isinstance(c, TextContent)])
            if text: response = text

        return ProcessResult(
            outcome=process_outcome,
            payload=ProcessResultPayload(text=response)
        )
"""

def main():
    parser = argparse.ArgumentParser(description="Generate a URP Agent boilerplate.")
    parser.add_argument("--name", required=True, help="Agent name (e.g., 'Analyst Agent')")
    parser.add_argument("--id", required=True, help="Agent ID (e.g., 'vhl.analyst.v1')")
    parser.add_argument("--output", required=True, help="Output file path (e.g., 'examples/analyst_agent.py')")
    
    args = parser.parse_args()
    
    class_name = args.name.replace(" ", "") + "URPAgent"
    logger_name = args.name.lower().replace(" ", "_") + "_agent"
    
    content = TEMPLATE.format(
        class_name=class_name,
        agent_name=args.name,
        agent_id=args.id,
        logger_name=logger_name
    )
    
    os.makedirs(os.path.dirname(os.path.abspath(args.output)), exist_ok=True)
    with open(args.output, "w") as f:
        f.write(content)
    
    print(f"Successfully generated agent at {args.output}")
    print(f"Next steps: Register {class_name} in examples/web_server.py")

if __name__ == "__main__":
    main()
