# Architecture: Lifecycle & State Machine

This document details the lifecycle state machine, execution loop, condition verification pipeline, and non-blocking state transitions implemented in `urp.core.abstract_urp` (`AbstractURPAgent`).

---

## 1. Lifecycle State Machine

Every URP agent is governed by an explicit finite state machine (`AgentStatus` defined in `urp.core.data_types`):

```
                        ┌──────────────────┐
                        │  UNINITIALIZED   │
                        └────────┬─────────┘
                                 │ initialize(context, emit_cb)
                                 ▼
                        ┌──────────────────┐
                        │   INITIALIZED    │
                        └────────┬─────────┘
                                 │ start() [verifies start preconditions]
                                 ▼
            ┌──────────► ┌──────────────────┐
            │            │     WAITING      │
            │            └────────┬─────────┘
            │                     │ mailbox.get() & pre_ok == True
            │                     ▼
            │            ┌──────────────────┐
            │            │    PROCESSING    │
            │            └────────┬─────────┘
            │                     │ process() completes & emits outcome
            └─────────────────────┘
                                 │
                                 │ shutdown()
                                 ▼
                        ┌──────────────────┐
                        │    TERMINATED    │
                        └──────────────────┘
```

### State Definitions

| State | Description | Permitted Inbound Operations |
|---|---|---|
| `UNINITIALIZED` | Instantiated via `__init__(descriptor)`. Baseline state. | `initialize(context, emit_callback)` |
| `INITIALIZED` | Context and event callback bound; `_on_initialize()` executed. | `start()` |
| `WAITING` | Agent lifecycle loop is running, listening for incoming mailbox messages. | `send(message)`, `shutdown()` |
| `PROCESSING` | Preconditions verified; agent is actively executing `process(message)`. | `send(message)` (queued), `shutdown()` |
| `TERMINATED` | Agent has safely cleaned up resources via `_on_shutdown()` and exited. | Read-only inspection (`state`) |
| `ERROR` | Critical unrecoverable lifecycle failure. | Read-only inspection (`state`) |

---

## 2. The Core Execution Loop (`_lifecycle_loop`)

When `start()` is invoked, an asynchronous background task `_lifecycle_loop()` is spawned. It enforces non-blocking queue ingestion, safety preconditions, outcome generation, postconditions, and automatic event dispatching.

```text
               ┌────────────────────────────────────────────────────────┐
               │                 Enter Loop Iteration                   │
               └───────────────────────────┬────────────────────────────┘
                                           │
                                           ▼
               ┌────────────────────────────────────────────────────────┐
               │    mailbox.get() (0.5s poll timeout check)             │
               └───────────────────────────┬────────────────────────────┘
                                           │
                                           ▼
               ┌────────────────────────────────────────────────────────┐
               │    _check_preconditions(message)                       │
               └───────────────┬────────────────────────┬───────────────┘
                               │ False                  │ True
                               ▼                        ▼
     ┌───────────────────────────────────┐    ┌───────────────────────────────────┐
     │ Emit:                             │    │ State -> PROCESSING               │
     │ TASK_PRECONDITIONS_VIOLATED       │    │ result = await process(message)   │
     │ outcome = TASK_FAILED             │    └─────────────────┬─────────────────┘
     │ category = PRECONDITION_FAILURE   │                      │
     └─────────────────┬─────────────────┘                      ▼
                       │                      ┌───────────────────────────────────┐
                       │                      │ _check_postconditions(msg, result)│
                       │                      └────────┬──────────────────┬───────┘
                       │                               │ False            │ True
                       │                               ▼                  ▼
                       │          ┌───────────────────────────┐ ┌─────────────────┐
                       │          │ Emit:                     │ │ State -> WAITING│
                       │          │ TASK_POSTCONDITIONS_      │ │ Emit outcome:   │
                       │          │ VIOLATED                  │ │ TASK_COMPLETED /│
                       │          │ outcome = result.outcome  │ │ TASK_FAILED /   │
                       │          │ category = POSTCONDITION_ │ │ WAITING_FOR_    │
                       │          │ FAILURE                   │ │ USER_INPUT      │
                       │          └─────────────┬─────────────┘ └────────┬────────┘
                       │                        │                        │
                       ▼                        ▼                        ▼
               ┌──────────────────────────────────────────────────────────────────┐
               │                      mailbox.task_done()                         │
               └──────────────────────────────────────────────────────────────────┘
```

---

## 3. Condition Verification Pipeline

URP incorporates deterministic contract verification around every task execution cycle. Child agent classes override these hooks to enforce domain invariants.

### 3.1 Start Preconditions (`_check_start_preconditions`)

* **Execution Point:** Called synchronously inside `start()`.
* **Signature:** `async def _check_start_preconditions(self) -> tuple[bool, str]`
* **Behavior on Failure:** If `False`, emits `AGENT_START_PRECONDITIONS_VIOLATED` and raises `StartPreconditionsViolatedError`.

### 3.2 Task Preconditions (`_check_preconditions`)

* **Execution Point:** Called immediately after a `MessageEnvelope` is dequeued from `mailbox`, before transitioning to `PROCESSING`.
* **Signature:** `async def _check_preconditions(self, message: MessageEnvelope) -> tuple[bool, str]`
* **Behavior on Failure:** Does not transition to `PROCESSING`. Emits `TASK_PRECONDITIONS_VIOLATED` with `category=FailureCategory.PRECONDITION_FAILURE`, marks `mailbox.task_done()`, and returns the agent to `WAITING`.

### 3.3 Task Postconditions (`_check_postconditions`)

* **Execution Point:** Called immediately after `process(message)` returns successfully, before committing the final outcome.
* **Signature:** `async def _check_postconditions(self, message: MessageEnvelope, result: ProcessResult) -> tuple[bool, str]`
* **Behavior on Failure:** Emits `TASK_POSTCONDITIONS_VIOLATED`. Preserves the `outcome` returned by `process()` while setting the category to `POSTCONDITION_FAILURE` (or child-defined categorical failure).

---

## 4. First-Class In-Flight Streaming & Sub-Task Tracking

URP provides native support for in-flight progressive streaming without violating the FSM:

1. **Streaming Negotiation:** Inbound `MessageEnvelope` objects declare `streaming=True` when progressive output is requested (e.g. from A2A `POST /message:stream`).
2. **Execution Context:** During `_lifecycle_loop()`, the active envelope is accessible via `self._current_message` and `self.is_streaming`.
3. **In-Flight Chunk Emission:** Subclasses invoke `self.emit_chunk(chunk, event_type="TEXT_DELTA")`. If `streaming=True`, chunks are emitted onto the event bus in real time; if `streaming=False`, intermediate chunks are cleanly suppressed to avoid bus congestion.
4. **Sub-Task Delegation Interception:** When an agent invokes sub-agents (such as via Pi's `delegate` tool), tool start/end events are mapped directly into `TASK_SUBTASK_STARTED` and `TASK_SUBTASK_COMPLETED` envelopes carrying the active `task_id`.

---

## 5. Failure Categorization

All task failures are categorized using `FailureCategory` (`urp.core.data_types`):

| Category | Trigger / Cause |
|---|---|
| `NONE` | Normal operation or successful task completion. |
| `PRECONDITION_FAILURE` | Input envelope invalid, missing parameters, or missing prerequisites. |
| `POSTCONDITION_FAILURE` | Task produced results violating expected assertions, schema, or invariants. |
| `AGENTIC_FAILURE` | LLM reasoning breakdown, stuck ReAct loop, or internal agent logic failure. |
| `VALIDATION_FAILURE` | Artifact schema mismatch or format validation error. |
| `INFRASTRUCTURE_FAILURE` | Unhandled runtime exception, network disconnect, or host process crash. |
