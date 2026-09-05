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
Static metadata describing the identity, version, and capabilities of an agent. Maps 1:1 with A2A Agent Card specifications.

```python
class AgentDescriptor(BaseModel):
    model_config = ConfigDict(arbitrary_types_allowed=True)
    
    agent_id: str                          # Globally unique agent instance or type ID
    name: str                              # Human-readable agent name
    version: str = "1.0.0"                 # Semantic version string
    description: str = ""                  # Semantic description for A2A discovery
    capabilities: List[str] = Field(default_factory=list) # Capability / skill tags
    accepted_message_types: List[str] = Field(default_factory=list) # Accepted message types
    metadata: Dict[str, Any] = Field(default_factory=dict)

    def to_agent_card(self) -> Dict[str, Any]:
        """Serializes descriptor to an A2A Agent Card format."""
        return {
            "name": self.name,
            "description": self.description,
            "version": self.version,
            "capabilities": self.capabilities,
            "accepted_message_types": self.accepted_message_types,
            "metadata": self.metadata,
        }
```

### 2.2 `AgentContext`
Injected runtime environment passed once into `initialize()`. Open and extensible to accommodate domain dependencies (workspaces, SQLite, clients):

```python
class AgentContext(BaseModel):
    model_config = ConfigDict(arbitrary_types_allowed=True, extra="allow")
    
    workspace_path: Optional[str] = None   # Path to agent workspace directory
    configuration: Dict[str, Any] = Field(default_factory=dict)
    metadata: Dict[str, Any] = Field(default_factory=dict)
    
    # Legacy backward-compatible handle fields
    workspace_handle: Any = None
    tool_registry: Any = None
    llm_adapter: Any = None
    persistent_memory_handle: Any = None
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
The universal communication container used for all mailbox inputs and emitted events. Carries first-class A2A `context_id` and `task_id` anchors:

```python
class MessageEnvelope(BaseModel):
    model_config = ConfigDict(arbitrary_types_allowed=True)
    
    type: str                              # Event or message type identifier
    payload: Any = None                    # Structured payload or primitive value
    sender: str                            # Originator ID (e.g. "host", "a2a-bridge", agent_id)
    receiver: str = "HIL"                  # Target ID
    context_id: Optional[str] = None       # Multi-turn conversational session anchor
    task_id: Optional[str] = None          # Isolated unit-of-work task anchor
    message_id: str = Field(default_factory=lambda: str(uuid.uuid4()))
    correlation_id: Optional[str] = None   # Tracing ID to link requests to emitted events
    metadata: Dict[str, Any] = Field(default_factory=dict)
    timestamp: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
```

### 2.5 `ProcessResult`
The structured return value of `process()`, aligning directly with A2A Task/Message return semantics:

```python
class ProcessResult(BaseModel):
    model_config = ConfigDict(arbitrary_types_allowed=True)
    
    outcome: LastTaskOutcome               # NONE, WAITING_FOR_USER_INPUT, TASK_FAILED, TASK_COMPLETED
    category: FailureCategory = FailureCategory.NONE
    text: Optional[str] = None             # Human-readable / LLM assistant text response
    artifacts: List[Dict[str, Any]] = Field(default_factory=list) # Produced files / A2A Artifacts
    metadata: Dict[str, Any] = Field(default_factory=dict)
    payload: Optional[ProcessResultPayload] = None # Backward compatibility payload wrapper
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
class LastTaskOutcome(str, Enum):
    NONE = "NONE"
    WAITING_FOR_USER_INPUT = "WAITING_FOR_USER_INPUT"
    TASK_FAILED = "TASK_FAILED"
    TASK_COMPLETED = "TASK_COMPLETED"
```

### 3.3 `FailureCategory`
```python
class FailureCategory(str, Enum):
    NONE = "NONE"
    AGENTIC_FAILURE = "AGENTIC_FAILURE"
    POSTCONDITION_FAILURE = "POSTCONDITION_FAILURE"
    PRECONDITION_FAILURE = "PRECONDITION_FAILURE"
    VALIDATION_FAILURE = "VALIDATION_FAILURE"
    INFRASTRUCTURE_FAILURE = "INFRASTRUCTURE_FAILURE"
```
