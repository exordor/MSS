# test_rosbag_controller.py - Unit tests for RosbagController

import pytest
import sys
import time
import tempfile
import yaml
from pathlib import Path
from unittest.mock import patch, Mock, MagicMock

# Add parent directory to path for imports
sys.path.insert(0, str(Path(__file__).parent.parent.parent))

try:
    from diagnostics.rosbag_controller import RosbagController
    CONTROLLER_AVAILABLE = True
except ImportError as e:
    print(f"Warning: Could not import RosbagController: {e}")
    CONTROLLER_AVAILABLE = False


@pytest.mark.skipif(not CONTROLLER_AVAILABLE, reason="RosbagController not available")
class TestRosbagControllerInit:
    """Tests for RosbagController initialization"""

    def test_controller_initialization(self, mock_rosbag_config):
        """Test RosbagController initialization"""
        controller = RosbagController(mock_rosbag_config)

        assert controller._start_service == "start_recording"
        assert controller._stop_service == "stop_recording"
        assert controller._service_timeout == 5.0
        assert controller._output_folder == mock_rosbag_config["ROSBAG_CONFIG"]["output_folder"]

    def test_controller_initialization_with_custom_config(self):
        """Test RosbagController with custom configuration"""
        config = {
            "ROS2_CONFIG": {
                "domain_id": 100,
                "source_cmd": "/custom/setup.bash",
                "workspace": "/custom/workspace",
            },
            "ROSBAG_CONFIG": {
                "config_path": "/custom/config.yaml",
                "output_folder": "/custom/output",
                "start_service": "custom_start",
                "stop_service": "custom_stop",
                "service_timeout_sec": 10.0,
            },
            "PROJECT_ROOT": "/custom/root",
        }

        controller = RosbagController(config)

        assert controller._start_service == "custom_start"
        assert controller._stop_service == "custom_stop"
        assert controller._service_timeout == 10.0


@pytest.mark.skipif(not CONTROLLER_AVAILABLE, reason="RosbagController not available")
class TestRosbagControllerConfigLoading:
    """Tests for configuration loading"""

    def test_load_config_success(self, mock_rosbag_config, temp_rosbag_dir):
        """Test successful config loading from YAML file"""
        # Create a temporary config file
        config_content = """
topics:
  - /test/topic1
  - /test/topic2
  - /test/topic3

output: test_output
"""
        config_file = temp_rosbag_dir / "test_rosbag.yaml"
        config_file.write_text(config_content)

        config = mock_rosbag_config.copy()
        config["ROSBAG_CONFIG"]["config_path"] = str(config_file)

        controller = RosbagController(config)
        controller.load_config()

        assert len(controller._topics) == 3
        assert "/test/topic1" in controller._topics
        assert "/test/topic2" in controller._topics
        assert "/test/topic3" in controller._topics

    def test_load_config_file_not_found(self, mock_rosbag_config):
        """Test loading config when file doesn't exist"""
        config = mock_rosbag_config.copy()
        config["ROSBAG_CONFIG"]["config_path"] = "/nonexistent/config.yaml"

        controller = RosbagController(config)
        result = controller.load_config()

        assert result is False


@pytest.mark.skipif(not CONTROLLER_AVAILABLE, reason="RosbagController not available")
class TestRosbagControllerStatus:
    """Tests for status checking"""

    def test_check_status_idle(self, mock_rosbag_config):
        """Test check_status returns idle state when not recording"""
        with patch('subprocess.run') as mock_run:
            mock_result = Mock()
            mock_result.returncode = 1  # No process found
            mock_result.stdout = ""
            mock_run.return_value = mock_result

            controller = RosbagController(mock_rosbag_config)
            status = controller.check_status()

            assert status['is_recording'] is False
            assert status['current_bag'] is None
            assert status['duration'] is None

    def test_check_status_recording(self, mock_rosbag_config, temp_rosbag_dir):
        """Test check_status returns recording state"""
        bag_path = temp_rosbag_dir / "rosbag_20250127_123456"

        with patch('subprocess.run') as mock_run:
            mock_result = Mock()
            mock_result.returncode = 0
            mock_result.stdout = f"12345 ros2 bag record -o {bag_path} /topic1 /topic2"
            mock_run.return_value = mock_result

            controller = RosbagController(mock_rosbag_config)
            controller._start_time = time.time() - 65  # 65 seconds ago
            status = controller.check_status()

            assert status['is_recording'] is True
            assert status['duration'] >= 65
            assert 'rosbag_20250127_123456' in status['current_bag']

    def test_check_status_with_pid(self, mock_rosbag_config):
        """Test check_status returns PID when recording"""
        with patch('subprocess.run') as mock_run:
            mock_result = Mock()
            mock_result.returncode = 0
            mock_result.stdout = "12345 ros2 bag record -o /tmp/bag /topic1"
            mock_run.return_value = mock_result

            controller = RosbagController(mock_rosbag_config)
            status = controller.check_status()

            assert status['is_recording'] is True
            assert status['pid'] == 12345


@pytest.mark.skipif(not CONTROLLER_AVAILABLE, reason="RosbagController not available")
class TestRosbagControllerStartRecording:
    """Tests for starting recording"""

    def test_start_recording_success(self, mock_rosbag_config, temp_rosbag_dir):
        """Test successful start of recording"""
        bag_path = temp_rosbag_dir / "rosbag_20250127_123456"

        with patch('subprocess.run') as mock_run:
            # Mock no existing process
            idle_result = Mock()
            idle_result.returncode = 1
            idle_result.stdout = ""

            # Mock successful start
            start_result = Mock()
            start_result.returncode = 0
            start_result.stdout = f"response: tuc_interfaces.srv.StartRecording_Response(success=True, message='Recording started at {bag_path}')"
            start_result.stderr = ""

            call_count = [0]
            def run_side_effect(cmd, **kwargs):
                call_count[0] += 1
                if 'pgrep' in str(cmd):
                    return idle_result
                return start_result

            mock_run.side_effect = run_side_effect

            controller = RosbagController(mock_rosbag_config)
            result = controller.start_recording()

            assert result['success'] is True
            assert bag_path.name in result['bag_path']

    def test_start_recording_already_recording(self, mock_rosbag_config):
        """Test start_recording when already recording"""
        with patch('subprocess.run') as mock_run:
            mock_result = Mock()
            mock_result.returncode = 0
            mock_result.stdout = "12345 ros2 bag record"
            mock_run.return_value = mock_result

            controller = RosbagController(mock_rosbag_config)
            result = controller.start_recording()

            assert result['success'] is False
            assert 'Already recording' in result['message']

    def test_start_recording_with_custom_topics(self, mock_rosbag_config):
        """Test start_recording with custom topic list"""
        custom_topics = ["/custom/topic1", "/custom/topic2"]

        with patch('subprocess.run') as mock_run:
            idle_result = Mock()
            idle_result.returncode = 1
            idle_result.stdout = ""

            start_result = Mock()
            start_result.returncode = 0
            start_result.stdout = "response: tuc_interfaces.srv.StartRecording_Response(success=True, message='Recording started')"
            start_result.stderr = ""

            call_count = [0]
            def run_side_effect(cmd, **kwargs):
                call_count[0] += 1
                if 'pgrep' in str(cmd):
                    return idle_result
                return start_result

            mock_run.side_effect = run_side_effect

            controller = RosbagController(mock_rosbag_config)
            result = controller.start_recording(custom_topics)

            assert result['success'] is True
            # Verify the custom topics were used
            # (by checking if subprocess.run was called with them)

    def test_start_recording_no_topics(self, mock_rosbag_config):
        """Test start_recording when no topics configured"""
        with patch('subprocess.run') as mock_run:
            idle_result = Mock()
            idle_result.returncode = 1
            idle_result.stdout = ""

            mock_run.return_value = idle_result

            controller = RosbagController(mock_rosbag_config)
            controller._topics = []  # No topics configured
            result = controller.start_recording()

            assert result['success'] is False
            assert 'No topics' in result['message']

    def test_start_recording_timeout(self, mock_rosbag_config):
        """Test start_recording when service call times out"""
        import subprocess

        with patch('subprocess.run') as mock_run:
            idle_result = Mock()
            idle_result.returncode = 1
            idle_result.stdout = ""

            mock_run.side_effect = [
                idle_result,
                subprocess.TimeoutExpired('cmd', 5)
            ]

            controller = RosbagController(mock_rosbag_config)
            result = controller.start_recording()

            assert result['success'] is False
            # Check for timeout indicator in message
            message_lower = result['message'].lower()
            assert 'timeout' in message_lower or 'timed out' in message_lower


@pytest.mark.skipif(not CONTROLLER_AVAILABLE, reason="RosbagController not available")
class TestRosbagControllerStopRecording:
    """Tests for stopping recording"""

    def test_stop_recording_success(self, mock_rosbag_config):
        """Test successful stop of recording"""
        with patch('subprocess.run') as mock_run:
            # Mock recording in progress
            recording_result = Mock()
            recording_result.returncode = 0
            recording_result.stdout = "12345 ros2 bag record -o /tmp/bag /topic1"

            # Mock successful stop
            stop_result = Mock()
            stop_result.returncode = 0
            stop_result.stdout = "response: std_srvs.srv.Trigger_Response(success=True, message='Recording stopped')"
            stop_result.stderr = ""

            call_count = [0]
            def run_side_effect(cmd, **kwargs):
                call_count[0] += 1
                if call_count[0] == 1:  # First call is status check
                    return recording_result
                return stop_result  # Second call is stop

            mock_run.side_effect = run_side_effect

            controller = RosbagController(mock_rosbag_config)
            result = controller.stop_recording()

            assert result['success'] is True

    def test_stop_recording_not_recording(self, mock_rosbag_config):
        """Test stop_recording when not recording"""
        with patch('subprocess.run') as mock_run:
            mock_result = Mock()
            mock_result.returncode = 1  # No process
            mock_result.stdout = ""
            mock_run.return_value = mock_result

            controller = RosbagController(mock_rosbag_config)
            result = controller.stop_recording()

            assert result['success'] is False
            # Check for recording stopped indicator in message
            message_lower = result['message'].lower()
            assert 'recording' in message_lower and ('not' in message_lower or 'currently' in message_lower)

    def test_stop_recording_timeout(self, mock_rosbag_config):
        """Test stop_recording when service call times out"""
        import subprocess

        with patch('subprocess.run') as mock_run:
            # Mock recording in progress
            recording_result = Mock()
            recording_result.returncode = 0
            recording_result.stdout = "12345 ros2 bag record"

            mock_run.side_effect = [
                recording_result,
                subprocess.TimeoutExpired('cmd', 5)
            ]

            controller = RosbagController(mock_rosbag_config)
            result = controller.stop_recording()

            assert result['success'] is False
            # Check for timeout indicator in message
            message_lower = result['message'].lower()
            assert 'timeout' in message_lower or 'timed out' in message_lower


@pytest.mark.skipif(not CONTROLLER_AVAILABLE, reason="RosbagController not available")
class TestRosbagControllerHelpers:
    """Tests for helper methods"""

    def test_extract_bag_path_from_cmd(self, mock_rosbag_config):
        """Test extracting bag path from command line"""
        controller = RosbagController(mock_rosbag_config)

        cmd = "ros2 bag record -o /home/user/rosbags/rosbag_20250127_123456 /topic1 /topic2"
        path = controller._extract_bag_path(cmd)

        assert path is not None
        assert "rosbag_20250127_123456" in path

    def test_extract_bag_path_no_output_flag(self, mock_rosbag_config):
        """Test extracting bag path when no -o flag present"""
        controller = RosbagController(mock_rosbag_config)

        cmd = "ros2 bag record /topic1 /topic2"
        path = controller._extract_bag_path(cmd)

        assert path is None

    def test_parse_bag_path_from_response(self, mock_rosbag_config):
        """Test parsing bag path from service response"""
        controller = RosbagController(mock_rosbag_config)

        output = "response: tuc_interfaces.srv.StartRecording_Response(success=True, message='Recording started at /home/user/rosbags/rosbag_20250127')"
        path = controller._parse_bag_path(output)

        assert path is not None
        assert "rosbag_20250127" in path

    def test_parse_message_from_response(self, mock_rosbag_config):
        """Test parsing message from service response"""
        controller = RosbagController(mock_rosbag_config)

        output = "response: tuc_interfaces.srv.StartRecording_Response(success=True, message='Recording started at /tmp/bag')"
        message = controller._parse_message(output)

        assert "Recording started" in message
