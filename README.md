# Unified Runtime Primitive (URP) — Reference Architecture & Specification

> **Package:** `urp-core`  
> **License:** Apache License 2.0 (Apache-2.0)  
> **Status:** Reference Implementation & Architecture Specification  
> **Primary Reference Implementation:** Python (`urp`)

---

## 1. Executive Summary & Core Philosophy

The **Unified Runtime Primitive (URP)** is a language-agnostic, minimal, stateful, message-driven runtime abstraction for artificial intelligence agents. While the AI ecosystem contains numerous high-level agent frameworks (OpenHands, LangGraph, AutoGen, CrewAI), URP operates at a lower structural abstraction layer: **the Application Binary Interface (ABI) and execution primitive for agent execution**.

URP is **not** another high-level agent framework. It is an **opaque runtime execution primitive** designed to isolate individual stateful agents from multi-agent system (MAS) orchestration topologies, supervisory control systems (such as AOSM), and networking protocols (such as Agent2Agent / A2A).

```
  ┌────────────────────────────────────────────────────────────────────────┐
  │                   HIGH-LEVEL MAS / NETWORK TOPOLOGY                    │
  │            (A2A Protocol, AOSM Supervisor, Multi-Agent Bus)            │
  └───────────────────────────────────┬────────────────────────────────────┘
                                      │  <--- Network / Semantics (A2A / RPC)
  ════════════════════════════════════╪════════════════════════════════════  <--- URP BOUNDARY
                                      │  <--- ABI / Process Primitive (URP Mailbox & Handles)
  ┌───────────────────────────────────┴────────────────────────────────────┐
  │                       UNDERLYING AGENT ENGINE                          │
  │     (OpenHands SDK, ReAct / Pi Loops, LangGraph, C/tiny-agent)         │
  └────────────────────────────────────────────────────────────────────────┘
```

### The Fundamental Axiom

Every URP agent—regardless of whether it is written in Python, C, Go, or Rust—conforms to a strict, non-blocking state transition loop:

$$\text{Initialize Once} \longrightarrow \text{Wait} \longrightarrow \text{Receive Message} \longrightarrow \text{Process Async} \longrightarrow \text{Emit Events/Result} \longrightarrow \text{Wait}$$

---

## 2. The URP Boundary: Architectural Isolation

URP divides multi-agent system architecture into two non-leaking layers:

```text
               AOSM / Orchestrator / External World
                                 │
                    MessageEnvelope (Mailbox Ingestion)
                                 │
 ════════════════════════════════╪════════════════════════════════ <--- URP BOUNDARY
                                 │  <--- mailbox.get() / process()
                                 ▼
┌─────────────────────────────────────────────────────────────────┐
│                      URP AGENT INSTANCE                         │
│                    (AbstractURPAgent Base)                      │
│                                                                 │
│  ┌───────────────────────────────────────────────────────────┐  │
│  │    PRECONDITION VERIFICATION (_check_preconditions)       │  │
│  └─────────────────────────────┬─────────────────────────────┘  │
│                                ▼                                │
│  ┌───────────────────────────────────────────────────────────┐  │
│  │    CORE EXECUTION ENGINE (process)                        │  │
│  │    - Autonomous ReAct / Tool Invocation                   │  │
│  │    - Sub-agent Delegation / SDK Tool Execution            │  │
│  └─────────────────────────────┬─────────────────────────────┘  │
│                                ▼                                │
│  ┌───────────────────────────────────────────────────────────┐  │
│  │    POSTCONDITION VERIFICATION (_check_postconditions)     │  │
│  └─────────────────────────────┬─────────────────────────────┘  │
│                                │                                │
│                                ▼ Returns ProcessResult          │
└────────────────────────────────┬────────────────────────────────┘
                                 │
 ════════════════════════════════╪════════════════════════════════ <--- URP BOUNDARY
                                 │
                    MessageEnvelope (Auto-Emitted Events & Results)
```

### Above the URP Boundary (Outer MAS, Host & Orchestration)

The outer orchestration layer (or host runtime) sees every agent purely as an addressable, event-emitting state machine. It interacts strictly via:
* **Asynchronous Mailboxes (`MessageEnvelope`):** Sending typed messages without directly accessing internal state or call stacks.
* **Decoupled Inspection (`AgentHandle` & `AgentReadiness`):** Querying external readiness and lifecycle status without mutating state.
* **Asynchronous Event Streaming:** Consuming emitted lifecycle events, intermediate progress reports, and final task outcomes.

### Below the URP Boundary (The Agent Execution Engine)

The agent engine executes inside an opaque boundary. Subclasses of `AbstractURPAgent` maintain internal context, manage tool execution (e.g., file editors, terminal shells, MCP servers), execute reasoning loops (such as OpenHands SDK or ReAct loops), evaluate precondition/postcondition assertions, and return typed `ProcessResult` structures.

---

## 3. Core Primitive Data Types

The Python implementation (`urp-core`) formalizes the primitive objects defined in the URP specification:

```
                  ┌──────────────────────┐
                  │   AgentDescriptor    │
                  │  (Static Identity)   │
                  └──────────┬───────────┘
                             │ describes
                             ▼
┌─────────────────────┐  instantiates   ┌─────────────────────┐
│    AgentContext     ├────────────────►│  AbstractURPAgent   │
│(Injected Resources) │                 │  (Runtime State M/C)│
└─────────────────────┘                 └──────────┬──────────┘
                                                   │
                   ┌───────────────────────────────┴───────────────────────────────┐
                   ▼                                                               ▼
        ┌─────────────────────┐                                         ┌─────────────────────┐
        │   MessageEnvelope   │                                         │    ProcessResult    │
        │  (Mailbox & Events) │                                         │ (Outcome & Category)│
        └─────────────────────┘                                         └─────────────────────┘
```

### 3.1 Static Descriptor: `AgentDescriptor`
Declares the static capabilities and identity of an agent type:
* `agent_id`: Globally unique identifier string (e.g., `vhl.sdk_example.v1`).
* `name`: Human-readable name.
* `version`: Semantic version string.
* `capabilities`: Declared capability tags (e.g., `["TERMINAL", "FILE_EDITOR"]`).
* `accepted_message_types`: List of message types accepted by the mailbox.

### 3.2 Injected Environment: `AgentContext`
Dependencies provided once during agent initialization:
* `workspace_handle`: Filesystem workspace handle or directory path.
* `tool_registry`: Accessible tool adapters.
* `llm_adapter`: LLM client or configuration.
* `persistent_memory_handle`: Long-term memory handle.
* `configuration`: Injected parameters, environment variables, or session overrides.

### 3.3 Dynamic State: `AgentState` & `AgentStatus`
Tracks agent runtime progression across its formal state machine:
* `AgentStatus`: `UNINITIALIZED` $\rightarrow$ `INITIALIZED` $\rightarrow$ `WAITING` $\rightleftharpoons$ `PROCESSING` $\rightarrow$ `TERMINATED` (or `ERROR`).
* `session_id`: Unique identifier for the persistent conversation/session.
* `last_process_result`: The outcome of the most recent message processing cycle.

### 3.4 Messaging & Event Envelope: `MessageEnvelope`
Universal vehicle for all inputs and outputs across the boundary:
* `message_id`, `correlation_id`: Unique tracing and causality IDs.
* `type`: Semantic type (e.g., `MESSAGE`, `TASK_COMPLETED`, `TASK_FAILED`, `AGENT_STARTED`).
* `sender`, `receiver`: Source and destination endpoints.
* `payload`: Structured or primitive content payload.
* `metadata`, `timestamp`: Routing metadata and UTC timestamp.

### 3.5 Structured Execution Outcome: `ProcessResult`
Represents the evaluated outcome of processing a message:
* `outcome`: `LastTaskOutcome` (`TASK_COMPLETED`, `TASK_FAILED`, `WAITING_FOR_USER_INPUT`, `NONE`).
* `category`: `FailureCategory` (`AGENTIC_FAILURE`, `PRECONDITION_FAILURE`, `POSTCONDITION_FAILURE`, `VALIDATION_FAILURE`, `INFRASTRUCTURE_FAILURE`, `NONE`).
* `payload`: Optional `ProcessResultPayload` containing response text or structured artifacts.

---

## 4. Lifecycle Contract & Verification Pipeline

Every `AbstractURPAgent` adheres to a verified execution lifecycle with built-in precondition and postcondition gates:

```text
 1. initialize(context, emit_callback)
    ├── Guard: AgentStatus == UNINITIALIZED
    ├── Injects context and event callback
    ├── Executes child hook: _on_initialize(context)
    └── State -> INITIALIZED

 2. start()
    ├── Guard: AgentStatus == INITIALIZED
    ├── Verifies: _check_start_preconditions()
    ├── Spawns: _lifecycle_loop() background task
    ├── State -> WAITING
    └── Emits: AGENT_STARTED

 3. send(message)
    ├── Guard: AgentStatus != TERMINATED
    └── Pushes MessageEnvelope to asyncio.Queue mailbox

 4. _lifecycle_loop() [Continuous State Machine]
    ├── message = await mailbox.get()
    ├── Gate 1: _check_preconditions(message)
    │   └── Fail -> Emit TASK_PRECONDITIONS_VIOLATED & return to WAITING
    ├── State -> PROCESSING
    ├── result = await process(message)
    ├── Gate 2: _check_postconditions(message, result)
    │   └── Fail -> Emit TASK_POSTCONDITIONS_VIOLATED
    ├── State -> WAITING
    └── Auto-Emit: result.outcome event (e.g., TASK_COMPLETED / TASK_FAILED)

 5. shutdown()
    ├── Sets shutdown signal
    ├── Executes child hook: _on_shutdown()
    ├── State -> TERMINATED
    └── Emits: AGENT_TERMINATED
```

### Mandatory Invariants

1. **Initialize Exactly Once:** An agent rejects re-initialization if already in `INITIALIZED` or beyond.
2. **Mailbox-Only Ingestion:** State cannot be mutated via external function calls; all inputs must enter through `send(MessageEnvelope)`.
3. **Emit-Only Output:** Output leaves solely through `emit(MessageEnvelope)` callbacks.
4. **State Persistence:** Conversation sessions, workspace handles, and tool connections persist across consecutive message dispatches.
5. **Contract Enforced Verification:** Preconditions and postconditions run deterministically around `process()`, ensuring system-level safety assertions cannot be bypassed.

---

## 5. Registry & Semantic Identity Layer

To decouple agent instantiation from orchestration control flow, URP provides a registry abstraction (`urp.agent_key` and `urp.agent_registry`):

```
       ┌────────────────────────────────────────┐
       │               AgentKey                 │
       │    (agent_type, module_name)           │
       └───────────────────┬────────────────────┘
                           │ identifies
                           ▼
┌───────────────────────────────────────────────┐
│                 AgentRegistry                 │
│  - register_agent(name, factory, descriptor)  │
│  - pre/post create lifecycle hooks            │
│  - create_agent(name, ...)                    │
└──────────────────────────┬────────────────────┘
                           │ creates & wraps
                           ▼
┌───────────────────────────────────────────────┐
│                  AgentHandle                  │
│  - send(message) [Mailbox delivery]           │
│  - state [Read-only runtime inspection]       │
│  - readiness: AgentReadiness (READY/DEGRADED) │
└───────────────────────────────────────────────┘
```

* **Composite Semantic Identity (`AgentKey`):** Maps agents to domain roles and modules (e.g., `AgentKey("archy", "bms-monitor-module")`).
* **System-Level Readiness (`AgentReadiness`):** Exposes whether an agent is `READY`, `NOT_READY`, `DEGRADED`, or `TERMINATED` to higher-level schedulers (e.g., AOSM) without breaking encapsulation.
* **Controlled Access (`AgentHandle`):** AOSM and external orchestrators interact with agents exclusively through handles, enforcing read-only state inspection and mailbox-only communication.

---

## 6. Reference Implementation Guide (`urp-core`)

The `urp-core` Python package serves as the reference implementation of the URP specification.

### Installation

```bash
# Clone the repository
git clone https://github.com/your-org/unified-runtime-primitive.git
cd unified-runtime-primitive

# Install package in editable mode
pip install -e .
```

### Implementing a Custom URP Agent

Below is a minimal conceptual implementation illustrating how to subclass `AbstractURPAgent` and leverage lifecycle hooks:

```python
import asyncio
from urp import (
    AbstractURPAgent,
    AgentDescriptor,
    AgentContext,
    MessageEnvelope,
    ProcessResult,
    ProcessResultPayload,
    LastTaskOutcome,
    FailureCategory,
)

class SampleReActAgent(AbstractURPAgent):
    """
    Conceptual URP Agent subclass implementing an autonomous execution loop.
    """

    def _on_initialize(self, context: AgentContext) -> None:
        """Invoked once during initialize(). Bind dependencies and workspace."""
        self.workspace = context.workspace_handle
        self.config = context.configuration

    async def _check_preconditions(self, message: MessageEnvelope) -> tuple[bool, str]:
        """Verify inputs, workspace readiness, and dependencies prior to processing."""
        if not message.payload:
            return False, "Message payload cannot be empty."
        return True, "Preconditions satisfied."

    async def process(self, message: MessageEnvelope) -> ProcessResult:
        """
        Core execution primitive.
        Autonomous reasoning, tool execution, and intermediate event emission.
        """
        user_text = message.payload.get("text", "") if isinstance(message.payload, dict) else str(message.payload)

        # Emit intermediate progress event
        await self.emit(MessageEnvelope(
            type="TASK_PROGRESS",
            payload={"step": "reasoning", "input": user_text},
            sender=self.descriptor.agent_id,
            correlation_id=message.correlation_id
        ))

        # Perform reasoning / tool execution
        await asyncio.sleep(0.5)
        response_text = f"Processed query: {user_text}"

        return ProcessResult(
            outcome=LastTaskOutcome.TASK_COMPLETED,
            payload=ProcessResultPayload(text=response_text)
        )

    async def _check_postconditions(self, message: MessageEnvelope, result: ProcessResult) -> tuple[bool, str]:
        """Validate output artifacts or assertions before committing the outcome."""
        if result.outcome == LastTaskOutcome.TASK_COMPLETED and not result.payload:
            return False, "Completed task must contain a valid result payload."
        return True, "Postconditions satisfied."
```

### Hosting Kernel & Execution (`URPHost`)

`URPHost` is the reference runtime host kernel that manages agent instantiation, lifecycle transitions, event routing, and communication:

```python
import asyncio
from urp.host import URPHost
from urp.data_types import AgentDescriptor, AgentContext

async def main():
    descriptor = AgentDescriptor(
        agent_id="sample.agent.v1",
        name="Sample Agent",
        version="1.0",
        capabilities=["TEXT_PROCESSING"],
        accepted_message_types=["MESSAGE"]
    )

    host = URPHost(agent_class=SampleReActAgent, descriptor=descriptor)

    # Attach event listener
    async def on_event(event):
        print(f"Captured Event [{event.type}]: {event.payload}")

    host.set_emit_callback(on_event)

    # Initialize and start agent
    context = AgentContext(configuration={"debug": True})
    await host.initialize_and_start(context)

    # Dispatch message via mailbox
    msg_id = await host.send_message("MESSAGE", {"text": "Execute task A"})
    
    # Await emitted events
    while True:
        event = await host.get_next_event()
        if event.type in ["TASK_COMPLETED", "TASK_FAILED"]:
            print(f"Final Task Outcome: {event.payload}")
            break

    # Graceful termination
    await host.shutdown()

if __name__ == "__main__":
    asyncio.run(main())
```

---

## 7. OpenHands SDK Integration (`SDKURPAgent`)

`urp-core` includes a full bridge for the **OpenHands SDK** (`urp.sdk_agent.SDKURPAgent`), illustrating how heavy LLM agent engines with terminal tools and file editors run transparently below the URP boundary:

* Encapsulates `openhands.sdk.Conversation`, `openhands.sdk.Agent`, and `openhands.tools` (such as `FileEditorTool` and `TerminalTool`).
* Maps SDK conversation lifecycle states (`FINISHED`, `PAUSED`, `STUCK`, `ERROR`) directly to canonical URP outcomes (`TASK_COMPLETED`, `WAITING_FOR_USER_INPUT`, `TASK_FAILED`).
* Provides persistent conversation state restoration across host reboots via conversation directory mappings.

---

## 8. Comparative Architectural Positioning

| Feature / Dimension | Classical Actor Model (Erlang/Akka) | High-Level Agent Frameworks (OpenHands, LangGraph) | URP (`urp-core`) |
| --- | --- | --- | --- |
| **Primary Scope** | Concurrent distributed message passing | Agent prompt engineering, graph workflows, tool loops | **Execution ABI & Runtime Contract Primitive** |
| **State Contract** | Ephemeral process heap state | Framework-specific graph / memory objects | **Strict FSM (`AgentStatus`) & Persistent Workspace/Session** |
| **Safety Invariants** | Actor failure supervision trees | Application-level exceptions / error handling | **Contractual Pre/Postcondition Gates & Outcome Ack** |
| **Interaction Boundary** | Process mailboxes | Direct method invocation / API wrappers | **Typed Envelopes (`MessageEnvelope`), Registry & Handles** |
| **Language Neutrality** | Erlang / JVM specific | Mostly Python / TypeScript | **Universal Contract (Python, C/tiny-agent, Rust, Go)** |

---

## 9. [License](LICENSE)

This project is licensed under the **Apache License, Version 2.0 (Apache-2.0)**.
