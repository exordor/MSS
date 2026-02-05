#!/usr/bin/env python3
# -*- coding: utf-8 -*-

import time

import rclpy
from rclpy.node import Node
from rclpy.qos import QoSProfile
from std_msgs.msg import Header

from battery_monitor.msg import BatteryVoltage

try:
    from smbus2 import SMBus
except ImportError:
    # Fallback to smbus for older systems
    from smbus import SMBus


class ADS1115:
    """Simplified ADS1115 ADC class for single-ended measurements"""

    # Single-ended mode MUX configuration
    MUX_SINGLE = {
        0: 0x4000,  # A0 - GND
        1: 0x5000,  # A1 - GND
        2: 0x6000,  # A2 - GND
        3: 0x7000,  # A3 - GND
    }

    # PGA configuration (gain and full-scale voltage)
    PGA_CONFIG = {
        2/3: (0x0000, 6.144),  # +/-6.144V
        1:   (0x0200, 4.096),  # +/-4.096V
        2:   (0x0400, 2.048),  # +/-2.048V
        4:   (0x0600, 1.024),  # +/-1.024V
        8:   (0x0800, 0.512),  # +/-0.512V
    }

    def __init__(self, bus_num=1, addr=0x48, gain=1):
        """Initialize ADS1115"""
        self.bus = SMBus(bus_num)
        self.addr = addr
        self.gain = gain
        self._pga_config, self.fullscale_voltage = self.PGA_CONFIG[gain]

    def read_single(self, pin):
        """Read single-ended channel (0=A0, 1=A1, 2=A2, 3=A3)"""
        if pin not in self.MUX_SINGLE:
            raise ValueError("Unsupported single-ended pin: {}".format(pin))

        mux = self.MUX_SINGLE[pin]

        # Config: OS_SINGLE | MUX | PGA | MODE_SINGLE | 860SPS | COMP_DISABLED
        config = 0x8000 | mux | self._pga_config | 0x0100 | 0x00E0 | 0x0003

        # Write config
        self.bus.write_i2c_block_data(self.addr, 0x01,
                                      [(config >> 8) & 0xFF, config & 0xFF])
        time.sleep(0.002)  # Wait for conversion (~1.2ms @ 860SPS)

        # Read conversion
        data = self.bus.read_i2c_block_data(self.addr, 0x00, 2)
        raw = (data[0] << 8) | data[1]

        # Signed conversion
        if raw & 0x8000:
            raw -= 0x10000

        return raw * self.fullscale_voltage / 32768.0

    def close(self):
        """Close I2C bus"""
        self.bus.close()


class BatteryMonitorNode(Node):
    """ROS2 node for battery voltage monitoring using ADS1115 ADC

    Channel configuration:
    - A0: Messtechnik +
    - A1: Messtechnik -
    - A2: Antrieb +
    - A3: Antrieb -
    """

    def __init__(self):
        super().__init__('battery_monitor')

        # Declare parameters
        self.declare_parameter('i2c_bus', 1)
        self.declare_parameter('i2c_addr', 0x48)
        self.declare_parameter('gain', 1)
        self.declare_parameter('publish_rate', 5.0)
        self.declare_parameter('frame_id', 'battery_sensor')

        # Get parameters
        i2c_bus = self.get_parameter('i2c_bus').value
        i2c_addr = self.get_parameter('i2c_addr').value
        gain = self.get_parameter('gain').value
        publish_rate = self.get_parameter('publish_rate').value
        self.frame_id = self.get_parameter('frame_id').value

        # Initialize ADS1115
        try:
            self.ads = ADS1115(bus_num=i2c_bus, addr=i2c_addr, gain=gain)
        except Exception as e:
            self.get_logger().error('Failed to initialize ADS1115: {}'.format(e))
            raise

        # Publisher
        qos = QoSProfile(depth=10)
        self.publisher = self.create_publisher(BatteryVoltage, '/battery_voltage', qos)

        # Timer for publishing
        period = 1.0 / publish_rate
        self.timer = self.create_timer(period, self._publish_callback)

        self.get_logger().info('=' * 60)
        self.get_logger().info('Battery Monitor Node (ADS1115)')
        self.get_logger().info('  I2C bus: {}'.format(i2c_bus))
        self.get_logger().info('  I2C addr: 0x{:02X}'.format(i2c_addr))
        self.get_logger().info('  Gain: {}'.format(gain))
        self.get_logger().info('  Publish rate: {} Hz'.format(publish_rate))
        self.get_logger().info('  Publishing to: /battery_voltage')
        self.get_logger().info('=' * 60)

    def _publish_callback(self):
        """Read and publish battery voltage"""
        try:
            # Read all 4 channels
            v_a0 = self.ads.read_single(0)  # A0: Messtechnik +
            v_a1 = self.ads.read_single(1)  # A1: Messtechnik -
            v_a2 = self.ads.read_single(2)  # A2: Antrieb +
            v_a3 = self.ads.read_single(3)  # A3: Antrieb -

            # Create message
            msg = BatteryVoltage()
            msg.header = Header()
            msg.header.stamp = self.get_clock().now().to_msg()
            msg.header.frame_id = self.frame_id

            msg.channel_a0 = v_a0
            msg.channel_a1 = v_a1
            msg.channel_a2 = v_a2
            msg.channel_a3 = v_a3

            self.publisher.publish(msg)

            # Optional: log for debugging
            # self.get_logger().info(
            #     'A0={:.4f}V A1={:.4f}V A2={:.4f}V A3={:.4f}V'.format(v_a0, v_a1, v_a2, v_a3)
            # )

        except Exception as e:
            self.get_logger().error('Error reading ADS1115: {}'.format(e))

    def destroy_node(self):
        """Clean up I2C on shutdown"""
        self.get_logger().info('Shutting down, closing I2C bus...')
        try:
            self.ads.close()
        except:
            pass
        super().destroy_node()


def main(args=None):
    rclpy.init(args=args)
    node = BatteryMonitorNode()

    try:
        rclpy.spin(node)
    except KeyboardInterrupt:
        pass
    finally:
        node.destroy_node()
        rclpy.shutdown()


if __name__ == '__main__':
    main()
