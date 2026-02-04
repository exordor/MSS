#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR=$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)
REPO_ROOT=$(cd -- "${SCRIPT_DIR}/../.." && pwd)
WS_DIR="${REPO_ROOT}/ros2_ws"
source "${SCRIPT_DIR}/lib/logging.sh"

# =============================================================================
# Argument Parsing
# =============================================================================

LOGGING_PROFILE=""
LOGGING_CONFIG=""
SHOW_LOG_CONFIG=false

DEFAULT_LIDAR_CONFIG="${REPO_ROOT}/config/navi_lidar/qt128.yaml"
DEFAULT_CAMERA_CONFIG="${REPO_ROOT}/config/camera/ros2.yaml"
DEFAULT_IMU_CONFIG="${REPO_ROOT}/config/imu/sbg_ros2.yaml"
DEFAULT_THRUSTER_CONFIG="${REPO_ROOT}/config/thruster/thruster_wifi.yaml"
DEFAULT_BAG_CONFIG="${REPO_ROOT}/config/rosbag/rosbag_ros2.yaml"
DEFAULT_ZDA_CONFIG="${REPO_ROOT}/config/ptp/zda_publisher.yaml"
DEFAULT_RECORDER_CONFIG="${REPO_ROOT}/config/recorder/recorder_ros2.yaml"
DEFAULT_COMPRESSOR_CONFIG="${REPO_ROOT}/config/compressor/compressor_ros2.yaml"

usage() {
  cat <<'USAGE'
Usage: ./run_ros2_all.sh [OPTIONS] [-- extra ros2 launch args]

Options:
  --lidar-config PATH     Override Navi LiDAR config (default: config/navi_lidar/qt128.yaml)
  --camera-config PATH    Override camera config (default: config/camera/ros2.yaml)
  --imu-config PATH       Override IMU config (default: config/imu/sbg_ros2.yaml)
  --thruster-config PATH  Override thruster config (default: config/thruster/thruster_wifi.yaml)
  --bag-config PATH       Override rosbag topics/output YAML (default: config/rosbag/rosbag_ros2.yaml)
  --zda-config PATH       Override ZDA publisher config (default: config/ptp/zda_publisher.yaml)
  --recorder-config PATH  Override recorder config (default: config/recorder/recorder_ros2.yaml)
  --compressor-config PATH Override compressor config (default: config/compressor/compressor_ros2.yaml)
  --compressor-input TOPIC Input topic for compressor (default: /navi_lidar/points)
  --compressor-output TOPIC Output topic for compressor (default: /points_downsampled)
  --record-bag            Enable rosbag recording (default: disabled)
  --record-topics "LIST"  Space-separated topics to record (overrides bag config topics)
  --bag-output NAME       Bag output name (overrides bag config output, default: temp/rosbag_<timestamp>)
  --log-profile PROFILE   Logging profile: dev, prod, debug, minimal (default: dev)
  --log-config PATH       Custom logging config YAML path (default: config/logging/logging.yaml)
  --show-log-config       Show active logging configuration and exit
  --log-level LEVEL       ROS 2 log level (overrides profile, default: info)
  --no-console            Do not print logs to terminal (log files only)
  -h, --help              Show this message and exit

Any args after `--` are forwarded to `ros2 launch`.
USAGE
}

LIDAR_CONFIG=""
CAMERA_CONFIG=""
IMU_CONFIG=""
THRUSTER_CONFIG=""
BAG_CONFIG=""
ZDA_CONFIG=""
RECORDER_CONFIG=""
COMPRESSOR_CONFIG=""
COMPRESSOR_INPUT=""
COMPRESSOR_OUTPUT=""
RECORD_BAG=false
RECORD_TOPICS=""
BAG_OUTPUT=""
LOG_LEVEL=""
NO_CONSOLE=false
EXTRA_ARGS=()

while (($#)); do
  case "$1" in
    --lidar-config) shift; LIDAR_CONFIG="$1"; shift;;
    --camera-config) shift; CAMERA_CONFIG="$1"; shift;;
    --imu-config) shift; IMU_CONFIG="$1"; shift;;
    --thruster-config) shift; THRUSTER_CONFIG="$1"; shift;;
    --bag-config) shift; BAG_CONFIG="$1"; shift;;
    --zda-config) shift; ZDA_CONFIG="$1"; shift;;
    --recorder-config) shift; RECORDER_CONFIG="$1"; shift;;
    --compressor-config) shift; COMPRESSOR_CONFIG="$1"; shift;;
    --compressor-input) shift; COMPRESSOR_INPUT="$1"; shift;;
    --compressor-output) shift; COMPRESSOR_OUTPUT="$1"; shift;;
    --record-bag) RECORD_BAG=true; shift;;
    --record-topics) shift; RECORD_TOPICS="$1"; shift;;
    --bag-output) shift; BAG_OUTPUT="$1"; shift;;
    --log-profile) shift; LOGGING_PROFILE="$1"; shift;;
    --log-config) shift; LOGGING_CONFIG="$1"; shift;;
    --show-log-config) SHOW_LOG_CONFIG=true; shift;;
    --log-level) shift; LOG_LEVEL="$1"; shift;;
    --no-console) NO_CONSOLE=true; shift;;
    -h|--help) usage; exit 0;;
    --) shift; EXTRA_ARGS+=("$@"); break;;
    *) EXTRA_ARGS+=("$1"); shift;;
  esac
done

# =============================================================================
# Log Directory Setup - Create a separate timestamped directory for each run
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

# Save runtime metadata to JSON file
write_runtime_info "$0"

# Main log redirection - Output to both console and log file
if $NO_CONSOLE; then
  exec >> "${APP_LOG_DIR}/00_master.log"
  exec 2>&1
  export RCUTILS_LOGGING_USE_STDOUT=0
else
  exec > >(tee -i "${APP_LOG_DIR}/00_master.log")
  exec 2>&1
fi

echo "=========================================="
echo "ROS2 System Startup"
echo "Log root: ${LOG_ROOT}"
echo "Run ID: ${RUN_ID}"
echo "=========================================="

LIDAR_CONFIG="${LIDAR_CONFIG:-${DEFAULT_LIDAR_CONFIG}}"
CAMERA_CONFIG="${CAMERA_CONFIG:-${DEFAULT_CAMERA_CONFIG}}"
IMU_CONFIG="${IMU_CONFIG:-${DEFAULT_IMU_CONFIG}}"
THRUSTER_CONFIG="${THRUSTER_CONFIG:-${DEFAULT_THRUSTER_CONFIG}}"
BAG_CONFIG="${BAG_CONFIG:-${DEFAULT_BAG_CONFIG}}"
ZDA_CONFIG="${ZDA_CONFIG:-${DEFAULT_ZDA_CONFIG}}"
RECORDER_CONFIG="${RECORDER_CONFIG:-${DEFAULT_RECORDER_CONFIG}}"
COMPRESSOR_CONFIG="${COMPRESSOR_CONFIG:-${DEFAULT_COMPRESSOR_CONFIG}}"
COMPRESSOR_INPUT="${COMPRESSOR_INPUT:-/navi_lidar/points}"
COMPRESSOR_OUTPUT="${COMPRESSOR_OUTPUT:-/points_downsampled}"

for cfg in "$LIDAR_CONFIG" "$CAMERA_CONFIG" "$IMU_CONFIG" "$THRUSTER_CONFIG" "$RECORDER_CONFIG" "$COMPRESSOR_CONFIG"; do
  if [[ ! -f "$cfg" ]]; then
    echo "Config file not found: $cfg" >&2
    exit 1
  fi
done

if $RECORD_BAG && [[ -z "$RECORD_TOPICS" ]] && [[ ! -f "$BAG_CONFIG" ]]; then
  echo "Bag config not found and no topics override provided: $BAG_CONFIG" >&2
  exit 1
fi

if $RECORD_BAG && [[ -z "$BAG_OUTPUT" ]]; then
  mkdir -p "${REPO_ROOT}/temp"
  BAG_OUTPUT="${REPO_ROOT}/temp/rosbag2_$(date +%Y%m%d_%H%M%S)"
fi

set +u
source /opt/ros/${ROS_DISTRO:-humble}/setup.bash
if [[ -f "${WS_DIR}/install/setup.bash" ]]; then
  source "${WS_DIR}/install/setup.bash"
else
  echo "ROS 2 workspace not built. Run colcon build in ${WS_DIR}." >&2
  exit 1
fi
set -u

# =============================================================================
# Cleanup any orphaned ROS 2 node processes to avoid duplicate node warnings
# =============================================================================
for node in "sbg_device" "galaxy_camera" "hesai_ros_driver_node" "thruster_wifi_node" "recorder_node"; do
  pkill -9 -f "$node" 2>/dev/null || true
done
sleep 0.5

start_ros2_healthcheck "all" \
  "navi_lidar_driver" \
  "galaxy_camera" \
  "sbg_device" \
  "thruster_wifi_node" \
  "recorder_node" \
  "sensor_downsample_node"

# =============================================================================
# Start background log extractors for each sensor node
# These create separate log files from 00_master.log for easier debugging
# =============================================================================
EXTRACTOR_PIDS=()

# Navi LiDAR (actual node name: hesai_ros_driver_node)
start_node_log_extractor "navi_lidar_driver"
EXTRACTOR_PIDS+=($!)

# Galaxy Camera
start_node_log_extractor "galaxy_camera"
EXTRACTOR_PIDS+=($!)

# IMU (sbg_device)
start_node_log_extractor "sbg_device"
EXTRACTOR_PIDS+=($!)

# Thruster
start_node_log_extractor "thruster_wifi_node"
EXTRACTOR_PIDS+=($!)

# Sensor compressor/downsample
start_node_log_extractor "sensor_downsample_node"
EXTRACTOR_PIDS+=($!)

# Recorder
start_node_log_extractor "recorder_node"
EXTRACTOR_PIDS+=($!)

# ZDA publisher
start_node_log_extractor "zda_publisher"
EXTRACTOR_PIDS+=($!)

echo "Started ${#EXTRACTOR_PIDS[@]} log extractors, output: ${APP_LOG_DIR}/<node_name>.log"

# Cleanup function to kill extractors on exit
cleanup_extractors() {
  for pid in "${EXTRACTOR_PIDS[@]:-}"; do
    kill "$pid" 2>/dev/null || true
  done
}
trap cleanup_extractors EXIT

LAUNCH_ARGS=(
  "lidar_config:=${LIDAR_CONFIG}"
  "camera_config:=${CAMERA_CONFIG}"
  "imu_config:=${IMU_CONFIG}"
  "thruster_config:=${THRUSTER_CONFIG}"
  "bag_config:=${BAG_CONFIG}"
  "zda_config:=${ZDA_CONFIG}"
  "recorder_config:=${RECORDER_CONFIG}"
  "compressor_config:=${COMPRESSOR_CONFIG}"
  "compressor_input:=${COMPRESSOR_INPUT}"
  "compressor_output:=${COMPRESSOR_OUTPUT}"
  "record_bag:=${RECORD_BAG}"
)

if [[ -n "$LOG_LEVEL" ]]; then
  LAUNCH_ARGS+=("log_level:=${LOG_LEVEL}")
fi

if [[ -n "$RECORD_TOPICS" ]]; then
  LAUNCH_ARGS+=("record_topics:=${RECORD_TOPICS}")
fi

if [[ -n "$BAG_OUTPUT" ]]; then
  LAUNCH_ARGS+=("bag_output:=${BAG_OUTPUT}")
fi

# For relative paths in config files (e.g., camera_info_url), ensure we're in the correct directory
# Use camera config's directory as working directory since it contains the calibration file
CAMERA_CONFIG_DIR=$(dirname "${CAMERA_CONFIG}")
cd "${CAMERA_CONFIG_DIR}"

printf '%q ' ros2 launch ros2_bringup all.launch.py "${LAUNCH_ARGS[@]}" "${EXTRA_ARGS[@]}" > "${META_LOG_DIR}/launch_cmd.txt"

ros2 launch ros2_bringup all.launch.py "${LAUNCH_ARGS[@]}" "${EXTRA_ARGS[@]}"
