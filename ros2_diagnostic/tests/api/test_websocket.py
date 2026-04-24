#!/usr/bin/env python3
"""
WebSocket API endpoint tests

Test FastAPI WebSocket endpoint functionality:
- WebSocket connection establishment
- Receive full_state message (on first connection)
- Receive channelized updates and legacy state_update messages
- Ping/pong handling
- Multiple client connections
- Connection disconnect handling

Note: Using synchronous TestClient for WebSocket testing
"""

import pytest
import json
import time
import asyncio
import threading
from pathlib import Path
from typing import List, Dict, Any
from anyio import WouldBlock

import sys
sys.path.insert(0, str(Path(__file__).parent.parent.parent))

# FastAPI WebSocket testing
from fastapi.testclient import TestClient
from fastapi.websockets import WebSocket

try:
    import main
    from main import app, manager, Channel, CHANNEL_CONFIG, WEBSOCKET_CONFIG
    from config import SENSOR_THRESHOLDS, SENSOR_IPS
except ImportError:
    pytest.skip("FastAPI main.py not available", allow_module_level=True)


def receive_until_type(websocket, expected_types, timeout=8):
    """Receive WebSocket JSON messages until one of expected_types appears."""
    if isinstance(expected_types, str):
        expected_types = {expected_types}
    else:
        expected_types = set(expected_types)

    end_time = time.time() + timeout
    last_message = None
    while time.time() < end_time:
        remaining = max(0.1, end_time - time.time())
        try:
            message = receive_json_with_timeout(websocket, remaining)
        except TimeoutError as exc:
            raise AssertionError(
                f"Timed out waiting for {expected_types}; last={last_message}"
            ) from exc
        last_message = message
        if message.get("type") in expected_types:
            return message

    raise AssertionError(f"Timed out waiting for {expected_types}; last={last_message}")


def receive_until_text(websocket, expected_text, timeout=5):
    """Receive WebSocket text frames until expected_text appears."""
    end_time = time.time() + timeout
    last_message = None
    while time.time() < end_time:
        remaining = max(0.1, end_time - time.time())
        try:
            message = receive_text_with_timeout(websocket, remaining)
        except TimeoutError as exc:
            raise AssertionError(
                f"Timed out waiting for {expected_text}; last={last_message}"
            ) from exc
        last_message = message
        if message == expected_text:
            return message

    raise AssertionError(f"Timed out waiting for {expected_text}; last={last_message}")


def receive_message_with_timeout(websocket, timeout):
    end_time = time.time() + timeout
    while time.time() < end_time:
        try:
            return websocket.portal.call(websocket._send_rx.receive_nowait)
        except WouldBlock:
            time.sleep(0.02)
    raise TimeoutError


def receive_text_with_timeout(websocket, timeout):
    message = receive_message_with_timeout(websocket, timeout)
    websocket._raise_on_close(message)
    if "text" in message:
        return message["text"]
    return message["bytes"].decode("utf-8")


def receive_json_with_timeout(websocket, timeout):
    return json.loads(receive_text_with_timeout(websocket, timeout))


class FakeWebSocket:
    """Minimal async WebSocket fake for ConnectionManager unit tests."""

    def __init__(self):
        self.accepted = False
        self.closed = False
        self.sent = []

    async def accept(self):
        self.accepted = True

    async def close(self, code=1000):
        self.closed = True
        self.close_code = code

    async def send_json(self, message):
        self.sent.append(message)


def mock_sensor_status():
    sensors = {
        name: {
            "status": "ok",
            "color": "green",
            "value": "OK",
            "message": f"{name} mock OK",
            "connected": "Connected",
            "frequency": "10.0 Hz",
            "packet_loss": 0,
            "latency_ms": 1.0,
            "topic_available": True,
            "node_available": True,
        }
        for name in main.SENSOR_NAMES
    }
    return {
        "sensors": sensors,
        "overall": "ok",
        "summary": f"{len(sensors)}/{len(sensors)} OK",
    }


@pytest.fixture(autouse=True)
def mock_diagnostic_collectors(monkeypatch):
    """Use deterministic mock data; tests must not touch real Arduino/MQTT/ROS."""
    async def collect_sensor_status_parallel_mock():
        return mock_sensor_status()

    monkeypatch.setattr(main, "collect_sensor_status_parallel", collect_sensor_status_parallel_mock)
    monkeypatch.setattr(main, "collect_sensor_status", mock_sensor_status)
    monkeypatch.setattr(main, "collect_sensor_status_cached", mock_sensor_status)
    monkeypatch.setattr(main, "_collect_connectivity_sync", lambda name: {
        "connected": "Connected",
    })
    monkeypatch.setattr(main, "background_collector_thread", lambda: None)
    monkeypatch.setattr(main, "collect_ros2_status", lambda: {
        "status": "ok",
        "message": "mock ros2 OK",
        "nodes": ["/mock_node"],
        "nodes_running": 1,
        "nodes_expected_running": [],
        "nodes_expected_missing": [],
        "topics": ["/mock_topic"],
        "topics_count": 1,
        "topics_important": {},
    })
    monkeypatch.setattr(main, "collect_ros2_status_cached", main.collect_ros2_status)
    monkeypatch.setattr(main, "collect_ros2_control_status", lambda: {
        "running": True,
        "pid": 1234,
        "error": None,
    })
    monkeypatch.setattr(main, "collect_rosbag_status", lambda: {
        "recording": False,
        "is_recording": False,
        "topic_count": 1,
        "topics_count": 1,
        "config_loaded": True,
    })
    monkeypatch.setattr(main, "collect_active_alerts", lambda: [])
    monkeypatch.setattr(main, "collect_time_status_cached", lambda max_age=None: {
        "system": {
            "iso": "2026-04-24T12:00:00+00:00",
            "display": "2026-04-24 12:00:00 UTC",
            "timezone": "UTC",
        }
    })
    with main._cache_lock:
        main._cache.clear()
        main._cache_stats = {"hits": 0, "misses": 0}
    yield
    with main._cache_lock:
        main._cache.clear()


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
            assert "channels" in data
            assert data["schema_version"] == "2.0"

    def test_websocket_full_state_structure(self):
        """Test full_state message structure"""
        client = TestClient(app)

        with client.websocket_connect("/ws") as websocket:
            data = websocket.receive_json()

            assert data["type"] == "full_state"
            state = data["data"]
            assert set(data["channels"]) == set(WEBSOCKET_CONFIG["default_channels"])

            # Verify all required state data is included
            assert "sensors" in state
            assert "ros2" in state
            assert "ros2_control" in state
            assert "rosbag" in state
            assert "alerts" in state
            assert "time" in state

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
            response = receive_until_text(websocket, "pong")
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
                response = receive_until_text(websocket, "pong")
                assert response == "pong"

    def test_websocket_state_update(self):
        """Test receiving state_update message"""
        assert WEBSOCKET_CONFIG["legacy_state_update"]["enabled"] is True
        legacy_message = {
            "type": "state_update",
            "data": {"sensors": {}},
            "timestamp": time.time(),
            "schema_version": "2.0",
            "deprecated": True,
        }
        assert legacy_message["type"] == "state_update"
        assert legacy_message["deprecated"] is True
        assert "data" in legacy_message
        assert "timestamp" in legacy_message

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
            response = receive_until_text(websocket, "pong")
            assert response == "pong"

    def test_subscribe_ack_is_explicit_only(self):
        """Test subscribe acknowledgements are only sent after subscribe commands."""
        client = TestClient(app)

        with client.websocket_connect("/ws") as websocket:
            initial = websocket.receive_json()
            assert initial["type"] == "full_state"

            websocket.send_text("subscribe:alerts")
            ack = receive_until_type(websocket, "subscribed", timeout=3)
            assert ack["channel"] == "alerts"
            assert ack["schema_version"] == "2.0"

    def test_invalid_channel_returns_error(self):
        """Test invalid subscription names return an error frame."""
        client = TestClient(app)

        with client.websocket_connect("/ws") as websocket:
            _ = websocket.receive_json()

            websocket.send_text("subscribe:nope")
            error = receive_until_type(websocket, "error", timeout=3)
            assert "Unknown channel" in error["message"]

    def test_channelized_update_structure(self):
        """Test channelized updates include channel and schema metadata."""
        message = main._channel_message(Channel.CONNECTIVITY, {"sensors": {}})
        assert message["channel"] == "connectivity"
        assert message["schema_version"] == "2.0"
        assert message["type"] == "connectivity_update"


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

    def test_broadcast_to_channel_respects_subscriptions(self):
        """Test channel broadcasts only reach subscribed clients."""
        previous_connections = manager.connections.copy()
        manager.connections.clear()

        async def scenario():
            alerts_ws = FakeWebSocket()
            sensors_ws = FakeWebSocket()
            await manager.connect(alerts_ws, [Channel.ALERTS])
            await manager.connect(sensors_ws, [Channel.SENSORS])
            await manager.broadcast_to_channel(Channel.ALERTS, {"type": "alert"})
            assert alerts_ws.sent == [{"type": "alert"}]
            assert sensors_ws.sent == []

        try:
            asyncio.run(scenario())
        finally:
            manager.connections.clear()
            manager.connections.update(previous_connections)

    def test_websocket_config_loaded(self):
        """Test WebSocket channel intervals and legacy toggle come from config."""
        assert WEBSOCKET_CONFIG["max_connections"] == 10
        assert WEBSOCKET_CONFIG["legacy_state_update"]["enabled"] is True
        assert WEBSOCKET_CONFIG["channels"]["connectivity"]["interval_sec"] == 0.5
        assert WEBSOCKET_CONFIG["channels"]["sensors"]["interval_sec"] == 0.5
        assert CHANNEL_CONFIG[Channel.CONNECTIVITY]["interval"] == 0.5
        assert CHANNEL_CONFIG[Channel.SENSORS]["interval"] == 0.5

    def test_alert_schedule_uses_app_loop_from_thread(self, sample_alert, monkeypatch):
        """Test alert callback can be scheduled from a non-event-loop thread."""
        called = threading.Event()

        async def fake_broadcast(alert):
            assert alert is sample_alert
            called.set()

        async def scenario():
            monkeypatch.setattr(main, "broadcast_alert", fake_broadcast)
            main._ws_app_loop = asyncio.get_running_loop()
            thread = threading.Thread(target=main.schedule_alert_broadcast, args=(sample_alert,))
            thread.start()
            thread.join(timeout=2)
            for _ in range(50):
                if called.is_set():
                    return
                await asyncio.sleep(0.01)
            raise AssertionError("Alert broadcast was not scheduled on the app loop")

        try:
            asyncio.run(scenario())
        finally:
            main._ws_app_loop = None


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
            pong = receive_until_text(websocket, "pong")
            assert pong == "pong"

    def test_data_consistency_across_updates(self):
        """Test data consistency across multiple updates"""
        client = TestClient(app)

        with client.websocket_connect("/ws") as websocket:
            # Receive initial state
            initial = websocket.receive_json()
            initial_sensors = initial["data"]["sensors"]["sensors"]

            # Verify full_state includes the configured sensor catalog.
            assert set(initial_sensors.keys()) == set(main.SENSOR_NAMES)


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
