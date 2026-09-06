# Technical Feasibility Report: Integration of `pi-delegate` Extension & A2A Protocol Task Management in URP

**Document ID:** `URP-DOC-2026-PIDEL-01`  
**Target Repository:** `urp-core` (Unified Runtime Primitive)  
**Analyzed Extension:** `pi-delegate` (`~/.pi/agent/git/github.com/bermudi/pi-delegate`)  
**Status:** Complete Feasibility & Architecture Specification  
**Date:** March 2026  

---

## Executive Summary

This feasibility report analyzes the **`pi-delegate`** extension for the Pi coding agent harness (`@earendil-works/pi-coding-agent`), focusing on its internal architecture, context management, session persistence, inter-agent communication, event streaming, and its feasibility as an execution substrate for the **Agent2Agent (A2A) Protocol Task Lifecycle**.

Our analysis concludes that **`pi-delegate` is highly feasible and architectural aligned for implementing A2A Task functionality**. Its asynchronous ticket subsystem (`AsyncTicket`), session pooling (`SessionPool`), progress callback pipeline (`onProgress` / `onUpdate`), and workspace isolation modes map cleanly to the A2A v1.0 task model, state machine (`TaskState`), artifact generation (`Artifact`), and SSE event streaming interfaces (`TaskStatusUpdateEvent`, `TaskArtifactUpdateEvent`).

---

## 1. System Orientation & `pi-delegate` Architecture

`pi-delegate` is a standalone Pi extension that exposes a unified tool named `delegate`. It allows a parent host agent (or external supervisor) to spawn, execute, manage, and coordinate subagent runs concurrently or asynchronously.

```
+-----------------------------------------------------------------------------------+
|                                Host Agent (Pi)                                    |
+-----------------------------------------------------------------------------------+
                                         |
                                `delegate()` tool
                                         |
    +------------------------------------+------------------------------------+
    | Synchronous Dispatch                                                    | Asynchronous Dispatch
    v                                                                         v
+------------------------+                                        +------------------------+
| Block Host Execution   |                                        | Return AsyncTicket ID  |
| Await Task Settlement  |                                        | Background Event Loop  |
+------------------------+                                        +------------------------+
    |                                                                         |
    v                                                                         v
+-----------------------------------------------------------------------------------+
|                              Subagent Execution Loop                              |
|   - noExtensions: true (Headless isolation)                                      |
|   - Workspace Isolation: shared | scratch (CoW) | isolated (Git worktree)          |
|   - Dedicated Session File: ~/.pi/agent/delegate-sessions/*.jsonl                 |
+-----------------------------------------------------------------------------------+
                                         |
                                         v
                     +---------------------------------------+
                     |  Host Notification / Delivery Channel |
                     |  - Tool Result (Sync)                 |
                     |  - sendMessage(deliverAs) (Async)    |
                     +---------------------------------------+
```

### Key Behavioral Invariants
1. **Headless Extension Isolation**: Subagents run with `noExtensions: true` by default. They do not inherit the parent session's interactive extension inventory or UI hooks, preventing cross-session pollution.
2. **Shared-Write Safety Gate**: Before spawning tasks, `dispatch.ts` inspects mutating tools and Git directory scopes. Any overlapping mutating tasks targeting the same repository tree within a batch (or against running async tickets) are rejected before execution begins.
3. **Agent Profile Discovery**: Profiles are discovered from `.pi/agents/*.md`, `~/.pi/agent/agents/*.md`, `.claude/agents/*.md`, and built-in profiles (`default`, `scout`, `coder`, `reviewer`). First definition wins.

---

## 2. Context Management Deep Dive

`pi-delegate` provides four distinct layers for context isolation, inheritance, and persistence:

```
                      +----------------------------------+
                      |       Subagent Invocation        |
                      +----------------------------------+
                                       |
                   +-------------------+-------------------+
                   |                                       |
          context: "fresh"                      context: "with-parent-transcript"
                   |                                       |
        [Clean Conversation]                     [Extract Parent Messages]
                   |                                       |
                   |                             Prepend <parent-session> XML
                   +-------------------+-------------------+
                                       |
                         [ResourceLoader Discovery]
                         Scans task cwd for AGENTS.md & SKILL.md
                                       |
                   +-------------------+-------------------+
                   |                                       |
            One-shot Task                           sessionId Provided
                   |                                       |
        [Fresh / Resumed .jsonl]                   [SessionPool Lookup]
                                                   - Verify Frozen Config
                                                   - Multi-turn Context Continuity
```

### 2.1 Context Transfer Options
* **`context: "fresh"` (Default)**: The subagent begins with an empty chat transcript. It cannot view previous host agent messages.
* **`context: "with-parent-transcript"`**: `parent-context.ts` uses Pi's `buildSessionContext()` to extract text blocks from all user and assistant messages up to the current session leaf. It wraps this conversation in `<parent-session>...</parent-session>` XML blocks and prepends it to the subagent's `prompt`.
* **Resource Discovery (Always Active)**: Regardless of `context` setting, Pi's `ResourceLoader` scans the task's working directory (`cwd`) for project instructions (`AGENTS.md`) and skill definitions (`SKILL.md`) and appends them to the subagent system prompt.

### 2.2 Multi-Turn & Resumed Contexts
* **Pooled Sessions (`sessionId`)**: Managed by `SessionPool` (`pool.ts`). When a `sessionId` is passed, the live `AgentSession` is retained in memory. Subsequent calls with the same `sessionId` continue the conversation, preserving past turns. The pool enforces a **frozen config invariant**: `{ cwd, thinking, tools, systemPrompt, model }` must match initial creation.
* **Resumed Sessions (`resumeFrom`)**: Passing an absolute path to a prior subagent `.jsonl` session file rehydrates the full message history and picks up execution from that checkpoint.

---

## 3. Session Invocation & JSONL Persistence Mechanics

### 3.1 Does `delegate` invoke a new Pi session?
**Yes.** Every subagent task instantiation calls Pi's SDK `createAgentSession()` inside `lifecycle.ts`. Each session maintains its own `AgentSession` object, execution loop, model runtime, and resource loader.

### 3.2 Does the newly invoked session have a dedicated `.jsonl` file?

The persistence behavior depends on the specified `workspace` mode:

| Workspace Mode | `.jsonl` Disk Persistence | Details & Rationale |
| :--- | :--- | :--- |
| **`workspace: "shared"`** | **Dedicated File Created** | Persisted to `~/.pi/agent/delegate-sessions/<timestamp>_<uuid>.jsonl` via `SessionManager.create()` (`sessions.ts`). Isolated from the parent host's session tree. |
| **`workspace: "scratch"`** | **In-Memory Only** | Uses `SessionManager.inMemory(task.cwd)`. Throwaway Copy-on-Write (CoW) workspaces must not leave resumable traces on disk that could lead to dirty state rehydration later. |
| **`workspace: "isolated"`** | **In-Memory Only** | Uses `SessionManager.inMemory(task.cwd)`. Execution runs in a detached Git worktree; proposal patches are reconciled, but subagent transcripts remain strictly in-memory. |
| **Pooled (`sessionId`)** | **Dedicated File Updated** | The pooled session continuously appends to its assigned `.jsonl` file in `~/.pi/agent/delegate-sessions/` throughout its multi-turn lifecycle. |

---

## 4. Inter-Agent Communication Channels

### 4.1 Host Agent $\rightarrow$ Delegated Agent
Communication is established when the Host Agent executes the `delegate` tool with structured arguments (`prompt`, `agent`, `cwd`, `tools`, `workspace`, etc.).

### 4.2 Delegated Agent $\rightarrow$ Host Agent

```
Synchronous Mode (async: false):
  Subagent Execution ---> TaskResult Output ---> Tool Call Result ---> Host Model Context

Asynchronous Mode (async: true):
  Subagent Execution ---> AsyncTicket Settled ---> sendMessage(deliverAs) ---> Parent Session Turn
```

1. **Synchronous Mode (`async: false`)**:
   * `dispatchSync()` blocks the host agent turn until all tasks settle or hit timeout/stall bounds.
   * Collects outputs, token/cost usage, touched files (`touchedFiles`), directly edited files (`attributedFiles`), and failure categories.
   * Formats and returns a single `DelegateToolResult` frame directly to the host agent context.

2. **Asynchronous Mode (`async: true`)**:
   * Returns an `AsyncTicket` object immediately (`{ ticket: "t1234v56", status: "running" }`).
   * Subagent workers execute asynchronously in the background.
   * When all tasks in a ticket complete, `deliverTicketResults()` (`tickets.ts`) calls `pi.sendMessage()` with `deliverAs: "steer"` and `triggerTurn: true`. This injects a custom message (`async_delegate_result`) into the parent host session, waking the host agent with subagent results.
   * **Leaf Affinity Safeguard (`leaf.ts`)**: If the parent session moved to a different `/tree` leaf during background execution, delivery automatically downgrades to `deliverAs: "nextTurn"` (no forced turn trigger) plus a UI notification, protecting unrelated session branches from context pollution.

---

## 5. Event Streaming Capabilities

### 5.1 Real-Time User & TUI Streaming
`pi-delegate` provides real-time progress events to the user/UI layer:
* **Tool Update Frames**: `execute()` receives an `onUpdate` callback from Pi. During execution, `runner.ts` catches `AgentProgressUpdate` events (tool calls, total tokens, activity descriptions, duration) and passes them to `onUpdate()`, streaming progress frames (`Running N subagents...`, tool counts, active phase) to the TUI/web console.
* **Footer Status**: `status.ts` maintains live background subagent indicators in the Pi UI footer (e.g., `⏳ 2 subagents · t5042v19`).

### 5.2 Model-Level Context Event Processing
* **Mid-Call Constraints**: Standard LLM tool execution protocols (OpenAI, Anthropic) treat tool calls as atomic request-response steps. The LLM model context cannot receive token-by-token streaming mid-tool-execution.
* **State Inspection via Ticket Polling**: In `async` mode, the host LLM model can inspect intermediate worker progress via dedicated ticket actions:
  * `delegate({ ticketAction: "poll", ticket: "t1234v56" })`: Returns current status, tool counts, duration, and activity trace.
  * `delegate({ ticketAction: "wait", ticket: "t1234v56", timeoutMs: 5000 })`: Blocks up to `timeoutMs` to await settlement or return updated progress snapshots.

---

## 6. Feasibility Analysis: Implementing A2A Protocol Tasks via `delegate`

The Agent2Agent (A2A) Protocol (implemented in `urp/a2a/`) defines a standardized lifecycle for asynchronous agent tasks (`Task`, `TaskState`, `TaskStatus`, `Artifact`, SSE streaming). 

`pi-delegate` provides an ideal execution engine for backing A2A Protocol endpoints.

### 6.1 Protocol Mapping Specification

| A2A Protocol Construct (`urp/a2a/models.py`) | `pi-delegate` Construct (`schema.ts` / `tickets.ts`) | Architectural Mapping Mechanics |
| :--- | :--- | :--- |
| **Task Submission** (`POST /tasks`) | `delegate({ async: true, tasks: [{ prompt, cwd, tools }] })` | Spawns an `AsyncTicket`. The generated ticket ID (`t1234v56`) serves as A2A `taskId`. |
| **Task State** (`TaskState`) | `ticket.status` & `progress.status` | • `TASK_STATE_SUBMITTED` $\rightarrow$ Ticket queued<br>• `TASK_STATE_WORKING` $\rightarrow$ `status: "running"`<br>• `TASK_STATE_COMPLETED` $\rightarrow$ `status: "done"`<br>• `TASK_STATE_FAILED` $\rightarrow$ `status: "error"` / `stalled`<br>• `TASK_STATE_CANCELED` $\rightarrow$ `status: "cancelled"` |
| **Task Status & Progress** (`GET /tasks/{id}`) | `delegate({ ticketAction: "poll", ticket: taskId })` | Maps `ticket.progress` (tool uses, tokens, duration, activities) to A2A `TaskStatus.statusMessage` and progress details. |
| **Task Cancellation** (`POST /tasks/{id}/cancel`) | `delegate({ ticketAction: "cancel", ticket: taskId })` | Invokes `AgentSession.abort()`, smoothly unwinds subagents, and transitions A2A state to `TASK_STATE_CANCELED`. |
| **Task Wait / Sync** | `delegate({ ticketAction: "wait", ticket: taskId, timeoutMs })` | Awaits task settlement within HTTP request deadlines. |
| **Artifacts** (`Artifact`) | `TaskResult.output`, `attributedFiles`, `sessionFile` | Mapped to A2A `Artifact` objects (text output parts, generated/edited file paths, session `.jsonl` transcript pointers). |
| **SSE Event Streaming** (`/tasks/{id}:stream`) | `onProgress` / `onStatusChange` hooks in `tickets.ts` | Listens to subagent progress events and broadcasts `TaskStatusUpdateEvent` and `TaskArtifactUpdateEvent` over SSE. |

### 6.2 Proposed URP Integration Architecture

To leverage `pi-delegate` as the execution backend for A2A tasks in `urp-core`:

```
+-----------------------------------------------------------------------------------+
|                                 A2A REST / SSE Router                             |
|                           (urp/a2a/router.py & router SSE)                        |
+-----------------------------------------------------------------------------------+
                                         |
                                         v
+-----------------------------------------------------------------------------------+
|                                URP Task Manager                                   |
|                             (urp/a2a/task_manager.py)                            |
+-----------------------------------------------------------------------------------+
                                         |
                                  JSON-RPC / Harness
                                         v
+-----------------------------------------------------------------------------------+
|                                 PiURPAgent Harness                                |
|                           (urp/harnesses/pi/pi_urp_agent.py)                      |
+-----------------------------------------------------------------------------------+
                                         |
                                 execute("delegate")
                                         v
+-----------------------------------------------------------------------------------+
|                                 pi-delegate Engine                                |
|  - Manages AsyncTickets, SessionPool, Workspaces, and .jsonl Session Files        |
+-----------------------------------------------------------------------------------+
```

---

## 7. Security, Risk Assessment & Guardrails

1. **Isolation vs. Confinement**: `workspace: "scratch"` and `workspace: "isolated"` protect the primary Git repository from relative writes, but they do **not** provide a sandboxed security boundary. Unrestricted subagent commands or absolute-path file operations can still affect the host filesystem.
2. **Shared-Write Collision Risk**: When multiple subagents run concurrently with `workspace: "shared"`, simultaneous file edits can cause race conditions. `pi-delegate` mitigates this via its static pre-dispatch overlap check.
3. **Stall Watchdog**: Subagents that hang on network calls or external processes are detected via `stallTimeoutMs` (inactivity watchdog) and cooperatively aborted via `AgentSession.abort()`.

---

## 8. Conclusion & Recommendations

1. **Feasibility Verdict**: **Highly Feasible**. `pi-delegate` provides all core primitives required to back A2A tasks: async execution, ticket tracking, state polling, cooperative cancellation, session pooling, and progress events.
2. **Implementation Action Plan**:
   * **Step 1**: Implement an adapter in `urp/harnesses/pi/` that maps A2A task creation requests into `delegate({ async: true, ... })` calls over JSON-RPC.
   * **Step 2**: Wire `urp/a2a/task_manager.py` to store `ticketId` as `taskId` and poll/wait via `delegate(ticketAction)`.
   * **Step 3**: Connect `runner.ts` / `tickets.ts` progress events to URP's A2A SSE stream publisher (`TaskStatusUpdateEvent`).
