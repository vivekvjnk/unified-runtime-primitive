import asyncio
from typing import Any
from urp.abstract_urp import AbstractURPAgent
from urp.data_types import ProcessResult, LastTaskOutcome, MessageEnvelope, ProcessResultPayload

class EchoAgent(AbstractURPAgent):
    """
    A simple URP agent that echoes back whatever it receives.
    Used for demonstrating the URP-HF runtime kernel.
    """
    
    def _on_initialize(self, context) -> None:
        print(f"[EchoAgent] Initialized with context: {context}")

    async def process(self, message: MessageEnvelope) -> ProcessResult:
        print(f"[EchoAgent] Processing message: {message.type}")
        
        # Simulate some work
        await asyncio.sleep(1)
        
        # Extract text from payload
        text = ""
        if isinstance(message.payload, dict) and "text" in message.payload:
            text = message.payload["text"]
        else:
            text = str(message.payload)
            
        # Emit a custom event
        await self.emit(MessageEnvelope(
            type="ECHO_RECEIVED",
            payload={"original_text": text},
            sender=self.descriptor.agent_id
        ))
        
        # Return completion result
        return ProcessResult(
            outcome=LastTaskOutcome.TASK_COMPLETED,
            payload=ProcessResultPayload(text=f"Echo: {text}")
        )
