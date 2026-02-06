/**
 * ROS2 System Diagnostic - Sensors Page JavaScript
 * WebSocket-based real-time updates
 */

// Current sensor tab
let currentSensor = 'navi_lidar';
// Cache for incremental updates
let sensorsCache = {};

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
    if (!sensorsData) return;

    const partial = sensorsData.partial === true;
    const sensors = sensorsData.sensors || {};

    if (partial) {
        Object.entries(sensors).forEach(([name, patch]) => {
            sensorsCache[name] = { ...(sensorsCache[name] || {}), ...(patch || {}) };
        });
    } else {
        sensorsCache = sensors;
    }

    const allSensors = sensorsCache;

    // Update each sensor panel
    updateNaviLidarPanel(allSensors.navi_lidar);
    updateUliLidarPanel(allSensors.uli_lidar);
    updateCameraPanel(allSensors.camera);
    updateImuPanel(allSensors.imu);
    updateThrusterPanel(allSensors.thruster);
    updateBatteryPanel(allSensors.battery);
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

function updateBatteryPanel(data) {
    if (!data) return;

    const badge = document.getElementById('batteryStatusBadge');
    if (badge) {
        badge.className = 'status-badge large ' + data.status;
        badge.textContent = data.status.toUpperCase();
    }

    // Update voltage displays
    const voltages = data.voltages || {};
    const a0El = document.getElementById('batteryA0');
    const a1El = document.getElementById('batteryA1');
    const a2El = document.getElementById('batteryA2');
    const a3El = document.getElementById('batteryA3');

    if (a0El && voltages.channel_a0 !== undefined) {
        a0El.textContent = voltages.channel_a0.toFixed(2) + ' V';
        a0El.className = getVoltageClass(voltages.channel_a0);
    }
    if (a1El && voltages.channel_a1 !== undefined) {
        a1El.textContent = voltages.channel_a1.toFixed(2) + ' V';
    }
    if (a2El && voltages.channel_a2 !== undefined) {
        a2El.textContent = voltages.channel_a2.toFixed(2) + ' V';
        a2El.className = getVoltageClass(voltages.channel_a2);
    }
    if (a3El && voltages.channel_a3 !== undefined) {
        a3El.textContent = voltages.channel_a3.toFixed(2) + ' V';
    }

    // Update main voltage display
    const mainVoltageEl = document.getElementById('batteryMainVoltage');
    if (mainVoltageEl && data.value) {
        mainVoltageEl.textContent = data.value;
    }
}

function getVoltageClass(voltage) {
    // Returns CSS class based on voltage level (for 4S LiPo)
    if (voltage < 10.5) return 'text-danger';   // Critical
    if (voltage < 11.0) return 'text-warning';  // Low
    if (voltage > 14.4) return 'text-warning';  // Overvoltage
    return 'text-success';                      // Normal
}
