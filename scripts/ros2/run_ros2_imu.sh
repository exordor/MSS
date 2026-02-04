#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR=$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)
REPO_ROOT=$(cd -- "${SCRIPT_DIR}/../.." && pwd)
WS_DIR="${REPO_ROOT}/ros2_ws"
DEFAULT_CONFIG="${REPO_ROOT}/config/imu/sbg_ros2.yaml"
source "${SCRIPT_DIR}/lib/logging.sh"

# =============================================================================
# Argument Parsing
# =============================================================================

LOGGING_PROFILE=""
LOGGING_CONFIG=""
SHOW_LOG_CONFIG=false

usage() {
  cat <<'USAGE'
Usage: ./run_ros2_imu.sh [OPTIONS] [extra ros2 launch args]

Options:
  --config PATH         Override the default IMU YAML passed to the launch file.
  --log-profile PROFILE Logging profile: dev, prod, debug, minimal (default: dev).
  --log-config PATH     Custom logging config YAML path.
  --show-log-config     Show active logging configuration and exit.
  --log-level LVL       ROS 2 log level (overrides profile, default: info).
  --no-console          Do not print logs to terminal (log files only).
  -h, --help            Show this message and exit.

Any remaining arguments are forwarded to `ros2 launch`.
USAGE
}

CONFIG_OVERRIDE=""
LOG_LEVEL=""
NO_CONSOLE=false
EXTRA_ARGS=()

while (($#)); do
  case "$1" in
    --config)
      shift
      [[ $# -gt 0 ]] || { echo "--config requires a path" >&2; exit 1; }
      CONFIG_OVERRIDE="$1"
      shift
      ;;
    --log-profile)
      shift
      [[ $# -gt 0 ]] || { echo "--log-profile requires a value" >&2; exit 1; }
      LOGGING_PROFILE="$1"
      shift
      ;;
    --log-config)
      shift
      [[ $# -gt 0 ]] || { echo "--log-config requires a path" >&2; exit 1; }
      LOGGING_CONFIG="$1"
      shift
      ;;
    --show-log-config)
      SHOW_LOG_CONFIG=true
      shift
      ;;
    --log-level)
      shift
      [[ $# -gt 0 ]] || { echo "--log-level requires a value" >&2; exit 1; }
      LOG_LEVEL="$1"
      shift
      ;;
    --no-console)
      NO_CONSOLE=true
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

# =============================================================================
# Log Directory Setup
# =============================================================================

# Export LOGGING_CONFIG for init_ros2_logging to pick up
if [[ -n "$LOGGING_CONFIG" ]]; then
  export LOGGING_CONFIG
fi
init_ros2_logging "${REPO_ROOT}" "${LOGGING_PROFILE}"

# Show configuration and exit if requested
if $SHOW_LOG_CONFIG; then
  show_logging_config
  exit 0
fi

CONFIG_PATH="${CONFIG_OVERRIDE:-${IMU_CONFIG:-${DEFAULT_CONFIG}}}"

if [[ ! -f "$CONFIG_PATH" ]]; then
  echo "Config file not found: $CONFIG_PATH" >&2
  exit 1
fi

write_runtime_info "$0"
if $NO_CONSOLE; then
  exec >> "${APP_LOG_DIR}/00_master.log"
  exec 2>&1
  export RCUTILS_LOGGING_USE_STDOUT=0
else
  exec > >(tee -i "${APP_LOG_DIR}/00_master.log")
  exec 2>&1
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

# =============================================================================
# Cleanup any orphaned sbg_device processes to avoid duplicate node warnings
# =============================================================================
pkill -9 -f "sbg_device" 2>/dev/null || true
sleep 0.5

start_ros2_healthcheck "imu" "sbg_device"

cd "${WS_DIR}"
if [[ ${#EXTRA_ARGS[@]} -gt 0 ]]; then
  printf '%q ' ros2 launch ros2_bringup imu.launch.py "config_file:=${CONFIG_PATH}" ${LOG_LEVEL:+log_level:=${LOG_LEVEL}} "${EXTRA_ARGS[@]}" > "${META_LOG_DIR}/launch_cmd.txt"
  ros2 launch ros2_bringup imu.launch.py "config_file:=${CONFIG_PATH}" ${LOG_LEVEL:+log_level:=${LOG_LEVEL}} "${EXTRA_ARGS[@]}"
else
  printf '%q ' ros2 launch ros2_bringup imu.launch.py "config_file:=${CONFIG_PATH}" ${LOG_LEVEL:+log_level:=${LOG_LEVEL}} > "${META_LOG_DIR}/launch_cmd.txt"
  ros2 launch ros2_bringup imu.launch.py "config_file:=${CONFIG_PATH}" ${LOG_LEVEL:+log_level:=${LOG_LEVEL}}
fi
