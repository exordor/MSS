# Changelog

All notable changes to ros2_diagnostic will be documented in this file.

## [Unreleased]

### Added - Event Logging System

Added SQLite-based audit trail for tracking all system actions and events.

**Files added:**
- `event_log.py` - EventLog dataclass and EventStore class
- `data/events.db` - SQLite database for event storage

**Files modified:**
- `main.py` - Added event logging to all action endpoints (ROS2 start/stop, rosbag, alerts)
- `templates/events.html` - Event log viewer page

**Features:**
- Persistent event logging with timestamp tracking
- Event types: system_start, ros2_start/stop, rosbag_start/stop, alert_resolved/ignored
- Export support: CSV and JSON formats
- Event filtering by type, action, resource, date range
- Event statistics dashboard

### Added - Connection State Caching

Added grace period logic to prevent false disconnections from transient network failures.

**Files modified:**
- `diagnostics/sensor_monitor/navi_lidar.py` - Added connection state caching
- `diagnostics/sensor_monitor/thruster.py` - Added connection state caching

**Features:**
- Grace period: 30 seconds after last successful connection
- Max consecutive failures: 3 before showing disconnected
- Alert cooldown: 60 seconds between same alert type
- State tracking with `_was_connected` flag for transition detection

### Added - Disconnection Alerts

Added automatic alert generation when sensors transition from connected to disconnected state.

**Files modified:**
- `diagnostics/sensor_monitor/navi_lidar.py` - Added disconnection alert recording
- `diagnostics/sensor_monitor/thruster.py` - Added disconnection alert recording

**Features:**
- Records critical alert on disconnection state transition
- Includes IP address and reason in alert metadata
- Cooldown period prevents alert spam

### Changed - Node/Topic Detection Priority

Reordered detection methods to prioritize shell commands for more reliable ROS2 detection.

**Files modified:**
- `main.py` - Updated `_get_node_available()` and `_get_topic_available()` functions
- `static/js/main.js` - Update ROS2 data before sensors (ensures caches are populated)

**Detection priority:**
1. Shell command (`ros2 node list` / `ros2 topic list`) - most reliable
2. ROS2Monitor._check_nodes/topics() - cached system queries
3. rclpy helper - direct Python API
4. Metrics-based - from sensor diagnostic results

### Changed - Thruster UDP Heartbeat

Migrated thruster monitoring from TCP connection to UDP heartbeat detection.

**Files modified:**
- `diagnostics/sensor_monitor/thruster.py` - Replaced TCP with UDP heartbeat logic

**Features:**
- Binds to UDP port 28889 to receive heartbeat/data from Arduino
- Detects HEARTBEAT, S status, F flow messages
- Timeout-based detection (no data for >5 seconds = offline)
- Matches logic from thruster_wifi_node.cpp

### Added - Systemd Service

Added systemd service configuration for automatic startup on boot.

**Files added:**
- `../../config/ros2-diagnostic.service` - Systemd service file

**Features:**
- ROS2 environment variables configured (PATH, AMENT_PREFIX_PATH, PYTHONPATH, LD_LIBRARY_PATH)
- ROS_DOMAIN_ID=42 set in service environment
- Automatic restart on failure (RestartSec=5)
- Journal logging for diagnostics

### Removed - Duplicate API Endpoints

Cleaned up duplicate Event Log API endpoints in main.py.

**Files modified:**
- `main.py` - Removed duplicate Event Log endpoints (previously lines 2250-2343)

### Changed

- **Sensors Page**: Simplified all sensor panels to display only connection status
  - Removed ROS2 Topics table from Navi LiDAR panel
  - Removed ROS2 Topics table from U-LiDAR panel
  - Removed Current Settings section from Camera panel
  - Removed GPS Information section from IMU panel
  - Thruster panel unchanged (already had only connection status)

### Files Modified
- `templates/sensors.html` - Unified sensor panel structure



### Fixed - Dashboard JavaScript Cache and Debugging

**Problem:** Dashboard could show stale "Error loading data" messages due to browser caching old JavaScript code. Also, IMU sensor was returning HTTP 500 errors.

**Files modified:**
- `app.py` - Added `@app.after_request` handler to disable caching for JavaScript files
- `static/js/dashboard.js` - Enhanced logging for API response debugging
- `diagnostics/sensor_monitor/imu.py` - Fixed missing `logger` import

**Files modified:**
- `app.py` - Added `@app.after_request` handler to disable caching for JavaScript files
- `static/js/dashboard.js` - Enhanced logging for API response debugging

**Changes:**
- JavaScript files now return `Cache-Control: no-store, no-cache, must-revalidate, max-age=0`
- Added `Pragma: no-cache` and `Expires: 0` headers for `.js` files
- Enhanced console logging: `success=${data.success}, hasData=${!!data.data}`
- Added warning log when API check fails: shows `success`, `hasData`, and `error` values
- Fixed IMU diagnostic: added missing `import logging` and `logger = logging.getLogger(__name__)`

**Result:**
- Browser always loads latest JavaScript, preventing stale error states
- IMU sensor now returns valid responses instead of HTTP 500

---

### Added - Camera Log Parser & Data Quality Monitoring

Added real-time log parser for monitoring Camera data quality (frame loss, network issues, processing latency).

**Files added:**
- `diagnostics/camera_log_parser.py` - Parses Galaxy Camera BOTTLENECK ANALYSIS REPORT output

**Files modified:**
- `diagnostics/sensor_monitor/camera.py` - Integrated log-based data quality checks

**Features:**
- Frame frequency monitoring (detects frame loss below 1.5 Hz or above 2.5 Hz)
- Frame drop tracking (SDKIncomplete + Queue drops)
- Network error/dropped packet monitoring
- Processing latency monitoring (threshold: 500 ms)
- Thread-safe statistics collection with caching
- Automatic log file discovery (supports `app/00_master.log` and `app/galaxy_camera.log`)

**Thresholds (from config.yaml):**
- `min_frequency: 1.5` Hz - Below = WARNING, below 0.75 Hz = CRITICAL
- `max_frequency: 2.5` Hz - Above 3.75 Hz = WARNING
- `max_latency: 500` ms - Above = WARNING
- Frame drops > 10% = CRITICAL, any drops = WARNING

**Log output format parsed:**
```
[galaxy_camera-1] ========== BOTTLENECK ANALYSIS REPORT ==========
[galaxy_camera-1] [1] FRAME STATUS: Total=3, Published=3, SDKIncomplete=0
[galaxy_camera-1] [2] NETWORK INTERFACE (eno1): errors=0, dropped=0
[galaxy_camera-1] [3] CALLBACK: Avg=2.97 ms
[galaxy_camera-1] [4] PROCESSING THREAD: Avg=49.75 ms
```

### Added - Camera Log Extraction

Added automatic log extraction for Camera node to separate `galaxy_camera.log` from master log.

**Files modified:**
- `../../scripts/ros2/run_ros2_camera.sh` - Added `start_node_log_extractor "galaxy_camera"` call

**Result:**
- Creates `logs/<run_id>/app/galaxy_camera.log` with filtered camera logs
- Uses same extraction mechanism as navi_lidar (grep + tail -f)

### Fixed - run_ros2_all.sh Missing Log Extractors

**Problem:** Flask web controller and direct `run_ros2_all.sh` execution did not create separate sensor log files.

**Root Cause:** `run_ros2_all.sh` bypassed individual sensor scripts (`run_ros2_navi_lidar.sh`, `run_ros2_camera.sh`) which contain the `start_node_log_extractor` calls.

**Files modified:**
- `../../scripts/ros2/run_ros2_all.sh` - Added log extractors for all sensor nodes

**Result:**
- Now creates separate log files when using Flask or `run_ros2_all.sh`:
  - `navi_lidar_driver.log` (Navi LiDAR)
  - `galaxy_camera.log` (Camera)
  - `sbg_device.log` (IMU)
  - `thruster_wifi_node.log` (Thruster)
  - `sensor_downsample_node.log` (Compressor)
  - `recorder_node.log` (Recorder)
  - `zda_publisher.log` (ZDA Publisher)
- Includes cleanup trap to kill extractor processes on exit

### Fixed - Dashboard Sensor Cards Not Loading

**Problem:** Dashboard sensor cards for navi_lidar and camera were not displaying frequency/packet loss data.

**Root Cause:** API endpoint `/api/sensors/status` was looking for metrics in wrong path:
- Looking for: `metrics['frequency']['measured']`
- Actual path: `metrics['log_data']['measured_frequency']`

**Files modified:**
- `app.py` - Fixed metrics path for navi_lidar, uli_lidar, camera, and imu sensors

**Result:**
- navi_lidar: frequency now correctly read from `metrics['log_data']['measured_frequency']`
- camera: fps (frequency) now correctly read from `metrics['log_data']['measured_frequency']`
- camera: processing latency now correctly read from `metrics['log_data']['avg_processing_ms']`
- imu: frequency now correctly read from `metrics['log_data']['measured_frequency']`

### Changed - Logging Timestamp Format

Added timestamps to `dev` profile logging format for all ROS2 nodes.

**Files modified:**
- `../../config/logging/logging.yaml` - Changed `dev` profile format from `[{severity}] [{name}] {message}` to `[{time}] [{severity}] [{name}] {message}`

**Impact:**
- All nodes using `dev` profile (default) now include timestamps in log output
- Affects: navi_lidar, camera, imu, thruster, and other nodes
- Format: `[seconds.nanoseconds] [INFO] [node_name] message`

### Fixed - Sensor Connection Logic

**Priority: Physical connection over ROS2 status**

Modified sensor monitors to check physical connectivity BEFORE checking ROS2 system status.
This ensures sensors show correct "Connected" status when hardware is connected but ROS2 is not running.

**Files modified:**
- `diagnostics/sensor_monitor/navi_lidar.py` - Network ping check first
- `diagnostics/sensor_monitor/camera.py` - Network ping check first
- `diagnostics/sensor_monitor/imu.py` - USB serial port check first
- `diagnostics/sensor_monitor/thruster.py` - Network ping + TCP connection check first

**Status decision flow:**
1. Physical connection failed? → DISCONNECTED
2. System not running? → CONNECTED (hardware ok, ROS2 not running)
3. Data quality issues? → WARNING / CRITICAL
4. Connected but no data? → CONNECTED
5. Everything normal → OK

### Fixed - StatusLevel.UNKNOWN

Added `UNKNOWN` status level to fix errors in ROS2 Monitor API.

**Files modified:**
- `diagnostics/base.py` - Added `UNKNOWN = "unknown"` to StatusLevel enum and STATUS_PRIORITY

### Improved - ROS2Helper

Enhanced `is_ready()` method to properly check rclpy initialization status.

**Files modified:**
- `diagnostics/ros2_helper.py` - Added try/except check for rclpy.ok() in is_ready()

### Added - Navi LiDAR Log Parser

Added real-time log parser for monitoring LiDAR data quality (frame loss, point count reduction).

**Files added:**
- `diagnostics/lidar_log_parser.py` - Parses Hesai LiDAR log output from `raw frame` lines

**Files modified:**
- `diagnostics/sensor_monitor/navi_lidar.py` - Integrated log-based data quality checks

**Features:**
- Frame frequency monitoring (detects frame loss below threshold)
- Point cloud count tracking (detects point count reduction below threshold)
- Thread-safe statistics collection with caching
- Automatic log file discovery (supports `app/00_master.log` and `navi_lidar_driver.log`)

**Thresholds (from config.yaml):**
- `min_frequency: 8.0` Hz - Below = WARNING, below 4.0 Hz = CRITICAL
- `min_points_per_frame: 50000` - Below = WARNING, below 25000 = CRITICAL

**Log output format parsed:**
```
[hesai_ros_driver_node-1] raw frame:49 points:115200 packet:450 start time:1602248443.495515 end time:1602248443.595332
```

### Added - Playwright Tests

Created end-to-end tests to verify frontend matches API results.

**Files added:**
- `../../test_ros2_diagnostic.spec.js` - 12 basic functionality tests
- `../../test_frontend_api_consistency.spec.js` - 5 frontend-API consistency tests

**Tests verify:**
- Sensor table status matches API responses
- ROS2 control panel state matches API
- Connection status matches API
- All API endpoints respond correctly
- Sensor data structure is complete

---

## Format

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.0.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

Types of changes:
- `Added` for new features
- `Changed` for changes in existing functionality
- `Deprecated` for soon-to-be removed features
- `Removed` for now removed features
- `Fixed` for any bug fixes
- `Security` in case of vulnerabilities
