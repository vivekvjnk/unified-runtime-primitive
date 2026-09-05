# Architecture: Data Types & Envelopes

This document details the core data models, serialization contracts, and envelope standards defined in `urp.data_types`.

---

## 1. Type Overview

All primary URP data structures are built on **Pydantic v2** (`BaseModel`), enabling strict validation, JSON serialization/deserialization, and arbitrary type compatibility where needed.

```
                  ┌──────────────────────┐
                  │   AgentDescriptor    │
                  │  (Static Identity)   │
                  └──────────────────────┘
                             │
                             ▼
┌─────────────────────┐  instantiates   ┌─────────────────────┐
│    AgentContext     ├────────────────►│     AgentState      │
│(Injected Resources) │                 │  (Mutable Runtime)  │
└─────────────────────┘                 └──────────┬──────────┘
                                                   │
                   ┌───────────────────────────────┴───────────────────────────────┐
                   ▼                                                               ▼
        ┌─────────────────────┐                                         ┌─────────────────────┐
        │   MessageEnvelope   │                                         │    ProcessResult    │
        │  (Mailbox / Events) │                                         │ (Execution Outcome) │
        └─────────────────────┘                                         └─────────────────────┘
```

---

## 2. Model Specifications

### 2.1 `AgentDescriptor`
Static metadata describing the identity, version, and capabilities of an agent.

```python
class AgentDescriptor(BaseModel):
    agent_id: str                          # Globally unique agent instance or type ID
    name: str                              # Human-readable agent name
    version: str                           # Semantic version string (e.g. "1.0.0")
    capabilities: List[str]                # Capability tags (e.g. ["TERMINAL", "FILE_EDITOR"])
    accepted_message_types: List[str]      # Permitted envelope types (e.g. ["QUERY", "TASK"])
```

### 2.2 `AgentContext`
Injected runtime environment passed once into `initialize()`:

```python
class AgentContext(BaseModel):
    model_config = ConfigDict(arbitrary_types_allowed=True)
    
    workspace_handle: Any = None           # Path or handle to agent workspace directory
    tool_registry: Any = None              # Available tools or MCP tool registry
    llm_adapter: Any = None                # LLM client or adapter configuration
    persistent_memory_handle: Any = None   # Database or persistent memory handle
    configuration: Dict[str, Any] = Field(default_factory=dict)
```

### 2.3 `AgentState`
Dynamic runtime state tracked by the agent:

```python
class AgentState(BaseModel):
    model_config = ConfigDict(arbitrary_types_allowed=True)
    
    session_id: str                        # UUID string tracking conversational session
    status: AgentStatus = AgentStatus.INITIALIZED
    last_process_result: ProcessResult | None = None
    internal_memory: Dict[str, Any] = Field(default_factory=dict)
```

### 2.4 `MessageEnvelope`
The universal communication container used for all mailbox inputs and emitted events:

```python
class MessageEnvelope(BaseModel):
    model_config = ConfigDict(arbitrary_types_allowed=True)
    
    type: str                              # Event or message type identifier
    payload: Any                           # Structured payload or primitive value
    sender: str                            # Originator ID (e.g. "host", "a2a-bridge", agent_id)
    receiver: str = "HIL"                  # Target ID
    message_id: str = Field(default_factory=lambda: str(uuid.uuid4()))
    correlation_id: Optional[str] = None   # Tracing ID to link requests to emitted events
    metadata: Dict[str, Any] = Field(default_factory=dict)
    timestamp: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
```

### 2.5 `ProcessResult` & `ProcessResultPayload`
The structured return value of `process()`:

```python
class ProcessResultPayload(BaseModel):
    text: str                              # Textual response or serialized output

class ProcessResult(BaseModel):
    outcome: LastTaskOutcome               # NONE, WAITING_FOR_USER_INPUT, TASK_FAILED, TASK_COMPLETED
    category: FailureCategory = FailureCategory.NONE
    payload: ProcessResultPayload | None = None
```

---

## 3. Enumerations

### 3.1 `AgentStatus`
```python
class AgentStatus(str, Enum):
    UNINITIALIZED = "UNINITIALIZED"
    INITIALIZED = "INITIALIZED"
    WAITING = "WAITING"
    PROCESSING = "PROCESSING"
    ERROR = "ERROR"
    TERMINATED = "TERMINATED"
```

### 3.2 `LastTaskOutcome`
```python
class LastTaskOutcome(Enum):
    NONE = "NONE"
    WAITING_FOR_USER_INPUT = "WAITING_FOR_USER_INPUT"
    TASK_FAILED = "TASK_FAILED"
    TASK_COMPLETED = "TASK_COMPLETED"
```

### 3.3 `FailureCategory`
```python
class FailureCategory(Enum):
    NONE = "NONE"
    AGENTIC_FAILURE = "AGENTIC_FAILURE"
    POSTCONDITION_FAILURE = "POSTCONDITION_FAILURE"
    PRECONDITION_FAILURE = "PRECONDITION_FAILURE"
    VALIDATION_FAILURE = "VALIDATION_FAILURE"
    INFRASTRUCTURE_FAILURE = "INFRASTRUCTURE_FAILURE"
```
