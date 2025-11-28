#!/usr/bin/env bash
set -euo pipefail

# Wrapper to launch all ROS 2 sensors with rosbag recording enabled.
# Additional arguments are forwarded to run_ros2_all.sh.

SCRIPT_DIR=$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)
FORCE_ARGS=(--record-bag)
"${SCRIPT_DIR}/run_ros2_all.sh" "${FORCE_ARGS[@]}" "$@"
