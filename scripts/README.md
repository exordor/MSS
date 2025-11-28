# Helper Scripts

This directory contains convenience scripts to streamline common workflows. Each script automatically sources ROS and the workspace before running its command, and they all forward additional CLI arguments to the underlying tools.

Note: ROS 1 helper scripts are located in the `scripts/ros1/` subfolder and ROS 2 helpers are in `scripts/ros2/`.

## Sensor bringup scripts

This project includes convenience wrappers for both ROS 1 and ROS 2 bringups. All scripts source the appropriate ROS setup and the local workspace before running. Use the wrappers from the repository root (`~/EAGRUMO`) so relative paths resolve correctly.

| Script | Description & Usage |
|--------|---------------------|
| `ros1/run_camera.sh` | (ROS1) Launches `ros1_bringup/camera.launch`. Example: `./scripts/ros1/run_camera.sh output:=log`. |
| `ros1/run_imu.sh` | (ROS1) Launches `ros1_bringup/imu.launch` (SBG IMU). Example: `./scripts/ros1/run_imu.sh imu_config_file:=/tmp/custom.yaml`. |
| `ros1/run_lidar.sh` | (ROS1) Launches `ros1_bringup/navi_lidar.launch`. Example: `./scripts/ros1/run_lidar.sh bringup_lidar:=true`. |
| `ros1/run_all_sensors.sh` | (ROS1) Launches `ros1_bringup/all_sensors.launch` with all sensors. Add `record:=true` to enable rosbag recording. Example: `./scripts/ros1/run_all_sensors.sh record:=true`. |
| `ros1/run_all_sensors_record.sh` | (ROS1) Wrapper that forces `record:=true`. Example: `./scripts/ros1/run_all_sensors_record.sh bag_name:=test_run`. |
| `ros1/run_all_sensors_no_record.sh` | (ROS1) Wrapper that forces `record:=false` for quick bringup without bagging. Example: `./scripts/ros1/run_all_sensors_no_record.sh`. |
| `ros2/run_ros2_all.sh` | (ROS2) Launches `ros2_bringup/all.launch.py`. Add `--record-bag` to enable rosbag recording. Topics and default output name come from `config/rosbag/rosbag_ros2.yaml` (default `ros2_bringup_all`). Override with `--bag-output` or `--bag-config`. Example: `./scripts/ros2/run_ros2_all.sh --record-bag`. |
| `ros2/run_ros2_all_record.sh` | (ROS2) Wrapper that always enables rosbag (forwards `--record-bag`). Example: `./scripts/ros2/run_ros2_all_record.sh`. |
| `ros2/run_ros2_all_no_record.sh` | (ROS2) Wrapper that keeps rosbag off (default). Example: `./scripts/ros2/run_ros2_all_no_record.sh`. |
| `ros2/run_ros2_navi_lidar.sh` | (ROS2) Launches `ros2_bringup/navi_lidar.launch.py`; override config via `--config`. Example: `./scripts/ros2/run_ros2_navi_lidar.sh --config config/navi_lidar/qt128.yaml`. |
| `ros2/run_ros2_camera.sh` | (ROS2) Launches `ros2_bringup/camera.launch.py` with configurable YAML. Example: `./scripts/ros2/run_ros2_camera.sh --config config/camera/ros2.yaml`. |
| `ros2/run_ros2_imu.sh` | (ROS2) Launches `ros2_bringup/imu.launch.py`. Example: `./scripts/ros2/run_ros2_imu.sh --config config/imu/sbg_ros2.yaml`. |
| `ros2/run_ros2_thruster.sh` | (ROS2) Launches `ros2_bringup/thruster.launch.py`. Example: `./scripts/ros2/run_ros2_thruster.sh --config config/thruster/thruster.yaml`. |
| `ros2/run_ros2_in_docker_humble.sh` | (ROS2) Convenience wrapper to run the ROS2 bringup inside a Humble-based docker image (project-specific). See script header for usage. |

## Git helpers

| Script | Description |
|--------|-------------|
| `add_submodule.sh` | Adds the vendor repositories as git submodules (used during initial setup). |
| `update_submodules.sh` | Updates all submodules to the latest registered revisions. |

## Tips

- Run scripts from the repo root (`~/EAGRUMO`) so relative paths resolve correctly.
- Each script forwards extra arguments to `roslaunch`, so you can override configs (e.g., `./run_all_sensors.sh bringup_camera:=false`).
- If you modify the workspace location or ROS distro, edit the scripts accordingly.
