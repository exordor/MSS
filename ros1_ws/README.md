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
| `fast_livo` | `src/slam/fast_livo2` | FAST-LIVO2 LiDAR–Inertial–Visual Odometry. Consumes Hesai point clouds, SBG IMU, and (optional) camera topics to provide a fused pose estimate for downstream navigation. |

## FAST-LIVO2 prerequisites

The SLAM package rides on a few dependencies that are not part of `ros-noetic-desktop-full`. Make sure they are in place before building:

- **Git submodules** – Pull the FAST-LIVO2 + VIKIT sources: `git submodule update --init --recursive` (or run `./scripts/update_submodules.sh`).

- **Sophus (non-templated)** – Build commit `a621ff` once and install it system-wide. Before configuring, apply the local patch: swaps the default SO2 constructor assignments to the setter overloads `unit_complex_.real(1.); unit_complex_.imag(0.);`, fixing builds on modern libstdc++. Do this under Project/temp/.


- **PCL toolchain** – Install via apt if you have not already:

	```bash
	sudo apt-get install libpcl-dev ros-noetic-pcl-ros
	```

- **Pinned CMake patch (optional)** – If all target machines use the Ubuntu aarch64 layout, you can bake the hint directly into `src/slam/fast_livo2/CMakeLists.txt`:

	```cmake
	# patch PCL_DIR
	set(PCL_DIR "/usr/lib/aarch64-linux-gnu/cmake/pcl")
	```

	This removes the need for manual exports, but remember to drop or conditionalize the line if you build on x86 hosts where PCL lives elsewhere.

- **Jetson support branch** – The `jetson-support` Git branch tracks the PCL fix *and* the patched Sophus copy so you can `git checkout jetson-support` on embedded targets while keeping `main` pristine for cross-platform development. Keep it rebased on the latest `main`, and cherry-pick only the portable commits back into `main` when upstreaming changes.

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