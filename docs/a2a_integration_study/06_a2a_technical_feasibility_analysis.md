# Technical Feasibility Analysis: A2A Protocol Implementation for URP

> **Document Version:** 1.0.0  
> **Status:** Completed Feasibility Analysis & Architectural Design Proposal  
> **Scope:** Integrating the Agent2Agent (A2A) v1.0 standard into `urp-core` & `URP-HF` with the WebHMI as the primary reference A2A client.

---

## 1. Executive Summary

We have evaluated the feasibility of implementing the **Agent2Agent (A2A) v1.0 Protocol** as an interoperable communication layer above the **Unified Runtime Primitive (URP)**. 

### Core Conclusion: **Feasible and Architecturally Aligned**
The integration is **highly feasible** with **zero architectural compromises** to `urp.core`. URP's execution ABI and finite state machine (FSM) naturally map to A2A semantics:
1. **URP `MessageEnvelope` $\rightleftharpoons$ A2A `Message` / `Part`**: URP already possesses native `context_id`, `task_id`, `type`, and structured payloads.
2. **URP Non-Blocking FSM $\rightleftharpoons$ A2A Asynchronous Task Lifecycle**: URP's `WAITING` $\rightleftharpoons$ `PROCESSING` transitions cleanly map to A2A states (`TASK_STATE_SUBMITTED`, `TASK_STATE_WORKING`, `TASK_STATE_COMPLETED`, `TASK_STATE_FAILED`).
3. **URP Event Bus $\rightleftharpoons$ A2A Server-Sent Events (SSE)**: URP emits intermediate progress, tool execution logs, and terminal results over an asynchronous event queue. This is a 1:1 match for A2A's HTTP+JSON streaming binding (`POST /message:stream` and `POST /tasks/{id}:subscribe`).
4. **Dogfooding via WebHMI**: By refactoring the existing browser UI (`urp/web/templates/index.html`) to act as the first reference A2A client, we guarantee full protocol compliance and feature parity between human users and autonomous peer agents.

---

## 2. A2A Protocol Specification Mapping

The official A2A specification defines three protocol bindings: **HTTP+JSON/REST**, **JSON-RPC 2.0**, and **gRPC**. 

### 2.1 Recommended Protocol Binding for URP: **HTTP+JSON / REST with SSE**
We recommend standardizing on the **HTTP+JSON/REST binding** for the following reasons:
- **FastAPI Native:** Fits directly into `URP-HF` (`FastAPI` + `uvicorn`) without introducing heavy gRPC compilation toolchains or protobuf stubs.
- **WebHMI Compatibility:** Standard browser APIs (`fetch()` and `EventSource`) can directly consume REST endpoints and SSE streams.
- **Enterprise-friendly:** Simple standard HTTP methods, standard status codes, and `text/event-stream`.

### 2.2 Canonical Wire Endpoint Mapping

| A2A Specification Operation | HTTP Method & Path | URP Kernel (`URPHost` / `AgentRegistry`) Execution |
|---|---|---|
| **Agent Card Discovery** | `GET /.well-known/agent.json` | Returns dynamic `AgentCard` via `agent_descriptor.to_agent_card(base_url)`. Also exposes catalog at `GET /a2a/agents`. |
| **Send Message (Sync)** | `POST /message:send` | Validates input parts $\rightarrow$ translates to `MessageEnvelope` $\rightarrow$ pushes to `host.send()` $\rightarrow$ awaits terminal event $\rightarrow$ returns A2A `Message` or completed `Task`. |
| **Send Streaming Message** | `POST /message:stream` | Translates message $\rightarrow$ dispatches into mailbox $\rightarrow$ returns `text/event-stream` (SSE) yielding initial `Task`, intermediate `TaskStatusUpdateEvent` / `TaskArtifactUpdateEvent`, and final completed `Task`. |
| **Get Task Status** | `GET /tasks/{task_id}` | Queries `URPHost` active task state or task persistence store $\rightarrow$ returns `Task` snapshot. |
| **List Tasks** | `GET /tasks` | Queries task store for current session / context $\rightarrow$ returns `ListTasksResponse` with cursor-based pagination. |
| **Subscribe to Task Updates** | `POST /tasks/{task_id}:subscribe` | Connects an `EventSource` (SSE) to an ongoing task's event stream. |
| **Cancel Task** | `POST /tasks/{task_id}:cancel` | Dispatches cancellation envelope to `URPHost` $\rightarrow$ agent transitions to `WAITING` $\rightarrow$ returns updated `Task` with `TASK_STATE_CANCELED`. |

---

## 3. Data Model Translation Mechanics (`urp.a2a`)

### 3.1 Inbound Translation: A2A $\rightarrow$ URP

```
A2A SendMessageRequest
  ├── message: A2AMessage
  │     ├── role: "ROLE_USER"
  │     ├── contextId: "session-abc"
  │     ├── taskId: "task-xyz"
  │     └── parts: [ { text: "Fix bug in auth.py" }, { file: { uri: "..." } } ]
  └── ...
                     │
                     ▼ urp.a2a.translator.a2a_to_envelope()
MessageEnvelope
  ├── id: UUID
  ├── context_id: "session-abc"
  ├── task_id: "task-xyz"
  ├── type: "MESSAGE"
  ├── sender: "a2a_client"
  └── payload: {
        "text": "Fix bug in auth.py",
        "parts": [...],
        "metadata": { "role": "ROLE_USER" }
      }
```

### 3.2 Outbound Translation: URP Events $\rightarrow$ A2A SSE Stream

```
URP Emitted Envelope
  │
  ├── AGENT_STARTED            ──► TaskStatusUpdateEvent(state="TASK_STATE_WORKING")
  ├── AGENT_TOOL_START/END     ──► TaskStatusUpdateEvent(state="TASK_STATE_WORKING", details={...})
  ├── AGENT_PROGRESS_UPDATE    ──► TaskStatusUpdateEvent(state="TASK_STATE_WORKING", message=...)
  │
  ├── TASK_COMPLETED           ──► 1. TaskArtifactUpdateEvent(artifacts=[...])
  │                                2. TaskStatusUpdateEvent(state="TASK_STATE_COMPLETED")
  │                                3. Final Task object snapshot (stream terminates)
  │
  └── TASK_FAILED              ──► 1. TaskStatusUpdateEvent(state="TASK_STATE_FAILED", error=...)
                                   2. Final Task object snapshot (stream terminates)
```

---

## 4. State Machine Harmonization

| URP Lifecycle Status (`AgentStatus`) | URP Task Outcome (`LastTaskOutcome`) | Canonical A2A Task State (`TaskState`) |
|---|---|---|
| `UNINITIALIZED` / `INITIALIZED` | — | *(Pre-task: Agent offline or deploying)* |
| `WAITING` | — | `TASK_STATE_SUBMITTED` (in mailbox queue) |
| `PROCESSING` | — | `TASK_STATE_WORKING` |
| `WAITING` | `TASK_COMPLETED` | `TASK_STATE_COMPLETED` |
| `WAITING` | `TASK_FAILED` | `TASK_STATE_FAILED` |
| `WAITING` | `WAITING_FOR_USER_INPUT` | `TASK_STATE_INPUT_REQUIRED` |
| `TERMINATED` | — | `TASK_STATE_CANCELED` (if aborted mid-task) |

*Key Verification:* Because we previously eliminated the blocking supervisor handshake (`acknowledge_outcome`), agents automatically transition `PROCESSING` $\rightarrow$ `WAITING` upon emitting terminal events. This matches A2A's state flow where the agent returns to ready status once the task outcome is published.

---

## 5. WebHMI as the First A2A Client (The Dogfooding Approach)

Currently, `urp/web/templates/index.html` uses non-standard REST endpoints:
- `POST /agent/init`
- `POST /agent/message`
- `GET /ws` (bespoke WebSocket JSON envelopes)

### Proposed WebHMI Architecture:
```
  ┌────────────────────────────────────────────────────────┐
  │                   Browser (WebHMI)                     │
  │                                                        │
  │  1. Agent Selection:                                   │
  │     GET /.well-known/agent.json (loads skills & card)  │
  │                                                        │
  │  2. Dispatch Message / Task:                           │
  │     POST /message:stream                               │
  │     Payload: { "message": { "parts": [{"text": ...}] } }│
  │                                                        │
  │  3. Real-Time Streaming:                               │
  │     Consumes SSE (text/event-stream) response:         │
  │     - TaskStatusUpdateEvent (updates status dot)       │
  │     - Tool call logs (renders collapsible cards)       │
  │     - TaskArtifactUpdateEvent (renders file downloads) │
  │     - Terminal Task snapshot (completes turn)          │
  └───────────────────────────┬────────────────────────────┘
                              │ Standard A2A HTTP+JSON / SSE
                              ▼
  ┌────────────────────────────────────────────────────────┐
  │              URP-HF FastAPI / a2a Router               │
  │               (urp/a2a/router.py)                      │
  └────────────────────────────────────────────────────────┘
```

**Benefits of this Approach:**
1. **Immediate Verification:** We do not rely on mocked integration tests alone; the browser UI becomes a living, visual test suite for A2A wire compliance.
2. **Standardization:** No proprietary API contracts between front-end and back-end. Any third-party A2A client or CLI can point to the same server and receive identical responses.
3. **Simpler Networking:** Replaces bidirectional WebSocket error recovery loops with HTTP POST + SSE streaming, which natively supports automatic reconnect and event ID tracking.

---

## 6. Target Directory & Module Structure

To ensure clean isolation and maintain zero leaks into `urp.core`, all A2A code will live in a dedicated subpackage:

```text
urp/
├── core/                       # Zero dependencies on A2A or web protocols
│   ├── abstract_urp.py
│   ├── data_types.py
│   ├── agent_registry.py
│   └── host.py
├── a2a/                        # NEW: Pure A2A Protocol Implementation
│   ├── __init__.py
│   ├── models.py               # Pydantic v2 schemas: AgentCard, Message, Task, Events
│   ├── translator.py           # Bidirectional conversion: A2A <-> URP MessageEnvelope
│   ├── task_manager.py         # In-memory / persistent A2A task state tracker
│   ├── router.py               # FastAPI APIRouter implementing standard A2A endpoints
│   └── client.py               # Outbound A2A client for inter-agent dialing
├── harnesses/                  # Engine adapters (Pi, OpenHands)
├── agents/                     # Concrete agents (EchoAgent, PiGeminiAgent)
└── web/                        # Hosting Framework & Web UI
    ├── app.py                  # Mounts urp.a2a.router
    ├── templates/index.html    # Refactored to communicate via A2A
    └── workspace_service.py    # Artifact file serving
```

---

## 7. Phased Implementation Roadmap

### Sprint 1: Schemas & Translation (Estimated Effort: 1-2 hours)
- Create `urp/a2a/models.py` with standard Pydantic models (matching `a2a.proto` / `a2a.json`).
- Implement `urp/a2a/translator.py` with unit tests for loss-less conversions.

### Sprint 2: A2A Task Manager & HTTP/SSE Endpoints (Estimated Effort: 2-3 hours)
- Create `urp/a2a/task_manager.py` to maintain task lifecycle history and artifact bindings.
- Implement `urp/a2a/router.py`:
  - `GET /.well-known/agent.json`
  - `POST /message:send`
  - `POST /message:stream` (SSE via `StreamingResponse`)
  - `GET /tasks/{id}`
  - `POST /tasks/{id}:cancel`
- Mount router onto `urp/web/app.py`.

### Sprint 3: WebHMI Migration to A2A Client (Estimated Effort: 1-2 hours)
- Refactor `urp/web/templates/index.html` to:
  - Query `/.well-known/agent.json` for agent details and skills.
  - Submit prompts via `POST /message:stream`.
  - Process SSE events for tool call collapsible cards and assistant messages.

### Sprint 4: Comprehensive Verification & Test Suite (Estimated Effort: 1-2 hours)
- Add `tests/test_a2a_models.py` (JSON schema compliance).
- Add `tests/test_a2a_endpoints.py` (HTTP client tests covering sync, streaming, and cancellation).
- Add `tests/test_a2a_live_agent.py` (live end-to-end task execution with `PiGeminiAgent`).

---

## 8. Risk Analysis & Mitigation

| Risk | Impact | Mitigation |
|---|---|---|
| **SSE Connection Drops** | Streaming broken if client disconnects | A2A provides `POST /tasks/{id}:subscribe` and `GET /tasks/{id}` to resume or poll status. Task manager retains task state independently of open HTTP connections. |
| **Large Artifact Transmission** | Sending huge files over SSE causes memory bloat | Follow A2A spec: Stream only `TaskArtifactUpdateEvent` containing file metadata and download URI; serve file contents via dedicated static/streamed artifact endpoints. |
| **Breaking Existing Tests** | Web console changes break current test suite | Keep legacy `/agent/*` endpoints intact or migrate `test_web_server.py` incrementally alongside the new A2A tests. |

---

## 9. Recommendation & Approval Request

The technical analysis confirms that A2A v1.0 fits naturally on top of URP with no friction. 

**Recommended Action:** Proceed with **Sprint 1 & Sprint 2** (implementing `urp.a2a.models`, `urp.a2a.translator`, and `urp.a2a.router`), followed by **Sprint 3** (migrating WebHMI to be the primary reference A2A client).
