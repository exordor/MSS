# Speed Data Support

## Overview

The `thruster_control` package supports receiving speed/flow data from an Arduino-based thruster controller with integrated flow sensor. This feature allows real-time monitoring of water flow velocity and related metrics.

## Message Type: `SpeedData`

### Definition

```rosidl
# SpeedData.msg
std_msgs/Header header

# Sensor frequency in Hz
float64 freq_hz

# Flow rate in L/min (for calibration)
float64 flow_lmin

# Water velocity in m/s (primary measurement)
float64 velocity_ms

# Total volume in liters
float64 total_liters
```

### Field Descriptions

| Field | Type | Unit | Description |
|-------|------|------|-------------|
| `header` | `std_msgs/Header` | - | Standard ROS2 header with timestamp and frame_id |
| `freq_hz` | `float64` | Hz | Sensor sampling frequency |
| `flow_lmin` | `float64` | L/min | Flow rate for calibration purposes |
| `velocity_ms` | `float64` | m/s | Water velocity (primary measurement) |
| `total_liters` | `float64` | L | Cumulative volume counter |

## Protocol

The Arduino sends speed data in the following text format over UDP:

```
F <freq_hz> <flow_lmin> <velocity_ms> <total_liters>
```

Example:
```
F 10.0 15.5 1.25 1234.5
```

This represents:
- 10 Hz sampling frequency
- 15.5 L/min flow rate
- 1.25 m/s water velocity
- 1234.5 total liters accumulated

## ROS2 Topic

| Property | Value |
|----------|-------|
| Topic Name | `/speed_data` |
| Message Type | `thruster_control/msg/SpeedData` |
| QoS | 10 (depth) |

## Usage Examples

### Viewing Speed Data

```bash
ros2 topic echo /speed_data
```

Output example:
```
header:
  stamp:
    sec: 1703123456
    nanosec: 123456789
  frame_id: 'thruster_link'
freq_hz: 10.0
flow_lmin: 15.5
velocity_ms: 1.25
total_liters: 1234.5
```

### Subscribing in Python

```python
import rclpy
from rclpy.node import Node
from thruster_control.msg import SpeedData

class SpeedSubscriber(Node):
    def __init__(self):
        super().__init__('speed_subscriber')
        self.subscription = self.create_subscription(
            SpeedData,
            '/speed_data',
            self.speed_callback,
            10)
        self.subscription

    def speed_callback(self, msg):
        self.get_logger().info(
            f'Velocity: {msg.velocity_ms:.2f} m/s, '
            f'Flow: {msg.flow_lmin:.2f} L/min, '
            f'Total: {msg.total_liters:.1f} L'
        )

def main():
    rclpy.init()
    node = SpeedSubscriber()
    rclpy.spin(node)
    rclpy.shutdown()

if __name__ == '__main__':
    main()
```

### Subscribing in C++

```cpp
#include <rclcpp/rclcpp.hpp>
#include <thruster_control/msg/speed_data.hpp>

class SpeedSubscriber : public rclcpp::Node
{
public:
  SpeedSubscriber()
  : Node("speed_subscriber")
  {
    subscription_ = this->create_subscription<thruster_control::msg::SpeedData>(
      "/speed_data", 10,
      [this](const thruster_control::msg::SpeedData::SharedPtr msg) {
        RCLCPP_INFO(
          this->get_logger(),
          "Velocity: %.2f m/s, Flow: %.2f L/min, Total: %.1f L",
          msg->velocity_ms, msg->flow_lmin, msg->total_liters);
      });
  }

private:
  rclcpp::Subscription<thruster_control::msg::SpeedData>::SharedPtr subscription_;
};

int main(int argc, char ** argv)
{
  rclcpp::init(argc, argv);
  rclcpp::spin(std::make_shared<SpeedSubscriber>());
  rclcpp::shutdown();
  return 0;
}
```

## Configuration

Speed data reception is configured via the `thruster_wifi_node` parameters:

| Parameter | Type | Default | Description |
|-----------|------|---------|-------------|
| `enable_speed_log` | bool | `false` | Enable debug logging for speed messages |

Example configuration (`config/thruster/thruster_wifi.yaml`):

```yaml
thruster_wifi_node:
  ros__parameters:
    enable_speed_log: true   # Enable to debug flow data reception
```

## Network Architecture

The speed data is received through the dual-port UDP architecture:

1. **Data Port** (default: 28888) - Receives both status (`S`) and flow (`F`) messages
2. **Heartbeat Port** (default: 28887) - Receives heartbeat messages

The Arduino sends `F` messages to the data port, which are then parsed and published to `/speed_data`.

## Related Messages

The package also provides related diagnostic messages:

- **`ConnectionStatus`** (`/thruster_connection_status`) - WiFi and Arduino connection state
- **`ThrusterMetrics`** (`/thruster_metrics`) - Including `rx_speed` count for received speed messages

## Metrics Tracking

The `ThrusterMetrics` message tracks speed data reception:

```rosidl
uint32 rx_speed  # Speed data messages received
```

This counter is incremented for each successfully parsed `F` message and can be used to monitor data flow and sensor health.

## Error Handling

If a speed message cannot be parsed:
- The `parse_errors` counter in `ThrusterMetrics` is incremented
- A debug log message is generated (if `enable_speed_log` is true)
- The invalid message is discarded

Valid messages must contain at least 4 numeric values after the `F` prefix.
