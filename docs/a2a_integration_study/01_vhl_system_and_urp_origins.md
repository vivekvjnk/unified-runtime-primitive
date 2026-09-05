# 01 — URP Origins & VHL-System Architectural Analysis

> **Study Series:** A2A Protocol Integration & URP Feasibility Study  
> **Topic:** Analysis of VHL-System (`vhl_common.gate`, `vhl_common.supervisor`) and URP Contract Origins  
> **Status:** Completed Phase 1 Exploration

---

## 1. Executive Context & Objective

As part of the roadmap to integrate the **Agent2Agent (A2A)** protocol as a first-class communication and interaction layer above **URP (Unified Runtime Primitive)**, this document captures the foundational architectural analysis of how URP originated and currently integrates within the **VHL-System** agent ecosystem.

Understanding the existing interactions between the **Global Asynchronous Transport Engine (GATE)**, the **Supervisor control plane**, and **URP Agents** provides the design constraints, invariants, and abstraction boundaries needed to build a coherent A2A protocol adapter.

---

## 2. High-Level System Architecture

In `VHL-System`, multi-agent workflows (such as **Archy** for SCUD generation, **Librarian** for component selection, and **ANA** for schematic & netlist synthesis) operate across three decoupled architectural tiers:

```
┌────────────────────────────────────────────────────────────────────────────────────────┐
│                        SUPERVISORY CONTROL PLANE (Supervisor)                          │
│  - Multi-Controller Arbitration (Workflow1Controller, DefaultController)               │
│  - Priority-based Claims: claim(controller_id, agent_id) / release(...)                │
│  - Continuous Outcome Routing & Acknowledgment: process_outcomes()                     │
└───────────────────────────────────────────┬────────────────────────────────────────────┘
                                            │
┌───────────────────────────────────────────▼────────────────────────────────────────────┐
│                    COMMUNICATION FABRIC: GATE (vhl_common.gate)                        │
│  - Global Asynchronous Transport Engine (stateless, capability-routed)                 │
│  - Endpoint Route Registry: routes[destination] -> enqueue_fn                          │
│  - Human-in-the-Loop Terminal: HILTerminal (TCP socket server on port 1085)           │
└───────────────────────────────────────────┬────────────────────────────────────────────┘
                                            │ MessageEnvelope
════════════════════════════════════════════╪════════════════════════════════════════════ <--- URP BOUNDARY
                                            │ agent.send() / agent.emit()
┌───────────────────────────────────────────▼────────────────────────────────────────────┐
│                             URP AGENT PRIMITIVE (urp-core)                             │
│  - Strict Lifecycle FSM: UNINITIALIZED -> INITIALIZED -> WAITING <-> PROCESSING        │
│  - Precondition Verification (_check_preconditions) & Gate Enforcement                 │
│  - Autonomous Tool / Reasoning Loop Execution (process -> ProcessResult)               │
│  - Postcondition Verification (_check_postconditions) & Categorical Classification     │
│  - Outcome Acknowledgment Handshake (outcome_acknowledged = False)                     │
└────────────────────────────────────────────────────────────────────────────────────────┘
```

---

## 3. Subsystem Breakdown & Implementation Mechanics

### 3.1 GATE (Global Asynchronous Transport Engine) — `vhl_common.gate`

`GATE` serves as the dumb, stateless, asynchronous transport layer:

1. **Stateless Delivery:** It does not inspect payloads, maintain thread history, or block execution. It simply maps a string endpoint name (`message.receiver`) to a registered async callable (`routes[name]`).
2. **Context Isolation (`GateRegistry`):** Lazily provisions a dedicated `Gate` instance per `context_id` (e.g., project workflow context) ensuring multi-tenant isolation.
3. **Transparent Ingress & Egress Binding:**
   - **Ingress:** `gate.register(agent_id, lambda msg: supervisor.send(agent_id, msg))`
   - **Egress:** `agent.set_callback(lambda msg: supervisor.route_egress(msg) -> gate.send(msg))`
4. **Human-In-The-Loop (`HILTerminal`):**
   - Connects human operators over an asynchronous TCP socket server (default port `1085` or via `nc`/`telnet`).
   - Registers as an endpoint `"HIL"` on the GATE.
   - Any agent emitting envelopes to receiver `"HIL"` formats and streams output to active TCP clients.
   - User inputs formatted as `<receiver>: <message>` are wrapped in `HUMAN_RESPONSE` envelopes and injected directly back into GATE routing.

### 3.2 Supervisor (Persistent Control Plane) — `vhl_common.supervisor`

The `Supervisor` acts as the authoritative control and arbitration plane for active URP agents:

1. **Multi-Controller Governance & Claims:**
   - Controllers subclass `AbstractController` (e.g., `Workflow1Controller`, `DefaultController`).
   - Schedulers acquire authority by asserting claims: `await supervisor.claim(controller_id, agent_id)`.
   - Claims are arbitrated deterministically by priority (`ControlClaim.priority`). If a higher-priority controller arrives, the previous controller is notified via `on_released(agent_id)` and the winning controller receives `on_acquired(agent_id)`.
   - Unclaimed agents default to `DefaultController` (priority 0).
2. **Continuous Outcome Monitoring & Routing Loop:**
   - The Supervisor runs a background loop (`_run_monitoring_loop()`, polling every 0.1s).
   - In `process_outcomes()`, it inspects all registered agents.
   - When `last_process_result.outcome != NONE` and `not outcome_acknowledged`, it schedules:
     ```python
     await active_controller.handle_outcome(agent_id, last_process_result)
     supervisor.acknowledge_outcome(agent_id) # resets outcome_acknowledged = True on agent
     ```

### 3.3 Workflow Controllers (e.g., `Workflow1Controller`)

Workflow controllers drive sequential and DAG-based multi-agent execution:
* Claims an agent (e.g., `archy_agent_id = f"{module_name}.archy"`).
* Dispatches task envelopes through `supervisor.send(agent_id, message)`.
* Awaits completion via internal outcome queues (`wait_for_outcome(agent_id)`).
* Inspects `ProcessResult` and handles branching, retries, and artifact handoffs to downstream agents (e.g., Archy $\rightarrow$ Librarian $\rightarrow$ ANA-D).

---

## 4. Why URP is Defined This Way: The Core Invariants

The design constraints of URP directly reflect the operational requirements of the VHL multi-agent platform:

| URP Invariant / Primitive | Architectural Rationale in VHL-System |
|---|---|
| **Mailbox-Driven Invocation (`send`)** | Decouples caller execution from agent execution. Supervisors and controllers submit work non-blockingly without holding synchronous RPC threads or mutating agent state directly. |
| **Precondition Gates (`_check_preconditions`)** | Safeguards expensive hardware synthesis and LLM loops. Before burning tokens or writing to workspaces, the agent validates input artifacts (e.g., SCUD existence, pinout specs). If invalid, it emits `TASK_PRECONDITIONS_VIOLATED` and avoids entering `PROCESSING`. |
| **Postcondition Gates (`_check_postconditions`)** | Enforces invariant assertions on generated outputs (e.g., schematic syntax validity, non-empty artifacts) before marking the task `COMPLETED`. |
| **Structured `FailureCategory`** | Allows workflow controllers to make domain-specific recovery decisions: `PRECONDITION_FAILURE` triggers asset regeneration; `VALIDATION_FAILURE` triggers retry loops up to `MAX_VALIDATION_FAILURES`; `INFRASTRUCTURE_FAILURE` halts execution. |
| **Outcome Acknowledgment Handshake (`outcome_acknowledged`)** | In multi-agent pipelines, prevents fast producers from flooding an agent mailbox before the supervisor and governing controller have inspected the previous result, verified outputs, and coordinated handoffs. |
| **Decoupled Identity (`AgentKey`) & Handles (`AgentHandle`)** | Allows controllers to identify agents semantically (`agent_type:module_name`) and query `AgentReadiness` without leaking internal execution details or violating encapsulation. |

---

## 5. Architectural Implications for A2A Protocol Integration

Integrating the **Agent2Agent (A2A)** protocol as a first-class communication layer above URP reveals key architectural alignments:

1. **A2A as a Protocol Layer Above the URP Boundary:**
   - A2A schemas (`Message`, `Task`, `Artifact`, `TaskStatusUpdate`) operate above the URP boundary.
   - An incoming A2A `Task` or `Message` translates directly into an inbound URP `MessageEnvelope` entering the agent's mailbox.
2. **Outcome Acknowledgment & A2A Task State Alignment:**
   - URP's `LastTaskOutcome` (`TASK_COMPLETED`, `TASK_FAILED`, `WAITING_FOR_USER_INPUT`) and `FailureCategory` map directly to A2A task state updates (`COMPLETED`, `FAILED`, `INPUT_REQUIRED`).
   - The outcome acknowledgment handshake provides the natural synchronization point for A2A response streaming and artifact publication.
3. **Gateway / Broker Integration:**
   - The stateless routing nature of `GATE` and the controller arbitration of `Supervisor` can naturally bridge to A2A transport endpoints (HTTP/REST, Server-Sent Events, WebSockets, or gRPC).
4. **Autonomous Agency Preservation:**
   - External A2A callers should not dictate internal execution sub-steps; the URP agent autonomously determines whether to answer immediately or delegate to internal sub-agent tools, emitting A2A protocol events as side-effects of execution.

---

## 6. Next Steps

* **Phase 2:** Deep exploration of related MAS topologies, protocol message schemas, and state representations in subsequent target directories.
* **Phase 3:** Formal synthesis and design specification of the URP-A2A interaction layer and adapter specifications.
