#!/usr/bin/env python3
"""
ROS2 Monitor
Monitors ROS2 nodes, topics, and overall system health
Uses rclpy for lightweight monitoring when available
"""

import os
import subprocess
import threading
import time
from collections import deque
from datetime import datetime, timedelta
from typing import Dict, List, Optional, Any

import psutil

from .base import BaseDiagnostic, DiagnosticResult, StatusLevel
from .ros2_helper import get_ros2_helper, RCLPY_AVAILABLE


class ROS2Monitor(BaseDiagnostic):
    """Monitor ROS2 nodes, topics, and overall system health"""

    def __init__(self, config: dict):
        super().__init__("ros2", config)
        self.ros2_config = config.get('ROS2_CONFIG', {})
        self.expected_nodes = config.get('EXPECTED_NODES', [])
        self.ignored_nodes = config.get('IGNORED_NODES', [])
        self.sensor_nodes = config.get('SENSOR_NODES', {})
        self.ros2_topics = config.get('ROS2_TOPICS', {})
        self.enable_topic_details = config.get('ENABLE_TOPIC_DETAILS', True)
        self.enable_rclpy_monitoring = config.get('ENABLE_RCLPY_MONITORING', True)
        self.fallback_to_shell = config.get('FALLBACK_TO_SHELL', True)
        self.domain_id = self.ros2_config.get('domain_id', 42)

        # Frequency tracking
        self._topic_timestamps: Dict[str, deque] = {}
        self._topic_lock = threading.Lock()
        self._max_history = 100  # Keep last 100 timestamps per topic

        # ROS2 Helper (rclpy-based monitoring)
        self._helper = None
        self._use_rclpy = RCLPY_AVAILABLE

        # Track which topics have frequency monitoring enabled
        self._monitored_topics: List[str] = []

    def check(self) -> DiagnosticResult:
        """Perform ROS2 system check"""
        metrics = {}
        details = {}

        # Check if ROS2 is running
        is_running, ros_process = self._check_ros2_running()
        metrics['running'] = is_running

        if not is_running:
            self.last_check = datetime.now()
            self.last_result = DiagnosticResult(
                name=self.name,
                status=StatusLevel.CRITICAL,
                message="ROS2 is not running",
                timestamp=self.last_check,
                metrics=metrics,
                details=details
            )
            return self.last_result

        # Check nodes
        nodes_result = self._check_nodes()
        metrics['nodes'] = nodes_result['metrics']
        details['nodes'] = nodes_result['details']
        overall_status = nodes_result['status']

        # Check topics
        topics_result = self._check_topics()
        metrics['topics'] = topics_result['metrics']
        details['topics'] = topics_result['details']
        overall_status = max(overall_status, topics_result['status'],
                            key=lambda s: [StatusLevel.UNKNOWN, StatusLevel.OK,
                                         StatusLevel.WARNING, StatusLevel.CRITICAL].index(s))

        # Check topic frequencies
        freq_result = self._check_frequencies()
        metrics['frequencies'] = freq_result['metrics']
        overall_status = max(overall_status, freq_result['status'],
                            key=lambda s: [StatusLevel.UNKNOWN, StatusLevel.OK,
                                         StatusLevel.WARNING, StatusLevel.CRITICAL].index(s))

        # Get daemon info
        daemon_info = self._get_daemon_info()
        details['daemon'] = daemon_info

        self.last_check = datetime.now()
        self.check_count += 1

        # Determine overall message
        running_nodes = metrics['nodes'].get('running_count', 0)
        total_expected = len(self.expected_nodes)

        if overall_status == StatusLevel.CRITICAL:
            message = "ROS2 system critical - nodes missing or not responding"
        elif overall_status == StatusLevel.WARNING:
            message = f"ROS2 running with warnings ({running_nodes}/{total_expected} nodes)"
        else:
            message = f"ROS2 system healthy ({running_nodes} nodes active)"

        self.last_result = DiagnosticResult(
            name=self.name,
            status=overall_status,
            message=message,
            timestamp=self.last_check,
            metrics=metrics,
            details=details
        )

        return self.last_result

    def _check_ros2_running(self) -> tuple[bool, Optional[dict]]:
        """Check if any ROS2 processes are running"""
        try:
            for proc in psutil.process_iter(['pid', 'name', 'cmdline']):
                try:
                    cmdline = proc.info.get('cmdline', [])
                    if cmdline:
                        cmdline_str = ' '.join(cmdline).lower()
                        # Check for ROS2 processes
                        if ('ros2 launch' in cmdline_str or
                            'ros2 run' in cmdline_str or
                            'ros2-daemon' in cmdline_str or
                            any(node in cmdline_str for node in ['sbg_device', 'galaxy_camera', 'hesai'])):
                            # Exclude web controller
                            if 'web_controller' not in cmdline_str and 'diagnostic' not in cmdline_str:
                                return True, {
                                    'pid': proc.info['pid'],
                                    'name': proc.info['name'],
                                    'cmdline': ' '.join(cmdline)[:100]
                                }
                except (psutil.NoSuchProcess, psutil.AccessDenied, psutil.ZombieProcess):
                    continue
            return False, None
        except Exception:
            return False, None

    def _check_nodes(self) -> Dict[str, Any]:
        """Check ROS2 nodes"""
        # Use rclpy if available, otherwise fallback to shell command
        if self._use_rclpy:
            node_list = self._get_nodes_rclpy()
        else:
            nodes = self._ros2_cmd('node list')
            if nodes is None:
                return {
                    'status': StatusLevel.WARNING,
                    'metrics': {'all': [], 'running_count': 0},
                    'details': {'error': 'Failed to get node list'}
                }
            node_list = [n.strip() for n in nodes.strip().split('\n') if n.strip()]

        if not node_list:
            return {
                'status': StatusLevel.WARNING,
                'metrics': {'all': [], 'running_count': 0},
                'details': {'error': 'No nodes found'}
            }

        # Filter out ignored nodes
        filtered_nodes = [n for n in node_list if not any(ignored in n for ignored in self.ignored_nodes)]

        # Check expected nodes
        running_expected = []
        missing_expected = []

        for expected in self.expected_nodes:
            if any(expected in node for node in node_list):
                running_expected.append(expected)
            else:
                missing_expected.append(expected)

        # Determine status
        status = StatusLevel.OK
        if missing_expected:
            if len(running_expected) == 0:
                status = StatusLevel.CRITICAL
            else:
                status = StatusLevel.WARNING

        # Get detailed info for running nodes (only if topic details enabled)
        node_details = []
        if self.enable_topic_details:
            for node in filtered_nodes[:20]:  # Limit to first 20 nodes
                detail = self._get_node_info(node)
                if detail:
                    node_details.append(detail)

        return {
            'status': status,
            'metrics': {
                'all': filtered_nodes,
                'running_count': len(filtered_nodes),
                'expected_running': running_expected,
                'expected_missing': missing_expected,
            },
            'details': {
                'node_details': node_details if self.enable_topic_details else [],
                'total_expected': len(self.expected_nodes),
                'using_rclpy': self._use_rclpy,
            }
        }

    def _get_nodes_rclpy(self) -> List[str]:
        """Get node names using rclpy (no shell commands)"""
        try:
            helper = self._get_helper()
            if helper and helper.is_ready():
                return helper.get_node_names()
        except Exception:
            pass
        return []

    def _check_topics(self) -> Dict[str, Any]:
        """Check ROS2 topics"""
        # Use rclpy if available, otherwise fallback to shell command
        if self._use_rclpy:
            topic_list = self._get_topics_rclpy()
        else:
            topics_output = self._ros2_cmd('topic list')
            if topics_output is None:
                return {
                    'status': StatusLevel.WARNING,
                    'metrics': {'all': [], 'count': 0},
                    'details': {'error': 'Failed to get topic list'}
                }
            topic_list = [t.strip() for t in topics_output.strip().split('\n') if t.strip()]

        if not topic_list:
            return {
                'status': StatusLevel.WARNING,
                'metrics': {'all': [], 'count': 0},
                'details': {'error': 'No topics found'}
            }

        # Get topic info for important topics (only if enabled)
        topic_details = {}
        if self.enable_topic_details:
            for category, topics in self.ros2_topics.items():
                for topic_name, topic_path in topics.items():
                    if topic_path in topic_list:
                        info = self._get_topic_info(topic_path)
                        if info:
                            topic_details[topic_path] = info

        return {
            'status': StatusLevel.OK,
            'metrics': {
                'all': topic_list,
                'count': len(topic_list),
                'important': topic_details,
            },
            'details': {
                'by_category': self.ros2_topics if self.enable_topic_details else {},
                'using_rclpy': self._use_rclpy,
            }
        }

    def _get_topics_rclpy(self) -> List[str]:
        """Get topic names using rclpy (no shell commands)"""
        try:
            helper = self._get_helper()
            if helper and helper.is_ready():
                return helper.get_topic_names()
        except Exception:
            pass
        return []

    def _check_frequencies(self) -> Dict[str, Any]:
        """Check topic frequencies using rclpy subscriptions or fallback to shell commands"""
        frequencies = {}
        status = StatusLevel.OK

        # Skip frequency checking if topic details are disabled
        if not self.enable_topic_details:
            return {
                'status': StatusLevel.UNKNOWN,
                'metrics': {'disabled': True, 'message': 'Frequency checking disabled'},
            }

        # Try rclpy-based monitoring first
        if self._use_rclpy and self.enable_rclpy_monitoring:
            helper = self._get_helper()
            if helper and helper.is_ready():
                # Ensure all expected topics have monitoring enabled
                self._ensure_frequency_monitoring(helper)

                # Get frequencies from all monitored topics
                all_freqs = helper.get_all_frequencies()
                for topic, data in all_freqs.items():
                    frequencies[topic] = data

                # Check frequencies against expected values
                expected_freqs = self._get_expected_frequencies()
                for topic, expected in expected_freqs.items():
                    if topic in frequencies:
                        measured = frequencies[topic]['frequency']
                        ratio = measured / expected if expected > 0 else 0
                        frequencies[topic]['expected'] = expected
                        frequencies[topic]['ratio'] = ratio

                        # Determine status based on frequency
                        if measured < expected * 0.7:  # 70% threshold
                            status = StatusLevel.CRITICAL
                        elif measured < expected * 0.9:  # 90% threshold
                            status = max(status, StatusLevel.WARNING,
                                       key=lambda s: [StatusLevel.OK, StatusLevel.WARNING,
                                                    StatusLevel.CRITICAL].index(s))

                return {
                    'status': status,
                    'metrics': frequencies,
                    'method': 'rclpy',
                }

        # Fallback to shell commands if rclpy failed or is disabled
        if self.fallback_to_shell:
            return self._check_frequencies_shell()

        return {
            'status': StatusLevel.UNKNOWN,
            'metrics': {'error': 'Frequency monitoring unavailable'},
        }

    def _ensure_frequency_monitoring(self, helper) -> None:
        """Ensure frequency monitoring is enabled for all expected topics"""
        expected_freqs = self._get_expected_frequencies()

        for topic in expected_freqs.keys():
            if topic not in self._monitored_topics:
                # Get topic type
                topic_info = helper.get_topic_info(topic)
                if topic_info and topic_info.get('types'):
                    msg_type = topic_info['types'][0]
                    if helper.start_frequency_monitor(topic, msg_type):
                        self._monitored_topics.append(topic)

    def _get_expected_frequencies(self) -> Dict[str, float]:
        """Get expected frequencies for topics based on config"""
        # Map topic names to expected frequencies (Hz)
        freq_map = {
            'navi_lidar_points': 10.0,
            'camera_image': 2.0,
            'imu_data': 25.0,
        }

        expected = {}
        # Try to get topics from config
        navi_lidar_points = self.ros2_topics.get('navi_lidar', {}).get('points', '/navi_lidar/points')
        camera_image = self.ros2_topics.get('camera', {}).get('image_raw', '/image_raw')
        imu_data = self.ros2_topics.get('imu', {}).get('data', '/imu/data')

        expected[navi_lidar_points] = freq_map.get('navi_lidar_points', 10.0)
        expected[camera_image] = freq_map.get('camera_image', 2.0)
        expected[imu_data] = freq_map.get('imu_data', 25.0)

        return expected

    def _check_frequencies_shell(self) -> Dict[str, Any]:
        """Check topic frequencies using shell commands (fallback method)"""
        frequencies = {}
        status = StatusLevel.OK

        expected_freqs = self._get_expected_frequencies()

        for topic, expected in expected_freqs.items():
            # Quick frequency check using ros2 topic hz
            hz_output = self._ros2_cmd(f'topic hz {topic} --window 20', timeout=5)

            if hz_output:
                # Parse average rate from output
                try:
                    for line in hz_output.split('\n'):
                        if 'average rate' in line.lower():
                            freq_str = line.split(':')[-1].strip()
                            measured_hz = float(freq_str.split()[0])

                            frequencies[topic] = {
                                'measured': measured_hz,
                                'expected': expected,
                                'ratio': measured_hz / expected if expected > 0 else 0,
                            }

                            # Check if frequency is acceptable
                            if measured_hz < expected * 0.7:
                                status = StatusLevel.CRITICAL
                            elif measured_hz < expected * 0.9:
                                status = max(status, StatusLevel.WARNING,
                                           key=lambda s: [StatusLevel.OK, StatusLevel.WARNING,
                                                        StatusLevel.CRITICAL].index(s))
                            break
                except (ValueError, IndexError):
                    frequencies[topic] = {'error': 'Could not parse frequency'}
            else:
                frequencies[topic] = {'error': 'No response from topic'}

        return {
            'status': status,
            'metrics': frequencies,
            'method': 'shell',
        }

    def _get_node_info(self, node_name: str) -> Optional[Dict[str, Any]]:
        """Get detailed info about a node"""
        info_output = self._ros2_cmd(f'node info {node_name}')
        if not info_output:
            return None

        info = {
            'name': node_name,
            'subscribers': [],
            'publishers': [],
            'services': [],
            'actions': [],
        }

        for line in info_output.strip().split('\n'):
            line = line.strip()
            if line.startswith('Subscribers:') or line.startswith('Subscribers:'):
                continue
            elif line.startswith('Publishers:') or line.startswith('Publishers:'):
                continue
            elif line.startswith('Services:') or line.startswith('Services:'):
                continue
            elif line.startswith('Action Servers:') or line.startswith('Action Servers:'):
                continue
            elif line.startswith('  '):
                topic = line.strip()
                if line.count(' ') >= 2:
                    # This is a topic/service
                    if topic:
                        if 'Subscribers' in info_output.split(line)[0]:
                            info['subscribers'].append(topic)
                        elif 'Publishers' in info_output.split(line)[0]:
                            info['publishers'].append(topic)
                        elif 'Services' in info_output.split(line)[0]:
                            info['services'].append(topic)

        return info

    def _get_topic_info(self, topic_name: str) -> Optional[Dict[str, Any]]:
        """Get detailed info about a topic"""
        # Use rclpy if available
        if self._use_rclpy:
            try:
                helper = self._get_helper()
                if helper and helper.is_ready():
                    info = helper.get_topic_info(topic_name)
                    if info and info.get('exists') and info.get('types'):
                        return {
                            'name': topic_name,
                            'type': info['types'][0] if info['types'] else 'unknown',
                            'types': info.get('types', []),
                        }
            except Exception:
                pass

        # Fallback to shell command
        info_output = self._ros2_cmd(f'topic info {topic_name}')
        if not info_output:
            return None

        info = {'name': topic_name}

        for line in info_output.strip().split('\n'):
            line = line.strip()
            if 'Subscription count:' in line:
                info['subscription_count'] = int(line.split(':')[-1].strip())
            elif 'Publisher count:' in line:
                info['publisher_count'] = int(line.split(':')[-1].strip())
            elif 'Type:' in line:
                info['type'] = line.split(':', 1)[-1].strip()

        return info

    def _get_daemon_info(self) -> Dict[str, Any]:
        """Get ROS2 daemon information"""
        try:
            # Check if rmw daemon is running
            result = subprocess.run(
                ['ps', 'aux'],
                capture_output=True,
                text=True,
                timeout=2
            )

            daemon_running = 'rmw' in result.stdout.lower() or 'ros2' in result.stdout.lower()

            return {
                'running': daemon_running,
                'domain_id': self.domain_id,
                'using_rclpy': self._use_rclpy,
            }
        except Exception:
            return {
                'running': False,
                'domain_id': self.domain_id,
                'using_rclpy': self._use_rclpy,
            }

    def _get_helper(self):
        """Get or create the ROS2Helper instance"""
        if self._helper is None:
            self._helper = get_ros2_helper(self.domain_id)
        return self._helper

    def check_sensor_nodes(self) -> Dict[str, Dict[str, Any]]:
        """
        Check sensor-specific ROS nodes using hierarchical approach
        Returns dict with sensor names as keys and their node status as values
        """
        result = {}

        # Get all running nodes
        if self._use_rclpy:
            all_nodes = self._get_nodes_rclpy()
        else:
            nodes = self._ros2_cmd('node list')
            all_nodes = [n.strip() for n in nodes.strip().split('\n') if n.strip()] if nodes else []

        # Filter out ignored nodes
        filtered_nodes = [n for n in all_nodes if not any(ignored in n for ignored in self.ignored_nodes)]

        # Check each sensor's expected nodes
        for sensor_name, expected_nodes in self.sensor_nodes.items():
            found = []
            missing = []

            for expected_node in expected_nodes:
                if any(expected_node in node for node in filtered_nodes):
                    found.append(expected_node)
                else:
                    missing.append(expected_node)

            result[sensor_name] = {
                'level2_status': 'ok' if found and not missing else 'critical' if not found else 'warning',
                'expected_nodes': expected_nodes,
                'found_nodes': found,
                'missing_nodes': missing,
            }

        return result

    def check_sensor_topics(self) -> Dict[str, Dict[str, Any]]:
        """
        Check sensor-specific ROS topics
        Returns dict with sensor names as keys and their topic status as values
        """
        result = {}

        # Get all running topics
        if self._use_rclpy:
            all_topics = self._get_topics_rclpy()
        else:
            topics_output = self._ros2_cmd('topic list')
            all_topics = [t.strip() for t in topics_output.strip().split('\n') if t.strip()] if topics_output else []

        # Check each sensor's expected topics
        for sensor_name, topics in self.ros2_topics.items():
            found = []
            missing = []

            for topic_key, topic_path in topics.items():
                if topic_path in all_topics:
                    found.append(topic_path)
                else:
                    missing.append(topic_path)

            result[sensor_name] = {
                'level3_status': 'ok' if found and not missing else 'warning' if found else 'critical',
                'all_topics': topics,
                'found_topics': found,
                'missing_topics': missing,
            }

        return result

    def _ros2_cmd(self, cmd: str, timeout: int = 10) -> Optional[str]:
        """Execute a ROS2 command"""
        bash_script = f"""
        source {self.ros2_config.get('source_cmd', '/opt/ros/humble/setup.bash')}
        export ROS_DOMAIN_ID={self.domain_id}
        ros2 {cmd}
        """

        try:
            result = subprocess.run(
                ['bash', '-c', bash_script],
                capture_output=True,
                text=True,
                timeout=timeout
            )

            if result.returncode == 0:
                return result.stdout
            else:
                return None
        except subprocess.TimeoutExpired:
            return None
        except Exception:
            return None

    def record_topic_timestamp(self, topic: str, timestamp: float):
        """Record a topic message timestamp for frequency calculation"""
        with self._topic_lock:
            if topic not in self._topic_timestamps:
                self._topic_timestamps[topic] = deque(maxlen=self._max_history)
            self._topic_timestamps[topic].append(timestamp)

    def calculate_frequency(self, topic: str, window_seconds: float = 5.0) -> Optional[float]:
        """Calculate frequency from recorded timestamps"""
        with self._topic_lock:
            if topic not in self._topic_timestamps:
                return None

            timestamps = list(self._topic_timestamps[topic])
            if len(timestamps) < 2:
                return None

            # Filter to last N seconds
            now = time.time()
            cutoff = now - window_seconds
            recent = [t for t in timestamps if t > cutoff]

            if len(recent) < 2:
                return None

            # Calculate frequency
            duration = recent[-1] - recent[0]
            if duration > 0:
                return (len(recent) - 1) / duration
            return None

    def get_topic_message(
        self,
        topic: str,
        msg_type: Optional[str] = None,
        timeout: int = 5
    ) -> Optional[Dict[str, Any]]:
        """Get a single message from a topic"""
        bash_script = f"""
        source {self.ros2_config.get('source_cmd', '/opt/ros/humble/setup.bash')}
        export ROS_DOMAIN_ID={self.domain_id}
        timeout {timeout} ros2 topic echo {topic} --once
        """

        try:
            result = subprocess.run(
                ['bash', '-c', bash_script],
                capture_output=True,
                text=True,
                timeout=timeout + 2
            )

            if result.returncode == 0 and result.stdout.strip():
                return {
                    'topic': topic,
                    'message': result.stdout.strip(),
                }
            return None
        except (subprocess.TimeoutExpired, Exception):
            return None

    def get_system_snapshot(self) -> Dict[str, Any]:
        """Get quick snapshot of ROS2 system"""
        is_running, proc = self._check_ros2_running()

        return {
            'timestamp': datetime.now().isoformat(),
            'running': is_running,
            'domain_id': self.domain_id,
            'process': proc,
        }

    def is_system_running(self) -> bool:
        """Quick check if ROS2 system is running (for sensor diagnostics)"""
        is_running, _ = self._check_ros2_running()
        return is_running
