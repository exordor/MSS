# ROS2 Diagnostic System

A comprehensive web-based diagnostic system for ROS2 underwater robot applications with real-time WebSocket updates, sensor health monitoring, alert management, event logging, and control capabilities.

## Features

### Real-time Monitoring
- **WebSocket Push**: Channel-based subscriptions (sensors, alerts, ros2, ros2_control, rosbag)
- **Parallel Sensor Checks**: Async concurrent monitoring for better performance
- **Multi-level Caching**: Configurable TTL for different data types
- **Node/Topic Detection**: Shell command priority for reliable ROS2 detection

### Sensor Diagnostics
- **Navi LiDAR** (Hesai QT128): Network, ROS2 topics, point cloud frequency (10 Hz), point count, packet loss
- **U-LiDAR**: Network connectivity (web control only, no ROS driver)
- **Galaxy Camera**: Network, FPS (2 Hz), image latency, resolution validation
- **IMU** (SBG): Serial connection, GPS fix status, data frequency (25 Hz)
- **Thruster**: UDP heartbeat detection (port 28889), network connectivity, timeout monitoring

### Event Logging & Auditing
- **Persistent Event Log**: SQLite-based audit trail for all system actions
- **Event Types**: System start/stop, ROS2 control, rosbag recording, alert actions
- **Export Support**: CSV and JSON export for external analysis
- **Event Statistics**: Summary views by type, action, and resource

### Control Capabilities
- **ROS2 Control**: Start/stop sensor drivers via control script
- **Rosbag Recording**: Start/stop rosbag with service calls
- **Alert Management**: Resolve/ignore alerts with persistent storage and disconnection tracking

### Log Analysis
- **Log Parsers**: LiDAR and camera log parsers for data quality metrics
- **Session Viewer**: Browse logs by session with SSE streaming
- **Application Logs**: Diagnostic and ROS2 control logs

### Control Capabilities
- **ROS2 Control**: Start/stop sensor drivers via control script
- **Rosbag Recording**: Start/stop rosbag with service calls
- **Alert Management**: Resolve/ignore alerts with persistent storage

### Log Analysis
- **Log Parsers**: LiDAR and camera log parsers for data quality metrics
- **Session Viewer**: Browse logs by session with SSE streaming
- **Application Logs**: Diagnostic and ROS2 control logs

## Architecture

```
ros2_diagnostic/
├── main.py                    # FastAPI web application
├── config.py                  # YAML configuration loader
├── config.yaml               # Main configuration file
├── alerts.py                 # SQLite-based alert system
├── event_log.py              # SQLite-based event audit log
├── tm_proxy.py               # Time Machine web proxy
├── run_with_ros2_env.sh      # ROS2 environment wrapper script
├── requirements.txt          # Python dependencies
│
├── diagnostics/              # Core diagnostic modules
│   ├── base.py              # Base classes (BaseDiagnostic, StatusLevel)
│   ├── ros2_monitor.py      # ROS2 system monitoring
│   ├── ros2_control.py      # ROS2 script control
│   ├── ros2_helper.py       # rclpy utilities
│   ├── rosbag_controller.py # Rosbag recording control
│   ├── utils.py             # Utilities (ping, formatting)
│   ├── lidar_log_parser.py  # LiDAR log analysis
│   ├── camera_log_parser.py # Camera log analysis
│   └── sensor_monitor/      # Sensor diagnostics
│       ├── navi_lidar.py    # Hesai QT128
│       ├── uli_lidar.py     # U-LiDAR
│       ├── camera.py        # Galaxy Camera
│       ├── imu.py           # SBG IMU
│       └── thruster.py      # Thruster (UDP heartbeat)
│
├── static/                  # Frontend assets
│   ├── css/
│   │   ├── main.css
│   │   └── base.css
│   └── js/
│       ├── main.js          # WebSocket & API utilities
│       ├── dashboard.js     # Dashboard logic
│       ├── sensors.js       # Sensor detail pages
│       ├── tools.js         # Diagnostic tools
│       ├── alerts.js        # Alert management
│       └── logs.js          # Log viewer
│
├── templates/               # HTML templates
│   ├── base.html
│   ├── index.html           # Dashboard
│   ├── sensors.html         # Sensor details
│   ├── tools.html           # Diagnostic tools
│   ├── logs.html            # Log viewer
│   └── events.html          # Event log viewer
│
├── logs/                    # Application logs
├── data/                    # SQLite databases (alerts.db, events.db)
└── tests/                   # Test suite
    ├── unit/                # Unit tests
    ├── integration/         # End-to-end tests
    ├── api/                 # API tests
    └── ui/                  # Playwright UI tests
```

## Installation

### 1. Install Dependencies

Install Python dependencies:
```bash
cd /home/eagrumo/mss_lecture/ros2_diagnostic
pip install -r requirements.txt
```

Install ROS2 rclpy (if not already installed):
```bash
sudo apt install ros-humble-rclpy
```

### 2. Create Required Directories

```bash
mkdir -p logs data
```

### 3. Systemd Service Installation (Recommended)

For automatic startup on boot, install the systemd service:

```bash
# Copy service file
sudo cp config/ros2-diagnostic.service /etc/systemd/system/

# Reload systemd
sudo systemctl daemon-reload

# Enable service to start on boot
sudo systemctl enable ros2-diagnostic

# Start service
sudo systemctl start ros2-diagnostic

# Check service status
sudo systemctl status ros2-diagnostic
```

The service configuration includes:
- ROS2 environment variables (PATH, AMENT_PREFIX_PATH, PYTHONPATH, LD_LIBRARY_PATH)
- ROS_DOMAIN_ID=42
- Automatic restart on failure
- TimeoutStopSec=5 (fast shutdown, was 90s default)
- Journal logging for diagnostics
- Proper cleanup: stops ROS2 subprocess and cancels background tasks on shutdown

## Configuration

All settings are in [config.yaml](config.yaml):

- **ROS2 Environment**: domain_id, workspace, launch scripts
- **Sensor IPs**: Network addresses for all sensors
- **Sensor Thresholds**: min_frequency, max_packet_loss, timeouts
- **ROS2 Topics**: Expected topic names
- **Monitoring Settings**: cache_ttl, enable features
- **WebSocket Settings**: ping_interval, broadcast_interval

Override with environment variable:
```bash
export ROS2_DIAGNOSTIC_CONFIG=/path/to/custom_config.yaml
```

## Usage

### Starting the Server

**Option 1: Using systemd service (recommended)**
```bash
sudo systemctl start ros2-diagnostic
sudo systemctl status ros2-diagnostic
```

**Option 2: Manual start**
```bash
# Using wrapper script (includes ROS2 environment)
./run_with_ros2_env.sh

# Or direct Python (requires ROS2 environment setup)
python3 main.py
```

Access at:
- Local: http://localhost:5000
- Network: http://<your-ip>:5000
- API docs: http://localhost:5000/docs

### Pages

| Page | Route | Description |
|------|-------|-------------|
| Dashboard | `/` | System overview with status cards |
| Sensors | `/sensors` | Detailed sensor diagnostics |
| Tools | `/tools` | Ping test, config validator |
| Logs | `/logs` | Session-based log viewer |
| Events | `/events` | Event log audit trail |

## WebSocket API

### Connection
```
WS /ws
```

### Channels
Subscribe to specific channels for targeted updates:
- `sensors` - Sensor status (5s interval)
- `alerts` - Real-time alert push
- `ros2` - ROS2 system (10s interval)
- `ros2_control` - ROS2 control status (5s)
- `rosbag` - Rosbag status (5s)

### Message Types
- `full_state` - Complete state on connect
- `state_update` - Incremental updates
- `alert` - Real-time alert notifications

### Example

```javascript
// Connect to WebSocket
const ws = new WebSocket('ws://localhost:5000/ws');

// Subscribe to sensors channel
ws.onopen = () => {
  ws.send('subscribe:sensors');
};

// Handle messages
ws.onmessage = (event) => {
  const data = JSON.parse(event.data);
  if (data.type === 'sensors_update') {
    console.log('Sensor status:', data.data);
  }
};
```

## HTTP API Endpoints

### System Status
- `GET /api/status` - Legacy ROS2 status
- `GET /api/sensors/status` - Manual sensor status refresh

### ROS2 Control
- `POST /api/ros2/control/start` - Start sensor drivers
- `POST /api/ros2/control/stop` - Stop sensor drivers
- `GET /api/ros2/control/logs` - Get runtime logs

### Rosbag
- `POST /api/rosbag/start` - Start recording (optional: topics override)
- `POST /api/rosbag/stop` - Stop recording

### Alerts
- `POST /api/alerts/{id}/resolve` - Mark alert as resolved
- `POST /api/alerts/{id}/ignore` - Mark alert as ignored
- `GET /api/alerts/stats` - Alert statistics
- `GET /api/alerts/sensor/{sensor}` - Alerts by sensor
- `GET /api/alerts/severity/{severity}` - Alerts by severity

### Event Log (Audit Trail)
- `GET /api/events/logs` - Get event logs with filtering
- `GET /api/events/stats` - Event statistics
- `GET /api/events/types` - Available event types
- `GET /api/events/export` - Export to CSV or JSON

Event filters: `limit`, `offset`, `event_type`, `action`, `resource`, `start_date`, `end_date`

### Logs
- `GET /api/logs` - Application logs (diagnostic/ros2)
- `GET /api/logs/sessions` - List all log sessions
- `GET /api/logs/session/{id}/files` - Files in session
- `GET /api/logs/read` - Read log file content
- `GET /api/logs/stream` - SSE log streaming

### Tools
- `POST /api/tools/ping` - Network ping test
- `POST /api/tools/config-validate` - Validate YAML configs

### Cache
- `GET /api/cache/stats` - Cache hit/miss statistics
- `POST /api/cache/invalidate` - Clear cache

## Sensor Configuration

| Sensor | IP | Topics | Detection Method | Expected Frequency |
|--------|-----|--------|------------------|-------------------|
| Navi LiDAR | 192.168.0.201 | `/navi_lidar/points` | Shell command → rclpy → topics | 10 Hz |
| U-LiDAR | 192.168.0.10 | None | Ping only | N/A |
| Camera | 192.168.0.11 | `/camera_info` | Shell command → rclpy → topics | 2 Hz |
| IMU | Serial | `/imu/data` | Shell command → rclpy → topics | 25 Hz |
| Thruster | 192.168.50.100 | `/thruster_status_pwm` | Ping + UDP heartbeat (port 28889) | 1 Hz heartbeat |

### Node/Topic Detection Priority

The system uses multiple methods with fallback priority:
1. **Shell command** (`ros2 node list` / `ros2 topic list`) - most reliable
2. **ROS2Monitor._check_nodes/topics()** - cached system queries
3. **rclpy helper** - direct Python API
4. **Metrics-based** - from sensor diagnostic results

### Connection State Caching

Sensors implement grace period logic to prevent false disconnections:
- **Grace period**: 30 seconds after last successful connection
- **Max consecutive failures**: 3 before showing disconnected
- **Alert cooldown**: 60 seconds between same alert type
- **State tracking**: `_was_connected` flag for transition detection

## Expected ROS2 Nodes

- `navi_lidar_driver` - Main LiDAR driver
- `galaxy_camera` - GigE camera driver
- `sbg_device` - IMU/GPS driver
- `thruster_wifi_node` - Thruster communication
- `sensor_compressor` - Data compression
- `recorder_node` - Rosbag recording

## Diagnostic Thresholds

Configured in [config.yaml](config.yaml):

```yaml
sensors:
  thresholds:
    navi_lidar:
      min_frequency: 8.0           # Hz
      max_packet_loss: 1.0         # Percentage
      min_points_per_frame: 50000

    camera:
      min_frequency: 1.5           # FPS
      max_frequency: 2.5           # FPS
      max_latency: 500             # ms
      expected_resolution: [4096, 3000]

    thruster:
      heartbeat_timeout: 5.0       # seconds (UDP heartbeat timeout)
      connection_grace_period: 30  # seconds
      max_consecutive_failures: 3  # before showing disconnected
```

## Tests

```bash
# Run all tests
pytest

# Run specific test categories
pytest tests/unit/
pytest tests/integration/
pytest tests/api/
pytest tests/ui/

# Run Playwright UI tests
pytest tests/ui/ --headed
```

## Notes

- **ROS2 Domain ID**: 42 (configurable in [config.yaml](config.yaml))
- **WebSocket Update Interval**: 5 seconds (sensors), 10 seconds (ROS2)
- **Chart History**: 30s (short), 90s (medium), 300s (long)
- **Cache TTL**: 5s (sensors/ROS2), 10s (frequency)
- **Event Logging**: Enabled by default, stores in `data/events.db`
- **Alert Storage**: SQLite database at `data/alerts.db`
- **Log Location**: Application logs in `logs/` directory
- **Service Logs**: `journalctl -u ros2-diagnostic -f` for live service logs
- **Service Restart**: Completes in <5 seconds (background tasks are properly cancelled)

## Time Machine Proxy

A standalone Flask proxy ([tm_proxy.py](tm_proxy.py)) is included for Time Machine device access with digest authentication forwarding. Runs on port 8083 by default.

## Development

### Adding New Sensors

1. Create diagnostic class in `diagnostics/sensor_monitor/`
2. Import in `diagnostics/sensor_monitor/__init__.py`
3. Add sensor config to [config.yaml](config.yaml)
4. Update `main.py` monitor factory
5. Add frontend UI in `templates/sensors.html`

Consider implementing:
- **Connection state caching** for resilience
- **Alert cooldown** to prevent duplicate notifications
- **Disconnection alerts** on state transitions
- **Node/topic patterns** for ROS2 detection

### Adding Event Logging

```python
from event_log import get_event_store, EventLog

event_store = get_event_store()
event_store.log_event(EventLog(
    event_type='your_event_type',
    action='your_action',
    resource='your_resource',
    message='Description of what happened',
    metadata=json.dumps({'key': 'value'}),  # Optional
    created_at=datetime.now().isoformat(),
    success=True
))
```

### Adding API Endpoints with Event Logging

```python
@app.post('/api/your-endpoint')
async def your_endpoint():
    event_store = get_event_store() if EVENT_LOG_CONFIG.get("enabled", True) else None
    try:
        # Your logic here
        result = do_something()

        # Log success event
        if event_store:
            event_store.log_event(EventLog(
                event_type='your_action',
                action='start',
                resource='your_resource',
                message='Action completed successfully',
                metadata=json.dumps(result),
                created_at=datetime.now().isoformat(),
                success=True
            ))

        return {'success': True, 'data': result}
    except Exception as e:
        # Log failure event
        if event_store:
            event_store.log_event(EventLog(
                event_type='your_action',
                action='start',
                resource='your_resource',
                message='Action failed',
                error=str(e),
                created_at=datetime.now().isoformat(),
                success=False
            ))
        return {'success': False, 'error': str(e)}
```

## Changelog

See [CHANGELOG.md](CHANGELOG.md) for version history and detailed changes.

## License

Part of the MSS Lecture project.
