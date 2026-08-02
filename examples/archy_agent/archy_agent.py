import asyncio
import os
import uuid
import logging
import sys
from typing import Any, Optional
from pathlib import Path

from openhands.sdk import (
    LLM,
    Agent,
    AgentContext,
    Conversation,
    Message,
    TextContent,
    Tool,
    Event,
    LLMConvertibleEvent,    
)
from openhands.sdk.skills import load_skills_from_dir
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

logger = logging.getLogger("urp.archy_agent")

class ArchyURPAgent(AbstractURPAgent):
    """
    Archy Agent implementation for URP-HF, specialized in module integration and SCUD generation.
    """

    def __init__(self, descriptor: Optional[AgentDescriptor] = None):
        if not descriptor:
            descriptor = AgentDescriptor(
                agent_id="vhl.archy.v1",
                name="Archy Agent",
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
                logger.info(f"[ArchyURPAgent] Conversation Event: {event_dict}")
            except Exception:
                event_dict = str(event)
                logger.info(f"[ArchyURPAgent] Conversation Event: {event_dict}")
            
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
        
        # Setup LLM
        llm_config = config.get("llm_config", {})
        self.llm = LLM(
            model=llm_config.get("model", os.getenv("LLM_MODEL", "anthropic/claude-sonnet-4-5-20250929")),
            api_key=llm_config.get("api_key", os.getenv("LLM_API_KEY")),
            base_url=llm_config.get("base_url", os.getenv("LLM_BASE_URL")),
        )

        # Load skills from workspace if available
        skills_path = Path(self.workspace_path) / ".agents" / "skills"
        agent_skills = {}
        if skills_path.exists():
            _, _, agent_skills = load_skills_from_dir(skills_path)
            logger.info(f"[ArchyURPAgent] Loaded {len(agent_skills)} skills from {skills_path}")

        agent_context = AgentContext(
            skills=list(agent_skills.values()),
            load_public_skills=True
        )

        # Setup Agent
        tools = [
            Tool(name=FileEditorTool.name),
            Tool(name=TerminalTool.name), 
        ]

        submodule_root = Path(__file__).resolve().parent
        sys_prompt_path = os.path.join(submodule_root, "archy_prompt.j2")
        sys_prompt_kwargs = config.get("system_prompt_kwargs", {})

        self.agent = Agent(
            llm=self.llm,
            tools=tools,
            system_prompt_filename=sys_prompt_path,
            system_prompt_kwargs=sys_prompt_kwargs,
            agent_context=agent_context
        )

        # Setup Conversation
        conv_id_str = config.get("conversation_id")
        conversation_id = uuid.UUID(conv_id_str) if conv_id_str else uuid.uuid4()

        self.conversation = Conversation(
            agent=self.agent,
            workspace=self.workspace_path,
            callbacks=[self._conversation_callback],
            persistence_dir=os.path.join(self.workspace_path, ".conversation"),
            conversation_id=conversation_id,
        )
        logger.info(f"[ArchyURPAgent] Initialized with workspace: {self.workspace_path}")

    def get_conversation_id(self) -> str:
        """Returns the current conversation ID."""
        if self.conversation:
            return str(self.conversation.state.id)
        return ""

    async def process(self, message: MessageEnvelope) -> ProcessResult:
        logger.info(f"[ArchyURPAgent] Processing message: {message}")
        
        user_message = message.payload.get("text", "") if isinstance(message.payload, dict) else str(message.payload)

        self.conversation.send_message(
            Message(
                role="user",
                content=[TextContent(text=user_message)],
            )
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

        response = "No response generated"
        if self.llm_messages:
            last_msg = self.llm_messages[-1]
            content_text = "".join([c.text for c in last_msg.content if isinstance(c, TextContent)])
            if content_text:
                response = content_text

        return ProcessResult(
            outcome=process_outcome,
            payload=ProcessResultPayload(text=response)
        )
