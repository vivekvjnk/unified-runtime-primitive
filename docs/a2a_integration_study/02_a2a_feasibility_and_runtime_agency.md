# 02 — A2A Feasibility Study & Runtime Agency Integration

> **Study Series:** A2A Protocol Integration & URP Feasibility Study  
> **Source Material:** `crazy_orca/` feasibility study, `a2a_resources/`, and `bell_corridor.md` (Software Laboratory engineering diary)  
> **Topic:** Decoupling A2A Protocol Abstractions from URP Runtime Agency, Local Layer 3 Shared-Disk IPC, and Dynamic Generic Worker Topologies  
> **Status:** Completed Phase 2 Exploration

---

## 1. Executive Summary & Core Discovery

A foundational insight derived from the `crazy_orca` exploration and the Software Laboratory forcing function (`bell_corridor.md`):

> **A2A describes how agents interact with the outside world; URP defines what an agent is at runtime.**

A common architectural trap in multi-agent engineering is conflating the **inter-agent wire protocol** with the **runtime agent's internal agency**:
* **Protocol-Driven View (External A2A):** The client or caller explicitly mandates whether a request is a lightweight `Message` or a long-running, stateful `Task`.
* **Agent-Driven View (URP Autonomous Authority):** The receiving URP Agent is an autonomous, stateful actor. External protocol constructs are ingested into the agent's mailbox, and the agent's internal reasoning loop (e.g., ReAct / OpenHands / Pi) autonomously determines the execution strategy—resolving simple queries inline as direct messages or spawning transient sub-agent tools that emit A2A `TaskStatusUpdateEvent` and `TaskArtifactUpdateEvent` protocol events as execution side-effects.

---

## 2. Structural Layering: Protocol Boundary vs. Runtime Agency

```text
                           A2A PROTOCOL BOUNDARY (External World)
   ┌─────────────────────────────────────────────────────────────────────────────┐
   │ Client / Initiator (Discovery: /.well-known/agent-card.json)                │
   │ Operations: SendMessage(contextId, taskId, message)                         │
   └─────────────────────────────────────┬───────────────────────────────────────┘
                                         │
 ========================================│========================================
             A2A LAYER 3 ADAPTER & URP INGRESS BOUNDARY (MessageEnvelope)
 ========================================│========================================
                                         ▼
   ┌─────────────────────────────────────────────────────────────────────────────┐
   │                        URP PRIMARY AGENT / ORCHESTRATOR                     │
   │  (Persistent State, Continuous Conversation Memory contextId, ReAct Loop)   │
   │                                                                             │
   │  Internal LLM Reasoning:                                                    │
   │  "Can I solve this directly, or should I spawn an internal worker tool?"    │
   │                                                                             │
   │          ┌───────────────────────────┴───────────────────────────┐          │
   │          ▼                                                       ▼          │
   │  [ Direct Inline Execution ]                           [ Transient Worker ] │
   │  Returns inline A2A Message                            Spawns Tool / Task   │
   │  (Fast turn / Chit-chat)                               (Copy-on-Write)      │
   │          │                                                       │          │
   │          │                                                       ▼          │
   │          │                                              [ Tool Execution ]  │
   │          │                                              Isolated Workspace  │
   │          │                                              Emits A2A Events    │
   │          │                                                       │          │
   │          └───────────────────────────┬───────────────────────────┘          │
   └──────────────────────────────────────┼──────────────────────────────────────┘
                                          │
                                          ▼
   ┌─────────────────────────────────────────────────────────────────────────────┐
   │ Published Output: A2A Events (TaskStatusUpdate / TaskArtifactUpdate / Msg)  │
   │ Storage Transit: /shared_ipc/contexts/{contextId}/tasks/{taskId}/artifacts/ │
   └─────────────────────────────────────────────────────────────────────────────┘
```

---

## 3. Four Core Dimensions: Identity, State, Workspace, and Role

From `crazy_orca/MAS.md`, a robust multi-agent architecture separates four distinct dimensions:

```text
                    AGENT
                      │
       ┌──────────────┼──────────────┬──────────────┐
       ▼              ▼              ▼              ▼
    Identity        State        Workspace         Role
    (Who am I?)   (What do I   (Where is data  (What am I doing
                   know now?)    persisted?)      right now?)
```

### 3.1 The Failure of Fixed Agent Taxonomies
In complex software and hardware laboratories, fixed agent classes (`RCAAgent`, `DebuggerAgent`, `TestAgent`, `DocumentationAgent`) break down because tasks are highly variable and dynamic.

### 3.2 Dynamic Generic Agent Model
Instead of hardcoding rigid agent classes, URP adopts **Generic Agents with Dynamic Contextual Roles**:
1. **Generic Core:** Every agent is an `AbstractURPAgent` capable of tool execution, workspace manipulation, and mailbox communication.
2. **Contextual Specialization:** When spawned by an Orchestrator, an agent is assigned a transient role:
   ```yaml
   agent_id: generic-worker-42
   current_role: "Network Protocol RCA"
   current_task: "Analyze abnormal capture on interface eth0"
   ```
3. **Clean Isolation via State vs. Workspace:**
   - **State:** Newly spawned workers receive fresh, clean state (empty conversation history) to prevent prompt cross-pollution.
   - **Workspace:** Workers share access to the project workspace and artifacts, allowing explicit knowledge transfer through files and logs rather than noisy conversation context.

---

## 4. Session Semantics: Context Continuity vs. Task Isolation

Achieving full A2A compliance while maintaining scalable URP runtime memory requires distinguishing three scope tiers:

1. **Agent Identity (`agentId` / `AgentCard`):** The static endpoint address and declared capabilities of the agent.
2. **Session Continuity (`contextId`):** The persistent, multi-turn conversational anchor. It survives across completed or failed tasks so subsequent follow-ups retain context.
3. **Task Isolation (`taskId`):** The isolated, stateful unit of work. When multiple tasks run concurrently under the same `contextId`, single-agent prompts fail due to context saturation. URP solves this via **Copy-on-Write Task Workers**:
   - **Read-Shared:** Worker tools inherit a snapshot of the primary session context.
   - **Write-Isolated:** Intermediate tool reasoning and scratchpads are scoped strictly to the worker's private sub-workspace.
   - **Reconciliation:** On task completion, final output artifacts and summaries are committed back to the session history.

---

## 5. Layer 3 Shared-Disk IPC Architecture (`/shared_ipc/`)

When agents are co-located on a single physical host or container pod, standard network serialization (HTTP/REST or gRPC) introduces unnecessary latency and serialization overhead for large artifacts (such as PCAP dumps, binary firmware images, or schematic netlists).

URP specifies a **Custom Layer 3 Shared-Disk IPC Binding** that preserves A2A Layer 1 schemas (`a2a.proto`) and Layer 2 operations (`SendMessage`, `GetTask`, `CancelTask`) while using local Unix Domain Sockets and filesystem IPC.

### 5.1 Storage Boundary Separation

Strict isolation is enforced between **Private Execution Workspaces** and the **Shared IPC Transit Zone**:

```text
/agent_workspaces/                     <-- PRIVATE AGENT EXECUTION WORKSPACES
├── orchestrator/                      <-- Opaque internal workspace for Orchestrator
└── workers/
    └── {taskId}/                      <-- Localized execution sandbox for worker tools

-----------------------------------------------------------------------------------------

/shared_ipc/                           <-- SHARED IPC TRANSIT ZONE (A2A OUTPUT PIPE)
├── control/
│   └── a2a_ipc.sock                   <-- Unix Domain Socket Control Plane
└── contexts/
    └── {contextId}/                   <-- Long-Lived Session Directory
        ├── session.meta               <-- Shared session parameters & metadata
        ├── memory.json                <-- Reconciled multi-turn conversational history
        └── tasks/
            └── {taskId}/              <-- Isolated Task Transit Directory
                ├── inputs/            <-- Immutable input Part references
                └── artifacts/         <-- Published read-only output Artifacts
```

### 5.2 The Locality Adapter & URI Translation
To prevent the "locality trap" (code breaking when deployed across distributed clusters), file references in A2A `Part` payloads use abstract URIs:
* **Wire Representation:** `a2a-file:///contexts/{contextId}/tasks/{taskId}/artifacts/report.pdf`
* **Local Co-located Node:** Layer 3 adapter resolves `a2a-file://` directly to `/shared_ipc/...` host file descriptors with zero network copy.
* **Cloud / Distributed Node:** Layer 3 adapter resolves `a2a-file://` to S3/GCS pre-signed URLs or object store paths without modifying agent reasoning loops.

---

## 6. Real-World Forcing Function: The Software Laboratory Workflow

From `bell_corridor.md`, the engineering bug-fixing workflow demonstrates why this architecture is mandatory:

```text
                         ┌──────────────────────────┐
                         │       BUG INTAKE         │
                         │ (Description & Symptoms) │
                         └────────────┬─────────────┘
                                      │
                                      ▼
              ┌─────────────────────────────────────────────────┐
              │ STAGE 1 — REPRODUCTION (Configuration + Obs.)   │
              │  - Deploys VM in KVM, attaches host bridges     │
              │  - Runs test signal injection / captures PCAP   │
              └───────────────────────┬─────────────────────────┘
                                      │ Evidence
                                      ▼
              ┌─────────────────────────────────────────────────┐
              │ STAGE 2 — ROOT CAUSE ANALYSIS (RCA)             │
              │  - Correlates PCAP evidence + codebase          │
              │  - Weak feedback loop to Stage 1 for tests      │
              │  - Produces grounded RCA hypothesis             │
              └───────────────────────┬─────────────────────────┘
                                      │ Proven RCA
                                      ▼
              ┌─────────────────────────────────────────────────┐
              │ STAGE 3 — FIX & VERIFICATION                    │
              │  - RCA explained to Expert (HIL) for approval   │
              │  - Coding agent implements fix in branch        │
              │  - Strong validation loop back to Stage 1       │
              └───────────────────────┬─────────────────────────┘
                                      │ Validated Fix
                                      ▼
              ┌─────────────────────────────────────────────────┐
              │ STAGE 4 — INTEGRATION & PULL REQUEST            │
              │  - Clean branch validation & PR generation      │
              └─────────────────────────────────────────────────┘
```

### Key Insights for URP + A2A
1. **Dual Role of Human-In-The-Loop (Expert):**
   - **Supervisor Role:** Validating stage outcomes, approving RCA before code modification, steering workflow.
   - **Worker Role:** Executing specialized manual tasks (e.g., complex engineering UI configuration) when delegated by the Orchestrator.
2. **Sub-Task Spawning:** Each stage contains multiple isolated sub-tasks that are best solved by dynamically spawning scoped worker agents with explicit task boundaries.

---

## 7. Synthesis: A2A & URP Architectural Mapping Matrix

| A2A Protocol Concept | URP Core Primitive (`urp-core`) | VHL / Host Layer Integration |
|---|---|---|
| **Agent Card (`agent-card.json`)** | `AgentDescriptor` | Advertises agent ID, capabilities, version, accepted messages, and transport endpoint. |
| **`SendMessageRequest` (`Message`)** | `MessageEnvelope` $\rightarrow$ `mailbox` | Asynchronous mailbox delivery (`send()`). |
| **`Task` Object & State Machine** | `AgentState.status` & `ProcessResult` | Managed via URP FSM (`WAITING` $\rightleftharpoons$ `PROCESSING`) and outcome mapping. |
| **`TaskStatusUpdateEvent`** | `emit(MessageEnvelope(type="TASK_STATUS_UPDATE"))` | Streamed over event queue / WebSocket / SSE. |
| **`TaskArtifactUpdateEvent`** | `emit(MessageEnvelope(type="TASK_ARTIFACT_UPDATE"))` | Artifact reference published to `/shared_ipc/...`. |
| **Terminal State Immutability** | `outcome_acknowledged` Handshake | Ensures orchestrator synchronizes state before agent accepts subsequent tasks. |
| **`contextId`** | `session_id` & Persistent Workspace Handle | Multi-turn session context surviving across terminal tasks. |
| **`taskId`** | Isolated Sub-Agent Execution Subdirectory | Copy-on-Write transient execution sandbox. |
