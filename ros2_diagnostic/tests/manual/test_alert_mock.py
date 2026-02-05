#!/usr/bin/env python3
"""
Manual Alert Mock Test Script

Usage:
    cd ros2_diagnostic
    python tests/manual/test_alert_mock.py

This script performs standalone mock testing of the alert system without
requiring actual sensors or running ROS2 system.

Tests:
1. AlertStore basic operations
2. NaviLidar Diagnostic alert triggering
3. FastAPI API endpoints
"""

import tempfile
import os
import sys
from pathlib import Path

# Add ros2_diagnostic directory to path
# script is at: ros2_diagnostic/tests/manual/test_alert_mock.py
# we need to go up two levels to reach ros2_diagnostic
script_dir = Path(__file__).parent.parent.parent
sys.path.insert(0, str(script_dir))


def print_section(title):
    """Print a section header"""
    print("\n" + "=" * 60)
    print(f" {title}")
    print("=" * 60)


def print_success(message):
    """Print a success message"""
    print(f"  ✓ {message}")


def print_error(message):
    """Print an error message"""
    print(f"  ✗ {message}")


def test_alert_store():
    """Test AlertStore basic functionality"""
    print_section("Testing AlertStore")

    from alerts import Alert, AlertStore
    from datetime import datetime

    with tempfile.NamedTemporaryFile(suffix='.db', delete=False) as f:
        db_path = f.name

    try:
        # Reset module for clean state
        if 'alerts' in sys.modules:
            del sys.modules['alerts']

        store = AlertStore(db_path=db_path)
        print_success("AlertStore created")

        # Test 1: Add alerts with different severity levels
        print("\n  Adding test alerts...")

        test_alerts = [
            Alert(
                sensor="navi_lidar",
                alert_type="frame_loss_critical",
                severity="critical",
                message=f"Severe frame loss: {freq} Hz",
                metric_value=freq,
                threshold=8.0,
                metadata=f'{{"measured_frequency": {freq}, "frame_count": 50}}',
                created_at=datetime.now().isoformat()
            )
            for freq in [3.5, 6.2, 10.0]  # critical, warning, normal
        ]

        alert_ids = []
        for alert in test_alerts:
            aid = store.add_alert(alert)
            alert_ids.append(aid)
        print_success(f"Added {len(alert_ids)} alerts (critical, warning, normal)")

        # Test 2: Get active alerts
        active = store.get_active_alerts()
        print_success(f"Active alerts: {len(active)}")

        # Test 3: Filter by sensor
        navi_alerts = store.get_active_alerts(sensor="navi_lidar")
        print_success(f"Navi LiDAR alerts: {len(navi_alerts)}")

        # Test 4: Filter by severity
        critical = store.get_alerts_by_severity("critical")
        print_success(f"Critical alerts: {len(critical)}")

        warning = store.get_alerts_by_severity("warning")
        print_success(f"Warning alerts: {len(warning)}")

        # Test 5: Get statistics
        stats = store.get_alert_stats()
        print_success(f"Statistics: total={stats['total']}, active={stats['active']}, "
                     f"critical={stats['critical']}, warning={stats['warning']}")

        # Test 6: Resolve an alert
        store.resolve_alert(alert_ids[0])
        active_after = store.get_active_alerts()
        print_success(f"After resolve: {len(active_after)} active alerts")

        # Test 7: Ignore an alert
        store.ignore_alert(alert_ids[1])
        active_after_ignore = store.get_active_alerts()
        print_success(f"After ignore: {len(active_after_ignore)} active alerts")

        print("\n  All AlertStore tests passed!")

    except Exception as e:
        print_error(f"AlertStore test failed: {e}")
        import traceback
        traceback.print_exc()
    finally:
        if os.path.exists(db_path):
            os.unlink(db_path)


def test_diagnostic_mock():
    """Test diagnostic module alert triggering"""
    print_section("Testing NaviLidar Diagnostic Alert Triggering")

    from diagnostics.sensor_monitor.navi_lidar import NaviLidarDiagnostic
    from unittest.mock import patch, Mock
    from datetime import datetime
    import json

    with tempfile.NamedTemporaryFile(suffix='.db', delete=False, dir='.') as f:
        db_path = f.name

    try:
        # Reset module for clean state
        if 'alerts' in sys.modules:
            del sys.modules['alerts']

        config = {
            'SENSOR_THRESHOLDS': {
                'navi_lidar': {
                    'min_frequency': 8.0,
                    'min_points_per_frame': 50000,
                    'max_packet_loss': 1.0,
                }
            },
            'SENSOR_IPS': {'navi_lidar': '192.168.0.201'},
            'ROS2_TOPICS': {'navi_lidar': {'points': '/navi_lidar/points'}},
            'ENABLE_TOPIC_DETAILS': False,
        }

        diagnostic = NaviLidarDiagnostic(config)

        # Test 1: Critical frame loss scenario
        print("\n  Test 1: Critical frame loss (frequency = 3.5 Hz)")

        with patch('diagnostics.sensor_monitor.navi_lidar.ping_host') as mock_ping:
            mock_ping.return_value = {'reachable': True, 'avg_time_ms': 1.5, 'packet_loss': 0}

            with patch.object(diagnostic, '_log_parser') as mock_parser:
                mock_parser.get_statistics.return_value = Mock(
                    frequency=3.5,  # Critical ( < 8.0 * 0.5 = 4.0)
                    avg_points=115200,
                    frame_count=100,
                    min_points=115000,
                    max_points=120000,
                    last_frame_num=99,
                    last_timestamp=1602248443.595332,
                    time_since_last_frame=0.1
                )

                with patch.object(diagnostic, '_get_ros2_monitor') as mock_monitor_getter:
                    mock_monitor = Mock()
                    mock_monitor.is_system_running = Mock(return_value=True)
                    with patch.object(diagnostic, '_ros2_monitor', mock_monitor):

                        with patch('diagnostics.sensor_monitor.navi_lidar.get_ros2_helper') as mock_ros2:
                            mock_helper = Mock()
                            mock_helper.get_node_names.return_value = ['navi_lidar_driver']
                            mock_helper.get_topic_names.return_value = ['/navi_lidar/points']
                            mock_ros2.return_value = mock_helper

                            result = diagnostic.check()
                            print_success(f"Diagnostic status: {result.status.value}")

        # Verify alert was generated
        from alerts import get_alert_store
        store = get_alert_store()
        alerts = store.get_active_alerts(sensor='navi_lidar')
        print_success(f"Alerts generated: {len(alerts)}")

        for alert in alerts:
            print(f"    - [{alert.severity.upper()}] {alert.alert_type}: {alert.message}")

        # Test 2: Warning frame loss scenario
        print("\n  Test 2: Warning frame loss (frequency = 6.2 Hz)")

        # Clear existing alerts
        for alert in alerts:
            store.resolve_alert(alert.id)

        with patch('diagnostics.sensor_monitor.navi_lidar.ping_host') as mock_ping:
            mock_ping.return_value = {'reachable': True, 'avg_time_ms': 1.5, 'packet_loss': 0}

            with patch.object(diagnostic, '_log_parser') as mock_parser:
                mock_parser.get_statistics.return_value = Mock(
                    frequency=6.2,  # Warning ( < 8.0 but >= 4.0)
                    avg_points=115200,
                    frame_count=100,
                    min_points=115000,
                    max_points=120000,
                    last_frame_num=99,
                    last_timestamp=1602248443.595332,
                    time_since_last_frame=0.1
                )

                with patch.object(diagnostic, '_get_ros2_monitor') as mock_monitor_getter:
                    mock_monitor = Mock()
                    mock_monitor.is_system_running = Mock(return_value=True)
                    with patch.object(diagnostic, '_ros2_monitor', mock_monitor):

                        with patch('diagnostics.sensor_monitor.navi_lidar.get_ros2_helper') as mock_ros2:
                            mock_helper = Mock()
                            mock_helper.get_node_names.return_value = ['navi_lidar_driver']
                            mock_helper.get_topic_topics.return_value = ['/navi_lidar/points']
                            mock_ros2.return_value = mock_helper

                            result = diagnostic.check()
                            print_success(f"Diagnostic status: {result.status.value}")

        alerts = store.get_active_alerts(sensor='navi_lidar')
        print_success(f"Alerts generated: {len(alerts)}")

        # Test 3: Point count critical scenario
        print("\n  Test 3: Point count critical (points = 20000)")

        # Clear existing alerts
        for alert in alerts:
            store.resolve_alert(alert.id)

        with patch('diagnostics.sensor_monitor.navi_lidar.ping_host') as mock_ping:
            mock_ping.return_value = {'reachable': True, 'avg_time_ms': 1.5, 'packet_loss': 0}

            with patch.object(diagnostic, '_log_parser') as mock_parser:
                mock_parser.get_statistics.return_value = Mock(
                    frequency=10.0,  # Normal
                    avg_points=20000,  # Critical ( < 50000 * 0.5 = 25000)
                    frame_count=100,
                    min_points=18000,
                    max_points=22000,
                    last_frame_num=99,
                    last_timestamp=1602248443.595332,
                    time_since_last_frame=0.1
                )

                with patch.object(diagnostic, '_get_ros2_monitor') as mock_monitor_getter:
                    mock_monitor = Mock()
                    mock_monitor.is_system_running = Mock(return_value=True)
                    with patch.object(diagnostic, '_ros2_monitor', mock_monitor):

                        with patch('diagnostics.sensor_monitor.navi_lidar.get_ros2_helper') as mock_ros2:
                            mock_helper = Mock()
                            mock_helper.get_node_names.return_value = ['navi_lidar_driver']
                            mock_helper.get_topic_topics.return_value = ['/navi_lidar/points']
                            mock_ros2.return_value = mock_helper

                            result = diagnostic.check()
                            print_success(f"Diagnostic status: {result.status.value}")

        alerts = store.get_active_alerts(sensor='navi_lidar')
        print_success(f"Alerts generated: {len(alerts)}")

        # Test 4: Normal operation (no alerts)
        print("\n  Test 4: Normal operation (no alerts expected)")

        # Clear existing alerts
        for alert in alerts:
            store.resolve_alert(alert.id)

        with patch('diagnostics.sensor_monitor.navi_lidar.ping_host') as mock_ping:
            mock_ping.return_value = {'reachable': True, 'avg_time_ms': 1.5, 'packet_loss': 0}

            with patch.object(diagnostic, '_log_parser') as mock_parser:
                mock_parser.get_statistics.return_value = Mock(
                    frequency=10.0,  # Normal (>= 8.0)
                    avg_points=115200,  # Normal (>= 50000)
                    frame_count=100,
                    min_points=110000,
                    max_points=120000,
                    last_frame_num=99,
                    last_timestamp=1602248443.595332,
                    time_since_last_frame=0.1
                )

                with patch.object(diagnostic, '_get_ros2_monitor') as mock_monitor_getter:
                    mock_monitor = Mock()
                    mock_monitor.is_system_running = Mock(return_value=True)
                    with patch.object(diagnostic, '_ros2_monitor', mock_monitor):

                        with patch('diagnostics.sensor_monitor.navi_lidar.get_ros2_helper') as mock_ros2:
                            mock_helper = Mock()
                            mock_helper.get_node_names.return_value = ['navi_lidar_driver']
                            mock_helper.get_topic_topics.return_value = ['/navi_lidar/points']
                            mock_ros2.return_value = mock_helper

                            result = diagnostic.check()
                            print_success(f"Diagnostic status: {result.status.value}")

        alerts = store.get_active_alerts(sensor='navi_lidar')
        print_success(f"Alerts generated: {len(alerts)} (expected 0)")

        if len(alerts) == 0:
            print_success("✓ No alerts generated for normal operation - correct!")
        else:
            print_error(f"Unexpected alerts: {alerts}")

        print("\n  All Diagnostic mock tests passed!")

    except Exception as e:
        print_error(f"Diagnostic test failed: {e}")
        import traceback
        traceback.print_exc()
    finally:
        if os.path.exists(db_path):
            os.unlink(db_path)


def test_api_mock():
    """Test FastAPI API endpoints"""
    print_section("Testing Alert API Endpoints")

    with tempfile.NamedTemporaryFile(suffix='.db', delete=False, dir='.') as f:
        db_path = f.name

    try:
        # Reset modules for clean state
        for mod in list(sys.modules.keys()):
            if 'alerts' in mod or mod == 'main':
                del sys.modules[mod]

        from main import app
        from alerts import Alert, AlertStore, get_alert_store

        from fastapi.testclient import TestClient
        client = TestClient(app)

        # Initialize store
        store = get_alert_store()

        # Test 1: GET /api/alerts (empty)
        print("\n  Test 1: GET /api/alerts (empty)")
        response = client.get('/api/alerts')
        assert response.status_code == 200
        data = response.json()
        assert data['success'] is True
        assert len(data['data']) == 0
        print_success("Empty alerts list returned")

        # Test 2: Add test data
        print("\n  Test 2: Adding test alerts...")
        test_alerts = [
            Alert(
                sensor="navi_lidar",
                alert_type="frame_loss",
                severity="critical",
                message="Severe frame loss: 3.5 Hz",
                metric_value=3.5,
                threshold=8.0,
                metadata='{"measured_frequency": 3.5}',
                created_at="2026-01-27T10:00:00"
            ),
            Alert(
                sensor="camera",
                alert_type="connectivity",
                severity="warning",
                message="Camera signal weak",
                metric_value=0.0,
                threshold=1.0,
                metadata='{}',
                created_at="2026-01-27T10:05:00"
            ),
            Alert(
                sensor="imu",
                alert_type="data_loss",
                severity="warning",
                message="IMU data intermittent",
                metric_value=0.0,
                threshold=1.0,
                metadata='{}',
                created_at="2026-01-27T10:10:00",
                resolved_at="2026-01-27T10:15:00",
                status="resolved"
            ),
        ]

        for alert in test_alerts:
            store.add_alert(alert)
        print_success(f"Added {len(test_alerts)} test alerts")

        # Test 3: GET /api/alerts (with data)
        print("\n  Test 3: GET /api/alerts (with data)")
        response = client.get('/api/alerts')
        assert response.status_code == 200
        data = response.json()
        print_success(f"Returned {len(data['data'])} active alerts")

        # Test 4: GET /api/alerts?status=all
        print("\n  Test 4: GET /api/alerts?status=all")
        response = client.get('/api/alerts?status=all')
        assert response.status_code == 200
        data = response.json()
        print_success(f"Returned {len(data['data'])} total alerts (including resolved)")

        # Test 5: GET /api/alerts/stats
        print("\n  Test 5: GET /api/alerts/stats")
        response = client.get('/api/alerts/stats')
        assert response.status_code == 200
        data = response.json()
        stats = data['data']
        print_success(f"Stats: total={stats['total']}, active={stats['active']}, "
                     f"resolved={stats['resolved']}, critical={stats['critical']}, "
                     f"warning={stats['warning']}")

        # Test 6: GET /api/alerts/sensor/{sensor}
        print("\n  Test 6: GET /api/alerts/sensor/navi_lidar")
        response = client.get('/api/alerts/sensor/navi_lidar')
        assert response.status_code == 200
        data = response.json()
        print_success(f"Returned {len(data['data'])} navi_lidar alerts")

        # Test 7: GET /api/alerts/severity/{severity}
        print("\n  Test 7: GET /api/alerts/severity/critical")
        response = client.get('/api/alerts/severity/critical')
        assert response.status_code == 200
        data = response.json()
        print_success(f"Returned {len(data['data'])} critical alerts")

        # Test 8: POST /api/alerts/{id}/resolve
        print("\n  Test 8: POST /api/alerts/{id}/resolve")
        response = client.get('/api/alerts')
        data = response.json()
        if len(data['data']) > 0:
            alert_id = data['data'][0]['id']
            response = client.post(f'/api/alerts/{alert_id}/resolve')
            assert response.status_code == 200
            resolve_data = response.json()
            print_success(f"Resolve response: success={resolve_data['success']}")

            # Verify it's resolved
            response = client.get('/api/alerts')
            data = response.json()
            print_success(f"Active alerts after resolve: {len(data['data'])}")

        # Test 9: POST /api/alerts/{id}/ignore
        print("\n  Test 9: POST /api/alerts/{id}/ignore")
        response = client.get('/api/alerts')
        data = response.json()
        if len(data['data']) > 0:
            alert_id = data['data'][0]['id']
            response = client.post(f'/api/alerts/{alert_id}/ignore')
            assert response.status_code == 200
            ignore_data = response.json()
            print_success(f"Ignore response: success={ignore_data['success']}")

        # Test 10: Invalid severity
        print("\n  Test 10: GET /api/alerts/severity/invalid")
        response = client.get('/api/alerts/severity/invalid')
        assert response.status_code == 400
        data = response.json()
        print_success(f"Invalid severity returned {response.status_code}: success={data['success']}")

        print("\n  All API mock tests passed!")

    except Exception as e:
        print_error(f"API test failed: {e}")
        import traceback
        traceback.print_exc()
    finally:
        if os.path.exists(db_path):
            os.unlink(db_path)


def run_all_tests():
    """Run all mock tests"""
    print("\n" + "=" * 60)
    print(" ALERT SYSTEM MOCK TESTS")
    print("=" * 60)
    print("\nRunning standalone mock tests without actual sensors...")

    try:
        test_alert_store()
        test_diagnostic_mock()
        test_api_mock()

        print("\n" + "=" * 60)
        print(" ALL MOCK TESTS PASSED!")
        print("=" * 60)
        print("\nYou can also run pytest for more comprehensive testing:")
        print("  cd ros2_diagnostic")
        print("  pytest tests/ -v")
        print("\nFor specific test categories:")
        print("  pytest tests/unit/ -v        # Unit tests")
        print("  pytest tests/api/ -v          # API tests")
        print("  pytest tests/integration/ -v  # Integration tests")
        print()

    except Exception as e:
        print_error(f"\nTest suite failed: {e}")
        import traceback
        traceback.print_exc()
        sys.exit(1)


if __name__ == '__main__':
    run_all_tests()
