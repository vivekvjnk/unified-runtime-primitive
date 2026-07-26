import asyncio
import os
import uuid
import logging
from typing import Any, Optional
from pathlib import Path

from openhands.sdk import (
    LLM,
    Agent,
    Conversation,
    Message,
    TextContent,
    Tool,
    Event,
    LLMConvertibleEvent,    
)

from openhands.sdk.conversation.state import (
    ConversationExecutionStatus,
)
from openhands.tools.file_editor import FileEditorTool
from openhands.tools.terminal import TerminalTool

from urp.abstract_urp import AbstractURPAgent
from urp.data_types import (
    AgentDescriptor,
    MessageEnvelope,
    ProcessResult,
    ProcessResultPayload,
    LastTaskOutcome,
    FailureCategory,
)

logger = logging.getLogger("urp.asm_agent")

class ASMURPAgent(AbstractURPAgent):
    """
    Architectural State Manager (ASM) Agent implementation using openhands-agent-sdk.
    """

    def __init__(self, descriptor: Optional[AgentDescriptor] = None):
        if not descriptor:
            descriptor = AgentDescriptor(
                agent_id="vhl.asm.v1",
                name="ASM Agent",
                version="1.0",
                capabilities=["TERMINAL", "FILE_EDITOR"],
                accepted_message_types=["PROCESS_ARCHITECTURE", "MESSAGE"]
            )
        super().__init__(descriptor=descriptor)
        self.llm = None
        self.agent = None
        self.conversation = None
        self.workspace_path = None
        self.llm_messages = []
        self._loop = None

    def _conversation_callback(self, event: Event):
            # Log all events for debugging
            try:
                event_dict = event.model_dump() if hasattr(event, "model_dump") else str(event)
                logger.info(f"[ASMURPAgent] Conversation Event: {event_dict}")
            except Exception:
                event_dict = str(event)
                logger.info(f"[ASMURPAgent] Conversation Event: {event_dict}")
            
            if isinstance(event, LLMConvertibleEvent):
                self.llm_messages.append(event.to_llm_message())
            
            # Extract summary if available
            summary = ""
            event_source = str(event.source).lower() if hasattr(event, "source") else ""
            if "agent" in event_source:
                # Ignore ObservationEvent as per user request
                if event.__class__.__name__ == "ObservationEvent":
                    return

                if hasattr(event, "summary") and event.summary:
                    summary = event.summary
                elif isinstance(event_dict, dict) and event_dict.get("summary"):
                    summary = event_dict.get("summary")
            
            # Emit progress to URP bus
            if self._emit_callback and self._loop:
                # Create a bridge to emit the event
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
        """
        Initializes the ASM agent.
        """
        self._loop = asyncio.get_running_loop()
        config = context.configuration
        self.workspace_path = config.get("workspace_path", os.path.join(os.getcwd(), "agent_workspace"))
        
        # Ensure workspace exists
        os.makedirs(self.workspace_path, exist_ok=True)
        
        # Setup LLM
        llm_config = config.get("llm_config", {})
        self.llm = LLM(
            model=llm_config.get("model", os.getenv("LLM_MODEL", "gpt-4o")),
            api_key=llm_config.get("api_key", os.getenv("LLM_API_KEY")),
            base_url=llm_config.get("base_url", os.getenv("LLM_BASE_URL")),
        )

        # Setup Agent
        tools = [
            Tool(name=FileEditorTool.name),
            Tool(name=TerminalTool.name), 
        ]

        submodule_root = Path(__file__).resolve().parent
        sys_prompt_path = os.path.join(submodule_root, "asm_prompt.j2")
        sys_prompt_kwargs = config.get("system_prompt_kwargs", {})

        self.agent = Agent(
            llm=self.llm,
            tools=tools,
            system_prompt_filename=sys_prompt_path,
            system_prompt_kwargs=sys_prompt_kwargs
        )

        # Setup Conversation
        conv_id_str = config.get("conversation_id")
        if conv_id_str:
            try:
                conversation_id = uuid.UUID(conv_id_str)
                logger.info(f"[ASMURPAgent._on_initialize] Resuming conversation with ID: {conversation_id}")
            except ValueError:
                conversation_id = uuid.uuid4()
                logger.warning(f"[ASMURPAgent._on_initialize] Invalid conversation ID provided, created new: {conversation_id}")
        else:
            conversation_id = uuid.uuid4()
            logger.info(f"[ASMURPAgent._on_initialize] Created new conversation with ID: {conversation_id}")

        self.conversation = Conversation(
            agent=self.agent,
            workspace=self.workspace_path,
            callbacks=[self._conversation_callback],
            persistence_dir=os.path.join(self.workspace_path, ".conversation"),
            conversation_id=conversation_id,
        )
        logger.info(f"[ASMURPAgent] Initialized with workspace: {self.workspace_path}")

    def get_conversation_id(self) -> str:
        """Returns the current conversation ID."""
        if self.conversation:
            return str(self.conversation.state.id)
        return ""

    async def process(self, message: MessageEnvelope) -> ProcessResult:
        """
        Core execution primitive.
        """
        logger.info(f"[ASMURPAgent] Processing message: {message}")
        
        user_message = ""
        if isinstance(message.payload, dict) and "text" in message.payload:
            user_message = message.payload["text"]
        else:
            user_message = str(message.payload)

        self.conversation.send_message(
            Message(
                role="user",
                content=[TextContent(text=user_message)],
            )
        )

        # Run conversation in thread as it is synchronous in the SDK (mostly)
        await asyncio.to_thread(self.conversation.run)

        # Map conversation status to URP outcome
        status = self.conversation.state.execution_status
        if status == ConversationExecutionStatus.PAUSED:
            process_outcome = LastTaskOutcome.WAITING_FOR_USER_INPUT
        elif status == ConversationExecutionStatus.FINISHED:
            process_outcome = LastTaskOutcome.TASK_COMPLETED
        elif status in [ConversationExecutionStatus.STUCK, ConversationExecutionStatus.ERROR]:
            process_outcome = LastTaskOutcome.TASK_FAILED
        else:
            process_outcome = LastTaskOutcome.NONE

        if self.llm_messages:
            last_msg = self.llm_messages[-1]
            response = ""
            for content_item in last_msg.content:
                if isinstance(content_item, TextContent):
                    response += content_item.text
            if not response:
                response = "No text response generated"
        else:
            response = "No response generated"

        return ProcessResult(
            outcome=process_outcome,
            payload=ProcessResultPayload(text=response)
        )
