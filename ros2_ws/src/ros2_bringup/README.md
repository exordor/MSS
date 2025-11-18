# ros2_bringup

Launch utilities for Navi LiDAR and related ROS 2 nodes.

## Package layout

- `launch/navi_lidar.launch.py` – starts `hesai_ros_driver`.
- `config/qt128.yaml` – default configuration copied from the project-wide config directory.

## Usage

```bash
source ~/EAGRUMO/ros2_ws/install/setup.bash
ros2 launch ros2_bringup navi_lidar.launch.py \
  config:=/home/eagrumo/EAGRUMO/config/navi_lidar/qt128.yaml
```

- Omit the `config` argument to use the packaged default at `share/ros2_bringup/config/qt128.yaml`.
- Provide your own YAML to point at custom correction files, ports, or playback sources.
