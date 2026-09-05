# AGENTS.md — Developer & Agent System Architecture Guide

> **Repository:** `urp-core` (Unified Runtime Primitive — Python Core Implementation)  
> **Documentation Model:** Progressive Disclosure  
> **Status:** Active Reference Implementation

Welcome to the **`urp-core`** codebase. This document serves as the top-level architectural map and orientation guide for human engineers and autonomous coding agents. Detailed operational specifications and deep-dive guides are progressively disclosed under the [`.agents/`](.agents/) directory.

---

## 1. System Orientation & High-Level Invariants

**URP (Unified Runtime Primitive)** is an execution ABI and runtime contract layer for stateful AI agents. It isolates individual agent execution loops from outer multi-agent system (MAS) orchestration topologies, supervisory control systems (such as AOSM), and network protocols (such as A2A).

### Key Architectural Invariants

1. **Strict Lifecycle FSM:** Agents progress strictly through `UNINITIALIZED` $\rightarrow$ `INITIALIZED` $\rightarrow$ `WAITING` $\rightleftharpoons$ `PROCESSING` $\rightarrow$ `TERMINATED`.
2. **Mailbox-Driven Invocation:** External systems never invoke `process()` or mutate internal memory directly; all inbound inputs pass through `send(MessageEnvelope)`.
3. **Emit-Only Dispatches:** All outputs, intermediate progress signals, and final task outcomes exit strictly via `emit(MessageEnvelope)` callbacks.
4. **Deterministic Pre/Postcondition Gates:** `_check_preconditions()` and `_check_postconditions()` run deterministically around the execution loop, safeguarding invariant compliance and categorizing failures (`FailureCategory`).
5. **Encapsulated Handles:** Supervisory schedulers interact with agents via `AgentHandle` and evaluate system-level `AgentReadiness` without leaking internal execution details.

---

## 2. Progressive Disclosure Navigation Guide

For deep-dive topics, consult the corresponding specification documents in [`.agents/`](.agents/):

```
.agents/
├── architecture/
│   ├── lifecycle-and-state-machine.md    <-- FSM, _lifecycle_loop(), pre/postconditions, outcome ack
│   ├── data-types-and-envelopes.md       <-- Pydantic schemas, MessageEnvelope, ProcessResult, enums
│   └── registry-and-handles.md           <-- AgentKey, AgentReadiness, AgentEntry, AgentHandle, AgentRegistry
├── runtime/
│   └── hosting-and-kernel.md             <-- URPHost kernel, event routing, FastAPI / WebSocket console
└── guides/
    ├── authoring-agents.md               <-- Step-by-step guide to subclassing AbstractURPAgent & SDK bridge
    └── testing-and-verification.md       <-- Unit test patterns, lifecycle mocking, assertion validation
```

### Quick Reference Matrix

| If you need to... | Refer to... |
|---|---|
| Understand the FSM, mailbox loop, or precondition/postcondition pipeline | [`.agents/architecture/lifecycle-and-state-machine.md`](.agents/architecture/lifecycle-and-state-machine.md) |
| Inspect schema fields for descriptors, contexts, states, or envelopes | [`.agents/architecture/data-types-and-envelopes.md`](.agents/architecture/data-types-and-envelopes.md) |
| Work with `AgentKey`, `AgentReadiness`, `AgentHandle`, or `AgentRegistry` | [`.agents/architecture/registry-and-handles.md`](.agents/architecture/registry-and-handles.md) |
| Run or modify `URPHost`, the web console, or WebSocket event streams | [`.agents/runtime/hosting-and-kernel.md`](.agents/runtime/hosting-and-kernel.md) |
| Write a new custom agent or integrate OpenHands SDK tools | [`.agents/guides/authoring-agents.md`](.agents/guides/authoring-agents.md) |
| Write or update unit and integration tests | [`.agents/guides/testing-and-verification.md`](.agents/guides/testing-and-verification.md) |

---

## 3. Codebase File Map

```text
unified-runtime-primitive/
├── pyproject.toml              # Build & dependency configuration (FastAPI, Pydantic v2, OpenHands SDK)
├── run_host.py                 # CLI launcher for the URP Independent Hosting Framework
├── README.md                   # High-level conceptual architecture and specification
├── AGENTS.md                   # Agent & developer operational map (this document)
├── .agents/                    # Progressive disclosure deep-dive documentation
├── configs/
│   └── agents/                 # JSON agent definitions (pi_agent.json, sdk_agent.json, echo_agent.json)
├── urp/
│   ├── __init__.py             # Public module exports
│   ├── config_loader.py        # Dynamic JSON agent configuration loader
│   ├── core/                   # Pure URP runtime primitives (no external engine dependencies)
│   │   ├── __init__.py
│   │   ├── abstract_urp.py     # AbstractURPAgent base class & core lifecycle execution loop
│   │   ├── data_types.py       # Pydantic data models (Descriptor, Context, State, Envelope, Result)
│   │   ├── agent_key.py        # AgentKey, AgentReadiness, AgentEntry, and AgentHandle
│   │   ├── agent_registry.py   # Global & instance-based AgentRegistry with create hooks
│   │   └── host.py             # URPHost runtime host kernel
│   ├── harnesses/              # Pluggable execution engine adapters
│   │   ├── openhands/          # OpenHands SDK wrapper (SDKURPAgent)
│   │   └── pi/                 # Pi coding agent harness (PiURPAgent, PiRpcClient)
│   ├── agents/                 # Reference agent implementations (EchoAgent)
│   └── web/                    # Modular FastAPI & WebSocket hosting server
│       ├── app.py              # Application factory and lifespan handler
│       ├── routes.py           # REST endpoints and WebSocket stream
│       ├── schemas.py          # Request and response models
│       ├── agent_service.py    # URPHost lifecycle and registry coordination
│       ├── workspace_service.py# Session persistence and directory browser
│       └── templates/          # HTML5/CSS/JS dark-theme dashboard
└── tests/
    ├── test_basic.py           # Basic agent lifecycle and state transition unit tests
    ├── test_host.py            # URPHost integration tests
    ├── test_config_loader.py   # JSON configuration loader tests
    ├── test_web_server.py      # REST API and web console integration tests
    ├── test_pi_rpc_integration.py # Pi JSON-RPC client integration tests
    └── test_pi_urp_agent_integration.py # PiURPAgent integration tests
```

---

## 4. Development & Operation Workflows

### 4.1 Running the Interactive URP Host Console
```bash
# Start the URP-HF web server on port 8000
python run_host.py
```
Visit `http://localhost:8000` to interact with agents, send messages, observe event logs, and inspect state transitions in real time.

### 4.2 Executing Test Suites
```bash
# Run pytest with pytest-asyncio
pytest
```

### 4.3 Standard Pattern: Writing a Custom Agent
1. Inherit from `AbstractURPAgent` in `urp.core`.
2. Implement `_on_initialize(context)` to configure dependencies and workspace directories.
3. Implement `async def process(message: MessageEnvelope) -> ProcessResult` to execute reasoning and tool workflows.
4. Optionally implement `_check_preconditions` and `_check_postconditions` for contract verification.

For complete code examples, see [`.agents/guides/authoring-agents.md`](.agents/guides/authoring-agents.md).

---

## 5. Guidelines for Autonomous Coding Agents

When working on this repository, autonomous agents must adhere to the following rules:

1. **Preserve ABI Boundaries:** Do not expose `AbstractURPAgent` internals directly to external callers; interact through `MessageEnvelope` or `AgentHandle`.
2. **Maintain Pydantic Schemas:** Ensure all modifications to envelopes or state models in `urp/core/data_types.py` maintain backward compatibility and JSON serializability.
3. **Respect Sub-package Separation:** Pure URP abstractions belong in `urp/core/`, engine integrations belong in `urp/harnesses/`, reference agents in `urp/agents/`, and web server code in `urp/web/`.
4. **Update Progressive Documentation:** Whenever state machine semantics, registry APIs, or kernel bindings change, update the corresponding deep-dive documentation in `.agents/`.
