/**
 * ROS2 System Diagnostic - Tools Page JavaScript
 */

// ==========================================
// Initialization
// ==========================================

document.addEventListener('DOMContentLoaded', function() {
    initPingTool();
    initConfigValidator();
    initPtpSyncFocus();
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

function initPtpSyncFocus() {
    const focusPtpSync = () => {
        if (window.location.hash !== '#ptp-sync') return;

        const section = document.getElementById('ptp-sync');
        if (!section) return;

        section.scrollIntoView({ behavior: 'smooth', block: 'start' });
        section.focus({ preventScroll: true });
    };

    focusPtpSync();
    window.addEventListener('hashchange', focusPtpSync);
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

    resultDiv.innerHTML = `
        <div class="script-result-summary ${statusClass}">
            <strong>${ok ? 'Completed' : 'Completed with errors'}</strong>
            <span>(${exitText}${durationText}${sudoText}${truncatedText})</span>
        </div>
        <pre class="tool-script-output">${renderScriptOutput(output)}</pre>
    `;
}

function renderPtpSyncVerifyResult(resultDiv, data) {
    if (!data || !data.success || !data.result) {
        const errorText = data?.error || 'Unknown error';
        resultDiv.innerHTML = renderPtpVerifyErrorCard(errorText);
        return;
    }

    const result = data.result;
    const output = result.output || 'No output';
    const model = buildPtpVerifyModel(output, result);

    resultDiv.innerHTML = `
        ${renderPtpDecisionCard(model)}
        ${renderPtpStatusCards(model.cards)}
        ${renderPtpTimeTable(model.timeRows)}
        ${renderPtpRawOutput(output, result.truncated)}
    `;
}

function renderPtpVerifyLoading() {
    return `
        <div class="ptp-decision-card running">
            <div class="ptp-decision-content">
                <div class="ptp-decision-icon">
                    <span class="spinner"></span>
                </div>
                <div>
                    <div class="ptp-decision-label">Running verification</div>
                    <h2>Checking PTP sync...</h2>
                    <p>Reading phc2sys, PTP port state, master clock, and PHC/system time.</p>
                </div>
            </div>
            <button class="tool-btn" type="button" disabled>
                <i class="fa-solid fa-rotate fa-spin"></i> Run Verify
            </button>
        </div>
    `;
}

function renderPtpVerifyEmpty() {
    return `
        <div class="ptp-decision-card unknown">
            <div class="ptp-decision-content">
                <div class="ptp-decision-icon">
                    <i class="fa-solid fa-circle-question"></i>
                </div>
                <div>
                    <div class="ptp-decision-label">Not verified</div>
                    <h2>PTP sync not checked</h2>
                    <p>Run verification before deciding whether to continue the experiment.</p>
                    <div class="ptp-decision-meta">
                        <span>Last update: never</span>
                        <span>Duration: --</span>
                        <span>Exit code: --</span>
                    </div>
                </div>
            </div>
            <button class="tool-btn" type="button" onclick="runPtpSyncVerify()">
                <i class="fa-solid fa-play"></i> Run Verify
            </button>
        </div>
    `;
}

function renderPtpVerifyErrorCard(errorText) {
    return `
        <div class="ptp-decision-card nogo">
            <div class="ptp-decision-content">
                <div class="ptp-decision-icon">
                    <i class="fa-solid fa-circle-xmark"></i>
                </div>
                <div>
                    <div class="ptp-decision-label">Not ready</div>
                    <h2>No-Go: wait/check TimeMachine, GPS, and PTP services</h2>
                    <p>${escapeHtml(errorText)}</p>
                    <div class="ptp-decision-meta">
                        <span>Last update: ${escapeHtml(formatPtpTimestamp(new Date()))}</span>
                        <span>Duration: --</span>
                        <span>Exit code: --</span>
                    </div>
                </div>
            </div>
            <button class="tool-btn" type="button" onclick="runPtpSyncVerify()">
                <i class="fa-solid fa-rotate"></i> Run Verify
            </button>
        </div>
    `;
}

function buildPtpVerifyModel(output, result) {
    const allPassed = /all checks passed|ptp sync is working correctly/i.test(output);
    const foundIssues = /found\s+([1-9][0-9]*)\s+issue/i.test(output);
    const cards = [
        getPtpServiceCard(output, allPassed),
        getPtpPortCard(output, allPassed),
        getPhc2sysCard(output, allPassed),
        getMasterClockCard(output, allPassed)
    ];

    const hasBlockingCard = cards.some(card => card.state === 'error');
    const ready = allPassed || (!foundIssues && !hasBlockingCard && cards.every(card => card.state === 'ok'));

    return {
        ready,
        title: ready ? 'PTP sync healthy' : 'Not ready',
        goText: ready
            ? 'Go: PTP sync is working correctly'
            : 'No-Go: wait/check TimeMachine, GPS, and PTP services',
        detail: ready
            ? 'The system can continue the experiment with synchronized time.'
            : 'Do not continue until phc2sys, PTP port state, and master clock are healthy.',
        lastUpdated: formatPtpTimestamp(new Date()),
        duration: formatDuration(result.duration_ms),
        exitCode: result.exit_code !== undefined && result.exit_code !== null ? String(result.exit_code) : 'N/A',
        cards,
        timeRows: getPtpTimeRows(output),
        rawTruncated: !!result.truncated
    };
}

function getPtpServiceCard(output, allPassed) {
    const lines = (output || '').split('\n');
    const line = lines.find(item => /ptp4l-client\.service:|ptp4l.*service:/i.test(item)) || '';
    const lower = line.toLowerCase();

    if (/not\s+running|failed|inactive|dead/.test(lower)) {
        return makePtpCard('PTP service', 'Not running', 'Check ptp4l-client.service', 'error', 'fa-satellite-dish');
    }

    if (/running|active/.test(lower)) {
        return makePtpCard('PTP service', 'OK', 'ptp4l-client.service running', 'ok', 'fa-satellite-dish');
    }

    if (allPassed) {
        return makePtpCard('PTP service', 'OK', 'Passed verification summary', 'ok', 'fa-satellite-dish');
    }

    return makePtpCard('PTP service', 'Unknown', 'No ptp4l service line found', 'unknown', 'fa-satellite-dish');
}

function getPtpPortCard(output, allPassed) {
    const portLine = findOutputLine(output, /port\s*state:/i);
    const stateMatch = portLine.match(/port\s*state:\s*(?:\u2713\s*)?([A-Z_]+)/i);
    const stateValue = stateMatch ? stateMatch[1].toUpperCase() : '';

    if (/ptp port is not in slave mode/i.test(output)) {
        return makePtpCard('Port state', stateValue || 'Not SLAVE', 'PTP port is not locked as SLAVE', 'error', 'fa-ethernet');
    }

    if (stateValue === 'SLAVE' || /ptp port is in slave mode/i.test(output) || allPassed) {
        return makePtpCard('Port state', stateValue || 'SLAVE', 'OK', 'ok', 'fa-ethernet');
    }

    if (stateValue) {
        return makePtpCard('Port state', stateValue, 'Expected SLAVE', 'warning', 'fa-ethernet');
    }

    return makePtpCard('Port state', 'Missing', 'No port state found', 'warning', 'fa-ethernet');
}

function getPhc2sysCard(output, allPassed) {
    const phc2sysStatus = getPhc2sysStatus(output);

    if (phc2sysStatus?.state === 'ok' || allPassed) {
        return makePtpCard('phc2sys', 'Running', 'OK', 'ok', 'fa-clock-rotate-left');
    }

    if (phc2sysStatus?.state === 'error') {
        return makePtpCard('phc2sys', 'Not running', 'Start phc2sys-client.service', 'error', 'fa-clock-rotate-left');
    }

    return makePtpCard('phc2sys', 'Unknown', 'No phc2sys status found', 'unknown', 'fa-clock-rotate-left');
}

function getMasterClockCard(output, allPassed) {
    if (/gmpresent\s+(false|0)/i.test(output)) {
        return makePtpCard('Master clock', 'Missing', 'Check TimeMachine/GPS/PTP master', 'error', 'fa-tower-broadcast');
    }

    if (/gmpresent\s+(true|1)|grandmasteridentity|gmidentity/i.test(output) || allPassed) {
        return makePtpCard('Master clock', 'OK', 'Grandmaster detected', 'ok', 'fa-tower-broadcast');
    }

    return makePtpCard('Master clock', 'Warning', 'Master clock evidence missing', 'warning', 'fa-tower-broadcast');
}

function makePtpCard(label, value, detail, state, icon) {
    return { label, value, detail, state, icon };
}

function findOutputLine(output, pattern) {
    return (output || '').split('\n').find(line => pattern.test(line)) || '';
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

function renderPtpDecisionCard(model) {
    const stateClass = model.ready ? 'go' : 'nogo';
    const icon = model.ready ? 'fa-circle-check' : 'fa-circle-xmark';
    const offlineNote = model.ready
        ? `
            <div class="ptp-offline-note">
                <i class="fa-solid fa-triangle-exclamation"></i>
                <div>
                    <strong>Offline time reference</strong>
                    <p>In no-network environments, the times below are the valid experiment-time reference, not the initial boot time.</p>
                </div>
            </div>
        `
        : '';

    return `
        <div class="ptp-decision-card ${stateClass}">
            <div class="ptp-decision-content">
                <div class="ptp-decision-icon">
                    <i class="fa-solid ${icon}"></i>
                </div>
                <div>
                    <div class="ptp-decision-label">${model.title}</div>
                    <h2>${model.goText}</h2>
                    <p>${model.detail}</p>
                    <div class="ptp-decision-meta">
                        <span>Last update: ${escapeHtml(model.lastUpdated)}</span>
                        <span>Duration: ${escapeHtml(model.duration)}</span>
                        <span>Exit code: ${escapeHtml(model.exitCode)}</span>
                    </div>
                    ${offlineNote}
                </div>
            </div>
            <button class="tool-btn" type="button" onclick="runPtpSyncVerify()">
                <i class="fa-solid fa-rotate"></i> Run Verify
            </button>
        </div>
    `;
}

function renderPtpStatusCards(cards) {
    const cardsHtml = cards.map(card => `
        <div class="ptp-status-card ${card.state}">
            <div class="ptp-status-card-top">
                <span class="ptp-status-card-icon">
                    <i class="fa-solid ${card.icon}"></i>
                </span>
                <span class="ptp-status-state">${escapeHtml(card.state === 'ok' ? 'OK' : card.state.toUpperCase())}</span>
            </div>
            <div class="ptp-status-label">${escapeHtml(card.label)}</div>
            <div class="ptp-status-value">${escapeHtml(card.value)}</div>
            <div class="ptp-status-detail">${escapeHtml(card.detail)}</div>
        </div>
    `).join('');

    return `<div class="ptp-status-grid">${cardsHtml}</div>`;
}

function renderPtpTimeTable(rows) {
    const rowsHtml = rows.map(row => `
        <tr>
            <th>${escapeHtml(row.label)}</th>
            <td>${escapeHtml(row.value)}</td>
        </tr>
    `).join('');

    return `
        <div class="ptp-time-panel">
            <div class="ptp-section-title">
                <i class="fa-solid fa-clock"></i>
                Key time comparison
            </div>
            <table class="ptp-time-table">
                <tbody>${rowsHtml}</tbody>
            </table>
        </div>
    `;
}

function renderPtpRawOutput(output, truncated) {
    const truncatedText = truncated ? '<span class="ptp-raw-warning">Output truncated</span>' : '';

    return `
        <details class="ptp-raw-output">
            <summary>
                <span><i class="fa-solid fa-file-lines"></i> Details / Raw output</span>
                ${truncatedText}
            </summary>
            <pre class="tool-script-output">${renderScriptOutput(output || 'No output')}</pre>
        </details>
    `;
}

function getPtpTimeRows(output) {
    const phcTime = matchOutputValue(output, /^PHC Time\s+\((?!UTC\))[^)]+\):\s*(.+)$/im);
    const systemTime = matchOutputValue(output, /^System Time:\s*(.+)$/im);
    const diff = matchOutputValue(output, /^PHC\s*-\s*System:\s*(.+)$/im);
    const interpretation = matchOutputValue(output, /^Inference:\s*(?:\u2713|\u26a0)?\s*(.+)$/im);

    return [
        { label: 'PHC time', value: phcTime || 'N/A' },
        { label: 'System time', value: systemTime || 'N/A' },
        { label: 'PHC-System diff', value: diff || 'N/A' },
        { label: 'Interpretation', value: interpretation || 'N/A' }
    ];
}

function matchOutputValue(output, pattern) {
    const match = (output || '').match(pattern);
    return match ? match[1].trim() : '';
}

function formatDuration(ms) {
    if (ms === undefined || ms === null) return 'N/A';
    if (ms < 1000) return `${ms} ms`;
    return `${(ms / 1000).toFixed(1)} s`;
}

function formatPtpTimestamp(date) {
    return date.toLocaleString(undefined, {
        year: 'numeric',
        month: '2-digit',
        day: '2-digit',
        hour: '2-digit',
        minute: '2-digit',
        second: '2-digit',
        hour12: false
    });
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
    resultDiv.innerHTML = renderPtpVerifyLoading();

    try {
        const data = await API.tools.ptpSyncVerify();
        renderPtpSyncVerifyResult(resultDiv, data);
    } catch (error) {
        resultDiv.innerHTML = renderPtpVerifyErrorCard(error.message);
    }
}

// Quick Commands removed (replaced by PTP tools)
