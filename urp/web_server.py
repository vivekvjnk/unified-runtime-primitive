import asyncio
import json
import os
from pathlib import Path
from contextlib import asynccontextmanager
from typing import Any, Dict, List, Optional

from fastapi import FastAPI, WebSocket, WebSocketDisconnect
from fastapi.responses import HTMLResponse
from pydantic import BaseModel

from .agent_registry import (
    create_agent,
    get_agent_factory,
    get_registered_agent_descriptors,
    get_registered_agent_types,
    register_agent_if_absent,
)
from .data_types import AgentContext, AgentDescriptor, MessageEnvelope
from .host import URPHost
from .sample_agent import EchoAgent
from .sdk_agent import SDKURPAgent
from .pi_harness import PiURPAgent

@asynccontextmanager
async def lifespan(app: FastAPI):
    """Lifespan context manager initializing the default host on startup."""
    await initialize_agent("echo", "./agent_workspace")
    yield
    global host
    if host:
        await host.shutdown()

app = FastAPI(title="URP Independent Hosting Framework (URP-HF)", lifespan=lifespan)

# Global host instance
host: Optional[URPHost] = None
event_log: List[dict] = []


def register_builtin_agents() -> None:
    """Registers standard reference agents with the AgentRegistry."""
    # 1. Echo Agent (Reference primitive test agent)
    register_agent_if_absent(
        name="echo",
        factory_func=lambda descriptor=None: EchoAgent(
            descriptor=descriptor
            or AgentDescriptor(
                agent_id="vhl.echo.v1",
                name="Echo Agent",
                version="1.0.0",
                description="Built-in diagnostic echo agent for testing runtime message loops.",
                capabilities=["ECHO"],
                accepted_message_types=["PING", "MESSAGE"],
            )
        ),
        descriptor=AgentDescriptor(
            agent_id="vhl.echo.v1",
            name="Echo Agent",
            version="1.0.0",
            description="Built-in diagnostic echo agent for testing runtime message loops.",
            capabilities=["ECHO"],
            accepted_message_types=["PING", "MESSAGE"],
        ),
    )

    # 2. SDK Agent (OpenHands SDK Agent with Terminal & FileEditor tools)
    register_agent_if_absent(
        name="sdk",
        factory_func=lambda descriptor=None: SDKURPAgent(
            descriptor=descriptor
            or AgentDescriptor(
                agent_id="vhl.sdk.v1",
                name="OpenHands SDK Agent",
                version="1.0.0",
                description="Autonomous coding agent powered by OpenHands SDK with terminal and file tools.",
                capabilities=["TERMINAL", "FILE_EDITOR"],
                accepted_message_types=["MESSAGE", "TASK"],
            )
        ),
        descriptor=AgentDescriptor(
            agent_id="vhl.sdk.v1",
            name="OpenHands SDK Agent",
            version="1.0.0",
            description="Autonomous coding agent powered by OpenHands SDK with terminal and file tools.",
            capabilities=["TERMINAL", "FILE_EDITOR"],
            accepted_message_types=["MESSAGE", "TASK"],
        ),
    )

    # 3. Pi Agent (Pi Agent Harness via high-performance JSON-RPC)
    register_agent_if_absent(
        name="pi_agent",
        factory_func=lambda descriptor=None: PiURPAgent(
            descriptor=descriptor
            or AgentDescriptor(
                agent_id="vhl.pi.v1",
                name="Pi Coding Agent",
                version="1.0.0",
                description="Autonomous agent powered by the Pi harness with .agents skill discovery.",
                capabilities=["TERMINAL", "FILE_EDITOR", "BASH", "SKILLS"],
                accepted_message_types=["MESSAGE", "TASK"],
            )
        ),
        descriptor=AgentDescriptor(
            agent_id="vhl.pi.v1",
            name="Pi Coding Agent",
            version="1.0.0",
            description="Autonomous agent powered by the Pi harness with .agents skill discovery.",
            capabilities=["TERMINAL", "FILE_EDITOR", "BASH", "SKILLS"],
            accepted_message_types=["MESSAGE", "TASK"],
        ),
    )


# Register standard agents on module load
register_builtin_agents()


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


async def initialize_agent(
    agent_type: str,
    workspace_path: str,
    conversation_id: Optional[str] = None,
    configuration: Optional[Dict[str, Any]] = None,
):
    """
    Initializes and starts a URP agent via the AgentRegistry.
    """
    global host
    if host:
        await host.shutdown()

    # 1. Retrieve agent factory & descriptor from registry
    factory = get_agent_factory(agent_type)
    descriptor = factory.descriptor

    # 2. Instantiate host with factory function
    # Note: URPHost wraps the agent class/factory
    class RegistryBoundAgentFactory:
        def __call__(self, descriptor):
            return create_agent(agent_type, descriptor=descriptor)

    host = URPHost(agent_class=RegistryBoundAgentFactory(), descriptor=descriptor)

    # 3. Build open AgentContext
    abs_workspace = os.path.abspath(workspace_path)
    os.makedirs(abs_workspace, exist_ok=True)

    agent_config = dict(configuration or {})
    agent_config["workspace_path"] = abs_workspace
    agent_config["workspace_dir"] = abs_workspace
    if conversation_id:
        agent_config["conversation_id"] = conversation_id

    context = AgentContext(
        workspace_path=abs_workspace,
        configuration=agent_config,
    )

    # 4. Attach event logger callback
    async def log_event(event: MessageEnvelope):
        event_dict = event.model_dump(mode="json")
        event_log.append(event_dict)

    host.set_emit_callback(log_event)
    await host.initialize_and_start(context)


# ---------------------------------------------------------------------------
# REST Endpoints
# ---------------------------------------------------------------------------

@app.get("/agent/types")
async def list_agent_types():
    """Returns all agent types registered in AgentRegistry."""
    registered = get_registered_agent_types()
    return [
        {
            "id": name,
            "name": desc.name,
            "description": desc.description,
            "version": desc.version,
            "capabilities": desc.capabilities,
            "accepted_message_types": desc.accepted_message_types,
        }
        for name, desc in registered.items()
    ]


@app.post("/agent/init")
async def init_agent(req: InitRequest):
    """Initializes and runs the requested agent type."""
    await initialize_agent(req.agent_type, req.workspace_path, req.conversation_id, req.configuration)
    return {
        "status": "initialized",
        "agent_id": host.descriptor.agent_id if host else "unknown",
        "agent_type": req.agent_type,
    }


@app.post("/agent/message")
async def send_message(req: MessageRequest):
    """Sends a message to the agent's mailbox."""
    if not host:
        return {"error": "Host not running"}
    message_id = await host.send_message(
        message_type=req.message_type,
        payload=req.payload,
        context_id=req.context_id,
        task_id=req.task_id,
    )
    return {"message_id": message_id}


@app.get("/agent/state")
async def get_state():
    """Returns read-only telemetry and state for the active agent."""
    if not host or not host.agent:
        return {"status": "OFFLINE"}

    state = host.agent.state
    # Ensure status string
    if hasattr(state["status"], "value"):
        state["status"] = state["status"].value

    if hasattr(host.agent, "get_conversation_id"):
        state["active_conversation_id"] = host.agent.get_conversation_id()

    if host.descriptor:
        state["agent_name"] = host.descriptor.name
        state["agent_id"] = host.descriptor.agent_id

    if state.get("last_process_result") and hasattr(state["last_process_result"], "model_dump"):
        state["last_process_result"] = state["last_process_result"].model_dump(mode="json")

    return state


@app.get("/agent/conversations")
async def list_conversations(workspace_path: str):
    """Lists saved conversation sessions in the workspace."""
    conv_file = os.path.join(os.path.abspath(workspace_path), ".conversation", "conversation_map.json")
    if os.path.exists(conv_file):
        with open(conv_file, "r") as f:
            try:
                return json.load(f)
            except Exception:
                return []
    return []


@app.get("/agent/conversations/history")
async def get_conversation_history(workspace_path: str, conversation_id: str):
    """Reads reconstructed conversation events from the workspace."""
    base_dir = os.path.join(os.path.abspath(workspace_path), ".conversation")
    events_dir = os.path.join(base_dir, conversation_id, "events")

    if not os.path.exists(events_dir):
        normalized_id = conversation_id.replace("-", "")
        events_dir = os.path.join(base_dir, normalized_id, "events")

    if not os.path.exists(events_dir):
        return []

    history = []
    try:
        event_files = sorted([f for f in os.listdir(events_dir) if f.endswith(".json")])
    except Exception:
        return []

    for filename in event_files:
        try:
            with open(os.path.join(events_dir, filename), "r") as f:
                event = json.load(f)

                if event.get("kind") == "MessageEvent":
                    role = event.get("source", "user")
                    content = event.get("content", [])
                    if not content and "llm_message" in event:
                        content = event.get("llm_message", {}).get("content", [])

                    text_str = ""
                    if content:
                        for item in content:
                            if isinstance(item, dict) and item.get("type") == "text":
                                text_str += item.get("text", "")
                            elif isinstance(item, str):
                                text_str += item
                    elif "text" in event:
                        text_str = event.get("text", "")

                    if text_str:
                        history.append({"role": role, "text": text_str})

                elif event.get("kind") in ("CmdRunEvent", "ObservationEvent") and event.get("tool_name") == "finish":
                    params = event.get("tool_params") or event.get("arguments") or event.get("observation") or {}
                    msg = params.get("message") or ""
                    if msg:
                        history.append({"role": "agent", "text": msg})
        except Exception:
            pass

    return history


@app.post("/agent/conversations/save")
async def save_conversation(req: SaveConversationRequest):
    """Saves the current active conversation ID with a human-readable name."""
    if not host or not host.agent or not hasattr(host.agent, "get_conversation_id"):
        return {"status": "error", "message": "Agent does not support conversation persistence"}

    conv_id = host.agent.get_conversation_id()
    if not conv_id:
        return {"status": "error", "message": "No active conversation ID"}

    conv_dir = os.path.join(os.path.abspath(req.workspace_path), ".conversation")
    os.makedirs(conv_dir, exist_ok=True)
    conv_file = os.path.join(conv_dir, "conversation_map.json")

    conversations = []
    if os.path.exists(conv_file):
        try:
            with open(conv_file, "r") as f:
                conversations = json.load(f)
        except Exception:
            conversations = []

    updated = False
    for conv in conversations:
        if conv["id"] == conv_id:
            conv["name"] = req.name
            updated = True
            break

    if not updated:
        conversations.append({"id": conv_id, "name": req.name})

    with open(conv_file, "w") as f:
        json.dump(conversations, f, indent=2)

    return {"status": "saved", "id": conv_id, "name": req.name}


@app.get("/agent/browse")
async def browse_directory(path: str = "."):
    """Directory picker endpoint for the UI."""
    try:
        abs_path = os.path.abspath(path)
        if not os.path.exists(abs_path):
            return {"error": "Path does not exist"}

        items = [{"name": "..", "path": os.path.dirname(abs_path), "is_dir": True}]
        with os.scandir(abs_path) as it:
            for entry in it:
                if entry.is_dir() and not entry.name.startswith("."):
                    items.append({"name": entry.name, "path": entry.path, "is_dir": True})

        return {
            "current_path": abs_path,
            "items": sorted(items, key=lambda x: x["name"]),
        }
    except Exception as e:
        return {"error": str(e)}


@app.websocket("/ws")
async def websocket_endpoint(websocket: WebSocket):
    """Real-time event streaming websocket."""
    await websocket.accept()
    try:
        while True:
            if not host:
                await asyncio.sleep(0.5)
                continue
            event = await host.get_next_event()
            event_dict = event.model_dump(mode="json")
            await websocket.send_text(json.dumps(event_dict))
    except WebSocketDisconnect:
        pass
    except Exception:
        pass


# ---------------------------------------------------------------------------
# HTML Console UI
# ---------------------------------------------------------------------------

@app.get("/", response_class=HTMLResponse)
async def get_index():
    return """
    <!DOCTYPE html>
    <html lang="en">
        <head>
            <meta charset="UTF-8">
            <meta name="viewport" content="width=device-width, initial-scale=1.0">
            <title>URP-HF | Unified Runtime Primitive Console</title>
            <script src="https://cdn.jsdelivr.net/npm/marked/marked.min.js"></script>
            <style>
                :root {
                    --bg-color: #0b1120;
                    --card-bg: #1e293b;
                    --text-main: #f8fafc;
                    --text-dim: #94a3b8;
                    --primary: #38bdf8;
                    --primary-hover: #0ea5e9;
                    --accent: #10b981;
                    --border: #334155;
                    --console-bg: #020617;
                    --danger: #ef4444;
                    --warning: #f59e0b;
                }
                * { box-sizing: border-box; }
                body { 
                    font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, Oxygen, Ubuntu, Cantarell, sans-serif;
                    margin: 0; 
                    background: var(--bg-color); 
                    color: var(--text-main);
                    display: flex;
                    flex-direction: column;
                    height: 100vh;
                    overflow: hidden;
                }
                header {
                    padding: 0.85rem 1.75rem;
                    background: var(--card-bg);
                    border-bottom: 1px solid var(--border);
                    display: flex;
                    justify-content: space-between;
                    align-items: center;
                }
                header h1 { margin: 0; font-size: 1.15rem; font-weight: 700; color: var(--primary); letter-spacing: -0.025em; }
                header .subtitle { font-size: 0.8rem; color: var(--text-dim); margin-left: 0.5rem; }
                
                main {
                    display: grid;
                    grid-template-columns: 360px 1fr;
                    gap: 0;
                    flex: 1;
                    overflow: hidden;
                }

                #sidebar {
                    background: var(--card-bg);
                    border-right: 1px solid var(--border);
                    padding: 1.25rem;
                    overflow-y: auto;
                    display: flex;
                    flex-direction: column;
                    gap: 1.25rem;
                }

                .config-section h3 { margin-top: 0; font-size: 0.8rem; text-transform: uppercase; color: var(--text-dim); letter-spacing: 0.05em; margin-bottom: 0.75rem; }
                .field-group { display: flex; flex-direction: column; gap: 0.35rem; margin-bottom: 0.85rem; }
                label { font-size: 0.8rem; color: var(--text-dim); font-weight: 500; }
                
                select, input, textarea {
                    background: var(--bg-color);
                    border: 1px solid var(--border);
                    color: var(--text-main);
                    padding: 0.55rem;
                    border-radius: 6px;
                    font-size: 0.85rem;
                    width: 100%;
                }
                select:focus, input:focus, textarea:focus {
                    outline: 2px solid var(--primary);
                    border-color: transparent;
                }

                button {
                    background: var(--primary);
                    color: #0b1120;
                    border: none;
                    padding: 0.55rem 0.9rem;
                    border-radius: 6px;
                    font-weight: 600;
                    cursor: pointer;
                    transition: all 0.15s ease;
                    font-size: 0.85rem;
                }
                button:hover { background: var(--primary-hover); }
                button.secondary { background: var(--border); color: var(--text-main); }
                button.secondary:hover { background: #475569; }
                button.accent { background: var(--accent); color: white; }

                #content {
                    display: flex;
                    flex-direction: column;
                    padding: 1.25rem;
                    gap: 0.85rem;
                    overflow: hidden;
                }

                #status-bar {
                    background: var(--card-bg);
                    padding: 0.65rem 1.25rem;
                    border-radius: 8px;
                    display: flex;
                    justify-content: space-between;
                    align-items: center;
                    border: 1px solid var(--border);
                }
                .status-badge {
                    display: flex;
                    align-items: center;
                    gap: 0.5rem;
                    font-size: 0.85rem;
                    font-weight: 500;
                }
                .dot { width: 10px; height: 10px; border-radius: 50%; background: var(--text-dim); }
                .dot.online { background: var(--accent); box-shadow: 0 0 8px var(--accent); }
                .dot.busy { background: var(--warning); box-shadow: 0 0 8px var(--warning); }
                
                #console {
                    flex: 1;
                    background: var(--console-bg);
                    border-radius: 8px;
                    border: 1px solid var(--border);
                    padding: 1rem;
                    overflow-y: auto;
                    font-family: ui-monospace, SFMono-Regular, Menlo, Monaco, Consolas, monospace;
                    font-size: 0.85rem;
                    line-height: 1.6;
                }
                
                .event { margin-bottom: 0.65rem; border-left: 2px solid var(--border); padding-left: 0.75rem; }
                .event.message { border-left-color: var(--accent); background: rgba(16, 185, 129, 0.05); }
                .event.user-msg { border-left-color: var(--primary); background: rgba(56, 189, 248, 0.05); }
                .event.agent-msg { border-left-color: var(--accent); background: rgba(16, 185, 129, 0.08); }
                .event.error { border-left-color: var(--danger); color: #fca5a5; }
                .event-time { color: var(--text-dim); font-size: 0.75rem; margin-right: 0.5rem; }

                /* Markdown rendering styles */
                .markdown-body { font-size: 0.9rem; line-height: 1.6; }
                .markdown-body h1, .markdown-body h2, .markdown-body h3 { color: var(--primary); margin-top: 0.75rem; margin-bottom: 0.4rem; }
                .markdown-body p { margin-bottom: 0.5rem; }
                .markdown-body code { background: #1e293b; padding: 0.2rem 0.35rem; border-radius: 4px; font-family: monospace; font-size: 0.85em; }
                .markdown-body pre { background: #020617; padding: 0.75rem; border-radius: 6px; overflow-x: auto; border: 1px solid var(--border); }
                .markdown-body pre code { background: transparent; padding: 0; }

                .input-area {
                    display: flex;
                    flex-direction: column;
                    gap: 0.5rem;
                }
                .input-container {
                    display: flex;
                    gap: 0.65rem;
                }
                textarea { resize: none; flex: 1; min-height: 70px; }

                /* Modal styling */
                .modal {
                    display: none;
                    position: fixed;
                    z-index: 1000;
                    left: 0;
                    top: 0;
                    width: 100%;
                    height: 100%;
                    background: rgba(0,0,0,0.7);
                    backdrop-filter: blur(4px);
                }
                .modal-content {
                    background: var(--card-bg);
                    margin: 8% auto;
                    padding: 1.5rem;
                    width: 500px;
                    border-radius: 10px;
                    border: 1px solid var(--border);
                    max-height: 75vh;
                    display: flex;
                    flex-direction: column;
                }
                #dirList { flex: 1; overflow-y: auto; margin: 1rem 0; border: 1px solid var(--border); border-radius: 6px; }
                .dir-item {
                    padding: 0.6rem 0.85rem;
                    cursor: pointer;
                    border-bottom: 1px solid var(--border);
                    display: flex;
                    align-items: center;
                    gap: 0.5rem;
                }
                .dir-item:hover { background: var(--bg-color); }
            </style>
        </head>
        <body>
            <header>
                <div style="display:flex; align-items:center;">
                    <h1>URP-HF</h1>
                    <span class="subtitle">Unified Runtime Primitive Independent Host</span>
                </div>
                <div id="activeConvoInfo" style="display:none; font-size: 0.85rem; color: var(--text-dim);">
                    Session: <span id="activeConvId" style="color: var(--primary); font-family: monospace;"></span>
                </div>
            </header>

            <main>
                <div id="sidebar">
                    <div class="config-section">
                        <h3>Agent Registry</h3>
                        <div class="field-group">
                            <label>Agent Type</label>
                            <select id="agentType" onchange="onAgentTypeChanged()">
                                <option value="echo">Loading agent types...</option>
                            </select>
                            <span id="agentDescription" style="font-size: 0.75rem; color: var(--text-dim); margin-top: 0.25rem;"></span>
                        </div>
                        <div class="field-group">
                            <label>Workspace Path</label>
                            <div style="display: flex; gap: 0.5rem;">
                                <input type="text" id="workspacePath" value="./agent_workspace">
                                <button class="secondary" onclick="openPicker()" title="Browse directory">...</button>
                            </div>
                        </div>
                    </div>

                    <div id="conversationSection" class="config-section" style="display: none;">
                        <h3>Session & History</h3>
                        <div class="field-group">
                            <label>Resume Conversation</label>
                            <select id="resumeConversation" onchange="loadHistory()">
                                <option value="">-- New Session --</option>
                            </select>
                        </div>
                        <button class="secondary" style="width: 100%;" onclick="loadConversations()">Refresh Sessions</button>
                    </div>

                    <div style="margin-top: auto;">
                        <button style="width: 100%; padding: 0.75rem;" onclick="initAgent()">Deploy Agent</button>
                        
                        <div id="saveConvPanel" style="display:none; margin-top: 1rem; padding-top: 1rem; border-top: 1px solid var(--border);">
                            <div class="field-group">
                                <label>Save Snapshot Name</label>
                                <input type="text" id="saveConvName" placeholder="e.g. analysis-checkpoint">
                            </div>
                            <button class="accent" style="width: 100%;" onclick="saveCurrentConversation()">Save Session</button>
                        </div>
                    </div>
                </div>

                <div id="content">
                    <div id="status-bar">
                        <div class="status-badge">
                            <div id="statusDot" class="dot"></div>
                            <span id="statusText">System Initializing</span>
                            <span id="activeAgentBadge" style="margin-left: 0.75rem; padding: 0.2rem 0.5rem; background: var(--border); border-radius: 4px; font-size: 0.75rem; color: var(--primary); display: none;"></span>
                        </div>
                        <div id="mailboxInfo" style="font-size: 0.85rem; color: var(--text-dim);">Mailbox: 0</div>
                    </div>

                    <div id="console"></div>

                    <div class="input-area">
                        <div class="input-container">
                            <textarea id="messageInput" placeholder="Enter message or prompt... (Ctrl+Enter to dispatch)"></textarea>
                            <button onclick="sendMessage()" style="padding: 0 1.25rem;">Send</button>
                        </div>
                    </div>
                </div>
            </main>

            <div id="pickerModal" class="modal">
                <div class="modal-content">
                    <h3 style="margin-top:0;">Select Workspace Directory</h3>
                    <div id="currentBrowsePath" style="font-size: 0.8rem; color: var(--text-dim); word-break: break-all; margin-bottom: 0.5rem;"></div>
                    <div id="dirList"></div>
                    <div style="display: flex; justify-content: flex-end; gap: 0.5rem; margin-top: 1rem;">
                        <button class="secondary" onclick="closePicker()">Cancel</button>
                        <button onclick="selectCurrentDir()">Select Directory</button>
                    </div>
                </div>
            </div>

            <script>
                const consoleDiv = document.getElementById('console');
                const statusText = document.getElementById('statusText');
                const statusDot = document.getElementById('statusDot');
                const mailboxInfo = document.getElementById('mailboxInfo');
                let registeredAgents = [];

                function addLog(msg, type='event') {
                    const div = document.createElement('div');
                    div.className = 'event ' + type;
                    const time = document.createElement('span');
                    time.className = 'event-time';
                    time.textContent = new Date().toLocaleTimeString();
                    div.appendChild(time);
                    
                    const content = document.createElement('div');
                    content.className = 'markdown-body';
                    
                    const rawMsg = typeof msg === 'string' ? msg : JSON.stringify(msg);
                    if (type.includes('message') || type.includes('msg')) {
                        content.innerHTML = marked.parse(rawMsg);
                    } else {
                        content.textContent = rawMsg;
                    }
                    div.appendChild(content);
                    
                    consoleDiv.appendChild(div);
                    consoleDiv.scrollTop = consoleDiv.scrollHeight;
                }

                async function loadAgentTypes() {
                    try {
                        const res = await fetch('/agent/types');
                        registeredAgents = await res.json();
                        const select = document.getElementById('agentType');
                        select.innerHTML = '';
                        registeredAgents.forEach(agent => {
                            const opt = document.createElement('option');
                            opt.value = agent.id;
                            opt.textContent = `${agent.name} (${agent.id})`;
                            select.appendChild(opt);
                        });
                        onAgentTypeChanged();
                    } catch (e) {
                        console.error('Failed loading agent types:', e);
                    }
                }

                function onAgentTypeChanged() {
                    const selId = document.getElementById('agentType').value;
                    const agent = registeredAgents.find(a => a.id === selId);
                    const descSpan = document.getElementById('agentDescription');
                    if (agent && agent.description) {
                        descSpan.textContent = agent.description;
                    } else {
                        descSpan.textContent = '';
                    }
                    
                    const supportsHistory = (selId === 'sdk' || selId === 'pi_agent');
                    document.getElementById('conversationSection').style.display = supportsHistory ? 'block' : 'none';
                }

                async function updateStatus() {
                    try {
                        const res = await fetch('/agent/state');
                        const state = await res.json();
                        
                        statusText.textContent = state.status || 'Offline';
                        mailboxInfo.textContent = `Mailbox: ${state.mailbox_size || 0}`;
                        
                        const agentBadge = document.getElementById('activeAgentBadge');
                        if (state.agent_name) {
                            agentBadge.textContent = state.agent_name;
                            agentBadge.style.display = 'inline-block';
                        } else {
                            agentBadge.style.display = 'none';
                        }

                        statusDot.className = 'dot';
                        if (state.status === 'PROCESSING') statusDot.classList.add('busy');
                        else if (state.status === 'WAITING') statusDot.classList.add('online');
                        else if (state.status === 'ERROR') statusDot.style.background = 'var(--danger)';

                        const activeId = state.active_conversation_id;
                        if (activeId && state.status !== 'OFFLINE') {
                            document.getElementById('activeConvoInfo').style.display = 'block';
                            document.getElementById('saveConvPanel').style.display = 'block';
                            document.getElementById('activeConvId').textContent = activeId.substring(0, 12);
                        } else {
                            document.getElementById('activeConvoInfo').style.display = 'none';
                            document.getElementById('saveConvPanel').style.display = 'none';
                        }
                    } catch (e) {
                        statusText.textContent = 'Connection Error';
                        statusDot.className = 'dot';
                    }
                }

                async function loadConversations() {
                    const workspacePath = document.getElementById('workspacePath').value;
                    const res = await fetch(`/agent/conversations?workspace_path=${encodeURIComponent(workspacePath)}`);
                    const convs = await res.json();
                    const select = document.getElementById('resumeConversation');
                    const curVal = select.value;
                    select.innerHTML = '<option value="">-- New Session --</option>';
                    convs.forEach(c => {
                        const opt = document.createElement('option');
                        opt.value = c.id;
                        opt.textContent = `${c.name} (${c.id.substring(0,8)})`;
                        select.appendChild(opt);
                    });
                    if (curVal) select.value = curVal;
                }

                async function loadHistory() {
                    const conversationId = document.getElementById('resumeConversation').value;
                    const workspacePath = document.getElementById('workspacePath').value;
                    if (!conversationId) return;

                    consoleDiv.innerHTML = '';
                    addLog(`Loading history for session: ${conversationId}...`, 'event');
                    try {
                        const res = await fetch(`/agent/conversations/history?workspace_path=${encodeURIComponent(workspacePath)}&conversation_id=${encodeURIComponent(conversationId)}`);
                        const history = await res.json();
                        history.forEach(item => {
                            addLog(item.text, item.role === 'user' ? 'user-msg' : 'agent-msg');
                        });
                        addLog(`Loaded ${history.length} historical turns.`, 'event');
                    } catch (e) {
                        addLog(`Error loading history: ${e}`, 'error');
                    }
                }

                async function saveCurrentConversation() {
                    const name = document.getElementById('saveConvName').value.trim();
                    const workspacePath = document.getElementById('workspacePath').value;
                    if (!name) { alert('Please enter a session name'); return; }

                    const res = await fetch('/agent/conversations/save', {
                        method: 'POST',
                        headers: { 'Content-Type': 'application/json' },
                        body: JSON.stringify({ name: name, workspace_path: workspacePath })
                    });
                    const data = await res.json();
                    if (data.status === 'saved') {
                        addLog(`Session saved as '${name}'`, 'event');
                        document.getElementById('saveConvName').value = '';
                        loadConversations();
                    } else {
                        alert(data.message || 'Failed to save session');
                    }
                }

                let currentBrowsingPath = ".";
                const pickerModal = document.getElementById('pickerModal');
                const dirList = document.getElementById('dirList');
                const currentBrowsePathDiv = document.getElementById('currentBrowsePath');

                function openPicker() {
                    pickerModal.style.display = 'block';
                    browse(currentBrowsingPath);
                }
                function closePicker() {
                    pickerModal.style.display = 'none';
                }

                async function browse(path) {
                    const res = await fetch(`/agent/browse?path=${encodeURIComponent(path)}`);
                    const data = await res.json();
                    if (data.error) {
                        alert(data.error);
                        return;
                    }
                    currentBrowsingPath = data.current_path;
                    currentBrowsePathDiv.textContent = currentBrowsingPath;
                    dirList.innerHTML = '';
                    data.items.forEach(item => {
                        const div = document.createElement('div');
                        div.className = 'dir-item';
                        div.textContent = (item.is_dir ? '📁 ' : '') + item.name;
                        div.onclick = () => browse(item.path);
                        dirList.appendChild(div);
                    });
                }

                function selectCurrentDir() {
                    document.getElementById('workspacePath').value = currentBrowsingPath;
                    closePicker();
                    loadConversations();
                }

                async function initAgent() {
                    const agentType = document.getElementById('agentType').value;
                    const workspacePath = document.getElementById('workspacePath').value;
                    const conversationId = document.getElementById('resumeConversation').value;

                    addLog(`Deploying ${agentType} agent...`, 'event');
                    const res = await fetch('/agent/init', {
                        method: 'POST',
                        headers: { 'Content-Type': 'application/json' },
                        body: JSON.stringify({
                            agent_type: agentType,
                            workspace_path: workspacePath,
                            conversation_id: conversationId || null
                        })
                    });
                    const data = await res.json();
                    addLog(`Agent deployed: ${data.agent_id} (${agentType})`, 'event');
                    loadConversations();
                    updateStatus();
                }

                async function sendMessage() {
                    const input = document.getElementById('messageInput');
                    const text = input.value.trim();
                    if (!text) return;

                    addLog(text, 'user-msg');
                    input.value = '';
                    await fetch('/agent/message', {
                        method: 'POST',
                        headers: { 'Content-Type': 'application/json' },
                        body: JSON.stringify({ message_type: 'MESSAGE', payload: { text: text } })
                    });
                }

                document.getElementById('messageInput').addEventListener('keydown', function(e) {
                    if (e.key === 'Enter' && (e.ctrlKey || e.metaKey)) {
                        e.preventDefault();
                        sendMessage();
                    }
                });

                function connectWS() {
                    const wsProtocol = window.location.protocol === 'https:' ? 'wss:' : 'ws:';
                    const ws = new WebSocket(`${wsProtocol}//${window.location.host}/ws`);
                    ws.onmessage = function(event) {
                        const data = JSON.parse(event.data);
                        let displayMsg = '';
                        let logType = 'event';

                        if (data.type === 'TASK_COMPLETED' || data.type === 'MESSAGE' || data.type === 'ECHO_RECEIVED') {
                            logType = 'agent-msg';
                            if (data.payload && data.payload.text) {
                                displayMsg = data.payload.text;
                            } else if (typeof data.payload === 'string') {
                                displayMsg = data.payload;
                            } else {
                                displayMsg = JSON.stringify(data.payload);
                            }
                        } else if (data.type === 'AGENT_PROGRESS_UPDATE' || data.type === 'TASK_PROGRESS') {
                            logType = 'event';
                            displayMsg = data.payload?.text || `[Progress] ${JSON.stringify(data.payload)}`;
                        } else {
                            displayMsg = `[${data.type}] ${JSON.stringify(data.payload)}`;
                        }

                        if (displayMsg) {
                            addLog(displayMsg, logType);
                        }
                        updateStatus();
                    };
                    ws.onclose = () => setTimeout(connectWS, 2000);
                }

                // Initial load
                loadAgentTypes();
                connectWS();
                setInterval(updateStatus, 2500);
                setTimeout(loadConversations, 800);
            </script>
        </body>
    </html>
    """
