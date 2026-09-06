// URP-HF Native A2A Web Client & Protocol Console

const consoleDiv = document.getElementById('console');
const statusText = document.getElementById('statusText');
const statusDot = document.getElementById('statusDot');
const activeAgentBadge = document.getElementById('activeAgentBadge');
const sidebar = document.getElementById('sidebar');

// Header status indicators
const headerTaskId = document.getElementById('headerTaskId');
const headerContextId = document.getElementById('headerContextId');

// Modals
const inspectorModal = document.getElementById('inspectorModal');
const inspectorTitle = document.getElementById('inspectorTitle');
const inspectorJson = document.getElementById('inspectorJson');
const pickerModal = document.getElementById('pickerModal');
const dirList = document.getElementById('dirList');
const currentBrowsePathDiv = document.getElementById('currentBrowsePath');

let registeredAgents = [];
let currentContextId = generateId('ctx-');
let currentTaskId = generateId('task-');
let activeStreamCard = null;
let currentStreamText = '';

function generateId(prefix='') {
    return prefix + Math.random().toString(36).substring(2, 10);
}

function updateIdDisplays() {
    headerContextId.textContent = currentContextId.substring(0, 12);
    headerTaskId.textContent = currentTaskId.substring(0, 12);
    const customCtxInput = document.getElementById('customContextId');
    if (customCtxInput && !customCtxInput.value) {
        customCtxInput.placeholder = currentContextId;
    }
    const customTaskInput = document.getElementById('customTaskId');
    if (customTaskInput && !customTaskInput.value) {
        customTaskInput.placeholder = currentTaskId;
    }
}

function resetA2AContext() {
    currentContextId = generateId('ctx-');
    document.getElementById('customContextId').value = '';
    updateIdDisplays();
    addLog(`Initialized new A2A context: ${currentContextId}`, 'system-info');
}

function resetA2ATask() {
    currentTaskId = generateId('task-');
    document.getElementById('customTaskId').value = '';
    document.getElementById('opTaskId').value = currentTaskId;
    updateIdDisplays();
    addLog(`Allocated new A2A task ID: ${currentTaskId}`, 'system-info');
}

// Sidebar toggle
function toggleSidebar() {
    sidebar.classList.toggle('collapsed');
}

function clearConsole() {
    consoleDiv.innerHTML = '';
    addLog('Console cleared', 'system-info');
}

function addLog(msg, type='event') {
    const div = document.createElement('div');
    div.className = 'event ' + type;
    const time = document.createElement('span');
    time.className = 'event-time';
    time.textContent = new Date().toLocaleTimeString();
    div.appendChild(time);
    
    const content = document.createElement('div');
    content.className = 'markdown-body';
    
    const rawMsg = typeof msg === 'string' ? msg : JSON.stringify(msg, null, 2);
    if (type.includes('message') || type.includes('msg')) {
        content.innerHTML = marked.parse(rawMsg);
    } else {
        content.textContent = rawMsg;
    }
    div.appendChild(content);
    
    consoleDiv.appendChild(div);
    consoleDiv.scrollTop = consoleDiv.scrollHeight;
    return div;
}

function getOrCreateStreamingAgentCard() {
    if (!activeStreamCard) {
        activeStreamCard = addLog('', 'agent-msg');
        currentStreamText = '';
    }
    return activeStreamCard;
}

function appendStreamingDelta(delta) {
    const card = getOrCreateStreamingAgentCard();
    currentStreamText += delta;
    const body = card.querySelector('.markdown-body');
    if (body) {
        body.innerHTML = marked.parse(currentStreamText);
    }
    consoleDiv.scrollTop = consoleDiv.scrollHeight;
}

function finalizeStreamingCard(fullText) {
    if (fullText) {
        currentStreamText = fullText;
    }
    if (activeStreamCard) {
        const body = activeStreamCard.querySelector('.markdown-body');
        if (body) {
            body.innerHTML = marked.parse(currentStreamText);
        }
    } else if (fullText) {
        addLog(fullText, 'agent-msg');
    }
    activeStreamCard = null;
    currentStreamText = '';
}

function addToolCallLog(toolName, argsStr, resultStr, isSubtask=false) {
    const details = document.createElement('details');
    details.className = 'tool-call-box';

    const summary = document.createElement('summary');
    const badge = document.createElement('span');
    badge.className = isSubtask ? 'subtask-badge' : 'tool-call-badge';
    badge.textContent = isSubtask ? `subtask: ${toolName}` : `tool: ${toolName}`;
    
    let paramPreview = '';
    if (typeof argsStr === 'object') {
        paramPreview = JSON.stringify(argsStr);
    } else {
        paramPreview = String(argsStr);
    }
    if (paramPreview.length > 60) {
        paramPreview = paramPreview.substring(0, 60) + '...';
    }

    summary.appendChild(badge);
    summary.appendChild(document.createTextNode(` ${paramPreview}`));
    details.appendChild(summary);

    const body = document.createElement('div');
    body.className = 'tool-call-content';
    let formattedContent = `Arguments:\n${typeof argsStr === 'object' ? JSON.stringify(argsStr, null, 2) : argsStr}`;
    if (resultStr) {
        let resFormatted = typeof resultStr === 'object' ? JSON.stringify(resultStr, null, 2) : resultStr;
        const lines = resFormatted.split('\n');
        if (lines.length > 8) {
            resFormatted = lines.slice(0, 8).join('\n') + '\n... (truncated)';
        }
        formattedContent += `\n\nOutput:\n${resFormatted}`;
    }
    body.textContent = formattedContent;
    details.appendChild(body);

    consoleDiv.appendChild(details);
    consoleDiv.scrollTop = consoleDiv.scrollHeight;
}

// ---------------------------------------------------------------------------
// 1. A2A Agent Card Discovery & Catalog
// ---------------------------------------------------------------------------

async function discoverAgentCard() {
    try {
        const res = await fetch('/.well-known/agent.json');
        if (res.ok) {
            const card = await res.json();
            activeAgentBadge.textContent = `${card.name} v${card.version}`;
            activeAgentBadge.style.display = 'inline-block';
            document.getElementById('agentDescription').textContent = card.description;
        }
    } catch (e) {
        console.warn('Agent card discovery deferred:', e);
    }
}

async function inspectAgentCard() {
    try {
        const res = await fetch('/.well-known/agent.json');
        const card = await res.json();
        showInspector('Active Agent Card (/.well-known/agent.json)', card);
    } catch (e) {
        alert('Failed to load Agent Card: ' + e);
    }
}

async function inspectCatalog() {
    try {
        const res = await fetch('/a2a/v1/agents');
        const catalog = await res.json();
        showInspector('A2A Agent Catalog (/a2a/v1/agents)', catalog);
    } catch (e) {
        alert('Failed to load catalog: ' + e);
    }
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
}

// ---------------------------------------------------------------------------
// 2. Dispatch Dispatch Knobs: Stream Turn, Sync Message, Async Task
// ---------------------------------------------------------------------------

async function dispatchA2ATurn() {
    const input = document.getElementById('messageInput');
    const text = input.value.trim();
    if (!text) return;

    // Resolve context and task IDs
    const userCtx = document.getElementById('customContextId').value.trim();
    if (userCtx) currentContextId = userCtx;

    const userTask = document.getElementById('customTaskId').value.trim();
    if (userTask) currentTaskId = userTask;
    else currentTaskId = generateId('task-');

    document.getElementById('opTaskId').value = currentTaskId;
    updateIdDisplays();

    addLog(text, 'user-msg');
    input.value = '';

    const sendBtn = document.getElementById('sendBtn');
    sendBtn.disabled = true;

    // Determine mode
    const mode = document.querySelector('input[name="dispatchMode"]:checked').value;

    if (mode === 'stream') {
        await executeStreamTurn(text, currentContextId, currentTaskId);
    } else if (mode === 'sync') {
        await executeSyncMessage(text, currentContextId, currentTaskId, false);
    } else if (mode === 'async') {
        await executeSyncMessage(text, currentContextId, currentTaskId, true);
    }

    sendBtn.disabled = false;
    updateStatus();
}

// A. Mode: Stream Turn (POST /message:stream)
async function executeStreamTurn(text, contextId, taskId) {
    activeStreamCard = null;
    currentStreamText = '';
    statusDot.className = 'dot busy';
    statusText.textContent = 'A2A Streaming...';

    try {
        const response = await fetch('/message:stream', {
            method: 'POST',
            headers: {
                'Content-Type': 'application/json',
                'Accept': 'text/event-stream'
            },
            body: JSON.stringify({
                message: {
                    role: 'ROLE_USER',
                    contextId: contextId,
                    taskId: taskId,
                    parts: [{ text: text, mediaType: 'text/plain' }]
                }
            })
        });

        if (!response.ok) {
            const err = await response.json();
            addLog(`A2A Error: ${err.detail || response.statusText}`, 'error');
            return;
        }

        const reader = response.body.getReader();
        const decoder = new TextDecoder();
        let buffer = '';

        while (true) {
            const { done, value } = await reader.read();
            if (done) break;

            buffer += decoder.decode(value, { stream: true });
            const lines = buffer.split('\n\n');
            buffer = lines.pop();

            for (const block of lines) {
                if (!block.trim() || block.startsWith(':')) continue;
                const dataLine = block.split('\n').find(l => l.startsWith('data: '));
                if (!dataLine) continue;

                const rawJson = dataLine.substring(6);
                try {
                    const streamResp = JSON.parse(rawJson);
                    handleA2AStreamResponse(streamResp);
                } catch (parseErr) {
                    console.error('Error parsing SSE json:', parseErr, rawJson);
                }
            }
        }
    } catch (netErr) {
        addLog(`Network Error during A2A stream: ${netErr}`, 'error');
    }
}

// B. Mode: Sync / Async Message (POST /message:send)
async function executeSyncMessage(text, contextId, taskId, returnImmediately) {
    statusDot.className = 'dot busy';
    statusText.textContent = returnImmediately ? 'A2A Dispatching...' : 'A2A Executing...';

    try {
        const response = await fetch('/message:send', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({
                message: {
                    role: 'ROLE_USER',
                    contextId: contextId,
                    taskId: taskId,
                    parts: [{ text: text, mediaType: 'text/plain' }]
                },
                configuration: {
                    returnImmediately: returnImmediately
                }
            })
        });

        const data = await response.json();
        if (!response.ok) {
            addLog(`A2A Send Error: ${data.detail || response.statusText}`, 'error');
            return;
        }

        if (data.task) {
            const t = data.task;
            addLog(`Task [${t.id}] Status: ${t.status.state}`, 'system-info');
            if (t.status.message && t.status.message.parts) {
                const responseText = t.status.message.parts.map(p => p.text).filter(Boolean).join('\n');
                if (responseText) {
                    addLog(responseText, 'agent-msg');
                }
            }
        } else if (data.message && data.message.parts) {
            const responseText = data.message.parts.map(p => p.text).filter(Boolean).join('\n');
            addLog(responseText, 'agent-msg');
        }
    } catch (e) {
        addLog(`Error during /message:send: ${e}`, 'error');
    }
}

// C. Stream event handler
function handleA2AStreamResponse(resp) {
    if (resp.task) {
        console.log('Task initialized:', resp.task.id);
        return;
    }

    if (resp.statusUpdate) {
        const su = resp.statusUpdate;
        const meta = su.metadata || {};

        if (meta.is_chunk && su.status?.message) {
            const delta = su.status.message.parts?.[0]?.text || '';
            appendStreamingDelta(delta);
            return;
        }

        if (meta.event_type === 'AGENT_TOOL_START') {
            addToolCallLog(meta.toolName || 'tool', meta.args || {});
            return;
        } else if (meta.event_type === 'AGENT_TOOL_END') {
            return;
        }

        if (meta.event_type === 'TASK_SUBTASK_STARTED') {
            addToolCallLog('delegate', meta.args || meta, '', true);
            return;
        } else if (meta.event_type === 'TASK_SUBTASK_COMPLETED') {
            addLog('Sub-task completed successfully', 'system-info');
            return;
        }

        if (su.status?.state === 'TASK_STATE_COMPLETED') {
            const finalText = su.status.message?.parts?.[0]?.text;
            finalizeStreamingCard(finalText);
        } else if (su.status?.state === 'TASK_STATE_FAILED') {
            const errText = su.status.message?.parts?.[0]?.text || 'Task failed';
            addLog(errText, 'error');
        }
    }

    if (resp.message && resp.message.parts) {
        const text = resp.message.parts.map(p => p.text).filter(Boolean).join('\n');
        finalizeStreamingCard(text);
    }
}

// ---------------------------------------------------------------------------
// 3. A2A Task Operations: Query, Cancel, List, Re-Subscribe
// ---------------------------------------------------------------------------

async function queryTaskStatus() {
    const tid = document.getElementById('opTaskId').value.trim() || currentTaskId;
    if (!tid) { alert('Please enter or select a Task ID'); return; }

    try {
        const res = await fetch(`/tasks/${encodeURIComponent(tid)}`);
        const task = await res.json();
        if (!res.ok) {
            alert(`Task not found: ${task.detail || res.statusText}`);
            return;
        }
        showInspector(`Task Details [${tid}]`, task);
    } catch (e) {
        alert('Failed querying task: ' + e);
    }
}

async function cancelCurrentTask() {
    const tid = document.getElementById('opTaskId').value.trim() || currentTaskId;
    if (!tid) { alert('Please enter or select a Task ID'); return; }

    if (!confirm(`Cancel A2A task '${tid}'?`)) return;

    try {
        const res = await fetch(`/tasks/${encodeURIComponent(tid)}:cancel`, {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ reason: 'Canceled from WebHMI' })
        });
        const task = await res.json();
        if (!res.ok) {
            alert(`Cancellation error: ${task.detail || res.statusText}`);
            return;
        }
        addLog(`Task '${tid}' canceled: ${task.status?.state}`, 'system-info');
        updateStatus();
    } catch (e) {
        alert('Failed canceling task: ' + e);
    }
}

async function listHostTasks() {
    try {
        const res = await fetch('/tasks?limit=20');
        const tasks = await res.json();
        showInspector('A2A Task History (/tasks)', tasks);
    } catch (e) {
        alert('Failed listing tasks: ' + e);
    }
}

async function attachTaskStream() {
    const tid = document.getElementById('opTaskId').value.trim() || currentTaskId;
    if (!tid) { alert('Please enter a Task ID to subscribe to'); return; }

    addLog(`Subscribing to ongoing task stream: ${tid}`, 'system-info');
    activeStreamCard = null;
    currentStreamText = '';

    try {
        const response = await fetch(`/tasks/${encodeURIComponent(tid)}:subscribe`, {
            headers: { 'Accept': 'text/event-stream' }
        });

        if (!response.ok) {
            const err = await response.json();
            alert(`Subscribe failed: ${err.detail || response.statusText}`);
            return;
        }

        const reader = response.body.getReader();
        const decoder = new TextDecoder();
        let buffer = '';

        while (true) {
            const { done, value } = await reader.read();
            if (done) break;

            buffer += decoder.decode(value, { stream: true });
            const lines = buffer.split('\n\n');
            buffer = lines.pop();

            for (const block of lines) {
                if (!block.trim() || block.startsWith(':')) continue;
                const dataLine = block.split('\n').find(l => l.startsWith('data: '));
                if (!dataLine) continue;

                const rawJson = dataLine.substring(6);
                try {
                    const streamResp = JSON.parse(rawJson);
                    handleA2AStreamResponse(streamResp);
                } catch (parseErr) {
                    console.error('Error parsing SSE json:', parseErr, rawJson);
                }
            }
        }
    } catch (e) {
        addLog(`Error subscribing to stream: ${e}`, 'error');
    }
}

// ---------------------------------------------------------------------------
// 4. Modal & Directory Helpers
// ---------------------------------------------------------------------------

function showInspector(title, jsonData) {
    inspectorTitle.textContent = title;
    inspectorJson.textContent = JSON.stringify(jsonData, null, 2);
    inspectorModal.style.display = 'block';
}

function closeInspector() {
    inspectorModal.style.display = 'none';
}

let currentBrowsingPath = ".";
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
}

async function initAgent() {
    const agentType = document.getElementById('agentType').value;
    const workspacePath = document.getElementById('workspacePath').value;

    addLog(`Deploying ${agentType} agent...`, 'system-info');
    const res = await fetch('/agent/init', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
            agent_type: agentType,
            workspace_path: workspacePath
        })
    });
    const data = await res.json();
    addLog(`Agent ready: ${data.agent_id}`, 'system-info');
    discoverAgentCard();
    updateStatus();
}

async function updateStatus() {
    try {
        const res = await fetch('/agent/state');
        const state = await res.json();
        
        statusText.textContent = state.status || 'Offline';
        statusDot.className = 'dot';
        if (state.status === 'PROCESSING') statusDot.classList.add('busy');
        else if (state.status === 'WAITING') statusDot.classList.add('online');
        else if (state.status === 'ERROR') statusDot.style.background = 'var(--danger)';
    } catch (e) {
        statusText.textContent = 'Connection Error';
    }
}

// Keyboard shortcuts
document.getElementById('messageInput').addEventListener('keydown', function(e) {
    if (e.key === 'Enter' && (e.ctrlKey || e.metaKey)) {
        e.preventDefault();
        dispatchA2ATurn();
    }
});

// Initial boot
updateIdDisplays();
loadAgentTypes();
discoverAgentCard();
setInterval(updateStatus, 3000);
