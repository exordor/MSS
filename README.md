# MSS

**Clone this repository — Quick (recommended)**

```bash
# HTTPS (recommended)
git clone --recurse-submodules --shallow-submodules --jobs 4 \
	https://gitlab.tu-clausthal.de/geomatics-teaching/mss_lecture.git
cd mss_lecture

# SSH (if you use SSH keys)
git clone --recurse-submodules --shallow-submodules --jobs 4 \
	git@gitlab.tu-clausthal.de:geomatics-teaching/mss_lecture.git
cd mss_lecture

# If you already cloned without submodules
git submodule update --init --recursive
```

Multi-Sensor Floating System (ROS1 + ROS2 Hybrid Architecture)

# Overview

This project provides a ROS 2 focused multi-sensor system targeting Jetson platforms (JetPack 5.1.2, Ubuntu 20.04).

Supported and maintained:

- ROS 2 (foxy / humble)
- Hesai LiDAR (ROS 2)
- SBG IMU (ROS 2)
- Camera driver (ROS 2)
- Arduino thruster (ROS 2)
- SLAM (not test ros2 yet)

Note: ROS 1 (Noetic) support is deprecated and no longer actively maintained in this repository.

## Quick start

- Work from the repository root (`~/EAGRUMO`) so helper scripts resolve relative paths correctly.
- Helper scripts live under `./scripts/ros1/` (ROS1 wrappers) and `./scripts/ros2/` (ROS2 wrappers). Use these to launch bringups quickly:
	- ROS1 example: `./scripts/ros1/run_lidar.sh`
	- ROS2 example (all sensors with recording): `./scripts/ros2/run_ros2_all_record.sh`

## Rosbag output defaults
- **Default behavior:** When recording is enabled via the ROS2 helpers or `--record-bag`, the default bag output is created under the repository `temp/` directory with a timestamped name, e.g. `temp/rosbag2_20251128_173045`.
- **Override:** You can override the output name with `--bag-output NAME` (script) or `bag_output:=NAME` (launch argument), or change topics/output via `config/rosbag/rosbag_ros2.yaml`.

**How to verify a recording**
- **Start a bringup with recording:**

```bash
./scripts/ros2/run_ros2_all_record.sh
# or
./scripts/ros2/run_ros2_all.sh --record-bag
```
- **Check for created bag folders:**

```bash
ls -lh temp/rosbag2_*
# Inspect a bag's metadata
ros2 bag info temp/rosbag2_<TIMESTAMP>
```

**Notes**
- Recording is off by default; enable it with the wrappers above. The launch uses the `ros2 bag` CLI to start recording (robust against differing package layouts).
- If a bag does not appear, capture the launch log output and check that `ros2 bag record` started successfully; errors may indicate missing topics or environment setup issues.

**SLAM status**
- ROS2 SLAM support in this repository is not yet ready. See the project TODO for next steps (evaluation of Fast-LIVO2 / MOLA, dependency list, and example launches).