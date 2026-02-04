# Camera Logging

## Overview

The Galaxy Camera uses the ROS2 RCUTILS logging system, outputting logs to standard output via `output='screen'`, which are then redirected to log files by the startup script.

## Log Locations

| File | Path | Description |
|------|------|-------------|
| Main Log | `logs/<run_id>/app/00_master.log` | Combined logs of all nodes |
| Camera Log | `logs/<run_id>/app/galaxy_camera.log` | Camera-specific logs (automatically extracted) |

## Log Extraction Mechanism

The Camera uses the same log extraction mechanism as Navi LiDAR:

1. **Startup Script**: [scripts/ros2/run_ros2_camera.sh](../../scripts/ros2/run_ros2_camera.sh)
   ```bash
   start_node_log_extractor "galaxy_camera" &
   ```

2. **Extraction Function**: [scripts/ros2/lib/logging.sh](../../scripts/ros2/lib/logging.sh:259-284)
   - Filters using `grep -E "\[(galaxy_camera[-_][0-9]+|galaxy_camera)\]"`
   - Tracks logs in real-time using `tail -f`

## Log Format

### Node Prefix

```
[galaxy_camera-1]
```

### Initialization Logs

```
[galaxy_camera-1] [INFO] [galaxy_camera] Starting 'galaxy_camera' at 4096x3000
[galaxy_camera-1] [INFO] [galaxy_camera] Target frame rate: 2.00 fps (period 500.00 ms)
[galaxy_camera-1] [INFO] [galaxy_camera] Camera opened with IP 192.168.0.11
[galaxy_camera-1] [INFO] [galaxy_camera] Detected network interface for camera: eno1
```

### GigE Configuration Logs

```
[galaxy_camera-1] [INFO] [galaxy_camera] ✓ Packet size set to 8192 bytes
[galaxy_camera-1] [INFO] [galaxy_camera] ✓ Inter-packet delay set to 8000µs
[galaxy_camera-1] [INFO] [galaxy_camera] ✓ Max wait packet count set to 9011
[galaxy_camera-1] [INFO] [galaxy_camera] ✓ Block timeout set to 60000ms
```

### Frame Status Logs

```
[galaxy_camera-1] [INFO] [galaxy_camera] Frame 1 status=SUCCESS(0) ts=10155814645808 bytes=12288000/12288000 gap=0
```

### BOTTLENECK ANALYSIS REPORT (Output every 3-4 frames)

```
[galaxy_camera-1] [INFO] [galaxy_camera] ========== BOTTLENECK ANALYSIS REPORT ==========
[galaxy_camera-1] [INFO] [galaxy_camera] [1] FRAME STATUS: Total=3, Published=3, SDKIncomplete=0 | Data loss: 0.0%
[galaxy_camera-1] [INFO] [galaxy_camera] [2] NETWORK INTERFACE (eno1): RX packets=31946 (45.57 MB, 364.5 Mbps), errors=0, dropped=0
[galaxy_camera-1] [INFO] [galaxy_camera] [3] CALLBACK (SDK->Queue): Avg=2.97 ms, Min=2.62 ms, Max=3.42 ms | Queue: 0/16 frames
[galaxy_camera-1] [INFO] [galaxy_camera] [4] PROCESSING THREAD: Avg=49.75 ms (Conversion=27.96 ms, Publish=21.79 ms)
[galaxy_camera-1] [INFO] [galaxy_camera] ================================================
```

## Key Metrics

| Metric | Meaning | Normal Value |
|--------|---------|--------------|
| `Total` | Total frames | Continuously increasing |
| `Published` | Published frames | ≈ Total |
| `SDKIncomplete` | SDK incomplete frames | 0 |
| `Data loss` | Data loss percentage | 0.0% |
| `RX packets` | Network received packets | Proportional to frame rate |
| `errors/dropped` | Network errors/dropped packets | 0 |
| `Avg CALLBACK` | Average callback time | < 5ms |
| `Avg PROCESSING` | Average processing thread time | < 100ms |

## Comparison with Navi LiDAR

| Feature | Navi LiDAR | Camera |
|---------|-----------|--------|
| Node Name | `navi_lidar_driver` | `galaxy_camera` |
| Log Prefix | `[hesai_ros_driver_node-1]` | `[galaxy_camera-1]` |
| SDK Logging Method | `printf()` bypassing RCUTILS | RCUTILS normal output |
| Special Handling Required | Yes | No |
| Statistics Report Interval | Every 100 frames | Every 3-4 frames |

## Troubleshooting

### Network Issues

```
[galaxy_camera-1] [WARN] [galaxy_camera] Could not set socket buffer size (status=-11)
```

### Processing Delay Warning

```
[galaxy_camera-1] [WARN] [galaxy_camera] [4] ⚠️  Processing thread is slow (49.75 ms) - may impact throughput
```

### SDK Callback Delay Warning

```
[galaxy_camera-1] [WARN] [galaxy_camera] [3] ⚠️  SDK callback is slow (8.90 ms) - should be < 5ms
```

## Configuration Files

- **Driver Configuration**: [config/camera/ros2.yaml](../../config/camera/ros2.yaml)
- **Calibration Configuration**: [config/camera/camera_calibration.yaml](../../config/camera/camera_calibration.yaml)
- **Startup Script**: [scripts/ros2/run_ros2_camera.sh](../../scripts/ros2/run_ros2_camera.sh)
- **Launch File**: [ros2_ws/src/ros2_bringup/launch/camera.launch.py](../../ros2_ws/src/ros2_bringup/launch/camera.launch.py)

## Testing and Verification

```bash
# 1. Verify hardware connection
ping -c 2 192.168.0.11

# 2. Run camera
./scripts/ros2/run_ros2_camera.sh

# 3. Check log files
ls -la logs/$(ls -t logs/ | head -1)/app/

# 4. View camera-specific logs
tail -50 logs/$(ls -t logs/ | head -1)/app/galaxy_camera.log

# 5. Search for BOTTLENECK REPORT
grep -A 10 "BOTTLENECK ANALYSIS REPORT" logs/$(ls -t logs/ | head -1)/app/galaxy_camera.log
```

## Next Steps for Improvement

- [x] Create `camera_log_parser.py` to parse logs
- [x] Update `ros2_diagnostic/diagnostics/sensor_monitor/camera.py` to add data quality checks
- [ ] Add single-line summary logs (output once per second)

## Data Quality Diagnostics

### Diagnostic Modules

**File**: [ros2_diagnostic/diagnostics/camera_log_parser.py](../../ros2_diagnostic/diagnostics/camera_log_parser.py)

**Functionality**:
- Parses BOTTLENECK ANALYSIS REPORT
- Extracts frame rate, frame drops, network statistics, processing delays

**File**: [ros2_diagnostic/diagnostics/sensor_monitor/camera.py](../../ros2_diagnostic/diagnostics/sensor_monitor/camera.py)

**Monitoring Items**:
- Frame drop detection (SDKIncomplete + Queue drops)
- Frame rate anomalies (min_frequency: 1.5 Hz, max_frequency: 2.5 Hz)
- Network packet loss (errors, dropped)
- High processing delays (max_latency: 500 ms)

### Threshold Configuration

From [ros2_diagnostic/config.yaml](../../ros2_diagnostic/config.yaml:82-88):

```yaml
camera:
  min_frequency: 1.5           # Minimum frame rate (Hz)
  max_frequency: 2.5           # Maximum frame rate (Hz)
  max_latency: 500             # Maximum latency (ms)
```

### Alert Levels

| Status | Condition |
|--------|-----------|
| CRITICAL | Frame rate < 0.75 Hz or frame drops > 10% or network errors > 10 |
| WARNING | Frame rate < 1.5 Hz or frame drops or processing delay > 500 ms |
| OK | All metrics normal |
