#!/usr/bin/env python3
"""
Event Log System - SQLite based event storage for audit trail

Provides persistent storage for system events with full metadata tracking.
All events are retained permanently for audit and compliance purposes.
"""

import sqlite3
import threading
import csv
import io
from dataclasses import dataclass
from datetime import datetime
from typing import List, Optional, Dict, Any
from pathlib import Path


@dataclass
class EventLog:
    """Event log data model for audit trail

    Attributes:
        id: Database auto-increment ID
        event_type: Event category (system_start, ros2_start, rosbag_start, etc.)
        action: Specific action (start, stop, resolve, etc.)
        resource: Resource identifier (ros2, rosbag, alert_id, etc.)
        user: User who performed the action (default: 'system')
        message: Human-readable event description
        metadata: JSON-formatted additional information
        created_at: ISO 8601 timestamp
        success: Whether the operation succeeded
        error: Error message if operation failed
    """
    id: Optional[int] = None
    event_type: str = ""
    action: str = ""
    resource: str = ""
    user: str = "system"
    message: str = ""
    metadata: str = ""
    created_at: str = ""
    success: bool = True
    error: str = ""


class EventLogStore:
    """Event log storage - Singleton pattern, thread-safe

    Provides persistent storage, query, and management for system events.
    All events are retained permanently for audit purposes.
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
            # Default path in ros2_diagnostic directory
            if db_path is None:
                db_path = Path(__file__).parent / 'logs' / 'events.db'
            else:
                db_path = Path(db_path)

            # Ensure logs directory exists
            db_path.parent.mkdir(parents=True, exist_ok=True)

            self.db_path = str(db_path)
            self._conn: Optional[sqlite3.Connection] = None
            self._init_db()
            self._initialized = True

    def _init_db(self):
        """Initialize database connection and tables"""
        try:
            self._conn = sqlite3.connect(
                self.db_path,
                check_same_thread=False,
                timeout=10
            )
            self._conn.row_factory = sqlite3.Row
            self._create_tables()
        except Exception as e:
            print(f"Failed to initialize event log database: {e}")
            raise

    def _create_tables(self):
        """Create event_log table and indexes"""
        self._conn.execute('''
            CREATE TABLE IF NOT EXISTS event_log (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                event_type TEXT NOT NULL,
                action TEXT NOT NULL,
                resource TEXT NOT NULL,
                user TEXT NOT NULL DEFAULT 'system',
                message TEXT NOT NULL,
                metadata TEXT,
                created_at TEXT NOT NULL,
                success INTEGER NOT NULL DEFAULT 1,
                error TEXT
            )
        ''')

        # Create indexes for query performance
        self._conn.execute('CREATE INDEX IF NOT EXISTS idx_event_type ON event_log(event_type)')
        self._conn.execute('CREATE INDEX IF NOT EXISTS idx_action ON event_log(action)')
        self._conn.execute('CREATE INDEX IF NOT EXISTS idx_resource ON event_log(resource)')
        self._conn.execute('CREATE INDEX IF NOT EXISTS idx_created ON event_log(created_at DESC)')
        self._conn.execute('CREATE INDEX IF NOT EXISTS idx_user ON event_log(user)')
        self._conn.execute('CREATE INDEX IF NOT EXISTS idx_event_created ON event_log(event_type, created_at DESC)')

        self._conn.commit()

    def log_event(self, event: EventLog) -> int:
        """Log a new event

        Args:
            event: EventLog object

        Returns:
            New event ID
        """
        cursor = self._conn.execute('''
            INSERT INTO event_log (event_type, action, resource, user, message,
                                metadata, created_at, success, error)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
        ''', (event.event_type, event.action, event.resource, event.user,
              event.message, event.metadata, event.created_at,
              1 if event.success else 0, event.error))

        self._conn.commit()
        return cursor.lastrowid

    def get_events(self, limit: int = 100, offset: int = 0,
                   event_type: str = None, action: str = None,
                   resource: str = None, user: str = None,
                   start_date: str = None, end_date: str = None) -> List[EventLog]:
        """Get events with optional filtering

        Args:
            limit: Maximum number of events to return
            offset: Pagination offset
            event_type: Filter by event type
            action: Filter by action
            resource: Filter by resource
            user: Filter by user
            start_date: Filter events after this ISO date
            end_date: Filter events before this ISO date

        Returns:
            List of EventLog objects
        """
        query = 'SELECT * FROM event_log WHERE 1=1'
        params = []

        if event_type:
            query += ' AND event_type = ?'
            params.append(event_type)
        if action:
            query += ' AND action = ?'
            params.append(action)
        if resource:
            query += ' AND resource = ?'
            params.append(resource)
        if user:
            query += ' AND user = ?'
            params.append(user)
        if start_date:
            query += ' AND created_at >= ?'
            params.append(start_date)
        if end_date:
            query += ' AND created_at <= ?'
            params.append(end_date)

        query += ' ORDER BY created_at DESC LIMIT ? OFFSET ?'
        params.extend([limit, offset])

        cursor = self._conn.execute(query, params)
        rows = cursor.fetchall()
        return [self._row_to_event(row) for row in rows]

    def get_events_by_type(self, event_type: str, limit: int = 50) -> List[EventLog]:
        """Get events by type

        Args:
            event_type: Event type to filter
            limit: Maximum number of events

        Returns:
            List of EventLog objects
        """
        cursor = self._conn.execute('''
            SELECT * FROM event_log
            WHERE event_type = ?
            ORDER BY created_at DESC
            LIMIT ?
        ''', (event_type, limit))

        rows = cursor.fetchall()
        return [self._row_to_event(row) for row in rows]

    def get_events_by_date_range(self, start_date: str, end_date: str,
                                  limit: int = 1000) -> List[EventLog]:
        """Get events within a date range

        Args:
            start_date: Start date (ISO 8601)
            end_date: End date (ISO 8601)
            limit: Maximum number of events

        Returns:
            List of EventLog objects
        """
        cursor = self._conn.execute('''
            SELECT * FROM event_log
            WHERE created_at >= ? AND created_at <= ?
            ORDER BY created_at DESC
            LIMIT ?
        ''', (start_date, end_date, limit))

        rows = cursor.fetchall()
        return [self._row_to_event(row) for row in rows]

    def get_event_stats(self) -> Dict[str, Any]:
        """Get event statistics

        Returns:
            Dictionary with event counts by type, action, and success rate
        """
        cursor = self._conn.execute('''
            SELECT
                COUNT(*) as total,
                COUNT(CASE WHEN success = 1 THEN 1 END) as successful,
                COUNT(CASE WHEN success = 0 THEN 1 END) as failed
            FROM event_log
        ''')
        row = cursor.fetchone()
        stats = dict(row) if row else {}

        # Get counts by event type
        cursor = self._conn.execute('''
            SELECT event_type, COUNT(*) as count
            FROM event_log
            GROUP BY event_type
            ORDER BY count DESC
        ''')
        stats['by_type'] = {row['event_type']: row['count'] for row in cursor.fetchall()}

        # Get counts by action
        cursor = self._conn.execute('''
            SELECT action, COUNT(*) as count
            FROM event_log
            GROUP BY action
            ORDER BY count DESC
        ''')
        stats['by_action'] = {row['action']: row['count'] for row in cursor.fetchall()}

        # Get recent activity (last 24 hours)
        cursor = self._conn.execute('''
            SELECT COUNT(*) as count
            FROM event_log
            WHERE created_at >= datetime('now', '-24 hours')
        ''')
        row = cursor.fetchone()
        stats['last_24h'] = row['count'] if row else 0

        return stats

    def export_to_csv(self, start_date: str = None, end_date: str = None) -> str:
        """Export events to CSV format

        Args:
            start_date: Optional start date filter
            end_date: Optional end date filter

        Returns:
            CSV string
        """
        query = 'SELECT * FROM event_log WHERE 1=1'
        params = []

        if start_date:
            query += ' AND created_at >= ?'
            params.append(start_date)
        if end_date:
            query += ' AND created_at <= ?'
            params.append(end_date)

        query += ' ORDER BY created_at ASC'

        cursor = self._conn.execute(query, params)
        rows = cursor.fetchall()

        output = io.StringIO()
        writer = csv.writer(output)

        # Header
        writer.writerow(['ID', 'Event Type', 'Action', 'Resource', 'User',
                        'Message', 'Metadata', 'Created At', 'Success', 'Error'])

        # Rows
        for row in rows:
            event = self._row_to_event(row)
            writer.writerow([
                event.id,
                event.event_type,
                event.action,
                event.resource,
                event.user,
                event.message,
                event.metadata,
                event.created_at,
                'Yes' if event.success else 'No',
                event.error
            ])

        return output.getvalue()

    def _row_to_event(self, row) -> EventLog:
        """Convert database row to EventLog object"""
        return EventLog(
            id=row['id'],
            event_type=row['event_type'],
            action=row['action'],
            resource=row['resource'],
            user=row['user'],
            message=row['message'],
            metadata=row['metadata'] or '',
            created_at=row['created_at'],
            success=bool(row['success']),
            error=row['error'] or ''
        )

    def close(self):
        """Close database connection"""
        if self._conn:
            self._conn.close()


# Global instance
_event_log_instance: Optional[EventLogStore] = None
_log_lock = threading.Lock()


def get_event_store(db_path: str = None) -> EventLogStore:
    """Get the EventLogStore singleton instance

    Args:
        db_path: Optional custom database path

    Returns:
        EventLogStore instance
    """
    global _event_log_instance

    with _log_lock:
        if _event_log_instance is None:
            _event_log_instance = EventLogStore(db_path)

        return _event_log_instance


def close_event_store():
    """Close the event log store (for cleanup on shutdown)"""
    global _event_log_instance

    with _log_lock:
        if _event_log_instance:
            _event_log_instance.close()
            _event_log_instance = None
