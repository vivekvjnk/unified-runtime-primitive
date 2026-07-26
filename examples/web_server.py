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
from .asm_agent.asm_agent import ASMURPAgent
from .bdm_agent.bdm_agent import BDMURPAgent
from urp.data_types import AgentDescriptor, AgentContext, MessageEnvelope

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
    elif agent_type == "sdk":
        descriptor = AgentDescriptor(
            agent_id="vhl.sdk_example.v1",
            name="SDK Example Agent",
            version="1.0",
            capabilities=["TERMINAL", "FILE_EDITOR"],
            accepted_message_types=["MESSAGE"]
        )
        host = URPHost(agent_class=SDKURPAgent, descriptor=descriptor)
    elif agent_type == "asm":
        descriptor = AgentDescriptor(
            agent_id="vhl.asm.v1",
            name="ASM Agent",
            version="1.0",
            capabilities=["TERMINAL", "FILE_EDITOR"],
            accepted_message_types=["PROCESS_ARCHITECTURE", "MESSAGE"]
        )
        host = URPHost(agent_class=ASMURPAgent, descriptor=descriptor)
    elif agent_type == "bdm":
        descriptor = AgentDescriptor(
            agent_id="vhl.bdm.v1",
            name="BDM Agent",
            version="1.0",
            capabilities=["TERMINAL", "FILE_EDITOR"],
            accepted_message_types=["PROCESS_BLOCK_DESIGN", "MESSAGE"]
        )
        host = URPHost(agent_class=BDMURPAgent, descriptor=descriptor)
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
    sys_prompt_kwargs = {}
    if agent_type == "asm":
        sys_prompt_kwargs = {
            "workspace_path": os.path.abspath(workspace_path),
            "context_description": "Architectural State Management"
        }

    context = AgentContext(
        configuration={
            "workspace_path": os.path.abspath(workspace_path),
            "conversation_id": conversation_id,
            "system_prompt_kwargs": sys_prompt_kwargs
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

@app.get("/agent/conversations/history")
async def get_conversation_history(workspace_path: str, conversation_id: str):
    base_dir = os.path.join(os.path.abspath(workspace_path), ".conversation")
    events_dir = os.path.join(base_dir, conversation_id, "events")
    
    # Try normalized ID (no dashes) if dashed ID fails
    if not os.path.exists(events_dir):
        normalized_id = conversation_id.replace("-", "")
        events_dir = os.path.join(base_dir, normalized_id, "events")
        print(f"Dashed ID failed, trying normalized: {events_dir}")

    if not os.path.exists(events_dir):
        print(f"History directory not found: {events_dir}")
        return []
    
    history = []
    # List and sort event files
    try:
        event_files = sorted([f for f in os.listdir(events_dir) if f.endswith(".json")])
    except Exception as e:
        print(f"Error listing events dir: {e}")
        return []
    
    for filename in event_files:
        try:
            with open(os.path.join(events_dir, filename), 'r') as f:
                event = json.load(f)
                
                # Check for User messages
                if event.get("kind") == "MessageEvent" and event.get("source") == "user":
                    # Some versions might have it in llm_message, others in content
                    content = event.get("content", [])
                    if not content and "llm_message" in event:
                        content = event.get("llm_message", {}).get("content", [])
                    
                    for item in content:
                        if isinstance(item, dict) and item.get("type") == "text":
                            history.append({"role": "user", "text": item.get("text")})
                        elif isinstance(item, str):
                            history.append({"role": "user", "text": item})
                
                # Check for Agent finish messages (ObservationEvent with tool_name: finish)
                elif event.get("kind") == "ObservationEvent" and event.get("tool_name") == "finish":
                    observation = event.get("observation", {})
                    # Handle both FinishObservation kind and general content
                    content = observation.get("content", [])
                    for item in content:
                        if isinstance(item, dict) and item.get("type") == "text":
                            history.append({"role": "agent", "text": item.get("text")})
                        elif isinstance(item, str):
                            history.append({"role": "agent", "text": item})
        except Exception as e:
            print(f"Error reading event file {filename}: {e}")
            
    return history

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
    <html lang="en">
        <head>
            <meta charset="UTF-8">
            <meta name="viewport" content="width=device-width, initial-scale=1.0">
            <title>URP-HF | Agent Console</title>
            <script src="https://cdn.jsdelivr.net/npm/marked/marked.min.js"></script>
            <style>
                :root {
                    --bg-color: #0f172a;
                    --card-bg: #1e293b;
                    --text-main: #f1f5f9;
                    --text-dim: #94a3b8;
                    --primary: #3b82f6;
                    --primary-hover: #2563eb;
                    --accent: #10b981;
                    --border: #334155;
                    --console-bg: #020617;
                    --danger: #ef4444;
                    --warning: #f59e0b;
                }
                * { box-sizing: border-box; }
                body { 
                    font-family: 'Inter', -apple-system, sans-serif; 
                    margin: 0; 
                    background: var(--bg-color); 
                    color: var(--text-main);
                    display: flex;
                    flex-direction: column;
                    height: 100vh;
                    overflow: hidden;
                }
                header {
                    padding: 1rem 2rem;
                    background: var(--card-bg);
                    border-bottom: 1px solid var(--border);
                    display: flex;
                    justify-content: space-between;
                    align-items: center;
                }
                header h1 { margin: 0; font-size: 1.25rem; font-weight: 600; color: var(--primary); }
                
                main {
                    display: grid;
                    grid-template-columns: 350px 1fr;
                    gap: 0;
                    flex: 1;
                    overflow: hidden;
                }

                #sidebar {
                    background: var(--card-bg);
                    border-right: 1px solid var(--border);
                    padding: 1.5rem;
                    overflow-y: auto;
                    display: flex;
                    flex-direction: column;
                    gap: 1.5rem;
                }

                .config-section h3 { margin-top: 0; font-size: 0.9rem; text-transform: uppercase; color: var(--text-dim); letter-spacing: 0.05em; }
                .field-group { display: flex; flex-direction: column; gap: 0.5rem; margin-bottom: 1rem; }
                label { font-size: 0.85rem; color: var(--text-dim); }
                
                select, input, textarea {
                    background: var(--bg-color);
                    border: 1px solid var(--border);
                    color: var(--text-main);
                    padding: 0.6rem;
                    border-radius: 6px;
                    font-size: 0.9rem;
                    width: 100%;
                }
                select:focus, input:focus, textarea:focus {
                    outline: 2px solid var(--primary);
                    border-color: transparent;
                }

                button {
                    background: var(--primary);
                    color: white;
                    border: none;
                    padding: 0.6rem 1rem;
                    border-radius: 6px;
                    font-weight: 600;
                    cursor: pointer;
                    transition: background 0.2s;
                    font-size: 0.9rem;
                }
                button:hover { background: var(--primary-hover); }
                button.secondary { background: var(--border); color: var(--text-main); }
                button.secondary:hover { background: #475569; }
                button.accent { background: var(--accent); }
                button.danger { background: var(--danger); }

                #content {
                    display: flex;
                    flex-direction: column;
                    padding: 1.5rem;
                    gap: 1rem;
                    overflow: hidden;
                }

                #status-bar {
                    background: var(--card-bg);
                    padding: 0.75rem 1.5rem;
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
                    font-size: 0.9rem;
                    font-weight: 500;
                }
                .dot { width: 10px; height: 10px; border-radius: 50%; background: var(--text-dim); }
                .dot.online { background: var(--accent); box-shadow: 0 0 8px var(--accent); }
                .dot.busy { background: var(--warning); }
                
                #console {
                    flex: 1;
                    background: var(--console-bg);
                    border-radius: 8px;
                    border: 1px solid var(--border);
                    padding: 1rem;
                    overflow-y: auto;
                    font-family: 'Fira Code', 'Cascadia Code', monospace;
                    font-size: 0.85rem;
                    line-height: 1.5;
                }
                
                .event { margin-bottom: 0.5rem; border-left: 2px solid var(--border); padding-left: 0.75rem; }
                .event.message { border-left-color: var(--accent); color: #e2e8f0; }
                .event.user-msg { border-left-color: var(--primary); background: rgba(59, 130, 246, 0.05); }
                .event.agent-msg { border-left-color: var(--accent); background: rgba(16, 185, 129, 0.05); }
                .event.error { border-left-color: var(--danger); color: #fca5a5; }
                .event-time { color: var(--text-dim); font-size: 0.75rem; margin-right: 0.5rem; }

                /* Markdown Styles */
                .markdown-body { font-size: 0.9rem; line-height: 1.6; }
                .markdown-body h1, .markdown-body h2, .markdown-body h3 { color: var(--primary); margin-top: 1rem; margin-bottom: 0.5rem; }
                .markdown-body p { margin-bottom: 0.75rem; }
                .markdown-body code { background: #1e293b; padding: 0.2rem 0.4rem; border-radius: 4px; font-family: monospace; }
                .markdown-body pre { background: #020617; padding: 1rem; border-radius: 6px; overflow-x: auto; border: 1px solid var(--border); }
                .markdown-body pre code { background: transparent; padding: 0; }
                .markdown-body ul, .markdown-body ol { margin-bottom: 0.75rem; padding-left: 1.5rem; }
                .markdown-body blockquote { border-left: 4px solid var(--primary); padding-left: 1rem; color: var(--text-dim); font-style: italic; margin: 1rem 0; }

                #ackArea {
                    background: rgba(245, 158, 11, 0.1);
                    border: 1px solid var(--warning);
                    padding: 0.75rem 1rem;
                    border-radius: 8px;
                    display: flex;
                    justify-content: space-between;
                    align-items: center;
                }

                .input-area {
                    display: flex;
                    flex-direction: column;
                    gap: 0.75rem;
                }
                .input-container {
                    display: flex;
                    gap: 0.75rem;
                }
                textarea { resize: none; flex: 1; min-height: 80px; }

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
                    margin: 5% auto;
                    padding: 2rem;
                    width: 500px;
                    border-radius: 12px;
                    border: 1px solid var(--border);
                    max-height: 80vh;
                    display: flex;
                    flex-direction: column;
                }
                #dirList { flex: 1; overflow-y: auto; margin: 1rem 0; border: 1px solid var(--border); border-radius: 6px; }
                .dir-item {
                    padding: 0.75rem 1rem;
                    cursor: pointer;
                    border-bottom: 1px solid var(--border);
                    display: flex;
                    align-items: center;
                    gap: 0.5rem;
                }
                .dir-item:hover { background: var(--bg-color); }
                .dir-item:last-child { border-bottom: none; }
            </style>
        </head>
        <body>
            <header>
                <h1>URP-HF Console</h1>
                <div id="activeConvoInfo" style="display:none; font-size: 0.85rem; color: var(--text-dim);">
                    Active: <span id="activeConvId" style="color: var(--primary); font-family: monospace;"></span>
                </div>
            </header>

            <main>
                <div id="sidebar">
                    <div class="config-section">
                        <h3>Agent Core</h3>
                        <div class="field-group">
                            <label>Agent Implementation</label>
                            <select id="agentType">
                                <option value="echo">Echo Agent (Standard)</option>
                                <option value="sdk">SDK Agent (OpenHands)</option>
                                <option value="asm">ASM Agent (Architectural State)</option>
                                <option value="bdm">BDM Agent (Block Design)</option>
                            </select>
                        </div>
                        <div class="field-group">
                            <label>Workspace Path</label>
                            <div style="display: flex; gap: 0.5rem;">
                                <input type="text" id="workspacePath" value="./agent_workspace">
                                <button class="secondary" onclick="openPicker()" title="Browse">...</button>
                            </div>
                        </div>
                    </div>

                    <div id="conversationSection" class="config-section" style="display: none;">
                        <h3>History Management</h3>
                        <div class="field-group">
                            <label>Resume From</label>
                            <select id="resumeConversation" onchange="loadHistory()">
                                <option value="">-- Start New --</option>
                            </select>
                        </div>
                        <button class="secondary" style="width: 100%;" onclick="loadConversations()">Refresh History</button>
                    </div>

                    <div style="margin-top: auto;">
                        <button style="width: 100%;" onclick="initAgent()">Deploy Agent</button>
                        
                        <div id="saveConvPanel" style="display:none; margin-top: 1rem; padding-top: 1rem; border-top: 1px solid var(--border);">
                            <div class="field-group">
                                <label>Snapshot Name</label>
                                <input type="text" id="saveConvName" placeholder="e.g. baseline-v1">
                            </div>
                            <button class="accent" style="width: 100%;" onclick="saveCurrentConversation()">Save State</button>
                        </div>
                    </div>
                </div>

                <div id="content">
                    <div id="status-bar">
                        <div class="status-badge">
                            <div id="statusDot" class="dot"></div>
                            <span id="statusText">System Offline</span>
                            <span id="activeAgentBadge" style="margin-left: 1rem; padding: 0.2rem 0.5rem; background: var(--border); border-radius: 4px; font-size: 0.75rem; color: var(--text-dim); display: none;"></span>
                        </div>
                        <div id="mailboxInfo" style="font-size: 0.85rem; color: var(--text-dim);">Mailbox: 0</div>
                    </div>

                    <div id="ackArea" style="display:none;">
                        <span style="font-size: 0.9rem; color: var(--warning);">Task completion pending user acknowledgement.</span>
                        <button class="accent" onclick="acknowledge()">Confirm Outcome</button>
                    </div>

                    <div id="console"></div>

                    <div class="input-area">
                        <div class="input-container">
                            <textarea id="messageInput" placeholder="Enter prompt... (Ctrl+Enter to send)"></textarea>
                            <button onclick="sendMessage()" style="height: auto;">Send</button>
                        </div>
                    </div>
                </div>
            </main>

            <div id="pickerModal" class="modal">
                <div class="modal-content">
                    <h3>Workspace Browser</h3>
                    <div id="currentBrowsePath" style="font-size: 0.8rem; color: var(--text-dim); word-break: break-all; margin-bottom: 0.5rem;"></div>
                    <div id="dirList"></div>
                    <div style="display: flex; justify-content: flex-end; gap: 0.75rem;">
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
                const ackArea = document.getElementById('ackArea');
                
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
                    if (type.includes('message')) {
                        // Render markdown for agent/user messages
                        content.innerHTML = marked.parse(rawMsg);
                    } else {
                        content.textContent = rawMsg;
                    }
                    div.appendChild(content);
                    
                    consoleDiv.appendChild(div);
                    consoleDiv.scrollTop = consoleDiv.scrollHeight;
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
                        if (state.status === 'PROCESSING') statusDot.classList.add('online');
                        else if (state.status === 'WAITING') statusDot.classList.add('busy');
                        else if (state.status === 'ERROR') {
                            statusDot.style.background = 'var(--danger)';
                            statusDot.style.boxShadow = '0 0 8px var(--danger)';
                        }
                        
                        ackArea.style.display = (state.outcome_acknowledged === false) ? 'flex' : 'none';

                        const agentType = document.getElementById('agentType').value;
                        const isComplex = (agentType === 'sdk' || agentType === 'asm' || agentType === 'bdm');
                        document.getElementById('conversationSection').style.display = isComplex ? 'block' : 'none';
                        
                        if (state.status !== 'OFFLINE' && isComplex) {
                            document.getElementById('activeConvoInfo').style.display = 'block';
                            document.getElementById('saveConvPanel').style.display = 'block';
                            document.getElementById('activeConvId').textContent = (state.active_conversation_id || 'new').substring(0, 12);
                        } else {
                            document.getElementById('activeConvoInfo').style.display = 'none';
                            document.getElementById('saveConvPanel').style.display = 'none';
                        }
                    } catch (e) {
                        statusText.textContent = 'Connection Lost';
                        statusDot.className = 'dot danger';
                    }
                }

                async function loadConversations() {
                    const workspacePath = document.getElementById('workspacePath').value;
                    const res = await fetch(`/agent/conversations?workspace_path=${encodeURIComponent(workspacePath)}`);
                    const convs = await res.json();
                    const select = document.getElementById('resumeConversation');
                    const currentValue = select.value;
                    select.innerHTML = '<option value="">-- Start New --</option>';
                    convs.forEach(c => {
                        const opt = document.createElement('option');
                        opt.value = c.id;
                        opt.textContent = `${c.name} (${c.id.substring(0,8)})`;
                        select.appendChild(opt);
                    });
                    if (currentValue) select.value = currentValue;
                }

                async function loadHistory() {
                    const conversationId = document.getElementById('resumeConversation').value;
                    const workspacePath = document.getElementById('workspacePath').value;
                    
                    // Clear console
                    consoleDiv.innerHTML = '';
                    addLog(`Loading history for conversation: ${conversationId || 'New'}...`, 'event');
                    
                    if (!conversationId) return;

                    try {
                        const res = await fetch(`/agent/conversations/history?workspace_path=${encodeURIComponent(workspacePath)}&conversation_id=${conversationId}`);
                        const history = await res.json();
                        
                        history.forEach(item => {
                            if (item.role === 'user') {
                                addLog(item.text, 'message user-msg');
                            } else {
                                addLog(item.text, 'message agent-msg');
                            }
                        });
                        addLog('History loaded.', 'event');
                    } catch (e) {
                        addLog(`Error loading history: ${e.message}`, 'error');
                    }
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
                        document.getElementById('saveConvName').value = '';
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
                        div.innerHTML = `<span>${item.is_dir ? '📁' : '📄'}</span> <span>${item.name}</span>`;
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

                    if (conversationId) {
                        await loadHistory();
                    } else {
                        consoleDiv.innerHTML = '';
                    }

                    addLog(`Deploying ${agentType} agent to ${workspacePath}...`, 'message');
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
                    addLog(`Agent deployed: ${data.agent_id}`);
                    loadConversations();
                    updateStatus();
                }

                async function sendMessage() {
                    const input = document.getElementById('messageInput');
                    const text = input.value.trim();
                    if (!text) return;
                    
                    // If we have an unacknowledged outcome, acknowledge it automatically before sending new message
                    if (ackArea.style.display !== 'none') {
                        addLog('Auto-acknowledging previous outcome...', 'event');
                        await fetch('/agent/acknowledge', { method: 'POST' });
                    }

                    addLog(text, 'message user-msg');
                    input.value = '';
                    try {
                        const res = await fetch('/agent/message', {
                            method: 'POST',
                            headers: { 'Content-Type': 'application/json' },
                            body: JSON.stringify({ message_type: 'MESSAGE', payload: { text: text } })
                        });
                        if (!res.ok) throw new Error('Failed to send message');
                    } catch (e) {
                        addLog(`Error: ${e.message}`, 'error');
                    }
                    updateStatus();
                }

                async function acknowledge() {
                    addLog('Acknowledging task outcome...', 'event');
                    await fetch('/agent/acknowledge', { method: 'POST' });
                    updateStatus();
                    await loadHistory();
                }

                // Keyboard support
                document.getElementById('messageInput').addEventListener('keydown', function(e) {
                    if (e.key === 'Enter' && (e.ctrlKey || e.metaKey)) {
                        sendMessage();
                    }
                });

                // WebSocket for real-time events
                let ws;
                function connectWS() {
                    ws = new WebSocket(`ws://${window.location.host}/ws`);
                    ws.onmessage = function(event) {
                        const data = JSON.parse(event.data);
                        console.log("Received envelope:", data);

                        let displayMsg = "";
                        let logType = "event";

                        const outcomeTypes = ['TASK_COMPLETED', 'TASK_FAILED', 'WAITING_FOR_USER_INPUT', 'TASK_POSTCONDITIONS_VIOLATED', 'TASK_PRECONDITIONS_VIOLATED'];
                        
                        if (outcomeTypes.includes(data.type)) {
                            logType = "message agent-msg";
                            // ProcessResult is the payload
                            const result = data.payload;
                            if (result && result.payload && result.payload.text) {
                                displayMsg = result.payload.text;
                            } else {
                                displayMsg = `Agent reached state: ${data.type}`;
                            }
                        } else if (data.type === "AGENT_PROGRESS") {
                            logType = "event";
                            if (data.payload && data.payload.text) {
                                displayMsg = data.payload.text;
                            } else {
                                displayMsg = "Agent Progress";
                            }
                        } else if (data.payload && typeof data.payload === 'object' && data.payload.text) {
                            displayMsg = data.payload.text;
                        } else if (typeof data.payload === 'string') {
                            displayMsg = data.payload;
                        } else {
                            displayMsg = `${data.type}: ${JSON.stringify(data.payload)}`;
                        }

                        if (displayMsg) {
                            addLog(displayMsg, logType);
                        }
                        updateStatus();
                    };
                    ws.onclose = function() {
                        console.log("WS closed, reconnecting...");
                        setTimeout(connectWS, 2000);
                    };
                    ws.onerror = function(err) {
                        console.error("WS Error:", err);
                        ws.close();
                    };
                }
                connectWS();
                
                setInterval(updateStatus, 2000);
                setTimeout(loadConversations, 500);
                addLog('Connected to URP Runtime Kernel');
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
    
    # Add agent info from host
    if host and host.descriptor:
        state["agent_name"] = host.descriptor.name
        state["agent_id"] = host.descriptor.agent_id

    if state["last_process_result"]:
        # If it's a Pydantic model, use model_dump
        if hasattr(state["last_process_result"], "model_dump"):
            state["last_process_result"] = state["last_process_result"].model_dump(mode='json')
    return state

@app.post("/agent/acknowledge")
async def acknowledge_outcome():
    if host.agent:
        host.agent.acknowledge_outcome()
        return {"status": "acknowledged"}
    return {"status": "error", "message": "Agent not running"}

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
            if not host:
                await asyncio.sleep(1)
                continue
            # We use a separate task to pull from the event queue and push to WS
            event = await host.get_next_event()
            event_dict = event.model_dump(mode='json')
            await websocket.send_text(json.dumps(event_dict))
    except WebSocketDisconnect:
        pass
    except Exception as e:
        print(f"WS Error: {e}")
