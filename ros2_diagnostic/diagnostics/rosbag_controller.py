#!/usr/bin/env python3
"""
Rosbag Controller - Control rosbag recording via remote recorder
Uses ros2 service call to start/stop recording with topics from rosbag_ros2.yaml
"""

import os
import subprocess
import threading
import time
import json
import yaml
from pathlib import Path
from typing import Optional, Dict, Any, List
from datetime import datetime


def _build_ros_env_setup(ros2_config: dict) -> str:
    source_cmd = ros2_config.get("source_cmd", "/opt/ros/humble/setup.bash")
    workspace = ros2_config.get("workspace", "")
    domain_id = ros2_config.get("domain_id", 42)

    parts = [f"source {source_cmd}"]
    if workspace:
        parts.append(f"source {workspace}/install/setup.bash")
    parts.append(f"export ROS_DOMAIN_ID={domain_id}")
    return " && ".join(parts) + " &&"


class RosbagController:
    """
    Controller for rosbag recording via remote recorder ROS2 services.
    Loads topics from rosbag_ros2.yaml and provides start/stop/status functionality.
    Uses subprocess to call ros2 service call for reliable operation.
    """

    def __init__(self, config: dict):
        ros2_config = config.get("ROS2_CONFIG", {})
        rosbag_config = config.get("ROSBAG_CONFIG", {})
        self.project_root = config.get("PROJECT_ROOT", "")

        self.domain_id = ros2_config.get("domain_id", 42)
        self._config_path = rosbag_config.get("config_path")
        self._output_folder = rosbag_config.get("output_folder")
        self._start_service = rosbag_config.get("start_service", "start_recording")
        self._stop_service = rosbag_config.get("stop_service", "stop_recording")
        self._service_timeout = float(rosbag_config.get("service_timeout_sec", 15.0))
        self._ros_env_setup = _build_ros_env_setup(ros2_config)
        self._config = None
        self._topics = []
        self._current_bag_path = None
        self._start_time = None
        self._lock = threading.Lock()

        # Load initial config
        self.load_config()

    def load_config(self) -> bool:
        """Load rosbag configuration from YAML file"""
        try:
            config_path = Path(self._config_path)
            if not config_path.exists():
                print(f"[RosbagController] Config not found: {self._config_path}")
                return False

            with open(config_path, 'r') as f:
                self._config = yaml.safe_load(f)

            self._topics = self._config.get('topics', [])
            print(f"[RosbagController] Loaded {len(self._topics)} topics from config")
            return True
        except Exception as e:
            print(f"[RosbagController] Failed to load config: {e}")
            return False

    def check_status(self) -> Dict[str, Any]:
        """
        Check current recording status
        Returns dict with: is_recording, current_bag, duration, topics_count, topics
        """
        with self._lock:
            # Check if ros2 bag process is running
            is_recording, pid, cmd = self._check_recording_process()

            # Calculate duration if recording
            duration = None
            if is_recording and self._start_time:
                duration = int(time.time() - self._start_time)

            # If process check differs from internal state, update
            if is_recording and not self._current_bag_path:
                # Try to find current bag path from command
                self._current_bag_path = self._extract_bag_path(cmd)
                if self._current_bag_path and not self._start_time:
                    self._start_time = time.time()
            elif not is_recording:
                self._current_bag_path = None
                self._start_time = None

            return {
                'is_recording': is_recording,
                'current_bag': self._current_bag_path,
                'duration': duration,
                'topics_count': len(self._topics),
                'topics': self._topics,
                'config_loaded': self._config is not None,
                'pid': pid
            }

    def start_recording(self, topics: Optional[List[str]] = None) -> Dict[str, Any]:
        """
        Start rosbag recording
        Args:
            topics: Optional list of topics to record (default: use config topics)
        Returns:
            Dict with success, message, and optionally bag_path
        """
        with self._lock:
            # Check if already recording
            is_recording, _, _ = self._check_recording_process()
            if is_recording:
                return {
                    'success': False,
                    'message': 'Already recording',
                    'current_bag': self._current_bag_path
                }

            # Ensure config is loaded
            if not self._config:
                if not self.load_config():
                    return {'success': False, 'message': 'Failed to load configuration'}

            topics_to_record = topics or self._topics
            if not topics_to_record:
                return {'success': False, 'message': 'No topics to record'}

            # Call ROS2 service via subprocess
            result = self._call_start_service(topics_to_record)
            if result.get('success'):
                self._current_bag_path = result.get('bag_path')
                self._start_time = time.time()

            return result

    def stop_recording(self) -> Dict[str, Any]:
        """
        Stop rosbag recording
        Returns:
            Dict with success and message
        """
        with self._lock:
            # Check if recording
            is_recording, _, _ = self._check_recording_process()
            if not is_recording:
                return {'success': False, 'message': 'Not currently recording'}

            # Call ROS2 service via subprocess
            result = self._call_stop_service()
            if result.get('success'):
                self._current_bag_path = None
                self._start_time = None

            return result

    def _check_recording_process(self) -> tuple[bool, Optional[int], Optional[str]]:
        """
        Check if ros2 bag record process is running
        Returns: (is_running, pid, command_line)
        """
        try:
            # Use pgrep to find ros2 bag record processes
            result = subprocess.run(
                ['pgrep', '-af', 'ros2 bag record'],
                capture_output=True,
                text=True,
                timeout=2
            )

            if result.returncode == 0 and result.stdout.strip():
                # Parse output: "pid command"
                lines = result.stdout.strip().split('\n')
                for line in lines:
                    parts = line.split(None, 1)
                    if len(parts) >= 2:
                        pid = int(parts[0])
                        cmd = parts[1]
                        # Make sure it's actually recording
                        if 'ros2 bag record' in cmd:
                            return True, pid, cmd
                return True, None, result.stdout.split('\n')[0]
            return False, None, None
        except (subprocess.TimeoutExpired, FileNotFoundError, ValueError):
            return False, None, None

    def _extract_bag_path(self, cmd: Optional[str]) -> Optional[str]:
        """Extract bag path from ros2 bag command line"""
        if not cmd:
            return None

        # Look for -o flag in command
        parts = cmd.split()
        for i, part in enumerate(parts):
            if part == '-o' and i + 1 < len(parts):
                bag_path = parts[i + 1]
                # Expand and shorten path
                expanded = os.path.expanduser(bag_path)
                if self.project_root and expanded.startswith(self.project_root):
                    expanded = expanded.replace(self.project_root, '~')
                return expanded
        return None

    def _call_start_service(self, topics: List[str]) -> Dict[str, Any]:
        """Call start_recording service using ros2 service call"""
        try:
            # Format topics list for YAML - use flow style for compact array
            # Result format: topics: [/topic1, /topic2, ...]
            topics_yaml = yaml.dump({'topics': topics}, default_flow_style=True, sort_keys=False).strip()

            # Build ros2 service call command
            cmd = [
                'bash', '-c',
                f'{self._ros_env_setup} ros2 service call {self._start_service} tuc_interfaces/srv/StartRecording "{topics_yaml}"'
            ]

            print(f"[RosbagController] Calling start_recording with {len(topics)} topics")

            result = subprocess.run(
                cmd,
                capture_output=True,
                text=True,
                timeout=self._service_timeout
            )

            if result.returncode != 0:
                return {
                    'success': False,
                    'message': f'Service call failed: {result.stderr}'
                }

            # Parse response
            # Expected format:
            # requester: making request: tuc_interfaces.srv.StartRecording_Request(...)
            # response:
            # tuc_interfaces.srv.StartRecording_Response(success=True, message='...')

            output = result.stdout
            if 'success=True' in output or 'success = True' in output:
                bag_path = self._parse_bag_path(output)
                return {
                    'success': True,
                    'message': self._parse_message(output),
                    'bag_path': bag_path
                }
            elif 'success=False' in output or 'success = False' in output:
                return {
                    'success': False,
                    'message': self._parse_message(output)
                }
            else:
                return {
                    'success': False,
                    'message': f'Unexpected response: {output}'
                }

        except subprocess.TimeoutExpired:
            return {
                'success': False,
                'message': 'Service call timed out'
            }
        except Exception as e:
            return {
                'success': False,
                'message': f'Service call failed: {e}'
            }

    def _call_stop_service(self) -> Dict[str, Any]:
        """Call stop_recording service using ros2 service call"""
        try:
            # Build ros2 service call command
            cmd = [
                'bash', '-c',
                f'{self._ros_env_setup} ros2 service call {self._stop_service} std_srvs/srv/Trigger "{{}}"'
            ]

            print(f"[RosbagController] Calling stop_recording")

            result = subprocess.run(
                cmd,
                capture_output=True,
                text=True,
                timeout=self._service_timeout
            )

            if result.returncode != 0:
                return {
                    'success': False,
                    'message': f'Service call failed: {result.stderr}'
                }

            # Parse response
            output = result.stdout
            if 'success=True' in output or 'success = True' in output:
                return {
                    'success': True,
                    'message': self._parse_message(output) or 'Recording stopped'
                }
            elif 'success=False' in output or 'success = False' in output:
                return {
                    'success': False,
                    'message': self._parse_message(output) or 'Stop failed'
                }
            else:
                return {
                    'success': False,
                    'message': f'Unexpected response: {output}'
                }

        except subprocess.TimeoutExpired:
            return {
                'success': False,
                'message': 'Service call timed out'
            }
        except Exception as e:
            return {
                'success': False,
                'message': f'Service call failed: {e}'
            }

    def _parse_bag_path(self, output: str) -> Optional[str]:
        """Parse bag path from service response message"""
        # Message format: "Recording started at /path/to/bag"
        for line in output.split('\n'):
            if 'Recording started at' in line:
                parts = line.split(' at ')
                if len(parts) > 1:
                    path = parts[-1].strip()
                    # Shorten path for display
                    if self.project_root and path.startswith(self.project_root):
                        path = path.replace(self.project_root, '~')
                    return path
        return None

    def _parse_message(self, output: str) -> Optional[str]:
        """Parse message from service response"""
        for line in output.split('\n'):
            line = line.strip()
            if "message='" in line:
                # Format: message='...'
                start = line.find("message='") + 9
                end = line.rfind("'")
                if start > 9 and end > start:
                    return line[start:end]
            elif 'message=' in line:
                # Format: message=...
                parts = line.split('message=', 1)
                if len(parts) > 1:
                    msg = parts[1].strip()
                    # Remove trailing quote if present
                    return msg.rstrip("'").rstrip('"')
        return None

    def shutdown(self):
        """Cleanup resources"""
        pass


# Singleton instance
_rosbag_controller_instance: Optional[RosbagController] = None
_rosbag_controller_lock = threading.Lock()


def get_rosbag_controller(config: dict) -> RosbagController:
    """Get or create the singleton RosbagController instance"""
    global _rosbag_controller_instance

    with _rosbag_controller_lock:
        if _rosbag_controller_instance is None:
            _rosbag_controller_instance = RosbagController(config)
        return _rosbag_controller_instance


def shutdown_rosbag_controller():
    """Shutdown the rosbag controller"""
    global _rosbag_controller_instance

    with _rosbag_controller_lock:
        if _rosbag_controller_instance:
            _rosbag_controller_instance.shutdown()
            _rosbag_controller_instance = None
