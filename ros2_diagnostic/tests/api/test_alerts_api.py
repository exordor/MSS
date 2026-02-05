#!/usr/bin/env python3
"""
Alert API 端点测试

测试 FastAPI API 端点的功能:
- GET /api/alerts - 获取告警列表
- POST /api/alerts/<id>/resolve - 解决告警
- POST /api/alerts/<id>/ignore - 忽略告警
- GET /api/alerts/stats - 获取统计信息
- GET /api/alerts/sensor/<sensor> - 按传感器获取
- GET /api/alerts/severity/<severity> - 按严重程度获取
"""

import pytest
import json
from pathlib import Path

import sys
sys.path.insert(0, str(Path(__file__).parent.parent))


class TestAlertsAPI:
    """告警 API 端点测试"""

    def test_get_alerts_empty(self, client):
        """测试获取空告警列表"""
        response = client.get('/api/alerts')
        data = response.json()

        assert response.status_code == 200
        assert data['success'] is True
        assert data['data'] == []

    def test_get_alerts_with_data(self, client, fresh_alert_store, sample_alerts):
        """测试获取告警列表"""
        for alert in sample_alerts:
            fresh_alert_store.add_alert(alert)

        response = client.get('/api/alerts')
        data = response.json()

        assert response.status_code == 200
        assert data['success'] is True
        assert len(data['data']) == 2  # 只返回 active

    def test_get_alerts_with_sensor_filter(self, client, fresh_alert_store, sample_alerts):
        """测试按传感器过滤"""
        for alert in sample_alerts:
            fresh_alert_store.add_alert(alert)

        response = client.get('/api/alerts?sensor=navi_lidar')
        data = response.json()

        assert response.status_code == 200
        assert data['success'] is True
        assert len(data['data']) == 2
        assert all(a['sensor'] == 'navi_lidar' for a in data['data'])

    def test_get_alerts_with_sensor_filter_camera(self, client, fresh_alert_store, sample_alerts):
        """测试按 camera 传感器过滤"""
        for alert in sample_alerts:
            fresh_alert_store.add_alert(alert)

        response = client.get('/api/alerts?sensor=camera')
        data = response.json()

        assert response.status_code == 200
        assert data['success'] is True
        assert len(data['data']) == 0  # camera 告警已解决

    def test_get_alerts_with_status_all(self, client, fresh_alert_store, sample_alerts):
        """测试获取所有告警包括已解决"""
        for alert in sample_alerts:
            fresh_alert_store.add_alert(alert)

        response = client.get('/api/alerts?status=all')
        data = response.json()

        assert response.status_code == 200
        assert data['success'] is True
        assert len(data['data']) == 3  # 包括 resolved

    def test_get_alerts_with_limit(self, client, fresh_alert_store, sample_alerts):
        """测试限制返回数量"""
        for alert in sample_alerts:
            fresh_alert_store.add_alert(alert)

        response = client.get('/api/alerts?status=all&limit=2')
        data = response.json()

        assert response.status_code == 200
        assert data['success'] is True
        assert len(data['data']) == 2

    def test_get_alerts_with_offset(self, client, fresh_alert_store, sample_alerts):
        """测试分页偏移"""
        for alert in sample_alerts:
            fresh_alert_store.add_alert(alert)

        # 获取第二页
        response = client.get('/api/alerts?status=all&limit=2&offset=2')
        data = response.json()

        assert response.status_code == 200
        assert data['success'] is True
        assert len(data['data']) == 1  # 只剩 1 个

    def test_resolve_alert(self, client, fresh_alert_store, sample_alert):
        """测试解决告警 API"""
        alert_id = fresh_alert_store.add_alert(sample_alert)

        response = client.post(f'/api/alerts/{alert_id}/resolve')
        data = response.json()

        assert response.status_code == 200
        assert data['success'] is True
        assert 'message' in data

        # 验证已解决
        active = fresh_alert_store.get_active_alerts()
        assert len(active) == 0

    def test_resolve_nonexistent_alert(self, client):
        """测试解决不存在的告警"""
        response = client.post('/api/alerts/999/resolve')
        data = response.json()

        assert response.status_code == 200
        assert data['success'] is False

    def test_ignore_alert(self, client, fresh_alert_store, sample_alert):
        """测试忽略告警 API"""
        alert_id = fresh_alert_store.add_alert(sample_alert)

        response = client.post(f'/api/alerts/{alert_id}/ignore')
        data = response.json()

        assert response.status_code == 200
        assert data['success'] is True
        assert 'message' in data

        # 验证活动告警为空
        active = fresh_alert_store.get_active_alerts()
        assert len(active) == 0

    def test_ignore_nonexistent_alert(self, client):
        """测试忽略不存在的告警"""
        response = client.post('/api/alerts/999/ignore')
        data = response.json()

        assert response.status_code == 200
        assert data['success'] is False

    def test_get_alert_stats(self, client, fresh_alert_store, sample_alerts):
        """测试获取统计信息 API"""
        for alert in sample_alerts:
            fresh_alert_store.add_alert(alert)

        response = client.get('/api/alerts/stats')
        data = response.json()

        assert response.status_code == 200
        assert data['success'] is True

        # 验证统计数据
        stats = data['data']
        assert stats['total'] == 3
        assert stats['active'] == 2
        assert stats['resolved'] == 1
        assert stats['critical'] == 2
        assert stats['warning'] == 1

    def test_get_alert_stats_empty(self, client, fresh_alert_store):
        """测试空数据库的统计信息"""
        response = client.get('/api/alerts/stats')
        data = response.json()

        assert response.status_code == 200
        assert data['success'] is True

        stats = data['data']
        assert stats['total'] == 0
        assert stats['active'] == 0

    def test_get_alerts_by_sensor(self, client, fresh_alert_store, sample_alerts):
        """测试按传感器获取告警 API"""
        for alert in sample_alerts:
            fresh_alert_store.add_alert(alert)

        response = client.get('/api/alerts/sensor/navi_lidar')
        data = response.json()

        assert response.status_code == 200
        assert data['success'] is True
        assert len(data['data']) == 2

    def test_get_alerts_by_sensor_with_limit(self, client, fresh_alert_store, sample_alerts):
        """测试按传感器获取并限制数量"""
        for alert in sample_alerts:
            fresh_alert_store.add_alert(alert)

        response = client.get('/api/alerts/sensor/navi_lidar?limit=1')
        data = response.json()

        assert response.status_code == 200
        assert data['success'] is True
        assert len(data['data']) == 1

    def test_get_alerts_by_severity(self, client, fresh_alert_store, sample_alerts):
        """测试按严重程度获取告警 API"""
        for alert in sample_alerts:
            fresh_alert_store.add_alert(alert)

        # 获取 critical
        response = client.get('/api/alerts/severity/critical')
        data = response.json()

        assert response.status_code == 200
        assert data['success'] is True
        assert len(data['data']) == 2
        assert all(a['severity'] == 'critical' for a in data['data'])

        # 获取 warning
        response = client.get('/api/alerts/severity/warning')
        data = response.json()

        assert response.status_code == 200
        assert data['success'] is True
        assert len(data['data']) == 1
        assert all(a['severity'] == 'warning' for a in data['data'])

    def test_get_alerts_by_severity_with_limit(self, client, fresh_alert_store, sample_alerts):
        """测试按严重程度获取并限制数量"""
        for alert in sample_alerts:
            fresh_alert_store.add_alert(alert)

        response = client.get('/api/alerts/severity/critical?limit=1')
        data = response.json()

        assert response.status_code == 200
        assert data['success'] is True
        assert len(data['data']) == 1

    def test_get_alerts_invalid_severity(self, client):
        """测试无效的严重程度参数"""
        response = client.get('/api/alerts/severity/invalid')
        data = response.json()

        assert response.status_code == 400
        assert data['success'] is False
        assert 'error' in data

    def test_response_format(self, client, fresh_alert_store, sample_alert):
        """测试 API 响应格式一致性"""
        fresh_alert_store.add_alert(sample_alert)

        # 测试多个端点的响应格式
        endpoints = [
            '/api/alerts',
            '/api/alerts?status=active',
            '/api/alerts/stats',
        ]

        for endpoint in endpoints:
            response = client.get(endpoint)
            data = response.json()

            # 所有响应都应有 success 字段
            assert 'success' in data

            # 成功的响应应有 data 字段
            if data['success']:
                assert 'data' in data

    def test_content_type(self, client):
        """测试 API 返回正确的 Content-Type"""
        response = client.get('/api/alerts')

        assert response.content_type == 'application/json'


class TestAlertAPIErrors:
    """API 错误处理测试"""

    def test_404_on_invalid_endpoint(self, client):
        """测试不存在的端点返回 404"""
        response = client.get('/api/alerts/invalid_endpoint')
        assert response.status_code == 404

    def test_method_not_allowed(self, client):
        """测试不支持的方法返回 405"""
        response = client.post('/api/alerts')
        assert response.status_code == 405

    def test_post_to_stats_returns_405(self, client):
        """测试 POST 到 stats 端点"""
        response = client.post('/api/alerts/stats')
        assert response.status_code == 405


class TestAlertAPIIntegration:
    """API 集成测试"""

    def test_full_alert_workflow(self, client, fresh_alert_store):
        """测试完整告警工作流: 添加 -> 查询 -> 解决"""
        from alerts import Alert

        # 1. 创建告警
        alert = Alert(
            sensor="test_sensor",
            alert_type="test_alert",
            severity="warning",
            message="Test alert for workflow",
            metric_value=5.0,
            threshold=10.0,
            metadata="{}",
            created_at="2026-01-27T10:00:00"
        )
        alert_id = fresh_alert_store.add_alert(alert)

        # 2. 查询告警
        response = client.get('/api/alerts')
        data = response.json()
        assert len(data['data']) == 1
        assert data['data'][0]['id'] == alert_id

        # 3. 解决告警
        response = client.post(f'/api/alerts/{alert_id}/resolve')
        assert response.status_code == 200

        # 4. 验证已解决
        response = client.get('/api/alerts')
        data = response.json()
        assert len(data['data']) == 0

    def test_multiple_sensors_filtering(self, client, fresh_alert_store):
        """测试多传感器过滤"""
        from alerts import Alert

        # 添加多个传感器的告警
        sensors_data = [
            ("navi_lidar", "frame_loss", "critical", "3.5 Hz"),
            ("camera", "connectivity", "warning", "No signal"),
            ("imu", "data_loss", "warning", "No data"),
        ]

        for sensor, alert_type, severity, message in sensors_data:
            alert = Alert(
                sensor=sensor,
                alert_type=alert_type,
                severity=severity,
                message=message,
                metric_value=0.0,
                threshold=1.0,
                metadata="{}",
                created_at="2026-01-27T10:00:00"
            )
            fresh_alert_store.add_alert(alert)

        # 测试每个传感器的过滤
        for sensor, _, _, _ in sensors_data:
            response = client.get(f'/api/alerts/sensor/{sensor}')
            data = response.json()

            assert response.status_code == 200
            assert data['success'] is True
            assert all(a['sensor'] == sensor for a in data['data'])
