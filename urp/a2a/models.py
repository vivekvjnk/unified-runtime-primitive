"""A2A (Agent2Agent) v1.0 canonical Pydantic v2 data models.

Defines wire models for:
- AgentCard, AgentInterface, AgentSkill, AgentCapabilities
- Message, Part, Role
- Task, TaskState, TaskStatus, Artifact
- Streaming Events (TaskStatusUpdateEvent, TaskArtifactUpdateEvent, StreamResponse)
- Request & Response payloads for HTTP+JSON/REST binding
"""

from __future__ import annotations

import datetime
from enum import Enum
from typing import Any, Dict, List, Optional
from uuid import uuid4
from pydantic import BaseModel, ConfigDict, Field


# ---------------------------------------------------------------------------
# Enums
# ---------------------------------------------------------------------------

class Role(str, Enum):
    ROLE_UNSPECIFIED = "ROLE_UNSPECIFIED"
    ROLE_USER = "ROLE_USER"
    ROLE_AGENT = "ROLE_AGENT"


class TaskState(str, Enum):
    TASK_STATE_UNSPECIFIED = "TASK_STATE_UNSPECIFIED"
    TASK_STATE_SUBMITTED = "TASK_STATE_SUBMITTED"
    TASK_STATE_WORKING = "TASK_STATE_WORKING"
    TASK_STATE_COMPLETED = "TASK_STATE_COMPLETED"
    TASK_STATE_FAILED = "TASK_STATE_FAILED"
    TASK_STATE_CANCELED = "TASK_STATE_CANCELED"
    TASK_STATE_INPUT_REQUIRED = "TASK_STATE_INPUT_REQUIRED"
    TASK_STATE_REJECTED = "TASK_STATE_REJECTED"
    TASK_STATE_AUTH_REQUIRED = "TASK_STATE_AUTH_REQUIRED"


# ---------------------------------------------------------------------------
# Message & Content Parts
# ---------------------------------------------------------------------------

class Part(BaseModel):
    model_config = ConfigDict(extra="allow", populate_by_name=True)

    text: Optional[str] = None
    raw: Optional[str] = None          # Base64 encoded bytes in JSON
    url: Optional[str] = None
    data: Optional[Any] = None         # Structured JSON value
    metadata: Optional[Dict[str, Any]] = None
    filename: Optional[str] = None
    media_type: Optional[str] = Field(default=None, alias="mediaType")


class Message(BaseModel):
    model_config = ConfigDict(extra="allow", populate_by_name=True)

    message_id: str = Field(default_factory=lambda: str(uuid4()), alias="messageId")
    context_id: Optional[str] = Field(default=None, alias="contextId")
    task_id: Optional[str] = Field(default=None, alias="taskId")
    role: Role = Role.ROLE_USER
    parts: List[Part] = Field(default_factory=list)
    metadata: Optional[Dict[str, Any]] = None
    extensions: List[str] = Field(default_factory=list)
    reference_task_ids: List[str] = Field(default_factory=list, alias="referenceTaskIds")

    @classmethod
    def from_text(cls, text: str, role: Role = Role.ROLE_USER, context_id: Optional[str] = None, task_id: Optional[str] = None) -> Message:
        return cls(
            role=role,
            context_id=context_id,
            task_id=task_id,
            parts=[Part(text=text, media_type="text/plain")]
        )

    def get_text(self) -> str:
        """Helper to extract concatenated text from parts."""
        return "\n".join(p.text for p in self.parts if p.text)


# ---------------------------------------------------------------------------
# Artifacts & Tasks
# ---------------------------------------------------------------------------

class Artifact(BaseModel):
    model_config = ConfigDict(extra="allow", populate_by_name=True)

    artifact_id: str = Field(default_factory=lambda: str(uuid4()), alias="artifactId")
    name: Optional[str] = None
    description: Optional[str] = None
    parts: List[Part] = Field(default_factory=list)
    metadata: Optional[Dict[str, Any]] = None
    extensions: List[str] = Field(default_factory=list)


class TaskStatus(BaseModel):
    model_config = ConfigDict(extra="allow", populate_by_name=True)

    state: TaskState = TaskState.TASK_STATE_SUBMITTED
    message: Optional[Message] = None
    timestamp: datetime.datetime = Field(default_factory=lambda: datetime.datetime.now(datetime.timezone.utc))


class Task(BaseModel):
    model_config = ConfigDict(extra="allow", populate_by_name=True)

    id: str = Field(default_factory=lambda: str(uuid4()))
    context_id: Optional[str] = Field(default=None, alias="contextId")
    status: TaskStatus = Field(default_factory=TaskStatus)
    artifacts: List[Artifact] = Field(default_factory=list)
    history: List[Message] = Field(default_factory=list)
    metadata: Optional[Dict[str, Any]] = None


# ---------------------------------------------------------------------------
# Streaming Events
# ---------------------------------------------------------------------------

class TaskStatusUpdateEvent(BaseModel):
    model_config = ConfigDict(extra="allow", populate_by_name=True)

    task_id: str = Field(alias="taskId")
    context_id: str = Field(alias="contextId")
    status: TaskStatus
    metadata: Optional[Dict[str, Any]] = None


class TaskArtifactUpdateEvent(BaseModel):
    model_config = ConfigDict(extra="allow", populate_by_name=True)

    task_id: str = Field(alias="taskId")
    context_id: str = Field(alias="contextId")
    artifact: Artifact
    append: bool = False
    last_chunk: bool = Field(default=True, alias="lastChunk")
    metadata: Optional[Dict[str, Any]] = None


class StreamResponse(BaseModel):
    """Wrapper object used in SSE / streaming operations."""
    model_config = ConfigDict(extra="allow", populate_by_name=True)

    task: Optional[Task] = None
    message: Optional[Message] = None
    status_update: Optional[TaskStatusUpdateEvent] = Field(default=None, alias="statusUpdate")
    artifact_update: Optional[TaskArtifactUpdateEvent] = Field(default=None, alias="artifactUpdate")


# ---------------------------------------------------------------------------
# Agent Discovery (Agent Card)
# ---------------------------------------------------------------------------

class AgentInterface(BaseModel):
    model_config = ConfigDict(extra="allow", populate_by_name=True)

    url: str
    protocol_binding: str = Field(alias="protocolBinding")  # HTTP+JSON, JSONRPC, GRPC
    protocol_version: str = Field(default="1.0", alias="protocolVersion")
    tenant: Optional[str] = None


class AgentProvider(BaseModel):
    model_config = ConfigDict(extra="allow", populate_by_name=True)

    organization: str
    url: str


class AgentCapabilities(BaseModel):
    model_config = ConfigDict(extra="allow", populate_by_name=True)

    streaming: bool = True
    push_notifications: bool = Field(default=False, alias="pushNotifications")
    extended_agent_card: bool = Field(default=False, alias="extendedAgentCard")
    extensions: List[Dict[str, Any]] = Field(default_factory=list)


class AgentSkill(BaseModel):
    model_config = ConfigDict(extra="allow", populate_by_name=True)

    id: str
    name: str
    description: str
    tags: List[str] = Field(default_factory=list)
    examples: List[str] = Field(default_factory=list)
    input_modes: List[str] = Field(default_factory=lambda: ["application/json", "text/plain"], alias="inputModes")
    output_modes: List[str] = Field(default_factory=lambda: ["application/json", "text/plain"], alias="outputModes")


class AgentCard(BaseModel):
    model_config = ConfigDict(extra="allow", populate_by_name=True)

    name: str
    description: str
    version: str = "1.0.0"
    documentation_url: Optional[str] = Field(default=None, alias="documentationUrl")
    icon_url: Optional[str] = Field(default=None, alias="iconUrl")
    provider: Optional[AgentProvider] = None
    capabilities: AgentCapabilities = Field(default_factory=AgentCapabilities)
    supported_interfaces: List[AgentInterface] = Field(default_factory=list, alias="supportedInterfaces")
    default_input_modes: List[str] = Field(default_factory=lambda: ["text/plain", "application/json"], alias="defaultInputModes")
    default_output_modes: List[str] = Field(default_factory=lambda: ["text/plain", "application/json"], alias="defaultOutputModes")
    skills: List[AgentSkill] = Field(default_factory=list)


# ---------------------------------------------------------------------------
# Request & Response Envelopes (REST Binding)
# ---------------------------------------------------------------------------

class SendMessageConfiguration(BaseModel):
    model_config = ConfigDict(extra="allow", populate_by_name=True)

    accepted_output_modes: List[str] = Field(default_factory=list, alias="acceptedOutputModes")
    history_length: Optional[int] = Field(default=None, alias="historyLength")
    return_immediately: bool = Field(default=False, alias="returnImmediately")


class SendMessageRequest(BaseModel):
    model_config = ConfigDict(extra="allow", populate_by_name=True)

    tenant: Optional[str] = None
    message: Message
    configuration: Optional[SendMessageConfiguration] = None
    metadata: Optional[Dict[str, Any]] = None


class SendMessageResponse(BaseModel):
    model_config = ConfigDict(extra="allow", populate_by_name=True)

    task: Optional[Task] = None
    message: Optional[Message] = None


class CancelTaskRequest(BaseModel):
    model_config = ConfigDict(extra="allow", populate_by_name=True)

    tenant: Optional[str] = None
    metadata: Optional[Dict[str, Any]] = None
