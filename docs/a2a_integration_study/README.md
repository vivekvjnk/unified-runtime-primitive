# A2A Protocol Integration & URP Feasibility Study

> **Objective:** Comprehensive feasibility and architectural study for integrating the **Agent2Agent (A2A)** protocol as a first-class communication and interaction layer above **URP (Unified Runtime Primitive)**.

---

## Study Documents & Exploration Roadmap

| Phase | Document | Status | Description |
|---|---|---|---|
| **Phase 1** | [`01_vhl_system_and_urp_origins.md`](01_vhl_system_and_urp_origins.md) | **Completed** | Deep exploration of `GATE`, `Supervisor`, `Controllers`, and the architectural origin of URP in `VHL-System`. |
| **Phase 2** | [`02_a2a_feasibility_and_runtime_agency.md`](02_a2a_feasibility_and_runtime_agency.md) | **Completed** | Analysis of A2A feasibility, protocol vs. runtime agency decoupling, Layer 3 shared-disk IPC, and Software Laboratory multi-stage workflows. |
| **Phase 3** | [`03_native_data_structures_and_a2a_alignment.md`](03_native_data_structures_and_a2a_alignment.md) | **Completed** | Deep review of real-world agents (Archy, ANA, Librarian) and proposed native data structure simplifications for A2A alignment. |
| **Phase 4** | [`04_vhl_agents_migration_guide.md`](04_vhl_agents_migration_guide.md) | **Completed** | Step-by-step migration recipes and diffs for upgrading Archy, ANA, and Librarian agents under VHL-System. |
| **Phase 5** | [`05_a2a_implementation_roadmap.md`](05_a2a_implementation_roadmap.md) | **Active / Current** | Phased engineering implementation roadmap and technical specification for the `urp.a2a` adapter layer. |

---

## Core Focus Areas

1. **Protocol Decoupling:** Isolating A2A wire and semantic protocol specifications from the internal execution agency of URP agents.
2. **Lifecycle & State Mapping:** Bi-directional translation between URP FSM (`AgentStatus`, `LastTaskOutcome`, `FailureCategory`) and A2A Task / Message lifecycles.
3. **Transport & Routing:** Mapping A2A endpoints and streaming protocols to URP mailboxes, `GATE` capability routing, and `URPHost` event queues.
4. **Outcome Synchronization:** Leveraging URP's outcome acknowledgment handshake for deterministic A2A artifact delivery and status transitions.
