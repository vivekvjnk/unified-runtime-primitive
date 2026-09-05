// URP-HF WebHMI Client Logic & A2A Event Streamer

const consoleDiv = document.getElementById('console');
const statusText = document.getElementById('statusText');
const statusDot = document.getElementById('statusDot');
const activeAgentBadge = document.getElementById('activeAgentBadge');
const sidebar = document.getElementById('sidebar');

let registeredAgents = [];
let currentContextId = 'session-' + Math.random().toString(36).substring(2, 10);
let activeStreamCard = null;
let currentStreamText = '';

// Toggle foldable left sidebar
function toggleSidebar() {
    sidebar.classList.toggle('collapsed');
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
    
    const rawMsg = typeof msg === 'string' ? msg : JSON.stringify(msg);
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

// 1. A2A Agent Card Discovery via /.well-known/agent.json
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
        statusDot.className = 'dot';
        if (state.status === 'PROCESSING') statusDot.classList.add('busy');
        else if (state.status === 'WAITING') statusDot.classList.add('online');
        else if (state.status === 'ERROR') statusDot.style.background = 'var(--danger)';

        const activeId = state.active_conversation_id || currentContextId;
        if (activeId && state.status !== 'OFFLINE') {
            document.getElementById('activeConvoInfo').style.display = 'block';
            document.getElementById('saveConvPanel').style.display = 'block';
            document.getElementById('activeConvId').textContent = activeId.substring(0, 14);
        }
    } catch (e) {
        statusText.textContent = 'Connection Error';
    }
}

// 2. Dispatch Task via A2A Streaming Endpoint: POST /message:stream
async function sendMessageA2A() {
    const input = document.getElementById('messageInput');
    const text = input.value.trim();
    if (!text) return;

    addLog(text, 'user-msg');
    input.value = '';
    const sendBtn = document.getElementById('sendBtn');
    sendBtn.disabled = true;

    const taskId = 'task-' + Math.random().toString(36).substring(2, 10);
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
                    contextId: currentContextId,
                    taskId: taskId,
                    parts: [{ text: text, mediaType: 'text/plain' }]
                }
            })
        });

        if (!response.ok) {
            const err = await response.json();
            addLog(`A2A Error: ${err.detail || response.statusText}`, 'error');
            sendBtn.disabled = false;
            updateStatus();
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
        addLog(`Network Error during A2A turn: ${netErr}`, 'error');
    } finally {
        sendBtn.disabled = false;
        updateStatus();
    }
}

// 3. Process Inbound A2A Stream Responses
function handleA2AStreamResponse(resp) {
    if (resp.task) {
        console.log('Task initialized:', resp.task.id);
        return;
    }

    if (resp.statusUpdate) {
        const su = resp.statusUpdate;
        const meta = su.metadata || {};

        // A. Text Delta streaming
        if (meta.is_chunk && su.status?.message) {
            const delta = su.status.message.parts?.[0]?.text || '';
            appendStreamingDelta(delta);
            return;
        }

        // B. Tool Call Event
        if (meta.event_type === 'AGENT_TOOL_START') {
            addToolCallLog(meta.toolName || 'tool', meta.args || {});
            return;
        } else if (meta.event_type === 'AGENT_TOOL_END') {
            return;
        }

        // C. Sub-Task Delegation
        if (meta.event_type === 'TASK_SUBTASK_STARTED') {
            addToolCallLog('delegate', meta.args || meta, '', true);
            return;
        } else if (meta.event_type === 'TASK_SUBTASK_COMPLETED') {
            addLog('Sub-task completed successfully', 'system-info');
            return;
        }

        // D. Terminal States
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

document.getElementById('messageInput').addEventListener('keydown', function(e) {
    if (e.key === 'Enter' && (e.ctrlKey || e.metaKey)) {
        e.preventDefault();
        sendMessageA2A();
    }
});

async function initAgent() {
    const agentType = document.getElementById('agentType').value;
    const workspacePath = document.getElementById('workspacePath').value;
    const conversationId = document.getElementById('resumeConversation').value;

    addLog(`Deploying ${agentType} agent...`, 'system-info');
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
    addLog(`Agent ready: ${data.agent_id}`, 'system-info');
    discoverAgentCard();
    updateStatus();
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
    addLog(`Resumed session: ${conversationId}`, 'system-info');
    currentContextId = conversationId;
    try {
        const res = await fetch(`/agent/conversations/history?workspace_path=${encodeURIComponent(workspacePath)}&conversation_id=${encodeURIComponent(conversationId)}`);
        const history = await res.json();
        history.forEach(item => {
            addLog(item.text, item.role === 'user' ? 'user-msg' : 'agent-msg');
        });
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
        addLog(`Session saved as '${name}'`, 'system-info');
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

// Initial load
loadAgentTypes();
discoverAgentCard();
setInterval(updateStatus, 3000);
setTimeout(loadConversations, 800);
