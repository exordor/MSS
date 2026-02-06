#!/usr/bin/env python3
"""
Battery Diagnostic
Monitors battery voltage health via ADS1115 ADC (I2C)
"""

import logging
import time
from datetime import datetime
from typing import Any, Dict

from ..base import BaseDiagnostic, DiagnosticResult, StatusLevel, get_higher_priority_status
from ..ros2_helper import get_ros2_helper, RCLPY_AVAILABLE

logger = logging.getLogger(__name__)


class BatteryDiagnostic(BaseDiagnostic):
    """Monitor battery voltage health via ADS1115 ADC

    Channel configuration:
    - A0: Messtechnik +
    - A1: Messtechnik -
    - A2: Antrieb +
    - A3: Antrieb -
    """

    def __init__(self, config: dict):
        super().__init__("battery", config)
        self.topics = config.get('ROS2_TOPICS', {}).get('battery', {})
        self.thresholds = config.get('SENSOR_THRESHOLDS', {}).get('battery', {})
        self.i2c_config = config.get('SENSOR_I2C', {}).get('battery', {})

        self.voltage_topic = self.topics.get('voltage', '/battery_voltage')

        # Voltage thresholds
        self.min_voltage = self.thresholds.get('min_voltage', 10.0)  # Minimum safe voltage
        self.max_voltage = self.thresholds.get('max_voltage', 14.4)  # Maximum safe voltage
        self.critical_voltage = self.thresholds.get('critical_voltage', 10.5)  # Critical low voltage

        self._ros2_monitor = None
        self._log_parser = None

        # Alert tracking to avoid duplicate alerts
        self._last_alert_time = {}  # alert_type -> last_timestamp
        self._alert_cooldown = 60  # seconds between same alert type

        # Latest voltage data cache
        self._latest_voltages = {
            'channel_a0': None,
            'channel_a1': None,
            'channel_a2': None,
            'channel_a3': None,
        }
        self._last_data_time = 0

        # Track previous physical connection state (I2C) for alerts
        self._was_connected = True  # Assume connected on startup

        # I2C probe configuration (independent of ROS2)
        self.i2c_bus = self._parse_i2c_value(self.i2c_config.get('bus', 1), default=1)
        self.i2c_addr = self._parse_i2c_value(self.i2c_config.get('addr', 0x48), default=0x48)
        self.i2c_probe_reg = self._parse_i2c_value(self.i2c_config.get('probe_reg', 0x01), default=0x01)

    @staticmethod
    def _parse_i2c_value(value: Any, default: int) -> int:
        """Parse I2C config values allowing hex strings like '0x48'."""
        if value is None:
            return default
        if isinstance(value, int):
            return value
        if isinstance(value, str):
            try:
                return int(value, 0)
            except ValueError:
                return default
        try:
            return int(value)
        except (TypeError, ValueError):
            return default

    def _check_i2c_connection(self) -> Dict[str, Any]:
        """Probe ADS1115 I2C connectivity without ROS dependencies."""
        result: Dict[str, Any] = {
            'connected': None,
            'bus': self.i2c_bus,
            'addr': hex(self.i2c_addr),
            'probe_reg': hex(self.i2c_probe_reg),
        }

        SMBus = None
        try:
            from smbus2 import SMBus as _SMBus
            SMBus = _SMBus
        except Exception:
            try:
                from smbus import SMBus as _SMBus
                SMBus = _SMBus
            except Exception:
                SMBus = None

        if SMBus is not None:
            try:
                bus = SMBus(self.i2c_bus)
                try:
                    # Read a register to confirm device presence
                    _ = bus.read_word_data(self.i2c_addr, self.i2c_probe_reg)
                finally:
                    bus.close()
                result['connected'] = True
                return result
            except Exception as e:
                result['connected'] = False
                result['error'] = str(e)
                return result

        # Fallback to i2cget if available
        try:
            import shutil
            import subprocess

            if shutil.which('i2cget'):
                proc = subprocess.run(
                    ['i2cget', '-y', str(self.i2c_bus), hex(self.i2c_addr), hex(self.i2c_probe_reg), 'w'],
                    capture_output=True,
                    text=True,
                    timeout=2
                )
                if proc.returncode == 0:
                    result['connected'] = True
                    result['value'] = proc.stdout.strip()
                else:
                    result['connected'] = False
                    result['error'] = proc.stderr.strip() or proc.stdout.strip()
                return result
        except Exception as e:
            result['connected'] = False
            result['error'] = str(e)
            return result

        result['error'] = 'smbus not available and i2cget not found'
        return result

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
        """Perform battery diagnostic check

        Status decision flow:
        1. System not running? → STOPPED
        2. Topic not available? → WARNING
        3. Voltage below critical? → CRITICAL
        4. Voltage below min? → WARNING
        5. Voltage above max? → WARNING
        6. Everything normal → OK
        """
        metrics = {}
        details = {}

        # 0. I2C physical connectivity check (independent of ROS2)
        i2c_status = self._check_i2c_connection()
        i2c_connected = i2c_status.get('connected')
        metrics['i2c'] = i2c_status
        details['i2c'] = {k: v for k, v in i2c_status.items() if k != 'connected'}

        if i2c_connected is False:
            if self._was_connected:
                current_time = time.time()
                if current_time - self._last_alert_time.get('sensor_disconnected', 0) > self._alert_cooldown:
                    self._record_alert(
                        alert_type='sensor_disconnected',
                        severity='critical',
                        message='Battery I2C disconnected',
                        metric_value=0,
                        threshold=1,
                        metadata={
                            'bus': self.i2c_bus,
                            'addr': hex(self.i2c_addr),
                            'probe_reg': hex(self.i2c_probe_reg),
                        }
                    )
                    self._last_alert_time['sensor_disconnected'] = current_time
            self._was_connected = False
            self.last_check = datetime.now()
            self.check_count += 1
            self.last_result = DiagnosticResult(
                name=self.name,
                status=StatusLevel.DISCONNECTED,
                message=f"Battery I2C disconnected ({i2c_status.get('error', 'probe failed')})",
                timestamp=self.last_check,
                metrics=metrics,
                details=details
            )
            return self.last_result
        if i2c_connected is True and not self._was_connected:
            self._was_connected = True

        # 1. Check if ROS2 system is running
        ros2_monitor = self._get_ros2_monitor()
        ros2_running = ros2_monitor.is_system_running()
        metrics['system_running'] = ros2_running

        if not ros2_running:
            self.last_check = datetime.now()
            self.check_count += 1
            if i2c_connected is True:
                status = StatusLevel.CONNECTED
                message = "Battery connected (I2C), ROS2 not running"
            else:
                status = StatusLevel.STOPPED
                message = "Battery - ROS2 not running (I2C status unknown)"
            self.last_result = DiagnosticResult(
                name=self.name,
                status=status,
                message=message,
                timestamp=self.last_check,
                metrics=metrics,
                details=details
            )
            return self.last_result

        # 2. ROS2 topic check and data reading
        topic_result = self._check_topics_and_read_data()
        metrics['topics'] = topic_result['metrics']
        details['topics'] = topic_result['details']

        topic_ok = topic_result['metrics'].get('data_available', False)
        voltages = topic_result['metrics'].get('voltages', {})

        # 3. Determine overall status based on voltages
        if not topic_ok:
            # If I2C is connected, treat as connected regardless of ROS topic data
            if i2c_connected is True:
                overall_status = StatusLevel.CONNECTED
                message = "Battery connected (I2C) but no ROS data"
            else:
                overall_status = StatusLevel.DISCONNECTED
                message = "Battery - no data available"
        else:
            # Update connection state when data is available
            if i2c_connected is True and not self._was_connected:
                self._was_connected = True

            # Check voltage levels
            overall_status = StatusLevel.OK
            messages = []

            # Check each channel
            for channel, voltage in voltages.items():
                if voltage is None:
                    continue

                if voltage <= self.critical_voltage:
                    overall_status = get_higher_priority_status(overall_status, StatusLevel.CRITICAL)
                    messages.append(f"{channel}: {voltage:.2f}V (CRITICAL)")
                    self._check_and_alert_voltage(channel, voltage, 'critical')
                elif voltage < self.min_voltage:
                    overall_status = get_higher_priority_status(overall_status, StatusLevel.WARNING)
                    messages.append(f"{channel}: {voltage:.2f}V (LOW)")
                    self._check_and_alert_voltage(channel, voltage, 'warning')
                elif voltage > self.max_voltage:
                    overall_status = get_higher_priority_status(overall_status, StatusLevel.WARNING)
                    messages.append(f"{channel}: {voltage:.2f}V (HIGH)")

            if not messages:
                # Show all voltages in OK message
                v_str = ", ".join([f"{k}: {v:.2f}V" for k, v in voltages.items() if v is not None])
                message = f"Battery - OK ({v_str})"
            else:
                message = f"Battery - {', '.join(messages)}"

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

    def _check_topics_and_read_data(self) -> Dict[str, Any]:
        """Check if battery topic exists and read latest data"""
        if not RCLPY_AVAILABLE:
            return {
                'status': StatusLevel.STOPPED,
                'metrics': {
                    'voltage_topic': self.voltage_topic,
                    'data_available': False,
                    'voltages': self._latest_voltages,
                },
                'details': {'error': 'rclpy not available'}
            }

        # Check ROS2 system status before querying topics
        ros2_monitor = self._get_ros2_monitor()
        if not ros2_monitor.is_system_running():
            return {
                'status': StatusLevel.STOPPED,
                'metrics': {
                    'voltage_topic': self.voltage_topic,
                    'data_available': False,
                    'voltages': self._latest_voltages,
                },
                'details': {'error': 'ROS2 system not running'}
            }

        try:
            helper = get_ros2_helper(42)

            # Get all nodes
            nodes = helper.get_node_names()

            # Find battery monitor node
            battery_nodes = [n for n in nodes if any(
                pattern in n.lower() for pattern in ['battery', 'ads1115']
            )]

            # Get all topic names
            topics = helper.get_topic_names()
            has_topic = self.voltage_topic in topics

            # Check if any battery node exists
            has_battery_node = len(battery_nodes) > 0

            # Try to read latest data
            voltages = self._read_battery_data()

            if has_topic and has_battery_node and voltages:
                return {
                    'status': StatusLevel.OK,
                    'metrics': {
                        'voltage_topic': self.voltage_topic,
                        'data_available': True,
                        'battery_nodes': battery_nodes,
                        'voltages': voltages,
                    },
                    'details': {
                        'all_topics': [t for t in topics if 'battery' in t.lower()],
                    }
                }
            elif has_topic:
                return {
                    'status': StatusLevel.WARNING,
                    'metrics': {
                        'voltage_topic': self.voltage_topic,
                        'data_available': True,
                        'battery_nodes': [],
                        'voltages': self._latest_voltages,
                    },
                    'details': {'message': 'Topic exists but no battery node found'}
                }
            else:
                return {
                    'status': StatusLevel.WARNING,
                    'metrics': {
                        'voltage_topic': self.voltage_topic,
                        'data_available': False,
                        'battery_nodes': battery_nodes,
                        'voltages': self._latest_voltages,
                    },
                    'details': {'message': 'Topic not found'}
                }
        except Exception as e:
            return {
                'status': StatusLevel.STOPPED,
                'metrics': {
                    'voltage_topic': self.voltage_topic,
                    'data_available': False,
                    'voltages': self._latest_voltages,
                },
                'details': {'error': f'Could not check topics: {e}'}
            }

    def _read_battery_data(self) -> Dict[str, float]:
        """Read latest battery voltage data from ROS2 topic

        Uses shell command to avoid importing custom message types.
        Returns cached data if topic data unavailable.

        Returns:
            Dict with channel voltages or cached data
        """
        try:
            import subprocess
            import json
            import re

            # Use ros2 topic echo with once flag to get latest message
            # This avoids needing to import custom message types
            env = {
                'ROS_DOMAIN_ID': '42',
                'AMENT_PREFIX_PATH': '/opt/ros/humble',
                'PATH': '/opt/ros/humble/bin:/usr/bin:/bin'
            }

            result = subprocess.run(
                ['ros2', 'topic', 'echo', '--once', self.voltage_topic],
                capture_output=True,
                text=True,
                timeout=3,
                env=env
            )

            if result.returncode == 0 and result.stdout:
                # Parse the output to extract voltage values
                # Format: "channel_a0: 12.34" or similar
                voltages = {}
                for line in result.stdout.split('\n'):
                    line = line.strip()
                    # Match pattern like "channel_a0: 12.34" or "channel_a0: 12.345"
                    match = re.match(r'(channel_a[0-3]):\s*([\d.]+)', line)
                    if match:
                        channel = match.group(1)
                        try:
                            voltage = float(match.group(2))
                            voltages[channel] = round(voltage, 3)
                        except ValueError:
                            pass

                if voltages:
                    self._latest_voltages = voltages
                    self._last_data_time = time.time()
                    logger.debug(f"Battery voltages read via shell: {voltages}")
                    return voltages

            # Topic echo failed, return cached data
            logger.debug(f"Battery topic echo returned no data, using cache")
            return self._latest_voltages

        except subprocess.TimeoutExpired:
            logger.debug("Battery topic read timeout")
            return self._latest_voltages
        except Exception as e:
            logger.debug(f"Battery data read error: {e}")
            return self._latest_voltages

    def _check_and_alert_voltage(self, channel: str, voltage: float, level: str):
        """Check and record voltage alert if needed

        Args:
            channel: Channel name (e.g., 'channel_a0')
            voltage: Current voltage reading
            level: Alert level ('critical' or 'warning')
        """
        current_time = time.time()
        alert_key = f"{level}_voltage_{channel}"

        if current_time - self._last_alert_time.get(alert_key, 0) > self._alert_cooldown:
            threshold = self.critical_voltage if level == 'critical' else self.min_voltage
            severity = 'critical' if level == 'critical' else 'warning'

            self._record_alert(
                alert_type=f"{level}_voltage",
                severity=severity,
                message=f'Battery {channel}: {voltage:.2f}V (threshold: {threshold:.2f}V)',
                metric_value=voltage,
                threshold=threshold,
                metadata={
                    'channel': channel,
                    'voltage': voltage,
                    'all_voltages': self._latest_voltages
                }
            )
            self._last_alert_time[alert_key] = current_time

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
                sensor='battery',
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
            logger.info(f"Battery alert recorded: ID={alert_id}, type={alert_type}, severity={severity}")
        except Exception as e:
            logger.error(f"Failed to record battery alert: {e}")

    def get_diagnostic_summary(self) -> Dict[str, Any]:
        """Get summary for dashboard display"""
        if self.last_result is None:
            return {
                'name': 'Battery',
                'status': 'stopped',
                'icon': 'fa-solid fa-battery-half',
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

        # Get main voltage (A0 - Messtechnik +) for display
        voltages = self.last_result.metrics.get('topics', {}).get('voltages', {})
        main_voltage = voltages.get('channel_a0')

        return {
            'name': 'Battery',
            'status': status_str,
            'icon': 'fa-solid fa-battery-half',
            'color': color,
            'value': f"{main_voltage:.2f}V" if main_voltage else "N/A",
            'message': self.last_result.message,
            'voltages': voltages,
        }
