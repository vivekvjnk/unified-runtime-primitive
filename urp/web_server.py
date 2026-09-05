import asyncio
import json
import os
from fastapi import FastAPI, WebSocket, WebSocketDisconnect
from fastapi.responses import HTMLResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel
from typing import Any, List, Optional


from .host import URPHost
from .sample_agent import EchoAgent
from .sdk_agent import SDKURPAgent
from .data_types import AgentDescriptor, AgentContext, MessageEnvelope

app = FastAPI(title="URP Independent Hosting Framework (URP-HF)")

# Global host instance (for demonstration)
host: URPHost = None

def create_host(agent_type: str = "echo"):
    global host
    if agent_type == "echo":
        descriptor = AgentDescriptor(
            agent_id="vhl.echo.v1",
            name="Echo Test Agent",
            version="1.0",
            capabilities=["ECHO"],
            accepted_message_types=["PING", "MESSAGE"]
        )
        host = URPHost(agent_class=EchoAgent, descriptor=descriptor)
    else:
        descriptor = AgentDescriptor(
            agent_id="vhl.sdk_example.v1",
            name="SDK Example Agent",
            version="1.0",
            capabilities=["TERMINAL", "FILE_EDITOR"],
            accepted_message_types=["MESSAGE"]
        )
        host = URPHost(agent_class=SDKURPAgent, descriptor=descriptor)
    return host

# In-memory event log for the UI
event_log: List[dict] = []

class MessageRequest(BaseModel):
    message_type: str
    payload: Any

class InitRequest(BaseModel):
    agent_type: str = "sdk"
    workspace_path: str = "./agent_workspace"
    conversation_id: Optional[str] = None

class SaveConversationRequest(BaseModel):
    name: str
    workspace_path: str

@app.on_event("startup")
async def startup_event():
    await initialize_agent("echo", "./agent_workspace")

async def initialize_agent(agent_type: str, workspace_path: str, conversation_id: str = None):
    global host
    if host:
        await host.shutdown()
    
    create_host(agent_type)
    
    # Initialize the host
    context = AgentContext(
        configuration={
            "workspace_path": os.path.abspath(workspace_path),
            "conversation_id": conversation_id
        }
    )
    
    # Set a callback to log events
    async def log_event(event: MessageEnvelope):
        event_dict = event.model_dump(mode='json')
        event_log.append(event_dict)
        print(f"Event Logged: {event.type}")

    host.set_emit_callback(log_event)
    await host.initialize_and_start(context)

@app.post("/agent/init")
async def init_agent(req: InitRequest):
    await initialize_agent(req.agent_type, req.workspace_path, req.conversation_id)
    return {"status": "initialized", "agent_id": host.descriptor.agent_id}

@app.get("/agent/conversations")
async def list_conversations(workspace_path: str):
    conv_file = os.path.join(os.path.abspath(workspace_path), ".conversation", "conversation_map.json")
    if os.path.exists(conv_file):
        with open(conv_file, 'r') as f:
            return json.load(f)
    return []

@app.post("/agent/conversations/save")
async def save_conversation(req: SaveConversationRequest):
    if not host or not host.agent or not hasattr(host.agent, "get_conversation_id"):
        return {"status": "error", "message": "Agent does not support conversation persistence"}
    
    conv_id = host.agent.get_conversation_id()
    if not conv_id:
        return {"status": "error", "message": "No active conversation"}
    
    conv_dir = os.path.join(os.path.abspath(req.workspace_path), ".conversation")
    os.makedirs(conv_dir, exist_ok=True)
    conv_file = os.path.join(conv_dir, "conversation_map.json")
    
    conversations = []
    if os.path.exists(conv_file):
        with open(conv_file, 'r') as f:
            conversations = json.load(f)
    
    # Check if conv_id already exists, if so update name
    updated = False
    for conv in conversations:
        if conv["id"] == conv_id:
            conv["name"] = req.name
            updated = True
            break
    
    if not updated:
        conversations.append({"id": conv_id, "name": req.name})
    
    with open(conv_file, 'w') as f:
        json.dump(conversations, f, indent=2)
    
    return {"status": "saved", "id": conv_id, "name": req.name}

@app.get("/", response_class=HTMLResponse)
async def get_index():
    return """
    <!DOCTYPE html>
    <html>
        <head>
            <title>URP-HF Console</title>
            <style>
                body { font-family: sans-serif; margin: 20px; background: #f4f4f9; }
                #console { background: #282c34; color: #abb2bf; padding: 15px; height: 400px; overflow-y: scroll; border-radius: 5px; font-family: monospace; }
                .event { margin-bottom: 5px; border-left: 3px solid #61afef; padding-left: 10px; }
                .message { border-left-color: #98c379; }
                .input-area { margin-top: 20px; }
                input, button { padding: 10px; font-size: 16px; }
                input { width: 300px; }
                #status { margin-bottom: 10px; font-weight: bold; }
                .modal { display: none; position: fixed; z-index: 1000; left: 0; top: 0; width: 100%; height: 100%; background: rgba(0,0,0,0.5); }
                .modal-content { background: white; margin: 10% auto; padding: 20px; width: 60%; border-radius: 5px; max-height: 70vh; overflow-y: auto; }
                .dir-item { cursor: pointer; padding: 5px; border-bottom: 1px solid #eee; }
                .dir-item:hover { background: #f0f0f0; }
            </style>
        </head>
        <body>
            <h1>URP Independent Hosting Framework</h1>
            
            <div style="background: #eee; padding: 15px; border-radius: 5px; margin-bottom: 20px;">
                <h3>Agent Configuration</h3>
                <label>Agent Type:</label>
                <select id="agentType">
                    <option value="echo">Echo Agent (Built-in)</option>
                    <option value="sdk">SDK Agent (OpenHands SDK)</option>
                </select>
                    <label>Workspace Path:</label>
                    <input type="text" id="workspacePath" value="./agent_workspace" style="width: 200px;">
                    <button onclick="openPicker()">Browse...</button>
                    
                    <div id="conversationSection" style="margin-top: 10px; display: none;">
                        <label>Resume Conversation:</label>
                        <select id="resumeConversation">
                            <option value="">-- New Conversation --</option>
                        </select>
                        <button onclick="loadConversations()">Refresh List</button>
                    </div>

                    <div style="margin-top: 10px;">
                        <button onclick="initAgent()">Initialize/Restart Agent</button>
                    </div>
                </div>

                <div id="activeConvoSection" style="background: #e7f3ff; padding: 10px; border-radius: 5px; margin-bottom: 20px; display: none;">
                    <strong>Active Conversation:</strong> <span id="activeConvId">None</span>
                    <input type="text" id="saveConvName" placeholder="Conversation Name">
                    <button onclick="saveCurrentConversation()">Save Conversation</button>
                </div>

            <div id="pickerModal" class="modal">
                <div class="modal-content">
                    <h3>Select Workspace Directory</h3>
                    <div id="currentBrowsePath" style="font-weight: bold; margin-bottom: 10px;"></div>
                    <div id="dirList"></div>
                    <div style="margin-top: 20px;">
                        <button onclick="closePicker()">Cancel</button>
                        <button onclick="selectCurrentDir()">Select Current Directory</button>
                    </div>
                </div>
            </div>

            <div class="status" id="status">Agent Status: Starting...</div>
            <div id="console"></div>
            <div class="input-area">
                <input type="text" id="messageInput" placeholder="Enter message to agent...">
                <button onclick="sendMessage()">Send to Agent</button>
            </div>

            <script>
                const consoleDiv = document.getElementById('console');
                const statusDiv = document.getElementById('status');
                
                function addLog(msg, type='event') {
                    const div = document.createElement('div');
                    div.className = 'event ' + type;
                    div.textContent = `[${new Date().toLocaleTimeString()}] ${msg}`;
                    consoleDiv.appendChild(div);
                    consoleDiv.scrollTop = consoleDiv.scrollHeight;
                }

                async function updateStatus() {
                    const res = await fetch('/agent/state');
                    const state = await res.json();
                    statusDiv.textContent = `Agent Status: ${state.status} | Mailbox: ${state.mailbox_size}`;

                    // Update agent UI visibility based on type
                    const agentType = document.getElementById('agentType').value;
                    document.getElementById('conversationSection').style.display = agentType === 'sdk' ? 'block' : 'none';
                    
                    if (state.status !== 'OFFLINE' && agentType === 'sdk') {
                        document.getElementById('activeConvoSection').style.display = 'block';
                        document.getElementById('activeConvId').textContent = state.active_conversation_id || 'None';
                    } else {
                        document.getElementById('activeConvoSection').style.display = 'none';
                    }
                }

                async function loadConversations() {
                    const workspacePath = document.getElementById('workspacePath').value;
                    const res = await fetch(`/agent/conversations?workspace_path=${encodeURIComponent(workspacePath)}`);
                    const convs = await res.json();
                    const select = document.getElementById('resumeConversation');
                    select.innerHTML = '<option value="">-- New Conversation --</option>';
                    convs.forEach(c => {
                        const opt = document.createElement('option');
                        opt.value = c.id;
                        opt.textContent = `${c.name} (${c.id.substring(0,8)})`;
                        select.appendChild(opt);
                    });
                }

                async function saveCurrentConversation() {
                    const name = document.getElementById('saveConvName').value;
                    const workspacePath = document.getElementById('workspacePath').value;
                    if (!name) { alert('Please enter a name'); return; }
                    
                    const res = await fetch('/agent/conversations/save', {
                        method: 'POST',
                        headers: { 'Content-Type': 'application/json' },
                        body: JSON.stringify({ name: name, workspace_path: workspacePath })
                    });
                    const data = await res.json();
                    if (data.status === 'saved') {
                        addLog(`Conversation saved as: ${name}`);
                        loadConversations();
                    } else {
                        alert(data.message);
                    }
                }

                let currentBrowsingPath = ".";
                const pickerModal = document.getElementById('pickerModal');
                const dirList = document.getElementById('dirList');
                const currentBrowsePathDiv = document.getElementById('currentBrowsePath');

                async function openPicker() {
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
                        div.onclick = () => { browse(item.path); };
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

                    addLog(`Initializing ${agentType} agent at ${workspacePath}...`, 'message');
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
                    addLog(`Agent initialized: ${data.agent_id}`);
                    
                    // After initialization, if it's an SDK agent, we want to know the active ID
                    if (agentType === 'sdk') {
                        // The active ID is now included in the state
                        loadConversations();
                    }
                    updateStatus();
                }

                async function sendMessage() {
                    const input = document.getElementById('messageInput');
                    const text = input.value;
                    if (!text) return;
                    
                    addLog(`Sending: ${text}`, 'message');
                    const res = await fetch('/agent/message', {
                        method: 'POST',
                        headers: { 'Content-Type': 'application/json' },
                        body: JSON.stringify({ message_type: 'MESSAGE', payload: { text: text } })
                    });
                    input.value = '';
                }

                // WebSocket for real-time events
                const ws = new WebSocket(`ws://${window.location.host}/ws`);
                ws.onmessage = function(event) {
                    const data = JSON.parse(event.data);
                    addLog(`Event Received: ${data.type} - ${JSON.stringify(data.payload)}`);
                    updateStatus();
                };
                
                setInterval(updateStatus, 2000);
                setTimeout(loadConversations, 500); // Load initial list
                addLog('Connecting to URP Runtime Kernel...');
            </script>
        </body>
    </html>
    """

@app.post("/agent/message")
async def send_message(req: MessageRequest):
    message_id = await host.send_message(req.message_type, req.payload)
    return {"message_id": message_id}

@app.get("/agent/state")
async def get_state():
    if not host or not host.agent:
        return {"status": "OFFLINE"}
    # Manually serialize to ensure Enums are strings
    state = host.agent.state
    state["status"] = state["status"].value
    
    # Add active conversation ID if available
    if hasattr(host.agent, "get_conversation_id"):
        state["active_conversation_id"] = host.agent.get_conversation_id()
    
    if state["last_process_result"]:
        # If it's a Pydantic model, use model_dump
        if hasattr(state["last_process_result"], "model_dump"):
            state["last_process_result"] = state["last_process_result"].model_dump(mode='json')
    return state

@app.get("/agent/browse")
async def browse_directory(path: str = "."):
    try:
        abs_path = os.path.abspath(path)
        if not os.path.exists(abs_path):
            return {"error": "Path does not exist"}
        
        items = []
        # Add parent directory
        parent = os.path.dirname(abs_path)
        items.append({"name": "..", "path": parent, "is_dir": True})
        
        with os.scandir(abs_path) as it:
            for entry in it:
                if entry.is_dir() and not entry.name.startswith('.'):
                    items.append({
                        "name": entry.name,
                        "path": entry.path,
                        "is_dir": True
                    })
        
        return {
            "current_path": abs_path,
            "items": sorted(items, key=lambda x: x["name"])
        }
    except Exception as e:
        return {"error": str(e)}

@app.websocket("/ws")
async def websocket_endpoint(websocket: WebSocket):
    await websocket.accept()
    try:
        while True:
            # We use a separate task to pull from the event queue and push to WS
            event = await host.get_next_event()
            event_dict = event.model_dump(mode='json')
            await websocket.send_text(json.dumps(event_dict))
    except WebSocketDisconnect:
        pass
