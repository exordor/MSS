#!/usr/bin/env bash
set -euo pipefail

# Persistent ROS 2 Humble Docker Environment
# - Creates container once (docker create)
# - Later runs commands using docker start + docker exec
# - Container never disappears unless manually removed

IMAGE=${IMAGE:-"ascroid/ros2-humble-ubuntu-22.04:pi-vnc-v1"}
CONTAINER_NAME=${CONTAINER_NAME:-"ros2_humble_dev"}

SCRIPT_DIR=$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)
REPO_ROOT=$(cd -- "${SCRIPT_DIR}/../.." && pwd)
WORKDIR_IN_CONTAINER="/workspace"

usage() {
  cat <<USAGE
Usage: $(basename "$0") [--shell] [--build] [--launch \"pkg file.launch.py\"] [--cmd \"COMMAND\"] [--recreate]

Options:
  --shell            Enter interactive shell (default)
  --build            Run colcon build inside ros2_ws
  --launch LAUNCH    Run: ros2 launch <LAUNCH>
  --cmd COMMAND      Execute COMMAND inside container
  --recreate         Destroy and recreate the persistent container
  -h|--help          Show this message

Examples:
  $0 --shell
  $0 --build
  $0 --launch "ros2_bringup navi_lidar.launch.py"
  $0 --cmd "bash -lc 'source /opt/ros/humble/setup.bash && ros2 topic list'"

Container name: '$CONTAINER_NAME'
Workspace mounted at: $WORKDIR_IN_CONTAINER
USAGE
}

MODE="shell"
CMD=""
RECREATE=false

while (($#)); do
  case "$1" in
    --shell)   MODE="shell"; shift;;
    --build)   MODE="build"; shift;;
    --launch)  shift; CMD="$1"; MODE="launch"; shift;;
    --cmd)     shift; CMD="$1"; MODE="cmd"; shift;;
    --recreate) RECREATE=true; shift;;
    -h|--help) usage; exit 0;;
    *) echo "Unknown arg: $1" >&2; usage; exit 1;;
  esac
done

############################################
# STEP 1 — remove container if recreate flag
############################################
if $RECREATE; then
  echo "Recreating container '$CONTAINER_NAME'..."
  docker rm -f "$CONTAINER_NAME" >/dev/null 2>&1 || true
fi

############################################
# STEP 2 — create container if not exists
############################################
if ! docker ps -a --format '{{.Names}}' | grep -q "^${CONTAINER_NAME}$"; then
  echo "[INFO] Creating persistent container: $CONTAINER_NAME"

  docker create -it \
    --name "$CONTAINER_NAME" \
    --network host \
    --runtime nvidia \
    --privileged \
    -v "$REPO_ROOT":"$WORKDIR_IN_CONTAINER" \
    -v /dev:/dev \
    -e DISPLAY \
    -v /tmp/.X11-unix:/tmp/.X11-unix \
    -w "$WORKDIR_IN_CONTAINER" \
    "$IMAGE" \
    bash >/dev/null

  echo "[INFO] Container created. Start it using:"
  echo "       docker start $CONTAINER_NAME"
fi

############################################
# STEP 3 — ensure container is running
############################################
if ! docker ps --format '{{.Names}}' | grep -q "^${CONTAINER_NAME}$"; then
  echo "[INFO] Starting container '$CONTAINER_NAME'..."
  docker start "$CONTAINER_NAME" >/dev/null
fi

############################################
# STEP 4 — build command to exec
############################################
if [[ "$MODE" == "build" ]]; then
  EXEC_CMD="source /opt/ros/humble/setup.bash && cd $WORKDIR_IN_CONTAINER/ros2_ws && colcon build --symlink-install"
elif [[ "$MODE" == "launch" ]]; then
  EXEC_CMD="source /opt/ros/humble/setup.bash && cd $WORKDIR_IN_CONTAINER/ros2_ws && source install/setup.bash || true && ros2 launch $CMD"
elif [[ "$MODE" == "cmd" ]]; then
  EXEC_CMD="$CMD"
else # shell
  EXEC_CMD="source /opt/ros/humble/setup.bash && cd $WORKDIR_IN_CONTAINER && bash"
fi

############################################
# STEP 5 — run exec into container
############################################
if [[ "$MODE" == "cmd" ]]; then
  docker exec -it "$CONTAINER_NAME" bash -lc "$EXEC_CMD"
else
  docker exec -it "$CONTAINER_NAME" bash -lc "$EXEC_CMD"
fi
