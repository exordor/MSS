/**
 * ROS2 System Diagnostic - Main JavaScript
 * WebSocket-based real-time updates
 */

// Configuration
const CONFIG = {
    chartUpdateInterval: 1000,
    maxRetries: 3,
    retryDelay: 5000,
    wsReconnectDelay: 1000,
    wsMaxReconnectDelay: 30000,
};

// State
let wsConnection = null;
let connectionState = 'disconnected';
let activeAlerts = {};
let bannerAutoHideTimer = null;
let initialDataPending = true;

// Latest cached state from WebSocket
let latestState = {
    sensors: null,
    ros2: null,
    ros2_control: null,
    rosbag: null,
    alerts: [],
};

// Colors
const COLORS = {
    ok: '#10b981',
    warning: '#f59e0b',
    critical: '#ef4444',
    unknown: '#6b7280',
    primary: '#3b82f6',
    primaryLight: '#60a5fa',
};

// ==========================================
// WebSocket Connection Manager
// ==========================================

class WSConnection {
    constructor(url) {
        this.url = url;
        this.ws = null;
        this.reconnectDelay = CONFIG.wsReconnectDelay;
        this.maxReconnectDelay = CONFIG.wsMaxReconnectDelay;
        this.reconnectAttempts = 0;
        this.handlers = {};
        this.isManualClose = false;
        this.pingInterval = null;

        this.connect();
    }

    connect() {
        const protocol = location.protocol === 'https:' ? 'wss:' : 'ws:';
        const wsUrl = this.url || `${protocol}//${location.host}/ws`;

        console.log(`[WS] Connecting to ${wsUrl}...`);
        console.log(`[WS] Protocol: ${protocol}, Host: ${location.host}`);
        this.ws = new WebSocket(wsUrl);
        console.log('[WS] WebSocket object created, readyState:', this.ws.readyState);

        this.ws.onopen = () => {
            console.log('[WS] Connected! readyState:', this.ws.readyState);
            this.reconnectAttempts = 0;
            this.reconnectDelay = CONFIG.wsReconnectDelay;
            updateConnectionStatus(true);

            // Send periodic ping to keep connection alive
            if (this.pingInterval) clearInterval(this.pingInterval);
            this.pingInterval = setInterval(() => {
                if (this.ws?.readyState === WebSocket.OPEN) {
                    console.log('[WS] Sending ping...');
                    this.ws.send('ping');
                }
            }, 30000);
        };

        this.ws.onclose = (event) => {
            console.log(`[WS] Disconnected (code: ${event.code})`);
            updateConnectionStatus(false);
            if (this.pingInterval) {
                clearInterval(this.pingInterval);
                this.pingInterval = null;
            }
            if (!this.isManualClose) {
                this.scheduleReconnect();
            }
        };

        this.ws.onerror = (error) => {
            console.error('[WS] Error:', error);
        };

        this.ws.onmessage = (event) => {
            try {
                // Handle ping/pong
                if (event.data === 'pong') {
                    console.log('[WS] Received pong');
                    return;
                }

                const msg = JSON.parse(event.data);
                console.log(`[WS] Received message: type=${msg.type}, timestamp=${msg.timestamp || 'N/A'}`);

                // Call registered handler for this message type
                if (this.handlers[msg.type]) {
                    this.handlers[msg.type](msg.data, msg.timestamp);
                }
            } catch (e) {
                console.error('[WS] Message error:', e, event.data);
            }
        };
    }

    scheduleReconnect() {
        this.reconnectAttempts++;
        const delay = this.reconnectDelay;
        console.log(`[WS] Reconnecting in ${delay}ms (attempt ${this.reconnectAttempts})`);
        setTimeout(() => this.connect(), delay);
        this.reconnectDelay = Math.min(
            this.reconnectDelay * 1.5,
            this.maxReconnectDelay
        );
    }

    on(eventType, callback) {
        this.handlers[eventType] = callback;
    }

    send(data) {
        if (this.ws?.readyState === WebSocket.OPEN) {
            this.ws.send(JSON.stringify(data));
        }
    }

    /**
     * 订阅频道
     * @param {string} channel - 频道名称 (sensors, alerts, ros2, ros2_control, rosbag)
     */
    subscribe(channel) {
        if (this.ws?.readyState === WebSocket.OPEN) {
            this.ws.send(`subscribe:${channel}`);
            console.log(`[WS] Subscribed to ${channel}`);
        }
    }

    /**
     * 取消订阅频道
     * @param {string} channel - 频道名称
     */
    unsubscribe(channel) {
        if (this.ws?.readyState === WebSocket.OPEN) {
            this.ws.send(`unsubscribe:${channel}`);
            console.log(`[WS] Unsubscribed from ${channel}`);
        }
    }

    /**
     * 设置只接收告警（低带宽模式）
     */
    lowBandwidthMode() {
        // 取消订阅传感器
        this.unsubscribe('sensors');
        this.unsubscribe('ros2');
        // 只保留告警
        console.log('[WS] Low bandwidth mode enabled (alerts only)');
    }

    close() {
        this.isManualClose = true;
        if (this.ws) {
            this.ws.close();
        }
        if (this.pingInterval) {
            clearInterval(this.pingInterval);
        }
    }
}

// ==========================================
// WebSocket Message Handlers
// ==========================================

function handleFullState(data, timestamp) {
    // Handle initial full state on connection
    console.log('[WS] Received full state');

    if (data.sensors) latestState.sensors = data.sensors;
    if (data.ros2) latestState.ros2 = data.ros2;
    if (data.ros2_control) latestState.ros2_control = data.ros2_control;
    if (data.rosbag) latestState.rosbag = data.rosbag;
    if (data.alerts) latestState.alerts = data.alerts;

    // Update UI components - IMPORTANT: update ROS2 FIRST, then sensors
    // This ensures ros2NodesCache and ros2TopicsCache are populated before sensor display
    if (typeof updateROS2Display === 'function') updateROS2Display(data.ros2, data.ros2_control);
    if (typeof updateSensorsDisplay === 'function') updateSensorsDisplay(data.sensors);
    if (typeof updateRosbagDisplay === 'function') updateRosbagDisplay(data.rosbag);
    if (typeof updateAlertsDisplay === 'function') updateAlertsDisplay(data.alerts);

    if (data.sensors && hasSensorUI()) {
        markInitialDataUpdated();
    } else if (!hasSensorUI()) {
        markInitialDataUpdated();
    }
    updateLastUpdated();
}

function handleStateUpdate(data, timestamp) {
    // Handle incremental state updates
    console.log('[WS] Received state update');

    // Update ROS2 data FIRST, then sensors (so caches are populated)
    if (data.ros2) {
        latestState.ros2 = data.ros2;
        if (typeof updateROS2Display === 'function') {
            updateROS2Display(data.ros2, data.ros2_control);
        }
    }
    if (data.sensors) {
        latestState.sensors = data.sensors;
        if (typeof updateSensorsDisplay === 'function') updateSensorsDisplay(data.sensors);
    }
    if (data.ros2_control) {
        latestState.ros2_control = data.ros2_control;
        if (typeof updateROS2ControlStatus === 'function') {
            updateROS2ControlStatusFromWS(data.ros2_control);
        }
    }
    if (data.rosbag) {
        latestState.rosbag = data.rosbag;
        if (typeof updateRosbagDisplay === 'function') updateRosbagDisplay(data.rosbag);
    }
    if (data.alerts) {
        latestState.alerts = data.alerts;
        if (typeof updateAlertsDisplay === 'function') updateAlertsDisplay(data.alerts);
        checkForNewAlertsFromWS(data.alerts);
    }

    if (!hasSensorUI()) {
        markInitialDataUpdated();
    }
    updateLastUpdated();
}

function handleAlert(data, timestamp) {
    // Handle real-time alert push (single alert)
    console.log('[WS] Received real-time alert:', data);

    // Add to alerts state
    if (!latestState.alerts) latestState.alerts = [];
    latestState.alerts.unshift(data);  // Add to beginning

    // Update active alerts tracking
    activeAlerts[data.id] = data;

    // Show notification banner immediately
    showNotificationBanner(data);

    // Update notification badge
    updateNotificationBadge(latestState.alerts.length);

    // Update alerts display if function exists
    if (typeof updateAlertsDisplay === 'function') {
        updateAlertsDisplay(latestState.alerts);
    }
}

function handleSensorsUpdate(data, timestamp) {
    // Handle sensors channel update
    console.log('[WS] Received sensors update');
    if (data && data.sensors) {
        if (data.partial) {
            if (!latestState.sensors || !latestState.sensors.sensors) {
                latestState.sensors = { sensors: {} };
            }
            latestState.sensors.sensors = mergeSensorUpdates(latestState.sensors.sensors, data.sensors);
        } else {
            latestState.sensors = data;
        }
    }
    if (typeof updateSensorsDisplay === 'function') updateSensorsDisplay(data);
    if (hasSensorUI()) {
        markInitialDataUpdated();
    }
    updateLastUpdated();
}

function handleRos2Update(data, timestamp) {
    // Handle ROS2 channel update
    console.log('[WS] Received ROS2 update');
    if (data) latestState.ros2 = data;
    if (typeof updateROS2Display === 'function') {
        updateROS2Display(latestState.ros2, latestState.ros2_control);
    }
    updateLastUpdated();
}

function handleRos2ControlUpdate(data, timestamp) {
    // Handle ROS2 control channel update
    console.log('[WS] Received ROS2 control update');
    if (data) latestState.ros2_control = data;
    if (typeof updateROS2ControlStatus === 'function') {
        updateROS2ControlStatusFromWS(data);
    }
    updateLastUpdated();
}

function handleConnectivityUpdate(data, timestamp) {
    console.log('[WS] Received connectivity update');
    if (data && data.sensors) {
        if (!latestState.sensors || !latestState.sensors.sensors) {
            latestState.sensors = { sensors: {} };
        }
        latestState.sensors.sensors = mergeSensorUpdates(latestState.sensors.sensors, data.sensors);
    }
    if (typeof updateSensorsDisplay === 'function') {
        updateSensorsDisplay({ sensors: data.sensors, partial: true });
    }
    if (hasSensorUI()) {
        markInitialDataUpdated();
    }
    updateLastUpdated();
}

function handleRosbagUpdate(data, timestamp) {
    // Handle rosbag channel update
    console.log('[WS] Received rosbag update');
    if (data) latestState.rosbag = data;
    if (typeof updateRosbagDisplay === 'function') updateRosbagDisplay(data);
    updateLastUpdated();
}

function checkForNewAlertsFromWS(alerts) {
    // Check for new alerts and show notification
    if (!alerts || alerts.length === 0) {
        updateNotificationBadge(0);
        return;
    }

    // Find new alerts (not in our tracking map)
    const newAlerts = alerts.filter(alert => !activeAlerts[alert.id]);

    if (newAlerts.length > 0) {
        // Sort by severity (critical first)
        newAlerts.sort((a, b) => {
            if (a.severity === 'critical' && b.severity !== 'critical') return -1;
            if (a.severity !== 'critical' && b.severity === 'critical') return 1;
            return new Date(b.created_at) - new Date(a.created_at);
        });

        // Show notification for the most important new alert
        showNotificationBanner(newAlerts[0]);
    }

    // Update active alerts map
    activeAlerts = {};
    alerts.forEach(alert => {
        activeAlerts[alert.id] = alert;
    });

    // Update notification badge
    updateNotificationBadge(alerts.length);
}

// ==========================================
// Utility Functions
// ==========================================

function formatBytes(bytes) {
    if (bytes === 0) return '0 B';
    const k = 1024;
    const sizes = ['B', 'KB', 'MB', 'GB', 'TB'];
    const i = Math.floor(Math.log(bytes) / Math.log(k));
    return parseFloat((bytes / Math.pow(k, i)).toFixed(1)) + ' ' + sizes[i];
}

function formatFrequency(hz) {
    if (hz >= 1) {
        return hz.toFixed(1) + ' Hz';
    } else {
        return (hz * 1000).toFixed(0) + ' mHz';
    }
}

function formatPercent(value) {
    return value.toFixed(1) + '%';
}

function getStatusClass(status) {
    const statusMap = {
        'ok': 'ok',
        'warning': 'warning',
        'critical': 'critical',
        'unknown': 'unknown',
    };
    return statusMap[status] || 'unknown';
}

function getStatusColor(status) {
    const colorMap = {
        'ok': COLORS.ok,
        'warning': COLORS.warning,
        'critical': COLORS.critical,
        'unknown': COLORS.unknown,
    };
    return colorMap[status] || COLORS.unknown;
}

function updateConnectionStatus(connected) {
    const statusEl = document.getElementById('connectionStatus');
    if (!statusEl) return;

    if (connected) {
        statusEl.className = 'connection-status connected';
        statusEl.innerHTML = '<i class="fa-solid fa-circle"></i> WebSocket Connected';
        connectionState = 'connected';
    } else {
        statusEl.className = 'connection-status disconnected';
        statusEl.innerHTML = '<i class="fa-solid fa-circle"></i> Disconnected';
        connectionState = 'disconnected';
    }
}

function updateLastUpdated() {
    const el = document.getElementById('lastUpdated');
    if (el) {
        const now = new Date();
        el.textContent = now.toLocaleTimeString();
    }
}

function mergeSensorUpdates(current, updates) {
    const merged = { ...(current || {}) };
    Object.entries(updates || {}).forEach(([name, patch]) => {
        merged[name] = { ...(merged[name] || {}), ...(patch || {}) };
    });
    return merged;
}

function hasSensorUI() {
    return !!(document.getElementById('sensorsTableBody') ||
        document.getElementById('naviLidarStatusBadge'));
}

function showInitialDataPending() {
    initialDataPending = true;
    const el = document.getElementById('lastUpdated');
    if (el) el.textContent = 'Waiting for data update...';
    showNotification('warning', 'Waiting for data update...');
}

function markInitialDataUpdated() {
    if (!initialDataPending) return;
    initialDataPending = false;
    showNotification('success', 'Data updated');
}

function escapeHtml(text) {
    const div = document.createElement('div');
    div.textContent = text;
    return div.innerHTML;
}

// ==========================================
// Chart Helpers
// ==========================================

function createLineChart(canvasId, label, color) {
    const canvas = document.getElementById(canvasId);
    if (!canvas) return null;

    const ctx = canvas.getContext('2d');
    return new Chart(ctx, {
        type: 'line',
        data: {
            labels: [],
            datasets: [{
                label: label,
                data: [],
                borderColor: color,
                backgroundColor: color + '20',
                borderWidth: 2,
                fill: true,
                tension: 0.4,
                pointRadius: 0,
            }]
        },
        options: {
            responsive: true,
            maintainAspectRatio: false,
            animation: { duration: 0 },
            plugins: {
                legend: { display: false },
            },
            scales: {
                x: { display: false },
                y: {
                    beginAtZero: true,
                    grid: { color: '#e5e7eb' },
                    ticks: { font: { size: 10 } }
                }
            }
        }
    });
}

function updateChart(chart, value, maxPoints = 60) {
    if (!chart) return;
    const now = new Date();
    const timeLabel = now.toLocaleTimeString();
    chart.data.labels.push(timeLabel);
    chart.data.datasets[0].data.push(value);
    if (chart.data.labels.length > maxPoints) {
        chart.data.labels.shift();
        chart.data.datasets[0].data.shift();
    }
    chart.update('none');
}

function createDoughnutChart(canvasId, value, color) {
    const canvas = document.getElementById(canvasId);
    if (!canvas) return null;
    const ctx = canvas.getContext('2d');
    return new Chart(ctx, {
        type: 'doughnut',
        data: {
            datasets: [{
                data: [value, 100 - value],
                backgroundColor: [color, '#e5e7eb'],
                borderWidth: 0,
            }]
        },
        options: {
            responsive: true,
            maintainAspectRatio: false,
            cutout: '75%',
            plugins: {
                legend: { display: false },
                tooltip: { enabled: false }
            }
        }
    });
}

function updateDoughnutChart(chart, value, color) {
    if (!chart) return;
    chart.data.datasets[0].data = [value, 100 - value];
    chart.data.datasets[0].backgroundColor = [color, '#e5e7eb'];
    chart.update();
}

// ==========================================
// API Helpers (for POST actions only)
// ==========================================

const API = {
    ros2: {
        control: {
            start: () => fetch('/api/ros2/control/start', {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' }
            }).then(r => r.json()),
            stop: () => fetch('/api/ros2/control/stop', {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' }
            }).then(r => r.json()),
            logs: (lines = 100) => fetch(`/api/ros2/control/logs?lines=${lines}`).then(r => r.json()),
        },
    },
    rosbag: {
        start: (topics) => fetch('/api/rosbag/start', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ topics })
        }).then(r => r.json()),
        stop: () => fetch('/api/rosbag/stop', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' }
        }).then(r => r.json()),
    },
    alerts: {
        resolve: (id) => fetch(`/api/alerts/${id}/resolve`, {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' }
        }).then(r => r.json()),
        resolveAll: () => fetch('/api/alerts/resolve_all', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' }
        }).then(r => r.json()),
        ignore: (id) => fetch(`/api/alerts/${id}/ignore`, {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' }
        }).then(r => r.json()),
        ignoreAll: () => fetch('/api/alerts/ignore_all', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' }
        }).then(r => r.json()),
        stats: () => fetch('/api/alerts/stats').then(r => r.json()),
        bySensor: (sensor, limit = 50) => fetch(`/api/alerts/sensor/${sensor}?limit=${limit}`).then(r => r.json()),
        bySeverity: (severity, limit = 50) => fetch(`/api/alerts/severity/${severity}?limit=${limit}`).then(r => r.json()),
    },
    tools: {
        ping: (host, count = 4, timeout = 2) => fetch('/api/tools/ping', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ host, count, timeout })
        }).then(r => r.json()),
        configValidate: (type = 'all') => fetch('/api/tools/config-validate', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ type })
        }).then(r => r.json()),
        ptpStatus: () => fetch('/api/tools/ptp/status', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' }
        }).then(r => r.json()),
        ptpSyncVerify: () => fetch('/api/tools/ptp/sync-verify', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' }
        }).then(r => r.json()),
    },
};

// ROS2 Control Functions are now in dashboard.js to avoid duplication

function updateROS2ControlStatusFromWS(status) {
    // Update ROS2 control status from WebSocket data
    const indicator = document.getElementById('ros2ControlIndicator');
    const statusText = document.getElementById('ros2ControlStatusText');
    const detail = document.getElementById('ros2ControlDetail');
    const startBtn = document.getElementById('startRos2Btn');
    const stopBtn = document.getElementById('stopRos2Btn');

    if (status) {
        if (indicator) {
            indicator.className = 'status-indicator ' + (status.running ? 'ok' : 'unknown');
        }
        if (statusText) {
            statusText.textContent = status.running ? 'Running' : 'Stopped';
        }
        if (detail) {
            detail.textContent = status.running ?
                `PID: ${status.pid}` : 'ROS2 drivers stopped';
        }
        if (startBtn && stopBtn) {
            startBtn.disabled = status.running;
            stopBtn.disabled = !status.running;
        }
    } else {
        if (indicator) indicator.className = 'status-indicator unknown';
        if (statusText) statusText.textContent = 'Unknown';
        if (detail) detail.textContent = 'Unable to get status';
    }
}

async function updateROS2ControlStatus() {
    // Fallback: fetch ROS2 control status via HTTP
    try {
        const response = await fetch('/api/ros2/control/status');
        const result = await response.json();
        if (result.success) {
            updateROS2ControlStatusFromWS(result.data);
        }
    } catch (error) {
        console.error('Error updating ROS2 control status:', error);
    }
}

// ==========================================
// Notification Functions
// ==========================================

function showNotification(type, message) {
    const existing = document.querySelector('.notification');
    if (existing) existing.remove();

    const notification = document.createElement('div');
    notification.className = `notification ${type}`;
    notification.innerHTML = `
        <i class="fa-solid ${type === 'success' ? 'fa-check-circle' : 'fa-exclamation-circle'}"></i>
        <span>${escapeHtml(message)}</span>
    `;

    document.body.appendChild(notification);

    setTimeout(() => notification.classList.add('show'), 10);
    setTimeout(() => {
        notification.classList.remove('show');
        setTimeout(() => notification.remove(), 300);
    }, 5000);
}

function showNotificationBanner(alert) {
    const banner = document.getElementById('alertNotificationBanner');
    const message = document.getElementById('notificationMessage');

    if (!banner || !message) return;

    if (bannerAutoHideTimer) {
        clearTimeout(bannerAutoHideTimer);
    }

    const sensorName = formatAlertSensorName(alert.sensor);
    banner.className = `alert-notification-banner ${alert.severity}`;
    message.innerHTML = `<strong>${sensorName}</strong>: ${alert.message}`;
    banner.classList.remove('hidden');

    bannerAutoHideTimer = setTimeout(() => closeNotificationBanner(), 10000);
}

function closeNotificationBanner() {
    const banner = document.getElementById('alertNotificationBanner');
    if (banner) {
        banner.classList.add('hidden');
    }
    if (bannerAutoHideTimer) {
        clearTimeout(bannerAutoHideTimer);
        bannerAutoHideTimer = null;
    }
}

function updateNotificationBadge(count) {
    const badge = document.getElementById('alertNotificationBadge');
    if (!badge) return;
    badge.textContent = count;
    if (count > 0) {
        badge.classList.add('visible');
    } else {
        badge.classList.remove('visible');
    }
}

// formatAlertSensorName is now in alerts.js (AlertManager.formatSensorName method)
// Placeholder update functions are removed - they are overridden by page-specific scripts

// ==========================================
// Initialization
// ==========================================

document.addEventListener('DOMContentLoaded', function() {
    console.log('[Main] DOM loaded, initializing WebSocket...');
    console.log('[Main] Current URL:', window.location.href);
    console.log('[Main] Host:', window.location.host);
    console.log('[Main] Protocol:', window.location.protocol);

    // Show pending data message on page load/refresh
    showInitialDataPending();

    // Initialize WebSocket connection
    console.log('[Main] Creating WSConnection instance...');
    wsConnection = new WSConnection();
    // Expose globally for testing/debugging
    window.wsConnection = wsConnection;

    // Register WebSocket message handlers
    console.log('[Main] Registering message handlers...');
    wsConnection.on('full_state', handleFullState);
    wsConnection.on('state_update', handleStateUpdate);
    wsConnection.on('alert', handleAlert);  // Real-time alert push
    // Channel-based handlers
    wsConnection.on('sensors_update', handleSensorsUpdate);
    wsConnection.on('connectivity_update', handleConnectivityUpdate);
    wsConnection.on('ros2_update', handleRos2Update);
    wsConnection.on('ros2_control_update', handleRos2ControlUpdate);
    wsConnection.on('rosbag_update', handleRosbagUpdate);

    // Initial update
    updateLastUpdated();

    console.log('[Main] WebSocket connection initialized');
    console.log('[Main] Connection object:', wsConnection);
});

// Cleanup on page unload
window.addEventListener('beforeunload', function() {
    if (wsConnection) {
        wsConnection.close();
    }
});
