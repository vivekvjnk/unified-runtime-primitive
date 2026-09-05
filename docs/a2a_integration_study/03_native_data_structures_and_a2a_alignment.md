# 03 — URP Native Data Structures Review & A2A Alignment

> **Study Series:** A2A Protocol Integration & URP Feasibility Study  
> **Source Material:** Real-world URP agent implementations in VHL (`archy/urp_archy.py`, `ana/urp_ana.py`, `librarian/urp_librarian.py`)  
> **Topic:** Evaluation of current URP data structures (`AgentContext`, `MessageEnvelope`, `ProcessResult`, `AgentDescriptor`, `AgentState`) and proposed simplifications for native A2A alignment.  
> **Status:** Completed Phase 3 Exploration

---

## 1. Executive Summary

A critical examination of how production agents (**Archy**, **ANA**, and **Librarian**) utilize URP primitives reveals significant opportunities for simplification and harmonization with the **Agent2Agent (A2A)** specification.

Currently, several native URP data structures suffer from:
1. **Rigid / Underutilized Containers:** E.g., `AgentContext` defines static fields (`llm_adapter`, `tool_registry`) that real agents routinely bypass in favor of custom dataclasses (`ArchyContext`, `AnaContext`).
2. **Artificial Nesting:** E.g., `ProcessResultPayload(text=...)` wraps a single `text: str` field, making artifact passing awkward.
3. **Implicit A2A Routing Anchors:** E.g., `context_id` and `task_id` (the foundational session/task anchors in A2A) are relegated to arbitrary dictionary payloads rather than being first-class fields on `MessageEnvelope`.

---

## 2. Deep-Dive Review of Current Agent Implementations

### 2.1 `AgentContext` — Rigid Schema vs. Domain Customization

#### Current State in `urp.data_types`:
```python
class AgentContext(BaseModel):
    workspace_handle: Any = None
    tool_registry: Any = None
    llm_adapter: Any = None
    persistent_memory_handle: Any = None
    configuration: Dict[str, Any] = Field(default_factory=dict)
```

#### Reality in Production Agents:
* `Archy` defines `ArchyContext(module_name, workspace, sqlite_manager, config)`.
* `ANA` defines `AnaContext(module_name, workspace, sqlite_manager, web_socket_client, config)`.
* `Librarian` defines `LibrarianContext(module_name, workspace, sqlite_manager, config)`.

#### Insight & Simplification:
In practice, every agent engine injects domain-specific dependencies (databases, WebSocket clients, skill registries, MCP servers). 

**Recommendation:** Make `AgentContext` a flexible, extensible Pydantic model with convenient standard defaults:
* `workspace_path: Optional[str | Path] = None` (universal across all file/tool agents)
* `configuration: Dict[str, Any] = Field(default_factory=dict)`
* `metadata: Dict[str, Any] = Field(default_factory=dict)`
* Support arbitrary keyword arguments / inheritance so custom agent authors don't have to fight a rigid schema.

---

### 2.2 `MessageEnvelope` — Elevating A2A Identity Anchors

#### Current State in `urp.data_types`:
```python
class MessageEnvelope(BaseModel):
    type: str
    payload: Any
    sender: str
    receiver: str = "HIL"
    message_id: str = Field(default_factory=lambda: str(uuid.uuid4()))
    correlation_id: Optional[str] = None
    metadata: Dict[str, Any] = Field(default_factory=dict)
    timestamp: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
```

#### Reality in Production Agents & A2A:
* In `Archy`, `ANA`, and `Librarian`, the agent immediately checks `message.payload["text"]` or expects `context_id` / `task_id`.
* In A2A, every communication occurs within a **Session Scope (`context_id`)** and optionally a **Task Scope (`task_id`)**. Currently, agents either generate new UUIDs per turn or parse them out of nested dictionary payloads.

#### Insight & Simplification:
Promote `context_id` and `task_id` to **first-class fields** on `MessageEnvelope`:

```python
class MessageEnvelope(BaseModel):
    type: str                              # Message/Event type (e.g. "MESSAGE", "TASK_STATUS_UPDATE", "BUILD_SCUD")
    payload: Any = None                    # Payload content (dict, str, or Part objects)
    sender: str                            # Originator ID
    receiver: str = "HIL"                  # Target agent ID or "HIL"
    
    # First-class A2A Routing & Session Anchors
    context_id: Optional[str] = None       # Multi-turn conversational session anchor
    task_id: Optional[str] = None          # Isolated unit-of-work anchor
    
    message_id: str = Field(default_factory=lambda: str(uuid.uuid4()))
    correlation_id: Optional[str] = None   # Causality / tracing ID
    metadata: Dict[str, Any] = Field(default_factory=dict)
    timestamp: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
```

---

### 2.3 `ProcessResult` & `ProcessResultPayload` — Eliminating Artificial Wrapping

#### Current State in `urp.data_types`:
```python
class ProcessResultPayload(BaseModel):
    text: str

class ProcessResult(BaseModel):
    outcome: LastTaskOutcome
    category: FailureCategory = FailureCategory.NONE
    payload: ProcessResultPayload | None = None
```

#### Reality in Production Agents:
* Every agent performs this dance:
  ```python
  payload = ProcessResultPayload(text=response)
  return ProcessResult(outcome=process_outcome, payload=payload)
  ```
* When an agent produces files or artifacts (such as `<module>.scud` or `.tsx` schematic code), it cannot put them in `ProcessResultPayload` because it only accepts `text: str`!

#### Insight & Simplification:
Collapse `ProcessResultPayload` directly into `ProcessResult`, enriching it with first-class fields for `text`, `artifacts`, and `metadata`:

```python
class ProcessResult(BaseModel):
    outcome: LastTaskOutcome               # TASK_COMPLETED, WAITING_FOR_USER_INPUT, TASK_FAILED
    category: FailureCategory = FailureCategory.NONE
    text: Optional[str] = None             # Human/LLM textual response or explanation
    artifacts: List[Dict[str, Any]] = Field(default_factory=list) # Produced files / A2A Artifact descriptors
    metadata: Dict[str, Any] = Field(default_factory=dict)
    
    # Optional backward-compatible payload accessor if needed
    @property
    def payload(self) -> Any:
        return {"text": self.text, "artifacts": self.artifacts, "metadata": self.metadata}
```

This immediately allows `Archy` to return `artifacts=[{"name": "SCUD", "path": "bms.scud"}]` and `ANA` to return generated circuit artifacts naturally.

---

### 2.4 `AgentDescriptor` — 1:1 Alignment with A2A `AgentCard`

#### Current State:
```python
class AgentDescriptor(BaseModel):
    agent_id: str
    name: str
    version: str
    capabilities: List[str]
    accepted_message_types: List[str]
```

#### Proposed Enrichment for A2A:
Add optional `description` and `author` / `skills` fields so that an `AgentDescriptor` can serialize directly into an A2A **Agent Card (`/.well-known/agent-card.json`)**:

```python
class AgentDescriptor(BaseModel):
    agent_id: str                          # Globally unique ID
    name: str                              # Human-readable name
    description: str = ""                  # Semantic description for A2A agent discovery
    version: str = "1.0.0"                 # Semantic version
    capabilities: List[str] = Field(default_factory=list) # Capability / skill tags
    accepted_message_types: List[str] = Field(default_factory=list)
    metadata: Dict[str, Any] = Field(default_factory=dict)
```

---

### 2.5 `LastTaskOutcome` & `TaskState` Enum Alignment

The current `LastTaskOutcome` enum:
```python
class LastTaskOutcome(str, Enum):
    NONE = "NONE"
    WAITING_FOR_USER_INPUT = "WAITING_FOR_USER_INPUT"
    TASK_FAILED = "TASK_FAILED"
    TASK_COMPLETED = "TASK_COMPLETED"
```

Maps cleanly to A2A `TaskState`:
* `TASK_COMPLETED` $\leftrightarrow$ `TaskState.completed`
* `WAITING_FOR_USER_INPUT` $\leftrightarrow$ `TaskState.input_required`
* `TASK_FAILED` $\leftrightarrow$ `TaskState.failed`
* `NONE` $\leftrightarrow$ Stateless `Message` or intermediate state

---

## 3. Comparison Matrix: Before vs. After Proposed Simplifications

| Dimension | Legacy URP (`vhl_common.urp`) | Proposed Streamlined URP (`urp-core` A2A-Ready) |
|---|---|---|
| **`AgentContext`** | Rigid static fields (`tool_registry`, `llm_adapter`) bypassed by real agents. | Clean, extensible model with `workspace_path`, `configuration`, and open kwargs. |
| **`MessageEnvelope`** | `context_id` and `task_id` hidden inside arbitrary payloads. | First-class `context_id` and `task_id` for native A2A session & task routing. |
| **`ProcessResult`** | Constrained to `ProcessResultPayload(text=str)` wrapper. | Direct `text`, `artifacts: List`, and `metadata` fields without artificial wrapping. |
| **`AgentDescriptor`** | Basic identity tags. | Fully compatible with A2A `AgentCard` (`/.well-known/agent-card.json`). |
| **Artifact Delivery** | Unmodeled in return types; side-effect only. | Native `artifacts` list holding paths or A2A `Artifact` parts (`a2a-file://`). |

---

## 4. Next Implementation Steps in `urp-core`

1. **Refactor `urp/data_types.py`:** Apply these streamlined models (`MessageEnvelope` with `context_id`/`task_id`, direct `ProcessResult` fields, flexible `AgentContext`, enhanced `AgentDescriptor`).
2. **Update `AbstractURPAgent`:** Support returning enriched `ProcessResult` while maintaining backward compatibility for existing simple text agents.
3. **Update Sample & SDK Agents:** Refactor `EchoAgent` and `SDKURPAgent` to showcase the clean, simplified APIs.
4. **Update Test Suites:** Validate serialization, property checks, and envelope dispatches.
