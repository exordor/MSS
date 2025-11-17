# Helper Scripts

This directory contains convenience scripts to streamline common workflows. Each script automatically sources ROS and the workspace before running its command, and they all forward additional CLI arguments to the underlying tools.

## Sensor bringup scripts

| Script | Description | Example |
|--------|-------------|---------|
| `run_camera.sh` | Launches `ros1_bringup/camera.launch` to start the Galaxy camera node. | `./run_camera.sh output:=log` |
| `run_imu.sh` | Launches `ros1_bringup/imu.launch` (SBG IMU). | `./run_imu.sh imu_config_file:=/tmp/custom.yaml` |
| `run_lidar.sh` | Launches `ros1_bringup/navi_lidar.launch`. | `./run_lidar.sh bringup_lidar:=true` |
| `run_all_sensors.sh` | Launches `ros1_bringup/all_sensors.launch` with all sensors; pass overrides like `record:=true`. | `./run_all_sensors.sh bringup_lidar:=false` |
| `run_all_sensors_record.sh` | Wraps `run_all_sensors.sh` and forces `record:=true` while still forwarding extra args. | `./run_all_sensors_record.sh bag_name:=test_run` |
| `run_all_sensors_no_record.sh` | Wraps `run_all_sensors.sh` and forces `record:=false` for quick bringup without rosbagging. | `./run_all_sensors_no_record.sh` |
| `run_record.sh` | Runs the rosbag recorder only, using `config/rosbag/all_sensors.yaml` for topics and defaults. | `./run_record.sh RECORD_FORCE=true` |

## Git helpers

| Script | Description |
|--------|-------------|
| `add_submodule.sh` | Adds the vendor repositories as git submodules (used during initial setup). |
| `update_submodules.sh` | Updates all submodules to the latest registered revisions. |

## Tips

- Run scripts from the repo root (`~/EAGRUMO`) so relative paths resolve correctly.
- Each script forwards extra arguments to `roslaunch`, so you can override configs (e.g., `./run_all_sensors.sh bringup_camera:=false`).
- If you modify the workspace location or ROS distro, edit the scripts accordingly.
