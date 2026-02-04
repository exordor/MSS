# Navi LiDAR Logging System Analysis

## Overview

Navi LiDAR uses the Hesai QT128 LiDAR, driven by the `hesai_ros_driver` ROS2 node. This document analyzes its logging mechanism, log paths, and formats.

## Logging System Architecture

```
┌─────────────────────────────────────────────────────────────────────────┐
│                        Navi LiDAR Log Flow                            │
├─────────────────────────────────────────────────────────────────────────┤
│                                                                         │
│  ┌──────────────┐     ┌──────────────┐     ┌─────────────────────┐     │
│  │ Hesai SDK    │────▶│  ROS2 Node   │────▶│  output='screen'    │     │
│  │ (C++ Logger) │     │  (rclcpp)    │     │  (stdout/stderr)    │     │
│  └──────────────┘     └──────────────┘     └─────────┬───────────┘     │
│                                                     │                  │
│                                                     ▼                  │
│  ┌────────────────────────────────────────────────────────────────┐  │
│  │         run_ros2_navi_lidar.sh (logging.sh)                   │  │
│  │  ┌─────────────────────────────────────────────────────────┐  │  │
│  │  │  exec > >(tee -i ${APP_LOG_DIR}/00_master.log)         │  │  │
│  │  │  exec 2>&1                                              │  │  │
│  │  └─────────────────────────────────────────────────────────┘  │  │
│  └────────────────────────────────────────────────────────────────┘  │
│                               │                                      │
│                               ▼                                      │
│  ┌────────────────────────────────────────────────────────────────┐ │
│  │     logs/YYYYMMDD_HHMMSS/                                      │ │
│  │        ├── ros/              (ROS2 internal logs)              │ │
│  │        ├── app/00_master.log (Complete log output)             │ │
│  │        └── meta/runtime.json  (Runtime metadata)               │ │
│  └────────────────────────────────────────────────────────────────┘ │
│                                                                         │
└─────────────────────────────────────────────────────────────────────┘
```

## Log Directory Structure

```
logs/
└── YYYYMMDD_HHMMSS/
    ├── ros/                                    # ROS2 internal logs
    │   ├── hesai_ros_driver_node_<pid>_<timestamp>.log
    │   └── 2026-01-27-17-18-57-xxxxx-ubuntu-xxxxx/  # Launch system logs
    │       └── launch.log
    ├── app/                                    # Application logs
    │   ├── 00_master.log                       # Complete log (all stdout/stderr)
    │   └── navi_lidar_driver.log               # Navi LiDAR-specific log (auto-extracted)
    └── meta/                                   # Metadata
        ├── runtime.json                        # Runtime information
        └── launch_cmd.txt                      # Launch command
```

## Three Log Sources

### 1. ROS2 Launch System Logs

**Format**: `[LEVEL] [launch]: message`

**Example**:
```
[INFO] [launch]: All log files can be found below /home/eagrumo/mss_lecture/logs/...
[INFO] [launch]: Default logging verbosity is set to INFO
[INFO] [hesai_ros_driver_node-1]: process started with pid [27368]
```

**Source**: ROS2 Launch system + RCUTILS

**Target Files**: `launch.log`, `00_master.log`

---

### 2. Hesai SDK Internal Logger Logs

**Format**: `[YYYY-MM-DD HH:MM:SS][LEVEL] message`

**Example**:
```
[2026-01-27 17:18:15][INFO]logger start to run
[2026-01-27 17:18:15][INFO]OS current udp socket recv buff size is: 20971520
[2026-01-27 17:18:15][INFO]SocketSource::Open succeed, sock:19
[2026-01-27 17:18:15][ERROR]Multicast IP error, set correct multicast ip address or keep it empty
[2026-01-27 17:18:15][WARNING]cpu version, not support for gpu
```

**Source**: Hesai SDK Internal Logger ([`libhesai/Logger/src/logger.cc`](../ros2_ws/src/navi_lidar/src/driver/HesaiLidar_SDK_2.0/libhesai/Logger/src/logger.cc))

**Output Method**: `printf()` directly to stdout

**Target File**: `00_master.log`

---

### 3. Point Cloud Data Output Logs

**Format**: `raw frame:X points:Y packet:Z start time:... end time:...`

**Example**:
```
[hesai_ros_driver_node-1] raw frame:0 points:22272 packet:87 start time:1602246458.417039 end time:1602246458.436148
[hesai_ros_driver_node-1] raw frame:1 points:115200 packet:450 start time:1602246458.436371 end time:1602246458.536147
```

**Source**: Direct `std::cout` output (bypassing the Logger system)

**Reason**: Performance considerations to avoid logging system overhead

**Target File**: `00_master.log`

---

## Why Are Logs Primarily in 00_master.log?

### Analysis

```
┌─────────────────────────────────────────────────────────────────────────┐
│                        ROS2 Logging System Explanation                │
├─────────────────────────────────────────────────────────────────────────┤
│                                                                         │
│  ┌─────────────────┐      ┌─────────────────┐      ┌─────────────────┐ │
│  │  Hesai SDK      │      │  ROS2 RCUTILS   │      │  ROS2 Launch    │ │
│  │  (printf)       │      │  (RCLCPP_*)     │      │  (launch.py)    │ │
│  └────────┬────────┘      └────────┬────────┘      └────────┬────────┘ │
│           │                        │                        │            │
│           ▼                        ▼                        ▼            │
│  ┌─────────────────────────────────────────────────────────────────┐  │
│  │                    stdout/stderr                               │  │
│  │        [2026-01-27 17:18:15][INFO]logger start to run         │  │
│  │        -------- Hesai Lidar ROS V2.0.11 --------               │  │
│  │        raw frame:0 points:22272...                             │  │
│  └──────────────────────────────┬──────────────────────────────────┘  │
│                                 │                                      │
│         ┌───────────────────────┴───────────────────────┐             │
│         ▼                                              ▼             │
│  ┌──────────────┐                              ┌──────────────┐           │
│  │ output='screen'│                              │  ROS2 Logger  │           │
│  │   → stdout   │                              │  (internal)   │           │
│  └──────┬───────┘                              └──────┬───────┘           │
│         │                                             │                   │
│         │     ┌────────────────────────────────────────┘             │
│         │     ▼                                                │        │
│         │  ┌─────────────────────┐                            │        │
│         │  │  hesai_ros_driver_  │ ← RCUTILS logs               │        │
│         │  │  node_27368_*.log   │   (only signal_handler)      │        │
│         │  └─────────────────────┘                            │        │
│         │                                                     │        │
│         ▼                                                     │        │
│  ┌──────────────┐                                           │        │
│  │   tee →      │                                           │        │
│  │ 00_master.log│ ← All stdout/stderr (Hesai SDK + Launch)  │        │
│  └──────────────┘                                           │        │
│                                                             │        │
└─────────────────────────────────────────────────────────────────────┘
```

### Key Points

1. **ROS2 RCUTILS Logging System** → `hesai_ros_driver_node_*.log`
   - Only logs emitted via `RCLCPP_*` macros
   - Hesai driver rarely uses these macros
   - Only signal_handler logs are recorded

2. **Hesai SDK Logger** → `printf(stdout)` → `00_master.log`
   - Uses its own Logger, directly outputs via `printf`
   - Does not enter the ROS2 RCUTILS system
   - Captured by `output='screen'` and written to `00_master.log`

3. **Point Cloud Data Output** → `std::cout(stdout)` → `00_master.log`
   - Direct printing, bypassing the logging system
   - For performance reasons

---

## Configuration Files

### Main Configuration File

**Path**: [`config/navi_lidar/qt128.yaml`](../config/navi_lidar/qt128.yaml)

**Key Configurations**:
```yaml
lidar:
  - driver:
      source_type: 1                                  # 1: Real-time, 2: pcap, 3: rosbag
      lidar_udp_type:
        device_ip_address: 192.168.0.201
        udp_port: 2368
        ptc_port: 9347
        multicast_ip_address: 255.255.255.0
        use_ptc_connected: true
  - ros:
      ros_frame_id: navi_lidar
      ros_send_point_cloud_topic: /navi_lidar/points
      send_point_cloud_ros: true
```

### Launch File

**Path**: [`ros2_ws/src/ros2_bringup/launch/navi_lidar.launch.py`](../ros2_ws/src/ros2_bringup/launch/navi_lidar.launch.py)

```python
lidar_node = Node(
    package='hesai_ros_driver',
    executable='hesai_ros_driver_node',
    name='navi_lidar_driver',
    output='screen',              # Key: Logs output to stdout
    parameters=[{'config_path': LaunchConfiguration('config')}],
    ros_arguments=['--log-level', LaunchConfiguration('log_level')],
)
```

### Logging Configuration File

**Path**: [`config/logging/logging.yaml`](../config/logging/logging.yaml)

Defines 4 logging profiles:
- `dev`: Development environment, colored output
- `prod`: Production environment, structured logs
- `debug`: Debug environment, includes file/line number
- `minimal`: Minimal configuration, errors only

---

## Usage

### Basic Startup

```bash
# Use default profile (dev)
./scripts/ros2/run_ros2_navi_lidar.sh

# Use production profile
./scripts/ros2/run_ros2_navi_lidar.sh --log-profile prod

# Use debug profile
./scripts/ros2/run_ros2_navi_lidar.sh --log-profile debug

# Via environment variable
LOG_PROFILE=prod ./scripts/ros2/run_ros2_navi_lidar.sh
```

### Viewing Logs

```bash
# View the latest master log
tail -f logs/$(ls -t logs/ | head -1)/app/00_master.log

# View runtime metadata
cat logs/$(ls -t logs/ | head -1)/meta/runtime.json

# View launch command
cat logs/$(ls -t logs/ | head -1)/meta/launch_cmd.txt
```

---

## Runtime Metadata Example

```json
{
  "start_time": "2026-01-27T17:18:13+01:00",
  "run_id": "20260127_171813",
  "launcher": "./scripts/ros2/run_ros2_navi_lidar.sh",
  "user": "eagrumo",
  "hostname": "ubuntu",
  "ros_distro": "humble",
  "ros_domain_id": "42",
  "log_root": "/home/eagrumo/mss_lecture/logs/20260127_171813",
  "ros_log_dir": "/home/eagrumo/mss_lecture/logs/20260127_171813/ros"
}
```

---

## Profile Comparison

| Profile | Colored | Log Level | Format | Use Case |
|---------|---------|-----------|--------|----------|
| **dev** | ✅ | info | `[{severity}] [{name}] {message}` | Daily development |
| **prod** | ❌ | warn | `[{time}] [{severity}] [{name}] {message}` | Production |
| **debug** | ✅ | debug | `[{time}] [{severity}] [{name}] [{file}:{line}] {message}` | Debugging |
| **minimal** | ❌ | error | `{severity}: {message}` | Minimal logging |

---

## Log Level Overrides

```bash
# Use profile but override log level
./scripts/ros2/run_ros2_navi_lidar.sh --log-profile prod --log-level debug
# Result: Uses debug level, but other prod settings remain (e.g., no color)
```

---

## Reference Files

- Hesai SDK Logger: [`ros2_ws/src/navi_lidar/src/driver/HesaiLidar_SDK_2.0/libhesai/Logger/`](../ros2_ws/src/navi_lidar/src/driver/HesaiLidar_SDK_2.0/libhesai/Logger/)
- ROS2 Node: [`ros2_ws/src/navi_lidar/node/hesai_ros_driver_node.cc`](../ros2_ws/src/navi_lidar/node/hesai_ros_driver_node.cc)
- Launch File: [`ros2_ws/src/ros2_bringup/launch/navi_lidar.launch.py`](../ros2_ws/src/ros2_bringup/launch/navi_lidar.launch.py)
- Logging Library: [`scripts/ros2/lib/logging.sh`](../scripts/ros2/lib/logging.sh)
- Logging Configuration: [`config/logging/logging.yaml`](../config/logging/logging.yaml)

---

## navi_lidar_driver.log - Dedicated Log File

### Generation Method

Generated in real-time by the `start_node_log_extractor()` function from `00_master.log`.

**Implementation Location**: [`scripts/ros2/lib/logging.sh`](../scripts/ros2/lib/logging.sh)

### Log Content

`navi_lidar_driver.log` includes:
- Hesai SDK initialization logs
- Network connection logs
- Point cloud frame output
- All logs with `[hesai_ros_driver_node-N]` prefix

### Example

```
[INFO] [hesai_ros_driver_node-1]: process started with pid [41413]
[hesai_ros_driver_node-1] -------- Hesai Lidar ROS V2.0.11 --------
[hesai_ros_driver_node-1] [2026-01-27 17:53:45][INFO]logger start to run
[hesai_ros_driver_node-1] [2026-01-27 17:53:45][INFO]SocketSource::Open succeed, sock:19
[hesai_ros_driver_node-1] raw frame:0 points:54784 packet:214 start time:1602248588.744757
[hesai_ros_driver_node-1] raw frame:1 points:115200 packet:450 start time:1602248588.792298
```

### Advantages

- **Focused on Navi LiDAR**: No need to filter other node outputs
- **Fully Retained**: Saved alongside `00_master.log`
- **Real-Time Updates**: Background process continuously monitors and extracts

### Viewing Dedicated Logs

```bash
# View Navi LiDAR-specific logs
tail -f logs/$(ls -t logs/ | head -1)/app/navi_lidar_driver.log

# Count frames
grep "raw frame" logs/$(ls -t logs/ | head -1)/app/navi_lidar_driver.log | wc -l
```

