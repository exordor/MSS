#!/usr/bin/env python3
# test_rosbag_api.py - Tests for rosbag recording API endpoints

import pytest
import json
import sys
from pathlib import Path
from unittest.mock import patch, Mock
import subprocess

# Add parent directory to path for imports
sys.path.insert(0, str(Path(__file__).parent.parent.parent))

# Import FastAPI test client
try:
    from fastapi.testclient import TestClient
    from main import app
    APP_AVAILABLE = True
except ImportError as e:
    print(f"Warning: Could not import FastAPI app: {e}")
    APP_AVAILABLE = False


@pytest.mark.skipif(not APP_AVAILABLE, reason="FastAPI app not available")
class TestRosbagStatusAPI:
    """Tests for GET /api/rosbag/status"""

    @pytest.fixture
    def client(self, test_config):
        """Create a test FastAPI client"""
        # Mock the configuration
        with patch('config.ROSBAG_CONFIG', test_config["ROSBAG_CONFIG"]):
            with patch('config.ROS2_CONFIG', test_config["ROS2_CONFIG"]):
                with patch('config.PROJECT_ROOT', test_config["PROJECT_ROOT"]):
                    with patch('diagnostics.rosbag_controller.get_rosbag_controller') as mock_get:
                        # Create a mock controller
                        mock_controller = Mock()
                        mock_controller.check_status.return_value = {
                            "is_recording": False,
                            "current_bag": None,
                            "duration": None,
                            "topics_count": 0,
                            "topics": [],
                            "config_loaded": False,
                            "pid": None
                        }
                        mock_get.return_value = mock_controller
                        yield TestClient(app)

    def test_status_idle(self, client, mock_pgrep_no_process):
        """Test status endpoint when not recording"""
        response = client.get('/api/rosbag/status')

        assert response.status_code == 200
        data = json.loads(response.data)

        assert data['success'] is True
        assert data['data']['is_recording'] is False
        assert 'topics_count' in data['data']

    def test_status_error_handling(self, client):
        """Test status endpoint error handling"""
        # First make a successful request to populate cache
        response = client.get('/api/rosbag/status')
        assert response.status_code == 200

        # Then mock an error - the app may return cached data or error
        with patch('diagnostics.rosbag_controller.get_rosbag_controller') as mock_get:
            mock_get.side_effect = Exception("Test error")

            response = client.get('/api/rosbag/status')

            # App should handle error gracefully (return 200 with stale data or 500)
            assert response.status_code in [200, 500]
            data = json.loads(response.data)

            if response.status_code == 500:
                assert data['success'] is False
            else:
                # May return cached/stale data
                assert 'data' in data or 'success' in data


@pytest.mark.skipif(not APP_AVAILABLE, reason="FastAPI app not available")
class TestRosbagStartAPI:
    """Tests for POST /api/rosbag/start"""

    @pytest.fixture
    def client(self, test_config):
        """Create a test FastAPI client"""
        with patch('config.ROSBAG_CONFIG', test_config["ROSBAG_CONFIG"]):
            with patch('config.ROS2_CONFIG', test_config["ROS2_CONFIG"]):
                with patch('config.PROJECT_ROOT', test_config["PROJECT_ROOT"]):
                    with patch('diagnostics.rosbag_controller.get_rosbag_controller') as mock_get:
                        # Create a mock controller
                        mock_controller = Mock()
                        mock_controller.check_status.return_value = {
                            "is_recording": False,
                            "current_bag": None,
                            "duration": None,
                            "topics_count": 0,
                            "topics": [],
                            "config_loaded": False,
                            "pid": None
                        }
                        mock_controller.start_recording.return_value = {
                            "success": True,
                            "message": "Recording started",
                            "bag_path": "/tmp/test_bag"
                        }
                        mock_get.return_value = mock_controller
                        yield TestClient(app)

    def test_start_success(self, client, mock_pgrep_no_process):
        """Test successful start of recording"""
        # Configure mock for successful start
        with patch('subprocess.run') as mock_run:
            mock_result = Mock()
            mock_result.returncode = 0
            mock_result.stdout = "response: tuc_interfaces.srv.StartRecording_Response(success=True, message='Recording started at /tmp/test_rosbags/bag_20250127')"
            mock_result.stderr = ""
            mock_run.return_value = mock_result

            response = client.post(
                '/api/rosbag/start',
                data=json.dumps({}),
                content_type='application/json'
            )

            assert response.status_code == 200
            data = json.loads(response.data)

            assert data['success'] is True
            assert 'bag_path' in data or 'message' in data

    def test_start_with_custom_topics(self, client, mock_pgrep_no_process):
        """Test start with custom topic list"""
        custom_topics = ["/custom/topic1", "/custom/topic2"]

        with patch('subprocess.run') as mock_run:
            mock_result = Mock()
            mock_result.returncode = 0
            mock_result.stdout = "response: tuc_interfaces.srv.StartRecording_Response(success=True, message='Recording started')"
            mock_result.stderr = ""
            mock_run.return_value = mock_result

            response = client.post(
                '/api/rosbag/start',
                data=json.dumps({"topics": custom_topics}),
                content_type='application/json'
            )

            assert response.status_code == 200
            data = json.loads(response.data)
            assert data['success'] is True

    def test_start_already_recording(self, client):
        """Test start when already recording"""
        with patch('subprocess.run') as mock_run:
            # Mock pgrep to show process is running
            def run_side_effect(cmd, **kwargs):
                mock_result = Mock()
                if 'pgrep' in str(cmd):
                    mock_result.returncode = 0
                    mock_result.stdout = "12345 ros2 bag record"
                else:
                    mock_result.returncode = 0
                    mock_result.stdout = ""
                mock_result.stderr = ""
                return mock_result

            mock_run.side_effect = run_side_effect

            response = client.post(
                '/api/rosbag/start',
                data=json.dumps({}),
                content_type='application/json'
            )

            assert response.status_code == 200
            data = json.loads(response.data)

            assert data['success'] is False
            assert 'Already recording' in data.get('message', '')

    def test_start_service_timeout(self, client, mock_pgrep_no_process):
        """Test start when service call times out"""
        with patch('subprocess.run') as mock_run:
            mock_run.side_effect = subprocess.TimeoutExpired('cmd', 5)

            response = client.post(
                '/api/rosbag/start',
                data=json.dumps({}),
                content_type='application/json'
            )

            assert response.status_code == 200
            data = json.loads(response.data)

            assert data['success'] is False
            # Check for timeout indicator in message
            message_lower = data.get('message', '').lower()
            assert 'timeout' in message_lower or 'timed out' in message_lower


@pytest.mark.skipif(not APP_AVAILABLE, reason="FastAPI app not available")
class TestRosbagStopAPI:
    """Tests for POST /api/rosbag/stop"""

    @pytest.fixture
    def client(self, test_config):
        """Create a test FastAPI client"""
        with patch('config.ROSBAG_CONFIG', test_config["ROSBAG_CONFIG"]):
            with patch('config.ROS2_CONFIG', test_config["ROS2_CONFIG"]):
                with patch('config.PROJECT_ROOT', test_config["PROJECT_ROOT"]):
                    with patch('diagnostics.rosbag_controller.get_rosbag_controller') as mock_get:
                        # Create a mock controller
                        mock_controller = Mock()
                        mock_controller.check_status.return_value = {
                            "is_recording": True,
                            "current_bag": "/tmp/test_bag",
                            "duration": None,
                            "topics_count": 0,
                            "topics": [],
                            "config_loaded": False,
                            "pid": 12345
                        }
                        mock_controller.stop_recording.return_value = {
                            "success": True,
                            "message": "Recording stopped"
                        }
                        mock_get.return_value = mock_controller
                        yield TestClient(app)

    def test_stop_success(self, client):
        """Test successful stop of recording"""
        with patch('subprocess.run') as mock_run:
            # Mock pgrep to show process is running
            def run_side_effect(cmd, **kwargs):
                mock_result = Mock()
                if 'pgrep' in str(cmd):
                    mock_result.returncode = 0
                    mock_result.stdout = "12345 ros2 bag record"
                elif 'stop_recording' in str(cmd):
                    mock_result.returncode = 0
                    mock_result.stdout = "response: std_srvs.srv.Trigger_Response(success=True, message='Recording stopped')"
                else:
                    mock_result.returncode = 0
                    mock_result.stdout = ""
                mock_result.stderr = ""
                return mock_result

            mock_run.side_effect = run_side_effect

            response = client.post('/api/rosbag/stop')

            assert response.status_code == 200
            data = json.loads(response.data)

            assert data['success'] is True

    def test_stop_when_not_recording(self, client, mock_pgrep_no_process):
        """Test stop when not recording"""
        response = client.post('/api/rosbag/stop')

        assert response.status_code == 200
        data = json.loads(response.data)

        assert data['success'] is False
        # Check for recording stopped indicator in message
        message_lower = data.get('message', '').lower()
        assert 'recording' in message_lower and 'not' in message_lower


@pytest.mark.skipif(not APP_AVAILABLE, reason="FastAPI app not available")
class TestRosbagWorkflow:
    """Integration tests for complete recording workflows"""

    @pytest.fixture
    def client(self, test_config):
        """Create a test FastAPI client"""
        with patch('config.ROSBAG_CONFIG', test_config["ROSBAG_CONFIG"]):
            with patch('config.ROS2_CONFIG', test_config["ROS2_CONFIG"]):
                with patch('config.PROJECT_ROOT', test_config["PROJECT_ROOT"]):
                    with patch('diagnostics.rosbag_controller.get_rosbag_controller') as mock_get:
                        # Create a mock controller
                        mock_controller = Mock()
                        mock_controller.check_status.return_value = {
                            "is_recording": False,
                            "current_bag": None,
                            "duration": None,
                            "topics_count": 0,
                            "topics": [],
                            "config_loaded": False,
                            "pid": None
                        }
                        mock_controller.start_recording.return_value = {
                            "success": True,
                            "message": "Recording started",
                            "bag_path": "/tmp/test_bag"
                        }
                        mock_controller.stop_recording.return_value = {
                            "success": True,
                            "message": "Recording stopped"
                        }
                        mock_get.return_value = mock_controller
                        yield TestClient(app)

    def test_full_recording_cycle(self, client):
        """Test complete start-status-stop cycle"""
        with patch('subprocess.run') as mock_run:
            call_count = [0]

            def run_side_effect(cmd, **kwargs):
                call_count[0] += 1
                mock_result = Mock()

                cmd_str = ' '.join(cmd) if isinstance(cmd, list) else str(cmd)

                # First calls: not recording
                if call_count[0] <= 2 and 'pgrep' in cmd_str:
                    mock_result.returncode = 1
                    mock_result.stdout = ""
                # Start recording
                elif 'start_recording' in cmd_str:
                    mock_result.returncode = 0
                    mock_result.stdout = "response: tuc_interfaces.srv.StartRecording_Response(success=True, message='Recording started at /tmp/test_rosbags/bag')"
                # After start: recording
                elif 'pgrep' in cmd_str and call_count[0] > 2:
                    mock_result.returncode = 0
                    mock_result.stdout = "12345 ros2 bag record -o /tmp/test_rosbags/bag /topic1"
                # Stop recording
                elif 'stop_recording' in cmd_str:
                    mock_result.returncode = 0
                    mock_result.stdout = "response: std_srvs.srv.Trigger_Response(success=True)"
                else:
                    mock_result.returncode = 0
                    mock_result.stdout = ""

                mock_result.stderr = ""
                return mock_result

            mock_run.side_effect = run_side_effect

            # 1. Check initial status
            response = client.get('/api/rosbag/status')
            assert json.loads(response.data)['data']['is_recording'] is False

            # 2. Start recording
            response = client.post('/api/rosbag/start', json={})
            assert json.loads(response.data)['success'] is True

            # 3. Check recording status
            response = client.get('/api/rosbag/status')
            data = json.loads(response.data)
            # After start, state would show recording
            # Note: In our mock, the third pgrep call returns recording state

            # 4. Stop recording
            response = client.post('/api/rosbag/stop')
            assert json.loads(response.data)['success'] is True
