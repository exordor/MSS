# ros2_bringup

Launch utilities for Navi LiDAR, Daheng Galaxy cameras, thruster control, and related ROS 2 nodes.

## Package layout

- `launch/navi_lidar.launch.py` – starts `hesai_ros_driver`.
- `launch/camera.launch.py` – starts `galaxy_camera` with the packaged camera preset.
- `launch/imu.launch.py` – starts `sbg_driver` with the packaged IMU preset.
- `launch/thruster.launch.py` – starts `thruster_control` with the packaged thruster preset.
- `launch/all.launch.py` – starts LiDAR, camera, IMU, and thruster together with packaged presets.
- `config/qt128.yaml` – default Navi LiDAR configuration copied from the project-wide config directory.
- `config/camera.yaml` – default Daheng MER2 camera configuration copied from `config/camera/ros2.yaml`.
- `config/sbg.yaml` – default SBG IMU configuration copied from `config/imu/sbg_ros2.yaml`.
- `config/thruster.yaml` – default thruster serial configuration.
- `config/rosbag.yaml` – default topics/output for rosbag recording when running everything at once.

## Usage

Source your workspace, then launch with the packaged defaults:

```bash
source ~/EAGRUMO/ros2_ws/install/setup.bash
ros2 launch ros2_bringup navi_lidar.launch.py          # uses share/ros2_bringup/config/qt128.yaml
ros2 launch ros2_bringup camera.launch.py              # uses share/ros2_bringup/config/camera.yaml
ros2 launch ros2_bringup imu.launch.py                 # uses share/ros2_bringup/config/sbg.yaml
ros2 launch ros2_bringup thruster.launch.py            # uses share/ros2_bringup/config/thruster.yaml
ros2 launch ros2_bringup all.launch.py                 # starts all of the above with packaged defaults
```

To use a custom YAML, override the config argument:

- LiDAR: `ros2 launch ros2_bringup navi_lidar.launch.py config:=/path/to/qt128.yaml`
- Camera: `ros2 launch ros2_bringup camera.launch.py config_file:=/path/to/camera.yaml`
- IMU: `ros2 launch ros2_bringup imu.launch.py config_file:=/path/to/sbg.yaml`
- Thruster: `ros2 launch ros2_bringup thruster.launch.py config_file:=/path/to/thruster.yaml`
- All: `ros2 launch ros2_bringup all.launch.py lidar_config:=/path/to/qt128.yaml camera_config:=/path/to/camera.yaml imu_config:=/path/to/sbg.yaml thruster_config:=/path/to/thruster.yaml`

All-in-one recording example (topics from YAML, optional overrides):

```bash
ros2 launch ros2_bringup all.launch.py record_bag:=true bag_config:=/path/to/rosbag.yaml
```

- `bag_config` defaults to `share/ros2_bringup/config/rosbag.yaml` and supplies `topics` and `output`.
- Override with `record_topics` (space-separated) and `bag_output` if you need to change them on the CLI.
