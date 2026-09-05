# Architecture: Registry & Handles

This document covers the decoupled registry, composite semantic identity (`AgentKey`), system readiness abstraction (`AgentReadiness`), and handle access security (`AgentHandle`) defined in `urp.agent_key` and `urp.agent_registry`.

---

## 1. Architectural Motivation

In complex multi-agent architectures (such as AOSM — Agent Orchestration State Machine):
* **"Systems decide; agents propose."** Schedulers decide *when* an agent is invoked based on overall system state.
* **No Direct Reference Leakage:** External orchestrators must not have direct references to internal agent objects or memory buffers.
* **Mailbox-Only Interaction:** Orchestrators interact with agents exclusively via mailbox dispatches and read-only inspection handles.

---

## 2. Component Structure

```
                  ┌───────────────────────────────┐
                  │           AgentKey            │
                  │  (agent_type, module_name)    │
                  └───────────────┬───────────────┘
                                  │ registers & queries
                                  ▼
┌─────────────────────────────────────────────────────────────────┐
│                          AgentRegistry                          │
│                                                                 │
│  - register(name, factory_func, descriptor)                     │
│  - add_pre_create_hook(hook) / add_post_create_hook(hook)       │
│  - create_agent(name, *args, **kwargs)                          │
└─────────────────────────────────┬───────────────────────────────┘
                                  │ wraps instance in AgentEntry
                                  ▼
┌─────────────────────────────────────────────────────────────────┐
│                           AgentHandle                           │
│                                                                 │
│  - send(message)        -> Pushes message into agent mailbox    │
│  - state                -> Safe, read-only dictionary snapshot  │
│  - readiness            -> Computed AgentReadiness enum         │
│  - status               -> Quick lifecycle status string        │
│  - mailbox_size         -> Number of queued items in mailbox    │
│  - to_dict()            -> Serializable registry snapshot       │
└─────────────────────────────────────────────────────────────────┘
```

---

## 3. Detailed Specifications

### 3.1 Composite Semantic Identity: `AgentKey`
Provides a human-meaningful semantic identity independent of internal ephemeral UUIDs:

```python
from urp.core import AgentKey

key = AgentKey(agent_type="archy", module_name="bms-monitor-module")
print(str(key))  # "archy:bms-monitor-module"
```

### 3.2 System-Level Readiness: `AgentReadiness`
Enables external schedulers to assess whether an agent can accept new workloads without peeking into private reasoning states:

* `READY`: Agent is in `WAITING` state and all external prerequisites are satisfied.
* `NOT_READY`: Agent is uninitialized, initializing, or currently busy (`PROCESSING`).
* `DEGRADED`: Agent is active but functioning under reduced capability (e.g., degraded tool connectivity).
* `TERMINATED`: Agent has terminated or shut down.

### 3.3 Safe External Wrapper: `AgentHandle`
`AgentHandle` wraps an internal `AgentEntry` and restricts the orchestrator's surface:

```python
# Delivering a message through the handle
await handle.send(MessageEnvelope(
    type="EXECUTE_CHECK",
    payload={"check_id": "voltage_matrix"},
    sender="supervisor"
))

# Inspecting read-only state
print(handle.readiness)    # AgentReadiness.READY
print(handle.status)       # "WAITING"
print(handle.mailbox_size) # 0
```

### 3.4 Factory Registry: `AgentRegistry`
Supports both global module-level registry functions and scoped `AgentRegistry` instances:

```python
from urp.core import AgentRegistry, register_agent, create_agent
from urp.core import AgentDescriptor

descriptor = AgentDescriptor(
    agent_id="vhl.echo.v1",
    name="Echo Agent",
    version="1.0",
    capabilities=["ECHO"],
    accepted_message_types=["PING"]
)

# 1. Register an agent factory
register_agent("echo_agent", lambda: EchoAgent(descriptor), descriptor)

# 2. Add lifecycle hooks
def on_agent_created(name, agent, *args, **kwargs):
    print(f"Hook: Created agent instance {name}")

# 3. Instantiate via registry
agent = create_agent("echo_agent")
```
