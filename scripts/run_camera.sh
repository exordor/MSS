#!/usr/bin/env bash
set -euo pipefail
SCRIPT_DIR=$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)
WS_DIR="${SCRIPT_DIR}/../ros1_ws"
source /opt/ros/${ROS_DISTRO:-noetic}/setup.bash
if [ -f "${WS_DIR}/devel/setup.bash" ]; then
  source "${WS_DIR}/devel/setup.bash"
fi
cd "${WS_DIR}"
roslaunch ros1_bringup camera.launch "$@"
