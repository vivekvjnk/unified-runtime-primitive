# 05: A2A Protocol Implementation Roadmap & Specification

> **Status:** Active Roadmap & Implementation Specification  
> **Target Package:** `urp.a2a` & `urp.web`  
> **Protocol Reference:** Agent2Agent (A2A) Open Protocol Specification  
> **Underlying Execution Engine:** Unified Runtime Primitive (`urp.core`)

---

## 1. Executive Summary & Objective

This document defines the formal, phased engineering plan to integrate the **Agent2Agent (A2A)** protocol as an interoperable wire and interaction standard for **URP (Unified Runtime Primitive)**.

### Architectural Decoupling Invariant
* **URP Core (`urp.core`):** Pure execution ABI and agent lifecycle FSM (`AbstractURPAgent`, `AgentContext`, `MessageEnvelope`, `ProcessResult`). URP does not know about HTTP, SSE, JSON-RPC, or A2A wire schemas.
* **A2A Adapter (`urp.a2a`):** Protocol translation layer that maps A2A endpoints, tasks, messages, events, and agent cards directly onto URP primitives.
* **Hosting Framework (`URP-HF` / `urp.web`):** Exposes discovery (`/.well-known/agent.json`), A2A REST/SSE task endpoints, and web administration.

```
                      External A2A Ecosystem
               (A2A Clients, Orchestrators, Peer Agents)
                                 │
                                 ▼ [A2A Wire: HTTP / SSE / JSON-RPC]
┌─────────────────────────────────────────────────────────────────────────┐
│                        URP Independent Host (URP-HF)                    │
│                                                                         │
│  ┌───────────────────────────────────────────────────────────────────┐  │
│  │                    A2A Protocol Adapter Layer                     │  │
│  │  - /.well-known/agent.json   (Agent Card Discovery)               │  │
│  │  - POST /tasks, GET /tasks   (A2A Task Management)                │  │
│  │  - GET /tasks/{id}/events    (SSE Streaming: Status/Artifacts)    │  │
│  │  - Envelope Translation      (A2A Part/Message <-> URP Envelope)  │  │
│  └─────────────────────────────────┬─────────────────────────────────┘  │
│                                    │ send() / emit()                    │
│                                    ▼                                    │
│  ┌───────────────────────────────────────────────────────────────────┐  │
│  │                       URP Core ABI & Host                         │  │
│  │  - URPHost / AgentHandle                                          │  │
│  │  - AgentRegistry                                                  │  │
│  │  - Strict Lifecycle FSM: WAITING <-> PROCESSING                   │  │
│  └─────────────────────────────────┬─────────────────────────────────┘  │
│                                    │ process()                          │
│                                    ▼                                    │
│  ┌───────────────────────────────────────────────────────────────────┐  │
│  │                  Agent Harnesses & Standalone Agents              │  │
│  │  - PiURPAgent (Pi Engine via JSON-RPC)                            │  │
│  │  - SDKURPAgent (OpenHands SDK)                                    │  │
│  │  - EchoAgent (Deterministic Reference)                            │  │
│  └───────────────────────────────────────────────────────────────────┘  │
└─────────────────────────────────────────────────────────────────────────┘
```

---

## 2. Overall Progress Assessment

| Phase | Milestone | Status | Key Deliverables |
|---|---|---|---|
| **Phase 1** | Architectural Origins & Analysis | **Completed (100%)** | `01_vhl_system_and_urp_origins.md` (VHL GATE, Supervisor, AOSM analysis) |
| **Phase 2** | A2A Feasibility & Agency Decoupling | **Completed (100%)** | `02_a2a_feasibility_and_runtime_agency.md` (Protocol vs. Execution separation) |
| **Phase 3** | URP Core Data Model Alignment | **Completed (100%)** | `03_native_data_structures_and_a2a_alignment.md`, `urp.core.data_types` (`context_id`, `task_id`, `to_agent_card()`, flat `ProcessResult`) |
| **Phase 4** | Subsystem Refactoring & Migration Guide | **Completed (100%)** | `04_vhl_agents_migration_guide.md`, modular `urp/` hierarchy, config loader, Pi agent harness |
| **Phase 5** | A2A Protocol Adapter Specification | **Active / Current** | `05_a2a_implementation_roadmap.md` (This document) |
| **Phase 6** | `urp.a2a` Adapter & WebHMI Migration | **Pending** | Translation layer: A2A schemas, Agent Card discovery, Task SSE streamer, and WebHMI migration to native A2A client |
| **Phase 7** | Inter-Agent Communication & Peer Dialing | **Pending** | URP-to-A2A client connector (allowing URP agents to call remote A2A agents) |

---

## 3. Phased Implementation Breakdown

### Phase 5A: A2A Data Models & Wire Schema Definition
**Goal:** Create a lightweight, high-fidelity Pydantic v2 schema module representing the A2A specification without bringing in bulky external dependencies.

* **Target Module:** `urp/a2a/models.py`
* **Artifacts to Implement:**
  1. **Agent Card Schema (`AgentCard`):**
     - Matches Google/Linux Foundation A2A specification: `name`, `description`, `version`, `protocol_version`, `endpoints`, `capabilities`, `skills`, `input_modes`, `output_modes`.
  2. **Message & Part Types:**
     - `TextPart`, `FilePart`, `DataPart`.
     - `A2AMessage`: `role` (`user` / `assistant` / `system`), `parts`, `context_id`, `task_id`, `metadata`.
  3. **Task & State Types:**
     - `A2ATask`: `task_id`, `context_id`, `status` (`submitted`, `working`, `completed`, `failed`, `canceled`), `artifacts`, `history`.
  4. **Streaming Event Schemas (SSE):**
     - `TaskStatusUpdateEvent`: updates to task status.
     - `TaskArtifactUpdateEvent`: progressive artifact generation.
     - `TaskLogUpdateEvent`: intermediate progress and tool execution notifications.

---

### Phase 5B: Bidirectional Protocol Translation Layer
**Goal:** Provide zero-loss, deterministic conversion between A2A types and URP core envelopes.

* **Target Module:** `urp/a2a/translator.py`
* **Translation Specifications:**
  1. **Inbound (A2A $\rightarrow$ URP):**
     - Convert `A2AMessage` / task submission into `MessageEnvelope`:
       - `envelope.context_id` $\leftarrow$ `a2a_task.context_id`
       - `envelope.task_id` $\leftarrow$ `a2a_task.task_id`
       - `envelope.type` $\leftarrow$ `"A2A_MESSAGE"` (or specific capability action)
       - `envelope.payload` $\leftarrow$ `{ "text": extracted_text, "parts": parts, "metadata": metadata }`
  2. **Outbound (URP $\rightarrow$ A2A SSE / Response):**
     - Convert `MessageEnvelope` emitted by URP into A2A events:
       - `AGENT_TOOL_START` / `AGENT_TOOL_END` $\rightarrow$ `TaskLogUpdateEvent` (with tool metadata)
       - `AGENT_PROGRESS_UPDATE` $\rightarrow$ `TaskLogUpdateEvent`
       - `TASK_COMPLETED` $\rightarrow$ `TaskStatusUpdateEvent(status="completed")` + `TaskArtifactUpdateEvent` (populated from `ProcessResult.artifacts` and `ProcessResult.text`)
       - `TASK_FAILED` $\rightarrow$ `TaskStatusUpdateEvent(status="failed", error=...)`

---

### Phase 5C: A2A HTTP & SSE Endpoint Exposure
**Goal:** Mount standard A2A endpoints onto the `URP-HF` FastAPI server (`urp/web/app.py`).

* **Target Module:** `urp/a2a/router.py` (mounted under `/a2a/v1` or root)
* **Endpoints:**
  1. **`GET /.well-known/agent.json`:**
     - Returns the active agent's `AgentCard` computed dynamically via `agent_descriptor.to_agent_card(base_url)`.
     - Supports multi-agent catalog at `GET /a2a/agents` returning a list of all cards registered in `AgentRegistry`.
  2. **`POST /tasks`:**
     - Initiates a new task. Allocates `task_id`, creates `MessageEnvelope`, dispatches into `URPHost` mailbox.
     - Returns HTTP 201 with `A2ATask` in `submitted` state.
  3. **`GET /tasks/{task_id}`:**
     - Returns current snapshot of task status and generated artifacts.
  4. **`GET /tasks/{task_id}/events`:**
     - Server-Sent Events (SSE) stream yielding real-time A2A events until `completed` or `failed`.
  5. **`POST /tasks/{task_id}/cancel`:**
     - Sends termination/cancellation envelope to agent.

---

### Phase 5D: WebHMI Migration to A2A Client (The First A2A Consumer)
**Goal:** Transform the browser front-end (`URP-HF WebHMI` in `urp/web/templates/index.html`) from bespoke endpoints (`/agent/message`, `/ws`) into our **primary reference A2A Client**.

* **Why WebHMI First?**
  - Our front-end is currently coupled to host-internal REST routes (`/agent/init`, `/agent/message`) and raw WebSocket event envelopes.
  - Making the WebHMI communicate exclusively through standard A2A endpoints proves the specification, provides immediate dogfooding, and ensures that an external A2A client (such as Google A2A tooling or another agent) has the exact same capabilities as the human user interface.
* **Front-End Refactoring:**
  1. **Agent Discovery:** The WebHMI fetches `/.well-known/agent.json` or `/a2a/agents` to populate the agent selection dropdown, render skills/capabilities, and inspect supported input modes.
  2. **Task Submission (`POST /tasks`):** Instead of posting to `/agent/message`, the WebHMI dispatches a standard A2A task with `A2AMessage` parts (text, attachments).
  3. **Event Streaming (`EventSource` / SSE):** Instead of a custom WebSocket, the WebHMI attaches a standard browser `EventSource` to `GET /tasks/{task_id}/events` to stream status updates, tool execution cards (`TaskLogUpdateEvent`), and artifact generation (`TaskArtifactUpdateEvent`) until task completion.
  4. **Artifact Display:** Render downloadable links to files generated in the workspace using A2A artifact URIs.

---

### Phase 5E: File & Artifact Sharing Integration
**Goal:** Seamless workspace artifact delivery complying with A2A file exchange semantics.

* **Target Module:** `urp/a2a/artifacts.py`
* **Capabilities:**
  - Files created by coding agents (such as `PiGeminiAgent` running `write` or `edit`) in `workspace_path` are automatically registered as A2A artifacts.
  - Generates signed/relative download endpoints: `GET /artifacts/{task_id}/{filename}`.
  - Maps artifact MIME types and checksums into `A2ATask.artifacts`.

---

### Phase 5F: URP Outbound A2A Client (Inter-Agent Calling)
**Goal:** Allow an agent hosted inside URP to dial out to another A2A agent (whether local or remote across the network).

* **Target Module:** `urp/a2a/client.py`
* **Capabilities:**
  - `A2AClient`: Discovers remote agent via its `/.well-known/agent.json`.
  - Sends tasks, awaits outcome, or streams SSE events.
  - Can be registered as an agent tool or capability, enabling multi-agent choreographies (e.g., Planner agent dispatching tasks to Pi Coder agent via pure A2A).

---

## 4. Immediate Action Plan (Sprint Breakdown)

| Step | Scope | Target Files | Verification Metric |
|---|---|---|---|
| **Step 1** | Implement `urp.a2a.models` (Pydantic v2 A2A schemas) | `urp/a2a/models.py`, `urp/a2a/__init__.py` | Unit tests validate serialization against standard A2A JSON schemas |
| **Step 2** | Implement `urp.a2a.translator` (URP $\rightleftharpoons$ A2A conversion) | `urp/a2a/translator.py` | Unit tests verify envelope round-trips and event mapping |
| **Step 3** | Implement FastAPI router (`/.well-known/agent.json`, `/tasks`, `/tasks/{id}/events`) | `urp/a2a/router.py`, `urp/web/app.py` | `TestClient` tests for task creation, polling, and SSE streaming |
| **Step 4** | Refactor WebHMI as reference A2A Client | `urp/web/templates/index.html` | Front-end dispatches tasks via `POST /tasks` and consumes SSE event stream via `EventSource` |
| **Step 5** | End-to-end integration test with `PiGeminiAgent` | `tests/test_a2a_integration.py` | Submit task via A2A REST API, stream SSE events, assert completed task and output artifacts |
| **Step 6** | Merge to `master` and update `.agents/` documentation | `AGENTS.md`, `README.md`, `.agents/` | Complete documentation alignment |

---

## 5. Architectural Alignment Check

* **Zero Leaks into `urp.core`:** All A2A logic stays in `urp/a2a/` and `urp/web/`. `urp/core/` remains a pure, decoupled execution ABI.
* **Backward Compatibility:** Existing web console (`/agent/message`, `/ws`) continues functioning side-by-side with the new `/a2a/v1/` endpoints.
* **Test Coverage:** Every A2A endpoint will have deterministic integration test fixtures mimicking remote client calls.
