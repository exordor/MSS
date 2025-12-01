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

## Gazebo Simulation

VRX (Virtual RobotX) simulation environment for testing WAM-V systems with ROS 2 Jazzy + Gazebo Harmonic.

**Quick start:**

```bash
cd gazebo
colcon build --merge-install
source install/setup.bash
```

**Features:**
- WAM-V generation from YAML (components, sensors, thrusters)
- Marine environment (waves, buoyancy, multiple world scenarios)
- RGL LiDAR plugin, auto-recording, gamepad teleop

**See also:** `gazebo/README.md` for detailed usage.

## Development Guidelines

**Branch workflow:**
- Always create a new branch for development work — do not commit directly to `main`
- Use descriptive branch names (e.g., `feature/new-sensor`, `fix/imu-calibration`)

**Working with submodules:**

This repository uses git submodules for package management. When developing code inside a submodule:

1. Navigate to the submodule directory (e.g., `ros2_ws/src/camera/`)
2. Create and checkout a development branch in the submodule repository:
   ```bash
   cd ros2_ws/src/camera
   git checkout -b feature/my-camera-update
   ```
3. Make your changes and commit within the submodule
4. Push the submodule branch to its remote repository
5. Return to the main repository root and commit the submodule reference update:
   ```bash
   cd /path/to/mss_lecture
   git add ros2_ws/src/camera
   git commit -m "Update camera submodule to feature branch"
   ```

**Important:** Each submodule is an independent git repository. Branch changes must be made in both the submodule repository and tracked in the parent repository.

**AI-assisted development:**
- Use AI tools (GitHub Copilot, ChatGPT, Claude, etc.) to accelerate development
- Ask AI for code reviews, debugging help, and implementation suggestions
- Leverage AI for documentation, test generation, and refactoring tasks