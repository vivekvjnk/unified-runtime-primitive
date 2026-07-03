from pydantic import BaseModel, Field, ConfigDict
from typing import Any, Dict, List, Optional, Callable
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

class LastTaskOutcome(Enum):
    """"""
    NONE = "NONE"
    WAITING_FOR_USER_INPUT = "WAITING_FOR_USER_INPUT"
    TASK_FAILED = "TASK_FAILED"
    TASK_COMPLETED = "TASK_COMPLETED"

class FailureCategory(Enum):
    NONE = "NONE"

    AGENTIC_FAILURE = "AGENTIC_FAILURE"
    POSTCONDITION_FAILURE = "POSTCONDITION_FAILURE"
    PRECONDITION_FAILURE = "PRECONDITION_FAILURE"

    VALIDATION_FAILURE = "VALIDATION_FAILURE"
    INFRASTRUCTURE_FAILURE = "INFRASTRUCTURE_FAILURE"

class ProcessResultPayload(BaseModel):
    text: str

class ProcessResult(BaseModel):
    outcome: LastTaskOutcome
    category: FailureCategory = FailureCategory.NONE
    payload: ProcessResultPayload | None = None

class AgentDescriptor(BaseModel):
    agent_id: str
    name: str
    version: str
    capabilities: List[str]
    accepted_message_types: List[str]

class MessageEnvelope(BaseModel):
    model_config = ConfigDict(arbitrary_types_allowed=True)
    
    type: str
    payload: Any
    sender: str
    receiver: str = "HIL"
    message_id: str = Field(default_factory=lambda: str(uuid.uuid4()))
    correlation_id: Optional[str] = None
    metadata: Dict[str, Any] = Field(default_factory=dict)
    timestamp: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))


class AgentState(BaseModel):
    model_config = ConfigDict(arbitrary_types_allowed=True)
    
    # URP's tracking of the internal state/session. 
    # For LangGraph, we track the thread_id to maintain conversational state.
    session_id: str
    status: AgentStatus = AgentStatus.INITIALIZED
    # Execution outcome of last processed message
    last_process_result: ProcessResult | None = None
    outcome_acknowledged: bool = True
    internal_memory: Dict[str, Any] = Field(default_factory=dict)
        
class AgentContext(BaseModel):
    model_config = ConfigDict(arbitrary_types_allowed=True)
    
    workspace_handle: Any = None
    tool_registry: Any = None
    llm_adapter: Any = None
    persistent_memory_handle: Any = None
    configuration: Dict[str, Any] = Field(default_factory=dict)