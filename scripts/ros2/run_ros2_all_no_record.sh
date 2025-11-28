#!/usr/bin/env bash
set -euo pipefail

# Wrapper to launch all ROS 2 sensors without rosbag recording.
# Additional arguments are forwarded to run_ros2_all.sh.

SCRIPT_DIR=$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)
"${SCRIPT_DIR}/run_ros2_all.sh" "$@"
