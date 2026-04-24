#!/usr/bin/env python3
"""
Alert System - SQLite based alert storage and query

Provides persistent storage for sensor alerts with full metadata tracking.
All alerts are retained permanently for historical analysis.
"""

import sqlite3
import threading
import asyncio
from dataclasses import dataclass, asdict
from datetime import datetime, timedelta
from typing import List, Optional, Dict, Any, Callable, Awaitable
from pathlib import Path


@dataclass
class Alert:
    """Alert data model

    Attributes:
        id: Database auto-increment ID
        sensor: Sensor name (navi_lidar, camera, imu, thruster)
        alert_type: Alert type (frame_loss, point_count_low, connectivity, etc.)
        severity: Severity level (critical, warning)
        message: Alert message
        metric_value: Measured value that triggered the alert
        threshold: Threshold value
        metadata: Additional metadata in JSON format
        created_at: Creation time (ISO 8601)
        resolved_at: Resolution time (ISO 8601), optional
        status: Status (active, resolved, ignored)
    """
    id: Optional[int] = None
    sensor: str = ""
    alert_type: str = ""
    severity: str = ""  # critical, warning
    message: str = ""
    metric_value: float = 0.0
    threshold: float = 0.0
    metadata: str = ""  # JSON format
    created_at: str = ""
    resolved_at: Optional[str] = None
    status: str = "active"  # active, resolved, ignored


class AlertStore:
    """Alert storage - singleton pattern, thread-safe

    Provides persistent storage, querying, and management for alerts.
    """

    _instance = None
    _lock = threading.Lock()

    def __new__(cls, db_path: str = None):
        if cls._instance is None:
            with cls._lock:
                if cls._instance is None:
                    cls._instance = super().__new__(cls)
        return cls._instance

    def __init__(self, db_path: str = None):
        if not hasattr(self, '_initialized'):
            # Default path is in the ros2_diagnostic directory
            if db_path is None:
                db_path = Path(__file__).parent / 'alerts.db'
            else:
                db_path = Path(db_path)

            self.db_path = str(db_path)
            self._conn: Optional[sqlite3.Connection] = None
            self._alert_callback = None  # Alert callback function (for real-time push)
            self._init_db()
            self._initialized = True

    def _init_db(self):
        """Initialize database connection and tables"""
        try:
            self._conn = sqlite3.connect(
                self.db_path,
                check_same_thread=False,
                timeout=10  # 10 second timeout
            )
            self._conn.row_factory = sqlite3.Row
            self._create_tables()
        except Exception as e:
            print(f"Failed to initialize alert database: {e}")
            raise

    def _create_tables(self):
        """Create alerts table and indexes"""
        self._conn.execute('''
            CREATE TABLE IF NOT EXISTS alerts (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                sensor TEXT NOT NULL,
                alert_type TEXT NOT NULL,
                severity TEXT NOT NULL,
                message TEXT NOT NULL,
                metric_value REAL,
                threshold REAL,
                metadata TEXT,
                created_at TEXT NOT NULL,
                resolved_at TEXT,
                status TEXT NOT NULL DEFAULT 'active'
            )
        ''')

        # Create indexes to improve query performance
        self._conn.execute('CREATE INDEX IF NOT EXISTS idx_sensor ON alerts(sensor)')
        self._conn.execute('CREATE INDEX IF NOT EXISTS idx_status ON alerts(status)')
        self._conn.execute('CREATE INDEX IF NOT EXISTS idx_created ON alerts(created_at DESC)')
        self._conn.execute('CREATE INDEX IF NOT EXISTS idx_severity ON alerts(severity)')
        self._conn.execute('CREATE INDEX IF NOT EXISTS idx_sensor_status ON alerts(sensor, status)')

        self._conn.commit()

    def set_alert_callback(self, callback):
        """Set alert callback function (for real-time push)

        Args:
            callback: Async callback function, receives Alert object as argument
        """
        self._alert_callback = callback

    async def _trigger_alert_callback(self, alert: Alert):
        """Trigger alert callback (async execution)

        Args:
            alert: Alert object
        """
        if self._alert_callback:
            try:
                # Try calling as coroutine
                if asyncio.iscoroutinefunction(self._alert_callback):
                    await self._alert_callback(alert)
                else:
                    # Plain callbacks are responsible for their own dispatching.
                    self._alert_callback(alert)
            except Exception as e:
                print(f"Error in alert callback: {e}")

    def add_alert(self, alert: Alert) -> int:
        """Add a new alert

        Args:
            alert: Alert object

        Returns:
            ID of the new alert
        """
        cursor = self._conn.execute('''
            INSERT INTO alerts (sensor, alert_type, severity, message,
                                metric_value, threshold, metadata, created_at, status)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
        ''', (alert.sensor, alert.alert_type, alert.severity, alert.message,
              alert.metric_value, alert.threshold, alert.metadata,
              alert.created_at, alert.status))

        self._conn.commit()
        alert_id = cursor.lastrowid

        # Trigger real-time push callback (async execution, non-blocking for add_alert)
        if self._alert_callback:
            try:
                if asyncio.iscoroutinefunction(self._alert_callback):
                    try:
                        loop = asyncio.get_running_loop()
                        loop.create_task(self._alert_callback(alert))
                    except RuntimeError:
                        import threading

                        def run_async_callback():
                            new_loop = asyncio.new_event_loop()
                            try:
                                asyncio.set_event_loop(new_loop)
                                new_loop.run_until_complete(self._alert_callback(alert))
                            except Exception as e:
                                print(f"Error in alert callback thread: {e}")
                            finally:
                                new_loop.close()

                        threading.Thread(target=run_async_callback, daemon=True).start()
                else:
                    self._alert_callback(alert)
            except Exception as e:
                print(f"Error scheduling alert callback: {e}")

        return alert_id

    def get_active_alerts(self, sensor: str = None) -> List[Alert]:
        """Get active alerts

        Args:
            sensor: Optional, filter by sensor

        Returns:
            List of Alert objects
        """
        if sensor:
            cursor = self._conn.execute('''
                SELECT * FROM alerts WHERE status = 'active' AND sensor = ?
                ORDER BY created_at DESC
            ''', (sensor,))
        else:
            cursor = self._conn.execute('''
                SELECT * FROM alerts WHERE status = 'active'
                ORDER BY created_at DESC
            ''')

        rows = cursor.fetchall()
        return [Alert(**dict(row)) for row in rows]

    def get_recent_alerts(self, limit: int = 100, offset: int = 0,
                         include_resolved: bool = False) -> List[Alert]:
        """Get recent alerts (optionally including resolved alerts)

        Args:
            limit: Maximum number of results
            offset: Offset for pagination
            include_resolved: Whether to include resolved alerts

        Returns:
            List of Alert objects
        """
        if include_resolved:
            cursor = self._conn.execute('''
                SELECT * FROM alerts ORDER BY created_at DESC LIMIT ? OFFSET ?
            ''', (limit, offset))
        else:
            cursor = self._conn.execute('''
                SELECT * FROM alerts WHERE status = 'active'
                ORDER BY created_at DESC LIMIT ? OFFSET ?
            ''', (limit, offset))

        rows = cursor.fetchall()
        return [Alert(**dict(row)) for row in rows]

    def resolve_alert(self, alert_id: int) -> bool:
        """Resolve an alert

        Args:
            alert_id: Alert ID

        Returns:
            Whether the alert was successfully resolved
        """
        cursor = self._conn.execute('''
            UPDATE alerts SET status = 'resolved', resolved_at = ?
            WHERE id = ?
        ''', (datetime.now().isoformat(), alert_id))
        self._conn.commit()
        return cursor.rowcount > 0

    def resolve_all(self) -> int:
        """Resolve all active alerts.

        Returns:
            Number of alerts updated
        """
        cursor = self._conn.execute('''
            UPDATE alerts SET status = 'resolved', resolved_at = ?
            WHERE status = 'active'
        ''', (datetime.now().isoformat(),))
        self._conn.commit()
        return cursor.rowcount

    def ignore_alert(self, alert_id: int) -> bool:
        """Ignore an alert (no longer displayed, but record is kept)

        Args:
            alert_id: Alert ID

        Returns:
            Whether the alert was successfully ignored
        """
        cursor = self._conn.execute('''
            UPDATE alerts SET status = 'ignored'
            WHERE id = ?
        ''', (alert_id,))
        self._conn.commit()
        return cursor.rowcount > 0

    def ignore_all(self) -> int:
        """Ignore all active alerts.

        Returns:
            Number of alerts updated
        """
        cursor = self._conn.execute('''
            UPDATE alerts SET status = 'ignored'
            WHERE status = 'active'
        ''')
        self._conn.commit()
        return cursor.rowcount

    def get_alert_stats(self) -> Dict[str, Any]:
        """Get alert statistics

        Returns:
            Dictionary with total alerts, active alerts, and severity breakdown
        """
        cursor = self._conn.execute('''
            SELECT
                COUNT(*) as total,
                COUNT(CASE WHEN status = 'active' THEN 1 END) as active,
                COUNT(CASE WHEN status = 'resolved' THEN 1 END) as resolved,
                COUNT(CASE WHEN status = 'ignored' THEN 1 END) as ignored,
                COUNT(CASE WHEN severity = 'critical' THEN 1 END) as critical,
                COUNT(CASE WHEN severity = 'warning' THEN 1 END) as warning
            FROM alerts
        ''')
        row = cursor.fetchone()
        return dict(row) if row else {}

    def get_alerts_by_sensor(self, sensor: str, limit: int = 50) -> List[Alert]:
        """Get alerts by sensor

        Args:
            sensor: Sensor name
            limit: Maximum number of results

        Returns:
            List of Alert objects
        """
        cursor = self._conn.execute('''
            SELECT * FROM alerts
            WHERE sensor = ?
            ORDER BY created_at DESC
            LIMIT ?
        ''', (sensor, limit))

        rows = cursor.fetchall()
        return [Alert(**dict(row)) for row in rows]

    def get_alerts_by_severity(self, severity: str, limit: int = 50) -> List[Alert]:
        """Get alerts by severity

        Args:
            severity: Severity level (critical, warning)
            limit: Maximum number of results

        Returns:
            List of Alert objects
        """
        cursor = self._conn.execute('''
            SELECT * FROM alerts
            WHERE severity = ?
            ORDER BY created_at DESC
            LIMIT ?
        ''', (severity, limit))

        rows = cursor.fetchall()
        return [Alert(**dict(row)) for row in rows]

    def cleanup_old_alerts(self, days: int = 30) -> int:
        """Clean up old alerts (optional, use as needed)

        Note: By default, all alerts are retained. This method is only for
        manual cleanup of very old alerts.

        Args:
            days: Number of recent days to keep

        Returns:
            Number of deleted alerts
        """
        cutoff = (datetime.now() - timedelta(days=days)).isoformat()

        cursor = self._conn.execute('''
            DELETE FROM alerts
            WHERE resolved_at IS NOT NULL
            AND resolved_at < ?
            AND status = 'resolved'
        ''', (cutoff,))

        self._conn.commit()
        return cursor.rowcount

    def close(self):
        """Close database connection"""
        if self._conn:
            self._conn.close()


# Global instance
_alert_store_instance: Optional[AlertStore] = None
_store_lock = threading.Lock()


def get_alert_store(db_path: str = None) -> AlertStore:
    """Get AlertStore singleton instance

    Args:
        db_path: Optional, custom database path

    Returns:
        AlertStore instance
    """
    global _alert_store_instance

    with _store_lock:
        if _alert_store_instance is None:
            _alert_store_instance = AlertStore(db_path)

        return _alert_store_instance


def close_alert_store():
    """Close alert storage (for cleanup during app shutdown)"""
    global _alert_store_instance

    with _store_lock:
        if _alert_store_instance:
            _alert_store_instance.close()
            _alert_store_instance = None
