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
        resultDiv.innerHTML = '<span class="script-result-summary error">Failed: ' + escapeHtml(errorText) + '</span>';
        return;
    }

    const result = data.result;
    const ok = !!result.ok;
    const statusClass = ok ? 'ok' : 'error';
    const exitText = result.exit_code !== undefined && result.exit_code !== null
        ? `Exit ${result.exit_code}`
        : 'Exit N/A';
    const durationText = result.duration_ms !== undefined
        ? ` · ${result.duration_ms} ms`
        : '';
    const sudoText = result.used_sudo ? ' · sudo' : '';
    const truncatedText = result.truncated ? ' · Output truncated' : '';
    const output = result.output || 'No output';
    const summaryHtml = buildPtpSyncSummary(output, ok);

    resultDiv.innerHTML = `
        ${summaryHtml}
        <div class="script-result-summary ${statusClass}">
            <strong>${ok ? 'Completed' : 'Completed with errors'}</strong>
            <span>(${exitText}${durationText}${sudoText}${truncatedText})</span>
        </div>
        <pre class="tool-script-output">${renderScriptOutput(output)}</pre>
    `;
}

function buildPtpSyncSummary(output, commandOk) {
    const text = (output || '').toLowerCase();
    const ptpServiceWarn = /ptp4l[^\n]*(inactive|failed|not running)|active:\s+(inactive|failed)/i.test(output);
    const phc2sysWarn = /phc2sys[^\n]*(not running|failed)|phc2sys is not running/i.test(output);
    const phc2sysStatus = getPhc2sysStatus(output);
    const checks = [
        {
            label: 'PTP service',
            ok: !ptpServiceWarn && /ptp4l[^\n]*active:\s+active|active:\s+active \(running\)|ptp4l.*running/i.test(output),
            warn: ptpServiceWarn
        },
        {
            label: 'Port state',
            ok: /port\s*state:\s*[\u2713 ]*slave|portstate\s+slave|ptp port is in slave mode/i.test(output),
            warn: /port\s*state:\s*(?![\u2713 ]*slave)\S+|ptp port is not in slave mode/i.test(output)
        },
        {
            label: 'Master clock',
            ok: /gmpresent\s+(true|1)|grandmasteridentity|gmidentity/i.test(output),
            warn: /gmpresent\s+(false|0)/i.test(output)
        },
        {
            label: 'phc2sys',
            ok: !phc2sysWarn && /phc2sys[^\n]*(\u2713\s*running|is running|:\s*running)|all checks passed/i.test(output),
            warn: phc2sysWarn
        }
    ];

    const passed = checks.filter(check => check.ok).length;
    const warnings = checks.filter(check => check.warn).length;
    const hasAllPassed = /all checks passed|ptp sync is working correctly/i.test(output);
    const hasErrors = !commandOk || warnings > 0 || /error|failed|cannot read|not supported/i.test(text);

    let state = 'warning';
    let icon = 'fa-triangle-exclamation';
    let title = 'PTP sync needs checking';
    let detail = 'Review the highlighted lines below.';

    if (hasAllPassed || (commandOk && warnings === 0 && passed >= 3)) {
        state = 'ok';
        icon = 'fa-circle-check';
        title = 'PTP sync looks healthy';
        detail = `${passed}/${checks.length} sync signals detected.`;
    } else if (hasErrors) {
        state = 'error';
        icon = 'fa-circle-xmark';
        title = 'PTP sync has issues';
        detail = `${warnings} warning signal(s), ${passed}/${checks.length} healthy signal(s).`;
    } else if (passed > 0) {
        detail = `${passed}/${checks.length} sync signals detected.`;
    }

    const checkHtml = checks.map(check => {
        const checkState = check.ok ? 'ok' : check.warn ? 'error' : 'unknown';
        const checkIcon = check.ok ? 'fa-check' : check.warn ? 'fa-xmark' : 'fa-minus';
        return `
            <span class="ptp-check ${checkState}">
                <i class="fa-solid ${checkIcon}"></i>
                ${escapeHtml(check.label)}
            </span>
        `;
    }).join('');

    return `
        <div class="ptp-sync-summary ${state}">
            ${renderPhc2sysFocus(phc2sysStatus)}
            <div class="ptp-sync-main">
                <i class="fa-solid ${icon}"></i>
                <div>
                    <strong>${title}</strong>
                    <span>${detail}</span>
                </div>
            </div>
            <div class="ptp-checks">${checkHtml}</div>
        </div>
    `;
}

function getPhc2sysStatus(output) {
    const lines = (output || '').split('\n');
    const serviceLine = lines.find(line => /phc2sys-client\.service:/i.test(line));
    const fallbackLine = lines.find(line => /phc2sys/i.test(line) && /not running|failed|inactive|running/i.test(line));
    const line = serviceLine || fallbackLine || '';
    const lower = line.toLowerCase();

    if (!line) {
        return null;
    }

    if (/not\s+running|failed|inactive|dead/.test(lower)) {
        return {
            state: 'error',
            icon: 'fa-circle-xmark',
            label: 'phc2sys-client.service',
            value: 'Not running',
            line
        };
    }

    if (/running|active/.test(lower)) {
        return {
            state: 'ok',
            icon: 'fa-circle-check',
            label: 'phc2sys-client.service',
            value: 'Running',
            hintTitle: 'Offline time reference',
            hint: 'When phc2sys is Running, the times below are the valid experiment-time reference in no-network environments, not the initial boot time.',
            line
        };
    }

    return {
        state: 'unknown',
        icon: 'fa-circle-question',
        label: 'phc2sys-client.service',
        value: 'Unknown',
        line
    };
}

function renderPhc2sysFocus(status) {
    if (!status) return '';
    const hintHtml = status.hint
        ? `
            <div class="phc2sys-time-note">
                <i class="fa-solid fa-triangle-exclamation"></i>
                <div>
                    <strong>${escapeHtml(status.hintTitle || 'Important time note')}</strong>
                    <p>${escapeHtml(status.hint)}</p>
                </div>
            </div>
        `
        : '';

    return `
        <div class="phc2sys-focus ${status.state}">
            <div class="phc2sys-focus-row">
                <div class="phc2sys-focus-label">
                    <i class="fa-solid ${status.icon}"></i>
                    <span>${escapeHtml(status.label)}</span>
                </div>
                <strong>${escapeHtml(status.value)}</strong>
            </div>
            ${hintHtml}
        </div>
    `;
}

function renderScriptOutput(output) {
    return (output || 'No output').split('\n').map(line => {
        const lineClass = getScriptLineClass(line);
        return `<span class="script-line ${lineClass}">${escapeHtml(line) || '&nbsp;'}</span>`;
    }).join('');
}

function getScriptLineClass(line) {
    const lower = line.toLowerCase();

    if (/phc2sys-client\.service:/.test(lower)) {
        if (/not\s+running|failed|inactive|dead/.test(lower)) {
            return 'phc2sys-error';
        }
        if (/running|active/.test(lower)) {
            return 'phc2sys-ok';
        }
        return 'phc2sys-unknown';
    }

    if (/error|failed|cannot read|not supported|not running|not in slave|inactive|timeout/.test(lower)) {
        return 'error';
    }

    if (/warning|warn|unclear|conflict|should be stopped|not available|\u26a0/.test(lower)) {
        return 'warning';
    }

    if (/all checks passed|active:\s+active|running|slave|gmpresent\s+(true|1)|supported|synchronized:\s+yes|\u2713/.test(lower)) {
        return 'ok';
    }

    if (/^=+|^-+|^\u2501+|ptp|clock|offset|time|status|summary|useful commands/.test(lower.trim())) {
        return 'meta';
    }

    return 'plain';
}

async function runPtpStatus() {
    const resultDiv = document.getElementById('ptpStatusResult');
    if (!resultDiv) return;
    resultDiv.innerHTML = '<span class="loading"><span class="spinner"></span> Running PTP status...</span>';

    try {
        const data = await API.tools.ptpStatus();
        renderScriptResult(resultDiv, data);
    } catch (error) {
        resultDiv.innerHTML = '<span class="script-result-summary error">Error: ' + escapeHtml(error.message) + '</span>';
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
        resultDiv.innerHTML = '<span class="script-result-summary error">Error: ' + escapeHtml(error.message) + '</span>';
    }
}

// Quick Commands removed (replaced by PTP tools)
