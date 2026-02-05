#!/usr/bin/env python3
"""
Quick verification that collect_sensor_status() returns topic_available and node_available.
This script does not require pytest.
"""

import sys
from pathlib import Path

# Add parent directory to path
project_root = Path(__file__).parent.parent
sys.path.insert(0, str(project_root))
sys.path.insert(0, str(Path(__file__).parent.parent))


def verify_collect_sensor_status_structure():
    """Verify collect_sensor_status() returns the correct structure."""
    from unittest.mock import Mock, patch

    from main import collect_sensor_status

    print("Testing collect_sensor_status()...")

    # Mock all monitors to avoid hardware checks
    with patch('main.get_monitor') as mock_get_monitor:
        mock_monitor = Mock()
        mock_result = Mock()
        mock_result.metrics = {
            'network': {'reachable': True, 'latency_ms': 5.0},
            'topics': {
                'points_available': True,
                'image_available': True,
                'data_available': True,
                'status_available': True,
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

        # Mock ROS2 monitor
        with patch('main.get_monitor') as mock_get_monitor_ros2:
            def get_monitor_side_effect(name):
                if name == 'ros2':
                    mock_ros2_monitor = Mock()
                    mock_ros2_monitor.is_system_running.return_value = False
                    return mock_ros2_monitor
                return mock_monitor

            mock_get_monitor_ros2.side_effect = get_monitor_side_effect

            # Call function
            result = collect_sensor_status()

            # Verify structure
            print(f"  - Has 'sensors' key: {('sensors' in result)}")
            print(f"  - Has 'overall' key: {('overall' in result)}")
            print(f"  - Has 'summary' key: {('summary' in result)}")

            # Check each sensor
            required_fields = [
                'status', 'color', 'value', 'message', 'frequency',
                'packet_loss', 'connected', 'gps_fix', 'satellites',
                'topic_available',  # NEW
                'node_available',   # NEW
            ]

            all_passed = True
            for sensor_name in ['navi_lidar', 'uli_lidar', 'camera', 'imu', 'thruster']:
                if sensor_name not in result['sensors']:
                    print(f"  ✗ {sensor_name}: NOT FOUND")
                    all_passed = False
                    continue

                sensor_data = result['sensors'][sensor_name]
                missing = [f for f in required_fields if f not in sensor_data]

                if missing:
                    print(f"  ✗ {sensor_name}: missing fields: {missing}")
                    all_passed = False
                else:
                    print(f"  ✓ {sensor_name}: all {len(required_fields)} fields present")
                    # Show the values of the new fields
                    print(f"    - topic_available: {sensor_data['topic_available']}")
                    print(f"    - node_available: {sensor_data['node_available']}")

            return all_passed


def verify_helper_functions():
    """Verify the helper functions work correctly."""
    from unittest.mock import Mock, patch
    from main import _get_topic_available, _get_node_available

    print("\nTesting helper functions...")

    # Test _get_topic_available
    print("\n  _get_topic_available():")

    # Test with points_available
    metrics = {'topics': {'points_available': True}}
    result = _get_topic_available(metrics, 'navi_lidar')
    print(f"    - navi_lidar with points_available=True: {result}")
    assert result is True, f"Expected True, got {result}"

    # Test with no topics
    metrics = {}
    result = _get_topic_available(metrics, 'navi_lidar')
    print(f"    - navi_lidar with no topics: {result}")
    assert result is None, f"Expected None, got {result}"

    print("    ✓ _get_topic_available() works correctly")

    # Test _get_node_available
    print("\n  _get_node_available():")

    with patch('main.get_monitor') as mock_get_monitor:
        mock_ros2_monitor = Mock()
        mock_ros2_monitor.is_system_running.return_value = False
        mock_get_monitor.return_value = mock_ros2_monitor

        result = _get_node_available('navi_lidar')
        print(f"    - navi_lidar with ROS2 not running: {result}")
        assert result is None, f"Expected None, got {result}"

        print("    ✓ _get_node_available() works correctly")

    return True


def verify_check_single_sensor():
    """Verify _check_single_sensor() returns the correct structure."""
    from unittest.mock import Mock, patch
    from main import _check_single_sensor

    print("\nTesting _check_single_sensor()...")

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

        with patch('main.get_monitor') as mock_get_monitor_ros2:
            def get_monitor_side_effect(name):
                if name == 'ros2':
                    mock_ros2_monitor = Mock()
                    mock_ros2_monitor.is_system_running.return_value = False
                    return mock_ros2_monitor
                return mock_monitor

            mock_get_monitor_ros2.side_effect = get_monitor_side_effect

            result = _check_single_sensor('navi_lidar')

            # Check new fields
            has_topic = 'topic_available' in result
            has_node = 'node_available' in result

            print(f"  - Has topic_available: {has_topic}")
            print(f"  - Has node_available: {has_node}")

            if has_topic and has_node:
                print(f"  ✓ topic_available = {result['topic_available']}")
                print(f"  ✓ node_available = {result['node_available']}")
                return True
            else:
                print(f"  ✗ Missing required fields")
                return False


def verify_frontend_compatibility():
    """Verify that the data structure matches what frontend expects."""
    print("\n" + "="*60)
    print("FRONTEND COMPATIBILITY CHECK")
    print("="*60)

    # These are the fields expected by dashboard.js
    frontend_expected_fields = {
        'status': 'boolean/string - sensor status',
        'connected': 'string - "Connected" or "Disconnected"',
        'node_available': 'boolean - ROS2 node running',
        'topic_available': 'boolean - ROS2 topic available',
        'frequency': 'string - frequency like "10.0 Hz"',
        'packet_loss': 'string/number - latency or packet loss',
    }

    print("\nFields expected by frontend (dashboard.js:78-108):")
    for field, description in frontend_expected_fields.items():
        print(f"  - {field}: {description}")

    print("\n" + "="*60)
    print("✓ All required fields are now included in collect_sensor_status()")
    print("="*60)


def main():
    """Run all verification tests."""
    print("="*60)
    print("SENSOR STATUS DATA STRUCTURE VERIFICATION")
    print("="*60)

    try:
        passed = verify_collect_sensor_status_structure()
        passed = verify_helper_functions() and passed
        passed = verify_check_single_sensor() and passed

        if passed:
            verify_frontend_compatibility()
            print("\n" + "="*60)
            print("ALL TESTS PASSED ✓")
            print("="*60)
            return 0
        else:
            print("\n" + "="*60)
            print("SOME TESTS FAILED ✗")
            print("="*60)
            return 1

    except Exception as e:
        print(f"\n✗ Error during verification: {e}")
        import traceback
        traceback.print_exc()
        return 1


if __name__ == '__main__':
    sys.exit(main())
