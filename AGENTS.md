# Unified Runtime Primitive (URP Core) — Knowledge Base

`urp-core` is the standalone, decoupled implementation of the **Unified Runtime Primitive (URP)** framework and **Pi Agent Harness** for electronic circuit design and multi-agent orchestration.

---

## Quick Start

### 1. Installation
Install `urp-core` in editable mode for local development or integration into agent backends:
```bash
pip install -e .
```

### 2. Running the Independent Hosting Framework (URP-HF)
Start the standalone web server and interactive agent web console:
```bash
python3 run_host.py
```
Access the URP Web Console at `http://localhost:8000`.

### 3. Running Integration Tests
Execute the fast, deterministic offline test suite:
```bash
PYTHONPATH=. pytest
```

---

## Directory Structure & Core Components

```
urp-core/
├── urp/                                # Core URP Library Package
│   ├── abstract_urp.py                 # AbstractURPAgent state machine & scheduler contract
│   ├── data_types.py                   # Standard URP data models (MessageEnvelope, ProcessResult, etc.)
│   ├── agent_registry.py               # Factory-based thread-safe agent registry
│   ├── agent_key.py                    # Agent key & handle management
│   └── pi_harness/                     # Pi Agent Harness Transport Bridge
│       ├── __init__.py                 # Re-exports PiRpcClient & PiURPAgent
│       ├── rpc_types.py                # Pi RPC command, response, event, & exception models
│       ├── pi_rpc_client.py            # Async subprocess manager & stdio JSONL transport
│       └── pi_urp_agent.py             # Base URP agent class backed by Pi RPC harness
├── examples/                           # Standalone Agent Implementations & Hosting Framework
│   ├── host.py                         # URPHost reference runtime kernel
│   ├── web_server.py                   # FastAPI + WebSocket server for hosting URP agents
│   └── layout_engineer/                # PCB Layout Engineer Agent module
│       ├── .agents/                    # Agent-specific skills directory
│       └── layout_engineer_agent/
│           ├── urp_layout_engineer.py  # LayoutEngineerURPAgent(PiURPAgent)
│           ├── utils.py                # Config & prompt resolution helpers
│           └── prompts/                # System prompt templates (.j2)
├── .agents/                            # Global URP Agent skills & skill guidelines
│   ├── agent-skill-generation-guideline.md
│   └── skills/                         # Skill definition packages
├── tests/                              # Integration Test Suite
│   ├── fixtures/fake_pi_rpc.py         # Fast mock RPC server for zero-LLM deterministic testing
│   ├── test_pi_rpc_integration.py      # Pi RPC transport test suite
│   ├── test_pi_urp_agent_integration.py # PiURPAgent base class test suite
│   └── test_layout_engineer_host.py   # URPHost hosted agent test suite
└── pyproject.toml                      # Package definition (urp-core)
```

---

## URP Agent Contract & Lifecycle

All URP agents extend `AbstractURPAgent` or `PiURPAgent` and enforce strict URP invariants:

1. **Addressable Identity**: Every agent instance has a unique `AgentDescriptor` (`agent_id`, `name`, `capabilities`) and `session_id`.
2. **Mailbox-Driven Invocation**: Incoming tasks enter exclusively through `agent.send(MessageEnvelope)` into an asynchronous queue (`mailbox`).
3. **Single Invariant Loop (`_lifecycle_loop`)**:
   - `WAITING` $\rightarrow$ Dequeue `MessageEnvelope` $\rightarrow$ Evaluate `_check_preconditions()` $\rightarrow$ `PROCESSING` $\rightarrow$ Execute `process(message)` $\rightarrow$ Evaluate `_check_postconditions()` $\rightarrow$ Auto-emit `ProcessResult` $\rightarrow$ Wait for Outcome Acknowledgment $\rightarrow$ `WAITING`.
4. **Outcome Acknowledgment Hold**:
   - After processing a message, `AbstractURPAgent` sets `self._state.outcome_acknowledged = False`.
   - The agent holds subsequent mailbox queue execution until the external supervisor/host invokes `agent.acknowledge_outcome()`.
5. **Preconditions & Postconditions**:
   - Precondition checks occur after message dequeue. Violations emit `TASK_PRECONDITIONS_VIOLATED` without calling process logic.
   - Postcondition checks occur after `process()` completes. Violations emit `TASK_POSTCONDITIONS_VIOLATED`.

---

## Pi Agent Harness (`urp.pi_harness`)

The `pi_harness` package connects Python URP agents with the high-performance Node.js `pi` coding agent harness (`pi --mode rpc`):

- **`PiRpcClient`**:
  - Manages `pi --mode rpc` subprocess spawning (`asyncio.create_subprocess_exec`).
  - Implements strict LF-delimited UTF-8 JSONL stdio transport.
  - Matches command requests to responses using unique request IDs (`asyncio.Future`).
  - Dispatches streamed events (`agent_start`, `turn_start`, `message_update`, `tool_execution_start`, `agent_settled`).
  - Handles Extension UI dialog sub-protocol requests (`select`, `confirm`, `input`, `editor`).
- **`PiURPAgent`**:
  - Base class inheriting from `AbstractURPAgent`.
  - Configures settlement timeouts (defaulting to **10 minutes / 600s**).
  - Handles timeout aborts (`pi_client.abort()`), captures last generated assistant text, and returns `TASK_FAILED` with `FailureCategory.AGENTIC_FAILURE`.
  - Automatically translates Pi RPC streaming events into URP telemetry events (`AGENT_PROGRESS_UPDATE`, `AGENT_TOOL_START`, `AGENT_TOOL_END`).

---

## Standalone Hosting Framework (URP-HF)

`urp-core` includes a standalone hosting kernel (`URPHost`) and web server (`examples/web_server.py`) to deploy agents without external system dependencies:

```python
from examples.host import URPHost
from examples.layout_engineer.layout_engineer_agent import LayoutEngineerURPAgent
from urp.data_types import AgentDescriptor, AgentContext

# 1. Instantiation & Descriptor
descriptor = AgentDescriptor(
    agent_id="vhl.layout_engineer.v1",
    name="Layout Engineer Agent",
    version="1.0.0",
    capabilities=["pcb_placement"],
    accepted_message_types=["LAYOUT_PLACEMENT_TASK"]
)
host = URPHost(agent_class=LayoutEngineerURPAgent, descriptor=descriptor)

# 2. Context & Initialization
context = AgentContext(configuration={"workspace_dir": "./agent_workspace", "no_session": True})
agent = await host.initialize_and_start(context)

# 3. Message Delivery & Event Consumption
msg_id = await host.send_message("LAYOUT_PLACEMENT_TASK", {"text": "Place MCU U1 at (0,0)"})
outcome_event = await host.get_next_event(timeout=10.0)

# 4. Outcome Acknowledgment & Teardown
agent.acknowledge_outcome()
await host.shutdown()
```

---

## Testing & Deterministic Verification

To test URP agents without incurring external LLM API costs or network delays, `urp-core` provides `tests/fixtures/fake_pi_rpc.py`, a fast mock RPC harness.

Pass `executable_path=FAKE_PI_SCRIPT` in `AgentContext.configuration` during tests:
```bash
cd urp-core
PYTHONPATH=. .venv/bin/pytest
```
All integration tests run deterministically in seconds.
