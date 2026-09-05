import asyncio
import logging
from typing import Any, Callable, Dict, Optional, Type
from .abstract_urp import AbstractURPAgent
from .data_types import AgentDescriptor, AgentContext, MessageEnvelope, AgentStatus

logger = logging.getLogger(__name__)

class URPHost:
    """
    Reference implementation of the URP Runtime Kernel.
    Manages the lifecycle of a single URP agent and provides communication bridges.
    """
    def __init__(self, agent_class: Type[AbstractURPAgent], descriptor: AgentDescriptor):
        self.agent_class = agent_class
        self.descriptor = descriptor
        self.agent: Optional[AbstractURPAgent] = None
        self.event_queue: asyncio.Queue[MessageEnvelope] = asyncio.Queue()
        self._emit_callback: Optional[Callable[[MessageEnvelope], Any]] = None

    def set_emit_callback(self, callback: Callable[[MessageEnvelope], Any]):
        """Sets a callback for events emitted by the agent."""
        self._emit_callback = callback

    async def _internal_emit_handler(self, event: MessageEnvelope):
        """Internal handler for agent-emitted events."""
        logger.debug(f"[URPHost] Agent emitted event: {event.type}")
        # Put in local queue for polling/streaming
        await self.event_queue.put(event)
        
        # Call external callback if provided
        if self._emit_callback:
            if asyncio.iscoroutinefunction(self._emit_callback):
                await self._emit_callback(event)
            else:
                self._emit_callback(event)

    async def initialize_and_start(self, context: AgentContext):
        """Initializes the agent with the given context and starts its lifecycle loop."""
        logger.info(f"[URPHost] Initializing agent {self.descriptor.agent_id}...")
        
        self.agent = self.agent_class(descriptor=self.descriptor)
        
        # Bind the agent to our internal emit handler
        self.agent.initialize(context=context, emit_callback=self._internal_emit_handler)
        
        logger.info(f"[URPHost] Starting agent {self.descriptor.agent_id}...")
        await self.agent.start()
        
        return self.agent

    async def send_message(
        self,
        message_type: str,
        payload: Any,
        sender: str = "host",
        context_id: Optional[str] = None,
        task_id: Optional[str] = None,
    ):
        """Sends a message to the agent's mailbox with optional A2A routing anchors."""
        if not self.agent:
            raise RuntimeError("Agent not initialized. Call initialize_and_start first.")
            
        envelope = MessageEnvelope(
            type=message_type,
            payload=payload,
            sender=sender,
            receiver=self.descriptor.agent_id,
            context_id=context_id,
            task_id=task_id,
        )
        
        logger.info(f"[URPHost] Sending message {message_type} to agent...")
        await self.agent.send(envelope)
        return envelope.message_id

    async def get_next_event(self, timeout: Optional[float] = None) -> MessageEnvelope:
        """Awaits and returns the next event emitted by the agent."""
        if timeout:
            return await asyncio.wait_for(self.event_queue.get(), timeout=timeout)
        return await self.event_queue.get()

    async def shutdown(self):
        """Gracefully shuts down the agent."""
        if self.agent:
            logger.info(f"[URPHost] Shutting down agent {self.descriptor.agent_id}...")
            await self.agent.shutdown()
            self.agent = None
