#!/usr/bin/env python3
"""
Thruster Diagnostic
Monitors Thruster WiFi connection health using UDP heartbeat detection
"""

import logging
import select
import socket
import subprocess
import threading
import time
from datetime import datetime
from typing import Any, Dict, Optional, List

from ..base import BaseDiagnostic, DiagnosticResult, StatusLevel
from ..utils import ping_host
from ..ros2_helper import get_ros2_helper, RCLPY_AVAILABLE

logger = logging.getLogger(__name__)


class ThrusterDiagnostic(BaseDiagnostic):
    """Monitor Thruster WiFi connection health - UDP heartbeat detection

    Mirrors the architecture used in thruster_wifi_node.cpp:
    - Binds to local UDP port 28889 to receive heartbeat/data
    - Detects any UDP data from thruster (HEARTBEAT, S status, F flow, D temp/humidity)
    - Uses timeout-based detection (no data for >udp_timeout = offline)
    """

    def __init__(self, config: dict):
        super().__init__("thruster", config)
        self.ips = config.get('SENSOR_IPS', {})
        self.topics = config.get('ROS2_TOPICS', {}).get('thruster', {})
        thresholds = config.get('SENSOR_THRESHOLDS', {}).get('thruster', {})

        self.thruster_ip = self.ips.get('thruster', '192.168.50.100')
        # Monitor UDP port (receives HEARTBEAT, S status, F flow, D temp/humidity from Arduino)
        self.monitor_port = 28889
        self.status_topic = self.topics.get('status', '/thruster_status_pwm')
        self.temp_humidity_topic = self.topics.get('temp_humidity', '/temp_humidity')

        # Temperature & humidity data cache
        self._latest_temp_humidity = {
            'temp1': None,
            'humidity1': None,
            'temp2': None,
            'humidity2': None,
        }
        self._last_temp_humidity_time = 0
        self._latest_thruster_status = {
            'mode': None,
            'mode_label': None,
            'left_pwm': None,
            'right_pwm': None,
        }
        self._last_thruster_status_time = 0
        self._latest_flow_data = {
            'freq_hz': None,
            'flow_lmin': None,
            'velocity_ms': None,
            'total_liters': None,
        }
        self._last_flow_data_time = 0

        # UDP timeout (matching driver's udp_timeout parameter)
        self.udp_timeout = thresholds.get('heartbeat_timeout', 5.0)
        self._ping_timeout = float(thresholds.get('ping_timeout', 2.0))
        self._ping_count = int(thresholds.get('ping_count', 2))

        # UDP socket for heartbeat detection
        self._udp_socket: Optional[socket.socket] = None
        self._udp_listen_thread: Optional[threading.Thread] = None
        self._udp_running = False
        self._udp_lock = threading.Lock()

        # Heartbeat tracking
        self._last_udp_receive = 0.0  # Timestamp of last UDP data received
        self._last_heartbeat = ""     # Last heartbeat message received
        self._heartbeat_count = 0     # Total heartbeats received
        self._ros2_monitor = None

        # Connection state caching for resilience against transient failures
        self._last_successful_connection = 0
        self._consecutive_failures = 0
        self._connection_grace_period = float(thresholds.get('connection_grace_period', 30))
        self._max_consecutive_failures = int(thresholds.get('max_consecutive_failures', 3))

        # Alert tracking to avoid duplicate alerts
        self._last_alert_time = {}  # alert_type -> last_timestamp
        self._alert_cooldown = 60  # seconds between same alert type

        # Track previous connection state for disconnection alerts
        self._was_connected = True  # Assume connected on startup

        # Initialize UDP listener
        self._init_udp_listener()

    def _init_udp_listener(self):
        """Initialize UDP socket listener for heartbeat detection

        Creates a non-blocking UDP socket bound to port 28889
        to receive heartbeat and data from the thruster controller.
        """
        try:
            self._udp_socket = self._create_udp_socket(self.monitor_port)

            if self._udp_socket:
                self._udp_running = True
                # Start background thread to listen for UDP data
                self._udp_listen_thread = threading.Thread(
                    target=self._udp_listen_loop,
                    daemon=True,
                    name="ThrusterUDPListener"
                )
                self._udp_listen_thread.start()
                logger.info(f"Thruster UDP listener started on port {self.monitor_port}")
        except Exception as e:
            logger.error(f"Failed to initialize UDP listener: {e}")

    def _create_udp_socket(self, port: int) -> Optional[socket.socket]:
        """Create and bind a UDP socket to the specified port"""
        try:
            sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
            sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
            sock.setblocking(False)  # Non-blocking mode
            sock.bind(('', port))  # Bind to all interfaces
            return sock
        except OSError as e:
            # Port might be in use by the actual ROS2 node - that's OK
            logger.debug(f"Could not bind to port {port}: {e}")
            return None

    def _udp_listen_loop(self):
        """Background thread loop to receive UDP data

        Listens for any UDP data from the thruster controller.
        Updates last_udp_receive timestamp when any data is received.
        """
        buffer_size = 256
        timeout_sec = 1.0  # Poll interval

        while self._udp_running:
            try:
                if self._udp_socket is None:
                    break

                # Use select to check for data with timeout
                readable, _, _ = select.select([self._udp_socket], [], [], timeout_sec)

                current_time = time.time()

                for sock in readable:
                    try:
                        data, addr = sock.recvfrom(buffer_size)
                        if data:
                            data_str = data.decode('utf-8', errors='ignore').strip()

                            # Update last receive time on ANY data from thruster
                            # Check if source is our thruster IP (or accept any for testing)
                            if addr[0] == self.thruster_ip or self.thruster_ip == '0.0.0.0':
                                with self._udp_lock:
                                    self._last_udp_receive = current_time

                                    # Track heartbeat messages
                                    if 'HEARTBEAT' in data_str:
                                        self._last_heartbeat = data_str
                                        self._heartbeat_count += 1
                                        logger.debug(f"Thruster heartbeat received: {data_str}")

                                    # Also track other data (S status, F flow, D temp/humidity)
                                    if data_str and data_str[0] in ['S', 'F', 'D']:
                                        logger.debug(f"Thruster data received: {data_str}")
                                        if data_str[0] == 'S':
                                            self._parse_thruster_status(data_str)
                                        elif data_str[0] == 'F':
                                            self._parse_flow_data(data_str)
                                        elif data_str[0] == 'D':
                                            self._parse_temp_humidity(data_str)

                    except (socket.error, UnicodeDecodeError) as e:
                        pass

            except (select.error, ValueError):
                # Socket might have been closed
                break
            except Exception as e:
                logger.debug(f"UDP listen error: {e}")

    def _close_udp_listener(self):
        """Close UDP sockets and stop listener thread"""
        self._udp_running = False
        if self._udp_socket:
            try:
                self._udp_socket.close()
            except Exception:
                pass
            self._udp_socket = None

    def _parse_temp_humidity(self, data_str: str):
        """Parse temperature & humidity from D message

        Format: D <temp1> <hum1> <temp2> <hum2>
        Example: D 25.30 65.00 24.80 68.50
        """
        try:
            parts = data_str.split()
            if len(parts) >= 5 and parts[0] == 'D':
                self._latest_temp_humidity['temp1'] = float(parts[1])
                self._latest_temp_humidity['humidity1'] = float(parts[2])
                self._latest_temp_humidity['temp2'] = float(parts[3])
                self._latest_temp_humidity['humidity2'] = float(parts[4])
                self._last_temp_humidity_time = time.time()
                logger.debug(f"Temp/Humidity parsed: {self._latest_temp_humidity}")
        except (ValueError, IndexError) as e:
            logger.debug(f"Failed to parse temp/humidity: {e}")

    def _parse_thruster_status(self, data_str: str):
        """Parse thruster status from S message.

        Format: S <mode> <left_pwm> <right_pwm>
        """
        try:
            parts = data_str.split()
            if len(parts) >= 4 and parts[0] == 'S':
                mode = int(float(parts[1]))
                left_pwm = int(float(parts[2]))
                right_pwm = int(float(parts[3]))
                mode_label = 'WiFi' if mode == 1 else 'RC' if mode == 0 else f'Mode {mode}'
                self._latest_thruster_status = {
                    'mode': mode,
                    'mode_label': mode_label,
                    'left_pwm': left_pwm,
                    'right_pwm': right_pwm,
                }
                self._last_thruster_status_time = time.time()
        except (ValueError, IndexError) as e:
            logger.debug(f"Failed to parse thruster status: {e}")

    def _parse_flow_data(self, data_str: str):
        """Parse flow/speed data from F message.

        Format: F <freq_hz> <flow_lmin> <velocity_ms> <total_liters>
        """
        try:
            parts = data_str.split()
            if len(parts) >= 5 and parts[0] == 'F':
                self._latest_flow_data = {
                    'freq_hz': float(parts[1]),
                    'flow_lmin': float(parts[2]),
                    'velocity_ms': float(parts[3]),
                    'total_liters': float(parts[4]),
                }
                self._last_flow_data_time = time.time()
        except (ValueError, IndexError) as e:
            logger.debug(f"Failed to parse flow data: {e}")

    def _read_temp_humidity(self) -> Dict[str, Optional[float]]:
        """Read latest temperature & humidity data from ROS2 topic

        Uses rclpy to directly subscribe and read one message.
        Falls back to UDP-parsed data if topic read fails.

        Returns:
            Dict with temperature and humidity values or cached data
        """
        # First try to use UDP-parsed data (more recent)
        if self._last_temp_humidity_time > 0:
            time_since = time.time() - self._last_temp_humidity_time
            if time_since < 5.0:  # Data is fresh (< 5 seconds)
                return self._latest_temp_humidity

        # Try to read from ROS2 topic using rclpy
        if RCLPY_AVAILABLE:
            initialized_here = False
            node = None
            try:
                import rclpy
                from rclpy.node import Node
                from threading import Lock

                # We need to import the custom message type.
                # This works because the service has the correct environment.
                try:
                    from thruster_control.msg import TempHumidity
                except ImportError:
                    logger.debug("Could not import TempHumidity message type")
                    return self._latest_temp_humidity

                data_received = []
                lock = Lock()
                topic_name = self.temp_humidity_topic
                node_name = f"temp_humidity_reader_{int(time.time() * 1000)}"

                class TempHumidityReader(Node):
                    def __init__(self, name: str):
                        super().__init__(name)
                        self.subscription = self.create_subscription(
                            TempHumidity,
                            topic_name,
                            self.callback,
                            10)

                    def callback(self, msg):
                        with lock:
                            data_received.append({
                                'temp1': msg.temp1,
                                'humidity1': msg.humidity1,
                                'temp2': msg.temp2,
                                'humidity2': msg.humidity2,
                            })

                if not rclpy.ok():
                    rclpy.init()
                    initialized_here = True

                node = TempHumidityReader(node_name)

                # Spin briefly to get one message
                start_time = time.time()
                while time.time() - start_time < 1.5:
                    rclpy.spin_once(node, timeout_sec=0.1)
                    with lock:
                        if data_received:
                            data = data_received[0]
                            break
                else:
                    logger.debug("Temp/Humidity topic timeout")
                    return self._latest_temp_humidity

                if all(v is not None for v in data.values()):
                    self._latest_temp_humidity = data
                    self._last_temp_humidity_time = time.time()
                    logger.debug(f"Temp/Humidity read via rclpy: {data}")
                    return data

            except Exception as e:
                logger.debug(f"Temp/Humidity rclpy read error: {e}")
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

        # Return cached data
        return self._latest_temp_humidity

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
        """Perform thruster diagnostic check

        Status decision flow (mirrors thruster_wifi_node.cpp logic):
        1. Physical connection failed? → DISCONNECTED (network unreachable)
        2. UDP heartbeat timeout? → WARNING (no data for >udp_timeout)
        3. System not running? → CONNECTED (hardware ok, ROS2 not running)
        4. Everything normal → OK
        """
        metrics = {}
        details = {}

        # 1. Network connectivity check (ping) - always check
        ping_result = self._check_connectivity()
        metrics['network'] = ping_result
        details['network'] = ping_result

        network_ok = ping_result.get('reachable', False)

        if not network_ok:
            # Record disconnection alert when transitioning from connected to disconnected
            if self._was_connected:
                current_time = time.time()
                if current_time - self._last_alert_time.get('sensor_disconnected', 0) > self._alert_cooldown:
                    self._record_alert(
                        alert_type='sensor_disconnected',
                        severity='critical',
                        message=f'Thruster disconnected - network unreachable ({self.thruster_ip})',
                        metric_value=0,
                        threshold=1,
                        metadata={
                            'ip': self.thruster_ip,
                            'reason': 'network_unreachable'
                        }
                    )
                    self._last_alert_time['sensor_disconnected'] = current_time
                self._was_connected = False

            self.last_check = datetime.now()
            self.check_count += 1
            self.last_result = DiagnosticResult(
                name=self.name,
                status=StatusLevel.DISCONNECTED,
                message=f"Thruster - network unreachable ({self.thruster_ip})",
                timestamp=self.last_check,
                metrics=metrics,
                details=details
            )
            return self.last_result

        # Update connection state when network is reachable
        if not self._was_connected:
            self._was_connected = True

        # 2. UDP heartbeat check - matching driver's timeout logic
        udp_result = self._check_udp_heartbeat()
        metrics['udp'] = udp_result
        details['udp'] = udp_result
        metrics['temp_humidity'] = self._latest_temp_humidity
        metrics['thruster_status'] = self._latest_thruster_status
        metrics['flow_data'] = self._latest_flow_data

        heartbeat_ok = udp_result.get('online', False)
        time_since_last = udp_result.get('time_since_last', 0)

        # 3. Check if ROS2 system is running
        ros2_monitor = self._get_ros2_monitor()
        ros2_running = ros2_monitor.is_system_running()
        metrics['system_running'] = ros2_running

        if not ros2_running:
            # Network is connected but ROS2 is not running
            self.last_check = datetime.now()
            self.check_count += 1
            self.last_result = DiagnosticResult(
                name=self.name,
                status=StatusLevel.CONNECTED,
                message=f"Thruster - network OK, ROS2 not running",
                timestamp=self.last_check,
                metrics=metrics,
                details=details
            )
            return self.last_result

        # 4. ROS2 topic check
        topic_result = self._check_topics()
        metrics['topics'] = topic_result['metrics']
        
        # Extract temp_humidity to top level for get_diagnostic_summary()
        if 'temp_humidity' in topic_result['metrics']:
            metrics['temp_humidity'] = topic_result['metrics']['temp_humidity']

        topic_ok = topic_result['metrics'].get('available', False)

        # 5. Determine overall status
        if not heartbeat_ok:
            overall_status = StatusLevel.WARNING
            message = f"Thruster - no heartbeat for {time_since_last:.1f}s (timeout: {self.udp_timeout}s)"
        elif not topic_ok:
            overall_status = StatusLevel.CONNECTED
            message = f"Thruster - heartbeat OK, no topic data"
        else:
            overall_status = StatusLevel.OK
            message = f"Thruster - OK (heartbeat {self._heartbeat_count} total, last {time_since_last:.1f}s ago)"

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

    def _check_connectivity(self) -> Dict[str, Any]:
        """Check network connectivity to thruster

        Includes connection state caching to prevent false disconnections.
        """
        current_time = time.time()
        result = ping_host(self.thruster_ip, timeout=self._ping_timeout, count=self._ping_count)

        if result.get('reachable'):
            self._last_successful_connection = current_time
            self._consecutive_failures = 0
            return {
                'ip': self.thruster_ip,
                'reachable': True,
                'latency_ms': result.get('avg_time_ms', 0),
                'packet_loss': result.get('packet_loss', 0),
            }

        # Ping failed - check grace period
        time_since_last_success = current_time - self._last_successful_connection
        self._consecutive_failures += 1

        in_grace_period = time_since_last_success < self._connection_grace_period
        within_failure_limit = self._consecutive_failures <= self._max_consecutive_failures
        has_previous_success = self._last_successful_connection > 0

        if in_grace_period and within_failure_limit and has_previous_success:
            return {
                'ip': self.thruster_ip,
                'reachable': True,
                'latency_ms': 0,
                'packet_loss': 0,
                'cached': True,
                'consecutive_failures': self._consecutive_failures,
            }

        return {
            'ip': self.thruster_ip,
            'reachable': False,
            'latency_ms': 0,
            'packet_loss': 100,
            'consecutive_failures': self._consecutive_failures,
        }

    def _check_udp_heartbeat(self) -> Dict[str, Any]:
        """Check UDP heartbeat status (matching driver's timeout logic)

        Mirrors the logic in thruster_wifi_node.cpp:
            arduino_online_ = (now - last_udp_receive_) < timeout_duration;

        Returns:
            Dict with heartbeat status info
        """
        current_time = time.time()

        with self._udp_lock:
            time_since_last = current_time - self._last_udp_receive if self._last_udp_receive > 0 else 999.0
            is_online = time_since_last < self.udp_timeout

        result = {
            'ip': self.thruster_ip,
            'port': self.monitor_port,
            'timeout': self.udp_timeout,
            'online': is_online,
            'time_since_last': time_since_last,
            'last_heartbeat': self._last_heartbeat,
            'total_heartbeats': self._heartbeat_count,
        }

        if is_online:
            self._last_successful_connection = current_time
            self._consecutive_failures = 0
        else:
            # Check grace period
            time_since_success = current_time - self._last_successful_connection
            self._consecutive_failures += 1

            in_grace = time_since_success < self._connection_grace_period
            within_limit = self._consecutive_failures <= self._max_consecutive_failures
            has_success = self._last_successful_connection > 0

            if in_grace and within_limit and has_success:
                result['online'] = True
                result['cached'] = True
                result['consecutive_failures'] = self._consecutive_failures

        return result

    def _check_topics(self) -> Dict[str, Any]:
        """Check if thruster topics have publishers using rclpy"""
        if not RCLPY_AVAILABLE:
            return {
                'status': StatusLevel.STOPPED,
                'metrics': {
                    'status_topic': self.status_topic,
                    'available': False,
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
                    'status_topic': self.status_topic,
                    'available': False,
                },
                'details': {'error': 'ROS2 system not running'}
            }

        try:
            helper = get_ros2_helper(42)

            # Get all nodes
            nodes = helper.get_node_names()

            # Find nodes that might publish thruster data
            thruster_nodes = [n for n in nodes if any(
                pattern in n.lower() for pattern in ['thruster', 'pwm', 'motor']
            )]

            # Get all topic names
            topics = helper.get_topic_names()
            has_topic = self.status_topic in topics

            # Check if any thruster node exists (likely publishing our topic)
            has_thruster_node = len(thruster_nodes) > 0

            if has_topic and has_thruster_node:
                # Read temperature & humidity data
                temp_humidity = self._read_temp_humidity()

                return {
                    'status': StatusLevel.OK,
                    'metrics': {
                        'status_topic': self.status_topic,
                        'available': True,
                        'thruster_nodes': thruster_nodes,
                        'temp_humidity': temp_humidity,
                        'thruster_status': self._latest_thruster_status,
                        'flow_data': self._latest_flow_data,
                    },
                    'details': {
                        'all_topics': [t for t in topics if 'thruster' in t.lower()],
                    }
                }
            elif has_topic:
                return {
                    'status': StatusLevel.WARNING,
                    'metrics': {
                        'status_topic': self.status_topic,
                        'available': True,
                        'thruster_nodes': [],
                        'temp_humidity': self._latest_temp_humidity,
                        'thruster_status': self._latest_thruster_status,
                        'flow_data': self._latest_flow_data,
                    },
                    'details': {'message': 'Topic exists but no thruster node found'}
                }
            else:
                return {
                    'status': StatusLevel.WARNING,
                    'metrics': {
                        'status_topic': self.status_topic,
                        'available': False,
                        'thruster_nodes': thruster_nodes,
                        'temp_humidity': self._latest_temp_humidity,
                        'thruster_status': self._latest_thruster_status,
                        'flow_data': self._latest_flow_data,
                    },
                    'details': {'message': 'Topic not found'}
                }
        except Exception as e:
            return {
                'status': StatusLevel.STOPPED,
                'metrics': {
                    'status_topic': self.status_topic,
                    'available': False,
                    'temp_humidity': self._latest_temp_humidity,
                    'thruster_status': self._latest_thruster_status,
                    'flow_data': self._latest_flow_data,
                },
                'details': {'error': f'Could not check topics: {e}'}
            }

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
                sensor='thruster',
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
            logger.info(f"Thruster alert recorded: ID={alert_id}, type={alert_type}, severity={severity}")
        except Exception as e:
            logger.error(f"Failed to record Thruster alert: {e}")

    def _get_data_updated_at(self) -> Optional[str]:
        """Get ISO timestamp of the latest telemetry update from Arduino."""
        with self._udp_lock:
            last_udp_receive = self._last_udp_receive

        latest_timestamp = max(
            last_udp_receive,
            self._last_temp_humidity_time,
            self._last_thruster_status_time,
            self._last_flow_data_time,
        )
        if latest_timestamp <= 0:
            return None
        return datetime.fromtimestamp(latest_timestamp).isoformat()

    def get_diagnostic_summary(self) -> Dict[str, Any]:
        """Get summary for dashboard display"""
        if self.last_result is None:
            return {
                'name': 'Arduino',
                'status': 'stopped',
                'icon': 'fa-solid fa-microchip',
                'color': 'gray',
                'data_updated_at': None,
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
        online = self.last_result.metrics.get('udp', {}).get('online', False)

        # Get temperature & humidity data
        temp_humidity = self.last_result.metrics.get('temp_humidity', {})
        temp1 = temp_humidity.get('temp1')
        hum1 = temp_humidity.get('humidity1')
        thruster_status = self.last_result.metrics.get('thruster_status', {})
        flow_data = self.last_result.metrics.get('flow_data', {})
        data_updated_at = self._get_data_updated_at()

        # Format value string
        if temp1 is not None and hum1 is not None:
            value_str = f"{temp1:.1f}°C / {hum1:.0f}%"
        else:
            value_str = 'Online' if online else 'Offline'

        return {
            'name': 'Arduino',
            'status': status_str,
            'icon': 'fa-solid fa-microchip',
            'color': color,
            'value': value_str,
            'message': self.last_result.message,
            'temp_humidity': temp_humidity,
            'thruster_status': thruster_status,
            'flow_data': flow_data,
            'data_updated_at': data_updated_at,
        }
