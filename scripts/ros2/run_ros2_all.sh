#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR=$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)
REPO_ROOT=$(cd -- "${SCRIPT_DIR}/../.." && pwd)
WS_DIR="${REPO_ROOT}/ros2_ws"

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
    -h|--help) usage; exit 0;;
    --) shift; EXTRA_ARGS+=("$@"); break;;
    *) EXTRA_ARGS+=("$1"); shift;;
  esac
done

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

ros2 launch ros2_bringup all.launch.py "${LAUNCH_ARGS[@]}" "${EXTRA_ARGS[@]}"