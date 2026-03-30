#!/usr/bin/env python3
"""
PTP Time Publisher Node
Reads PTP-synchronized system time and publishes NMEA ZDA sentences via UART.
"""

import rclpy
from rclpy.node import Node
from rclpy.qos import QoSProfile
from std_msgs.msg import String
import time
import serial
import subprocess
import os
from datetime import datetime, timezone


class ZDAPublisherNode(Node):
    """ROS2 node that reads PTP time and transmits NMEA ZDA sentences via serial."""

    def __init__(self):
        super().__init__('zda_publisher_node')

        # Declare parameters
        self.declare_parameter('serial_port', '/dev/ttyTHS1')
        self.declare_parameter('serial_baudrate', 460800)
        self.declare_parameter('talker_id', 'GP')
        self.declare_parameter('local_zone_hours', 1)
        self.declare_parameter('local_zone_minutes', 0)
        self.declare_parameter('publish_rate', 1.0)
        self.declare_parameter('check_ptp_sync', True)
        self.declare_parameter('max_offset_ms', 10.0)
        self.declare_parameter('ptp_device', '/dev/ptp0')
        self.declare_parameter('publish_when_unsynced', False)
        self.declare_parameter('warning_interval', 10.0)

        # Get parameters
        self.serial_port = self.get_parameter('serial_port').value
        self.serial_baudrate = self.get_parameter('serial_baudrate').value
        self.talker_id = self.get_parameter('talker_id').value
        self.local_zone_hours = self.get_parameter('local_zone_hours').value
        self.local_zone_minutes = self.get_parameter('local_zone_minutes').value
        self.publish_rate = self.get_parameter('publish_rate').value
        self.check_ptp_sync = self.get_parameter('check_ptp_sync').value
        self.max_offset_ms = self.get_parameter('max_offset_ms').value
        self.ptp_device = self.get_parameter('ptp_device').value
        self.publish_when_unsynced = self.get_parameter('publish_when_unsynced').value
        self.warning_interval = self.get_parameter('warning_interval').value

        # State variables
        self.ptp_synced = False
        self.last_warning_time = 0
        self.serial_conn = None
        self.output_initialized = False

        # Initialize serial port
        self._init_serial_port()

        # Create ROS2 publisher for monitoring
        self.zda_publisher = self.create_publisher(
            String,
            '/ptp/zda',
            QoSProfile(depth=10)
        )

        # Create timer for periodic publishing
        timer_period = 1.0 / self.publish_rate
        self.create_timer(timer_period, self.publish_zda_callback)

        self.get_logger().info('ZDA Publisher Node initialized')
        self.get_logger().info(f'  Serial port: {self.serial_port}')
        self.get_logger().info(f'  Baudrate: {self.serial_baudrate}')
        self.get_logger().info(f'  Publish rate: {self.publish_rate} Hz')
        self.get_logger().info(f'  Talker ID: {self.talker_id}ZDA')

    def _init_serial_port(self):
        """Initialize serial port for NMEA output."""
        try:
            self.get_logger().info(f'Opening serial port: {self.serial_port} @ {self.serial_baudrate}')
            self.serial_conn = serial.Serial(
                port=self.serial_port,
                baudrate=self.serial_baudrate,
                bytesize=serial.EIGHTBITS,
                parity=serial.PARITY_NONE,
                stopbits=serial.STOPBITS_ONE,
                timeout=1,
                write_timeout=1
            )

            # Clear any existing data in buffers
            self.serial_conn.reset_input_buffer()
            self.serial_conn.reset_output_buffer()

            self.output_initialized = True
            self.get_logger().info('Serial port opened successfully')

        except serial.SerialException as e:
            self.get_logger().error(f'Failed to open serial port {self.serial_port}: {e}')
            self.get_logger().error('Make sure the port exists and you have permissions (dialout group)')
            self.output_initialized = False
        except Exception as e:
            self.get_logger().error(f'Unexpected error initializing serial port: {e}')
            self.output_initialized = False

    def check_ptp_synchronization(self):
        """
        Check if PTP is synchronized.

        Returns:
            bool: True if PTP is synchronized within acceptable limits
        """
        if not self.check_ptp_sync:
            return True

        try:
            # Method 1: Check if PTP device exists
            if not os.path.exists(self.ptp_device):
                self.get_logger().debug(f'PTP device not found: {self.ptp_device}')
                return False

            # Method 2: Check systemd service status
            result = subprocess.run(
                ['systemctl', 'is-active', 'ptp4l-client.service'],
                capture_output=True,
                text=True,
                timeout=1
            )
            if result.returncode == 0 and result.stdout.strip() == 'active':
                return True

            # Method 3: Check if phc2sys service is active
            result = subprocess.run(
                ['systemctl', 'is-active', 'phc2sys-client.service'],
                capture_output=True,
                text=True,
                timeout=1
            )
            if result.returncode == 0 and result.stdout.strip() == 'active':
                return True

        except subprocess.TimeoutExpired:
            self.get_logger().debug('PTP check timeout')
            return False
        except Exception as e:
            self.get_logger().debug(f'PTP check failed: {e}')
            return False

        return False

    def generate_nmea_zda(self, timestamp):
        """
        Generate NMEA ZDA sentence from timestamp.

        Args:
            timestamp: Unix timestamp (seconds since epoch)

        Returns:
            str: Complete NMEA ZDA sentence with checksum
        """
        # Convert to UTC datetime
        utc_dt = datetime.utcfromtimestamp(timestamp)

        # Format time: hhmmss.ss (with 2 decimal places for hundredths)
        # Get microseconds and convert to hundredths (2 decimal places)
        microseconds = utc_dt.microsecond
        hundredths = int(microseconds / 10000)
        time_str = utc_dt.strftime('%H%M%S.') + f'{hundredths:02d}'

        # Format date: dd,mm,yyyy
        day_str = utc_dt.strftime('%d')
        month_str = utc_dt.strftime('%m')
        year_str = utc_dt.strftime('%Y')

        # Keep the sign on the ZDA local zone hour field.
        zone_hours = self.local_zone_hours
        zone_minutes = self.local_zone_minutes

        # Build sentence without checksum
        sentence_fields = [
            self.talker_id + 'ZDA',
            time_str,
            day_str,
            month_str,
            year_str,
            self._format_zone_hours(zone_hours),
            f'{zone_minutes:02d}'
        ]

        sentence_without_checksum = '$' + ','.join(sentence_fields)

        # Calculate checksum
        checksum = self._calculate_nmea_checksum(sentence_without_checksum)

        # Complete sentence with CRLF
        complete_sentence = f'{sentence_without_checksum}*{checksum}\r\n'

        return complete_sentence

    def _format_zone_hours(self, zone_hours):
        """Format the signed local zone hours field for ZDA."""
        if zone_hours < 0:
            return f'-{abs(zone_hours):02d}'
        return f'{zone_hours:02d}'

    def _calculate_nmea_checksum(self, sentence):
        """
        Calculate XOR checksum for NMEA sentence.

        Args:
            sentence: NMEA sentence including $ but excluding *checksum

        Returns:
            str: Two-character hexadecimal checksum
        """
        checksum = 0
        # Skip the starting '$'
        for char in sentence[1:]:
            checksum ^= ord(char)
        return f'{checksum:02X}'

    def publish_zda_callback(self):
        """Timer callback to publish ZDA sentence."""
        if not self.output_initialized:
            return

        # Check PTP synchronization
        self.ptp_synced = self.check_ptp_synchronization()

        if not self.ptp_synced:
            current_time = time.time()
            if current_time - self.last_warning_time >= self.warning_interval:
                self.get_logger().warn('PTP not synchronized')
                self.last_warning_time = current_time

            if not self.publish_when_unsynced:
                return

        # Get current PTP-synchronized time
        current_time = time.time()  # Reads from CLOCK_REALTIME (synced by PTP)

        # Generate NMEA ZDA sentence
        zda_sentence = self.generate_nmea_zda(current_time)

        # Send to serial port
        try:
            if self.serial_conn and self.serial_conn.is_open:
                self.serial_conn.write(zda_sentence.encode())
                self.serial_conn.flush()

                # Also publish to ROS topic for monitoring
                self.zda_publisher.publish(String(data=zda_sentence))

                self.get_logger().debug(f'Sent: {zda_sentence.strip()}')

        except serial.SerialException as e:
            self.get_logger().error(f'Serial port error: {e}')
            # Try to reinitialize
            self.output_initialized = False
            self._init_serial_port()/ptp/zda
        except Exception as e:
            self.get_logger().error(f'Failed to send ZDA: {e}')

    def destroy_node(self):
        """Clean up resources."""
        if self.serial_conn and self.serial_conn.is_open:
            self.serial_conn.close()
            self.get_logger().info('Serial port closed')
        super().destroy_node()


def main(args=None):
    rclpy.init(args=args)
    node = ZDAPublisherNode()

    try:
        rclpy.spin(node)
    except KeyboardInterrupt:
        pass
    finally:
        node.destroy_node()
        rclpy.shutdown()


if __name__ == '__main__':
    main()
