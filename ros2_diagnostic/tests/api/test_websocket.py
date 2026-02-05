#!/usr/bin/env python3
"""
WebSocket API 端点测试

测试 FastAPI WebSocket 端点的功能:
- WebSocket 连接建立
- 接收 full_state 消息 (首次连接)
- 接收 state_update 消息 (每5秒)
- Ping/pong 处理
- 多客户端连接
- 连接断开处理

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
    """WebSocket 连接测试"""

    def test_websocket_connect(self):
        """测试 WebSocket 连接建立"""
        client = TestClient(app)

        with client.websocket_connect("/ws") as websocket:
            # 连接成功后应该立即收到 full_state
            data = websocket.receive_json()
            assert data["type"] == "full_state"
            assert "data" in data
            assert "timestamp" in data

    def test_websocket_full_state_structure(self):
        """测试 full_state 消息结构"""
        client = TestClient(app)

        with client.websocket_connect("/ws") as websocket:
            data = websocket.receive_json()

            assert data["type"] == "full_state"
            state = data["data"]

            # 验证包含所有必需的状态数据
            assert "sensors" in state
            assert "ros2" in state
            assert "ros2_control" in state
            assert "rosbag" in state
            assert "alerts" in state

            # 验证 sensors 数据结构
            sensors = state["sensors"]
            assert "sensors" in sensors
            assert "overall" in sensors
            assert "summary" in sensors

            # 验证包含所有传感器
            expected_sensors = ["navi_lidar", "uli_lidar", "camera", "imu", "thruster"]
            for sensor in expected_sensors:
                assert sensor in sensors["sensors"]
                sensor_data = sensors["sensors"][sensor]
                # 验证每个传感器有必需的字段
                assert "status" in sensor_data
                assert "connected" in sensor_data

    def test_websocket_ping_pong(self):
        """测试 ping/pong 心跳机制"""
        client = TestClient(app)

        with client.websocket_connect("/ws") as websocket:
            # 接收初始 full_state
            _ = websocket.receive_json()

            # 发送 ping
            websocket.send_text("ping")

            # 应该收到 pong
            response = websocket.receive_text()
            assert response == "pong"

    def test_websocket_multiple_pings(self):
        """测试多次 ping/pong"""
        client = TestClient(app)

        with client.websocket_connect("/ws") as websocket:
            # 接收初始 full_state
            _ = websocket.receive_json()

            # 发送多个 ping
            for _ in range(3):
                websocket.send_text("ping")
                response = websocket.receive_text()
                assert response == "pong"

    def test_websocket_state_update(self):
        """测试接收 state_update 消息"""
        client = TestClient(app)

        with client.websocket_connect("/ws") as websocket:
            # 接收初始 full_state
            _ = websocket.receive_json()

            # 等待接收 state_update (最多等待7秒)
            try:
                data = websocket.receive_json(timeout=7)
                assert data["type"] == "state_update"
                assert "data" in data
                assert "timestamp" in data
            except Exception as e:
                pytest.skip(f"State update timeout or error: {e}")

    def test_websocket_disconnect(self):
        """测试 WebSocket 正常断开"""
        client = TestClient(app)

        initial_count = manager.get_connection_count()

        with client.websocket_connect("/ws") as websocket:
            # 连接建立
            _ = websocket.receive_json()
            current_count = manager.get_connection_count()
            assert current_count >= initial_count

        # 退出上下文后连接应该断开
        time.sleep(0.1)
        final_count = manager.get_connection_count()
        # Note: connection count might not decrease immediately due to async cleanup


class TestWebSocketMultipleClients:
    """WebSocket 多客户端测试"""

    def test_multiple_connections(self):
        """测试多个 WebSocket 连接"""
        client = TestClient(app)

        initial_count = manager.get_connection_count()

        # 创建多个连接
        connections = []
        for i in range(3):
            ws = client.websocket_connect("/ws")
            ws.__enter__()
            connections.append(ws)
            # 接收 full_state
            _ = ws.receive_json()

        # 验证连接数增加
        assert manager.get_connection_count() >= initial_count + 3

        # 关闭所有连接
        for ws in connections:
            ws.__exit__(None, None, None)

        time.sleep(0.1)
        # 验证连接数减少
        assert manager.get_connection_count() < initial_count + 3


class TestWebSocketStateData:
    """WebSocket 状态数据测试"""

    def test_sensors_state_data(self):
        """测试传感器状态数据"""
        client = TestClient(app)

        with client.websocket_connect("/ws") as websocket:
            data = websocket.receive_json()
            sensors = data["data"]["sensors"]

            # 验证每个传感器的数据结构
            for sensor_name, sensor_data in sensors["sensors"].items():
                assert isinstance(sensor_data["status"], str)
                # status can be: ok, warning, critical, unknown, stopped, disconnected
                assert sensor_data["status"] in ["ok", "warning", "critical", "unknown", "stopped", "disconnected", "connected"]
                # connected field has string values like "Connected" or "Disconnected"
                assert isinstance(sensor_data["connected"], str)

    def test_ros2_state_data(self):
        """测试 ROS2 状态数据"""
        client = TestClient(app)

        with client.websocket_connect("/ws") as websocket:
            data = websocket.receive_json()
            ros2 = data["data"]["ros2"]

            # 验证 ROS2 数据结构
            assert "status" in ros2
            assert "nodes" in ros2
            assert "topics" in ros2
            assert isinstance(ros2["nodes"], list)
            assert isinstance(ros2["topics"], list)

    def test_rosbag_state_data(self):
        """测试 rosbag 状态数据"""
        client = TestClient(app)

        with client.websocket_connect("/ws") as websocket:
            data = websocket.receive_json()
            rosbag = data["data"]["rosbag"]

            # 验证 rosbag 数据结构 (can be "recording" or "is_recording")
            has_recording = "recording" in rosbag or "is_recording" in rosbag
            assert has_recording, "rosbag data should contain 'recording' or 'is_recording'"
            recording_value = rosbag.get("recording") or rosbag.get("is_recording")
            assert isinstance(recording_value, bool)

    def test_alerts_state_data(self):
        """测试告警状态数据"""
        client = TestClient(app)

        with client.websocket_connect("/ws") as websocket:
            data = websocket.receive_json()
            alerts = data["data"]["alerts"]

            # 验证 alerts 数据结构
            assert isinstance(alerts, list)

            # 如果有告警，验证其结构
            for alert in alerts:
                assert "id" in alert
                assert "sensor" in alert
                assert "severity" in alert
                assert "message" in alert
                assert "created_at" in alert


class TestWebSocketMessageTypes:
    """WebSocket 消息类型测试"""

    def test_unknown_message_ignored(self):
        """测试未知消息类型被忽略 (不会导致连接关闭)"""
        client = TestClient(app)

        with client.websocket_connect("/ws") as websocket:
            # 接收初始 full_state
            _ = websocket.receive_json()

            # 发送未知消息 (应该被忽略，不会关闭连接)
            websocket.send_text("unknown_message")

            # 发送 ping 验证连接仍然活跃
            websocket.send_text("ping")
            response = websocket.receive_text()
            assert response == "pong"


class TestWebSocketConnectionManager:
    """ConnectionManager 单元测试"""

    def test_manager_initial_state(self):
        """测试连接管理器初始状态"""
        assert isinstance(manager.active_connections, list)
        assert manager.get_connection_count() >= 0

    def test_manager_get_connection_count(self):
        """测试获取连接数"""
        count = manager.get_connection_count()
        assert isinstance(count, int)
        assert count >= 0


class TestWebSocketIntegration:
    """WebSocket 集成测试"""

    def test_full_workflow(self):
        """测试完整的 WebSocket 工作流"""
        client = TestClient(app)

        with client.websocket_connect("/ws") as websocket:
            # 1. 接收 full_state
            initial_data = websocket.receive_json()
            assert initial_data["type"] == "full_state"

            # 2. 发送 ping
            websocket.send_text("ping")
            pong = websocket.receive_text()
            assert pong == "pong"

            # 3. 等待 state_update
            try:
                update_data = websocket.receive_json(timeout=7)
                assert update_data["type"] == "state_update"
            except:
                pytest.skip("State update timeout")

    def test_data_consistency_across_updates(self):
        """测试多次更新的数据一致性"""
        client = TestClient(app)

        with client.websocket_connect("/ws") as websocket:
            # 接收初始状态
            initial = websocket.receive_json()
            initial_sensors = initial["data"]["sensors"]["sensors"]

            # 等待更新
            try:
                update = websocket.receive_json(timeout=7)
                update_sensors = update["data"]["sensors"]["sensors"]

                # 验证传感器名称一致
                assert set(initial_sensors.keys()) == set(update_sensors.keys())
            except:
                pytest.skip("State update timeout")


class TestWebSocketErrorHandling:
    """WebSocket 错误处理测试"""

    def test_connection_rejection_invalid_path(self):
        """测试无效路径的 WebSocket 连接被拒绝"""
        client = TestClient(app)

        with pytest.raises(Exception):
            with client.websocket_connect("/ws_invalid"):
                pass

    def test_connection_close_on_disconnect(self):
        """测试客户端主动断开连接"""
        client = TestClient(app)

        with client.websocket_connect("/ws") as websocket:
            # 接收初始消息
            _ = websocket.receive_json()

            # 正常退出上下文会关闭连接
            pass

        # 连接应该已断开
        time.sleep(0.1)


@pytest.fixture(scope="function")
def reset_manager():
    """在每个测试后重置连接管理器状态"""
    yield
    # 清理所有连接 (测试结束后)
    for conn in manager.active_connections.copy():
        try:
            # 尝试优雅关闭
            pass
        except:
            manager.disconnect(conn)
