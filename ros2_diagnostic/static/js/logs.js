/**
 * ROS2 System Diagnostic - Logs Page JavaScript
 * IIFE pattern to avoid conflicts with main.js
 */

(function() {
    'use strict';

    // ==========================================
    // Private State
    // ==========================================
    const state = {
        autoRefreshEnabled: false,
        autoRefreshTimer: null,
        liveEnabled: false,
        liveSource: null,
        originalLogs: [],
        currentCategory: 'application',
        currentSession: null,
        currentFile: null,
        sessions: [],
        applicationFiles: [
            { name: 'diagnostic', label: 'Diagnostic Log' },
            { name: 'ros2', label: 'ROS2 Control Log' }
        ]
    };

    const AUTO_REFRESH_DELAY = 5000; // 5 seconds
    const LIVE_REFRESH_DELAY = 1000; // 1 second
    const containerEl = document.querySelector('.logs-container');
    const LOG_ROOT = containerEl?.dataset.logRoot || '';
    const PROJECT_ROOT = containerEl?.dataset.projectRoot || '';

    // ==========================================
    // Initialization
    // ==========================================
    document.addEventListener('DOMContentLoaded', init);

    function init() {
        console.log('[LogsViewer] Initializing...');

        // Bind category radio buttons
        const categoryInputs = document.querySelectorAll('input[name="logCategory"]');
        categoryInputs.forEach(input => {
            input.addEventListener('change', onCategoryChange);
        });

        // Bind session select
        const sessionSelect = document.getElementById('sessionSelect');
        if (sessionSelect) {
            sessionSelect.addEventListener('change', onSessionChange);
        }

        // Bind file select
        const fileSelect = document.getElementById('fileSelect');
        if (fileSelect) {
            fileSelect.addEventListener('change', onFileChange);
        }

        // Bind control buttons
        const loadBtn = document.getElementById('loadLogsBtn');
        const refreshBtn = document.getElementById('autoRefreshLogsBtn');
        const liveBtn = document.getElementById('liveLogsBtn');
        const clearBtn = document.getElementById('clearLogsBtn');
        const searchInput = document.getElementById('logSearch');
        const severitySelect = document.getElementById('logSeverity');
        const nodeInput = document.getElementById('logNode');

        if (loadBtn) loadBtn.addEventListener('click', loadLogs);
        if (refreshBtn) refreshBtn.addEventListener('click', toggleAutoRefresh);
        if (liveBtn) liveBtn.addEventListener('click', toggleLive);
        if (clearBtn) clearBtn.addEventListener('click', clearFilter);
        if (searchInput) {
            searchInput.addEventListener('keyup', onSearchKeyup);
            searchInput.addEventListener('input', debounce(onSearchInput, 300));
        }
        if (severitySelect) severitySelect.addEventListener('change', applySearchFilter);
        if (nodeInput) nodeInput.addEventListener('input', debounce(onSearchInput, 300));

        // Initialize with Application category
        initializeApplicationMode();
    }

    // ==========================================
    // Category Handling
    // ==========================================
    function onCategoryChange(e) {
        const category = e.target.value;
        state.currentCategory = category;
        console.log('[LogsViewer] Category changed to:', category);

        stopLiveStream();

        if (category === 'application') {
            initializeApplicationMode();
        } else if (category === 'session') {
            initializeSessionMode();
        }
    }

    function initializeApplicationMode() {
        const sessionSelect = document.getElementById('sessionSelect');
        const fileSelect = document.getElementById('fileSelect');
        const appInfo = document.getElementById('applicationInfo');

        // Disable session select, show application info
        if (sessionSelect) {
            sessionSelect.disabled = true;
            sessionSelect.innerHTML = '<option value="">N/A</option>';
        }
        if (appInfo) {
            appInfo.innerHTML = '<small>Diagnostic & ROS2 control logs</small>';
            appInfo.style.display = 'block';
        }

        // Populate file select with application logs
        if (fileSelect) {
            fileSelect.disabled = false;
            fileSelect.innerHTML = state.applicationFiles.map(f =>
                `<option value="${f.name}">${f.label}</option>`
            ).join('');
            // Auto-select first file
            fileSelect.value = 'diagnostic';
            state.currentFile = 'diagnostic';
        }

        // Auto-load diagnostic log
        loadLogs();
    }

    async function initializeSessionMode() {
        const sessionSelect = document.getElementById('sessionSelect');
        const fileSelect = document.getElementById('fileSelect');
        const appInfo = document.getElementById('applicationInfo');

        // Show session info
        if (appInfo) {
            appInfo.innerHTML = '<small>Select a ROS2 session</small>';
            appInfo.style.display = 'block';
        }

        // Load sessions
        if (sessionSelect) {
            sessionSelect.disabled = true;
            sessionSelect.innerHTML = '<option value="">Loading sessions...</option>';
        }

        try {
            const response = await fetch('/api/logs/sessions');
            const data = await response.json();

            if (data.success && data.sessions.length > 0) {
                state.sessions = data.sessions;
                sessionSelect.disabled = false;
                sessionSelect.innerHTML = data.sessions.map(s =>
                    `<option value="${s.id}">${s.name}</option>`
                ).join('');
            } else {
                sessionSelect.innerHTML = '<option value="">No sessions found</option>';
            }
        } catch (error) {
            console.error('[LogsViewer] Error loading sessions:', error);
            sessionSelect.innerHTML = '<option value="">Error loading sessions</option>';
        }

        // Reset file select
        if (fileSelect) {
            fileSelect.disabled = true;
            fileSelect.innerHTML = '<option value="">-- Select Session First --</option>';
        }
    }

    // ==========================================
    // Session Handling
    // ==========================================
    async function onSessionChange(e) {
        const sessionId = e.target.value;
        state.currentSession = sessionId;
        console.log('[LogsViewer] Session changed to:', sessionId);
        stopLiveStream();

        const fileSelect = document.getElementById('fileSelect');

        if (!sessionId || !fileSelect) return;

        // Load files for this session
        fileSelect.disabled = true;
        fileSelect.innerHTML = '<option value="">Loading files...</option>';

        try {
            const response = await fetch(`/api/logs/session/${sessionId}/files`);
            const data = await response.json();

            if (data.success && data.files.length > 0) {
                fileSelect.disabled = false;
                fileSelect.innerHTML = data.files.map(f =>
                    `<option value="${f.name}">${f.label} (${formatBytes(f.size)})</option>`
                ).join('');

                // Auto-select first non-empty file
                const firstFile = data.files.find(f => f.size > 0);
                if (firstFile) {
                    fileSelect.value = firstFile.name;
                    state.currentFile = firstFile.name;
                    loadLogs();
                } else {
                    // Empty session
                    showEmptyMessage('No log files in this session');
                }
            } else {
                fileSelect.innerHTML = '<option value="">No files found</option>';
            }
        } catch (error) {
            console.error('[LogsViewer] Error loading files:', error);
            fileSelect.innerHTML = '<option value="">Error loading files</option>';
        }
    }

    function onFileChange(e) {
        state.currentFile = e.target.value;
        // Don't auto-load on file change, let user click Refresh
        stopLiveStream();
    }

    // ==========================================
    // Log Loading
    // ==========================================
    async function loadLogs() {
        const lines = parseInt(document.getElementById('logLines')?.value || 100, 10);
        const contentDiv = document.getElementById('logContent');
        const statsDiv = document.getElementById('logStats');
        const loadBtn = document.getElementById('loadLogsBtn');

        console.log('[LogsViewer] Loading:', {
            category: state.currentCategory,
            session: state.currentSession,
            file: state.currentFile,
            lines
        });

        // Validate selection
        if (state.currentCategory === 'session' && (!state.currentSession || !state.currentFile)) {
            showError('Please select a session and file');
            return;
        }

        // Show loading state
        if (contentDiv) {
            contentDiv.innerHTML = '<span class="log-loading"><span class="spinner"></span> Loading logs...</span>';
        }
        if (loadBtn) loadBtn.disabled = true;

        try {
            // Build query parameters
            const params = new URLSearchParams({
                category: state.currentCategory,
                file: state.currentFile,
                lines: lines
            });

            if (state.currentCategory === 'session') {
                params.append('session', state.currentSession);
            }

            const response = await fetch(`/api/logs/read?${params}`);
            const data = await response.json();

            console.log('[LogsViewer] Response:', { status: response.status, data });

            if (data.success && data.logs) {
                state.originalLogs = data.logs;

                // Update stats
                updateStats(data);

                // Display logs
                displayLogs(data.logs);

                // Update last updated time
                updateLastUpdated();
            } else {
                showError(data.error || 'Unknown error');
            }
        } catch (error) {
            console.error('[LogsViewer] Error:', error);
            showError(error.message);
        } finally {
            if (loadBtn) loadBtn.disabled = false;
        }
    }

    // ==========================================
    // Display Functions
    // ==========================================
    function displayLogs(logs) {
        const contentDiv = document.getElementById('logContent');

        if (!contentDiv) return;

        if (logs.length === 0) {
            contentDiv.innerHTML = '<span class="log-empty">Log file is empty</span>';
            updateShownCount(0);
            return;
        }

        // Convert logs to HTML with syntax highlighting
        const html = logs.map(line => formatLogLine(line)).join('\n');
        contentDiv.innerHTML = html;

        updateShownCount(logs.length);
        contentDiv.scrollTop = 0;
    }

    function formatLogLine(line) {
        // Escape HTML first
        let formatted = escapeHtml(line);

        // Highlight log levels
        formatted = formatted.replace(/\b(ERROR|CRITICAL|FATAL)\b/g, '<span class="log-level-error">$1</span>');
        formatted = formatted.replace(/\b(WARNING|WARN)\b/g, '<span class="log-level-warning">$1</span>');
        formatted = formatted.replace(/\b(INFO)\b/g, '<span class="log-level-info">$1</span>');
        formatted = formatted.replace(/\b(DEBUG)\b/g, '<span class="log-level-debug">$1</span>');

        // Highlight timestamps
        formatted = formatted.replace(/(\d{4}-\d{2}-\d{2}\s+\d{2}:\d{2}:\d{2})/g, '<span class="log-timestamp">$1</span>');

        // Strip ANSI color codes
        formatted = formatted.replace(/\x1b\[[0-9;]*m/g, '');

        return formatted;
    }

    function parseLogMeta(line) {
        const severityMatch = line.match(/\b(DEBUG|INFO|WARN|WARNING|ERROR|FATAL|CRITICAL)\b/);
        const severity = severityMatch ? severityMatch[1] : '';

        // Try to capture node/logger name in [name] after severity
        let node = '';
        const bracketMatches = line.match(/\[[^\]]+\]/g);
        if (bracketMatches && bracketMatches.length >= 2) {
            // Common format: [time] [SEVERITY] [name]
            node = bracketMatches[2] ? bracketMatches[2].replace(/^\[|\]$/g, '') : '';
        }
        return { severity, node };
    }

    function showError(message) {
        const contentDiv = document.getElementById('logContent');
        const statsDiv = document.getElementById('logStats');
        if (contentDiv) {
            contentDiv.innerHTML = `<span class="log-error">Error: ${escapeHtml(message)}</span>`;
        }
        if (statsDiv) statsDiv.style.display = 'none';
    }

    function showEmptyMessage(message) {
        const contentDiv = document.getElementById('logContent');
        const statsDiv = document.getElementById('logStats');
        if (contentDiv) {
            contentDiv.innerHTML = `<span class="log-empty">${escapeHtml(message)}</span>`;
        }
        if (statsDiv) statsDiv.style.display = 'none';
    }

    // ==========================================
    // Stats Updates
    // ==========================================
    function updateStats(data) {
        const statsDiv = document.getElementById('logStats');
        if (!statsDiv) return;

        const pathEl = document.getElementById('logPath');
        const totalEl = document.getElementById('logTotalLines');

        if (pathEl) {
            // Shorten path for display
            let displayPath = data.path || '';
            if (LOG_ROOT && displayPath.startsWith(LOG_ROOT)) {
                displayPath = displayPath.replace(LOG_ROOT, 'logs');
            } else if (PROJECT_ROOT && displayPath.startsWith(PROJECT_ROOT)) {
                displayPath = displayPath.replace(PROJECT_ROOT, '~');
            }
            pathEl.textContent = displayPath;
        }
        if (totalEl) totalEl.textContent = data.total_lines || data.logs?.length || 0;

        statsDiv.style.display = 'flex';
    }

    function updateShownCount(count) {
        const shownEl = document.getElementById('logShownLines');
        if (shownEl) shownEl.textContent = count;
    }

    function updateLastUpdated() {
        const lastUpdatedEl = document.getElementById('lastUpdated');
        if (lastUpdatedEl) {
            const now = new Date();
            const timeStr = now.toLocaleTimeString();
            lastUpdatedEl.textContent = `Updated: ${timeStr}`;
        }
    }

    // ==========================================
    // Search/Filter
    // ==========================================
    function onSearchKeyup(e) {
        if (e.key === 'Enter') {
            applySearchFilter();
        }
    }

    function onSearchInput() {
        applySearchFilter();
    }

    function applySearchFilter() {
        const searchTerm = document.getElementById('logSearch')?.value.trim();
        const severityFilter = document.getElementById('logSeverity')?.value || '';
        const nodeFilter = document.getElementById('logNode')?.value.trim().toLowerCase();
        const contentDiv = document.getElementById('logContent');

        if (!contentDiv || state.originalLogs.length === 0) return;

        let filtered = state.originalLogs;
        if (searchTerm) {
            filtered = filtered.filter(line =>
                line.toLowerCase().includes(searchTerm.toLowerCase())
            );
        }
        if (severityFilter) {
            filtered = filtered.filter(line => {
                const meta = parseLogMeta(line);
                if (severityFilter === 'WARN') {
                    return meta.severity === 'WARN' || meta.severity === 'WARNING';
                }
                return meta.severity === severityFilter;
            });
        }
        if (nodeFilter) {
            filtered = filtered.filter(line => {
                const meta = parseLogMeta(line);
                return meta.node.toLowerCase().includes(nodeFilter);
            });
        }

        displayLogs(filtered);
    }

    function clearFilter() {
        const searchInput = document.getElementById('logSearch');
        if (searchInput) searchInput.value = '';
        applySearchFilter();
    }

    // ==========================================
    // Auto Refresh
    // ==========================================
    function toggleAutoRefresh() {
        state.autoRefreshEnabled = !state.autoRefreshEnabled;

        const statusSpan = document.getElementById('autoRefreshStatus');
        const btn = document.getElementById('autoRefreshLogsBtn');

        if (state.autoRefreshEnabled) {
            stopLiveStream();
            if (statusSpan) statusSpan.textContent = 'On';
            if (btn) btn.classList.add('active');
            startAutoRefresh();
        } else {
            if (statusSpan) statusSpan.textContent = 'Off';
            if (btn) btn.classList.remove('active');
            stopAutoRefresh();
        }
    }

    function startAutoRefresh() {
        stopAutoRefresh();
        // NOTE: HTTP polling removed - use Live streaming (SSE) or manual refresh instead
        // Auto-refresh button now acts as a one-time refresh for user convenience
        loadLogs();
        console.log('[LogsViewer] Manual refresh triggered (auto-refresh via HTTP removed)');
    }

    function stopAutoRefresh() {
        if (state.autoRefreshTimer) {
            clearInterval(state.autoRefreshTimer);
            state.autoRefreshTimer = null;
            console.log('[LogsViewer] Auto-refresh stopped');
        }
    }

    function toggleLive() {
        state.liveEnabled = !state.liveEnabled;
        const statusSpan = document.getElementById('liveStatus');
        const btn = document.getElementById('liveLogsBtn');
        if (state.liveEnabled) {
            stopAutoRefresh();
            if (statusSpan) statusSpan.textContent = 'On';
            if (btn) btn.classList.add('active');
            startLiveStream();
        } else {
            if (statusSpan) statusSpan.textContent = 'Off';
            if (btn) btn.classList.remove('active');
            stopLiveStream();
        }
    }

    function startLiveStream() {
        stopLiveStream();
        if (state.currentCategory === 'session' && (!state.currentSession || !state.currentFile)) {
            showError('Please select a session and file');
            return;
        }
        const params = new URLSearchParams({
            category: state.currentCategory,
            file: state.currentFile,
            interval: (LIVE_REFRESH_DELAY / 1000).toFixed(1),
        });
        if (state.currentCategory === 'session') {
            params.append('session', state.currentSession);
        }
        state.liveSource = new EventSource(`/api/logs/stream?${params}`);
        state.liveSource.onmessage = (event) => {
            try {
                const data = JSON.parse(event.data);
                if (data.error) {
                    console.error('[LogsViewer] Live error:', data.error);
                    return;
                }
                if (data.lines && data.lines.length) {
                    const maxLines = parseInt(document.getElementById('logLines')?.value || 1000, 10);
                    state.originalLogs = state.originalLogs.concat(data.lines);
                    if (state.originalLogs.length > maxLines) {
                        state.originalLogs = state.originalLogs.slice(-maxLines);
                    }
                    applySearchFilter();
                    updateLastUpdated();
                }
            } catch (e) {
                console.error('[LogsViewer] Live parse error:', e);
            }
        };
        state.liveSource.onerror = () => {
            console.warn('[LogsViewer] Live stream disconnected');
        };
    }

    function stopLiveStream() {
        if (state.liveSource) {
            state.liveSource.close();
            state.liveSource = null;
        }
    }

    // ==========================================
    // Utility Functions
    // ==========================================
    // escapeHtml is now in main.js to avoid duplication

    function formatBytes(bytes) {
        if (bytes === 0) return '0 B';
        const k = 1024;
        const sizes = ['B', 'KB', 'MB', 'GB'];
        const i = Math.floor(Math.log(bytes) / Math.log(k));
        return parseFloat((bytes / Math.pow(k, i)).toFixed(1)) + ' ' + sizes[i];
    }

    function debounce(func, wait) {
        let timeout;
        return function executedFunction(...args) {
            const later = () => {
                clearTimeout(timeout);
                func(...args);
            };
            clearTimeout(timeout);
            timeout = setTimeout(later, wait);
        };
    }

    // Expose some functions for debugging
    window.LogsViewer = {
        loadLogs,
        toggleAutoRefresh,
        toggleLive,
        clearFilter,
        getState: () => ({ ...state })
    };

    console.log('[LogsViewer] Module loaded');
})();
