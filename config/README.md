# Configuration Files Directory

This directory contains configuration files for various sensors and systems used by ROS1 and ROS2 nodes.

## Directory Structure

```
config/
├── camera/              # Camera configuration
│   ├── ros1.yaml       # ROS1 Galaxy Camera configuration
│   ├── ros2.yaml       # ROS2 Galaxy Camera configuration
│   └── camera_calibration.yaml  # Camera calibration file (intrinsics and distortion coefficients)
├── imu/                # IMU configuration
│   ├── sbg_ros1.yaml  # ROS1 SBG IMU configuration
│   └── sbg_ros2.yaml  # ROS2 SBG IMU configuration
├── navi_lidar/         # LiDAR configuration
│   └── qt128.yaml      # Hesai Qt128 configuration
├── ptp/               # PTP time synchronization configuration
│   ├── ptp_master.conf     # PTP master clock configuration
│   ├── ptp_client.conf     # PTP client clock configuration
│   ├── phc2sys-client.service  # systemd service configuration
│   ├── ptp4l-client.service
│   ├── ptp4l-master.service
│   └── phc2sys-client.service
├── rosbag/             # Rosbag recording configuration
│   └── rosbag_ros2.yaml # ROS2 rosbag parameters
└── thruster/           # Thruster configuration
    ├── thruster.yaml       # Thruster configuration
    └── thruster_wifi.yaml # WiFi thruster configuration
```

## Camera Configuration (`camera/`)

### `ros1.yaml` / `ros2.yaml`
Configuration files for Galaxy Camera nodes.

**Main Parameters:**

| Parameter | Description | Default | Unit |
|-----------|-------------|----------|-------|
| `camera_ip` | Camera IP address (GigE Vision network) | 192.168.0.11 | - |
| `camera_frame_id` | TF frame ID | camera | - |
| `camera_name` | Camera name (must match calibration file) | galaxy_camera | - |
| `camera_info_url` | Calibration file path (absolute path with `file:///` prefix) | - | - |
| `image_width/height` | Image resolution | 4096x3000 | pixels |
| `pixel_format` | ROS output pixel format | bgr8 | - |
| `camera_pixel_format` | Camera sensor Bayer pattern | BayerRG8 | - |
| `frame_rate` | Target frame rate | 2.0 | fps |
| `processing_queue_depth` | Processing queue depth | 8-16 | frames |
| `exposure_auto` | Auto exposure mode | false | - |
| `exposure_value` | Manual exposure value | 4000 | microseconds(μs) |
| `gain_auto` | Auto gain mode | false | - |
| `gain_value` | Manual gain value | 15 | - |
| `white_auto` | Auto white balance | true | - |
| `gev_packet_size` | GigE max packet size | 8192 | bytes |
| `GevSCPD` | Inter-packet delay | 8000 | microseconds(μs) |
| `ptp_enable` | PTP time synchronization | true | - |
| `enable_custom_compression` | Custom compression (recommended: false) | false | - |

**Usage:**

```bash
# ROS1
roslaunch galaxy_camera camera.launch config:=/path/to/camera/ros1.yaml

# ROS2 (using scripts)
./scripts/ros1/run_ros1_camera.sh --config /path/to/camera/ros1.yaml
./scripts/ros2/run_ros2_camera.sh --config /path/to/camera/ros2.yaml

# ROS2 (direct launch)
ros2 launch galaxy_camera camera.launch.py
```

### `camera_calibration.yaml`
Camera calibration file containing intrinsic parameters and distortion coefficients.

**Field Description:**

```yaml
image_width: 4096          # Image width
image_height: 3000         # Image height
camera_name: galaxy_camera   # Camera name

# Camera intrinsic matrix (3x3)
# K = [fx  0  cx]
#     [ 0 fy  cy]
#     [ 0  0   1]
camera_matrix:
  rows: 3
  cols: 3
  data: [fx, 0, cx, 0, fy, cy, 0, 0, 1]

# Distortion coefficients (5 parameters, plumb_bob model)
# [k1, k2, p1, p2, k3]
distortion_coefficients:
  rows: 1
  cols: 5
  data: [k1, k2, p1, p2, k3]
```

**Generating Calibration File:**

```bash
# ROS2 camera calibration
ros2 run camera_calibration cameracalibrator \
  --size 8x6 \
  --square 0.108 \
  image:=/image_raw \
  camera:=/camera

# After calibration completes, select Save to generate .yaml file
# Copy to this directory and update camera_info_url path
```

**Important Notes:**

1. Calibration file path must use `file:///` prefix with absolute path
   - ✅ Correct: `file:///home/eagrumo/mss_lecture/config/camera/camera_calibration.yaml`
   - ❌ Wrong: `file://camera_calibration.yaml`
   - ❌ Wrong: `package://galaxy_camera/config/camera_calibration.yaml`

2. `camera_name` must match the name in the calibration file

3. Resolution settings must match the resolution used during calibration

## IMU Configuration (`imu/`)

Configuration files for SBG IMU sensors.

**Main Parameters:**

| Parameter | Description | Default |
|-----------|-------------|----------|
| `port` | Serial port device | /dev/ttyUSB0 |
| `baudrate` | Baud rate | 921600 |
| `output_frequency` | Output frequency | 100 | Hz |
| `publish_tf` | Whether to publish TF | true |
| `frame_id` | TF frame ID | imu_link |

**Usage:**

```bash
# ROS1
roslaunch sbg_ros_driver sbg_driver.launch config:=/path/to/imu/sbg_ros1.yaml

# ROS2
ros2 launch sbg_ros_driver sbg_driver.launch.py config:=/path/to/imu/sbg_ros2.yaml
```

## LiDAR Configuration (`navi_lidar/`)

Configuration file for Livox Qt128 LiDAR.

**Main Parameters:**

| Parameter | Description | Default |
|-----------|-------------|----------|
| `ip` | LiDAR IP address | 192.168.1.100 |
| `port` | LiDAR port | 8080 |
| `publish_freq` | Publishing frequency | 10 | Hz |
| `scan_pattern` | Scan pattern | NonRepetitive |

**Usage:**

```bash
# ROS2
ros2 launch livox_ros_driver2 msg_MID360_launch.py config:=/path/to/navi_lidar/qt128.yaml
```

## PTP Time Synchronization Configuration (`ptp/`)

PTP (Precision Time Protocol) for sub-microsecond multi-sensor time synchronization.

**Configuration Files:**

- `ptp_master.conf` - PTP master clock (typically on network switch or gateway)
- `ptp_client.conf` - PTP client clock (cameras, IMU, LiDAR, etc.)

**systemd Services:**

| Service File | Description |
|--------------|-------------|
| `ptp4l-master.service` | PTP master clock daemon |
| `ptp4l-client.service` | PTP client clock daemon |
| `phc2sys-client.service` | Sync hardware clock to system clock |

**Usage:**

```bash
# Enable and start services
sudo systemctl enable ptp4l-client
sudo systemctl enable phc2sys-client
sudo systemctl start ptp4l-client
sudo systemctl start phc2sys-client

# Check synchronization status
./scripts/ptp_status.sh
```

**Network Requirements:**

- Switch must support PTP (IEEE 1588)
- Recommended to use network interface cards with hardware PTP support
- Latency < 100 ns

## Thruster Configuration (`thruster/`)

Configuration file for thruster control nodes.

**Main Parameters:**

| Parameter | Description | Default |
|-----------|-------------|----------|
| `thruster_count` | Number of thrusters | 6 |
| `max_thrust` | Maximum thrust | 100 | % |
| `serial_port` | Serial port device | /dev/ttyACM0 |

## Rosbag Configuration (`rosbag/`)

ROS2 rosbag recording configuration file, defining topics to record and compression parameters.

**Usage:**

```bash
# Record using configuration file
ros2 bag record -c /path/to/rosbag/ros2_ros2.yaml

# Record with compression
ros2 bag record -c /path/to/rosbag/ros2_ros2.yaml --compression-mode zstd
```

## Launch Scripts

The project provides convenient launch scripts located in the `scripts/` directory:

```bash
# ROS1
./scripts/ros1/run_ros1_all.sh      # Launch all ROS1 nodes
./scripts/ros1/run_ros1_camera.sh   # Launch camera only
./scripts/ros1/run_ros1_imu.sh      # Launch IMU only

# ROS2
./scripts/ros2/run_ros2_all.sh      # Launch all ROS2 nodes
./scripts/ros2/run_ros2_camera.sh   # Launch camera only
./scripts/ros2/run_ros2_imu.sh      # Launch IMU only
./scripts/ros2/run_ros2_lidar.sh    # Launch LiDAR only
./scripts/ros2/run_ros2_rosbag.sh   # Launch rosbag only
```

## Configuration File Priority

When launching a node, parameters are loaded in the following priority (highest to lowest):

1. **Command Line Arguments** - Highest priority
   ```bash
   ros2 launch ... camera_ip:=192.168.0.20
   ```

2. **Launch File Parameters** - `parameters` in launch file
   ```xml
   <param name="camera_ip" value="192.168.0.20"/>
   ```

3. **Configuration File** - YAML file specified by `config:` parameter
   ```yaml
   camera_ip: "192.168.0.11"
   ```

4. **Default Values** - Default values in code - Lowest priority

## Troubleshooting

### Camera Cannot Connect
- Check if IP address is correct
- Confirm network interface and camera are on the same subnet
- Use `ping` to test connectivity
- Check firewall settings

### Calibration File Load Failed
- Confirm path uses `file:///` prefix
- Verify file permissions (readable)
- Check if file format is valid YAML
- Ensure `camera_name` matches the name in calibration file

### Time Synchronization Inaccurate
- Check if PTP service is running: `systemctl status ptp4l-client`
- View sync status: `./scripts/ptp_status.sh`
- Confirm network switch supports PTP
- Check if sensors have PTP enabled (`ptp_enable: true`)

### High Latency or Frame Drops
- Check network bandwidth and latency
- Adjust `gev_packet_size` (use 8192 if jumbo frames supported)
- Increase `processing_queue_depth`
- Disable custom compression (`enable_custom_compression: false`)

## Related Documentation

- [PTP Network Guide](../Doc/PTP_Network_Guide.md)
- [Camera Documentation](../Doc/CameraDocsLink.md)
- [LiDAR Documentation](../Doc/NaviLiDARDocLinks.md)
- [SBG IMU Data Flow Analysis](../temp/SBG_IMU_DATA_FLOW_ANALYSIS.md)

## Contributing

When modifying configuration files, please:

1. Maintain correct YAML format (check with `yamllint`)
2. Update this README documentation
3. Add comments in configuration files to explain parameter usage
4. Test modified configurations

## License

Configuration files follow the project's main license.
