import asyncio
import json
from pathlib import Path
from typing import Any

from fastapi import APIRouter, WebSocket, WebSocketDisconnect
from fastapi.responses import HTMLResponse

from .agent_service import AgentHostingService
from .schemas import InitRequest, MessageRequest, SaveConversationRequest
from .workspace_service import (
    browse_filesystem,
    list_workspace_conversations,
    load_conversation_history,
    save_workspace_conversation,
)
from .pi_log_parser import parse_pi_session_log

router = APIRouter()
service = AgentHostingService()

TEMPLATES_DIR = Path(__file__).resolve().parent / "templates"


@router.get("/", response_class=HTMLResponse)
async def get_console_ui():
    """Serves the modernized interactive URP-HF dashboard."""
    index_file = TEMPLATES_DIR / "index.html"
    with open(index_file, "r", encoding="utf-8") as f:
        return f.read()


@router.get("/logs", response_class=HTMLResponse)
async def get_logs_ui():
    """Serves the dedicated Pi Agent Raw LLM Response Monitor dashboard."""
    logs_file = TEMPLATES_DIR / "logs.html"
    with open(logs_file, "r", encoding="utf-8") as f:
        return f.read()


@router.get("/agent/pi/raw-logs")
async def get_pi_raw_logs(limit: int = 50):
    """Retrieves structured LLM interaction turns from the active Pi agent harness session log."""
    if not service.host or not service.host.agent:
        return {
            "error": "No active URP agent is currently running.",
            "is_pi_agent": False,
            "turns": [],
            "stats": {},
        }

    agent = service.host.agent
    # Check if this agent is a PiURPAgent harness or exposes get_raw_log_path
    if not hasattr(agent, "get_raw_log_path"):
        return {
            "error": f"Active agent ({service.host.descriptor.name}) is not a Pi harness agent and does not provide JSONL session logs.",
            "is_pi_agent": False,
            "agent_type": service.host.descriptor.agent_id,
            "turns": [],
            "stats": {},
        }

    session_path = await agent.get_raw_log_path()
    if not session_path:
        return {
            "error": "Pi RPC client is not running or has not yet written a session file.",
            "is_pi_agent": True,
            "turns": [],
            "stats": {},
        }

    parsed = parse_pi_session_log(session_path, max_turns=limit)
    parsed["is_pi_agent"] = True
    parsed["agent_id"] = service.host.descriptor.agent_id
    parsed["agent_name"] = service.host.descriptor.name
    return parsed


@router.get("/agent/types")
async def list_agent_types():
    """Returns all agent types registered in AgentRegistry."""
    return service.get_registered_types()


@router.post("/agent/init")
async def init_agent(req: InitRequest):
    """Initializes and runs the requested agent type."""
    host = await service.initialize_agent(
        agent_type=req.agent_type,
        workspace_path=req.workspace_path,
        conversation_id=req.conversation_id,
        configuration=req.configuration,
    )
    return {
        "status": "initialized",
        "agent_id": host.descriptor.agent_id if host else "unknown",
        "agent_type": req.agent_type,
    }


@app_message_route := router.post("/agent/message")
async def send_message(req: MessageRequest):
    """Sends a message to the agent's mailbox."""
    try:
        msg_id = await service.send_message(
            message_type=req.message_type,
            payload=req.payload,
            context_id=req.context_id,
            task_id=req.task_id,
        )
        return {"message_id": msg_id}
    except Exception as e:
        return {"error": str(e)}


@router.get("/agent/state")
async def get_state():
    """Returns read-only telemetry and state for the active agent."""
    return service.get_state()


@router.get("/agent/conversations")
async def list_conversations(workspace_path: str):
    """Lists saved conversation sessions in the workspace."""
    return list_workspace_conversations(workspace_path)


@router.get("/agent/conversations/history")
async def get_conversation_history(workspace_path: str, conversation_id: str):
    """Reads reconstructed conversation events from the workspace."""
    return load_conversation_history(workspace_path, conversation_id)


@router.post("/agent/conversations/save")
async def save_conversation(req: SaveConversationRequest):
    """Saves the current active conversation ID with a human-readable name."""
    if not service.host or not service.host.agent or not hasattr(service.host.agent, "get_conversation_id"):
        return {"status": "error", "message": "Agent does not support conversation persistence"}

    conv_id = service.host.agent.get_conversation_id()
    if not conv_id:
        return {"status": "error", "message": "No active conversation ID"}

    return save_workspace_conversation(req.workspace_path, conv_id, req.name)


@router.get("/agent/browse")
async def browse_directory(path: str = "."):
    """Directory picker endpoint for the UI."""
    return browse_filesystem(path)


@router.websocket("/ws")
async def websocket_endpoint(websocket: WebSocket):
    """Real-time event streaming websocket."""
    await websocket.accept()
    try:
        while True:
            if not service.host:
                await asyncio.sleep(0.5)
                continue
            event = await service.host.get_next_event()
            event_dict = event.model_dump(mode="json")
            await websocket.send_text(json.dumps(event_dict))
    except WebSocketDisconnect:
        pass
    except Exception:
        pass
