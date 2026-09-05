import os
from pydantic import BaseModel
from typing import Any, Dict, Optional

class MessageRequest(BaseModel):
    message_type: str = "MESSAGE"
    payload: Any
    context_id: Optional[str] = None
    task_id: Optional[str] = None

class InitRequest(BaseModel):
    agent_type: str = "echo"
    workspace_path: str = "./agent_workspace"
    conversation_id: Optional[str] = None
    configuration: Dict[str, Any] = {}

class SaveConversationRequest(BaseModel):
    name: str
    workspace_path: str
