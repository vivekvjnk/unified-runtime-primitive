import os
from pydantic import BaseModel, Field
from typing import Any, Dict, List, Optional

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

class CreateAgentRequest(BaseModel):
    agent_name: str
    workspace_path: str = "./agent_workspace"
    description: Optional[str] = None
    system_prompt: Optional[str] = None
    harness: str = "pi"
    model: str = "gemini-3.8-flash"
    provider: str = "google-vertex"
    thinking_level: str = "medium"
    ecp_dir: Optional[str] = None
    configuration: Dict[str, Any] = Field(default_factory=dict)

class SaveConversationRequest(BaseModel):
    name: str
    workspace_path: str
