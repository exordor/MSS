# thruster_control

ROS2 C++ package to control and read status from an Arduino-based thruster controller.

## Nodes

### `thruster_node`
Serial-based communication node.

### `thruster_wifi_node`
WiFi/UDP-based communication node (recommended).

## Usage

1. Build the workspace from the repo root (where `ros2_ws` lives):

```bash
cd ros2_ws
colcon build
source install/setup.bash
```

2. Run the WiFi node:

```bash
ros2 run thruster_control thruster_wifi_node
```

Or with launch file:

```bash
ros2 launch ros2_bringup thruster.launch.py
```

## Topics

### Published

| Topic | Message | Description |
|-------|---------|-------------|
| `/thruster_status_pwm` | `ThrusterStatusPWM` | PWM status of left/right thrusters |
| `/speed_data` | `SpeedData` | Flow sensor data (frequency, flow rate, velocity, total volume) |
| `/temp_humidity` | `TempHumidity` | Temperature & humidity from two sensors |
| `/thruster_connection_status` | `ConnectionStatus` | Connection status metrics |
| `/thruster_metrics` | `ThrusterMetrics` | Performance and statistics |

### Subscribed

| Topic | Message | Description |
|-------|---------|-------------|
| `/thruster_cmd_pwm` | `ThrusterCmdPWM` | PWM commands to send to thrusters |

## Message Types

### `ThrusterStatusPWM`
```bash
ros2 topic echo /thruster_status_pwm
```
```
mode: 0          # 0=RC, 1=ROS
left_pwm: 1500   # 1100-1900, 1500=stop
right_pwm: 1500
```

### `SpeedData`
```
freq_hz: 10.0        # Sensor frequency
flow_lmin: 5.2       # Flow rate (L/min)
velocity_ms: 0.5     # Water velocity (m/s)
total_liters: 123.4  # Total volume
```

### `TempHumidity`
```
temp1: 25.3      # Sensor 1 temperature (°C)
humidity1: 65.0  # Sensor 1 humidity (%)
temp2: 24.8      # Sensor 2 temperature (°C)
humidity2: 68.5  # Sensor 2 humidity (%)
```

### `ThrusterCmdPWM`
Send commands (example sends 1700/1700 at 10Hz):

```bash
ros2 topic pub /thruster_cmd_pwm thruster_control/msg/ThrusterCmdPWM '{left_pwm: 1700, right_pwm: 1700}' -r 10
```

## Arduino Protocol

### Command (→ Arduino)
```
C <left_pwm> <right_pwm>\n
```

### Status Messages (← Arduino)

| Prefix | Format | Description |
|--------|--------|-------------|
| `S` | `S <mode> <left_pwm> <right_pwm>` | Thruster status |
| `F` | `F <freq> <flow> <velocity> <total>` | Flow sensor data |
| `D` | `D <temp1> <hum1> <temp2> <hum2>` | Temperature & humidity (2 sensors) |
| `HEARTBEAT` | `HEARTBEAT` | Heartbeat message |

## Configuration

Parameters for `thruster_wifi_node`:

| Parameter | Type | Default | Description |
|-----------|------|---------|-------------|
| `arduino_host` | string | `192.168.50.100` | Arduino IP address |
| `arduino_cmd_port` | int | `8888` | Command port |
| `arduino_ping_port` | int | `8889` | PING/heartbeat port |
| `data_port` | int | `28888` | Data receive port |
| `heartbeat_port` | int | `28887` | Heartbeat receive port |
| `udp_timeout` | double | `0.1` | UDP timeout (seconds) |
| `read_period` | double | `0.01` | Read period (seconds) |
| `status_frame_id` | string | `thruster_link` | Frame ID for headers |

## Notes

- Ensure your network allows UDP communication with the Arduino
- The node automatically handles reconnection with exponential backoff
- Modify parameters via launch file YAML or ROS2 parameters
