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
    activateRequestedSensorTab();
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

function activateRequestedSensorTab() {
    const params = new URLSearchParams(window.location.search);
    let requested = params.get('sensor');

    if (!requested && window.location.hash) {
        requested = window.location.hash.replace('#', '').replace('Panel', '');
    }

    if (requested && SensorCatalog.has(requested)) {
        switchSensorTab(requested);
    }
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
    updatePi5SensorsPanel(allSensors.pi5_sensors);
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

    const ipEl = document.getElementById('thrusterIpValue');
    const protocolEl = document.getElementById('thrusterProtocolValue');
    const arduinoPortsEl = document.getElementById('thrusterArduinoPortsValue');
    const jetsonPortsEl = document.getElementById('thrusterJetsonPortsValue');
    const networkStatus = document.getElementById('thrusterNetworkStatus');
    const udpStatus = document.getElementById('thrusterUdpStatus');
    const latencyEl = document.getElementById('thrusterLatencyValue');
    const connectionInfo = data.connection_info || {};

    if (ipEl) {
        ipEl.textContent = connectionInfo.ip || '192.168.50.100';
    }
    if (protocolEl) {
        protocolEl.textContent = connectionInfo.protocol || 'UDP';
    }
    if (arduinoPortsEl) {
        const cmdPort = connectionInfo.arduino_cmd_port ?? 8888;
        const pingPort = connectionInfo.arduino_ping_port ?? 8889;
        arduinoPortsEl.textContent = `${cmdPort} cmd / ${pingPort} ping`;
    }
    if (jetsonPortsEl) {
        const dataPort = connectionInfo.driver_data_port ?? 28888;
        const heartbeatPort = connectionInfo.driver_heartbeat_port ?? 28887;
        const monitorPort = connectionInfo.monitor_port ?? 28889;
        jetsonPortsEl.textContent = `${dataPort} data / ${heartbeatPort} heartbeat / ${monitorPort} monitor`;
    }

    if (networkStatus) {
        if (data.connected === 'Connected') {
            networkStatus.textContent = 'Connected';
            networkStatus.className = 'info-value text-success';
        } else {
            networkStatus.textContent = 'Disconnected';
            networkStatus.className = 'info-value text-danger';
        }
    }

    if (udpStatus) {
        if (connectionInfo.udp_online === true) {
            udpStatus.textContent = 'Online';
            udpStatus.className = 'info-value text-success';
        } else if (connectionInfo.udp_online === false) {
            udpStatus.textContent = 'Offline';
            udpStatus.className = 'info-value text-danger';
        } else {
            udpStatus.textContent = '--';
            udpStatus.className = 'info-value';
        }
    }

    if (latencyEl) {
        if (data.latency_ms !== undefined && data.latency_ms !== null) {
            latencyEl.textContent = Number(data.latency_ms).toFixed(1) + ' ms';
        } else {
            latencyEl.textContent = '--';
        }
    }

    const dataUpdatedEl = document.getElementById('thrusterDataUpdatedAt');
    if (dataUpdatedEl) {
        if (data.data_updated_at) {
            const parsedTime = new Date(data.data_updated_at);
            dataUpdatedEl.textContent = Number.isNaN(parsedTime.getTime())
                ? data.data_updated_at
                : parsedTime.toLocaleString();
        } else {
            dataUpdatedEl.textContent = '--';
        }
    }

    // Update thruster status (S)
    const thrusterStatus = data.thruster_status || {};
    const modeEl = document.getElementById('thrusterMode');
    const leftPwmEl = document.getElementById('thrusterLeftPwm');
    const rightPwmEl = document.getElementById('thrusterRightPwm');

    if (modeEl) {
        if (thrusterStatus.mode !== undefined && thrusterStatus.mode !== null) {
            const modeLabel = thrusterStatus.mode_label || (thrusterStatus.mode === 1 ? 'WiFi' : (thrusterStatus.mode === 0 ? 'RC' : 'Mode'));
            modeEl.textContent = `${modeLabel} (${thrusterStatus.mode})`;
        } else {
            modeEl.textContent = '--';
        }
    }
    if (leftPwmEl) {
        if (thrusterStatus.left_pwm !== undefined && thrusterStatus.left_pwm !== null) {
            leftPwmEl.textContent = thrusterStatus.left_pwm + ' us';
        } else {
            leftPwmEl.textContent = '--';
        }
    }
    if (rightPwmEl) {
        if (thrusterStatus.right_pwm !== undefined && thrusterStatus.right_pwm !== null) {
            rightPwmEl.textContent = thrusterStatus.right_pwm + ' us';
        } else {
            rightPwmEl.textContent = '--';
        }
    }

    // Update flow / speed (F)
    const flowData = data.flow_data || {};
    const freqEl = document.getElementById('thrusterFreqHz');
    const flowLminEl = document.getElementById('thrusterFlowLmin');
    const velocityEl = document.getElementById('thrusterVelocityMs');
    const totalLitersEl = document.getElementById('thrusterTotalLiters');

    if (freqEl) {
        if (flowData.freq_hz !== undefined && flowData.freq_hz !== null) {
            freqEl.textContent = flowData.freq_hz.toFixed(2) + ' Hz';
        } else {
            freqEl.textContent = '--';
        }
    }
    if (flowLminEl) {
        if (flowData.flow_lmin !== undefined && flowData.flow_lmin !== null) {
            flowLminEl.textContent = flowData.flow_lmin.toFixed(2) + ' L/min';
        } else {
            flowLminEl.textContent = '--';
        }
    }
    if (velocityEl) {
        if (flowData.velocity_ms !== undefined && flowData.velocity_ms !== null) {
            velocityEl.textContent = flowData.velocity_ms.toFixed(3) + ' m/s';
        } else {
            velocityEl.textContent = '--';
        }
    }
    if (totalLitersEl) {
        if (flowData.total_liters !== undefined && flowData.total_liters !== null) {
            totalLitersEl.textContent = flowData.total_liters.toFixed(3) + ' L';
        } else {
            totalLitersEl.textContent = '--';
        }
    }

    // Update temperature & humidity
    const tempHumidity = data.temp_humidity || {};
    const temp1El = document.getElementById('thrusterTemp1');
    const hum1El = document.getElementById('thrusterHum1');
    const temp2El = document.getElementById('thrusterTemp2');
    const hum2El = document.getElementById('thrusterHum2');

    if (temp1El && tempHumidity.temp1 !== undefined && tempHumidity.temp1 !== null) {
        temp1El.textContent = tempHumidity.temp1.toFixed(1) + ' °C';
    }
    if (hum1El && tempHumidity.humidity1 !== undefined && tempHumidity.humidity1 !== null) {
        hum1El.textContent = tempHumidity.humidity1.toFixed(0) + ' %';
    }
    if (temp2El && tempHumidity.temp2 !== undefined && tempHumidity.temp2 !== null) {
        temp2El.textContent = tempHumidity.temp2.toFixed(1) + ' °C';
    }
    if (hum2El && tempHumidity.humidity2 !== undefined && tempHumidity.humidity2 !== null) {
        hum2El.textContent = tempHumidity.humidity2.toFixed(0) + ' %';
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

    if (a0El && voltages.channel_a0 !== undefined && voltages.channel_a0 !== null) {
        a0El.textContent = voltages.channel_a0.toFixed(2) + ' V';
        a0El.className = 'info-value';
    } else if (a0El) {
        a0El.textContent = '-- V';
        a0El.className = 'info-value';
    }
    if (a1El && voltages.channel_a1 !== undefined && voltages.channel_a1 !== null) {
        a1El.textContent = voltages.channel_a1.toFixed(2) + ' V';
        a1El.className = 'info-value';
    } else if (a1El) {
        a1El.textContent = '-- V';
        a1El.className = 'info-value';
    }
    if (a2El && voltages.channel_a2 !== undefined && voltages.channel_a2 !== null) {
        a2El.textContent = voltages.channel_a2.toFixed(2) + ' V';
        a2El.className = 'info-value';
    } else if (a2El) {
        a2El.textContent = '-- V';
        a2El.className = 'info-value';
    }
    if (a3El && voltages.channel_a3 !== undefined && voltages.channel_a3 !== null) {
        a3El.textContent = voltages.channel_a3.toFixed(2) + ' V';
        a3El.className = 'info-value';
    } else if (a3El) {
        a3El.textContent = '-- V';
        a3El.className = 'info-value';
    }
}

function updatePi5SensorsPanel(data) {
    if (!data) return;

    const badge = document.getElementById('pi5SensorsStatusBadge');
    if (badge) {
        badge.className = 'status-badge large ' + (data.status || 'unknown');
        badge.textContent = (data.status || 'unknown').toUpperCase();
    }

    const connected = data.connected;
    const netEl = document.getElementById('pi5NetworkStatus');
    if (netEl) {
        netEl.textContent = connected === 'Connected' ? 'Online' : 'Offline';
        netEl.className = 'info-value ' + (connected === 'Connected' ? 'text-success' : 'text-danger');
    }

    const wq = data.water_quality || {};
    const hasData = wq && Object.keys(wq).length > 0;
    const mqttEl = document.getElementById('pi5MqttStatus');
    if (mqttEl) {
        if (hasData && data.water_quality_fresh !== false) {
            mqttEl.textContent = 'Streaming';
            mqttEl.className = 'info-value text-success';
        } else if (hasData) {
            mqttEl.textContent = 'Stale';
            mqttEl.className = 'info-value text-warning';
        } else {
            mqttEl.textContent = 'No data';
            mqttEl.className = 'info-value';
        }
    }

    const ageEl = document.getElementById('pi5DataAge');
    if (ageEl) {
        if (data.water_quality_age_s !== undefined && data.water_quality_age_s !== null) {
            const ageSeconds = Math.max(0, Number(data.water_quality_age_s));
            ageEl.textContent = `${ageSeconds.toFixed(1)} s`;
            ageEl.className = 'info-value ' + (data.water_quality_fresh === false ? 'text-warning' : 'text-success');
        } else if (hasData) {
            ageEl.textContent = '0.0 s';
            ageEl.className = 'info-value text-success';
        } else {
            ageEl.textContent = 'No data';
            ageEl.className = 'info-value';
        }
    }

    // Water quality
    setInfoValue('pi5C4eTemp', wq.c4e_temp_c, ' °C');
    setInfoValue('pi5Conductivity', wq.c4e_conductivity_uscm, ' µS/cm');
    setInfoValue('pi5Salinity', wq.c4e_salinity_ppt, ' ppt');
    setInfoValue('pi5Tds', wq.c4e_tds_ppm, ' ppm');
    setInfoValue('pi5OptodTemp', wq.optod_temp_c, ' °C');
    setInfoValue('pi5O2Sat', wq.optod_o2_saturation_pct, ' %');
    setInfoValue('pi5O2Mgl', wq.optod_o2_mgl, ' mg/L');
    setInfoValue('pi5O2Ppm', wq.optod_o2_ppm, ' ppm');
    setInfoValue('pi5PhTemp', wq.ph_temp_c, ' °C');
    setInfoValue('pi5Ph', wq.ph_ph, '');
    setInfoValue('pi5Redox', wq.ph_redox_mv, ' mV');
    setInfoValue('pi5PhMv', wq.ph_mv, ' mV');

    // UPS status
    const ups = data.ups || {};
    setInfoText('pi5UpsComponent', ups.component);
    setInfoText('pi5UpsParameter', ups.parameter);
    if (ups.value !== undefined && ups.value !== null) {
        setInfoValue('pi5UpsValue', ups.value, '');
    }
    setInfoText('pi5UpsState', ups.state);
}

function setInfoValue(id, value, suffix) {
    const el = document.getElementById(id);
    if (!el) return;
    if (value !== undefined && value !== null) {
        el.textContent = (typeof value === 'number' ? value.toFixed(2) : value) + suffix;
        el.className = 'info-value';
    } else {
        el.textContent = '--' + suffix;
        el.className = 'info-value';
    }
}

function setInfoText(id, value) {
    const el = document.getElementById(id);
    if (!el) return;
    el.textContent = (value && value !== '') ? value : '--';
    el.className = 'info-value';
}
