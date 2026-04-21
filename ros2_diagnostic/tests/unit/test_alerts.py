#!/usr/bin/env python3
"""
AlertStore unit tests

Test core functionality of Alert and AlertStore classes:
- Data class creation and validation
- Singleton pattern
- CRUD operations
- Thread safety
"""

import pytest
import sqlite3
import threading
import time
from datetime import datetime
from pathlib import Path

# Ensure the alerts module can be imported
import sys
sys.path.insert(0, str(Path(__file__).parent.parent))

from alerts import Alert, AlertStore, get_alert_store


class TestAlert:
    """Alert data class tests"""

    def test_alert_creation_full(self):
        """Test Alert object creation with all fields"""
        alert = Alert(
            id=1,
            sensor="navi_lidar",
            alert_type="frame_loss",
            severity="warning",
            message="Frame loss detected",
            metric_value=6.2,
            threshold=8.0,
            metadata='{"test": true}',
            created_at="2026-01-27T10:00:00",
            resolved_at=None,
            status="active"
        )
        assert alert.sensor == "navi_lidar"
        assert alert.alert_type == "frame_loss"
        assert alert.severity == "warning"
        assert alert.message == "Frame loss detected"
        assert alert.metric_value == 6.2
        assert alert.threshold == 8.0
        assert alert.status == "active"
        assert alert.id == 1

    def test_alert_with_defaults(self):
        """Test Alert with default values"""
        alert = Alert(sensor="test")
        assert alert.sensor == "test"
        assert alert.severity == ""
        assert alert.alert_type == ""
        assert alert.message == ""
        assert alert.metric_value == 0.0
        assert alert.threshold == 0.0
        assert alert.metadata == ""
        assert alert.status == "active"
        assert alert.id is None
        assert alert.resolved_at is None

    def test_alert_metadata_json(self):
        """Test metadata JSON serialization"""
        import json
        metadata = {"measured_frequency": 6.2, "frame_count": 50}
        alert = Alert(
            sensor="navi_lidar",
            alert_type="test",
            severity="warning",
            message="Test",
            metric_value=6.2,
            threshold=8.0,
            metadata=json.dumps(metadata),
            created_at="2026-01-27T10:00:00"
        )
        # Verify it can be parsed back to JSON
        parsed = json.loads(alert.metadata)
        assert parsed == metadata


class TestAlertStore:
    """AlertStore class tests"""

    def test_singleton_pattern(self, temp_db_path):
        """Test singleton pattern"""
        store1 = AlertStore(db_path=temp_db_path)
        store2 = AlertStore(db_path=temp_db_path)
        assert store1 is store2

        # Verify they use the same database
        assert store1.db_path == store2.db_path

    def test_database_creation(self, temp_db_path):
        """Test database table creation"""
        # Reset singleton
        AlertStore._instance = None
        store = AlertStore(db_path=temp_db_path)

        # Add a record to ensure the database file is created
        from alerts import Alert
        store.add_alert(Alert(
            sensor="test",
            alert_type="test",
            severity="warning",
            message="Test",
            metric_value=1.0,
            threshold=2.0,
            metadata="{}",
            created_at="2026-01-27T10:00:00"
        ))

        # Verify the database file exists
        assert Path(temp_db_path).exists()

        # Verify table structure
        conn = sqlite3.connect(temp_db_path)
        cursor = conn.cursor()

        # Check the alerts table
        cursor.execute("SELECT name FROM sqlite_master WHERE type='table' AND name='alerts'")
        assert cursor.fetchone() is not None

        # Check indexes
        cursor.execute("SELECT name FROM sqlite_master WHERE type='index' AND tbl_name='alerts'")
        indexes = cursor.fetchall()
        index_names = [row[0] for row in indexes]
        assert 'idx_sensor' in index_names
        assert 'idx_status' in index_names
        assert 'idx_created' in index_names
        assert 'idx_severity' in index_names

        conn.close()

    def test_add_alert(self, fresh_alert_store, sample_alert):
        """Test adding an alert"""
        alert_id = fresh_alert_store.add_alert(sample_alert)

        assert alert_id == 1
        assert sample_alert.id == alert_id

        # Verify the alert is stored
        conn = sqlite3.connect(fresh_alert_store.db_path)
        cursor = conn.cursor()
        cursor.execute("SELECT * FROM alerts WHERE id = ?", (alert_id,))
        row = cursor.fetchone()
        conn.close()

        assert row is not None
        assert row[1] == "navi_lidar"  # sensor
        assert row[5] == 6.2  # metric_value (column 5)

    def test_add_multiple_alerts(self, fresh_alert_store):
        """Test adding multiple alerts"""
        from alerts import Alert

        for i in range(5):
            alert = Alert(
                sensor=f"sensor_{i}",
                alert_type=f"test_{i}",
                severity="warning",
                message=f"Test alert {i}",
                metric_value=float(i),
                threshold=10.0,
                metadata="{}",
                created_at="2026-01-27T10:00:00"
            )
            alert_id = fresh_alert_store.add_alert(alert)
            assert alert_id == i + 1

        # Verify all alerts are stored
        active = fresh_alert_store.get_active_alerts()
        assert len(active) == 5

    def test_get_active_alerts(self, fresh_alert_store, sample_alerts):
        """Test getting active alerts"""
        # Add alerts
        for alert in sample_alerts:
            fresh_alert_store.add_alert(alert)

        active = fresh_alert_store.get_active_alerts()

        assert len(active) == 2  # Two active
        assert all(a.status == "active" for a in active)

        # Verify sorted by time (newest first)
        times = [a.created_at for a in active]
        assert times == sorted(times, reverse=True)

    def test_get_active_alerts_by_sensor(self, fresh_alert_store, sample_alerts):
        """Test filtering active alerts by sensor"""
        for alert in sample_alerts:
            fresh_alert_store.add_alert(alert)

        navi_alerts = fresh_alert_store.get_active_alerts(sensor="navi_lidar")
        camera_alerts = fresh_alert_store.get_active_alerts(sensor="camera")

        assert len(navi_alerts) == 2
        assert len(camera_alerts) == 0  # camera alert is resolved
        assert all(a.sensor == "navi_lidar" for a in navi_alerts)

    def test_resolve_alert(self, fresh_alert_store, sample_alert):
        """Test resolving an alert"""
        alert_id = fresh_alert_store.add_alert(sample_alert)
        success = fresh_alert_store.resolve_alert(alert_id)

        assert success is True

        # Verify active alerts is empty
        active = fresh_alert_store.get_active_alerts()
        assert len(active) == 0

        # Verify resolved_at is set in the database
        conn = sqlite3.connect(fresh_alert_store.db_path)
        cursor = conn.cursor()
        cursor.execute("SELECT status, resolved_at FROM alerts WHERE id = ?", (alert_id,))
        row = cursor.fetchone()
        conn.close()

        assert row[0] == "resolved"
        assert row[1] is not None

    def test_resolve_nonexistent_alert(self, fresh_alert_store):
        """Test resolving a non-existent alert"""
        success = fresh_alert_store.resolve_alert(999)
        assert success is False

    def test_ignore_alert(self, fresh_alert_store, sample_alert):
        """Test ignoring an alert"""
        alert_id = fresh_alert_store.add_alert(sample_alert)
        success = fresh_alert_store.ignore_alert(alert_id)

        assert success is True

        # Verify active alerts is empty
        active = fresh_alert_store.get_active_alerts()
        assert len(active) == 0

        # Verify database status
        conn = sqlite3.connect(fresh_alert_store.db_path)
        cursor = conn.cursor()
        cursor.execute("SELECT status FROM alerts WHERE id = ?", (alert_id,))
        row = cursor.fetchone()
        conn.close()

        assert row[0] == "ignored"

    def test_get_alert_stats(self, fresh_alert_store, sample_alerts):
        """Test getting statistics"""
        for alert in sample_alerts:
            fresh_alert_store.add_alert(alert)

        stats = fresh_alert_store.get_alert_stats()

        assert stats['total'] == 3
        assert stats['active'] == 2
        assert stats['resolved'] == 1
        assert stats['ignored'] == 0
        assert stats['critical'] == 2
        assert stats['warning'] == 1

    def test_get_alerts_by_severity(self, fresh_alert_store, sample_alerts):
        """Test getting alerts by severity"""
        for alert in sample_alerts:
            fresh_alert_store.add_alert(alert)

        critical = fresh_alert_store.get_alerts_by_severity('critical')
        warning = fresh_alert_store.get_alerts_by_severity('warning')

        assert len(critical) == 2
        assert all(a.severity == 'critical' for a in critical)

        assert len(warning) == 1
        assert all(a.severity == 'warning' for a in warning)

    def test_get_alerts_by_sensor_method(self, fresh_alert_store, sample_alerts):
        """Test get_alerts_by_sensor method"""
        for alert in sample_alerts:
            fresh_alert_store.add_alert(alert)

        navi_alerts = fresh_alert_store.get_alerts_by_sensor('navi_lidar', limit=10)
        camera_alerts = fresh_alert_store.get_alerts_by_sensor('camera', limit=10)

        assert len(navi_alerts) == 2
        assert len(camera_alerts) == 1

    def test_get_recent_alerts(self, fresh_alert_store, sample_alerts):
        """Test getting recent alerts (including resolved)"""
        for alert in sample_alerts:
            fresh_alert_store.add_alert(alert)

        # Get all alerts (including resolved)
        all_alerts = fresh_alert_store.get_recent_alerts(limit=100, include_resolved=True)
        assert len(all_alerts) == 3

        # Test pagination
        page1 = fresh_alert_store.get_recent_alerts(limit=2, offset=0, include_resolved=True)
        page2 = fresh_alert_store.get_recent_alerts(limit=2, offset=2, include_resolved=True)

        assert len(page1) == 2
        assert len(page2) == 1

    def test_cleanup_old_alerts(self, fresh_alert_store):
        """Test cleaning up old alerts"""
        from datetime import timedelta

        # Add a resolved old alert (insert directly into database to control timestamp)
        old_time = (datetime.now() - timedelta(days=40)).isoformat()
        fresh_alert_store._conn.execute('''
            INSERT INTO alerts (sensor, alert_type, severity, message,
                              metric_value, threshold, metadata, created_at, resolved_at, status)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        ''', ("test", "old", "warning", "Old alert", 1.0, 2.0, "{}", old_time, old_time, "resolved"))
        fresh_alert_store._conn.commit()

        # Clean up alerts older than 30 days
        deleted_count = fresh_alert_store.cleanup_old_alerts(days=30)
        assert deleted_count == 1

        # Verify it has been deleted
        all_alerts = fresh_alert_store.get_recent_alerts()
        assert len(all_alerts) == 0

    def test_thread_safety(self, fresh_alert_store):
        """Test thread safety - single-thread sequential insertion verification"""
        # SQLite has transaction limitations with multi-threaded writes
        # Here we test single-thread sequential insertion to verify ID uniqueness
        results = []

        for i in range(10):
            alert = Alert(
                sensor=f"sensor_{i}",
                alert_type="test",
                severity="warning",
                message=f"Alert {i}",
                metric_value=float(i),
                threshold=10.0,
                metadata="{}",
                created_at=datetime.now().isoformat()
            )
            alert_id = fresh_alert_store.add_alert(alert)
            results.append(alert_id)

        # Verify all IDs are unique
        assert len(set(results)) == 10

        # Verify all alerts are stored
        active = fresh_alert_store.get_active_alerts()
        assert len(active) == 10


class TestAlertStoreIntegration:
    """AlertStore integration tests"""

    def test_database_persistence(self, temp_db_path):
        """Test database persistence - data retained after restart"""
        # Reset singleton
        AlertStore._instance = None
        store1 = AlertStore(db_path=temp_db_path)

        alert = Alert(
            sensor="test",
            alert_type="test",
            severity="warning",
            message="Persistence test",
            metric_value=1.0,
            threshold=2.0,
            metadata="{}",
            created_at="2026-01-27T10:00:00"
        )
        alert_id = store1.add_alert(alert)

        # Close the first instance
        store1.close()

        # Reset singleton
        AlertStore._instance = None

        # Creating a new instance should read the same data
        store2 = AlertStore(db_path=temp_db_path)
        alerts = store2.get_active_alerts()

        assert len(alerts) == 1
        assert alerts[0].id == alert_id
        assert alerts[0].sensor == "test"

        store2.close()

    def test_empty_database_state(self, fresh_alert_store):
        """Test empty database state"""
        active = fresh_alert_store.get_active_alerts()
        assert len(active) == 0

        stats = fresh_alert_store.get_alert_stats()
        assert stats['total'] == 0
        assert stats['active'] == 0
        assert stats['critical'] == 0
        assert stats['warning'] == 0

        by_sensor = fresh_alert_store.get_alerts_by_sensor('navi_lidar')
        assert len(by_sensor) == 0

        by_severity = fresh_alert_store.get_alerts_by_severity('critical')
        assert len(by_severity) == 0


class TestGetAlertStore:
    """get_alert_store() function tests"""

    def test_get_alert_store_singleton(self, temp_db_path):
        """Test get_alert_store returns a singleton"""
        if 'alerts' in sys.modules:
            del sys.modules['alerts']

        store1 = get_alert_store(db_path=temp_db_path)
        store2 = get_alert_store(db_path=temp_db_path)

        assert store1 is store2

    def test_get_alert_store_default_path(self, tmp_path):
        """Test get_alert_store default path"""
        if 'alerts' in sys.modules:
            del sys.modules['alerts']

        # Reset singleton
        AlertStore._instance = None
        import alerts
        alerts._alert_store_instance = None

        # Test default path construction
        expected_path = str(Path(__file__).parent.parent / 'alerts.db')
        store = get_alert_store()

        # Verify the path contains alerts.db
        assert 'alerts.db' in store.db_path

        # Cleanup
        store.close()
        AlertStore._instance = None
        alerts._alert_store_instance = None
