/**
 * ROS2 System Diagnostic - Sensors Page JavaScript
 * WebSocket-based real-time updates
 */

// Current sensor tab
let currentSensor = 'navi_lidar';

// ==========================================
// Initialization
// ==========================================

document.addEventListener('DOMContentLoaded', function() {
    initSensorTabs();
});

// ==========================================
// Tab Switching
// ==========================================

function initSensorTabs() {
    const tabs = document.querySelectorAll('.sensor-tab');
    const panels = document.querySelectorAll('.sensor-panel');

    tabs.forEach(tab => {
        tab.addEventListener('click', function() {
            const sensor = this.dataset.sensor;
            switchSensorTab(sensor);
        });
    });
}

function switchSensorTab(sensor) {
    document.querySelectorAll('.sensor-tab').forEach(tab => {
        tab.classList.toggle('active', tab.dataset.sensor === sensor);
    });

    document.querySelectorAll('.sensor-panel').forEach(panel => {
        panel.classList.toggle('active', panel.id === sensor + 'Panel');
    });

    currentSensor = sensor;
    // Update will come from WebSocket data
}

// ==========================================
// WebSocket Message Handlers
// ==========================================

// Override main.js placeholder function to handle sensor updates
function updateSensorsDisplay(sensorsData) {
    if (!sensorsData || !sensorsData.sensors) return;

    const sensors = sensorsData.sensors;

    // Update each sensor panel
    updateNaviLidarPanel(sensors.navi_lidar);
    updateUliLidarPanel(sensors.uli_lidar);
    updateCameraPanel(sensors.camera);
    updateImuPanel(sensors.imu);
    updateThrusterPanel(sensors.thruster);
}

function updateNaviLidarPanel(data) {
    if (!data) return;

    const badge = document.getElementById('naviLidarStatusBadge');
    if (badge) {
        badge.className = 'status-badge large ' + data.status;
        badge.textContent = data.status.toUpperCase();
    }

    const connStatus = document.getElementById('naviLidarConnStatus');
    const latencyEl = document.getElementById('naviLidarLatency');

    if (connStatus) {
        if (data.connected === 'Connected') {
            connStatus.textContent = 'Connected';
            connStatus.className = 'info-value text-success';
        } else {
            connStatus.textContent = 'Disconnected';
            connStatus.className = 'info-value text-danger';
        }
    }

    if (latencyEl && data.packet_loss) {
        latencyEl.textContent = data.packet_loss;
    }
}

function updateUliLidarPanel(data) {
    if (!data) return;

    const badge = document.getElementById('uliLidarStatusBadge');
    if (badge) {
        badge.className = 'status-badge large ' + data.status;
        badge.textContent = data.status.toUpperCase();
    }

    const connStatus = document.getElementById('uliLidarConnStatus');
    const latencyEl = document.getElementById('uliLidarLatency');

    if (connStatus) {
        if (data.connected === 'Connected') {
            connStatus.textContent = 'Connected';
            connStatus.className = 'info-value text-success';
        } else {
            connStatus.textContent = 'Disconnected';
            connStatus.className = 'info-value text-danger';
        }
    }

    if (latencyEl && data.packet_loss) {
        latencyEl.textContent = data.packet_loss;
    }
}

function updateCameraPanel(data) {
    if (!data) return;

    const badge = document.getElementById('cameraStatusBadge');
    if (badge) {
        badge.className = 'status-badge large ' + data.status;
        badge.textContent = data.status.toUpperCase();
    }

    const connStatus = document.getElementById('cameraConnStatus');
    if (connStatus) {
        if (data.connected === 'Connected') {
            connStatus.textContent = 'Connected';
            connStatus.className = 'info-value text-success';
        } else {
            connStatus.textContent = 'Disconnected';
            connStatus.className = 'info-value text-danger';
        }
    }
}

function updateImuPanel(data) {
    if (!data) return;

    const badge = document.getElementById('imuStatusBadge');
    if (badge) {
        badge.className = 'status-badge large ' + data.status;
        badge.textContent = data.status.toUpperCase();
    }

    const connStatus = document.getElementById('imuConnStatus');
    if (connStatus) {
        if (data.connected === 'Connected') {
            connStatus.textContent = 'Connected';
            connStatus.className = 'info-value text-success';
        } else {
            connStatus.textContent = 'Disconnected';
            connStatus.className = 'info-value text-danger';
        }
    }
}

function updateThrusterPanel(data) {
    if (!data) return;

    const badge = document.getElementById('thrusterStatusBadge');
    if (badge) {
        badge.className = 'status-badge large ' + data.status;
        badge.textContent = data.status.toUpperCase();
    }

    const tcpStatus = document.getElementById('thrusterTcpStatus');
    const latencyEl = document.getElementById('thrusterLatencyValue');

    if (tcpStatus) {
        if (data.connected === 'Connected') {
            tcpStatus.textContent = 'Connected';
            tcpStatus.className = 'info-value text-success';
        } else {
            tcpStatus.textContent = 'Disconnected';
            tcpStatus.className = 'info-value text-danger';
        }
    }

    if (latencyEl && data.packet_loss) {
        latencyEl.textContent = data.packet_loss + ' ms';
    }
}
