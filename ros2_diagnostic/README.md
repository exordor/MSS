# ROS2 Diagnostic System

Web-based diagnostics for the MSS ROS2 stack. The app provides a FastAPI dashboard with WebSocket updates, sensor health checks, alert/event persistence, ROS2 control hooks, rosbag control, and log inspection.

## Features

- Real-time dashboard and sensor detail pages over `FastAPI` + `WebSocket`
- Unified backend sensor catalog (`SENSOR_DEFS`) shared with the frontend
- Health checks for Navi LiDAR, U-LiDAR, Camera, IMU, Arduino, Battery, and Pi5 Sensors
- ROS2 node/topic visibility, sensor-specific metrics, and incremental websocket updates
- SQLite-backed alerts and event audit logs
- Rosbag start/stop control
- Log viewing plus size-based rotation for the main diagnostic log

## Sensor Coverage

| Sensor | Internal Key | Primary Checks | Main Data Source |
|------|------|------|------|
| Navi LiDAR | `navi_lidar` | Ping, ROS2 node/topic, point cloud frequency and quality | `/navi_lidar/points` |
| U-LiDAR | `uli_lidar` | Ping only | Web control only, no ROS driver |
| Camera | `camera` | Ping, ROS2 node/topic, image frequency and latency | `/image_raw` |
| IMU | `imu` | Serial availability, ROS2 node/topic, data presence | `/imu/data` |
| Arduino | `thruster` | Ping, UDP heartbeat, ROS2 node/topic | `/thruster_status_pwm` |
| Battery | `battery` | Local I2C probe, ROS2 node/topic, voltage thresholds | `/battery_voltage` |
| Pi5 Sensors | `pi5_sensors` | MQTT freshness, ping, ROS2 node/topic, water quality and UPS payloads | MQTT `modbus_logger/pi5/*`, ROS2 `/water_quality` |

Pi5 uses the same ROS2 node match as Arduino: `thruster_wifi_node` / `thruster`.

## Architecture

The current codebase uses one backend source of truth for sensor metadata:

- `main.py:SENSOR_DEFS` defines display name, icon, node/topic match rules, and UI visibility
- `main.py:_build_frontend_sensor_catalog()` serializes that catalog for the browser
- `templates/base.html` injects `window.__SENSOR_DEFS__`
- `static/js/sensor-config.js` exposes the shared `SensorCatalog`
- `static/js/dashboard.js` and `static/js/sensors.js` both consume that same catalog

Sensor status payloads are normalized in one place through `_build_sensor_result()`, which reduces drift between manual refresh, websocket incremental updates, and dashboard rendering.

## Project Layout

```text
ros2_diagnostic/
├── main.py
├── config.py
├── config.yaml
├── alerts.py
├── event_log.py
├── tm_proxy.py
├── run_with_ros2_env.sh
├── requirements.txt
├── diagnostics/
│   ├── base.py
│   ├── mqtt_client.py
│   ├── ros2_control.py
│   ├── ros2_helper.py
│   ├── ros2_monitor.py
│   ├── rosbag_controller.py
│   ├── lidar_log_parser.py
│   ├── camera_log_parser.py
│   └── sensor_monitor/
│       ├── navi_lidar.py
│       ├── uli_lidar.py
│       ├── camera.py
│       ├── imu.py
│       ├── thruster.py
│       ├── battery.py
│       └── pi5_sensors.py
├── static/
│   └── js/
│       ├── main.js
│       ├── sensor-config.js
│       ├── dashboard.js
│       ├── sensors.js
│       ├── tools.js
│       ├── alerts.js
│       ├── events.js
│       └── logs.js
├── templates/
│   ├── base.html
│   ├── index.html
│   ├── sensors.html
│   ├── tools.html
│   ├── logs.html
│   └── events.html
└── tests/
    ├── unit/
    │   ├── test_sensor_status_fields.py
    │   ├── test_pi5_sensors.py
    │   └── test_log_rotation.py
    ├── api/
    ├── integration/
    ├── ui/
    └── manual/
        └── mock_pi5_mqtt.py
```

## Installation

### 1. Install Python dependencies

```bash
cd /home/eagrumo/mss_lecture/ros2_diagnostic
pip install -r requirements.txt
```

### 2. Install ROS2 Python bindings if needed

```bash
sudo apt install ros-humble-rclpy
```

### 3. Create runtime directories

```bash
mkdir -p logs data
```

### 4. Optional systemd service

```bash
sudo cp config/ros2-diagnostic.service /etc/systemd/system/
sudo systemctl daemon-reload
sudo systemctl enable ros2-diagnostic
sudo systemctl start ros2-diagnostic
sudo systemctl status ros2-diagnostic
```

## Configuration

All runtime settings live in [config.yaml](config.yaml). Important sections:

- `ros2`: domain ID, workspace, launch script
- `mqtt`: broker config plus Pi5 topics
- `sensors.ips`: network addresses for sensors
- `sensors.thresholds`: sensor-specific warning and timeout thresholds
- `sensors.topics`: configured ROS2 topic names
- `ros2_nodes`: expected nodes and per-sensor node mapping
- `sensor_connections`: transport type for each sensor
- `logs.rotation`: diagnostic log rotation policy
- `monitoring.cache_ttl`: cache TTL for ROS2 and sensor refresh

Override the config file with:

```bash
export ROS2_DIAGNOSTIC_CONFIG=/path/to/custom_config.yaml
```

### Log Rotation

The main diagnostic log now rotates by size to avoid one ever-growing file:

```yaml
logs:
  rotation:
    enabled: true
    max_mb: 20
    backup_count: 10
    compress: true
    encoding: "utf-8"
```

By default:

- Active application log: `ros2_diagnostic/logs/diagnostic.log`
- ROS2 control log: `ros2_diagnostic/logs/ros2.log`
- Rotated archives: `diagnostic.log.1.gz`, `diagnostic.log.2.gz`, ...

The `/logs` page still reads the active log files. Rotated archives are retained on disk.

## Running

### Manual start

```bash
cd /home/eagrumo/mss_lecture/ros2_diagnostic
./run_with_ros2_env.sh
```

or:

```bash
cd /home/eagrumo/mss_lecture/ros2_diagnostic
python3 main.py
```

### Systemd start

```bash
sudo systemctl start ros2-diagnostic
sudo systemctl status ros2-diagnostic
```

### Web entry points

- Dashboard: `http://localhost:5000/`
- Sensor details: `http://localhost:5000/sensors`
- API docs: `http://localhost:5000/docs`

## Web UI Pages

| Page | Route | Purpose |
|------|-------|---------|
| Dashboard | `/` | Overall system state, sensor preview, ROS2 status |
| Sensors | `/sensors` | Detailed per-sensor diagnostics |
| Tools | `/tools` | Utility tools such as ping and config validation |
| Logs | `/logs` | Active log viewer |
| Events | `/events` | Audit/event log browser |

## WebSocket API

Connect to:

```text
WS /ws
```

Supported channels:

- `sensors`
- `alerts`
- `ros2`
- `ros2_control`
- `rosbag`

Typical flow:

```javascript
const ws = new WebSocket("ws://localhost:5000/ws");

ws.onopen = () => {
  ws.send("subscribe:sensors");
};

ws.onmessage = (event) => {
  const data = JSON.parse(event.data);
  if (data.type === "sensors_update") {
    console.log(data.data);
  }
};
```

Common message types:

- `full_state`
- `state_update`
- `sensors_update`
- `alert`

## HTTP API

### Status and Sensors

- `GET /api/status`
- `GET /api/sensors/status`

### ROS2 Control

- `POST /api/ros2/control/start`
- `POST /api/ros2/control/stop`
- `GET /api/ros2/control/logs`

### Rosbag

- `POST /api/rosbag/start`
- `POST /api/rosbag/stop`

### Alerts

- `POST /api/alerts/{id}/resolve`
- `POST /api/alerts/{id}/ignore`
- `GET /api/alerts/stats`
- `GET /api/alerts/sensor/{sensor}`
- `GET /api/alerts/severity/{severity}`

### Events

- `GET /api/events/logs`
- `GET /api/events/stats`
- `GET /api/events/types`
- `GET /api/events/export`

### Logs

- `GET /api/logs`
- `GET /api/logs/sessions`
- `GET /api/logs/session/{id}/files`
- `GET /api/logs/read`
- `GET /api/logs/stream`

### Tools and Cache

- `POST /api/tools/ping`
- `POST /api/tools/config-validate`
- `GET /api/cache/stats`
- `POST /api/cache/invalidate`

## Testing

Run the main regression tests with:

```bash
pytest tests/unit/test_sensor_status_fields.py -q
pytest tests/unit/test_pi5_sensors.py -q
pytest tests/unit/test_log_rotation.py -q
```

Full suite:

```bash
pytest
```

### Pi5 MQTT Mock

Use the manual publisher to inject Pi5 water-quality and UPS data into a local broker:

```bash
python3 tests/manual/mock_pi5_mqtt.py --with-ups
```

This is useful when verifying:

- MQTT ingestion in `diagnostics/sensor_monitor/pi5_sensors.py`
- websocket `sensors_update` payloads
- `/sensors?sensor=pi5_sensors` rendering

## Development Notes

### Adding a new sensor

1. Add the sensor metadata to `main.py:SENSOR_DEFS`
2. Add config entries in [config.yaml](config.yaml)
3. Implement the diagnostic monitor in `diagnostics/sensor_monitor/`
4. Register the monitor in the backend factory path
5. Extend the sensor detail UI only if the sensor needs custom fields

The important rule now is: do not duplicate sensor metadata in the frontend. `dashboard.js` and `sensors.js` should consume the injected shared catalog instead of maintaining their own lists.

### Logs and service debugging

- Active application logs live under `ros2_diagnostic/logs/`
- Live service logs: `journalctl -u ros2-diagnostic -f`
- Diagnostic log rotation is handled in `main.py` with `RotatingFileHandler` + gzip compression

## Time Machine Proxy

[tm_proxy.py](tm_proxy.py) provides a standalone Flask proxy for Time Machine device access with digest-auth forwarding. Default port: `8083`.

## Changelog

See [CHANGELOG.md](CHANGELOG.md).

## License

Part of the MSS Lecture project.
