#!/bin/bash
# Wrapper script to start FastAPI with ROS2 environment
# This ensures tuc_interfaces and ROS2 services are available

SCRIPT_DIR=$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)
REPO_ROOT=$(cd -- "${SCRIPT_DIR}/.." && pwd)
ROS_WS="${REPO_ROOT}/ros2_ws"

# Store system Python path before sourcing ROS2 environment
SYSTEM_PYTHON=/usr/bin/python3

# Source ROS2 environment
source /opt/ros/humble/setup.bash
if [[ -f "${ROS_WS}/install/setup.bash" ]]; then
  source "${ROS_WS}/install/setup.bash"
fi

# Set ROS domain ID
export ROS_DOMAIN_ID="${ROS_DOMAIN_ID:-42}"

# Start FastAPI app using system Python (which has fastapi installed)
cd "${SCRIPT_DIR}"
# Disable reload mode - it causes environment variable issues
exec "$SYSTEM_PYTHON" -m uvicorn main:app --host 0.0.0.0 --port 5000 --log-level info
