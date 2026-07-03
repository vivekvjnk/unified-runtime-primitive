# URP Core

Unified Runtime Primitive (URP) is the foundational execution model for VHL agents. It defines a minimal, language-agnostic, stateful, message-driven agent primitive.

## Core Concepts

- **Addressable identity**: Each agent has a globally unique runtime id.
- **Persistent state**: State survives across messages.
- **Mailbox-driven invocation**: Messages are delivered asynchronously.
- **Asynchronous execution**: Invocation is non-blocking.
- **Event emission**: Outputs are emitted as events.
- **Capability declaration**: Agents advertise supported operations.

## Installation

```bash
pip install .
```

## Usage

```python
from urp import AbstractURPAgent, AgentDescriptor, MessageEnvelope

class MyAgent(AbstractURPAgent):
    async def process(self, message: MessageEnvelope):
        print(f"Processing: {message.payload}")
        await self.emit(MessageEnvelope(
            type="RESPONSE",
            payload="Done",
            sender=self.descriptor.agent_id
        ))

# Initialize and start agent...
```

See `docs/URP.md` for the full specification.
