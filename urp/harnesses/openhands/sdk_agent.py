import asyncio
import os
import uuid
import logging
from typing import Any, Optional

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

from urp.core import (
    AbstractURPAgent,
    AgentDescriptor,
    MessageEnvelope,
    ProcessResult,
    LastTaskOutcome,
    FailureCategory,
)

logger = logging.getLogger("urp.sdk_agent")

class SDKURPAgent(AbstractURPAgent):
    """
    URP Agent implementation using openhands-agent-sdk.
    """

    def __init__(self, descriptor: Optional[AgentDescriptor] = None):
        if not descriptor:
            descriptor = AgentDescriptor(
                agent_id="vhl.sdk_example.v1",
                name="SDK Example Agent",
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

    def _conversation_callback(self, event: Event):
            if isinstance(event, LLMConvertibleEvent):
                self.llm_messages.append(event.to_llm_message())
    
    def _on_initialize(self, context: Any) -> None:
        """
        Initializes the SDK agent.
        Expected context.configuration:
        {
            "workspace_path": "/path/to/workspace",
            "llm_config": { ... }, # Optional
            "conversation_id": "..." # Optional
        }
        """
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

        self.agent = Agent(
            llm=self.llm,
            tools=tools,
            system_prompt="You are a helpful assistant with access to a terminal and file editor. "
                          "Use them to help the user with their tasks."
        )

        # Setup Conversation
        conv_id_str = config.get("conversation_id")
        if conv_id_str:
            try:
                conversation_id = uuid.UUID(conv_id_str)
                logger.info(f"[SDKURPAgent._on_initialize] Resuming conversation with ID: {conversation_id}")
            except ValueError:
                conversation_id = uuid.uuid4()
                logger.warning(f"[SDKURPAgent._on_initialize] Invalid conversation ID provided, created new: {conversation_id}")
        else:
            conversation_id = uuid.uuid4()
            logger.info(f"[SDKURPAgent._on_initialize] Created new conversation with ID: {conversation_id}")

        self.conversation = Conversation(
            agent=self.agent,
            workspace=self.workspace_path,
            callbacks=[self._conversation_callback],
            persistence_dir=os.path.join(self.workspace_path, ".conversation"),
            conversation_id=conversation_id,
        )
        logger.info(f"[SDKURPAgent] Initialized with workspace: {self.workspace_path}")

    def get_conversation_id(self) -> str:
        """Returns the current conversation ID."""
        if self.conversation:
            return str(self.conversation.state.id)
        return ""

    async def process(self, message: MessageEnvelope) -> ProcessResult:
        """
        Core execution primitive.
        """
        logger.info(f"[SDKURPAgent] Processing message: {message}")
        
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
        # Note: In newer SDK versions conversation.run() might be async, 
        # but here we follow the pattern from librarian_agent.
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
            text=response
        )
