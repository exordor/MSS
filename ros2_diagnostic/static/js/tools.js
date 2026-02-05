/**
 * ROS2 System Diagnostic - Tools Page JavaScript
 */

// ==========================================
// Initialization
// ==========================================

document.addEventListener('DOMContentLoaded', function() {
    initPingTool();
    initTopicInspector();
    initNodeInspector();
    initConfigValidator();
});

// ==========================================
// Ping Tool
// ==========================================

function initPingTool() {
    const targetSelect = document.getElementById('pingTarget');
    const customIpInput = document.getElementById('pingCustomIp');

    if (targetSelect && customIpInput) {
        targetSelect.addEventListener('change', function() {
            if (this.value === 'custom') {
                customIpInput.style.display = 'block';
                customIpInput.focus();
            } else {
                customIpInput.style.display = 'none';
            }
        });
    }
}

async function runPingTest() {
    const targetSelect = document.getElementById('pingTarget');
    const customIpInput = document.getElementById('pingCustomIp');
    const resultDiv = document.getElementById('pingResult');

    let target = targetSelect.value;
    if (target === 'custom') {
        target = customIpInput.value.trim();
    }

    if (!target) {
        resultDiv.innerHTML = '<span class="text-danger">Please select a target</span>';
        return;
    }

    resultDiv.innerHTML = '<span class="loading"><span class="spinner"></span> Pinging ' + escapeHtml(target) + '...</span>';

    try {
        const data = await API.tools.ping(target, 4, 2);

        if (data.success && data.result) {
            const result = data.result;
            const reachable = result.reachable;
            const loss = result.packet_loss || 0;
            const avgTime = result.avg_time_ms || 0;

            let statusClass = reachable ? 'text-success' : 'text-danger';
            let statusText = reachable ? 'Reachable' : 'Unreachable';

            let html = `
                <div class="ping-result">
                    <div class="ping-status ${statusClass}">
                        <i class="fa-solid fa-${reachable ? 'check' : 'xmark'}"></i>
                        <strong>${escapeHtml(target)}</strong>: ${statusText}
                    </div>
                    <div class="ping-stats">
                        <div class="ping-stat">
                            <span class="stat-label">Packet Loss:</span>
                            <span class="stat-value">${loss.toFixed(1)}%</span>
                        </div>
            `;

            if (reachable) {
                html += `
                        <div class="ping-stat">
                            <span class="stat-label">Latency:</span>
                            <span class="stat-value">${avgTime.toFixed(1)} ms (avg)</span>
                        </div>
                        <div class="ping-stat">
                            <span class="stat-label">Min/Max:</span>
                            <span class="stat-value">${result.min_time_ms.toFixed(1)} / ${result.max_time_ms.toFixed(1)} ms</span>
                        </div>
                `;
            }

            html += `
                    </div>
                </div>
            `;

            resultDiv.innerHTML = html;
        } else {
            resultDiv.innerHTML = '<span class="text-danger">Ping failed: ' + escapeHtml(data.error || 'Unknown error') + '</span>';
        }
    } catch (error) {
        resultDiv.innerHTML = '<span class="text-danger">Error: ' + escapeHtml(error.message) + '</span>';
    }
}

// ==========================================
// Topic Inspector
// ==========================================

function initTopicInspector() {
    // Load topics on page load
    loadTopicsForInspector();
}

async function loadTopicsForInspector() {
    const select = document.getElementById('topicSelect');

    try {
        const data = await API.ros2.topics();

        if (data.success) {
            const topics = data.topics || [];
            select.innerHTML = '<option value="">Select topic...</option>' +
                topics.map(t => `<option value="${escapeHtml(t)}">${escapeHtml(t)}</option>`).join('');
        }
    } catch (error) {
        console.error('Error loading topics:', error);
    }
}

async function inspectTopic() {
    const select = document.getElementById('topicSelect');
    const resultDiv = document.getElementById('topicResult');

    const topic = select.value;
    if (!topic) {
        resultDiv.innerHTML = '<span class="text-muted">Select a topic to inspect</span>';
        return;
    }

    resultDiv.innerHTML = '<span class="loading"><span class="spinner"></span> Inspecting...</span>';

    try {
        const response = await fetch('/api/ros2/topic/info?topic=' + encodeURIComponent(topic));
        const data = await response.json();

        if (data.success && data.topic) {
            const info = data.topic;
            resultDiv.innerHTML = `
                <div class="topic-info">
                    <div class="info-row">
                        <span class="info-label">Name:</span>
                        <span class="info-value">${escapeHtml(info.name)}</span>
                    </div>
                    <div class="info-row">
                        <span class="info-label">Type:</span>
                        <span class="info-value">${escapeHtml(info.type || 'N/A')}</span>
                    </div>
                    <div class="info-row">
                        <span class="info-label">Publishers:</span>
                        <span class="info-value">${info.publisher_count || 0}</span>
                    </div>
                    <div class="info-row">
                        <span class="info-label">Subscribers:</span>
                        <span class="info-value">${info.subscription_count || 0}</span>
                    </div>
                </div>
            `;
        } else {
            resultDiv.innerHTML = '<span class="text-danger">Failed to get topic info</span>';
        }
    } catch (error) {
        resultDiv.innerHTML = '<span class="text-danger">Error: ' + escapeHtml(error.message) + '</span>';
    }
}

// ==========================================
// Node Inspector
// ==========================================

function initNodeInspector() {
    loadNodesForInspector();
}

async function loadNodesForInspector() {
    const select = document.getElementById('nodeSelect');

    try {
        const data = await API.ros2.nodes();

        if (data.success) {
            const nodes = data.nodes || [];
            select.innerHTML = '<option value="">Select node...</option>' +
                nodes.map(n => `<option value="${escapeHtml(n)}">${escapeHtml(n)}</option>`).join('');
        }
    } catch (error) {
        console.error('Error loading nodes:', error);
    }
}

async function inspectNode() {
    const select = document.getElementById('nodeSelect');
    const resultDiv = document.getElementById('nodeResult');

    const node = select.value;
    if (!node) {
        resultDiv.innerHTML = '<span class="text-muted">Select a node to inspect</span>';
        return;
    }

    resultDiv.innerHTML = '<span class="loading"><span class="spinner"></span> Inspecting...</span>';

    // For now, just show basic info
    resultDiv.innerHTML = `
        <div class="node-info">
            <p><strong>Node:</strong> ${escapeHtml(node)}</p>
            <p class="text-muted">Detailed node info requires ros2 cli integration</p>
        </div>
    `;
}

// ==========================================
// Config Validator
// ==========================================

function initConfigValidator() {
    // Nothing to initialize
}

async function validateConfig() {
    const select = document.getElementById('configSelect');
    const resultDiv = document.getElementById('configResult');

    const type = select.value;
    resultDiv.innerHTML = '<span class="loading"><span class="spinner"></span> Validating...</span>';

    try {
        const data = await API.tools.configValidate(type);

        if (data.success) {
            const results = data.results || {};
            let html = '<div class="config-results">';

            for (const [name, result] of Object.entries(results)) {
                const statusClass = result.valid ? 'text-success' : 'text-danger';
                const icon = result.valid ? 'check' : 'xmark';
                html += `
                    <div class="config-result-item">
                        <span class="${statusClass}">
                            <i class="fa-solid fa-${icon}"></i>
                            <strong>${name}</strong>:
                        </span>
                        ${result.valid ? 'Valid' : escapeHtml(result.error || 'Invalid')}
                    </div>
                `;
            }

            html += '</div>';
            resultDiv.innerHTML = html;
        } else {
            resultDiv.innerHTML = '<span class="text-danger">Validation failed</span>';
        }
    } catch (error) {
        resultDiv.innerHTML = '<span class="text-danger">Error: ' + escapeHtml(error.message) + '</span>';
    }
}

// ==========================================
// Quick Commands
// ==========================================

async function runCommand(command) {
    const resultDiv = document.getElementById('commandResult');
    resultDiv.innerHTML = '<span class="loading"><span class="spinner"></span> Running...</span>';

    try {
        let endpoint = '';
        switch (command) {
            case 'topics':
                endpoint = '/api/ros2/topics';
                break;
            case 'nodes':
                endpoint = '/api/ros2/nodes';
                break;
            case 'freq':
            case 'info':
                resultDiv.innerHTML = '<span class="text-muted">Command not yet implemented</span>';
                return;
        }

        const data = await fetchWithRetry(endpoint);

        if (data.success) {
            let content = '';
            if (command === 'topics') {
                content = (data.topics || []).map(t => escapeHtml(t)).join('\n');
            } else if (command === 'nodes') {
                content = (data.nodes || []).map(n => escapeHtml(n)).join('\n');
            }

            resultDiv.innerHTML = '<pre class="log-content">' + content + '</pre>';
        } else {
            resultDiv.innerHTML = '<span class="text-danger">Command failed</span>';
        }
    } catch (error) {
        resultDiv.innerHTML = '<span class="text-danger">Error: ' + escapeHtml(error.message) + '</span>';
    }
}
