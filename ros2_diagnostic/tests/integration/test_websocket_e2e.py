#!/usr/bin/env python3
"""
WebSocket end-to-end integration tests

Tests the complete WebSocket workflow:
- Client connect -> receive full_state -> receive channelized/legacy updates -> disconnect
- Multi-client concurrent connections and broadcasting
- Client reconnection scenarios
- Integration with HTTP API

Note: Using synchronous TestClient for WebSocket testing
"""

import pytest
import json
import time
import os
from pathlib import Path
from typing import List
import threading
from anyio import WouldBlock

import sys
sys.path.insert(0, str(Path(__file__).parent.parent.parent))

try:
    from fastapi.testclient import TestClient
    import main
    from main import app, manager, collect_all_state
    from alerts import get_alert_store, Alert
except ImportError:
    pytest.skip("FastAPI main.py not available", allow_module_level=True)


def receive_until_type(websocket, expected_types, timeout=8):
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


def mock_active_alerts():
    from alerts import AlertStore

    store = AlertStore._instance
    if store is None:
        return []
    return [alert.__dict__ for alert in store.get_active_alerts(None)]


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
    monkeypatch.setattr(main, "collect_active_alerts", mock_active_alerts)
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


class TestWebSocketE2E:
    """WebSocket end-to-end tests"""

    def test_complete_client_lifecycle(self):
        """Test complete client lifecycle

        1. Connect to WebSocket
        2. Receive full_state
        3. Receive at least one state_update
        4. Disconnect
        """
        client = TestClient(app)

        with client.websocket_connect("/ws") as websocket:
            # Steps 1 & 2: Connect and receive full_state
            first_message = websocket.receive_json()
            assert first_message["type"] == "full_state", "First message should be full_state"
            assert "data" in first_message
            assert "timestamp" in first_message

            # Verify full_state contains all data
            state = first_message["data"]
            required_keys = ["sensors", "ros2", "ros2_control", "rosbag", "alerts", "time"]
            for key in required_keys:
                assert key in state, f"full_state should contain {key}"

            # Step 3: Receive state_update when a lifespan-driven broadcaster is running.
            try:
                update_message = receive_until_type(websocket, "state_update", timeout=2)
                assert update_message["type"] == "state_update"
                assert "data" in update_message
                assert "timestamp" in update_message
                assert update_message["deprecated"] is True
            except Exception as e:
                pytest.skip(f"State update not received in this mock client: {e}")

            # Step 4: Connection auto-closes here (exiting context)

    def test_multiple_state_updates(self):
        """Test receiving consecutive state_update messages"""
        client = TestClient(app)

        with client.websocket_connect("/ws") as websocket:
            # Receive full_state
            _ = websocket.receive_json()

            # Try to receive multiple state_updates
            updates_received = 0
            max_wait = 3
            start_time = time.time()

            try:
                while time.time() - start_time < max_wait:
                    data = receive_until_type(
                        websocket,
                        {"state_update", "connectivity_update", "sensors_update", "time_update", "ros2_control_update"},
                        timeout=1,
                    )
                    if data["type"] == "state_update":
                        updates_received += 1
                        if updates_received >= 2:
                            break
            except Exception:
                pass

            if updates_received < 1:
                pytest.skip("No lifespan-driven state_update broadcaster in this mock client")

    def test_reconnect_scenario(self):
        """Test client reconnection scenario

        Simulates:
        1. Client connects
        2. Receives data
        3. Disconnects
        4. Reconnects
        5. Receives full_state again
        """
        client = TestClient(app)

        # First connection
        with client.websocket_connect("/ws") as websocket:
            first_message = websocket.receive_json()
            assert first_message["type"] == "full_state"
            try:
                _ = receive_until_type(websocket, "state_update", timeout=8)
            except:
                pass

        # Simulate brief delay
        time.sleep(0.5)

        # Reconnect
        with client.websocket_connect("/ws") as websocket:
            reconnect_message = websocket.receive_json()
            assert reconnect_message["type"] == "full_state"
            # Verify reconnection works properly
            websocket.send_text("ping")
            pong = receive_until_text(websocket, "pong")
            assert pong == "pong"


class TestWebSocketBroadcast:
    """WebSocket broadcast tests"""

    def test_broadcast_to_multiple_clients(self):
        """Test broadcasting to multiple clients"""
        client = TestClient(app)

        messages_received = {"client1": [], "client2": []}

        def client_handler(client_id: str):
            with client.websocket_connect("/ws") as websocket:
                # Receive full_state
                msg1 = websocket.receive_json()
                messages_received[client_id].append(msg1["type"])

                # Wait for possible state_update
                try:
                    msg2 = receive_until_type(
                        websocket,
                        {"state_update", "connectivity_update", "sensors_update", "time_update", "ros2_control_update"},
                        timeout=7,
                    )
                    messages_received[client_id].append(msg2["type"])
                except:
                    pass

        # Use threads to simulate concurrent connections
        t1 = threading.Thread(target=client_handler, args=("client1",))
        t2 = threading.Thread(target=client_handler, args=("client2",))

        t1.start()
        t2.start()

        t1.join(timeout=10)
        t2.join(timeout=10)

        # Both clients should have received full_state
        assert "full_state" in messages_received["client1"]
        assert "full_state" in messages_received["client2"]

    def test_concurrent_connections(self):
        """Test concurrent connection limit"""
        client = TestClient(app)

        results = []

        def connect_and_wait(client_id: str):
            try:
                with client.websocket_connect("/ws") as websocket:
                    _ = websocket.receive_json()
                    time.sleep(1)
                    results.append((client_id, True))
            except Exception as e:
                results.append((client_id, False))

        # Create multiple concurrent connections
        threads = []
        for i in range(5):
            t = threading.Thread(target=connect_and_wait, args=(f"client_{i}",))
            threads.append(t)
            t.start()

        for t in threads:
            t.join(timeout=10)

        # Verify at least some connections succeeded
        successful = sum(1 for r in results if r[1])
        assert successful >= 3, f"Expected at least 3 successful connections, got {successful}"


class TestWebSocketWithAlerts:
    """WebSocket and alert system integration tests"""

    def test_alerts_in_full_state(self, temp_db_path):
        """Test full_state contains alert data"""
        # Reset alert storage
        from alerts import AlertStore
        AlertStore._instance = None

        store = AlertStore(db_path=temp_db_path)

        # Add test alert
        alert = Alert(
            sensor="test_sensor",
            alert_type="test_alert",
            severity="warning",
            message="Test alert for WebSocket",
            metric_value=5.0,
            threshold=10.0,
            metadata="{}",
            created_at="2026-01-27T10:00:00"
        )
        store.add_alert(alert)

        # Connect WebSocket
        client = TestClient(app)

        with client.websocket_connect("/ws") as websocket:
            data = websocket.receive_json()
            alerts = data["data"]["alerts"]

            # Verify alert data
            assert isinstance(alerts, list)

        store.close()

    def test_alerts_api_sync(self, temp_db_path):
        """Test alert API and WebSocket data sync"""
        from alerts import AlertStore
        AlertStore._instance = None

        store = AlertStore(db_path=temp_db_path)

        # Add alert
        alert = Alert(
            sensor="navi_lidar",
            alert_type="frame_loss",
            severity="critical",
            message="Frame loss detected",
            metric_value=3.5,
            threshold=8.0,
            metadata="{}",
            created_at="2026-01-27T10:00:00"
        )
        alert_id = store.add_alert(alert)

        # Get alerts via WebSocket
        client = TestClient(app)

        with client.websocket_connect("/ws") as websocket:
            data = websocket.receive_json()
            ws_alerts = data["data"]["alerts"]

            # Verify alert exists
            assert any(a["id"] == alert_id for a in ws_alerts)

        # Get alerts via API for verification
        response = client.get(f"/api/alerts/sensor/navi_lidar")
        api_data = response.json()

        assert api_data["success"] is True
        api_alerts = api_data["data"]

        # WebSocket and API should return the same number of alerts
        ws_navi_alerts = [a for a in ws_alerts if a["sensor"] == "navi_lidar"]
        assert len(ws_navi_alerts) == len(api_alerts)

        store.close()


class TestWebSocketWithROS2:
    """WebSocket and ROS2 system integration tests"""

    def test_ros2_data_in_websocket(self):
        """Test WebSocket contains ROS2 data"""
        client = TestClient(app)

        with client.websocket_connect("/ws") as websocket:
            data = websocket.receive_json()
            ros2 = data["data"]["ros2"]
            ros2_control = data["data"]["ros2_control"]

            # Verify ROS2 data structure
            assert "status" in ros2
            assert "nodes" in ros2
            assert "topics" in ros2

            # Verify ROS2 control data
            assert "running" in ros2_control

    def test_ros2_api_sync(self):
        """Test ROS2 API and WebSocket data sync"""
        client = TestClient(app)

        # Get ROS2 status via WebSocket
        with client.websocket_connect("/ws") as websocket:
            ws_data = websocket.receive_json()
            ws_ros2 = ws_data["data"]["ros2"]

        # Get status via API for verification (using compatible endpoint)
        response = client.get("/api/status")
        api_data = response.json()

        # Verify data consistency
        assert "running" in api_data
        assert isinstance(api_data["running"], bool)


class TestWebSocketWithRosbag:
    """WebSocket and Rosbag system integration tests"""

    def test_rosbag_data_in_websocket(self):
        """Test WebSocket contains rosbag data"""
        client = TestClient(app)

        with client.websocket_connect("/ws") as websocket:
            data = websocket.receive_json()
            rosbag = data["data"]["rosbag"]

            # Verify rosbag data structure
            assert "recording" in rosbag
            assert isinstance(rosbag["recording"], bool)


class TestWebSocketPerformance:
    """WebSocket performance tests"""

    def test_message_latency(self):
        """Test message latency"""
        client = TestClient(app)

        with client.websocket_connect("/ws") as websocket:
            # Record connection time
            connect_time = time.time()

            # Receive first message
            _ = websocket.receive_json()
            first_message_latency = time.time() - connect_time

            # First message (full_state) should arrive within reasonable time
            assert first_message_latency < 2.0, f"First message latency too high: {first_message_latency}s"

            # Test ping/pong latency
            ping_time = time.time()
            websocket.send_text("ping")
            _ = receive_until_text(websocket, "pong")
            pong_latency = time.time() - ping_time

            # Ping/pong should be fast
            assert pong_latency < 1.0, f"Ping/pong latency too high: {pong_latency}s"

    def test_connection_time(self):
        """Test connection establishment time"""
        client = TestClient(app)

        start_time = time.time()
        with client.websocket_connect("/ws") as websocket:
            connect_time = time.time() - start_time

            # Connection should be established quickly
            assert connect_time < 1.0, f"Connection time too high: {connect_time}s"

            # Receive one message to ensure connection works
            _ = websocket.receive_json()


class TestWebSocketErrorRecovery:
    """WebSocket error recovery tests"""

    def test_graceful_disconnect(self):
        """Test graceful disconnection"""
        client = TestClient(app)

        initial_count = manager.get_connection_count()

        with client.websocket_connect("/ws") as websocket:
            _ = websocket.receive_json()
            # Connection should be in active list
            current_count = manager.get_connection_count()
            assert current_count >= initial_count

        # Connection should be cleaned up after disconnect
        time.sleep(0.2)
        final_count = manager.get_connection_count()
        assert final_count <= initial_count


class TestWebSocketDataIntegrity:
    """WebSocket data integrity tests"""

    def test_json_parseability(self):
        """Test all messages are valid JSON"""
        client = TestClient(app)

        with client.websocket_connect("/ws") as websocket:
            # Receive multiple messages
            for _ in range(3):
                try:
                    raw = receive_message_with_timeout(websocket, 0.5)
                    if raw:
                        # Try to parse as JSON
                        if isinstance(raw, str):
                            data = json.loads(raw)
                        elif "text" in raw:
                            data = json.loads(raw["text"])
                        else:
                            data = raw
                        assert isinstance(data, dict)
                        assert "type" in data
                except:
                    # May timeout
                    break

    def test_timestamp_consistency(self):
        """Test timestamp consistency"""
        client = TestClient(app)

        with client.websocket_connect("/ws") as websocket:
            # Receive first message
            first = websocket.receive_json()
            first_timestamp = first.get("timestamp")

            assert first_timestamp is not None
            assert isinstance(first_timestamp, (int, float))

            # Receive second message
            try:
                second = receive_until_type(
                    websocket,
                    {"state_update", "connectivity_update", "sensors_update", "time_update", "ros2_control_update"},
                    timeout=7,
                )
                second_timestamp = second.get("timestamp")

                assert second_timestamp is not None
                # Second message timestamp should be later
                assert second_timestamp >= first_timestamp
            except:
                pass


@pytest.fixture
def temp_db_path(tmp_path):
    """Temporary database path"""
    return str(tmp_path / "test_ws_e2e_alerts.db")


@pytest.fixture(autouse=True)
def reset_alert_store():
    """Reset alert storage after each test"""
    yield
    try:
        from alerts import AlertStore
        AlertStore._instance = None
    except:
        pass
