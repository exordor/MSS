#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR=$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)
REPO_ROOT=$(cd -- "${SCRIPT_DIR}/../.." && pwd)
WS_DIR="${REPO_ROOT}/ros2_ws"
DEFAULT_CONFIG="${REPO_ROOT}/config/camera/ros2.yaml"

usage() {
  cat <<'USAGE'
Usage: ./run_ros2_camera.sh [--config /path/to/camera.yaml] [extra ros2 launch args]

Options:
  --config PATH   Override the default camera YAML passed to the launch file.
  -h, --help      Show this message and exit.

Any remaining arguments are forwarded to `ros2 launch`.
USAGE
}

CONFIG_OVERRIDE=""
EXTRA_ARGS=()

while (($#)); do
  case "$1" in
    --config)
      shift
      [[ $# -gt 0 ]] || { echo "--config requires a path" >&2; exit 1; }
      CONFIG_OVERRIDE="$1"
      shift
      ;;
    -h|--help)
      usage
      exit 0
      ;;
    *)
      EXTRA_ARGS+=("$1")
      shift
      ;;
  esac
done

CONFIG_PATH="${CONFIG_OVERRIDE:-${CAMERA_CONFIG:-${DEFAULT_CONFIG}}}"

if [[ ! -f "$CONFIG_PATH" ]]; then
  echo "Config file not found: $CONFIG_PATH" >&2
  exit 1
fi

set +u
source /opt/ros/${ROS_DISTRO:-foxy}/setup.bash
if [[ -f "${WS_DIR}/install/setup.bash" ]]; then
  source "${WS_DIR}/install/setup.bash"
else
  echo "ROS 2 workspace not built. Run colcon build in ${WS_DIR}." >&2
  exit 1
fi
set -u

# Change to the directory containing the config file for relative paths
CONFIG_DIR=$(dirname "${CONFIG_PATH}")
cd "${CONFIG_DIR}"

if [[ ${#EXTRA_ARGS[@]} -gt 0 ]]; then
  ros2 launch ros2_bringup camera.launch.py "config_file:=${CONFIG_PATH}" "${EXTRA_ARGS[@]}"
else
  ros2 launch ros2_bringup camera.launch.py "config_file:=${CONFIG_PATH}"
fi
