// Pi Agent Raw LLM Monitor UI Logic

const turnsContainer = document.getElementById('turnsContainer');
const statModel = document.getElementById('statModel');
const statProvider = document.getElementById('statProvider');
const statInputTokens = document.getElementById('statInputTokens');
const statOutputTokens = document.getElementById('statOutputTokens');
const statReasoningTokens = document.getElementById('statReasoningTokens');
const statTotalTokens = document.getElementById('statTotalTokens');
const statCost = document.getElementById('statCost');
const sessionFilePath = document.getElementById('sessionFilePath');
const autoRefreshCheckbox = document.getElementById('autoRefreshCheckbox');

let refreshInterval = null;
// Track user-expanded details elements across refreshes using unique keys
const expandedKeys = new Set();

async function fetchAndRenderLogs() {
    try {
        const res = await fetch('/agent/pi/raw-logs?limit=50');
        const data = await res.json();

        if (data.error) {
            sessionFilePath.textContent = data.error;
            if (!data.is_pi_agent) {
                turnsContainer.innerHTML = `
                    <div style="text-align: center; color: var(--text-dim); margin-top: 3rem;">
                        <h3>Not a Pi Harness Agent</h3>
                        <p>${data.error}</p>
                        <p>Switch the active agent to a Pi agent (e.g. <code>pi_agent</code>) in the console to inspect raw LLM JSONL sessions.</p>
                    </div>
                `;
            } else {
                turnsContainer.innerHTML = `
                    <div style="text-align: center; color: var(--text-dim); margin-top: 3rem;">
                        <h3>No Active Session Yet</h3>
                        <p>${data.error}</p>
                    </div>
                `;
            }
            return;
        }

        // 1. Render Metrics
        const stats = data.stats || {};
        statModel.textContent = stats.model || 'Unknown';
        statProvider.textContent = stats.provider || 'Google Vertex';
        statInputTokens.textContent = (stats.total_input_tokens || 0).toLocaleString();
        statOutputTokens.textContent = (stats.total_output_tokens || 0).toLocaleString();
        statReasoningTokens.textContent = (stats.total_reasoning_tokens || 0).toLocaleString();
        statTotalTokens.textContent = (stats.total_tokens || 0).toLocaleString();
        statCost.textContent = `$${(stats.total_cost || 0).toFixed(5)}`;
        sessionFilePath.textContent = data.session_file || 'In-Memory';

        // 2. Render Structured Turns
        renderTurns(data.turns || []);
    } catch (e) {
        sessionFilePath.textContent = 'Error connecting to host: ' + e;
    }
}

function renderTurns(turns) {
    if (!turns || turns.length === 0) {
        turnsContainer.innerHTML = `
            <div style="text-align: center; color: var(--text-dim); margin-top: 3rem;">
                <h3>No Conversational Turns Yet</h3>
                <p>Send a message in the WebHMI to see structured LLM reasoning, tokens, and tool calls here.</p>
            </div>
        `;
        return;
    }

    // Capture user's scroll position before re-rendering (window scroll)
    const scrollEl = document.scrollingElement || document.documentElement || document.body;
    const previousScrollTop = scrollEl.scrollTop;
    const isAtBottom = (scrollEl.scrollHeight - scrollEl.scrollTop <= scrollEl.clientHeight + 80);

    turnsContainer.innerHTML = '';

    turns.forEach((turn, idx) => {
        const turnId = turn.id || `turn-${idx}`;
        const turnCard = document.createElement('div');
        turnCard.className = 'turn-card';

        // Header
        const header = document.createElement('div');
        header.className = 'turn-header';

        const userPrompt = document.createElement('div');
        userPrompt.className = 'turn-user-prompt';
        userPrompt.innerHTML = `<span>👤 User Turn #${idx + 1}:</span> <span>${escapeHtml(turn.user_text || '(Empty Prompt)')}</span>`;

        const timeSpan = document.createElement('span');
        timeSpan.className = 'turn-time';
        timeSpan.textContent = turn.timestamp ? new Date(turn.timestamp).toLocaleTimeString() : '';

        header.appendChild(userPrompt);
        header.appendChild(timeSpan);
        turnCard.appendChild(header);

        // Body
        const body = document.createElement('div');
        body.className = 'turn-body';

        const responses = turn.model_responses || [];
        responses.forEach((resp, rIdx) => {
            const respId = resp.id || `resp-${rIdx}`;

            // A. Thinking / Reasoning Block
            if (resp.thinking && resp.thinking.length > 0) {
                const thinkingKey = `${turnId}-${respId}-thinking`;
                const thinkingBox = document.createElement('details');
                thinkingBox.className = 'thinking-box';
                if (expandedKeys.has(thinkingKey)) {
                    thinkingBox.open = true;
                }
                thinkingBox.addEventListener('toggle', () => {
                    if (thinkingBox.open) expandedKeys.add(thinkingKey);
                    else expandedKeys.delete(thinkingKey);
                });

                const summary = document.createElement('summary');
                summary.className = 'thinking-summary';
                const reasonTok = resp.usage?.reasoning || 0;
                summary.innerHTML = `<span>🧠 Model Reasoning & Thoughts</span> <span style="font-size:0.75rem; color:#818cf8;">(${reasonTok} tokens)</span>`;
                thinkingBox.appendChild(summary);

                const contentDiv = document.createElement('div');
                contentDiv.className = 'thinking-content';
                contentDiv.textContent = resp.thinking.join('\n\n---\n\n');
                thinkingBox.appendChild(contentDiv);

                body.appendChild(thinkingBox);
            }

            // B. Tool Calls & Delegations
            if (resp.tool_calls && resp.tool_calls.length > 0) {
                resp.tool_calls.forEach((tool, tIdx) => {
                    const toolKey = `${turnId}-${respId}-tool-${tool.id || tIdx}`;
                    const toolBox = document.createElement('details');
                    toolBox.className = 'tool-call-box';
                    if (expandedKeys.has(toolKey)) {
                        toolBox.open = true;
                    }
                    toolBox.addEventListener('toggle', () => {
                        if (toolBox.open) expandedKeys.add(toolKey);
                        else expandedKeys.delete(toolKey);
                    });

                    const summary = document.createElement('summary');
                    const badgeClass = tool.is_subtask ? 'subtask-badge' : 'tool-call-badge';
                    const badgeText = tool.is_subtask ? `delegated: ${tool.name}` : `tool: ${tool.name}`;
                    
                    let argPreview = JSON.stringify(tool.arguments || {});
                    if (argPreview.length > 70) argPreview = argPreview.substring(0, 70) + '...';

                    summary.innerHTML = `<span class="${badgeClass}">${badgeText}</span> <span style="color:var(--text-dim); margin-left:0.5rem;">${escapeHtml(argPreview)}</span>`;
                    toolBox.appendChild(summary);

                    const content = document.createElement('div');
                    content.className = 'tool-call-content';
                    content.textContent = `Arguments:\n${JSON.stringify(tool.arguments, null, 2)}\n\nOutput / Result:\n${tool.result || '(No Output)'}`;
                    toolBox.appendChild(content);

                    body.appendChild(toolBox);
                });
            }

            // C. Assistant Final Response
            if (resp.text && resp.text.trim()) {
                const finalCard = document.createElement('div');
                finalCard.className = 'model-final-text markdown-body';
                finalCard.innerHTML = marked.parse(resp.text);
                body.appendChild(finalCard);
            }

            // D. Raw Generation Drawer
            const rawKey = `${turnId}-${respId}-raw`;
            const rawDrawer = document.createElement('details');
            rawDrawer.className = 'raw-drawer';
            if (expandedKeys.has(rawKey)) {
                rawDrawer.open = true;
            }
            rawDrawer.addEventListener('toggle', () => {
                if (rawDrawer.open) expandedKeys.add(rawKey);
                else expandedKeys.delete(rawKey);
            });

            const rawSummary = document.createElement('summary');
            rawSummary.textContent = `Raw API Response Metadata (${resp.model || 'model'} | ${resp.stop_reason || 'stop'} | ${resp.usage?.total || 0} tokens)`;
            rawDrawer.appendChild(rawSummary);

            const rawJson = document.createElement('pre');
            rawJson.style.margin = '0.5rem 0 0 0';
            rawJson.style.fontSize = '0.75rem';
            rawJson.textContent = JSON.stringify(resp.raw_message || resp, null, 2);
            rawDrawer.appendChild(rawJson);

            body.appendChild(rawDrawer);
        });

        turnCard.appendChild(body);
        turnsContainer.appendChild(turnCard);
    });

    // Restore window scroll position so auto-refresh doesn't jerk the viewport
    if (!isAtBottom) {
        scrollEl.scrollTop = previousScrollTop;
    } else {
        scrollEl.scrollTop = scrollEl.scrollHeight;
    }
}

function escapeHtml(str) {
    if (!str) return '';
    return str.replace(/&/g, "&amp;").replace(/</g, "&lt;").replace(/>/g, "&gt;");
}

function setupAutoRefresh() {
    if (autoRefreshCheckbox.checked) {
        if (!refreshInterval) {
            refreshInterval = setInterval(fetchAndRenderLogs, 3000);
        }
    } else {
        if (refreshInterval) {
            clearInterval(refreshInterval);
            refreshInterval = null;
        }
    }
}

autoRefreshCheckbox.addEventListener('change', setupAutoRefresh);

// Initial execution
fetchAndRenderLogs();
setupAutoRefresh();
