# Unified Runtime Primitive (URP) Specification

## Purpose

The Unified Runtime Primitive (URP) is the foundational execution model for VHL agents (Python) and tiny-agent runtimes (C). It defines a minimal, language-agnostic, stateful, message-driven agent primitive that can be implemented in any high-level programming language.

Core principle:

> **Initialize once → wait → receive message → process asynchronously → emit event/response → wait again**

URP is intentionally small enough to be a runtime primitive, not a framework.

---

# 1. Design Goals

## Mandatory properties

Every URP implementation must provide:

1. **Addressable identity**

   * each agent has a globally unique runtime id

2. **Persistent state**

   * state survives across messages
   * workspace/session survives across messages

3. **Mailbox-driven invocation**

   * messages are delivered asynchronously
   * sender and receiver are decoupled

4. **Asynchronous execution**

   * invocation is non-blocking from caller perspective

5. **Event emission**

   * outputs are emitted as messages/events
   * not direct stack returns

6. **Capability declaration**

   * each agent advertises supported operations

7. **Dependency injection at initialization**

   * LLM adapters
   * tools
   * workspace
   * system prompts
   * configs

8. **Transport agnostic**

   * in-memory queue
   * IPC
   * socket
   * HTTP/WebSocket
   * all are implementation details

---

# 2. Runtime Model

```text
spawn
  ↓
initialize
  ↓
WAITING
  ↓ receive message
PROCESSING
  ↓ emit events
WAITING
  ↓ ...
TERMINATED

AGENT_ERROR (Error state)
```

Single invariant:

> Agent is always in a well-defined state.

---

# 3. Primitive Objects

## 3.1 AgentDescriptor

Static identity.

Fields:

* agent_id
* name
* version
* capabilities[]
* accepted_message_types[]
* implementation metadata

---

## 3.2 AgentContext

Initialized once.

Fields:

* configuration
* workspace handle
* tool registry
* llm adapter
* system prompt inputs
* persistent memory handle
* runtime hooks

---

## 3.3 AgentState

Mutable internal state.

Examples:

* conversation state
* current task
* cached artifacts
* internal FSM state
* session metadata

Opaque outside agent.

---

## 3.4 Mailbox

Queue abstraction.

Operations:

* send(message)
* receive()
* peek(optional)
* drain(optional)

Guarantee:

FIFO unless implementation specifies otherwise.

---

## 3.5 Message Envelope

Canonical message format.

Fields:

* message_id
* correlation_id
* sender
* receiver
* type
* payload
* metadata
* timestamp

Payload is implementation-specific.

---

## 3.6 Event Envelope

Output message.

Examples:

* TASK_ACCEPTED
* TASK_RUNNING
* TASK_PROGRESS
* TASK_COMPLETED
* TASK_FAILED
* AGENT_IDLE
* AGENT_ERROR
* CUSTOM_DOMAIN_EVENT

---

# 4. Lifecycle Contract

## initialize(context)

Runs exactly once.

Purpose:

* bind dependencies
* initialize workspace
* load prompts/config
* allocate resources

---

## start()

Makes agent runnable.

Enters WAITING state.

---

## send(message)

Asynchronous.

Places message in mailbox.

No direct execution guarantee.

---

## process(message)

Core execution primitive.

May:

* invoke LLM
* invoke tools
* mutate state
* emit events
* create sub-messages

Must not violate state invariants.

---

## emit(event)

Pushes output to runtime bus.

Receiver may be:

* AOSM
* another agent
* external protocol adapter

---

## shutdown()

Graceful termination.

Flush resources.

Persist state if needed.

---

# 5. Scheduler Contract

Scheduler is external.

URP does not mandate:

* one thread per agent
* cooperative scheduling
* event loop
* process isolation

Allowed implementations:

1. dedicated thread
2. async task
3. actor runtime
4. scheduler loop
5. OS process

Only mailbox semantics are fixed.

---


# 6. Minimal Language Interface

Every implementation should expose:

* create_agent(descriptor, context)
* start(agent)
* send(agent, message)
* emit(agent, event)
* shutdown(agent)

Optional:

* inspect_state(agent)
* checkpoint(agent)
* restore(agent)

---

# 7. Invariants

1. initialize exactly once
2. state persists until shutdown
3. messages enter only through mailbox
4. outputs leave only through emit
5. sender never mutates receiver state directly
6. transport must not affect semantics
7. agent remains addressable throughout lifecycle

---

# 8. Reference Implementations

## Python (VHL)

Model:

* asyncio Queue mailbox
* async task/event loop
* async LLM invocation

## C (tiny-agent)

Model:

* ring buffer mailbox
* scheduler/event loop
* pluggable adapter interface
* deterministic memory ownership
===

# Implementation details
- Abstract class is implemented under vhl-agent-backend/vhl-common/urp