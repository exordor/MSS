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

### Starting every sensor at once

```bash
# Option 1: helper script
~/EAGRUMO/scripts/run_all_sensors.sh

# Option 2: manual
cd ~/EAGRUMO/ros1_ws
source devel/setup.bash
roslaunch ros1_bringup all_sensors.launch
```

You can disable individual sensors or override their configs via arguments, e.g.:

```bash
roslaunch ros1_bringup all_sensors.launch bringup_lidar:=false camera_config_file:=/tmp/cam.yaml
```

### Recording all topics

`all_sensors.launch` can start a rosbag recorder that captures the topics listed in `config/rosbag/all_sensors.yaml`:

```bash
roslaunch ros1_bringup all_sensors.launch record_rosbag:=true rosbag_name:=test_run
```

Use `rosbag_config_file` to point to a different YAML file. The YAML now also stores default values under the `record` key (`enabled`, `bag_name`, `output_dir`), so you can change the defaults without editing the launch file. Override any of them at runtime with `record_rosbag`, `rosbag_name`, or `rosbag_output`. The YAML must define a `topics` array—edit it to add or remove streams you care about.

Refer to the launch file for the complete list of arguments (camera output mode, respawn policy, etc.).
