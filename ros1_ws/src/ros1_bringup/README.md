## ROS1 Bringup Package

This package hosts launch files that bring up each hardware component individually as well as a convenience launcher that starts the full sensor stack.

### Available launch files

| Launch file | Description |
|-------------|-------------|
| `camera.launch` | Starts the Daheng Galaxy camera driver and loads `config/camera/auto.yaml`. |
| `imu.launch` | Starts the SBG IMU driver with `config/imu/sbg.yaml`. |
| `navi_lidar.launch` | Starts the Hesai Navi LiDAR driver with `config/navi_lidar/qt128.yaml`. |
| `all_sensors.launch` | Includes the three launch files above with optional enable/disable switches, per-sensor overrides, and an optional rosbag recorder. |

Helper scripts are available under `scripts/`:

| Script | Description |
|--------|-------------|
| `scripts/run_camera.sh` | Sources ROS + workspace environment and launches `camera.launch`. |
| `scripts/run_imu.sh` | Launches `imu.launch`. |
| `scripts/run_lidar.sh` | Launches `navi_lidar.launch`. |
| `scripts/run_all_sensors.sh` | Launches `all_sensors.launch` (defaults configurable via CLI args). |
| `scripts/run_all_sensors_record.sh` | Wraps `run_all_sensors.sh` and forces `record:=true` while still accepting extra CLI overrides. |
| `scripts/run_all_sensors_no_record.sh` | Same as above but forces `record:=false` for quick sensor bringup without rosbagging. |

### Starting every sensor at once

```bash
# Option 1: helper script
~/EAGRUMO/scripts/run_all_sensors.sh

# Option 2: manual
cd ~/EAGRUMO/ros1_ws
source devel/setup.bash
roslaunch ros1_bringup all_sensors.launch
```

`all_sensors.launch` exposes a few convenience arguments:

| Argument | Default | Description |
|----------|---------|-------------|
| `bringup_camera`, `bringup_imu`, `bringup_lidar` | `true` | Quickly toggle each sensor stack. |
| `camera_config_file`, `imu_config_file`, `lidar_config_file` | package defaults | Point to alternate YAML files under `config/`. |
| `camera_launch_file`, `imu_launch_file`, `lidar_launch_file` | package defaults | Swap in a different launch file if needed. |
| `camera_node_name`, `camera_output`, `camera_respawn` | `galaxy_camera`, `screen`, `false` | Handy passthroughs to the Galaxy driver launch file. |
| `record` | `false` | Enables rosbag recording when set to `true`. |
| `bag_dir`, `bag_name` | `~/EAGRUMO/temp`, `all_sensors` | Output location and base bag name. |
| `rosbag_topics` | (pre-filled list) | Whitespace-separated list of topics to record. Override entirely to customize. |
| `rosbag_extra_args` | `--lz4` | Additional flags forwarded to `rosbag record` (e.g., `--split --size=4096`). |

Disable individual sensors or override their configs via arguments, e.g.:

```bash
roslaunch ros1_bringup all_sensors.launch bringup_lidar:=false camera_config_file:=/tmp/cam.yaml
```

### Recording all topics

`all_sensors.launch` no longer depends on an external YAML file for rosbag topics—the default list lives directly inside the launch file so it always ships with the bringup package. Override `rosbag_topics` if you need a different set:

```bash
roslaunch ros1_bringup all_sensors.launch record:=true bag_name:=test_run \
	rosbag_topics:="/navi_lidar/points /sbg/ekf_nav"
```
`rosbag_extra_args` is handy for compression or splitting:

```bash
roslaunch ros1_bringup all_sensors.launch record:=true \
	rosbag_extra_args:="--lz4 --split --duration=600"
```

Refer to the launch file for the complete list of arguments (camera output mode, respawn policy, etc.).
