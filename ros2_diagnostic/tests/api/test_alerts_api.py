#!/usr/bin/env python3
"""
Alert API endpoint tests

Test FastAPI API endpoint functionality:
- GET /api/alerts - Get alert list
- POST /api/alerts/<id>/resolve - Resolve alert
- POST /api/alerts/<id>/ignore - Ignore alert
- GET /api/alerts/stats - Get statistics
- GET /api/alerts/sensor/<sensor> - Get by sensor
- GET /api/alerts/severity/<severity> - Get by severity
"""

import pytest
import json
from pathlib import Path

import sys
sys.path.insert(0, str(Path(__file__).parent.parent))


class TestAlertsAPI:
    """Alert API endpoint tests"""

    def test_get_alerts_empty(self, client):
        """Test getting empty alert list"""
        response = client.get('/api/alerts')
        data = response.json()

        assert response.status_code == 200
        assert data['success'] is True
        assert data['data'] == []

    def test_get_alerts_with_data(self, client, fresh_alert_store, sample_alerts):
        """Test getting alert list"""
        for alert in sample_alerts:
            fresh_alert_store.add_alert(alert)

        response = client.get('/api/alerts')
        data = response.json()

        assert response.status_code == 200
        assert data['success'] is True
        assert len(data['data']) == 2  # Only returns active

    def test_get_alerts_with_sensor_filter(self, client, fresh_alert_store, sample_alerts):
        """Test filtering by sensor"""
        for alert in sample_alerts:
            fresh_alert_store.add_alert(alert)

        response = client.get('/api/alerts?sensor=navi_lidar')
        data = response.json()

        assert response.status_code == 200
        assert data['success'] is True
        assert len(data['data']) == 2
        assert all(a['sensor'] == 'navi_lidar' for a in data['data'])

    def test_get_alerts_with_sensor_filter_camera(self, client, fresh_alert_store, sample_alerts):
        """Test filtering by camera sensor"""
        for alert in sample_alerts:
            fresh_alert_store.add_alert(alert)

        response = client.get('/api/alerts?sensor=camera')
        data = response.json()

        assert response.status_code == 200
        assert data['success'] is True
        assert len(data['data']) == 0  # camera alert already resolved

    def test_get_alerts_with_status_all(self, client, fresh_alert_store, sample_alerts):
        """Test getting all alerts including resolved"""
        for alert in sample_alerts:
            fresh_alert_store.add_alert(alert)

        response = client.get('/api/alerts?status=all')
        data = response.json()

        assert response.status_code == 200
        assert data['success'] is True
        assert len(data['data']) == 3  # Including resolved

    def test_get_alerts_with_limit(self, client, fresh_alert_store, sample_alerts):
        """Test limiting return count"""
        for alert in sample_alerts:
            fresh_alert_store.add_alert(alert)

        response = client.get('/api/alerts?status=all&limit=2')
        data = response.json()

        assert response.status_code == 200
        assert data['success'] is True
        assert len(data['data']) == 2

    def test_get_alerts_with_offset(self, client, fresh_alert_store, sample_alerts):
        """Test pagination offset"""
        for alert in sample_alerts:
            fresh_alert_store.add_alert(alert)

        # Get the second page
        response = client.get('/api/alerts?status=all&limit=2&offset=2')
        data = response.json()

        assert response.status_code == 200
        assert data['success'] is True
        assert len(data['data']) == 1  # Only 1 remaining

    def test_resolve_alert(self, client, fresh_alert_store, sample_alert):
        """Test resolve alert API"""
        alert_id = fresh_alert_store.add_alert(sample_alert)

        response = client.post(f'/api/alerts/{alert_id}/resolve')
        data = response.json()

        assert response.status_code == 200
        assert data['success'] is True
        assert 'message' in data

        # Verify resolved
        active = fresh_alert_store.get_active_alerts()
        assert len(active) == 0

    def test_resolve_nonexistent_alert(self, client):
        """Test resolving non-existent alert"""
        response = client.post('/api/alerts/999/resolve')
        data = response.json()

        assert response.status_code == 200
        assert data['success'] is False

    def test_ignore_alert(self, client, fresh_alert_store, sample_alert):
        """Test ignore alert API"""
        alert_id = fresh_alert_store.add_alert(sample_alert)

        response = client.post(f'/api/alerts/{alert_id}/ignore')
        data = response.json()

        assert response.status_code == 200
        assert data['success'] is True
        assert 'message' in data

        # Verify active alerts are empty
        active = fresh_alert_store.get_active_alerts()
        assert len(active) == 0

    def test_ignore_nonexistent_alert(self, client):
        """Test ignoring non-existent alert"""
        response = client.post('/api/alerts/999/ignore')
        data = response.json()

        assert response.status_code == 200
        assert data['success'] is False

    def test_get_alert_stats(self, client, fresh_alert_store, sample_alerts):
        """Test get statistics API"""
        for alert in sample_alerts:
            fresh_alert_store.add_alert(alert)

        response = client.get('/api/alerts/stats')
        data = response.json()

        assert response.status_code == 200
        assert data['success'] is True

        # Verify statistics data
        stats = data['data']
        assert stats['total'] == 3
        assert stats['active'] == 2
        assert stats['resolved'] == 1
        assert stats['critical'] == 2
        assert stats['warning'] == 1

    def test_get_alert_stats_empty(self, client, fresh_alert_store):
        """Test statistics for empty database"""
        response = client.get('/api/alerts/stats')
        data = response.json()

        assert response.status_code == 200
        assert data['success'] is True

        stats = data['data']
        assert stats['total'] == 0
        assert stats['active'] == 0

    def test_get_alerts_by_sensor(self, client, fresh_alert_store, sample_alerts):
        """Test get alerts by sensor API"""
        for alert in sample_alerts:
            fresh_alert_store.add_alert(alert)

        response = client.get('/api/alerts/sensor/navi_lidar')
        data = response.json()

        assert response.status_code == 200
        assert data['success'] is True
        assert len(data['data']) == 2

    def test_get_alerts_by_sensor_with_limit(self, client, fresh_alert_store, sample_alerts):
        """Test get by sensor with limit"""
        for alert in sample_alerts:
            fresh_alert_store.add_alert(alert)

        response = client.get('/api/alerts/sensor/navi_lidar?limit=1')
        data = response.json()

        assert response.status_code == 200
        assert data['success'] is True
        assert len(data['data']) == 1

    def test_get_alerts_by_severity(self, client, fresh_alert_store, sample_alerts):
        """Test get alerts by severity API"""
        for alert in sample_alerts:
            fresh_alert_store.add_alert(alert)

        # Get critical
        response = client.get('/api/alerts/severity/critical')
        data = response.json()

        assert response.status_code == 200
        assert data['success'] is True
        assert len(data['data']) == 2
        assert all(a['severity'] == 'critical' for a in data['data'])

        # Get warning
        response = client.get('/api/alerts/severity/warning')
        data = response.json()

        assert response.status_code == 200
        assert data['success'] is True
        assert len(data['data']) == 1
        assert all(a['severity'] == 'warning' for a in data['data'])

    def test_get_alerts_by_severity_with_limit(self, client, fresh_alert_store, sample_alerts):
        """Test get by severity with limit"""
        for alert in sample_alerts:
            fresh_alert_store.add_alert(alert)

        response = client.get('/api/alerts/severity/critical?limit=1')
        data = response.json()

        assert response.status_code == 200
        assert data['success'] is True
        assert len(data['data']) == 1

    def test_get_alerts_invalid_severity(self, client):
        """Test invalid severity parameter"""
        response = client.get('/api/alerts/severity/invalid')
        data = response.json()

        assert response.status_code == 400
        assert data['success'] is False
        assert 'error' in data

    def test_response_format(self, client, fresh_alert_store, sample_alert):
        """Test API response format consistency"""
        fresh_alert_store.add_alert(sample_alert)

        # Test response format for multiple endpoints
        endpoints = [
            '/api/alerts',
            '/api/alerts?status=active',
            '/api/alerts/stats',
        ]

        for endpoint in endpoints:
            response = client.get(endpoint)
            data = response.json()

            # All responses should have a success field
            assert 'success' in data

            # Successful responses should have a data field
            if data['success']:
                assert 'data' in data

    def test_content_type(self, client):
        """Test API returns correct Content-Type"""
        response = client.get('/api/alerts')

        assert response.content_type == 'application/json'


class TestAlertAPIErrors:
    """API error handling tests"""

    def test_404_on_invalid_endpoint(self, client):
        """Test non-existent endpoint returns 404"""
        response = client.get('/api/alerts/invalid_endpoint')
        assert response.status_code == 404

    def test_method_not_allowed(self, client):
        """Test unsupported method returns 405"""
        response = client.post('/api/alerts')
        assert response.status_code == 405

    def test_post_to_stats_returns_405(self, client):
        """Test POST to stats endpoint"""
        response = client.post('/api/alerts/stats')
        assert response.status_code == 405


class TestAlertAPIIntegration:
    """API integration tests"""

    def test_full_alert_workflow(self, client, fresh_alert_store):
        """Test full alert workflow: add -> query -> resolve"""
        from alerts import Alert

        # 1. Create alert
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

        # 2. Query alert
        response = client.get('/api/alerts')
        data = response.json()
        assert len(data['data']) == 1
        assert data['data'][0]['id'] == alert_id

        # 3. Resolve alert
        response = client.post(f'/api/alerts/{alert_id}/resolve')
        assert response.status_code == 200

        # 4. Verify resolved
        response = client.get('/api/alerts')
        data = response.json()
        assert len(data['data']) == 0

    def test_multiple_sensors_filtering(self, client, fresh_alert_store):
        """Test multi-sensor filtering"""
        from alerts import Alert

        # Add alerts from multiple sensors
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

        # Test filtering for each sensor
        for sensor, _, _, _ in sensors_data:
            response = client.get(f'/api/alerts/sensor/{sensor}')
            data = response.json()

            assert response.status_code == 200
            assert data['success'] is True
            assert all(a['sensor'] == sensor for a in data['data'])
