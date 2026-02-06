#!/usr/bin/env python3
"""
Navi LiDAR Diagnostic
Monitors Hesai QT128 Navi LiDAR health (IP: 192.168.0.201)
"""

import json
import logging
import subprocess
import time
from datetime import datetime
from typing import Any, Dict

from ..base import BaseDiagnostic, DiagnosticResult, StatusLevel, get_higher_priority_status
from ..utils import ping_host, check_tcp_connectivity_sync
from ..ros2_helper import get_ros2_helper, RCLPY_AVAILABLE

logger = logging.getLogger(__name__)


class NaviLidarDiagnostic(BaseDiagnostic):
    """Monitor Navi LiDAR (Hesai QT128) health - simplified"""

    def __init__(self, config: dict):
        super().__init__("navi_lidar", config)
        self.ips = config.get('SENSOR_IPS', {})
        self.topics = config.get('ROS2_TOPICS', {}).get('navi_lidar', {})
        self.thresholds = config.get('SENSOR_THRESHOLDS', {}).get('navi_lidar', {})

        self.lidar_ip = self.ips.get('navi_lidar', '192.168.0.201')
        self.points_topic = self.topics.get('points', '/navi_lidar/points')

        # Connection status
        self._last_ping_result = None
        self._last_ping_time = None
        self._ros2_monitor = None

        # Log parser for data quality monitoring
        self._log_parser = None

        # Alert tracking to avoid duplicate alerts
        self._last_alert_time = {}  # alert_type -> last_timestamp
        self._alert_cooldown = 60  # seconds between same alert type

        # Connection state caching for resilience against transient failures
        self._last_successful_connection = 0  # timestamp of last successful connection
        self._consecutive_failures = 0  # count of consecutive failures
        self._connection_grace_period = float(self.thresholds.get('connection_grace_period', 30))
        self._max_consecutive_failures = int(self.thresholds.get('max_consecutive_failures', 3))

        # Track previous connection state for disconnection alerts
        self._was_connected = True  # Assume connected on startup

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
        """Perform Navi LiDAR diagnostic check

        Status decision flow:
        1. Physical connection failed? → DISCONNECTED
        2. System not running? → CONNECTED (hardware ok, ROS2 not running)
        3. Data quality issues? → WARNING / CRITICAL
        4. Connected but no data? → CONNECTED
        5. Everything normal → OK
        """
        metrics = {}
        details = {}

        # 1. Network connectivity check (always check, regardless of ROS2 status)
        ping_result = self._check_connectivity()
        metrics['network'] = ping_result
        details['network'] = ping_result

        network_ok = ping_result.get('reachable', False)
        latency = ping_result.get('latency_ms', 0)
        packet_loss = ping_result.get('packet_loss', 0)

        if not network_ok:
            # Record disconnection alert when transitioning from connected to disconnected
            if self._was_connected:
                current_time = time.time()
                if current_time - self._last_alert_time.get('sensor_disconnected', 0) > self._alert_cooldown:
                    self._record_alert(
                        alert_type='sensor_disconnected',
                        severity='critical',
                        message=f'Navi LiDAR disconnected - network unreachable ({self.lidar_ip})',
                        metric_value=0,
                        threshold=1,
                        metadata={
                            'ip': self.lidar_ip,
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
                message=f"Navi LiDAR - network unreachable ({self.lidar_ip})",
                timestamp=self.last_check,
                metrics=metrics,
                details=details
            )
            return self.last_result

        # Update connection state when network is reachable
        if not self._was_connected:
            self._was_connected = True

        # 2. Check if ROS2 system is running
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
                message=f"Navi LiDAR - connected, ROS2 not running ({latency:.0f}ms latency)",
                timestamp=self.last_check,
                metrics=metrics,
                details=details
            )
            return self.last_result

        # 3. ROS2 topic check
        topic_result = self._check_topics()
        metrics['topics'] = topic_result['metrics']
        details['topics'] = topic_result['details']

        topic_ok = metrics.get('topics', {}).get('points_available', False)

        # 4. 从日志文件检查数据质量 (丢帧、点云数降低)
        log_result = self._check_lidar_log_data()
        metrics['log_data'] = log_result['metrics']
        details['log_data'] = log_result['details']
        log_status = log_result['status']

        # 5. Determine overall status
        if not topic_ok:
            overall_status = StatusLevel.CONNECTED
            message = f"Navi LiDAR - connected, no data ({latency:.0f}ms latency)"
        elif log_status == StatusLevel.CRITICAL:
            overall_status = StatusLevel.CRITICAL
            issues = log_result['details'].get('issues', [])
            message = f"Navi LiDAR - CRITICAL: {issues[0] if issues else 'data quality issue'}"
        elif log_status == StatusLevel.WARNING:
            overall_status = StatusLevel.WARNING
            issues = log_result['details'].get('issues', [])
            message = f"Navi LiDAR - WARNING: {issues[0] if issues else 'data quality issue'} ({latency:.0f}ms latency)"
        elif packet_loss > 1:
            overall_status = StatusLevel.WARNING
            message = f"Navi LiDAR - OK, high packet loss ({packet_loss:.1f}%)"
        else:
            # 添加统计信息到成功消息
            overall_status = StatusLevel.OK
            freq = log_result['metrics'].get('measured_frequency')
            pts = log_result['metrics'].get('avg_points')
            if freq and pts:
                message = f"Navi LiDAR - OK ({freq:.1f} Hz, {pts:.0f} pts/frame, {latency:.0f}ms latency)"
            else:
                message = f"Navi LiDAR - OK ({latency:.0f}ms latency)"

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
        """Check network connectivity to Navi LiDAR

        Uses TCP connection to Web interface (port 8081) for fast detection.
        Falls back to ping if TCP fails.

        Includes connection state caching to prevent false disconnections
        from transient network issues (e.g., device power-saving, firewall timeouts).
        """
        current_time = time.time()

        # Try TCP connection first (much faster - 0.5s vs 3s)
        tcp_result = check_tcp_connectivity_sync(self.lidar_ip, port=8081, timeout=0.5)

        if tcp_result.get('reachable'):
            # Connection successful - update state and return success
            self._last_ping_result = tcp_result
            self._last_ping_time = current_time
            self._last_successful_connection = current_time
            self._consecutive_failures = 0
            return {
                'status': StatusLevel.OK,
                'ip': self.lidar_ip,
                'reachable': True,
                'latency_ms': tcp_result.get('latency_ms', 0),
                'method': 'tcp',
            }

        # TCP failed - try ping fallback
        result = ping_host(self.lidar_ip, timeout=1, count=1)

        if result.get('reachable'):
            # Ping succeeded - update state and return success
            self._last_ping_result = result
            self._last_ping_time = current_time
            self._last_successful_connection = current_time
            self._consecutive_failures = 0
            return {
                'status': StatusLevel.OK,
                'ip': self.lidar_ip,
                'reachable': True,
                'latency_ms': result.get('avg_time_ms', 0),
                'packet_loss': result.get('packet_loss', 0),
                'method': 'ping',
            }

        # Both TCP and ping failed - check if we should use cached success state
        time_since_last_success = current_time - self._last_successful_connection
        self._consecutive_failures += 1

        # Grace period logic: keep showing "connected" if:
        # 1. Within grace period of last successful connection, AND
        # 2. Haven't exceeded max consecutive failures
        in_grace_period = time_since_last_success < self._connection_grace_period
        within_failure_limit = self._consecutive_failures <= self._max_consecutive_failures
        has_previous_success = self._last_successful_connection > 0

        if in_grace_period and within_failure_limit and has_previous_success:
            # Use cached success state to prevent false disconnection
            logger.info(
                f"Navi LiDAR: Using cached connection state "
                f"(failure #{self._consecutive_failures}, "
                f"{time_since_last_success:.1f}s since last success)"
            )
            cached_result = self._last_ping_result or {}
            return {
                'status': StatusLevel.OK,
                'ip': self.lidar_ip,
                'reachable': True,
                'latency_ms': cached_result.get('latency_ms', cached_result.get('avg_time_ms', 0)),
                'method': f'{cached_result.get("method", "cached")}_cached',
                'cached': True,
                'consecutive_failures': self._consecutive_failures,
                'time_since_last_success': time_since_last_success,
            }

        # Genuine disconnection - grace period expired or too many failures
        self._last_ping_result = result
        self._last_ping_time = current_time

        return {
            'status': StatusLevel.CRITICAL,
            'ip': self.lidar_ip,
            'reachable': False,
            'latency_ms': 0,
            'packet_loss': 100,
            'method': 'failed',
            'consecutive_failures': self._consecutive_failures,
            'time_since_last_success': time_since_last_success,
        }

    def _check_topics(self) -> Dict[str, Any]:
        """Check if Navi LiDAR topics have publishers using rclpy"""
        if not RCLPY_AVAILABLE:
            return {
                'status': StatusLevel.STOPPED,
                'metrics': {
                    'points_topic': self.points_topic,
                    'points_available': False,
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
                    'points_topic': self.points_topic,
                    'points_available': False,
                },
                'details': {'error': 'ROS2 system not running'}
            }

        try:
            helper = get_ros2_helper(self._get_domain_id())

            # Get all nodes
            nodes = helper.get_node_names()

            # Find nodes that might publish lidar data
            lidar_nodes = [n for n in nodes if any(
                pattern in n.lower() for pattern in ['navi', 'lidar', 'hesai']
            )]

            # Get all topic names
            topics = helper.get_topic_names()
            has_topic = self.points_topic in topics

            # Check if any lidar node exists (likely publishing our topic)
            has_lidar_node = len(lidar_nodes) > 0

            # CRITICAL: Verify topic has active publishers (not just exists in DDS)
            publisher_count = self._get_topic_publisher_count(self.points_topic)
            has_publishers = publisher_count > 0

            # Fallback: if rclpy didn't find topic/nodes but publisher exists, use shell command
            if not has_topic and not has_lidar_node:
                try:
                    import subprocess
                    # Try shell command to get nodes
                    node_result = subprocess.run(
                        ['ros2', 'node', 'list'],
                        capture_output=True,
                        text=True,
                        timeout=2
                    )
                    if node_result.returncode == 0:
                        shell_nodes = [n.strip() for n in node_result.stdout.strip().split('\n') if n.strip()]
                        lidar_nodes = [n for n in shell_nodes if any(
                            pattern in n.lower() for pattern in ['navi', 'lidar', 'hesai']
                        )]
                        has_lidar_node = len(lidar_nodes) > 0

                    # Try shell command to get topics
                    topic_result = subprocess.run(
                        ['ros2', 'topic', 'list'],
                        capture_output=True,
                        text=True,
                        timeout=2
                    )
                    if topic_result.returncode == 0:
                        shell_topics = [t.strip() for t in topic_result.stdout.strip().split('\n') if t.strip()]
                        has_topic = self.points_topic in shell_topics

                        if has_topic:
                            logger.debug(f"[NaviLidar] Topic found via shell fallback")

                    # Re-check publishers with updated info
                    if not has_publishers and has_topic:
                        publisher_count = self._get_topic_publisher_count(self.points_topic)
                        has_publishers = publisher_count > 0
                except Exception as shell_error:
                    logger.debug(f"Shell fallback failed: {shell_error}")

            if has_topic and has_lidar_node and has_publishers:
                return {
                    'status': StatusLevel.OK,
                    'metrics': {
                        'points_topic': self.points_topic,
                        'points_available': True,
                        'lidar_nodes': lidar_nodes,
                    },
                    'details': {
                        'all_topics': [t for t in topics if 'lidar' in t.lower() or 'hesai' in t.lower()],
                    }
                }
            elif has_topic:
                return {
                    'status': StatusLevel.WARNING,
                    'metrics': {
                        'points_topic': self.points_topic,
                        'points_available': True,
                        'lidar_nodes': [],
                    },
                    'details': {'message': 'Topic exists but no lidar node found'}
                }
            else:
                return {
                    'status': StatusLevel.WARNING,
                    'metrics': {
                        'points_topic': self.points_topic,
                        'points_available': False,
                        'lidar_nodes': lidar_nodes,
                    },
                    'details': {'message': 'Topic not found'}
                }
        except Exception as e:
            return {
                'status': StatusLevel.STOPPED,
                'metrics': {
                    'points_topic': self.points_topic,
                    'points_available': False,
                },
                'details': {'error': f'Could not check topics: {e}'}
            }

    def _get_topic_publisher_count(self, topic_name: str) -> int:
        """Get the number of publishers for a topic using ros2 topic info

        Args:
            topic_name: Full topic name (e.g., '/navi_lidar/points')

        Returns:
            Number of publishers (0 if none or error)
        """
        try:
            import subprocess
            result = subprocess.run(
                ['ros2', 'topic', 'info', topic_name],
                capture_output=True,
                text=True,
                timeout=2
            )

            # Parse output for publisher count
            # Format: "Publisher count: 1"
            for line in result.stdout.split('\n'):
                if 'Publisher count:' in line:
                    try:
                        count_str = line.split('Publisher count:')[1].strip()
                        return int(count_str)
                    except (ValueError, IndexError):
                        pass

            # Alternative: look for "Publishers:" section in newer ROS2 versions
            # or check if there's a "Publishers:" header followed by entries
            if 'Publishers:' in result.stdout:
                # Count the number of publisher entries after "Publishers:"
                publishers_section = result.stdout.split('Publishers:')[-1]
                # Count non-empty lines that look like node entries
                publisher_lines = [l for l in publishers_section.split('\n')
                                     if l.strip() and not l.strip().startswith('---')]
                # First line after "Publishers:" is header, actual publishers start after
                if len(publisher_lines) > 1:
                    return len(publisher_lines) - 1

            return 0
        except Exception as e:
            logger.debug(f"Failed to get publisher count for {topic_name}: {e}")
            return 0

    def _check_lidar_log_data(self) -> Dict[str, Any]:
        """从日志文件检查 LiDAR 数据质量

        监控:
        - 丢帧 (频率检测)
        - 点云数降低
        """
        from ..lidar_log_parser import LidarLogParser

        # 获取阈值配置
        thresholds = self.config.get('sensors', {}).get('thresholds', {}).get('navi_lidar', {})
        min_frequency = thresholds.get('min_frequency', 8.0)
        min_points = thresholds.get('min_points_per_frame', 50000)

        # 创建或获取解析器
        if self._log_parser is None:
            self._log_parser = LidarLogParser(max_history=100)

        # 获取统计
        stats = self._log_parser.get_statistics()

        metrics = {
            'frame_count': stats.frame_count,
            'total_points': stats.total_points,
            'avg_points': stats.avg_points,
            'min_points': stats.min_points,
            'max_points': stats.max_points,
            'measured_frequency': stats.frequency,
            'last_frame_num': stats.last_frame_num,
            'time_since_last_frame': stats.time_since_last_frame,
        }

        details = {
            'thresholds': {
                'min_frequency': min_frequency,
                'min_points_per_frame': min_points
            },
            'issues': []
        }

        status = StatusLevel.OK

        # 检查是否有数据
        if stats.frame_count == 0:
            status = StatusLevel.CONNECTED
            details['issues'].append('No log data available yet')
            return {
                'status': status,
                'metrics': metrics,
                'details': details
            }

        current_time = time.time()

        # 检查频率 (丢帧检测)
        if stats.frequency > 0:
            if stats.frequency < min_frequency * 0.5:  # 低于 50%
                status = StatusLevel.CRITICAL
                details['issues'].append(
                    f'Severe frame loss: {stats.frequency:.1f} Hz (expected >= {min_frequency} Hz)'
                )
                logger.error(f"Navi LiDAR: Severe frame loss - {stats.frequency:.1f} Hz < {min_frequency} Hz")

                # 记录告警 (带冷却时间避免重复)
                if current_time - self._last_alert_time.get('frame_loss_critical', 0) > self._alert_cooldown:
                    self._record_alert(
                        alert_type='frame_loss_critical',
                        severity='critical',
                        message=f'Severe frame loss: {stats.frequency:.1f} Hz (expected >= {min_frequency} Hz)',
                        metric_value=stats.frequency,
                        threshold=min_frequency,
                        metadata={
                            'measured_frequency': stats.frequency,
                            'frame_count': stats.frame_count,
                            'avg_points': stats.avg_points
                        }
                    )
                    self._last_alert_time['frame_loss_critical'] = current_time

            elif stats.frequency < min_frequency:  # 低于阈值
                status = StatusLevel.WARNING
                details['issues'].append(
                    f'Frame loss detected: {stats.frequency:.1f} Hz (expected >= {min_frequency} Hz)'
                )
                logger.warning(f"Navi LiDAR: Frame loss - {stats.frequency:.1f} Hz < {min_frequency} Hz")

                # 记录告警
                if current_time - self._last_alert_time.get('frame_loss', 0) > self._alert_cooldown:
                    self._record_alert(
                        alert_type='frame_loss',
                        severity='warning',
                        message=f'Frame loss detected: {stats.frequency:.1f} Hz (expected >= {min_frequency} Hz)',
                        metric_value=stats.frequency,
                        threshold=min_frequency,
                        metadata={
                            'measured_frequency': stats.frequency,
                            'frame_count': stats.frame_count,
                            'avg_points': stats.avg_points
                        }
                    )
                    self._last_alert_time['frame_loss'] = current_time

        # 检查点数 (点云数降低检测)
        avg_points = stats.avg_points
        if avg_points < min_points * 0.5:  # 低于 50%
            status = get_higher_priority_status(status, StatusLevel.CRITICAL)
            details['issues'].append(
                f'Point count very low: {avg_points:.0f} (expected >= {min_points})'
            )
            logger.error(f"Navi LiDAR: Very low point count - {avg_points:.0f} < {min_points}")

            # 记录告警
            if current_time - self._last_alert_time.get('point_count_critical', 0) > self._alert_cooldown:
                self._record_alert(
                    alert_type='point_count_critical',
                    severity='critical',
                    message=f'Point count very low: {avg_points:.0f} (expected >= {min_points})',
                    metric_value=avg_points,
                    threshold=min_points,
                    metadata={
                        'avg_points': avg_points,
                        'min_points': stats.min_points,
                        'max_points': stats.max_points,
                        'frame_count': stats.frame_count
                    }
                )
                self._last_alert_time['point_count_critical'] = current_time

        elif avg_points < min_points:  # 低于阈值
            status = get_higher_priority_status(status, StatusLevel.WARNING)
            details['issues'].append(
                f'Point count reduced: {avg_points:.0f} (expected >= {min_points})'
            )
            logger.warning(f"Navi LiDAR: Point count reduced - {avg_points:.0f} < {min_points}")

            # 记录告警
            if current_time - self._last_alert_time.get('point_count', 0) > self._alert_cooldown:
                self._record_alert(
                    alert_type='point_count_low',
                    severity='warning',
                    message=f'Point count reduced: {avg_points:.0f} (expected >= {min_points})',
                    metric_value=avg_points,
                    threshold=min_points,
                    metadata={
                        'avg_points': avg_points,
                        'min_points': stats.min_points,
                        'max_points': stats.max_points,
                        'frame_count': stats.frame_count
                    }
                )
                self._last_alert_time['point_count'] = current_time

        # 检查数据是否过期
        if stats.time_since_last_frame > 2.0:
            status = get_higher_priority_status(status, StatusLevel.WARNING)
            details['issues'].append(f'No new frames for {stats.time_since_last_frame:.1f}s')
            logger.warning(f"Navi LiDAR: No new frames for {stats.time_since_last_frame:.1f}s")

        return {
            'status': status,
            'metrics': metrics,
            'details': details
        }

    def _record_alert(self, alert_type: str, severity: str, message: str,
                      metric_value: float, threshold: float, metadata: dict):
        """记录告警到数据库

        Args:
            alert_type: 告警类型
            severity: 严重程度 (critical, warning)
            message: 告警消息
            metric_value: 触发值
            threshold: 阈值
            metadata: 额外元数据
        """
        try:
            from alerts import get_alert_store, Alert

            alert = Alert(
                sensor='navi_lidar',
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
            logger.info(f"Navi LiDAR alert recorded: ID={alert_id}, type={alert_type}, severity={severity}")
        except Exception as e:
            logger.error(f"Failed to record alert: {e}")

    def _get_domain_id(self) -> int:
        """Get ROS2 domain ID from config"""
        return 42  # Default from config

    def get_diagnostic_summary(self) -> Dict[str, Any]:
        """Get summary for dashboard display"""
        if self.last_result is None:
            return {
                'name': 'Navi LiDAR',
                'status': 'stopped',
                'icon': 'fa-solid fa-radar',
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
        reachable = self.last_result.metrics.get('network', {}).get('reachable', False)

        return {
            'name': 'Navi LiDAR',
            'status': status_str,
            'icon': 'fa-solid fa-radar',
            'color': color,
            'value': "Connected" if reachable else "Disconnected",
            'message': self.last_result.message,
        }
