# ROS1 Workspace Overview

This workspace bundles all ROS 1 drivers and launch files required to bring up
EAGRUMO's navigation sensor stack.  The tree lives under `ros1_ws/` and follows
the standard catkin layout (`src`, `build`, `devel`, `install`).

## Packages

| Package | Location | Purpose |
| --- | --- | --- |
| `ros1_bringup` | `src/ros1_bringup` | Launch files, parameter presets, and convenience scripts that start the full navigation sensor suite (LiDAR + IMU). The default entry point is `roslaunch ros1_bringup navi_lidar.launch`. |
| `hesai_ros_driver` | `src/navi_lidar` | Catkin-wrapped Hesai LiDAR driver (HesaiLidar SDK 2.0). Publishes point clouds, UDP diagnostics, and PTP timing from Hesai QT/XT series sensors. Builds both the SDK libraries and the ROS node used by `ros1_bringup`. |
| `sbg_driver` | `src/imu` | Vendor driver for SBG Systems IMUs. Provides message definitions, device configuration helpers, and runnable binaries (`sbg_device`, `sbg_device_mag`) for streaming IMU/NAV data into ROS topics. |

## Build Instructions

1. **Install ROS Noetic** and the dependencies listed in each package's
	`package.xml` (Boost, yaml-cpp, tf2, etc.). On Ubuntu 20.04 this usually
	means installing `ros-noetic-desktop-full` plus `libyaml-cpp-dev`.
2. **Source the ROS setup file** so `catkin_make` can locate catkin:

	```bash
	source /opt/ros/noetic/setup.bash
	```

3. **Build the workspace** from the `ros1_ws` root:

	```bash
	cd /home/eagrumo/EAGRUMO/ros1_ws
	catkin_make
	```

	- To keep symlinks instead of copying install artifacts, pass
	  `catkin_make --cmake-args -DCATKIN_SYMLINK_INSTALL=ON`.

4. **Source the workspace overlay** before running launch files:

	```bash
	source /home/eagrumo/EAGRUMO/ros1_ws/devel/setup.bash
	```

5. **Launch the stack** (example):

	```bash
	roslaunch ros1_bringup navi_lidar.launch
	```

After building, you can inspect topics such as `/navi_lidar/ptp` or
`/sbg/imu_data` using `rostopic list` / `rostopic echo` to verify sensor data.