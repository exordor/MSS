/**
 * ROS2 System Diagnostic - Dashboard JavaScript
 * WebSocket-based real-time updates
 */

// Sensor update tracking
let sensorsLastUpdate = 0;
let sensorsUpdateInterval = 1000; // 1 second (matching backend)

// Local cache for sensor data (from WebSocket)
let sensorsCache = {};
let ros2NodesCache = [];
let ros2TopicsCache = [];

// ==========================================
// Initialization
// ==========================================

document.addEventListener('DOMContentLoaded', function() {
    console.log('[Dashboard] DOMContentLoaded, initializing...');
    initRosbagControls();
    initSensorsTable();
    initROS2Controls();
    initTimeStatus();
});

function initSensorsTable() {
    const tableBody = document.getElementById('sensorsTableBody');
    if (!tableBody) return;

    const sensors = SensorCatalog.getNames();
    let html = '';
    for (const sensor of sensors) {
        const info = SensorCatalog.get(sensor);
        html += `
            <tr id="row-${sensor}" data-sensor="${sensor}">
                <td>
                    <div class="sensor-name">
                        <i class="fa-solid ${info.icon}"></i>
                        <span>${info.name}</span>
                    </div>
                </td>
                <td><span class="text-muted">--</span></td>
                <td><span class="text-muted">--</span></td>
                <td><span class="text-muted">--</span></td>
                <td><span class="status-badge stopped">--</span></td>
            </tr>
        `;
    }
    tableBody.innerHTML = html;
}

// ==========================================
// Time Status (System + PHC)
// ==========================================

let timeStatusTimer = null;

function initTimeStatus() {
    const systemEl = document.getElementById('systemTimeValue');
    if (!systemEl) return;

    const refreshBtn = document.getElementById('timeRefreshBtn');
    if (refreshBtn) {
        refreshBtn.addEventListener('click', () => refreshTimeStatus(true));
    }

    refreshTimeStatus(false);

    const interval = (typeof TIME_REFRESH_INTERVAL !== 'undefined' ? TIME_REFRESH_INTERVAL : 1000);
    if (timeStatusTimer) clearInterval(timeStatusTimer);
    timeStatusTimer = setInterval(() => refreshTimeStatus(false), Math.max(500, interval));
}

async function refreshTimeStatus(manual = false) {
    const refreshBtn = document.getElementById('timeRefreshBtn');
    const originalIcon = refreshBtn?.querySelector('i')?.className;

    if (manual && refreshBtn) {
        refreshBtn.querySelector('i').className = 'fa-solid fa-rotate fa-spin';
    }

    try {
        const response = await fetch('/api/time/status');
        const result = await response.json();
        if (result.success && result.data) {
            updateTimeDisplay(result.data);
        }
    } catch (error) {
        console.error('Error refreshing time status:', error);
        const metaEl = document.getElementById('timeMeta');
        if (metaEl) metaEl.textContent = 'Error: failed to load time status';
    } finally {
        if (manual && refreshBtn) {
            setTimeout(() => {
                refreshBtn.querySelector('i').className = originalIcon || 'fa-solid fa-rotate';
            }, 300);
        }
    }
}

function updateTimeDisplay(data) {
    const systemEl = document.getElementById('systemTimeValue');
    const metaEl = document.getElementById('timeMeta');

    if (!systemEl || !metaEl) return;

    const system = data.system || {};

    systemEl.textContent = system.display || system.iso || '--';

    const notice = "Jetson system time is sourced from TimeMachine. Make sure TimeMachine is running and GPS time is locked before PTP sync starts. If you don't need this, run timedatectl set-ntp true to use network time.";
    const tzText = system.timezone ? `TZ: ${system.timezone} · ` : '';
    metaEl.innerHTML = `<i class="fa-solid fa-triangle-exclamation"></i><span>${tzText}${notice}</span>`;
}

// ==========================================
// WebSocket Message Handlers
// ==========================================

// ==========================================
// // Refresh Functions
// // ==========================================

async function refreshSensors() {
    const btn = document.getElementById('refreshSensorsBtn');
    const previewBtn = document.getElementById('refreshArduinoPreviewBtn');
    const originalIcon = btn?.querySelector('i')?.className;
    const previewOriginalIcon = previewBtn?.querySelector('i')?.className;

    // Show spinning animation
    if (btn) {
        btn.querySelector('i').className = 'fa-solid fa-rotate fa-spin';
    }
    if (previewBtn) {
        previewBtn.querySelector('i').className = 'fa-solid fa-rotate fa-spin';
    }

    try {
        // Fetch latest sensor status via HTTP (fallback)
        const response = await fetch('/api/sensors/status');
        const result = await response.json();

        if (result.success) {
            updateSensorsDisplay(result.data);
            // Reset last update time
            sensorsLastUpdate = Date.now();
            updateSensorsLastUpdate();
        }
    } catch (error) {
        console.error('Error refreshing sensors:', error);
    } finally {
        // Restore icon after short delay
        setTimeout(() => {
            if (btn) {
                btn.querySelector('i').className = originalIcon || 'fa-solid fa-rotate';
            }
            if (previewBtn) {
                previewBtn.querySelector('i').className = previewOriginalIcon || 'fa-solid fa-rotate';
            }
        }, 500);
    }
}

function updateSensorsLastUpdate() {
    // Update the last update time display in sensor card
    const lastUpdateEl = document.getElementById('sensorsLastUpdate');
    if (lastUpdateEl && sensorsLastUpdate > 0) {
        const elapsed = Math.floor((Date.now() - sensorsLastUpdate) / 1000);
        lastUpdateEl.textContent = `Updated ${elapsed}s ago`;
    }
}

// Update elapsed time every second
setInterval(updateSensorsLastUpdate, 1000);

// Override main.js placeholder functions with actual implementations
function updateSensorsDisplay(sensorsData) {
    if (!sensorsData) return;

    const partial = sensorsData.partial === true;
    const sensors = sensorsData.sensors || {};
    const tableBody = document.getElementById('sensorsTableBody');
    const countEl = document.getElementById('sensorsCount');

    if (!tableBody) return;

    // Update cache (merge for partial updates, per-sensor)
    if (partial) {
        Object.entries(sensors).forEach(([name, patch]) => {
            sensorsCache[name] = { ...(sensorsCache[name] || {}), ...(patch || {}) };
        });
    } else {
        sensorsCache = sensors;
    }

    const allSensors = sensorsCache;

    // Update temperature & humidity display in ROS2 Control card
    // Use cached allSensors to ensure temp_humidity persists across partial updates
    updateTempHumidityDisplay(allSensors);
    updateArduinoSummaryCard(allSensors);

    // Track counts
    const counts = { ok: 0, connected: 0, warning: 0, stopped: 0, disconnected: 0, critical: 0 };

    // Update each sensor row
    for (const [sensorName, sensorData] of Object.entries(allSensors)) {
        const status = sensorData.status || 'stopped';
        // For thruster, use 'connected' field
        // For other sensors, use 'connected' field
        const connected = sensorData.connected === 'Connected';

        // Update counts
        if (status === 'ok') counts.ok++;
        else if (status === 'connected') counts.connected++;
        else if (status === 'warning') counts.warning++;
        else if (status === 'stopped') counts.stopped++;
        else if (status === 'disconnected') counts.disconnected++;
        else if (status === 'critical') counts.critical++;

        const showNodeTopic = SensorCatalog.shouldShowNodeTopic(sensorName);
        const nodeAvailable = SensorCatalog.resolveNodeAvailable(
            sensorName,
            ros2NodesCache,
            sensorData.node_available
        );
        const topicAvailable = SensorCatalog.resolveTopicAvailable(
            sensorName,
            ros2TopicsCache,
            sensorData.topic_available
        );

        const row = document.getElementById(`row-${sensorName}`);
        if (row) {
            const nodeCell = showNodeTopic ? getStatusIcon(nodeAvailable) : '<span class="text-muted">N/A</span>';
            const topicCell = showNodeTopic ? getStatusIcon(topicAvailable) : '<span class="text-muted">N/A</span>';
            const info = SensorCatalog.get(sensorName) || { icon: 'fa-microchip', name: sensorName };

            row.innerHTML = `
                <td>
                    <div class="sensor-name">
                        <i class="fa-solid ${info.icon}"></i>
                        <span>${info.name}</span>
                    </div>
                </td>
                <td>${getStatusIcon(connected)}</td>
                <td>${nodeCell}</td>
                <td>${topicCell}</td>
                <td><span class="status-badge ${status}">${status.toUpperCase()}</span></td>
            `;
        }
    }

    // Update summary count
    const okTotal = counts.ok;
    const total = okTotal + counts.connected + counts.warning + counts.disconnected + counts.critical;
    const stoppedCount = counts.stopped;

    if (countEl) {
        if (total > 0 || stoppedCount > 0) {
            const allSensors = okTotal + counts.connected + counts.warning + counts.disconnected + counts.critical + stoppedCount;
            countEl.textContent = `${okTotal}/${allSensors} OK`;
            countEl.className = 'status-count ' + (
                counts.critical > 0 || counts.disconnected > 0 ? 'critical' :
                counts.warning > 0 ? 'warning' : 'ok'
            );
        } else {
            countEl.textContent = '--';
            countEl.className = 'status-count';
        }
    }
}

function updateTempHumidityDisplay(sensors) {
    const tempHumidityEl = document.getElementById('tempHumidityValue');
    if (!tempHumidityEl) {
        console.log('[TempHumidity] Element not found');
        return;
    }

    console.log('[TempHumidity] sensors:', sensors);
    const thruster = sensors && sensors.thruster;
    console.log('[TempHumidity] thruster:', thruster);
    const tempHumidity = thruster && thruster.temp_humidity;
    console.log('[TempHumidity] temp_humidity:', tempHumidity);

    if (tempHumidity && tempHumidity.temp1 !== null && tempHumidity.temp1 !== undefined) {
        const temp1 = tempHumidity.temp1.toFixed(1);
        const hum1 = tempHumidity.humidity1.toFixed(0);
        
        // Show both sensors if available
        if (tempHumidity.temp2 !== null && tempHumidity.temp2 !== undefined) {
            const temp2 = tempHumidity.temp2.toFixed(1);
            const hum2 = tempHumidity.humidity2.toFixed(0);
            tempHumidityEl.textContent = `JetsonBox: ${temp1}°C/${hum1}% | ArduinoBox: ${temp2}°C/${hum2}%`;
        } else {
            tempHumidityEl.textContent = `${temp1}°C / ${hum1}%`;
        }
        console.log('[TempHumidity] Updated to:', tempHumidityEl.textContent);
    } else {
        tempHumidityEl.textContent = '--';
        console.log('[TempHumidity] No data, showing --');
    }
}

function updateArduinoSummaryCard(sensors) {
    const primaryEl = document.getElementById('arduinoSummaryPrimary');
    const secondaryEl = document.getElementById('arduinoSummarySecondary');
    const batteryEl = document.getElementById('arduinoSummaryBattery');
    const pi5El = document.getElementById('arduinoSummaryPi5');
    const pi5AuxEl = document.getElementById('arduinoSummaryPi5Aux');
    const pi5LinkEl = document.getElementById('arduinoSummaryPi5Link');
    const updatedEl = document.getElementById('arduinoSummaryUpdated');
    if (!primaryEl || !secondaryEl || !batteryEl || !updatedEl) return;

    const arduino = sensors && sensors.thruster;
    const battery = sensors && sensors.battery;
    const pi5 = sensors && sensors.pi5_sensors;
    const tempHumidity = arduino && arduino.temp_humidity ? arduino.temp_humidity : {};
    const statusData = arduino && arduino.thruster_status ? arduino.thruster_status : {};
    const flowData = arduino && arduino.flow_data ? arduino.flow_data : {};
    const voltages = battery && battery.voltages ? battery.voltages : {};
    const wq = pi5 && pi5.water_quality ? pi5.water_quality : {};

    const primaryParts = [];
    if (tempHumidity.temp1 !== null && tempHumidity.temp1 !== undefined &&
        tempHumidity.humidity1 !== null && tempHumidity.humidity1 !== undefined) {
        primaryParts.push(`JetsonBox: ${tempHumidity.temp1.toFixed(1)}°C/${tempHumidity.humidity1.toFixed(0)}%`);
    }
    if (tempHumidity.temp2 !== null && tempHumidity.temp2 !== undefined &&
        tempHumidity.humidity2 !== null && tempHumidity.humidity2 !== undefined) {
        primaryParts.push(`ArduinoBox: ${tempHumidity.temp2.toFixed(1)}°C/${tempHumidity.humidity2.toFixed(0)}%`);
    }
    primaryEl.textContent = primaryParts.length > 0 ? primaryParts.join(' | ') : '--';

    const secondaryParts = [];
    if (statusData.mode_label) {
        const leftPwm = statusData.left_pwm !== null && statusData.left_pwm !== undefined ? statusData.left_pwm : '--';
        const rightPwm = statusData.right_pwm !== null && statusData.right_pwm !== undefined ? statusData.right_pwm : '--';
        secondaryParts.push(`PWM: ${statusData.mode_label} ${leftPwm}/${rightPwm}`);
    }
    if (flowData.velocity_ms !== null && flowData.velocity_ms !== undefined) {
        secondaryParts.push(`Speed: ${flowData.velocity_ms.toFixed(2)} m/s`);
    }
    secondaryEl.textContent = secondaryParts.length > 0 ? secondaryParts.join(' | ') : '--';

    const batteryParts = [];
    ['channel_a0', 'channel_a1', 'channel_a2', 'channel_a3'].forEach((channel, index) => {
        const value = voltages[channel];
        if (value !== null && value !== undefined) {
            batteryParts.push(`A${index}: ${value.toFixed(2)}V`);
        }
    });
    batteryEl.textContent = batteryParts.length > 0 ? `Battery: ${batteryParts.join(' | ')}` : 'Battery: --';

    const pi5PrimaryParts = [
        formatPi5Metric('pH', wq.ph_ph, '', 2),
        formatPi5Metric('Redox', wq.ph_redox_mv, ' mV', 1),
        formatPi5Metric('O2', wq.optod_o2_mgl, ' mg/L', 2),
        formatPi5Metric('Sat', wq.optod_o2_saturation_pct, ' %', 1),
        formatPi5Metric('Cond', wq.c4e_conductivity_uscm, ' µS/cm', 2),
    ].filter(Boolean);
    if (pi5El) {
        pi5El.textContent = pi5PrimaryParts.length > 0
            ? `Pi5 Water: ${pi5PrimaryParts.join(' | ')}`
            : 'Pi5 Water: --';
    }

    const pi5AuxParts = [
        formatPi5Metric('C4E T', wq.c4e_temp_c, '°C', 1),
        formatPi5Metric('OPTOD T', wq.optod_temp_c, '°C', 1),
        formatPi5Metric('pH T', wq.ph_temp_c, '°C', 1),
        formatPi5Metric('O2 ppm', wq.optod_o2_ppm, '', 2),
        formatPi5Metric('Sal', wq.c4e_salinity_ppt, ' ppt', 4),
        formatPi5Metric('TDS', wq.c4e_tds_ppm, ' ppm', 2),
        formatPi5Metric('pH mV', wq.ph_mv, ' mV', 1),
    ].filter(Boolean);
    if (pi5AuxEl) {
        pi5AuxEl.textContent = pi5AuxParts.length > 0
            ? `Pi5 Detail: ${pi5AuxParts.join(' | ')}`
            : 'Pi5 Detail: --';
    }

    const pi5LinkParts = [];
    if (pi5 && pi5.water_quality_age_s !== undefined && pi5.water_quality_age_s !== null) {
        pi5LinkParts.push(`Age: ${Number(pi5.water_quality_age_s).toFixed(1)}s`);
    }
    const upsSummary = formatPi5UpsSummary(pi5 && pi5.ups ? pi5.ups : {});
    if (upsSummary) {
        pi5LinkParts.push(`UPS: ${upsSummary}`);
    }
    if (pi5LinkEl) {
        pi5LinkEl.textContent = pi5LinkParts.length > 0
            ? `Pi5 Status: ${pi5LinkParts.join(' | ')}`
            : 'Pi5 Status: --';
    }

    updatedEl.textContent = arduino && arduino.data_updated_at
        ? `Updated: ${formatArduinoTimestamp(arduino.data_updated_at)}`
        : 'Updated: --';
}

function formatPi5Metric(label, value, suffix = '', digits = 2) {
    if (value === undefined || value === null) return null;
    if (typeof value === 'number' && Number.isFinite(value)) {
        return `${label}: ${value.toFixed(digits)}${suffix}`;
    }
    return `${label}: ${value}${suffix}`;
}

function formatPi5UpsSummary(ups) {
    if (!ups || typeof ups !== 'object' || Object.keys(ups).length === 0) return null;

    const parts = [];
    if (ups.parameter) {
        parts.push(String(ups.parameter));
    } else if (ups.component) {
        parts.push(String(ups.component));
    }

    if (ups.value !== undefined && ups.value !== null) {
        const valueText = typeof ups.value === 'number' && Number.isFinite(ups.value)
            ? ups.value.toFixed(2)
            : String(ups.value);
        parts.push(valueText);
    }

    if (ups.state) {
        parts.push(`(${ups.state})`);
    }

    return parts.length > 0 ? parts.join(' ') : null;
}

function formatArduinoTimestamp(timestamp) {
    const parsed = new Date(timestamp);
    if (Number.isNaN(parsed.getTime())) return timestamp;
    return parsed.toLocaleString();
}

function updateROS2Display(ros2Data, ros2ControlData) {
    // Update nodes list
    if (ros2Data && ros2Data.nodes) {
        ros2NodesCache = ros2Data.nodes;
        updateNodesList(ros2Data);
    }

    // Update topics list
    if (ros2Data && ros2Data.topics) {
        ros2TopicsCache = ros2Data.topics;
        updateTopicsList(ros2Data);
    }

    // Update ROS2 control status
    if (ros2ControlData) {
        updateROS2ControlStatusFromData(ros2ControlData);
    }
}

function updateRosbagDisplay(rosbagData) {
    if (!rosbagData) return;

    const data = rosbagData;
    const indicator = document.getElementById('rosbagIndicator');
    const statusText = document.getElementById('rosbagStatusText');
    const infoDiv = document.getElementById('rosbagInfo');
    const fileEl = document.getElementById('rosbagFile');
    const durationEl = document.getElementById('rosbagDuration');
    const topicCountEl = document.getElementById('rosbagTopicCount');
    const startBtn = document.getElementById('startRosbagBtn');
    const stopBtn = document.getElementById('stopRosbagBtn');

    const isRecording = data.is_recording || data.recording;

    // Reset operation flags when status confirms the operation completed
    if (isRecording && rosbagOperationState.isStarting) {
        rosbagOperationState.isStarting = false;
    }
    if (!isRecording && rosbagOperationState.isStopping) {
        rosbagOperationState.isStopping = false;
    }

    if (isRecording) {
        // Recording state
        if (indicator) {
            indicator.className = 'status-indicator recording';
            indicator.style.background = 'var(--success)';
        }
        if (statusText) {
            statusText.textContent = 'Recording';
            statusText.className = 'rosbag-status-text text-success';
        }
        if (fileEl) fileEl.textContent = data.current_bag || data.filename || 'Unknown';
        if (durationEl) {
            if (data.duration !== undefined && data.duration !== null) {
                startRosbagDurationTicker(data.duration);
            } else {
                startRosbagDurationTicker(0);
            }
        }
        if (topicCountEl) topicCountEl.textContent = data.topics_count || data.topic_count || 0;
        if (infoDiv) infoDiv.style.display = 'block';
        if (startBtn) {
            startBtn.disabled = true;
            startBtn.innerHTML = '<i class="fa-solid fa-circle"></i> Start';
        }
        if (stopBtn) {
            // Only enable stop button if not in stopping state
            if (!rosbagOperationState.isStopping) {
                stopBtn.disabled = false;
                stopBtn.innerHTML = '<i class="fa-solid fa-square"></i> Stop';
            }
        }
    } else {
        // Idle state
        if (indicator) {
            indicator.className = 'status-indicator idle';
            indicator.style.background = 'var(--gray-400)';
        }
        if (statusText) {
            statusText.textContent = 'Idle';
            statusText.className = 'rosbag-status-text text-muted';
        }
        if (startBtn) {
            // Only enable start button if not in starting state
            if (!rosbagOperationState.isStarting) {
                startBtn.disabled = false;
                startBtn.innerHTML = '<i class="fa-solid fa-circle"></i> Start';
            }
        }
        if (stopBtn) {
            stopBtn.disabled = true;
            stopBtn.innerHTML = '<i class="fa-solid fa-square"></i> Stop';
        }

        if (data.config_loaded || data.topic_count) {
            if (topicCountEl) topicCountEl.textContent = data.topic_count || 0;
            if (infoDiv) {
                infoDiv.style.display = 'block';
                if (fileEl) fileEl.textContent = '(not recording)';
                if (durationEl) {
                    stopRosbagDurationTicker();
                    durationEl.textContent = '--:--';
                }
            }
        } else {
            if (infoDiv) infoDiv.style.display = 'none';
        }
    }
}

let rosbagDurationTimer = null;
let rosbagDurationStart = null;

function startRosbagDurationTicker(durationSeconds) {
    rosbagDurationStart = Date.now() - Math.max(0, durationSeconds) * 1000;
    updateRosbagDurationDisplay();
    if (rosbagDurationTimer) clearInterval(rosbagDurationTimer);
    rosbagDurationTimer = setInterval(updateRosbagDurationDisplay, 1000);
}

function stopRosbagDurationTicker() {
    rosbagDurationStart = null;
    if (rosbagDurationTimer) {
        clearInterval(rosbagDurationTimer);
        rosbagDurationTimer = null;
    }
}

function updateRosbagDurationDisplay() {
    const durationEl = document.getElementById('rosbagDuration');
    if (!durationEl || rosbagDurationStart === null) return;

    const elapsed = Math.max(0, Math.floor((Date.now() - rosbagDurationStart) / 1000));
    const hours = Math.floor(elapsed / 3600);
    const mins = Math.floor((elapsed % 3600) / 60);
    const secs = elapsed % 60;
    if (hours > 0) {
        durationEl.textContent = `${hours.toString().padStart(2, '0')}:${mins.toString().padStart(2, '0')}:${secs.toString().padStart(2, '0')}`;
    } else {
        durationEl.textContent = `${mins.toString().padStart(2, '0')}:${secs.toString().padStart(2, '0')}`;
    }
}

// ==========================================
// Nodes/Topics List Update (from WebSocket data)
// ==========================================

function updateNodesList(ros2Data) {
    const listEl = document.getElementById('nodesList');
    const countEl = document.getElementById('nodesCount');

    if (!listEl) return;

    const nodes = ros2Data.nodes || [];
    countEl.textContent = nodes.length + ' nodes';

    if (nodes.length === 0) {
        listEl.innerHTML = '<li class="text-muted">No nodes running</li>';
    } else {
        listEl.innerHTML = nodes.slice(0, 10).map(node =>
            `<li>${escapeHtml(node)}</li>`
        ).join('');

        if (nodes.length > 10) {
            listEl.innerHTML += `<li class="text-muted">... and ${nodes.length - 10} more</li>`;
        }
    }
}

function updateTopicsList(ros2Data) {
    const listEl = document.getElementById('topicsList');
    const countEl = document.getElementById('topicsCount');

    if (!listEl) return;

    const topics = ros2Data.topics || [];
    countEl.textContent = topics.length + ' topics';

    if (topics.length === 0) {
        listEl.innerHTML = '<li class="text-muted">No topics found</li>';
    } else {
        const importantTopics = [
            '/navi_lidar/points',
            '/uli_lidar/points',
            '/image_raw',
            '/imu/data',
            '/thruster_status_pwm',
            '/battery_voltage',
        ];

        const sortedTopics = topics.sort((a, b) => {
            const aImportant = importantTopics.some(t => a.includes(t));
            const bImportant = importantTopics.some(t => b.includes(t));
            return bImportant - aImportant;
        });

        listEl.innerHTML = sortedTopics.slice(0, 15).map(topic =>
            `<li>${escapeHtml(topic)}</li>`
        ).join('');

        if (topics.length > 15) {
            listEl.innerHTML += `<li class="text-muted">... and ${topics.length - 15} more</li>`;
        }
    }
}

// ==========================================
// Rosbag Recording Control
// ==========================================

// Rosbag operation state tracking for idempotency
const rosbagOperationState = {
    isStarting: false,
    isStopping: false,
    lastStartAttempt: 0,
    lastStopAttempt: 0,
    OPERATION_COOLDOWN: 3000  // 3 seconds cooldown
};

function initRosbagControls() {
    const startBtn = document.getElementById('startRosbagBtn');
    const stopBtn = document.getElementById('stopRosbagBtn');
    const refreshBtn = document.getElementById('rosbagRefreshBtn');

    if (startBtn) {
        startBtn.addEventListener('click', startRosbagRecording);
    }
    if (stopBtn) {
        stopBtn.addEventListener('click', stopRosbagRecording);
    }
    if (refreshBtn) {
        // NOTE: HTTP polling removed - rosbag status updates via WebSocket every 5 seconds
        // The refresh button now only provides visual feedback for user action
        refreshBtn.addEventListener('click', () => {
            refreshBtn.querySelector('i').classList.add('fa-spin');
            setTimeout(() => {
                refreshBtn.querySelector('i').classList.remove('fa-spin');
            }, 500);
        });
    }
}

async function startRosbagRecording() {
    const startBtn = document.getElementById('startRosbagBtn');
    const originalText = startBtn.innerHTML;

    // Idempotency check: prevent duplicate requests
    const now = Date.now();
    if (rosbagOperationState.isStarting) {
        console.log('Rosbag start operation already in progress, ignoring duplicate request');
        return;
    }
    if (now - rosbagOperationState.lastStartAttempt < rosbagOperationState.OPERATION_COOLDOWN) {
        const remaining = Math.ceil((rosbagOperationState.OPERATION_COOLDOWN - (now - rosbagOperationState.lastStartAttempt)) / 1000);
        showNotification('warning', `Please wait ${remaining} second(s) before starting again`);
        return;
    }

    // Note: ROS2 status check is now done on the backend for reliability
    // This avoids issues with stale frontend state after page load

    rosbagOperationState.isStarting = true;
    rosbagOperationState.lastStartAttempt = now;
    startBtn.disabled = true;
    startBtn.innerHTML = '<i class="fa-solid fa-spinner fa-spin"></i> Starting...';

    try {
        const result = await API.rosbag.start();

        if (result.success) {
            showNotification('success', result.message || 'Recording started');
            // Keep button disabled until status updates via WebSocket
        } else {
            showNotification('error', 'Failed to start recording: ' + (result.message || 'Unknown error'));
            startBtn.disabled = false;
            startBtn.innerHTML = originalText;
            rosbagOperationState.isStarting = false;
        }
    } catch (error) {
        console.error('Error starting rosbag:', error);
        showNotification('error', 'Error starting recording: ' + error.message);
        startBtn.disabled = false;
        startBtn.innerHTML = originalText;
        rosbagOperationState.isStarting = false;
    }
}

async function stopRosbagRecording() {
    const stopBtn = document.getElementById('stopRosbagBtn');
    const originalText = stopBtn.innerHTML;

    // Idempotency check: prevent duplicate requests
    const now = Date.now();
    if (rosbagOperationState.isStopping) {
        console.log('Rosbag stop operation already in progress, ignoring duplicate request');
        return;
    }
    if (now - rosbagOperationState.lastStopAttempt < rosbagOperationState.OPERATION_COOLDOWN) {
        const remaining = Math.ceil((rosbagOperationState.OPERATION_COOLDOWN - (now - rosbagOperationState.lastStopAttempt)) / 1000);
        showNotification('warning', `Please wait ${remaining} second(s) before stopping again`);
        return;
    }

    rosbagOperationState.isStopping = true;
    rosbagOperationState.lastStopAttempt = now;
    stopBtn.disabled = true;
    stopBtn.innerHTML = '<i class="fa-solid fa-spinner fa-spin"></i> Stopping...';

    try {
        const result = await API.rosbag.stop();

        if (result.success) {
            showNotification('success', result.message || 'Recording stopped');
            // Keep button disabled until status updates via WebSocket
        } else {
            showNotification('error', 'Failed to stop recording: ' + (result.message || 'Unknown error'));
            stopBtn.disabled = false;
            stopBtn.innerHTML = originalText;
            rosbagOperationState.isStopping = false;
        }
    } catch (error) {
        console.error('Error stopping rosbag:', error);
        showNotification('error', 'Error stopping recording: ' + error.message);
        stopBtn.disabled = false;
        stopBtn.innerHTML = originalText;
        rosbagOperationState.isStopping = false;
    }
}

// ==========================================
// ROS2 Control Functions
// ==========================================

function initROS2Controls() {
    const startBtn = document.getElementById('startRos2Btn');
    const stopBtn = document.getElementById('stopRos2Btn');

    if (startBtn) {
        startBtn.addEventListener('click', startROS2);
    }
    if (stopBtn) {
        stopBtn.addEventListener('click', stopROS2);
    }
}

function updateROS2ControlStatusFromData(status) {
    const indicator = document.getElementById('ros2ControlIndicator');
    const statusText = document.getElementById('ros2ControlStatusText');
    const detailEl = document.getElementById('ros2ControlDetail');
    const startBtn = document.getElementById('startRos2Btn');
    const stopBtn = document.getElementById('stopRos2Btn');

    // Reset operation flags when status confirms the operation completed
    if (status.running && ros2OperationState.isStarting) {
        ros2OperationState.isStarting = false;
    }
    if (!status.running && ros2OperationState.isStopping) {
        ros2OperationState.isStopping = false;
    }

    if (indicator) {
        indicator.className = 'status-indicator ' + (status.running ? 'ok' : 'unknown');
    }
    if (statusText) {
        // Don't override text if operation is in progress
        if (!ros2OperationState.isStarting && !ros2OperationState.isStopping) {
            statusText.textContent = status.running ? 'Running' : 'Stopped';
        }
    }
    if (detailEl) {
        detailEl.textContent = status.running ?
            `PID: ${status.pid || 'Unknown'}` : 'ROS2 drivers stopped';
    }
    if (startBtn && stopBtn) {
        // Only update button states if no operation is in progress
        if (!ros2OperationState.isStarting && !ros2OperationState.isStopping) {
            startBtn.disabled = status.running;
            stopBtn.disabled = !status.running;
        }
    }
}

// Operation state tracking for idempotency
const ros2OperationState = {
    isStarting: false,
    isStopping: false,
    lastStartAttempt: 0,
    lastStopAttempt: 0,
    OPERATION_COOLDOWN: 3000  // 3 seconds cooldown between operations
};

async function startROS2() {
    const startBtn = document.getElementById('startRos2Btn');
    const statusText = document.getElementById('ros2ControlStatusText');

    // Idempotency check: prevent duplicate requests
    const now = Date.now();
    if (ros2OperationState.isStarting) {
        console.log('Start operation already in progress, ignoring duplicate request');
        return;
    }
    if (now - ros2OperationState.lastStartAttempt < ros2OperationState.OPERATION_COOLDOWN) {
        const remaining = Math.ceil((ros2OperationState.OPERATION_COOLDOWN - (now - ros2OperationState.lastStartAttempt)) / 1000);
        showNotification('warning', `Please wait ${remaining} second(s) before starting again`);
        return;
    }

    ros2OperationState.isStarting = true;
    ros2OperationState.lastStartAttempt = now;
    startBtn.disabled = true;
    if (statusText) statusText.textContent = 'Starting...';

    try {
        const result = await API.ros2.control.start();

        if (result.success) {
            showNotification('success', result.message || 'ROS2 starting...');
            // Keep button disabled until status updates via WebSocket
        } else {
            showNotification('error', 'Failed to start ROS2: ' + (result.message || 'Unknown error'));
            startBtn.disabled = false;
            ros2OperationState.isStarting = false;
            if (statusText) statusText.textContent = 'Start Failed';
        }
    } catch (error) {
        console.error('Error starting ROS2:', error);
        showNotification('error', 'Error starting ROS2: ' + error.message);
        startBtn.disabled = false;
        ros2OperationState.isStarting = false;
        if (statusText) statusText.textContent = 'Error';
    }
}

async function stopROS2() {
    const stopBtn = document.getElementById('stopRos2Btn');
    const statusText = document.getElementById('ros2ControlStatusText');

    // Idempotency check: prevent duplicate requests
    const now = Date.now();
    if (ros2OperationState.isStopping) {
        console.log('Stop operation already in progress, ignoring duplicate request');
        return;
    }
    if (now - ros2OperationState.lastStopAttempt < ros2OperationState.OPERATION_COOLDOWN) {
        const remaining = Math.ceil((ros2OperationState.OPERATION_COOLDOWN - (now - ros2OperationState.lastStopAttempt)) / 1000);
        showNotification('warning', `Please wait ${remaining} second(s) before stopping again`);
        return;
    }

    ros2OperationState.isStopping = true;
    ros2OperationState.lastStopAttempt = now;
    stopBtn.disabled = true;
    if (statusText) statusText.textContent = 'Stopping...';

    try {
        const result = await API.ros2.control.stop();

        if (result.success) {
            showNotification('success', result.message || 'ROS2 stopped');
            // Keep button disabled until status updates via WebSocket
        } else {
            showNotification('error', 'Failed to stop ROS2: ' + (result.message || 'Unknown error'));
            stopBtn.disabled = false;
            ros2OperationState.isStopping = false;
            if (statusText) statusText.textContent = 'Stop Failed';
        }
    } catch (error) {
        console.error('Error stopping ROS2:', error);
        showNotification('error', 'Error stopping ROS2: ' + error.message);
        stopBtn.disabled = false;
        ros2OperationState.isStopping = false;
        if (statusText) statusText.textContent = 'Error';
    }
}

// ==========================================
// Utility Functions
// ==========================================

function getStatusIcon(isOk) {
    if (isOk === true) {
        return '<span class="status-icon ok"></span><span class="text-success">OK</span>';
    } else if (isOk === false) {
        return '<span class="status-icon critical"></span><span class="text-danger">--</span>';
    } else {
        return '<span class="text-muted">N/A</span>';
    }
}

// escapeHtml and showNotification are now in main.js to avoid duplication
