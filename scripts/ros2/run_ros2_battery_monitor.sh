#!/bin/bash
#
# run_ros2_battery_monitor.sh
# Launch the battery monitor node
#

# Source ROS2 workspace
source /home/eagrumo/mss_lecture/ros2_ws/install/setup.bash

# Set environment variables for better logging
export PYTHONUNBUFFERED=1
export RCUTILS_CONSOLE_OUTPUT_FORMAT='[{time}] [{severity}] [{name}] {message}'

# Launch the battery monitor node
echo "Starting battery monitor node..."
ros2 launch battery_monitor battery_monitor.launch.py
