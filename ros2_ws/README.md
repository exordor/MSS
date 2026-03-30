# ROS 2 Workspace

Quick steps to build and launch each sensor bringup.

## Build

```bash
cd ~/EAGRUMO/ros2_ws
source /opt/ros/foxy/setup.bash          # or your ROS 2 distro
colcon build --symlink-install
# or --merge-install
source install/setup.bash
```

## Launch (defaults to packaged configs)

- LiDAR: `ros2 launch ros2_bringup navi_lidar.launch.py`
- Camera: `ros2 launch ros2_bringup camera.launch.py`
- IMU: `ros2 launch ros2_bringup imu.launch.py`
- PTP ZDA: `ros2 launch ros2_bringup ptp.launch.py`
- Thruster: `ros2 launch ros2_bringup thruster.launch.py`
- All sensors: `ros2 launch ros2_bringup all.launch.py`

Override configs with launch arguments, e.g.:

```bash
ros2 launch ros2_bringup camera.launch.py config_file:=/path/to/camera.yaml
ros2 launch ros2_bringup all.launch.py \
  lidar_config:=/path/to/qt128.yaml camera_config:=/path/to/camera.yaml \
  imu_config:=/path/to/sbg.yaml zda_config:=/path/to/zda_publisher.yaml \
  thruster_config:=/path/to/thruster.yaml \
  record_bag:=true bag_config:=/path/to/rosbag.yaml
```

## Helper scripts (from repo root)

- `./scripts/ros2/run_ros2_navi_lidar.sh --config config/navi_lidar/qt128.yaml`
- `./scripts/ros2/run_ros2_camera.sh --config config/camera/ros2.yaml`
- `./scripts/ros2/run_ros2_imu.sh --config config/imu/sbg_ros2.yaml`
- `./scripts/ros2/run_ros2_thruster.sh --config config/thruster/thruster.yaml`
- `./scripts/ros2/run_ros2_all.sh --record-bag --bag-config config/rosbag/rosbag_ros2.yaml`

Notes about rosbag recording
- By default, when recording is enabled (`--record-bag` or via `run_ros2_all_record.sh`), the scripts will create a timestamped folder under the repository `temp/` directory and use that as the bag output name, e.g. `temp/rosbag2_20251128_173045`.
- To override the bag output name, pass `--bag-output NAME` to `run_ros2_all.sh` or `bag_output:=<name>` to the launch file.
- The default topics and output name are taken from `config/rosbag/rosbag_ros2.yaml` when no overrides are provided.

Examples
- Start full bringup and write a timestamped bag (default location):
```bash
./scripts/ros2/run_ros2_all_record.sh
```
- Start full bringup and specify a bag name:
```bash
./scripts/ros2/run_ros2_all.sh --record-bag --bag-output my_test_run
```
