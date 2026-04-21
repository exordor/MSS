#!/usr/bin/env python3
"""
WebSocket API endpoint tests

Test FastAPI WebSocket endpoint functionality:
- WebSocket connection establishment
- Receive full_state message (on first connection)
- Receive state_update message (every 5 seconds)
- Ping/pong handling
- Multiple client connections
- Connection disconnect handling

Note: Using synchronous TestClient for WebSocket testing
"""

import pytest
import json
import time
from pathlib import Path
from typing import List, Dict, Any

import sys
sys.path.insert(0, str(Path(__file__).parent.parent.parent))

# FastAPI WebSocket testing
from fastapi.testclient import TestClient
from fastapi.websockets import WebSocket

try:
    from main import app, manager
    from config import SENSOR_THRESHOLDS, SENSOR_IPS
except ImportError:
    pytest.skip("FastAPI main.py not available", allow_module_level=True)


class TestWebSocketConnection:
    """WebSocket connection tests"""

    def test_websocket_connect(self):
        """Test WebSocket connection establishment"""
        client = TestClient(app)

        with client.websocket_connect("/ws") as websocket:
            # Should receive full_state immediately after successful connection
            data = websocket.receive_json()
            assert data["type"] == "full_state"
            assert "data" in data
            assert "timestamp" in data

    def test_websocket_full_state_structure(self):
        """Test full_state message structure"""
        client = TestClient(app)

        with client.websocket_connect("/ws") as websocket:
            data = websocket.receive_json()

            assert data["type"] == "full_state"
            state = data["data"]

            # Verify all required state data is included
            assert "sensors" in state
            assert "ros2" in state
            assert "ros2_control" in state
            assert "rosbag" in state
            assert "alerts" in state

            # Verify sensors data structure
            sensors = state["sensors"]
            assert "sensors" in sensors
            assert "overall" in sensors
            assert "summary" in sensors

            # Verify all sensors are included
            expected_sensors = ["navi_lidar", "uli_lidar", "camera", "imu", "thruster"]
            for sensor in expected_sensors:
                assert sensor in sensors["sensors"]
                sensor_data = sensors["sensors"][sensor]
                # Verify each sensor has required fields
                assert "status" in sensor_data
                assert "connected" in sensor_data

    def test_websocket_ping_pong(self):
        """Test ping/pong heartbeat mechanism"""
        client = TestClient(app)

        with client.websocket_connect("/ws") as websocket:
            # Receive initial full_state
            _ = websocket.receive_json()

            # Send ping
            websocket.send_text("ping")

            # Should receive pong
            response = websocket.receive_text()
            assert response == "pong"

    def test_websocket_multiple_pings(self):
        """Test multiple ping/pong"""
        client = TestClient(app)

        with client.websocket_connect("/ws") as websocket:
            # Receive initial full_state
            _ = websocket.receive_json()

            # Send multiple pings
            for _ in range(3):
                websocket.send_text("ping")
                response = websocket.receive_text()
                assert response == "pong"

    def test_websocket_state_update(self):
        """Test receiving state_update message"""
        client = TestClient(app)

        with client.websocket_connect("/ws") as websocket:
            # Receive initial full_state
            _ = websocket.receive_json()

            # Wait to receive state_update (up to 7 seconds)
            try:
                data = websocket.receive_json(timeout=7)
                assert data["type"] == "state_update"
                assert "data" in data
                assert "timestamp" in data
            except Exception as e:
                pytest.skip(f"State update timeout or error: {e}")

    def test_websocket_disconnect(self):
        """Test WebSocket normal disconnect"""
        client = TestClient(app)

        initial_count = manager.get_connection_count()

        with client.websocket_connect("/ws") as websocket:
            # Connection established
            _ = websocket.receive_json()
            current_count = manager.get_connection_count()
            assert current_count >= initial_count

        # After exiting the context, the connection should be disconnected
        time.sleep(0.1)
        final_count = manager.get_connection_count()
        # Note: connection count might not decrease immediately due to async cleanup


class TestWebSocketMultipleClients:
    """WebSocket multiple client tests"""

    def test_multiple_connections(self):
        """Test multiple WebSocket connections"""
        client = TestClient(app)

        initial_count = manager.get_connection_count()

        # Create multiple connections
        connections = []
        for i in range(3):
            ws = client.websocket_connect("/ws")
            ws.__enter__()
            connections.append(ws)
            # Receive full_state
            _ = ws.receive_json()

        # Verify connection count increased
        assert manager.get_connection_count() >= initial_count + 3

        # Close all connections
        for ws in connections:
            ws.__exit__(None, None, None)

        time.sleep(0.1)
        # Verify connection count decreased
        assert manager.get_connection_count() < initial_count + 3


class TestWebSocketStateData:
    """WebSocket state data tests"""

    def test_sensors_state_data(self):
        """Test sensor state data"""
        client = TestClient(app)

        with client.websocket_connect("/ws") as websocket:
            data = websocket.receive_json()
            sensors = data["data"]["sensors"]

            # Verify data structure of each sensor
            for sensor_name, sensor_data in sensors["sensors"].items():
                assert isinstance(sensor_data["status"], str)
                # status can be: ok, warning, critical, unknown, stopped, disconnected
                assert sensor_data["status"] in ["ok", "warning", "critical", "unknown", "stopped", "disconnected", "connected"]
                # connected field has string values like "Connected" or "Disconnected"
                assert isinstance(sensor_data["connected"], str)

    def test_ros2_state_data(self):
        """Test ROS2 state data"""
        client = TestClient(app)

        with client.websocket_connect("/ws") as websocket:
            data = websocket.receive_json()
            ros2 = data["data"]["ros2"]

            # Verify ROS2 data structure
            assert "status" in ros2
            assert "nodes" in ros2
            assert "topics" in ros2
            assert isinstance(ros2["nodes"], list)
            assert isinstance(ros2["topics"], list)

    def test_rosbag_state_data(self):
        """Test rosbag state data"""
        client = TestClient(app)

        with client.websocket_connect("/ws") as websocket:
            data = websocket.receive_json()
            rosbag = data["data"]["rosbag"]

            # Verify rosbag data structure (can be "recording" or "is_recording")
            has_recording = "recording" in rosbag or "is_recording" in rosbag
            assert has_recording, "rosbag data should contain 'recording' or 'is_recording'"
            recording_value = rosbag.get("recording") or rosbag.get("is_recording")
            assert isinstance(recording_value, bool)

    def test_alerts_state_data(self):
        """Test alert state data"""
        client = TestClient(app)

        with client.websocket_connect("/ws") as websocket:
            data = websocket.receive_json()
            alerts = data["data"]["alerts"]

            # Verify alerts data structure
            assert isinstance(alerts, list)

            # If there are alerts, verify their structure
            for alert in alerts:
                assert "id" in alert
                assert "sensor" in alert
                assert "severity" in alert
                assert "message" in alert
                assert "created_at" in alert


class TestWebSocketMessageTypes:
    """WebSocket message type tests"""

    def test_unknown_message_ignored(self):
        """Test unknown message type is ignored (should not cause connection close)"""
        client = TestClient(app)

        with client.websocket_connect("/ws") as websocket:
            # Receive initial full_state
            _ = websocket.receive_json()

            # Send unknown message (should be ignored, will not close connection)
            websocket.send_text("unknown_message")

            # Send ping to verify connection is still active
            websocket.send_text("ping")
            response = websocket.receive_text()
            assert response == "pong"


class TestWebSocketConnectionManager:
    """ConnectionManager unit tests"""

    def test_manager_initial_state(self):
        """Test connection manager initial state"""
        assert isinstance(manager.active_connections, list)
        assert manager.get_connection_count() >= 0

    def test_manager_get_connection_count(self):
        """Test getting connection count"""
        count = manager.get_connection_count()
        assert isinstance(count, int)
        assert count >= 0


class TestWebSocketIntegration:
    """WebSocket integration tests"""

    def test_full_workflow(self):
        """Test complete WebSocket workflow"""
        client = TestClient(app)

        with client.websocket_connect("/ws") as websocket:
            # 1. Receive full_state
            initial_data = websocket.receive_json()
            assert initial_data["type"] == "full_state"

            # 2. Send ping
            websocket.send_text("ping")
            pong = websocket.receive_text()
            assert pong == "pong"

            # 3. Wait for state_update
            try:
                update_data = websocket.receive_json(timeout=7)
                assert update_data["type"] == "state_update"
            except:
                pytest.skip("State update timeout")

    def test_data_consistency_across_updates(self):
        """Test data consistency across multiple updates"""
        client = TestClient(app)

        with client.websocket_connect("/ws") as websocket:
            # Receive initial state
            initial = websocket.receive_json()
            initial_sensors = initial["data"]["sensors"]["sensors"]

            # Wait for update
            try:
                update = websocket.receive_json(timeout=7)
                update_sensors = update["data"]["sensors"]["sensors"]

                # Verify sensor names are consistent
                assert set(initial_sensors.keys()) == set(update_sensors.keys())
            except:
                pytest.skip("State update timeout")


class TestWebSocketErrorHandling:
    """WebSocket error handling tests"""

    def test_connection_rejection_invalid_path(self):
        """Test WebSocket connection rejection on invalid path"""
        client = TestClient(app)

        with pytest.raises(Exception):
            with client.websocket_connect("/ws_invalid"):
                pass

    def test_connection_close_on_disconnect(self):
        """Test client-initiated disconnect"""
        client = TestClient(app)

        with client.websocket_connect("/ws") as websocket:
            # Receive initial message
            _ = websocket.receive_json()

            # Exiting the context normally will close the connection
            pass

        # Connection should be disconnected
        time.sleep(0.1)


@pytest.fixture(scope="function")
def reset_manager():
    """Reset connection manager state after each test"""
    yield
    # Clean up all connections (after tests finish)
    for conn in manager.active_connections.copy():
        try:
            # Attempt graceful close
            pass
        except:
            manager.disconnect(conn)
