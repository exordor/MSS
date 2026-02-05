#!/usr/bin/env python3
"""
Camera Diagnostic
Monitors Galaxy Camera health
"""

import logging
import time
from datetime import datetime
from typing import Any, Dict

from ..base import BaseDiagnostic, DiagnosticResult, StatusLevel, get_higher_priority_status
from ..utils import ping_host, check_gige_camera_arp
from ..ros2_helper import get_ros2_helper, RCLPY_AVAILABLE

logger = logging.getLogger(__name__)


class CameraDiagnostic(BaseDiagnostic):
    """Monitor Galaxy Camera health"""

    def __init__(self, config: dict):
        super().__init__("camera", config)
        self.ips = config.get('SENSOR_IPS', {})
        self.topics = config.get('ROS2_TOPICS', {}).get('camera', {})

        self.camera_ip = self.ips.get('camera', '192.168.0.11')
        self.image_topic = self.topics.get('image_raw', '/image_raw')

        self._ros2_monitor = None
        self._log_parser = None

        # Alert tracking to avoid duplicate alerts
        self._last_alert_time = {}  # alert_type -> last_timestamp
        self._alert_cooldown = 60  # seconds between same alert type

        # Connection state caching for resilience against transient failures
        self._last_successful_connection = 0
        self._consecutive_failures = 0
        self._connection_grace_period = 30
        self._max_consecutive_failures = 3

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
        """Perform camera diagnostic check

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
        network_result = self._check_connectivity()
        metrics['network'] = network_result
        details['network'] = network_result

        network_ok = network_result.get('reachable', False)
        latency = network_result.get('latency_ms', 0)

        if not network_ok:
            # Record disconnection alert when transitioning from connected to disconnected
            if self._was_connected:
                current_time = time.time()
                if current_time - self._last_alert_time.get('sensor_disconnected', 0) > self._alert_cooldown:
                    self._record_alert(
                        alert_type='sensor_disconnected',
                        severity='critical',
                        message=f'Camera disconnected - network unreachable ({self.camera_ip})',
                        metric_value=0,
                        threshold=1,
                        metadata={
                            'ip': self.camera_ip,
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
                message=f"Camera - network unreachable ({self.camera_ip})",
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
                message=f"Camera - connected, ROS2 not running ({latency:.0f}ms latency)",
                timestamp=self.last_check,
                metrics=metrics,
                details=details
            )
            return self.last_result

        # 3. ROS2 topic check
        topic_result = self._check_topics()
        metrics['topics'] = topic_result['metrics']
        details['topics'] = topic_result['details']

        topic_ok = topic_result['metrics'].get('image_available', False)

        # 4. 从日志文件检查数据质量 (丢帧、延迟、网络问题)
        log_result = self._check_camera_log_data()
        metrics['log_data'] = log_result['metrics']
        details['log_data'] = log_result['details']
        log_status = log_result['status']

        # 5. Determine overall status
        if not topic_ok:
            overall_status = StatusLevel.CONNECTED
            message = f"Camera - connected, no data ({latency:.0f}ms latency)"
        elif log_status == StatusLevel.CRITICAL:
            overall_status = StatusLevel.CRITICAL
            issues = log_result['details'].get('issues', [])
            message = f"Camera - CRITICAL: {issues[0] if issues else 'data quality issue'}"
        elif log_status == StatusLevel.WARNING:
            overall_status = StatusLevel.WARNING
            issues = log_result['details'].get('issues', [])
            message = f"Camera - WARNING: {issues[0] if issues else 'data quality issue'} ({latency:.0f}ms latency)"
        else:
            overall_status = StatusLevel.OK
            # 添加统计信息到成功消息
            freq = log_result['metrics'].get('measured_frequency')
            if freq:
                message = f"Camera - OK ({freq:.1f} Hz, {latency:.0f}ms latency)"
            else:
                message = f"Camera - OK ({latency:.0f}ms latency)"

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
        """Check network connectivity to GigE camera

        Uses ARP table query for fast detection (< 0.1s).
        GigE Vision uses custom UDP protocol, not standard TCP ports.
        Fallback to ping if ARP is unavailable.

        Includes connection state caching to prevent false disconnections
        from transient network issues.
        """
        current_time = time.time()

        # Try ARP table first (much faster - < 0.1s)
        arp_result = check_gige_camera_arp(self.camera_ip)

        if arp_result.get('reachable'):
            self._last_successful_connection = current_time
            self._consecutive_failures = 0
            return {
                'ip': self.camera_ip,
                'reachable': True,
                'method': 'arp',
                'state': arp_result.get('state', 'reachable'),
            }

        # Fallback to ping if ARP fails
        result = ping_host(self.camera_ip, timeout=1, count=1)

        if result.get('reachable'):
            self._last_successful_connection = current_time
            self._consecutive_failures = 0
            return {
                'ip': self.camera_ip,
                'reachable': True,
                'latency_ms': result.get('avg_time_ms', 0),
                'packet_loss': result.get('packet_loss', 0),
                'method': 'ping',
            }

        # Both methods failed - check grace period
        time_since_last_success = current_time - self._last_successful_connection
        self._consecutive_failures += 1

        in_grace_period = time_since_last_success < self._connection_grace_period
        within_failure_limit = self._consecutive_failures <= self._max_consecutive_failures
        has_previous_success = self._last_successful_connection > 0

        if in_grace_period and within_failure_limit and has_previous_success:
            # Use cached success state
            return {
                'ip': self.camera_ip,
                'reachable': True,
                'method': 'cached',
                'cached': True,
                'consecutive_failures': self._consecutive_failures,
            }

        return {
            'ip': self.camera_ip,
            'reachable': False,
            'method': 'failed',
            'consecutive_failures': self._consecutive_failures,
        }

    def _check_topics(self) -> Dict[str, Any]:
        """Check if camera topics have publishers using rclpy"""
        if not RCLPY_AVAILABLE:
            return {
                'status': StatusLevel.STOPPED,
                'metrics': {
                    'image_topic': self.image_topic,
                    'image_available': False,
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
                    'image_topic': self.image_topic,
                    'image_available': False,
                },
                'details': {'error': 'ROS2 system not running'}
            }

        try:
            helper = get_ros2_helper(42)

            # Get all nodes
            nodes = helper.get_node_names()

            # Find nodes that might publish camera data
            camera_nodes = [n for n in nodes if any(
                pattern in n.lower() for pattern in ['camera', 'galaxy', 'gmsl']
            )]

            # Get all topic names
            topics = helper.get_topic_names()
            has_topic = self.image_topic in topics

            # Check if any camera node exists
            has_camera_node = len(camera_nodes) > 0

            # CRITICAL: Verify topic has active publishers
            publisher_count = self._get_topic_publisher_count(self.image_topic)
            has_publishers = publisher_count > 0

            if has_topic and has_camera_node and has_publishers:
                return {
                    'status': StatusLevel.OK,
                    'metrics': {
                        'image_topic': self.image_topic,
                        'image_available': True,
                        'camera_nodes': camera_nodes,
                    },
                    'details': {
                        'all_topics': [t for t in topics if 'image' in t.lower() or 'camera' in t.lower()],
                    }
                }
            elif has_topic:
                return {
                    'status': StatusLevel.WARNING,
                    'metrics': {
                        'image_topic': self.image_topic,
                        'image_available': True,
                        'camera_nodes': [],
                    },
                    'details': {'message': 'Topic exists but no camera node found'}
                }
            else:
                return {
                    'status': StatusLevel.WARNING,
                    'metrics': {
                        'image_topic': self.image_topic,
                        'image_available': False,
                        'camera_nodes': camera_nodes,
                    },
                    'details': {'message': 'Topic not found'}
                }
        except Exception as e:
            return {
                'status': StatusLevel.STOPPED,
                'metrics': {
                    'image_topic': self.image_topic,
                    'image_available': False,
                },
                'details': {'error': f'Could not check topics: {e}'}
            }

    def _get_topic_publisher_count(self, topic_name: str) -> int:
        """Get the number of publishers for a topic using ros2 topic info

        Args:
            topic_name: Full topic name

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
            for line in result.stdout.split('\n'):
                if 'Publisher count:' in line:
                    try:
                        count_str = line.split('Publisher count:')[1].strip()
                        return int(count_str)
                    except (ValueError, IndexError):
                        pass

            # Alternative: check for "Publishers:" section
            if 'Publishers:' in result.stdout:
                publishers_section = result.stdout.split('Publishers:')[-1]
                publisher_lines = [l for l in publishers_section.split('\n')
                                     if l.strip() and not l.strip().startswith('---')]
                if len(publisher_lines) > 1:
                    return len(publisher_lines) - 1

            return 0
        except Exception as e:
            logger.debug(f"Failed to get publisher count for {topic_name}: {e}")
            return 0

    def _check_camera_log_data(self) -> Dict[str, Any]:
        """从日志文件检查 Camera 数据质量

        监控:
        - 丢帧 (SDKIncomplete + Queue drops)
        - 帧率异常
        - 网络丢包
        - 处理延迟过高
        """
        from ..camera_log_parser import CameraLogParser

        # 获取阈值配置
        thresholds = self.config.get('sensors', {}).get('thresholds', {}).get('camera', {})
        min_frequency = thresholds.get('min_frequency', 1.5)
        max_frequency = thresholds.get('max_frequency', 2.5)
        max_latency = thresholds.get('max_latency', 500)

        # 创建或获取解析器
        if self._log_parser is None:
            self._log_parser = CameraLogParser(max_history=30)

        # 获取统计
        stats = self._log_parser.get_statistics()

        metrics = {
            'frame_count': stats.frame_count,
            'published_count': stats.published_count,
            'incomplete_count': stats.incomplete_count,
            'queue_dropped': stats.queue_dropped,
            'measured_frequency': stats.frequency,
            'avg_callback_ms': stats.avg_callback_ms,
            'avg_processing_ms': stats.avg_processing_ms,
            'rx_errors': stats.rx_errors,
            'rx_dropped': stats.rx_dropped,
            'time_since_last_report': stats.time_since_last_report,
        }

        details = {
            'thresholds': {
                'min_frequency': min_frequency,
                'max_frequency': max_frequency,
                'max_latency_ms': max_latency
            },
            'issues': []
        }

        status = StatusLevel.OK
        current_time = time.time()

        # 检查是否有数据
        if stats.frame_count == 0:
            status = StatusLevel.CONNECTED
            details['issues'].append('No log data available yet')
            return {
                'status': status,
                'metrics': metrics,
                'details': details
            }

        # 检查频率 (帧率异常检测)
        if stats.frequency > 0:
            if stats.frequency < min_frequency * 0.5:  # 低于 50%
                status = StatusLevel.CRITICAL
                details['issues'].append(
                    f'Severe frame loss: {stats.frequency:.1f} Hz (expected >= {min_frequency} Hz)'
                )
                logger.error(f"Camera: Severe frame loss - {stats.frequency:.1f} Hz < {min_frequency} Hz")

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
                            'incomplete_count': stats.incomplete_count
                        }
                    )
                    self._last_alert_time['frame_loss_critical'] = current_time

            elif stats.frequency < min_frequency:  # 低于阈值
                status = StatusLevel.WARNING
                details['issues'].append(
                    f'Frame loss detected: {stats.frequency:.1f} Hz (expected >= {min_frequency} Hz)'
                )
                logger.warning(f"Camera: Frame loss - {stats.frequency:.1f} Hz < {min_frequency} Hz")

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
                            'incomplete_count': stats.incomplete_count
                        }
                    )
                    self._last_alert_time['frame_loss'] = current_time

            elif stats.frequency > max_frequency * 1.5:  # 高于 150%
                status = get_higher_priority_status(status, StatusLevel.WARNING)
                details['issues'].append(
                    f'Frame rate too high: {stats.frequency:.1f} Hz (expected <= {max_frequency} Hz)'
                )
                logger.warning(f"Camera: Frame rate too high - {stats.frequency:.1f} Hz > {max_frequency} Hz")

        # 检查队列溢出 (处理队列满导致的丢帧)
        if stats.queue_dropped > 0:
            if stats.queue_dropped > stats.frame_count * 0.05:  # 超过 5% 触发严重告警
                status = get_higher_priority_status(status, StatusLevel.CRITICAL)
                details['issues'].append(
                    f'Queue overflow: {stats.queue_dropped} frames dropped due to full processing queue'
                )
                logger.error(f"Camera: Queue overflow - {stats.queue_dropped} frames dropped")

                if current_time - self._last_alert_time.get('queue_overflow', 0) > self._alert_cooldown:
                    self._record_alert(
                        alert_type='queue_overflow',
                        severity='critical',
                        message=f'Queue overflow: {stats.queue_dropped} frames dropped. Increase processing_queue_depth parameter.',
                        metric_value=stats.queue_dropped,
                        threshold=stats.frame_count * 0.05,
                        metadata={
                            'queue_dropped': stats.queue_dropped,
                            'frame_count': stats.frame_count,
                            'recommendation': 'Increase processing_queue_depth parameter'
                        }
                    )
                    self._last_alert_time['queue_overflow'] = current_time
            elif current_time - self._last_alert_time.get('queue_overflow_warning', 0) > self._alert_cooldown:
                # 队列溢出即使少量也值得警告
                status = get_higher_priority_status(status, StatusLevel.WARNING)
                details['issues'].append(
                    f'Queue dropping frames: {stats.queue_dropped} frames dropped'
                )
                logger.warning(f"Camera: Queue dropping - {stats.queue_dropped} frames")

                self._record_alert(
                    alert_type='queue_overflow',
                    severity='warning',
                    message=f'Queue dropping frames: {stats.queue_dropped} frames dropped',
                    metric_value=stats.queue_dropped,
                    threshold=1,
                    metadata={
                        'queue_dropped': stats.queue_dropped,
                        'frame_count': stats.frame_count
                    }
                )
                self._last_alert_time['queue_overflow_warning'] = current_time

        # 检查网络丢帧 (SDKIncomplete)
        incomplete_dropped = stats.incomplete_count
        if incomplete_dropped > stats.frame_count * 0.1:  # 超过 10%
            status = get_higher_priority_status(status, StatusLevel.CRITICAL)
            details['issues'].append(
                f'High frame loss (network): {incomplete_dropped}/{stats.frame_count} frames incomplete'
            )
            logger.error(f"Camera: High network frame loss - {incomplete_dropped}/{stats.frame_count}")

            if current_time - self._last_alert_time.get('high_frame_loss', 0) > self._alert_cooldown:
                self._record_alert(
                    alert_type='high_frame_loss',
                    severity='critical',
                    message=f'High frame loss: {incomplete_dropped}/{stats.frame_count} frames incomplete',
                    metric_value=incomplete_dropped,
                    threshold=stats.frame_count * 0.1,
                    metadata={
                        'incomplete_count': incomplete_dropped,
                        'queue_dropped': stats.queue_dropped,
                        'frame_count': stats.frame_count
                    }
                )
                self._last_alert_time['high_frame_loss'] = current_time

        # 总体丢帧统计 (包括队列和网络丢帧)
        total_dropped = stats.incomplete_count + stats.queue_dropped
        if total_dropped > 0 and stats.queue_dropped == 0:
            # 只有网络丢帧时才显示这个警告 (避免与 queue_overflow 重复)
            status = get_higher_priority_status(status, StatusLevel.WARNING)
            details['issues'].append(
                f'Frame loss detected: {total_dropped}/{stats.frame_count} frames dropped'
            )
            logger.warning(f"Camera: Frame loss - {total_dropped}/{stats.frame_count}")

        # 检查网络丢包
        if stats.rx_errors > 10 or stats.rx_dropped > 10:
            status = get_higher_priority_status(status, StatusLevel.CRITICAL)
            details['issues'].append(
                f'Network issues: rx_errors={stats.rx_errors}, rx_dropped={stats.rx_dropped}'
            )
            logger.error(f"Camera: Network issues - rx_errors={stats.rx_errors}, rx_dropped={stats.rx_dropped}")

        # 检查处理延迟
        if stats.avg_processing_ms > max_latency:
            status = get_higher_priority_status(status, StatusLevel.WARNING)
            details['issues'].append(
                f'High processing latency: {stats.avg_processing_ms:.1f} ms (limit: {max_latency} ms)'
            )
            logger.warning(f"Camera: High processing latency - {stats.avg_processing_ms:.1f} ms")

        # 检查数据是否过期
        if stats.time_since_last_report > 5.0:
            status = get_higher_priority_status(status, StatusLevel.WARNING)
            details['issues'].append(f'No new reports for {stats.time_since_last_report:.1f}s')
            logger.warning(f"Camera: No new reports for {stats.time_since_last_report:.1f}s")

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
            import json
            from ...alerts import get_alert_store, Alert

            alert = Alert(
                sensor='camera',
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
            logger.info(f"Camera alert recorded: ID={alert_id}, type={alert_type}, severity={severity}")
        except Exception as e:
            logger.error(f"Failed to record alert: {e}")

    def get_diagnostic_summary(self) -> Dict[str, Any]:
        """Get summary for dashboard display"""
        if self.last_result is None:
            return {
                'name': 'Camera',
                'status': 'stopped',
                'icon': 'fa-solid fa-camera',
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
            'name': 'Camera',
            'status': status_str,
            'icon': 'fa-solid fa-camera',
            'color': color,
            'value': "Connected" if reachable else "Disconnected",
            'message': self.last_result.message,
        }
