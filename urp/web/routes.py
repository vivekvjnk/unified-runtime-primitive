import asyncio
import json
import os
from pathlib import Path
from typing import Any, Optional

from fastapi import APIRouter, File, Form, HTTPException, Query, UploadFile, WebSocket, WebSocketDisconnect
from fastapi.responses import HTMLResponse

from .agent_service import AgentHostingService, normalize_agent_name
from .schemas import (
    CreateAgentRequest,
    InitRequest,
    MessageRequest,
    SaveConversationRequest,
    StopAgentRequest,
    SwitchAgentRequest,
)
from .workspace_service import (
    browse_filesystem,
    list_workspace_conversations,
    load_conversation_history,
    save_workspace_conversation,
)
from .pi_log_parser import parse_pi_session_log
from .ecp_service import validate_and_extract_ecp

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
async def get_pi_raw_logs(limit: int = 50, agent_name: Optional[str] = None):
    """Retrieves structured LLM interaction turns from the target Pi agent session log."""
    host = service.get_host(agent_name)
    if not host or not host.agent:
        return {
            "error": "No active URP agent is currently running.",
            "is_pi_agent": False,
            "turns": [],
            "stats": {},
        }

    agent = host.agent
    if not hasattr(agent, "get_raw_log_path"):
        return {
            "error": f"Agent ({host.descriptor.name}) is not a Pi harness agent and does not provide JSONL session logs.",
            "is_pi_agent": False,
            "agent_type": host.descriptor.agent_id,
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
    parsed["agent_id"] = host.descriptor.agent_id
    parsed["agent_name"] = host.descriptor.name
    return parsed


@router.get("/agent/types")
async def list_agent_types():
    """Returns all agent types registered in AgentRegistry."""
    return service.get_registered_types()


@router.get("/agent/active")
async def get_active_agents():
    """Returns the currently active agent and list of all running agents."""
    return {
        "active_agent_name": service.active_agent_name,
        "running_agents": service.list_running_agents(),
    }


@router.post("/agent/switch")
async def switch_active_agent(req: SwitchAgentRequest):
    """Switches active agent focus in the container."""
    try:
        service.set_active_agent(req.agent_name)
        return {
            "status": "switched",
            "active_agent_name": service.active_agent_name,
            "running_agents": service.list_running_agents(),
        }
    except KeyError as e:
        raise HTTPException(status_code=404, detail=str(e))


@router.post("/agent/stop")
async def stop_agent(req: StopAgentRequest):
    """Gracefully shuts down a specific running agent or the currently active agent."""
    target_name = req.agent_name or service.active_agent_name
    if not target_name:
        raise HTTPException(status_code=400, detail="No active agent to stop")

    norm_name = normalize_agent_name(target_name)
    if norm_name not in service.hosts and target_name not in service.hosts:
        raise HTTPException(status_code=404, detail=f"No running agent found for '{target_name}'")

    await service.shutdown(agent_name=norm_name)
    return {
        "status": "stopped",
        "stopped_agent": norm_name,
        "active_agent_name": service.active_agent_name,
        "running_agents": service.list_running_agents(),
    }


@router.get("/workspace/agents")
async def scan_workspace_agents(path: str = "."):
    """Scans <workspace_path>/.well_known/<agent_name>.json for A2A Agent Cards."""
    return service.scan_workspace_well_known_agents(path)


@router.post("/agent/create")
async def create_agent_endpoint(
    agent_name: str = Form(...),
    workspace_path: str = Form("./agent_workspace"),
    description: Optional[str] = Form(None),
    system_prompt: Optional[str] = Form(None),
    harness: str = Form("pi"),
    model: str = Form("gemini-3.8-flash"),
    provider: str = Form("google-vertex"),
    thinking_level: str = Form("medium"),
    ecp_dir: Optional[str] = Form(None),
    ecp_file: Optional[UploadFile] = File(None),
):
    """
    Authoring endpoint: Configures, persists, and launches a new URP agent.
    Supports injecting an ECP (Engineering Capability Package) from a zip archive or local directory.
    """
    norm_name = normalize_agent_name(agent_name)
    extracted_skills = []
    capabilities = ["READ", "BASH", "EDIT", "WRITE", "SKILLS"]

    # Ingest ECP if provided
    if ecp_file:
        file_bytes = await ecp_file.read()
        pkg_name = Path(ecp_file.filename).stem if ecp_file.filename else None
        skill_info = validate_and_extract_ecp(
            workspace_path=workspace_path,
            archive_bytes=file_bytes,
            package_name=pkg_name,
        )
        extracted_skills.append(skill_info)
        capabilities.append(skill_info["skill_name"].upper().replace("-", "_"))
    elif ecp_dir and ecp_dir.strip():
        skill_info = validate_and_extract_ecp(
            workspace_path=workspace_path,
            source_dir=ecp_dir.strip(),
        )
        extracted_skills.append(skill_info)
        capabilities.append(skill_info["skill_name"].upper().replace("-", "_"))

    try:
        host = await service.create_and_register_agent(
            agent_name=norm_name,
            workspace_path=workspace_path,
            description=description,
            system_prompt=system_prompt,
            harness=harness,
            model=model,
            provider=provider,
            thinking_level=thinking_level,
            capabilities=capabilities,
            persist_config=False,  # Keep repo clean; .well_known card in workspace is the source of truth
        )
        return {
            "status": "created",
            "agent_name": norm_name,
            "agent_id": host.descriptor.agent_id,
            "harness": harness,
            "workspace_path": os.path.abspath(workspace_path),
            "well_known_card": str(Path(workspace_path).resolve() / ".well_known" / f"{norm_name}.json"),
            "extracted_skills": extracted_skills,
            "active_agent_name": service.active_agent_name,
            "running_agents": service.list_running_agents(),
        }
    except Exception as e:
        raise HTTPException(status_code=400, detail=f"Failed to create agent: {str(e)}")


@router.post("/agent/init")
async def init_agent(req: InitRequest):
    """Initializes and runs the requested agent type as an independent URPHost."""
    host = await service.initialize_agent(
        agent_type=req.agent_type,
        workspace_path=req.workspace_path,
        conversation_id=req.conversation_id,
        configuration=req.configuration,
        agent_name=req.agent_name,
    )
    return {
        "status": "initialized",
        "agent_id": host.descriptor.agent_id if host else "unknown",
        "agent_name": host.descriptor.name if host else req.agent_type,
        "agent_type": req.agent_type,
        "active_agent_name": service.active_agent_name,
        "running_agents": service.list_running_agents(),
    }


@router.post("/agent/message")
async def send_message(req: MessageRequest):
    """Sends a message to the target agent's mailbox."""
    try:
        msg_id = await service.send_message(
            message_type=req.message_type,
            payload=req.payload,
            context_id=req.context_id,
            task_id=req.task_id,
            agent_name=req.agent_name,
        )
        return {"message_id": msg_id}
    except Exception as e:
        return {"error": str(e)}


@router.get("/agent/state")
async def get_state(agent_name: Optional[str] = None):
    """Returns read-only telemetry and state for the requested or active agent."""
    return service.get_state(agent_name=agent_name)


@router.get("/agent/conversations")
async def list_conversations(workspace_path: str):
    """Lists saved conversation sessions in the workspace."""
    return list_workspace_conversations(workspace_path)


@router.get("/agent/conversations/history")
async def get_conversation_history(workspace_path: str, conversation_id: str):
    """Reads reconstructed conversation events from the workspace."""
    return load_conversation_history(workspace_path, conversation_id)


@router.post("/agent/conversations/save")
async def save_conversation(req: SaveConversationRequest, agent_name: Optional[str] = None):
    """Saves the current active conversation ID with a human-readable name."""
    host = service.get_host(agent_name)
    if not host or not host.agent or not hasattr(host.agent, "get_conversation_id"):
        return {"status": "error", "message": "Agent does not support conversation persistence"}

    conv_id = host.agent.get_conversation_id()
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
