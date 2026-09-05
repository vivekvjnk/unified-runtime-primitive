import asyncio
import sys
import os
import pytest

# Add the parent directory to sys.path
sys.path.append(os.path.join(os.path.dirname(os.path.abspath(__file__)), ".."))

from urp.core import URPHost, AgentDescriptor, AgentContext, MessageEnvelope
from urp.agents import EchoAgent

@pytest.mark.asyncio
async def test_urp_host():
    descriptor = AgentDescriptor(
        agent_id="test.echo",
        name="Test Echo Agent",
        version="1.0",
        capabilities=["ECHO"],
        accepted_message_types=["MESSAGE"]
    )
    
    host = URPHost(EchoAgent, descriptor)
    
    # Track received events
    received_events = []
    async def on_event(event):
        print(f"[Test] Received event: {event.type}")
        received_events.append(event)

    host.set_emit_callback(on_event)
    
    # Start the host
    context = AgentContext(configuration={"test": True})
    await host.initialize_and_start(context)
    
    # Send a message
    print("[Test] Sending message...")
    await host.send_message("TEST_MESSAGE", {"text": "Hello URP!"})
    
    # Wait for the echo event
    print("[Test] Waiting for events...")
    # The EchoAgent sleeps for 1s, so we should see the result soon
    
    # Poll for events
    for _ in range(5):
        try:
            event = await host.get_next_event(timeout=2.0)
            print(f"[Test] Successfully pulled event from queue: {event.type} payload: {event.payload}")
            if event.type == "TASK_COMPLETED":
                print(f"[Test] Task outcome: {event.payload.outcome}")
                break
        except asyncio.TimeoutError:
            print("[Test] Timeout waiting for event")
            break

    await host.shutdown()
    print("[Test] Test completed.")

if __name__ == "__main__":
    asyncio.run(test_urp_host())
