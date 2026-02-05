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
    """告警数据模型

    Attributes:
        id: 数据库自增 ID
        sensor: 传感器名称 (navi_lidar, camera, imu, thruster)
        alert_type: 告警类型 (frame_loss, point_count_low, connectivity, etc.)
        severity: 严重程度 (critical, warning)
        message: 告警消息
        metric_value: 触发告警的测量值
        threshold: 阈值
        metadata: JSON 格式的额外元数据
        created_at: 创建时间 (ISO 8601)
        resolved_at: 解决时间 (ISO 8601), 可选
        status: 状态 (active, resolved, ignored)
    """
    id: Optional[int] = None
    sensor: str = ""
    alert_type: str = ""
    severity: str = ""  # critical, warning
    message: str = ""
    metric_value: float = 0.0
    threshold: float = 0.0
    metadata: str = ""  # JSON 格式
    created_at: str = ""
    resolved_at: Optional[str] = None
    status: str = "active"  # active, resolved, ignored


class AlertStore:
    """告警存储 - 单例模式，线程安全

    提供告警的持久化存储、查询和管理功能。
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
            # 默认路径在 ros2_diagnostic 目录下
            if db_path is None:
                db_path = Path(__file__).parent / 'alerts.db'
            else:
                db_path = Path(db_path)

            self.db_path = str(db_path)
            self._conn: Optional[sqlite3.Connection] = None
            self._alert_callback = None  # 告警回调函数（用于实时推送）
            self._init_db()
            self._initialized = True

    def _init_db(self):
        """初始化数据库连接和表"""
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
        """创建告警表和索引"""
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

        # 创建索引以提高查询性能
        self._conn.execute('CREATE INDEX IF NOT EXISTS idx_sensor ON alerts(sensor)')
        self._conn.execute('CREATE INDEX IF NOT EXISTS idx_status ON alerts(status)')
        self._conn.execute('CREATE INDEX IF NOT EXISTS idx_created ON alerts(created_at DESC)')
        self._conn.execute('CREATE INDEX IF NOT EXISTS idx_severity ON alerts(severity)')
        self._conn.execute('CREATE INDEX IF NOT EXISTS idx_sensor_status ON alerts(sensor, status)')

        self._conn.commit()

    def set_alert_callback(self, callback):
        """设置告警回调函数（用于实时推送）

        Args:
            callback: 异步回调函数，接收 Alert 对象作为参数
        """
        self._alert_callback = callback

    async def _trigger_alert_callback(self, alert: Alert):
        """触发告警回调（异步执行）

        Args:
            alert: Alert 对象
        """
        if self._alert_callback:
            try:
                # 尝试作为协程调用
                if asyncio.iscoroutinefunction(self._alert_callback):
                    await self._alert_callback(alert)
                else:
                    # 普通函数，在 asyncio 事件循环中调度
                    loop = asyncio.get_event_loop()
                    if loop.is_running():
                        asyncio.create_task(self._alert_callback(alert))
                    else:
                        # 如果事件循环未运行，直接调用
                        self._alert_callback(alert)
            except Exception as e:
                print(f"Error in alert callback: {e}")

    def add_alert(self, alert: Alert) -> int:
        """添加新告警

        Args:
            alert: Alert 对象

        Returns:
            新告警的 ID
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

        # 触发实时推送回调（异步执行，不阻塞 add_alert）
        if self._alert_callback:
            try:
                # 尝试获取运行中的事件循环
                try:
                    loop = asyncio.get_running_loop()
                    # 在运行中的事件循环中调度任务
                    loop.create_task(self._alert_callback(alert))
                except RuntimeError:
                    # 没有运行中的事件循环，尝试使用 run_in_executor
                    import threading
                    def run_callback():
                        try:
                            new_loop = asyncio.new_event_loop()
                            asyncio.set_event_loop(new_loop)
                            if asyncio.iscoroutinefunction(self._alert_callback):
                                new_loop.run_until_complete(self._alert_callback(alert))
                            else:
                                self._alert_callback(alert)
                            new_loop.close()
                        except Exception as e:
                            print(f"Error in alert callback thread: {e}")
                    thread = threading.Thread(target=run_callback, daemon=True)
                    thread.start()
            except Exception as e:
                print(f"Error scheduling alert callback: {e}")

        return alert_id

    def get_active_alerts(self, sensor: str = None) -> List[Alert]:
        """获取活动告警

        Args:
            sensor: 可选，按传感器过滤

        Returns:
            Alert 对象列表
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
        """获取最近的告警（包括可选的已解决告警）

        Args:
            limit: 返回数量限制
            offset: 偏移量
            include_resolved: 是否包含已解决的告警

        Returns:
            Alert 对象列表
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
        """解决告警

        Args:
            alert_id: 告警 ID

        Returns:
            是否成功解决
        """
        cursor = self._conn.execute('''
            UPDATE alerts SET status = 'resolved', resolved_at = ?
            WHERE id = ?
        ''', (datetime.now().isoformat(), alert_id))
        self._conn.commit()
        return cursor.rowcount > 0

    def ignore_alert(self, alert_id: int) -> bool:
        """忽略告警（不再显示，但保留记录）

        Args:
            alert_id: 告警 ID

        Returns:
            是否成功忽略
        """
        cursor = self._conn.execute('''
            UPDATE alerts SET status = 'ignored'
            WHERE id = ?
        ''', (alert_id,))
        self._conn.commit()
        return cursor.rowcount > 0

    def get_alert_stats(self) -> Dict[str, Any]:
        """获取告警统计

        Returns:
            包含总告警数、活动告警数、严重程度统计的字典
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
        """按传感器获取告警

        Args:
            sensor: 传感器名称
            limit: 返回数量限制

        Returns:
            Alert 对象列表
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
        """按严重程度获取告警

        Args:
            severity: 严重程度 (critical, warning)
            limit: 返回数量限制

        Returns:
            Alert 对象列表
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
        """清理旧告警（可选功能，按需求使用）

        注意：根据用户需求，默认保留所有告警。此方法仅用于
        手动清理非常旧的告警。

        Args:
            days: 保留最近多少天的告警

        Returns:
            删除的告警数量
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
        """关闭数据库连接"""
        if self._conn:
            self._conn.close()


# 全局实例
_alert_store_instance: Optional[AlertStore] = None
_store_lock = threading.Lock()


def get_alert_store(db_path: str = None) -> AlertStore:
    """获取 AlertStore 单例实例

    Args:
        db_path: 可选，自定义数据库路径

    Returns:
        AlertStore 实例
    """
    global _alert_store_instance

    with _store_lock:
        if _alert_store_instance is None:
            _alert_store_instance = AlertStore(db_path)

        return _alert_store_instance


def close_alert_store():
    """关闭告警存储（用于应用关闭时清理）"""
    global _alert_store_instance

    with _store_lock:
        if _alert_store_instance:
            _alert_store_instance.close()
            _alert_store_instance = None
