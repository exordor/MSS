#!/usr/bin/env python3
"""
Test sensor status data structure consistency.

This test verifies that collect_sensor_status() returns the same fields
as _check_single_sensor() for frontend compatibility.
"""

import pytest
from unittest.mock import Mock, patch, MagicMock
from typing import Dict, Any


class TestSensorStatusFields:
    """Test that sensor status data has all required fields for frontend."""

    @pytest.fixture
    def test_config(self):
        """Test configuration for sensor monitors."""
        return {
            'ROS2_CONFIG': {
                'domain_id': 42,
                'source_cmd': '/opt/ros/humble/setup.bash',
                'workspace': '/tmp/test_ws',
            },
            'SENSOR_THRESHOLDS': {
                'navi_lidar': {
                    'min_frequency': 8.0,
                    'min_points_per_frame': 50000,
                },
                'camera': {
                    'min_frequency': 1.5,
                    'max_frequency': 2.5,
                    'max_latency': 500,
                },
                'imu': {
                    'min_frequency': 50.0,
                },
                'thruster': {},
            },
            'SENSOR_IPS': {
                'navi_lidar': '192.168.0.201',
                'camera': '192.168.0.11',
                'imu': '/dev/ttyUSB0',
                'thruster': '192.168.0.30',
            },
            'ROS2_TOPICS': {
                'navi_lidar': {'points': '/navi_lidar/points'},
                'camera': {'image_raw': '/image_raw'},
                'imu': {'data': '/imu/data'},
                'thruster': {'status': '/thruster_status_pwm'},
            },
            'ENABLE_TOPIC_DETAILS': False,
            'EXPECTED_NODES': [],
            'IGNORED_NODES': [],
            'SENSOR_NODES': {},
        }

    def test_collect_sensor_status_has_required_fields(self, test_config):
        """Test that collect_sensor_status() returns topic_available and node_available."""
        # Import after setting up path
        import sys
        from pathlib import Path
        sys.path.insert(0, str(Path(__file__).parent.parent.parent))

        from main import collect_sensor_status

        # Mock all the monitors to avoid actual hardware checks
        with patch('main.get_monitor') as mock_get_monitor:
            # Create mock monitor that returns a valid result
            mock_monitor = Mock()
            mock_result = Mock()
            mock_result.metrics = {
                'network': {'reachable': True, 'latency_ms': 5.0},
                'topics': {
                    'points_available': True,  # For navi_lidar
                    'image_available': True,   # For camera
                    'data_available': True,    # For imu
                    'status_available': True,  # For thruster
                },
                'log_data': {
                    'measured_frequency': 10.0,
                    'avg_processing_ms': 50.0,
                },
                'serial': {'connected': True},
                'tcp': {'connected': True, 'latency_ms': 10},
                'gps': {'fix_status': '3D', 'satellites': 12},
            }

            mock_monitor.check.return_value = mock_result
            mock_monitor.get_diagnostic_summary.return_value = {
                'status': 'ok',
                'color': 'green',
                'value': 'OK',
                'message': 'Sensor OK',
            }

            mock_get_monitor.return_value = mock_monitor

            # Mock ROS2 monitor for node availability check
            with patch('main.get_monitor') as mock_get_monitor_ros2:
                # Create a map to return different mocks based on name
                def get_monitor_side_effect(name):
                    if name == 'ros2':
                        mock_ros2_monitor = Mock()
                        mock_ros2_monitor.is_system_running.return_value = False
                        return mock_ros2_monitor
                    return mock_monitor

                mock_get_monitor_ros2.side_effect = get_monitor_side_effect

                # Call the function
                result = collect_sensor_status()

                # Verify structure
                assert 'sensors' in result, "Result should have 'sensors' key"
                assert 'overall' in result, "Result should have 'overall' key"
                assert 'summary' in result, "Result should have 'summary' key"

                # Check each sensor has required fields
                for sensor_name in ['navi_lidar', 'uli_lidar', 'camera', 'imu', 'thruster']:
                    assert sensor_name in result['sensors'], f"Should have {sensor_name}"
                    sensor_data = result['sensors'][sensor_name]

                    # These are the fields expected by the frontend
                    required_fields = [
                        'status',
                        'color',
                        'value',
                        'message',
                        'frequency',
                        'packet_loss',
                        'connected',
                        'gps_fix',
                        'satellites',
                        'topic_available',  # NEW - required by frontend
                        'node_available',   # NEW - required by frontend
                    ]

                    for field in required_fields:
                        assert field in sensor_data, \
                            f"{sensor_name} should have '{field}' field"

    def test_get_topic_available_with_valid_metrics(self):
        """Test _get_topic_available() with valid metrics."""
        import sys
        from pathlib import Path
        sys.path.insert(0, str(Path(__file__).parent.parent.parent))

        from main import _get_topic_available

        # Test navi_lidar
        metrics = {'topics': {'points_available': True}}
        assert _get_topic_available(metrics, 'navi_lidar') is True

        # Test camera
        metrics = {'topics': {'image_available': False}}
        assert _get_topic_available(metrics, 'camera') is False

        # Test with no topics
        metrics = {}
        assert _get_topic_available(metrics, 'navi_lidar') is None

    def test_get_topic_available_with_generic_fallback(self):
        """Test _get_topic_available() with generic *_available fallback."""
        import sys
        from pathlib import Path
        sys.path.insert(0, str(Path(__file__).parent.parent.parent))

        from main import _get_topic_available

        # Test generic fallback
        metrics = {'topics': {'custom_available': True}}
        assert _get_topic_available(metrics, 'navi_lidar') is True

    def test_get_node_available_with_ros2_running(self):
        """Test _get_node_available() when ROS2 is running."""
        import sys
        from pathlib import Path
        sys.path.insert(0, str(Path(__file__).parent.parent.parent))

        from main import _get_node_available

        with patch('main.get_monitor') as mock_get_monitor:
            mock_ros2_monitor = Mock()
            mock_ros2_monitor.is_system_running.return_value = True

            mock_get_monitor.return_value = mock_ros2_monitor

            with patch('main.get_ros2_helper') as mock_get_helper:
                mock_helper = Mock()
                mock_helper.get_node_names.return_value = [
                    '/hesai_driver_node',
                    '/camera_node',
                    '/imu_driver',
                ]
                mock_get_helper.return_value = mock_helper

                # Test navi_lidar - should find 'hesai' in node names
                result = _get_node_available('navi_lidar')
                assert result is True

                # Test thruster - should not find any matching nodes
                result = _get_node_available('thruster')
                assert result is False

    def test_get_node_available_with_ros2_not_running(self):
        """Test _get_node_available() when ROS2 is not running."""
        import sys
        from pathlib import Path
        sys.path.insert(0, str(Path(__file__).parent.parent.parent))

        from main import _get_node_available

        with patch('main.get_monitor') as mock_get_monitor:
            mock_ros2_monitor = Mock()
            mock_ros2_monitor.is_system_running.return_value = False
            mock_get_monitor.return_value = mock_ros2_monitor

            # Should return None when ROS2 is not running
            result = _get_node_available('navi_lidar')
            assert result is None

    def test_check_single_sensor_has_required_fields(self, test_config):
        """Test that _check_single_sensor() returns topic_available and node_available."""
        import sys
        from pathlib import Path
        sys.path.insert(0, str(Path(__file__).parent.parent.parent))

        from main import _check_single_sensor

        with patch('main.get_monitor') as mock_get_monitor:
            mock_monitor = Mock()
            mock_result = Mock()
            mock_result.metrics = {
                'network': {'reachable': True},
                'topics': {'points_available': True},
                'log_data': {'measured_frequency': 10.0},
            }

            mock_monitor.check.return_value = mock_result
            mock_monitor.get_diagnostic_summary.return_value = {
                'status': 'ok',
                'color': 'green',
                'value': 'OK',
                'message': 'OK',
            }

            mock_get_monitor.return_value = mock_monitor

            # Mock ROS2 monitor for node availability
            with patch('main.get_monitor') as mock_get_monitor_ros2:
                def get_monitor_side_effect(name):
                    if name == 'ros2':
                        mock_ros2_monitor = Mock()
                        mock_ros2_monitor.is_system_running.return_value = False
                        return mock_ros2_monitor
                    return mock_monitor

                mock_get_monitor_ros2.side_effect = get_monitor_side_effect

                # Call the function
                result = _check_single_sensor('navi_lidar')

                # Verify required fields exist
                assert 'topic_available' in result
                assert 'node_available' in result
                assert result['topic_available'] is True  # From our mock metrics
                assert result['node_available'] is None  # ROS2 not running


if __name__ == '__main__':
    pytest.main([__file__, '-v'])
