# Battery Voltage Monitoring

## Overview

The `battery_monitor` package provides real-time battery voltage monitoring using the ADS1115 16-bit ADC over I2C. It measures voltage on 4 channels for monitoring two battery banks:

- **Messtechnik** (Measurement Electronics): Channels A0 (+) and A1 (-)
- **Antrieb** (Drive/Propulsion): Channels A2 (+) and A3 (-)

## Message Type: `BatteryVoltage`

### Definition

```rosidl
# BatteryVoltage.msg
# Battery voltage monitoring message from ADS1115 ADC

std_msgs/Header header

# Channel voltages (V) - raw values, current conversion to be added later
float64 channel_a0    # A0: Messtechnik +
float64 channel_a1    # A1: Messtechnik -
float64 channel_a2    # A2: Antrieb +
float64 channel_a3    # A3: Antrieb -
```

### Field Descriptions

| Field | Type | Unit | Description |
|-------|------|------|-------------|
| `header` | `std_msgs/Header` | - | Standard ROS2 header with timestamp and frame_id |
| `channel_a0` | `float64` | V | Messtechnik positive voltage |
| `channel_a1` | `float64` | V | Messtechnik negative voltage |
| `channel_a2` | `float64` | V | Antrieb positive voltage |
| `channel_a3` | `float64` | V | Antrieb negative voltage |

**Note:** Values are raw ADC voltages. External conversion may be required to calculate actual battery voltages based on your voltage divider configuration.

## Hardware: ADS1115 ADC

### Specifications

| Property | Value |
|----------|-------|
| Resolution | 16-bit |
| Sampling Rate | 860 SPS |
| Interface | I2C |
| Default Address | 0x48 |
| Operating Voltage | 2.0V - 5.5V |

### PGA Gain Settings

| Gain | Full-Scale Range | Resolution |
|------|------------------|------------|
| 2/3 | +/-6.144V | 0.1875 mV |
| 1 | +/-4.096V | 0.125 mV |
| 2 | +/-2.048V | 0.0625 mV |
| 4 | +/-1.024V | 0.03125 mV |
| 8 | +/-0.512V | 0.015625 mV |

### Pin Configuration

| ADS1115 Pin | Connected To |
|-------------|--------------|
| A0 | Messtechnik Battery (+) |
| A1 | Messtechnik Battery (-) |
| A2 | Antrieb Battery (+) |
| A3 | Antrieb Battery (-) |
| VDD | 3.3V or 5V |
| GND | GND |
| SDA | I2C SDA (GPIO 2) |
| SCL | I2C SCL (GPIO 3) |

## ROS2 Topic

| Property | Value |
|----------|-------|
| Topic Name | `/battery_voltage` |
| Message Type | `battery_monitor/msg/BatteryVoltage` |
| QoS | 10 (depth) |
| Default Rate | 5 Hz |

## Usage Examples

### Viewing Battery Voltage

```bash
ros2 topic echo /battery_voltage
```

Output example:
```
header:
  stamp:
    sec: 1703123456
    nanosec: 123456789
  frame_id: 'battery_sensor'
channel_a0: 3.456
channel_a1: 0.012
channel_a2: 3.432
channel_a3: 0.008
```

### Running the Node

```bash
# Source the workspace
cd ros2_ws
source install/setup.bash

# Run the node
ros2 run battery_monitor battery_monitor_node

# Or with custom parameters
ros2 run battery_monitor battery_monitor_node --ros-args -p i2c_bus:=1 -p gain:=2
```

### Using Launch File

```bash
ros2 launch battery_monitor battery_monitor.launch.py
```

### Subscribing in Python

```python
import rclpy
from rclpy.node import Node
from battery_monitor.msg import BatteryVoltage

class BatterySubscriber(Node):
    def __init__(self):
        super().__init__('battery_subscriber')
        self.subscription = self.create_subscription(
            BatteryVoltage,
            '/battery_voltage',
            self.battery_callback,
            10)

    def battery_callback(self, msg):
        # Calculate actual battery voltages (adjust for your voltage divider)
        messtechnik = msg.channel_a0 - msg.channel_a1
        antrieb = msg.channel_a2 - msg.channel_a3

        self.get_logger().info(
            f'Messtechnik: {messtechnik:.2f}V, '
            f'Antrieb: {antrieb:.2f}V'
        )

def main():
    rclpy.init()
    node = BatterySubscriber()
    rclpy.spin(node)
    rclpy.shutdown()

if __name__ == '__main__':
    main()
```

### Subscribing in C++

```cpp
#include <rclcpp/rclcpp.hpp>
#include <battery_monitor/msg/battery_voltage.hpp>

class BatterySubscriber : public rclcpp::Node
{
public:
  BatterySubscriber()
  : Node("battery_subscriber")
  {
    subscription_ = this->create_subscription<battery_monitor::msg::BatteryVoltage>(
      "/battery_voltage", 10,
      [this](const battery_monitor::msg::BatteryVoltage::SharedPtr msg) {
        double messtechnik = msg->channel_a0 - msg->channel_a1;
        double antrieb = msg->channel_a2 - msg->channel_a3;

        RCLCPP_INFO(
          this->get_logger(),
          "Messtechnik: %.2fV, Antrieb: %.2fV",
          messtechnik, antrieb);
      });
  }

private:
  rclcpp::Subscription<battery_monitor::msg::BatteryVoltage>::SharedPtr subscription_;
};

int main(int argc, char ** argv)
{
  rclcpp::init(argc, argv);
  rclcpp::spin(std::make_shared<BatterySubscriber>());
  rclcpp::shutdown();
  return 0;
}
```

## Configuration

Parameters can be set via YAML config or command line:

| Parameter | Type | Default | Description |
|-----------|------|---------|-------------|
| `i2c_bus` | int | `1` | I2C bus number (usually 1 on Raspberry Pi) |
| `i2c_addr` | int | `0x48` | ADS1115 I2C address (0x48-0x4B) |
| `gain` | int | `1` | PGA gain setting (see table above) |
| `publish_rate` | float | `5.0` | Publishing frequency in Hz |
| `frame_id` | string | `"battery_sensor"` | Frame ID for message header |

Example configuration (`config/battery_monitor.yaml`):

```yaml
battery_monitor:
  ros__parameters:
    # I2C Configuration
    i2c_bus: 1              # I2C bus number
    i2c_addr: 0x48          # ADS1115 I2C address

    # ADC Configuration
    gain: 1                 # PGA gain: 1 = +/-4.096V

    # Publishing
    publish_rate: 5.0       # Publishing rate in Hz
    frame_id: "battery_sensor"  # Frame ID for message header
```

## Hardware Setup

### I2C Enable on Raspberry Pi

```bash
# Enable I2C
sudo raspi-config

# Or use command line
sudo raspi-config nonint do_i2c 0

# Install I2C tools
sudo apt-get install i2c-tools

# Verify connection
i2cdetect -y 1
```

You should see the ADS1115 at address `0x48`:

```
     0  1  2  3  4  5  6  7  8  9  a  b  c  d  e  f
00:          -- -- -- -- -- -- -- -- -- -- -- -- --
10: -- -- -- -- -- -- -- -- -- -- -- -- -- -- -- --
20: -- -- -- -- -- -- -- -- -- -- -- -- -- -- -- --
30: -- -- -- -- -- -- -- -- -- -- -- -- -- -- -- --
40: -- -- -- -- -- -- -- -- 48 -- -- -- -- -- -- --
50: -- -- -- -- -- -- -- -- -- -- -- -- -- -- -- --
60: -- -- -- -- -- -- -- -- -- -- -- -- -- -- -- --
70: -- -- -- -- -- -- -- -- --
```

### Dependencies

```bash
# Python I2C library
pip3 install smbus2

# Or system package
sudo apt-get install python3-smbus2
```

## Voltage Divider Calculation

If using voltage dividers to measure batteries above the ADC's full-scale range:

```
V_actual = V_measured * (R1 + R2) / R2

Where:
- R1 = Top resistor (between battery+ and ADC input)
- R2 = Bottom resistor (between ADC input and GND)
```

Example: For 12V battery with 33kΩ/10kΩ divider:
```
V_actual = V_measured * (33000 + 10000) / 10000
V_actual = V_measured * 4.3
```

## Troubleshooting

### No I2C Device Found

```bash
# Check I2C is enabled
lsmod | grep i2c

# Scan for devices
sudo i2cdetect -y 1
```

### Permission Denied

Add user to i2c group:
```bash
sudo usermod -aG i2c $USER
# Log out and back in
```

### Incorrect Voltage Readings

1. Verify PGA gain setting matches expected voltage range
2. Check voltage divider values
3. Ensure stable power supply to ADS1115
4. Add filtering capacitors near ADC power pins

## Building

```bash
cd ros2_ws
colcon build --packages-select battery_monitor
source install/setup.bash
```
