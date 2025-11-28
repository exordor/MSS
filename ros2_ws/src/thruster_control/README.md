# thruster_control

ROS2 C++ package to control and read status from an Arduino-based thruster controller over serial.

Usage

1. Build the workspace from the repo root (where `ros2_ws` lives):

```bash
cd ros2_ws
colcon build
source install/setup.bash
```

2. Run the node:

```bash
ros2 run thruster_control thruster_node
```

3. Send PWM commands (example sends 1700/1700 in 10Hz):

```bash
ros2 topic pub /thruster_cmd_pwm thruster_control/msg/ThrusterCmdPWM '{left_pwm: 1700, right_pwm: 1700}' -r 10
```

4. Read status as `thruster_control/msg/ThrusterStatusPWM` from `/thruster_status_pwm`:

```bash
ros2 topic echo /thruster_status_pwm
```

Configuration

- Parameters (can be set via `ros2 run` arguments or a launch file):
  - `port` (string): serial device path (default matches the original script)
  - `baud` (int): baud rate (default `115200`)
  - `read_interval` (float): timer interval for polling serial (seconds)
  - `stop_cmd` (string): command sent on shutdown (default `C 1500 1500`)
  - `status_frame_id` (string): frame id stored in the outgoing status header (default `thruster_link`)

Notes

- Ensure your user has permission to access the serial device (e.g., add to the `dialout` group or udev rule).
