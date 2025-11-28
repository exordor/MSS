#!/usr/bin/env bash
set -euo pipefail
SCRIPT_DIR=$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)
REPO_ROOT=$(cd -- "${SCRIPT_DIR}/../.." && pwd)
WS_DIR="${REPO_ROOT}/ros1_ws"

set +u
source /opt/ros/${ROS_DISTRO:-noetic}/setup.bash
if [ -f "${WS_DIR}/devel/setup.bash" ]; then
  source "${WS_DIR}/devel/setup.bash"
fi
set -u

cd "${WS_DIR}"
roslaunch ros1_bringup imu.launch "$@"
