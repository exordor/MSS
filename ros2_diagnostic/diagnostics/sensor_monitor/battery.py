#!/usr/bin/env python3
"""
Battery Diagnostic
Monitors battery voltage health via ADS1115 ADC (I2C)
"""

import glob
import logging
import os
import re
import shlex
import sys
import time
from datetime import datetime
from typing import Any, Dict

from ..base import BaseDiagnostic, DiagnosticResult, StatusLevel
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
        self.ros2_config = config.get('ROS2_CONFIG', {})

        self.voltage_topic = self.topics.get('voltage', '/battery_voltage')
        self.ros2_domain_id = int(self.ros2_config.get('domain_id', 42))
        self.ros2_source_cmd = self.ros2_config.get('source_cmd', '/opt/ros/humble/setup.bash')
        workspace_root = self.ros2_config.get('workspace')
        self.workspace_setup_cmd = (
            os.path.join(workspace_root, 'install', 'setup.bash') if workspace_root else None
        )
        self._workspace_root = workspace_root
        self._workspace_python_path_extended = False

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
        self._last_read_attempt_time = 0.0
        self._read_min_interval = float(self.thresholds.get('read_min_interval_sec', 2.0))
        self._data_fresh_window = float(self.thresholds.get('data_fresh_window_sec', 5.0))

        # Track previous physical connection state (I2C) for alerts
        self._was_connected = True  # Assume connected on startup

        # I2C probe configuration (independent of ROS2)
        self.i2c_bus = self._parse_i2c_value(self.i2c_config.get('bus', 1), default=1)
        self.i2c_addr = self._parse_i2c_value(self.i2c_config.get('addr', 0x48), default=0x48)
        self.i2c_probe_reg = self._parse_i2c_value(self.i2c_config.get('probe_reg', 0x01), default=0x01)

    @staticmethod
    def _has_valid_voltage_data(voltages: Dict[str, Any]) -> bool:
        """Return True if at least one channel has a numeric value."""
        return any(value is not None for value in voltages.values())

    def _ensure_workspace_python_path(self):
        """Add workspace site-packages to sys.path for custom ROS message imports."""
        if self._workspace_python_path_extended or not self._workspace_root:
            return

        patterns = [
            os.path.join(self._workspace_root, 'install', 'lib', 'python*', 'site-packages'),
            os.path.join(self._workspace_root, 'install', 'lib', 'python*', 'dist-packages'),
            os.path.join(self._workspace_root, 'install', '*', 'lib', 'python*', 'site-packages'),
            os.path.join(self._workspace_root, 'install', '*', 'lib', 'python*', 'dist-packages'),
            os.path.join(self._workspace_root, 'install', '*', 'local', 'lib', 'python*', 'site-packages'),
            os.path.join(self._workspace_root, 'install', '*', 'local', 'lib', 'python*', 'dist-packages'),
        ]
        for pattern in patterns:
            for path in sorted(glob.glob(pattern)):
                if os.path.isdir(path) and path not in sys.path:
                    sys.path.append(path)

        self._workspace_python_path_extended = True

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
        2. Topic not available or no data? → CONNECTED
        3. Topic data available → OK
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

        # 3. Determine overall status (voltage thresholds disabled)
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

            overall_status = StatusLevel.OK
            v_str = ", ".join(
                [f"{k}: {v:.2f}V" for k, v in voltages.items() if v is not None]
            )
            message = f"Battery channels ({v_str})" if v_str else "Battery data received"

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
            helper = get_ros2_helper(self.ros2_domain_id)

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

            has_valid_data = self._has_valid_voltage_data(voltages)

            if has_topic and has_battery_node and has_valid_data:
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
                        'data_available': has_valid_data,
                        'battery_nodes': battery_nodes,
                        'voltages': voltages,
                    },
                    'details': {
                        'message': 'Topic exists but no battery node found'
                        if not has_battery_node else 'Topic exists but no battery data received'
                    }
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
        now = time.time()
        # Keep UI responsive: if cache is fresh, avoid expensive CLI calls.
        if self._last_data_time > 0 and (now - self._last_data_time) < self._data_fresh_window:
            return dict(self._latest_voltages)
        # Throttle repeated read attempts when data is missing/stale.
        if (now - self._last_read_attempt_time) < self._read_min_interval:
            return dict(self._latest_voltages)
        self._last_read_attempt_time = now

        # Preferred path: direct ROS2 subscription to battery topic.
        if RCLPY_AVAILABLE:
            initialized_here = False
            node = None
            try:
                import rclpy
                from rclpy.node import Node
                from threading import Lock

                self._ensure_workspace_python_path()
                try:
                    from battery_monitor.msg import BatteryVoltage
                except ImportError:
                    BatteryVoltage = None

                if BatteryVoltage is not None:
                    topic_name = self.voltage_topic
                    data_received = []
                    lock = Lock()

                    class BatteryReader(Node):
                        def __init__(self, name: str):
                            super().__init__(name)
                            self.subscription = self.create_subscription(
                                BatteryVoltage,
                                topic_name,
                                self.callback,
                                10
                            )

                        def callback(self, msg):
                            with lock:
                                data_received.append({
                                    'channel_a0': round(float(msg.channel_a0), 3),
                                    'channel_a1': round(float(msg.channel_a1), 3),
                                    'channel_a2': round(float(msg.channel_a2), 3),
                                    'channel_a3': round(float(msg.channel_a3), 3),
                                })

                    if not rclpy.ok():
                        rclpy.init()
                        initialized_here = True

                    node = BatteryReader(f"battery_reader_{int(time.time() * 1000)}")
                    start_time = time.time()
                    while time.time() - start_time < 1.2:
                        rclpy.spin_once(node, timeout_sec=0.1)
                        with lock:
                            if data_received:
                                updated = dict(self._latest_voltages)
                                updated.update(data_received[0])
                                self._latest_voltages = updated
                                self._last_data_time = time.time()
                                return dict(self._latest_voltages)
            except Exception as e:
                logger.debug(f"Battery rclpy subscription read error: {e}")
            finally:
                try:
                    if node is not None:
                        node.destroy_node()
                except Exception:
                    pass
                try:
                    if initialized_here and RCLPY_AVAILABLE:
                        import rclpy
                        if rclpy.ok():
                            rclpy.shutdown()
                except Exception:
                    pass

        try:
            import subprocess

            # First try direct CLI with current process env (fast path).
            direct_env = dict(os.environ)
            direct_env['ROS_DOMAIN_ID'] = str(self.ros2_domain_id)
            result = subprocess.run(
                ['ros2', 'topic', 'echo', '--once', self.voltage_topic],
                capture_output=True,
                text=True,
                timeout=1.5,
                env=direct_env,
            )

            # Fallback: source ROS2 + workspace overlay for custom message resolution.
            if result.returncode != 0 or not result.stdout.strip():
                setup_cmds = []
                if self.ros2_source_cmd and os.path.exists(self.ros2_source_cmd):
                    setup_cmds.append(f"source {shlex.quote(self.ros2_source_cmd)}")
                if self.workspace_setup_cmd and os.path.exists(self.workspace_setup_cmd):
                    setup_cmds.append(f"source {shlex.quote(self.workspace_setup_cmd)}")
                setup_cmds.append(f"export ROS_DOMAIN_ID={shlex.quote(str(self.ros2_domain_id))}")
                setup_cmds.append(f"ros2 topic echo --once {shlex.quote(self.voltage_topic)}")
                result = subprocess.run(
                    ['bash', '-lc', ' && '.join(setup_cmds)],
                    capture_output=True,
                    text=True,
                    timeout=3.5,
                )

            if result.returncode == 0 and result.stdout:
                # Parse the output to extract voltage values
                # Format: "channel_a0: 12.34" or similar
                voltages = {}
                for line in result.stdout.split('\n'):
                    line = line.strip()
                    # Match signed float/scientific forms, e.g. -0.123, 1.2e-3.
                    match = re.search(
                        r'(channel_a[0-3]):\s*([-+]?(?:\d+(?:\.\d*)?|\.\d+)(?:[eE][-+]?\d+)?)',
                        line
                    )
                    if match:
                        channel = match.group(1)
                        try:
                            voltage = float(match.group(2))
                            voltages[channel] = round(voltage, 3)
                        except ValueError:
                            pass

                if voltages:
                    updated = dict(self._latest_voltages)
                    updated.update(voltages)
                    self._latest_voltages = updated
                    self._last_data_time = time.time()
                    logger.debug(f"Battery voltages read via shell: {self._latest_voltages}")
                    return dict(self._latest_voltages)

            # Topic echo failed, return cached data
            logger.debug(f"Battery topic echo returned no data, using cache")
            return dict(self._latest_voltages)

        except subprocess.TimeoutExpired:
            logger.debug("Battery topic read timeout")
            return dict(self._latest_voltages)
        except Exception as e:
            logger.debug(f"Battery data read error: {e}")
            return dict(self._latest_voltages)

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
            'value': f"{main_voltage:.2f}V" if main_voltage is not None else "N/A",
            'message': self.last_result.message,
            'voltages': voltages,
        }
