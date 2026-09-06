import os
from pydantic import BaseModel, Field
from typing import Any, Dict, Optional

class MessageRequest(BaseModel):
    message_type: str = "MESSAGE"
    payload: Any
    context_id: Optional[str] = None
    task_id: Optional[str] = None
    agent_name: Optional[str] = None

class InitRequest(BaseModel):
    agent_type: str = "echo_agent"
    agent_name: Optional[str] = None
    workspace_path: str = "./agent_workspace"
    conversation_id: Optional[str] = None
    configuration: Dict[str, Any] = Field(default_factory=dict)

class SwitchAgentRequest(BaseModel):
    agent_name: str

class SaveConversationRequest(BaseModel):
    name: str
    workspace_path: str
