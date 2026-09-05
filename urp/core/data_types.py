from pydantic import BaseModel, Field, ConfigDict, model_validator
from typing import Any, Dict, List, Optional, Callable, Union
from datetime import datetime, timezone
import uuid
from enum import Enum

class AgentStatus(str, Enum):
    """Strict state machine enforcement per URP Section 2."""
    UNINITIALIZED = "UNINITIALIZED"
    INITIALIZED = "INITIALIZED"
    WAITING = "WAITING"
    PROCESSING = "PROCESSING"
    ERROR = "ERROR"
    TERMINATED = "TERMINATED"

class LastTaskOutcome(str, Enum):
    """Canonical task execution outcome matching A2A TaskState semantics."""
    NONE = "NONE"
    WAITING_FOR_USER_INPUT = "WAITING_FOR_USER_INPUT"
    TASK_FAILED = "TASK_FAILED"
    TASK_COMPLETED = "TASK_COMPLETED"

class FailureCategory(str, Enum):
    """Categorical classification of task processing failures."""
    NONE = "NONE"
    AGENTIC_FAILURE = "AGENTIC_FAILURE"
    POSTCONDITION_FAILURE = "POSTCONDITION_FAILURE"
    PRECONDITION_FAILURE = "PRECONDITION_FAILURE"
    VALIDATION_FAILURE = "VALIDATION_FAILURE"
    INFRASTRUCTURE_FAILURE = "INFRASTRUCTURE_FAILURE"

class ProcessResultPayload(BaseModel):
    """Legacy payload wrapper kept for backward compatibility."""
    text: str = ""

class ProcessResult(BaseModel):
    """
    Standardized execution outcome produced by AbstractURPAgent.process().
    Directly aligns with A2A Task and Message return semantics.
    """
    model_config = ConfigDict(arbitrary_types_allowed=True)
    
    outcome: LastTaskOutcome
    category: FailureCategory = FailureCategory.NONE
    text: Optional[str] = None
    artifacts: List[Dict[str, Any]] = Field(default_factory=list)
    metadata: Dict[str, Any] = Field(default_factory=dict)
    payload: Optional[ProcessResultPayload] = None

    @model_validator(mode="after")
    def _sync_text_and_payload(self) -> "ProcessResult":
        """Harmonizes direct text with legacy payload object for bidirectional compatibility."""
        if self.text is None and self.payload is not None:
            self.text = self.payload.text
        elif self.text is not None and self.payload is None:
            self.payload = ProcessResultPayload(text=self.text)
        return self

class AgentDescriptor(BaseModel):
    """
    Static metadata declaring an agent's identity and capabilities.
    Maps 1:1 with A2A Agent Card specifications.
    """
    model_config = ConfigDict(arbitrary_types_allowed=True)
    
    agent_id: str
    name: str
    version: str = "1.0.0"
    description: str = ""
    capabilities: List[str] = Field(default_factory=list)
    accepted_message_types: List[str] = Field(default_factory=list)
    metadata: Dict[str, Any] = Field(default_factory=dict)

    def to_agent_card(self, base_url: Optional[str] = None) -> Dict[str, Any]:
        """Serializes descriptor to an A2A Agent Card format."""
        card: Dict[str, Any] = {
            "name": self.name,
            "description": self.description,
            "version": self.version,
            "capabilities": self.capabilities,
            "accepted_message_types": self.accepted_message_types,
            "metadata": self.metadata,
        }
        if base_url:
            card["url"] = f"{base_url.rstrip('/')}/a2a/v1"
        return card

class MessageEnvelope(BaseModel):
    """
    Universal container for all inbound mailbox messages and outbound emitted events.
    Carries first-class A2A context_id (session anchor) and task_id (task anchor).
    """
    model_config = ConfigDict(arbitrary_types_allowed=True)
    
    type: str
    payload: Any = None
    sender: str
    receiver: str = "HIL"
    context_id: Optional[str] = None       # Multi-turn conversational session anchor
    task_id: Optional[str] = None          # Isolated unit-of-work task anchor
    message_id: str = Field(default_factory=lambda: str(uuid.uuid4()))
    correlation_id: Optional[str] = None   # Causality / tracing ID
    metadata: Dict[str, Any] = Field(default_factory=dict)
    timestamp: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))

class AgentState(BaseModel):
    """
    Dynamic runtime state tracked by the URP agent.
    """
    model_config = ConfigDict(arbitrary_types_allowed=True)
    
    session_id: str
    status: AgentStatus = AgentStatus.INITIALIZED
    last_process_result: Optional[ProcessResult] = None
    internal_memory: Dict[str, Any] = Field(default_factory=dict)
        
class AgentContext(BaseModel):
    """
    Injected execution context passed to initialize().
    Open and extensible to accommodate domain dependencies (workspaces, SQLite, clients).
    """
    model_config = ConfigDict(arbitrary_types_allowed=True, extra="allow")
    
    workspace_path: Optional[str] = None
    configuration: Dict[str, Any] = Field(default_factory=dict)
    metadata: Dict[str, Any] = Field(default_factory=dict)
    
    # Backward-compatible handle fields
    workspace_handle: Any = None
    tool_registry: Any = None
    llm_adapter: Any = None
    persistent_memory_handle: Any = None
