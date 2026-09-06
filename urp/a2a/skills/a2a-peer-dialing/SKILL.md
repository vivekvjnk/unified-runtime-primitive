---
name: a2a-peer-dialing
description: Enables an agent to discover and delegate tasks or queries to peer agents in the local A2A (Agent2Agent) network using the a2a_peer_call tool. Use when an operation falls outside your specialized domain (such as container compilation, Bitbake builds, or low-level systems programming) and a peer agent in the roster possesses the required capability.
---

# A2A Peer Dialing (Inter-Agent Delegation)

## Overview

In an Agent2Agent (A2A) multi-agent system, specialized agents collaborate as peers. When a task requires capabilities, tools, or domain knowledge held by another agent, you can delegate sub-tasks to that peer using `a2a_peer_call`.

```text
Caller Agent (e.g. tiny_dev_agent)
       │
       │ runs: a2a_peer_call --peer tiny_infra_agent --message "..."
       ▼
Local A2A Router (POST /message:send)
       ▼
Target Peer Agent (e.g. tiny_infra_agent)
       │ (executes Docker, compiler, environment check)
       ▼
Returns structured JSON result with stdout/stderr and completion state.
```

## How to Call a Peer Agent

Run the `a2a_peer_call` CLI tool from bash:

```bash
a2a_peer_call --peer <peer_agent_name> --message "<clear, self-contained instruction>"
```

### Options:
- `--peer`: The unique identifier/name of the peer agent (e.g., `tiny_infra_agent`, `tiny_dev_agent`, `echo_agent`).
- `--message`: The specific instruction or task request.
- `--context-id`: (Optional) Keeps conversation turns anchored in a multi-turn dialogue with the peer.
- `--timeout`: (Optional, default 180s) Maximum seconds to await completion.

### Example: Requesting a Container Build from the Infrastructure Specialist
```bash
a2a_peer_call --peer tiny_infra_agent --message "Please verify the Docker build container for tiny-agent and run 'make clean all' in /workspace."
```

### Expected Output
The tool outputs structured JSON:
```json
{
  "peer": "tiny_infra_agent",
  "task_id": "...",
  "context_id": "...",
  "state": "TASK_STATE_COMPLETED",
  "output": "Compilation succeeded. Built bin/tiny-agent."
}
```

## When to Delegate
1. **Separation of Concerns:**
   - If you are a development agent (C coding, logic), delegate container lifecycle, environment setup, and system build execution to the infrastructure agent.
   - If you are an infrastructure agent, delegate C code review, bug fixes, or test logic to the development agent.
2. **Clear Boundaries:** Always provide complete, self-contained instructions when calling a peer so they do not have to guess file paths or objectives.
