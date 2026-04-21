#!/usr/bin/env python3
"""
IMU Diagnostic
Monitors SBG IMU health (USB serial connection)
"""

import logging
import os
import subprocess
import time
from datetime import datetime
from typing import Any, Dict

from ..base import BaseDiagnostic, DiagnosticResult, StatusLevel
from ..ros2_helper import get_ros2_helper, RCLPY_AVAILABLE

logger = logging.getLogger(__name__)


class IMUDiagnostic(BaseDiagnostic):
    """Monitor SBG IMU health - simplified"""

    def __init__(self, config: dict):
        super().__init__("imu", config)
        self.topics = config.get('ROS2_TOPICS', {}).get('imu', {})

        self.data_topic = self.topics.get('data', '/imu/data')
        self.status_topic = self.topics.get('status', '/sbg/status')

        # Serial port configuration
        self.serial_port = self._detect_serial_port()

        # One-time data verification flags
        self._data_verified = False      # Data verification result
        self._data_check_done = False    # Whether verification has been completed

        self._ros2_monitor = None

        # Alert tracking to avoid duplicate alerts
        self._last_alert_time = {}  # alert_type -> last_timestamp
        self._alert_cooldown = 60  # seconds between same alert type

        # Track previous connection state for disconnection alerts
        self._was_connected = True  # Assume connected on startup

    def _detect_serial_port(self) -> str:
        """Detect SBG serial port

        First tries configured ports from config.yaml, then falls back
        to hardcoded defaults. This allows easy configuration changes
        when hardware is modified.
        """
        # Default fallback list (used if config not available)
        default_ports = [
            '/dev/serial/by-id/usb-FTDI_FT232R_USB_UART_B001WVHZ-if00-port0',
            '/dev/serial/by-id/usb-FTDI_USB-RS232_Cable_FT3R66K9-if00-port0',
            '/dev/ttyUSB0',
            '/dev/ttyACM0',
        ]
        default_fallback = '/dev/ttyUSB0'

        # Try to get from config
        serial_config = self.config.get('imu_serial', {})
        configured_ports = serial_config.get('ports', [])
        configured_default = serial_config.get('default', default_fallback)

        # Use configured ports if available, otherwise use defaults
        ports_to_try = configured_ports if configured_ports else default_ports
        fallback_port = configured_default

        for port in ports_to_try:
            if os.path.exists(port):
                return port
        return fallback_port  # Default fallback

    def _get_ros2_monitor(self):
        """Lazy load ROS2 monitor for system status check"""
        if self._ros2_monitor is None:
            from ..ros2_monitor import ROS2Monitor
            self._ros2_monitor = ROS2Monitor({
                'ROS2_CONFIG': self.config.get('ROS2_CONFIG', {}),
                'EXPECTED_NODES': self.config.get('EXPECTED_NODES', []),
                'IGNORED_NODES': self.config.get('IGNORED_NODES', []),
                'SENSOR_NODES': self.config.get('SENSOR_NODES', {}),
                'ROS2_TOPICS': self.config.get('ROS2_TOPICS', {}),
                'ENABLE_TOPIC_DETAILS': self.config.get('ENABLE_TOPIC_DETAILS', False),
            })
        return self._ros2_monitor

    def check(self) -> DiagnosticResult:
        """Perform IMU diagnostic check

        Status decision flow:
        1. Physical connection failed? → DISCONNECTED (serial not connected)
        2. System not running? → CONNECTED (hardware ok, ROS2 not running)
        3. Data quality issues? → WARNING / CRITICAL
        4. Connected but no data? → CONNECTED
        5. Everything normal → OK
        """
        metrics = {}
        details = {}

        # 1. Serial connection check (always check, regardless of ROS2 status)
        serial_result = self._check_serial_connection()
        metrics['serial'] = serial_result
        details['serial'] = serial_result

        serial_ok = serial_result.get('connected', False)

        if not serial_ok:
            # Record disconnection alert when transitioning from connected to disconnected
            if self._was_connected:
                current_time = time.time()
                if current_time - self._last_alert_time.get('sensor_disconnected', 0) > self._alert_cooldown:
                    self._record_alert(
                        alert_type='sensor_disconnected',
                        severity='critical',
                        message=f'IMU disconnected - serial port not connected ({self.serial_port})',
                        metric_value=0,
                        threshold=1,
                        metadata={
                            'serial_port': self.serial_port,
                            'reason': 'serial_not_connected'
                        }
                    )
                    self._last_alert_time['sensor_disconnected'] = current_time
                self._was_connected = False

            self.last_check = datetime.now()
            self.check_count += 1
            self.last_result = DiagnosticResult(
                name=self.name,
                status=StatusLevel.DISCONNECTED,
                message=f"IMU - serial port not connected ({self.serial_port})",
                timestamp=self.last_check,
                metrics=metrics,
                details=details
            )
            return self.last_result

        # Update connection state when serial is connected
        if not self._was_connected:
            self._was_connected = True

        # 2. Check if ROS2 system is running
        ros2_monitor = self._get_ros2_monitor()
        ros2_running = ros2_monitor.is_system_running()
        metrics['system_running'] = ros2_running

        if not ros2_running:
            # Serial is connected but ROS2 is not running
            self.last_check = datetime.now()
            self.check_count += 1
            self.last_result = DiagnosticResult(
                name=self.name,
                status=StatusLevel.CONNECTED,
                message=f"IMU - connected, ROS2 not running ({self.serial_port})",
                timestamp=self.last_check,
                metrics=metrics,
                details=details
            )
            return self.last_result

        # 3. ROS2 topic check
        topic_result = self._check_topics()
        metrics['topics'] = topic_result['metrics']
        details['topics'] = topic_result['details']

        topic_ok = topic_result['metrics'].get('data_available', False)

        # 4. One-time data verification (only when topic exists)
        data_verified = True
        if topic_ok and not self._data_check_done:
            data_verified = self._verify_data_once()
            metrics['topics']['data_verified'] = data_verified
        elif self._data_check_done:
            metrics['topics']['data_verified'] = self._data_verified

        # 5. Determine overall status
        if not topic_ok:
            overall_status = StatusLevel.CONNECTED
            message = f"IMU - connected, no data ({self.serial_port})"
        elif not data_verified:
            overall_status = StatusLevel.WARNING
            message = f"IMU - topic exists but no data ({self.serial_port})"
        else:
            overall_status = StatusLevel.OK
            message = f"IMU - OK ({self.serial_port})"

        self.last_check = datetime.now()
        self.check_count += 1

        self.last_result = DiagnosticResult(
            name=self.name,
            status=overall_status,
            message=message,
            timestamp=self.last_check,
            metrics=metrics,
            details=details
        )

        return self.last_result

    def _check_serial_connection(self) -> Dict[str, Any]:
        """Check serial port connection"""
        # Check if serial port exists
        if os.path.exists(self.serial_port):
            # Check if we can read from it (basic check)
            try:
                # Check if device file is readable
                if os.access(self.serial_port, os.R_OK):
                    return {
                        'port': self.serial_port,
                        'connected': True,
                    }
                else:
                    return {
                        'port': self.serial_port,
                        'connected': True,
                        'note': 'Port exists but not readable',
                    }
            except Exception:
                pass

        # Check for any FTDI devices
        try:
            result = subprocess.run(
                ['ls', '/dev/serial/by-id/'],
                capture_output=True,
                text=True,
                timeout=2
            )
            if result.returncode == 0 and 'FTDI' in result.stdout:
                return {
                    'port': self.serial_port,
                    'connected': False,
                    'note': 'FTDI device found but not expected port',
                }
        except Exception:
            pass

        return {
            'port': self.serial_port,
            'connected': False,
            'note': 'Serial port not found',
        }

    def _check_topics(self) -> Dict[str, Any]:
        """Check if IMU topics have publishers using rclpy"""
        if not RCLPY_AVAILABLE:
            return {
                'status': StatusLevel.STOPPED,
                'metrics': {
                    'data_topic': self.data_topic,
                    'data_available': False,
                },
                'details': {'error': 'rclpy not available'}
            }

        # CRITICAL FIX: Check ROS2 system status before querying topics
        # DDS discovery may have cached info even after ROS2 stops
        ros2_monitor = self._get_ros2_monitor()
        if not ros2_monitor.is_system_running():
            return {
                'status': StatusLevel.STOPPED,
                'metrics': {
                    'data_topic': self.data_topic,
                    'data_available': False,
                },
                'details': {'error': 'ROS2 system not running'}
            }

        try:
            helper = get_ros2_helper(42)

            # Get all nodes
            nodes = helper.get_node_names()

            # Find nodes that might publish IMU data
            imu_nodes = [n for n in nodes if any(
                pattern in n.lower() for pattern in ['sbg', 'imu', 'ekf']
            )]

            # Get all topic names
            topics = helper.get_topic_names()
            has_topic = self.data_topic in topics

            # Check if any IMU node exists (likely publishing our topic)
            has_imu_node = len(imu_nodes) > 0

            if has_topic and has_imu_node:
                return {
                    'status': StatusLevel.OK,
                    'metrics': {
                        'data_topic': self.data_topic,
                        'data_available': True,
                        'imu_nodes': imu_nodes,
                    },
                    'details': {
                        'all_topics': [t for t in topics if 'imu' in t.lower() or 'sbg' in t.lower()],
                    }
                }
            elif has_topic:
                return {
                    'status': StatusLevel.WARNING,
                    'metrics': {
                        'data_topic': self.data_topic,
                        'data_available': True,
                        'imu_nodes': [],
                    },
                    'details': {'message': 'Topic exists but no IMU node found'}
                }
            else:
                return {
                    'status': StatusLevel.WARNING,
                    'metrics': {
                        'data_topic': self.data_topic,
                        'data_available': False,
                        'imu_nodes': imu_nodes,
                    },
                    'details': {'message': 'Topic not found'}
                }
        except Exception as e:
            return {
                'status': StatusLevel.STOPPED,
                'metrics': {
                    'data_topic': self.data_topic,
                    'data_available': False,
                },
                'details': {'error': f'Could not check topics: {e}'}
            }

    def _verify_data_once(self) -> bool:
        """One-time verification: check if /imu/data has actual data being published

        Returns:
            bool: Whether data was received
        """
        # If already verified, return cached result
        if self._data_check_done:
            return self._data_verified

        if not RCLPY_AVAILABLE:
            self._data_check_done = True
            return False

        try:
            import rclpy
            from sensor_msgs.msg import Imu
            from rclpy.qos import QoSProfile, ReliabilityPolicy, DurabilityPolicy

            helper = get_ros2_helper(42)

            # Create temporary subscriber to receive data
            received = {'count': 0}
            def msg_callback(msg):
                received['count'] += 1

            qos = QoSProfile(
                reliability=ReliabilityPolicy.BEST_EFFORT,
                durability=DurabilityPolicy.VOLATILE,
                depth=1
            )
            sub = helper._node.create_subscription(
                Imu, self.data_topic, msg_callback, qos
            )

            # Wait for messages (up to 3 seconds)
            import time
            deadline = time.time() + 3.0
            while time.time() < deadline and received['count'] == 0:
                try:
                    rclpy.spin_once(helper._node, timeout_sec=0.1)
                except Exception:
                    break

            # Clean up subscriber
            sub.destroy()

            self._data_verified = received['count'] > 0
            self._data_check_done = True

            if self._data_verified:
                logger.info(f"IMU data verification successful: received {received['count']} messages")
            else:
                logger.warning(f"IMU data verification failed: no data received on {self.data_topic}")

            return self._data_verified

        except Exception as e:
            logger.error(f"IMU data verification error: {e}")
            self._data_check_done = True
            return False

    def _record_alert(self, alert_type: str, severity: str, message: str,
                      metric_value: float, threshold: float, metadata: dict):
        """Record alert to database

        Args:
            alert_type: Alert type
            severity: Severity level (critical, warning)
            message: Alert message
            metric_value: Trigger value
            threshold: Threshold value
            metadata: Additional metadata
        """
        try:
            import json
            from alerts import get_alert_store, Alert

            alert = Alert(
                sensor='imu',
                alert_type=alert_type,
                severity=severity,
                message=message,
                metric_value=metric_value,
                threshold=threshold,
                metadata=json.dumps(metadata),
                created_at=datetime.now().isoformat(),
                status='active'
            )

            alert_id = get_alert_store().add_alert(alert)
            logger.info(f"IMU alert recorded: ID={alert_id}, type={alert_type}, severity={severity}")
        except Exception as e:
            logger.error(f"Failed to record IMU alert: {e}")

    def get_diagnostic_summary(self) -> Dict[str, Any]:
        """Get summary for dashboard display"""
        if self.last_result is None:
            return {
                'name': 'IMU',
                'status': 'stopped',
                'icon': 'fa-solid fa-compass',
                'color': 'gray',
            }

        status_map = {
            StatusLevel.CRITICAL: ('critical', 'red'),
            StatusLevel.DISCONNECTED: ('disconnected', 'red'),
            StatusLevel.WARNING: ('warning', 'orange'),
            StatusLevel.STOPPED: ('stopped', 'gray'),
            StatusLevel.CONNECTED: ('connected', 'blue'),
            StatusLevel.OK: ('ok', 'green'),
        }

        status_str, color = status_map.get(self.last_result.status, ('stopped', 'gray'))
        connected = self.last_result.metrics.get('serial', {}).get('connected', False)

        return {
            'name': 'IMU',
            'status': status_str,
            'icon': 'fa-solid fa-compass',
            'color': color,
            'value': "Connected" if connected else "Disconnected",
            'message': self.last_result.message,
        }
