/**
 * ROS2 System Diagnostic - Tools Page JavaScript
 */

// ==========================================
// Initialization
// ==========================================

document.addEventListener('DOMContentLoaded', function() {
    initPingTool();
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

// Topic/Node Inspector removed

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

function renderScriptResult(resultDiv, data) {
    if (!data || !data.success || !data.result) {
        const errorText = data?.error || 'Unknown error';
        resultDiv.innerHTML = '<span class="text-danger">Failed: ' + escapeHtml(errorText) + '</span>';
        return;
    }

    const result = data.result;
    const ok = !!result.ok;
    const statusClass = ok ? 'text-success' : 'text-danger';
    const exitText = result.exit_code !== undefined && result.exit_code !== null
        ? `Exit ${result.exit_code}`
        : 'Exit N/A';
    const durationText = result.duration_ms !== undefined
        ? ` · ${result.duration_ms} ms`
        : '';
    const sudoText = result.used_sudo ? ' · sudo' : '';
    const truncatedText = result.truncated ? ' · Output truncated' : '';
    const output = result.output || 'No output';

    resultDiv.innerHTML = `
        <div class="${statusClass}">
            <strong>${ok ? 'Completed' : 'Completed with errors'}</strong>
            <span>(${exitText}${durationText}${sudoText}${truncatedText})</span>
        </div>
        <pre class="log-content">${escapeHtml(output)}</pre>
    `;
}

async function runPtpStatus() {
    const resultDiv = document.getElementById('ptpStatusResult');
    if (!resultDiv) return;
    resultDiv.innerHTML = '<span class="loading"><span class="spinner"></span> Running PTP status...</span>';

    try {
        const data = await API.tools.ptpStatus();
        renderScriptResult(resultDiv, data);
    } catch (error) {
        resultDiv.innerHTML = '<span class="text-danger">Error: ' + escapeHtml(error.message) + '</span>';
    }
}

async function runPtpSyncVerify() {
    const resultDiv = document.getElementById('ptpSyncVerifyResult');
    if (!resultDiv) return;
    resultDiv.innerHTML = '<span class="loading"><span class="spinner"></span> Running PTP sync verification...</span>';

    try {
        const data = await API.tools.ptpSyncVerify();
        renderScriptResult(resultDiv, data);
    } catch (error) {
        resultDiv.innerHTML = '<span class="text-danger">Error: ' + escapeHtml(error.message) + '</span>';
    }
}

// Quick Commands removed (replaced by PTP tools)
