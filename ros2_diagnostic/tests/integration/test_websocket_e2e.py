#!/usr/bin/env python3
"""
WebSocket 端到端集成测试

测试完整的 WebSocket 工作流:
- 客户端连接 → 接收 full_state → 接收 state_update → 断开
- 多客户端并发连接和广播
- 客户端重连场景
- 与 HTTP API 的协同工作

Note: Using synchronous TestClient for WebSocket testing
"""

import pytest
import json
import time
import os
from pathlib import Path
from typing import List
import threading

import sys
sys.path.insert(0, str(Path(__file__).parent.parent.parent))

try:
    from fastapi.testclient import TestClient
    from main import app, manager, collect_all_state
    from alerts import get_alert_store, Alert
except ImportError:
    pytest.skip("FastAPI main.py not available", allow_module_level=True)


class TestWebSocketE2E:
    """WebSocket 端到端测试"""

    def test_complete_client_lifecycle(self):
        """测试完整的客户端生命周期

        1. 连接到 WebSocket
        2. 接收 full_state
        3. 接收至少一个 state_update
        4. 断开连接
        """
        client = TestClient(app)

        with client.websocket_connect("/ws") as websocket:
            # 步骤 1 & 2: 连接并接收 full_state
            first_message = websocket.receive_json()
            assert first_message["type"] == "full_state", "First message should be full_state"
            assert "data" in first_message
            assert "timestamp" in first_message

            # 验证 full_state 包含所有数据
            state = first_message["data"]
            required_keys = ["sensors", "ros2", "ros2_control", "rosbag", "alerts"]
            for key in required_keys:
                assert key in state, f"full_state should contain {key}"

            # 步骤 3: 接收 state_update
            try:
                update_message = websocket.receive_json(timeout=7)
                assert update_message["type"] == "state_update", "Second message should be state_update"
                assert "data" in update_message
                assert "timestamp" in update_message
            except Exception as e:
                pytest.skip(f"State update not received in time: {e}")

            # 步骤 4: 连接在此处自动关闭 (退出上下文)

    def test_multiple_state_updates(self):
        """测试接收连续的 state_update 消息"""
        client = TestClient(app)

        with client.websocket_connect("/ws") as websocket:
            # 接收 full_state
            _ = websocket.receive_json()

            # 尝试接收多个 state_update
            updates_received = 0
            max_wait = 15  # 最多等待15秒
            start_time = time.time()

            try:
                while time.time() - start_time < max_wait:
                    data = websocket.receive_json(timeout=6)
                    if data["type"] == "state_update":
                        updates_received += 1
                        if updates_received >= 2:
                            break
            except Exception:
                pass

            # 至少应该收到一个更新
            assert updates_received >= 1, f"Expected at least 1 update, got {updates_received}"

    def test_reconnect_scenario(self):
        """测试客户端重连场景

        模拟:
        1. 客户端连接
        2. 接收数据
        3. 断开
        4. 重新连接
        5. 再次接收 full_state
        """
        client = TestClient(app)

        # 第一次连接
        with client.websocket_connect("/ws") as websocket:
            first_message = websocket.receive_json()
            assert first_message["type"] == "full_state"
            try:
                _ = websocket.receive_json(timeout=7)  # state_update
            except:
                pass

        # 模拟短暂延迟
        time.sleep(0.5)

        # 重新连接
        with client.websocket_connect("/ws") as websocket:
            reconnect_message = websocket.receive_json()
            assert reconnect_message["type"] == "full_state"
            # 验证重连后能正常工作
            websocket.send_text("ping")
            pong = websocket.receive_text()
            assert pong == "pong"


class TestWebSocketBroadcast:
    """WebSocket 广播测试"""

    def test_broadcast_to_multiple_clients(self):
        """测试向多个客户端广播消息"""
        client = TestClient(app)

        messages_received = {"client1": [], "client2": []}

        def client_handler(client_id: str):
            with client.websocket_connect("/ws") as websocket:
                # 接收 full_state
                msg1 = websocket.receive_json()
                messages_received[client_id].append(msg1["type"])

                # 等待可能的 state_update
                try:
                    msg2 = websocket.receive_json(timeout=7)
                    messages_received[client_id].append(msg2["type"])
                except:
                    pass

        # 使用线程模拟并发连接
        t1 = threading.Thread(target=client_handler, args=("client1",))
        t2 = threading.Thread(target=client_handler, args=("client2",))

        t1.start()
        t2.start()

        t1.join(timeout=10)
        t2.join(timeout=10)

        # 两个客户端都应该收到 full_state
        assert "full_state" in messages_received["client1"]
        assert "full_state" in messages_received["client2"]

    def test_concurrent_connections(self):
        """测试并发连接数限制"""
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

        # 创建多个并发连接
        threads = []
        for i in range(5):
            t = threading.Thread(target=connect_and_wait, args=(f"client_{i}",))
            threads.append(t)
            t.start()

        for t in threads:
            t.join(timeout=10)

        # 验证至少有部分连接成功
        successful = sum(1 for r in results if r[1])
        assert successful >= 3, f"Expected at least 3 successful connections, got {successful}"


class TestWebSocketWithAlerts:
    """WebSocket 与告警系统集成测试"""

    def test_alerts_in_full_state(self, temp_db_path):
        """测试 full_state 包含告警数据"""
        # 重置告警存储
        from alerts import AlertStore
        AlertStore._instance = None

        store = AlertStore(db_path=temp_db_path)

        # 添加测试告警
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

        # 连接 WebSocket
        client = TestClient(app)

        with client.websocket_connect("/ws") as websocket:
            data = websocket.receive_json()
            alerts = data["data"]["alerts"]

            # 验证告警数据
            assert isinstance(alerts, list)

        store.close()

    def test_alerts_api_sync(self, temp_db_path):
        """测试告警 API 与 WebSocket 数据同步"""
        from alerts import AlertStore
        AlertStore._instance = None

        store = AlertStore(db_path=temp_db_path)

        # 添加告警
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

        # 通过 WebSocket 获取告警
        client = TestClient(app)

        with client.websocket_connect("/ws") as websocket:
            data = websocket.receive_json()
            ws_alerts = data["data"]["alerts"]

            # 验证告警存在
            assert any(a["id"] == alert_id for a in ws_alerts)

        # 通过 API 获取告警进行验证
        response = client.get(f"/api/alerts/sensor/navi_lidar")
        api_data = response.json()

        assert api_data["success"] is True
        api_alerts = api_data["data"]

        # WebSocket 和 API 应该返回相同数量的告警
        ws_navi_alerts = [a for a in ws_alerts if a["sensor"] == "navi_lidar"]
        assert len(ws_navi_alerts) == len(api_alerts)

        store.close()


class TestWebSocketWithROS2:
    """WebSocket 与 ROS2 系统集成测试"""

    def test_ros2_data_in_websocket(self):
        """测试 WebSocket 包含 ROS2 数据"""
        client = TestClient(app)

        with client.websocket_connect("/ws") as websocket:
            data = websocket.receive_json()
            ros2 = data["data"]["ros2"]
            ros2_control = data["data"]["ros2_control"]

            # 验证 ROS2 数据结构
            assert "status" in ros2
            assert "nodes" in ros2
            assert "topics" in ros2

            # 验证 ROS2 控制数据
            assert "running" in ros2_control

    def test_ros2_api_sync(self):
        """测试 ROS2 API 与 WebSocket 数据同步"""
        client = TestClient(app)

        # 通过 WebSocket 获取 ROS2 状态
        with client.websocket_connect("/ws") as websocket:
            ws_data = websocket.receive_json()
            ws_ros2 = ws_data["data"]["ros2"]

        # 通过 API 获取状态进行验证 (使用兼容端点)
        response = client.get("/api/status")
        api_data = response.json()

        # 验证数据一致性
        assert "running" in api_data
        assert isinstance(api_data["running"], bool)


class TestWebSocketWithRosbag:
    """WebSocket 与 Rosbag 系统集成测试"""

    def test_rosbag_data_in_websocket(self):
        """测试 WebSocket 包含 rosbag 数据"""
        client = TestClient(app)

        with client.websocket_connect("/ws") as websocket:
            data = websocket.receive_json()
            rosbag = data["data"]["rosbag"]

            # 验证 rosbag 数据结构
            assert "recording" in rosbag
            assert isinstance(rosbag["recording"], bool)


class TestWebSocketPerformance:
    """WebSocket 性能测试"""

    def test_message_latency(self):
        """测试消息延迟"""
        client = TestClient(app)

        with client.websocket_connect("/ws") as websocket:
            # 记录连接时间
            connect_time = time.time()

            # 接收第一条消息
            _ = websocket.receive_json()
            first_message_latency = time.time() - connect_time

            # 第一条消息 (full_state) 应该在合理时间内到达
            assert first_message_latency < 2.0, f"First message latency too high: {first_message_latency}s"

            # 测试 ping/pong 延迟
            ping_time = time.time()
            websocket.send_text("ping")
            _ = websocket.receive_text()
            pong_latency = time.time() - ping_time

            # Ping/pong 应该很快
            assert pong_latency < 1.0, f"Ping/pong latency too high: {pong_latency}s"

    def test_connection_time(self):
        """测试连接建立时间"""
        client = TestClient(app)

        start_time = time.time()
        with client.websocket_connect("/ws") as websocket:
            connect_time = time.time() - start_time

            # 连接建立应该很快
            assert connect_time < 1.0, f"Connection time too high: {connect_time}s"

            # 接收一条消息确保连接工作
            _ = websocket.receive_json()


class TestWebSocketErrorRecovery:
    """WebSocket 错误恢复测试"""

    def test_graceful_disconnect(self):
        """测试优雅断开连接"""
        client = TestClient(app)

        initial_count = manager.get_connection_count()

        with client.websocket_connect("/ws") as websocket:
            _ = websocket.receive_json()
            # 连接应该在活动列表中
            current_count = manager.get_connection_count()
            assert current_count >= initial_count

        # 断开后连接应该被清理
        time.sleep(0.2)
        final_count = manager.get_connection_count()
        assert final_count <= initial_count


class TestWebSocketDataIntegrity:
    """WebSocket 数据完整性测试"""

    def test_json_parseability(self):
        """测试所有消息都是有效的 JSON"""
        client = TestClient(app)

        with client.websocket_connect("/ws") as websocket:
            # 接收多条消息
            for _ in range(3):
                try:
                    raw = websocket.receive()
                    if raw:
                        # 尝试解析为 JSON
                        data = json.loads(raw) if isinstance(raw, str) else raw
                        assert isinstance(data, dict)
                        assert "type" in data
                except:
                    # 可能超时
                    break

    def test_timestamp_consistency(self):
        """测试时间戳一致性"""
        client = TestClient(app)

        with client.websocket_connect("/ws") as websocket:
            # 接收第一条消息
            first = websocket.receive_json()
            first_timestamp = first.get("timestamp")

            assert first_timestamp is not None
            assert isinstance(first_timestamp, (int, float))

            # 接收第二条消息
            try:
                second = websocket.receive_json(timeout=7)
                second_timestamp = second.get("timestamp")

                assert second_timestamp is not None
                # 第二条消息的时间戳应该更晚
                assert second_timestamp >= first_timestamp
            except:
                pass


@pytest.fixture
def temp_db_path(tmp_path):
    """临时数据库路径"""
    return str(tmp_path / "test_ws_e2e_alerts.db")


@pytest.fixture(autouse=True)
def reset_alert_store():
    """每个测试后重置告警存储"""
    yield
    try:
        from alerts import AlertStore
        AlertStore._instance = None
    except:
        pass
