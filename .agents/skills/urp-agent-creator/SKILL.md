---
name: urp-agent-creator
description: Create a new Unified Runtime Primitive (URP) agent for the VHL-System Hosting Framework. Use this skill when asked to build, design, or implement a new URP-compatible agent, particularly those leveraging the OpenHands SDK for specialized tasks.
---

# URP Agent Creator

This skill provides the standardized workflow for creating URP agents that can be hosted independently under the VHL Unified Runtime Primitive Hosting Framework (URP-HF).

## Standard Workflow

### 1. Planning the Agent
Define the core attributes of the agent:
- **Agent ID**: Unique identifier (e.g., `vhl.myagent.v1`).
- **Capabilities**: What tools does it use? (e.g., `TERMINAL`, `FILE_EDITOR`).
- **Message Types**: What specialized messages does it handle? (e.g., `PROCESS_BLOCK_DESIGN`, `MESSAGE`).

### 2. Generating Boilerplate
Use the bundled generation script to create the initial agent file.
```bash
python3 .agents/skills/urp-agent-creator/scripts/generate_urp_agent.py --name "My New Agent" --id "vhl.myagent.v1" --output examples/my_agent.py
```

### 3. Implementation Details
The agent must inherit from `AbstractURPAgent` and implement the following:

- **`__init__`**: Configure the `AgentDescriptor`.
- **`_on_initialize`**: Set up the environment, workspace, LLM, and OpenHands `Agent` and `Conversation` objects.
- **`process`**: The core execution loop. It receives a `MessageEnvelope` and must return a `ProcessResult`.
- **`_conversation_callback`**: Handles real-time progress emission to the URP bus.

Refer to [REFERENCE.md](REFERENCE.md) for the full implementation template and code snippets.

### 4. Integration with URP-HF
To host the agent in the WebUI:
1.  Open `examples/web_server.py`.
2.  Import your new agent class.
3.  Add the agent to the `create_host` function logic.
4.  Update `InitRequest` defaults if necessary.

## Best Practices
- **Isolation**: Ensure the agent only interacts with the provided `workspace_path`.
- **Progressive Feedback**: Use the `emit` method within the conversation callback to send `AGENT_PROGRESS` events for real-time UI updates.
- **Error Handling**: Wrap the `process` logic to catch exceptions and return `LastTaskOutcome.TASK_FAILED` with an appropriate `FailureCategory`.
- **Stateless Execution**: While URP agents can maintain state during a session, aim for deterministic behavior based on the input workspace.

## Documentation Reference
Read [REFERENCE.md](REFERENCE.md) for detailed class structures and registration examples.
