// URP-HF Native A2A Web Client & Multi-Agent Protocol Console

const consoleDiv = document.getElementById('console');
const statusText = document.getElementById('statusText');
const statusDot = document.getElementById('statusDot');
const activeAgentBadge = document.getElementById('activeAgentBadge');
const sidebar = document.getElementById('sidebar');

// Header status indicators
const headerTaskId = document.getElementById('headerTaskId');
const headerContextId = document.getElementById('headerContextId');

// Multi-Agent Tab Bar
const agentTabsContainer = document.getElementById('agentTabsContainer');
const workspaceAgentsNotice = document.getElementById('workspaceAgentsNotice');
const workspaceAgentsText = document.getElementById('workspaceAgentsText');

// Modals
const inspectorModal = document.getElementById('inspectorModal');
const inspectorTitle = document.getElementById('inspectorTitle');
const inspectorJson = document.getElementById('inspectorJson');
const pickerModal = document.getElementById('pickerModal');
const dirList = document.getElementById('dirList');
const currentBrowsePathDiv = document.getElementById('currentBrowsePath');
const createAgentModal = document.getElementById('createAgentModal');

// Multi-Agent State Tracking
let registeredAgents = [];
let runningAgents = [];
let currentActiveAgent = null; // Agent name/id

// Isolated conversation state per agent
// Map: agent_name -> { contextId, taskId, logs: [HTML elements/snapshots] }
const agentSessions = {};

let currentContextId = generateId('ctx-');
let currentTaskId = generateId('task-');
let activeStreamCard = null;
let currentStreamText = '';

// Active tools grouped container for current turn
let activeToolsGroup = null;
let activeToolsCount = 0;

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
    if (currentActiveAgent && agentSessions[currentActiveAgent]) {
        agentSessions[currentActiveAgent].contextId = currentContextId;
    }
    updateIdDisplays();
    addLog(`Initialized new A2A context: ${currentContextId}`, 'system-info');
}

function resetA2ATask() {
    currentTaskId = generateId('task-');
    document.getElementById('customTaskId').value = '';
    document.getElementById('opTaskId').value = currentTaskId;
    if (currentActiveAgent && agentSessions[currentActiveAgent]) {
        agentSessions[currentActiveAgent].taskId = currentTaskId;
    }
    updateIdDisplays();
    addLog(`Allocated new A2A task ID: ${currentTaskId}`, 'system-info');
}

// Sidebar toggle
function toggleSidebar() {
    sidebar.classList.toggle('collapsed');
}

function clearConsole() {
    consoleDiv.innerHTML = '';
    if (currentActiveAgent && agentSessions[currentActiveAgent]) {
        agentSessions[currentActiveAgent].logs = [];
    }
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

    // Save snapshot to active agent's isolated session history
    if (currentActiveAgent) {
        if (!agentSessions[currentActiveAgent]) {
            agentSessions[currentActiveAgent] = {
                contextId: currentContextId,
                taskId: currentTaskId,
                logs: [],
            };
        }
        agentSessions[currentActiveAgent].logs.push(div.cloneNode(true));
    }

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
        consoleDiv.appendChild(activeStreamCard);

        // Update stored clone in active agent's history
        if (currentActiveAgent && agentSessions[currentActiveAgent]) {
            const logs = agentSessions[currentActiveAgent].logs;
            if (logs.length > 0) {
                logs[logs.length - 1] = activeStreamCard.cloneNode(true);
            }
        }
    } else if (fullText) {
        addLog(fullText, 'agent-msg');
    }
    activeStreamCard = null;
    currentStreamText = '';
    activeToolsGroup = null;
    activeToolsCount = 0;
}

function getOrCreateToolsGroup() {
    if (!activeToolsGroup) {
        const details = document.createElement('details');
        details.className = 'tools-group-box';

        const summary = document.createElement('summary');
        summary.className = 'tools-group-summary';

        const countBadge = document.createElement('span');
        countBadge.className = 'tools-group-count';
        countBadge.textContent = '1 tool';

        const textSpan = document.createElement('span');
        textSpan.textContent = 'Tools & Operations';

        summary.appendChild(countBadge);
        summary.appendChild(textSpan);
        details.appendChild(summary);

        const body = document.createElement('div');
        body.className = 'tools-group-body';
        details.appendChild(body);

        if (activeStreamCard && activeStreamCard.parentNode === consoleDiv) {
            consoleDiv.insertBefore(details, activeStreamCard);
        } else {
            consoleDiv.appendChild(details);
        }

        activeToolsGroup = details;
        activeToolsCount = 0;
    }
    return activeToolsGroup;
}

function updateToolsGroupHeader() {
    if (!activeToolsGroup) return;
    const countBadge = activeToolsGroup.querySelector('.tools-group-count');
    if (countBadge) {
        countBadge.textContent = `${activeToolsCount} tool${activeToolsCount === 1 ? '' : 's'}`;
    }
}

function addToolCallLog(toolName, argsStr, resultStr, isSubtask=false) {
    const group = getOrCreateToolsGroup();
    activeToolsCount += 1;
    updateToolsGroupHeader();

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

    const groupBody = group.querySelector('.tools-group-body');
    if (groupBody) {
        groupBody.appendChild(details);
    } else {
        group.appendChild(details);
    }

    if (activeStreamCard && activeStreamCard.parentNode === consoleDiv) {
        consoleDiv.appendChild(activeStreamCard);
    }
    consoleDiv.scrollTop = consoleDiv.scrollHeight;
}

// ---------------------------------------------------------------------------
// 1. Multi-Agent Roster & Interactive Tab Bar
// ---------------------------------------------------------------------------

async function refreshActiveAgents() {
    try {
        const res = await fetch('/agent/active');
        if (!res.ok) return;
        const data = await res.json();
        
        currentActiveAgent = data.active_agent_name;
        runningAgents = data.running_agents || [];

        renderAgentTabs();
        updateActiveAgentBadge();
    } catch (e) {
        console.warn('Failed refreshing active agents:', e);
    }
}

function renderAgentTabs() {
    if (!agentTabsContainer) return;
    agentTabsContainer.innerHTML = '';

    if (runningAgents.length === 0) {
        const emptySpan = document.createElement('span');
        emptySpan.style.fontSize = '0.75rem';
        emptySpan.style.color = 'var(--text-dim)';
        emptySpan.textContent = 'No agents running';
        agentTabsContainer.appendChild(emptySpan);
        return;
    }

    runningAgents.forEach(agent => {
        const pill = document.createElement('div');
        pill.className = 'agent-tab-pill' + (agent.is_active ? ' active' : '');
        pill.title = `${agent.agent_name} (${agent.status})\n${agent.description || ''}`;

        const dot = document.createElement('span');
        dot.className = 'agent-status-mini-dot';
        if (agent.status === 'PROCESSING') dot.classList.add('busy');
        else if (agent.status !== 'WAITING' && agent.status !== 'INITIALIZED') dot.classList.add('offline');

        const nameSpan = document.createElement('span');
        nameSpan.textContent = agent.agent_name;

        pill.appendChild(dot);
        pill.appendChild(nameSpan);

        // Add a small inline close/stop button (✕)
        const closeBtn = document.createElement('span');
        closeBtn.innerHTML = '&times;';
        closeBtn.className = 'agent-tab-close-btn';
        closeBtn.title = `Stop agent ${agent.agent_name}`;
        closeBtn.onclick = (e) => {
            e.stopPropagation();
            stopSpecificAgent(agent.agent_name);
        };
        pill.appendChild(closeBtn);

        pill.onclick = () => switchActiveAgent(agent.agent_name);
        agentTabsContainer.appendChild(pill);
    });
}

async function stopActiveAgent() {
    if (!currentActiveAgent) {
        alert('No active agent is running.');
        return;
    }
    await stopSpecificAgent(currentActiveAgent);
}

async function stopSpecificAgent(agentName) {
    if (!confirm(`Are you sure you want to stop agent '${agentName}'?`)) {
        return;
    }

    addLog(`Stopping agent ${agentName}...`, 'system-info');
    try {
        const res = await fetch('/agent/stop', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ agent_name: agentName })
        });
        if (!res.ok) {
            const err = await res.json();
            alert('Failed stopping agent: ' + (err.detail || res.statusText));
            return;
        }

        const data = await res.json();
        addLog(`Agent ${agentName} has been stopped.`, 'system-info');

        currentActiveAgent = data.active_agent_name;
        runningAgents = data.running_agents || [];

        renderAgentTabs();
        updateActiveAgentBadge();

        if (currentActiveAgent) {
            await switchActiveAgent(currentActiveAgent);
        } else {
            consoleDiv.innerHTML = '';
            addLog('All agents stopped. Ready to deploy an agent.', 'system-info');
            updateStatus();
        }
    } catch (e) {
        console.error('Error stopping agent:', e);
        alert('Error stopping agent: ' + e);
    }
}

async function switchActiveAgent(agentName) {
    if (agentName === currentActiveAgent) return;

    try {
        const res = await fetch('/agent/switch', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ agent_name: agentName })
        });
        if (!res.ok) {
            const err = await res.json();
            alert('Failed switching agent: ' + (err.detail || res.statusText));
            return;
        }

        currentActiveAgent = agentName;

        // Restore or initialize session conversation for switched agent
        consoleDiv.innerHTML = '';
        if (!agentSessions[agentName]) {
            agentSessions[agentName] = {
                contextId: generateId('ctx-'),
                taskId: generateId('task-'),
                logs: [],
            };
            addLog(`Switched focus to agent: ${agentName}`, 'system-info');
        } else {
            // Restore isolated logs
            agentSessions[agentName].logs.forEach(l => consoleDiv.appendChild(l.cloneNode(true)));
            consoleDiv.scrollTop = consoleDiv.scrollHeight;
        }

        currentContextId = agentSessions[agentName].contextId;
        currentTaskId = agentSessions[agentName].taskId;
        updateIdDisplays();

        await refreshActiveAgents();
        discoverAgentCard(agentName);
        updateStatus();
    } catch (e) {
        console.error('Error switching agent:', e);
    }
}

function updateActiveAgentBadge() {
    if (!currentActiveAgent) {
        activeAgentBadge.style.display = 'none';
        return;
    }
    activeAgentBadge.textContent = currentActiveAgent;
    activeAgentBadge.style.display = 'inline-block';
}

// ---------------------------------------------------------------------------
// 2. A2A Agent Card Discovery & Catalog
// ---------------------------------------------------------------------------

async function discoverAgentCard(agentName=null) {
    try {
        const url = agentName ? `/.well-known/agent.json?agent_name=${encodeURIComponent(agentName)}` : '/.well-known/agent.json';
        const res = await fetch(url);
        if (res.ok) {
            const card = await res.json();
            activeAgentBadge.textContent = `${card.name} v${card.version}`;
            activeAgentBadge.style.display = 'inline-block';
            document.getElementById('agentDescription').textContent = card.description || '';
        }
    } catch (e) {
        console.warn('Agent card discovery deferred:', e);
    }
}

async function inspectAgentCard() {
    try {
        const target = currentActiveAgent || '';
        const url = target ? `/.well-known/agent.json?agent_name=${encodeURIComponent(target)}` : '/.well-known/agent.json';
        const res = await fetch(url);
        const card = await res.json();
        showInspector(`Agent Card: ${card.name}`, card);
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
    const select = document.getElementById('agentType');
    try {
        const res = await fetch('/agent/types');
        if (!res.ok) {
            console.error('Failed fetching /agent/types:', res.statusText);
            if (select) select.innerHTML = '<option value="">Error loading agents</option>';
            return;
        }
        registeredAgents = await res.json();
        if (select) {
            select.innerHTML = '';
            registeredAgents.forEach(agent => {
                const opt = document.createElement('option');
                opt.value = agent.id;
                opt.textContent = `${agent.name} (${agent.id})`;
                select.appendChild(opt);
            });
            onAgentTypeChanged();
        }
    } catch (e) {
        console.error('Failed loading agent types:', e);
        if (select) select.innerHTML = '<option value="">Failed loading agents</option>';
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

async function onWorkspacePathChanged() {
    const path = document.getElementById('workspacePath').value.trim();
    if (!path) return;
    try {
        const res = await fetch(`/workspace/agents?path=${encodeURIComponent(path)}`);
        if (!res.ok) return;
        const discovered = await res.json();
        if (discovered && discovered.length > 0) {
            const names = discovered.map(d => d.agent_name).join(', ');
            workspaceAgentsText.textContent = `Found ${discovered.length} workspace agent(s) in .well_known: ${names}`;
            workspaceAgentsNotice.style.display = 'block';
            await loadAgentTypes();
        } else {
            workspaceAgentsNotice.style.display = 'none';
        }
    } catch (e) {
        console.warn('Workspace agent scan error:', e);
    }
}

// ---------------------------------------------------------------------------
// 3. Dynamic Agent Creation Modal & Normalization
// ---------------------------------------------------------------------------

function openCreateAgentModal() {
    const ws = document.getElementById('workspacePath').value;
    document.getElementById('createAgentWorkspace').value = ws;
    createAgentModal.style.display = 'block';
    document.getElementById('createAgentName').focus();
}

function closeCreateAgentModal() {
    createAgentModal.style.display = 'none';
    document.getElementById('createAgentForm').reset();
}

/**
 * Real-time normalization for agent name input:
 * - Automatically converts spaces and hyphens to underscores
 * - Strips characters other than [a-z0-9_]
 * - Lowercases input
 */
function onAgentNameInput(inputElement) {
    const cursor = inputElement.selectionStart;
    const original = inputElement.value;
    const normalized = original
        .toLowerCase()
        .replace(/[\s-]+/g, '_')
        .replace(/[^a-z0-9_]/g, '')
        .replace(/_+/g, '_');

    inputElement.value = normalized;
    inputElement.setSelectionRange(cursor, cursor);
}

function onCreateHarnessChanged() {
    const harness = document.getElementById('createAgentHarness').value;
    const promptArea = document.getElementById('createAgentPrompt');
    if (harness === 'pi' && !promptArea.value) {
        promptArea.placeholder = 'You are an expert AI software engineering agent. You have access to bash, read, edit, and write tools. Follow instructions carefully.';
    } else if (harness === 'echo') {
        promptArea.placeholder = 'Diagnostic echo agent for verifying message streams and telemetry.';
    } else if (harness === 'sdk') {
        promptArea.placeholder = 'Autonomous software agent using OpenHands SDK terminal and file tools.';
    }
}

async function handleCreateAgentSubmit(event) {
    event.preventDefault();

    const nameInput = document.getElementById('createAgentName');
    const agentName = nameInput.value.trim();
    if (!agentName) {
        alert('Please specify a valid Agent Name');
        return;
    }

    const submitBtn = document.getElementById('createAgentSubmitBtn');
    submitBtn.disabled = true;
    submitBtn.textContent = 'Deploying...';

    try {
        const formData = new FormData();
        formData.append('agent_name', agentName);
        formData.append('workspace_path', document.getElementById('createAgentWorkspace').value.trim());
        formData.append('description', document.getElementById('createAgentDesc').value.trim());
        formData.append('system_prompt', document.getElementById('createAgentPrompt').value.trim());
        formData.append('harness', document.getElementById('createAgentHarness').value);
        formData.append('thinking_level', document.getElementById('createAgentThinking').value);

        const ecpDir = document.getElementById('createAgentEcpDir').value.trim();
        if (ecpDir) {
            formData.append('ecp_dir', ecpDir);
        }

        const ecpFileInput = document.getElementById('createAgentEcpFile');
        if (ecpFileInput.files && ecpFileInput.files.length > 0) {
            formData.append('ecp_file', ecpFileInput.files[0]);
        }

        const res = await fetch('/agent/create', {
            method: 'POST',
            body: formData,
        });

        if (!res.ok) {
            const err = await res.json();
            throw new Error(err.detail || res.statusText);
        }

        const result = await res.json();
        addLog(`Successfully authored & deployed agent: ${result.agent_name}`, 'system-info');
        if (result.extracted_skills && result.extracted_skills.length > 0) {
            const skNames = result.extracted_skills.map(s => s.skill_name).join(', ');
            addLog(`Ingested ECP skill(s): ${skNames}`, 'system-info');
        }

        closeCreateAgentModal();
        await refreshActiveAgents();
        await loadAgentTypes();
        await switchActiveAgent(result.agent_name);
    } catch (err) {
        alert('Agent Creation Error: ' + err.message);
    } finally {
        submitBtn.disabled = false;
        submitBtn.textContent = 'Create & Deploy Agent';
    }
}

// ---------------------------------------------------------------------------
// 4. Dispatch Knobs: Stream Turn, Sync Message, Async Task
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
    activeToolsGroup = null;
    activeToolsCount = 0;
    statusDot.className = 'dot busy';
    statusText.textContent = 'A2A Streaming...';

    const targetParam = currentActiveAgent ? `?agent_name=${encodeURIComponent(currentActiveAgent)}` : '';
    const headers = {
        'Content-Type': 'application/json',
        'Accept': 'text/event-stream'
    };
    if (currentActiveAgent) {
        headers['X-Target-Agent'] = currentActiveAgent;
    }

    try {
        const response = await fetch(`/message:stream${targetParam}`, {
            method: 'POST',
            headers: headers,
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
    activeToolsGroup = null;
    activeToolsCount = 0;
    statusDot.className = 'dot busy';
    statusText.textContent = returnImmediately ? 'A2A Dispatching...' : 'A2A Executing...';

    const targetParam = currentActiveAgent ? `?agent_name=${encodeURIComponent(currentActiveAgent)}` : '';
    const headers = { 'Content-Type': 'application/json' };
    if (currentActiveAgent) {
        headers['X-Target-Agent'] = currentActiveAgent;
    }

    try {
        const response = await fetch(`/message:send${targetParam}`, {
            method: 'POST',
            headers: headers,
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

        if (!response.ok) {
            const err = await response.json();
            addLog(`A2A Error: ${err.detail || response.statusText}`, 'error');
            return;
        }

        const sendResp = await response.json();
        if (returnImmediately) {
            addLog(`Task submitted asynchronously: ${sendResp.task ? sendResp.task.id : taskId}`, 'system-info');
            if (sendResp.task) {
                addLog(`State: ${sendResp.task.status.state}`, 'system-info');
            }
        } else {
            if (sendResp.task && sendResp.task.status) {
                const finalState = sendResp.task.status.state;
                const msg = sendResp.task.status.message;
                const outText = msg && msg.parts && msg.parts[0] ? msg.parts[0].text : `Task finished with state: ${finalState}`;
                addLog(outText, finalState === 'TASK_STATE_FAILED' ? 'error' : 'agent-msg');
            } else if (sendResp.message && sendResp.message.parts) {
                addLog(sendResp.message.parts[0].text, 'agent-msg');
            }
        }
    } catch (e) {
        addLog(`Sync dispatch error: ${e}`, 'error');
    }
}

// Handler for all streaming events
function handleA2AStreamResponse(streamResp) {
    if (streamResp.message) {
        const text = streamResp.message.parts && streamResp.message.parts[0] ? streamResp.message.parts[0].text : '';
        if (text) {
            finalizeStreamingCard(text);
        }
        return;
    }

    if (streamResp.statusUpdate) {
        const su = streamResp.statusUpdate;
        const state = su.status ? su.status.state : 'WORKING';

        if (su.metadata && su.metadata.event_type) {
            const evtType = su.metadata.event_type;

            if (evtType === 'TEXT_DELTA') {
                const delta = su.metadata.delta || (su.metadata.payload ? su.metadata.payload.delta : '');
                if (delta) {
                    appendStreamingDelta(delta);
                }
                return;
            }

            if (evtType === 'AGENT_TOOL_START' || evtType === 'TASK_SUBTASK_STARTED') {
                const toolName = su.metadata.toolName || su.metadata.tool_name || 'tool';
                const args = su.metadata.args || su.metadata.parameters || {};
                const isSubtask = evtType === 'TASK_SUBTASK_STARTED';
                addToolCallLog(toolName, args, null, isSubtask);
                return;
            }

            if (evtType === 'AGENT_TOOL_END' || evtType === 'TASK_SUBTASK_COMPLETED') {
                const toolName = su.metadata.toolName || su.metadata.tool_name || 'tool';
                const result = su.metadata.result || su.metadata.output || '';
                const isSubtask = evtType === 'TASK_SUBTASK_COMPLETED';
                addToolCallLog(toolName, '(completed)', result, isSubtask);
                return;
            }
        }

        if (state === 'TASK_STATE_COMPLETED') {
            const outText = su.status.message && su.status.message.parts && su.status.message.parts[0]
                ? su.status.message.parts[0].text
                : '';
            finalizeStreamingCard(outText);
            statusDot.className = 'dot online';
            statusText.textContent = 'Task Completed';
        } else if (state === 'TASK_STATE_FAILED') {
            const errText = su.status.message && su.status.message.parts && su.status.message.parts[0]
                ? su.status.message.parts[0].text
                : 'Task failed';
            finalizeStreamingCard();
            addLog(`Task Failed: ${errText}`, 'error');
            statusDot.className = 'dot';
            statusDot.style.background = 'var(--danger)';
            statusText.textContent = 'Task Failed';
        }
    }
}

// ---------------------------------------------------------------------------
// 5. Task Query, Cancel, Re-Subscribe
// ---------------------------------------------------------------------------

async function queryTaskStatus() {
    const tid = document.getElementById('opTaskId').value.trim();
    if (!tid) {
        alert('Enter a Task ID to inspect');
        return;
    }
    try {
        const res = await fetch(`/tasks/${encodeURIComponent(tid)}`);
        const task = await res.json();
        showInspector(`Task: ${tid}`, task);
    } catch (e) {
        alert('Failed fetching task: ' + e);
    }
}

async function cancelCurrentTask() {
    const tid = document.getElementById('opTaskId').value.trim();
    if (!tid) {
        alert('Enter a Task ID to cancel');
        return;
    }
    try {
        const res = await fetch(`/tasks/${encodeURIComponent(tid)}:cancel`, {
            method: 'POST'
        });
        const task = await res.json();
        addLog(`Task ${tid} canceled. Current state: ${task.status.state}`, 'system-info');
        updateStatus();
    } catch (e) {
        alert('Failed to cancel task: ' + e);
    }
}

async function listHostTasks() {
    try {
        const res = await fetch('/tasks?limit=30');
        const tasks = await res.json();
        showInspector('Host Tasks List (/tasks)', tasks);
    } catch (e) {
        alert('Failed fetching tasks list: ' + e);
    }
}

async function attachTaskStream() {
    const tid = document.getElementById('opTaskId').value.trim();
    if (!tid) {
        alert('Enter a Task ID to re-subscribe');
        return;
    }
    addLog(`Re-subscribing to live SSE stream of task: ${tid}`, 'system-info');
    try {
        const response = await fetch(`/tasks/${encodeURIComponent(tid)}:subscribe`, {
            headers: { 'Accept': 'text/event-stream' }
        });
        if (!response.ok) {
            const err = await response.json();
            alert('Cannot subscribe: ' + (err.detail || response.statusText));
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
// 6. Modal & Directory Helpers
// ---------------------------------------------------------------------------

function showInspector(title, jsonData) {
    inspectorTitle.textContent = title;
    inspectorJson.textContent = JSON.stringify(jsonData, null, 2);
    inspectorModal.style.display = 'block';
}

function closeInspector() {
    inspectorModal.style.display = 'none';
}

let pickerTargetField = 'workspace';
let currentBrowsingPath = ".";

function openPicker(target='workspace') {
    pickerTargetField = target;
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
    if (pickerTargetField === 'workspace') {
        document.getElementById('workspacePath').value = currentBrowsingPath;
        onWorkspacePathChanged();
    } else if (pickerTargetField === 'create_workspace') {
        document.getElementById('createAgentWorkspace').value = currentBrowsingPath;
    } else if (pickerTargetField === 'ecp_dir') {
        document.getElementById('createAgentEcpDir').value = currentBrowsingPath;
    }
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
    await refreshActiveAgents();
    discoverAgentCard();
    updateStatus();
}

async function updateStatus() {
    try {
        const target = currentActiveAgent ? `?agent_name=${encodeURIComponent(currentActiveAgent)}` : '';
        const res = await fetch(`/agent/state${target}`);
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
document.addEventListener('DOMContentLoaded', () => {
    updateIdDisplays();
    loadAgentTypes();
    refreshActiveAgents();
    discoverAgentCard();
    onWorkspacePathChanged();
    setInterval(updateStatus, 3000);
});

if (document.readyState === 'complete' || document.readyState === 'interactive') {
    updateIdDisplays();
    loadAgentTypes();
    refreshActiveAgents();
    discoverAgentCard();
    onWorkspacePathChanged();
}
