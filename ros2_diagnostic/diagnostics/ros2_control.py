#!/usr/bin/env python3
"""
ROS2 Control Module
Manages starting and stopping ROS2 sensor drivers
"""

import os
import subprocess
import threading
import time
import psutil
from datetime import datetime
from typing import Optional, Dict, Any


class ROS2Controller:
    """Manages ROS2 sensor driver lifecycle with idempotent operations"""

    # Operation cooldown to prevent rapid repeated calls
    OPERATION_COOLDOWN = 2.0  # seconds

    def __init__(self, config: dict):
        self.config = config
        self.ros2_config = config.get('ROS2_CONFIG', {})
        self.ros2_control = config.get('ROS2_CONTROL', {})
        self.log_files = config.get('LOG_FILES', {})

        self.script_path = self.ros2_control.get('script_path') or self.ros2_config.get('launch_script')
        self.repo_root = self.ros2_control.get('repo_root') or os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
        self.log_file_path = self.ros2_control.get('log_file') or self.log_files.get('ros2_control', 'ros2.log')
        self.domain_id = str(self.ros2_control.get('domain_id') or self.ros2_config.get('domain_id', 42))

        self.ros_process: Optional[subprocess.Popen] = None
        self.ros_thread: Optional[threading.Thread] = None
        self._lock = threading.Lock()
        self._log_file = None
        self._status = {
            'running': False,
            'pid': None,
            'message': 'Checking status...'
        }
        # Track last operation time for idempotency
        self._last_start_time = 0.0
        self._last_stop_time = 0.0

    def check_running(self) -> Dict[str, Any]:
        """Check if ROS2 is currently running"""
        try:
            for proc in psutil.process_iter(['pid', 'name', 'cmdline']):
                try:
                    cmdline = proc.info.get('cmdline', [])
                    if cmdline:
                        cmdline_str = ' '.join(cmdline).lower()
                        if ('ros2 launch' in cmdline_str or 'ros2 run' in cmdline_str):
                            if 'web_controller' not in cmdline_str and 'diagnostic' not in cmdline_str:
                                self._status['running'] = True
                                self._status['pid'] = proc.info['pid']
                                self._status['message'] = f'ROS2 is running (PID: {proc.info["pid"]})'
                                return {
                                    'running': True,
                                    'pid': proc.info['pid'],
                                    'message': self._status['message']
                                }
                except (psutil.NoSuchProcess, psutil.AccessDenied):
                    continue

            self._status['running'] = False
            self._status['pid'] = None
            self._status['message'] = 'ROS2 is not running'
            return {
                'running': False,
                'pid': None,
                'message': 'ROS2 is not running'
            }
        except Exception as e:
            self._status['running'] = False
            self._status['pid'] = None
            self._status['message'] = f'Error checking status: {str(e)}'
            return {
                'running': False,
                'pid': None,
                'error': str(e)
            }

    def start(self) -> Dict[str, Any]:
        """Start ROS2 sensor drivers (idempotent operation)"""
        with self._lock:
            current_time = time.time()

            # Idempotency check: cooldown period
            if current_time - self._last_start_time < self.OPERATION_COOLDOWN:
                remaining = round(self.OPERATION_COOLDOWN - (current_time - self._last_start_time), 1)
                return {
                    'success': False,
                    'message': f'Start operation in progress, please wait {remaining}s'
                }

            # Check if already running
            status = self.check_running()
            if status['running']:
                self._last_start_time = current_time
                return {
                    'success': True,  # Return success for idempotency
                    'message': f'ROS2 is already running (PID: {status["pid"]})',
                    'already_running': True,
                    'pid': status['pid']
                }

            try:
                # Mark operation start time
                self._last_start_time = current_time

                # Ensure log directory exists
                os.makedirs(os.path.dirname(self.log_file_path), exist_ok=True)

                # Open log file
                timestamp = datetime.now().strftime('%Y-%m-%d %H:%M:%S')
                self._log_file = open(self.log_file_path, 'w')
                self._log_write(f"Starting ROS2 at {timestamp}")
                self._log_write(f"Script: {self.script_path}")
                self._log_write("=" * 80)

                # Set environment
                env = os.environ.copy()
                env['ROS_DOMAIN_ID'] = self.domain_id

                # Start ROS2 script
                self.ros_process = subprocess.Popen(
                    [self.script_path],
                    cwd=self.repo_root,
                    stdout=self._log_file,
                    stderr=subprocess.STDOUT,
                    text=True,
                    env=env,
                    preexec_fn=os.setsid
                )

                self._status['running'] = True
                self._status['pid'] = self.ros_process.pid

                return {
                    'success': True,
                    'message': f'ROS2 starting (PID: {self.ros_process.pid})',
                    'pid': self.ros_process.pid
                }

            except Exception as e:
                if self._log_file:
                    self._log_write(f"ERROR: {str(e)}")
                    self._log_file.close()
                    self._log_file = None
                self._status['running'] = False
                self._status['pid'] = None
                self._last_start_time = 0  # Reset on error to allow retry
                return {
                    'success': False,
                    'message': f'Failed to start ROS2: {str(e)}'
                }

    def stop(self) -> Dict[str, Any]:
        """Stop ROS2 sensor drivers (idempotent operation)"""
        with self._lock:
            current_time = time.time()

            # Idempotency check: cooldown period
            if current_time - self._last_stop_time < self.OPERATION_COOLDOWN:
                remaining = round(self.OPERATION_COOLDOWN - (current_time - self._last_stop_time), 1)
                return {
                    'success': False,
                    'message': f'Stop operation in progress, please wait {remaining}s'
                }

            # Mark operation start time
            self._last_stop_time = current_time

            killed_count = 0

            try:
                # Kill all ROS2 processes
                for proc in psutil.process_iter(['pid', 'name', 'cmdline']):
                    try:
                        cmdline = proc.info.get('cmdline', [])
                        if cmdline:
                            cmdline_str = ' '.join(cmdline).lower()
                            if ('ros2 launch' in cmdline_str or
                                'ros2 run' in cmdline_str or
                                'ros2-daemon' in cmdline_str or
                                'ros2 bag' in cmdline_str or  # Catch rosbag record processes
                                '_node' in cmdline_str or      # Catch ROS node executables
                                'hesai_ros_driver_node' in cmdline_str or
                                'galaxy_camera' in cmdline_str or
                                'sbg_device' in cmdline_str or
                                'thruster_wifi_node' in cmdline_str or
                                'recorder_node' in cmdline_str or
                                'sensor_compressor' in cmdline_str):
                                if 'web_controller' not in cmdline_str and 'diagnostic' not in cmdline_str:
                                    proc.terminate()
                                    killed_count += 1
                    except (psutil.NoSuchProcess, psutil.AccessDenied):
                        continue

                # Wait for graceful shutdown
                time.sleep(2)

                # Force kill remaining
                for proc in psutil.process_iter(['pid', 'name', 'cmdline']):
                    try:
                        cmdline = proc.info.get('cmdline', [])
                        if cmdline:
                            cmdline_str = ' '.join(cmdline).lower()
                            if ('ros2 launch' in cmdline_str or
                                'ros2 run' in cmdline_str or
                                'ros2-daemon' in cmdline_str or
                                'ros2 bag' in cmdline_str or  # Catch rosbag record processes
                                '_node' in cmdline_str or      # Catch ROS node executables
                                'hesai_ros_driver_node' in cmdline_str or
                                'galaxy_camera' in cmdline_str or
                                'sbg_device' in cmdline_str or
                                'thruster_wifi_node' in cmdline_str or
                                'recorder_node' in cmdline_str or
                                'sensor_compressor' in cmdline_str):
                                if 'web_controller' not in cmdline_str and 'diagnostic' not in cmdline_str:
                                    proc.kill()
                                    killed_count += 1
                    except (psutil.NoSuchProcess, psutil.AccessDenied):
                        continue

                # Close log file
                if self._log_file:
                    timestamp = datetime.now().strftime('%Y-%m-%d %H:%M:%S')
                    self._log_write(f"\n{'=' * 80}")
                    self._log_write(f"ROS2 stopped at {timestamp}")
                    self._log_write(f"Killed {killed_count} process(es)")
                    self._log_file.close()
                    self._log_file = None

                self._status['running'] = False
                self._status['pid'] = None

                if killed_count > 0:
                    self._status['message'] = f'ROS2 stopped (killed {killed_count} process(es))'
                    return {
                        'success': True,
                        'message': f'ROS2 stopped (killed {killed_count} process(es))'
                    }
                else:
                    # Idempotency: no processes found is OK (already stopped)
                    self._status['message'] = 'ROS2 is not running'
                    return {
                        'success': True,  # Return success for idempotency
                        'message': 'ROS2 is not running (already stopped)',
                        'already_stopped': True
                    }

            except Exception as e:
                self._status['message'] = f'Error stopping ROS2: {str(e)}'
                self._last_stop_time = 0  # Reset on error to allow retry
                return {
                    'success': False,
                    'message': f'Error stopping ROS2: {str(e)}'
                }

    def get_logs(self, lines: int = 100) -> list:
        """Get recent log lines"""
        try:
            if os.path.exists(self.log_file_path):
                with open(self.log_file_path, 'r') as f:
                    all_lines = f.readlines()
                    return all_lines[-lines:] if len(all_lines) > lines else all_lines
            return []
        except Exception:
            return []

    def _log_write(self, message: str):
        """Write to log file"""
        if self._log_file:
            self._log_file.write(message + "\n")
            self._log_file.flush()
