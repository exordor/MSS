#!/usr/bin/env python3
"""
ROS2 System Diagnostic Web Application
FastAPI-based web interface with WebSocket support for system and sensor diagnostics
"""

import os
import sys
import json
import logging
import time
import asyncio
import io
from datetime import datetime
from threading import Thread, Lock
from typing import List, Dict, Any, Optional, Set
from enum import Enum
from dataclasses import field, dataclass

from fastapi import FastAPI, WebSocket, WebSocketDisconnect, Request, Response
from fastapi.responses import HTMLResponse, JSONResponse, StreamingResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
from contextlib import asynccontextmanager
from pydantic import BaseModel
import uvicorn

# Add parent directory to path for imports
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from config import (
    ROS2_CONFIG, ROS2_CONTROL, ROSBAG_CONFIG, SENSOR_IPS, SENSOR_THRESHOLDS,
    EXPECTED_NODES, IGNORED_NODES, SENSOR_NODES, ROS2_TOPICS,
    ENABLE_TOPIC_DETAILS, CACHE_TTL, LOG_FILES, LOG_ROOT, UI_CONFIG, PROJECT_ROOT,
    TOOLS_CONFIG_FILES, EVENT_LOG_CONFIG
)
from diagnostics import ROS2Monitor, ROS2Controller
from diagnostics.rosbag_controller import get_rosbag_controller
from diagnostics.sensor_monitor import (
    NaviLidarDiagnostic, UliLidarDiagnostic,
    CameraDiagnostic, IMUDiagnostic, ThrusterDiagnostic, BatteryDiagnostic
)
from alerts import get_alert_store, Alert
from event_log import get_event_store, EventLog

# =============================================================================
# Configure logging
# =============================================================================

logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    handlers=[
        logging.FileHandler(LOG_FILES.get('diagnostic', 'diagnostic.log')),
        logging.StreamHandler()
    ]
)
logger = logging.getLogger(__name__)

# =============================================================================
# Global state (thread-safe)
# =============================================================================

_monitors: Dict[str, Any] = {}
_monitors_lock = Lock()

_ros2_controller = None
_ros2_controller_lock = Lock()

_cache: Dict[str, Dict] = {}
_cache_lock = Lock()

# Cache statistics
_cache_stats = {"hits": 0, "misses": 0}
_cache_stats_lock = Lock()

# Wireless IP cache
_wireless_ip_cache = {"value": None, "time": 0}
_wireless_ip_lock = Lock()

# Event stats cache (60 second TTL)
_event_stats_cache = {"value": None, "time": 0}
_event_stats_lock = Lock()
_EVENT_STATS_TTL = 60  # Statistics only need to refresh every minute

# Event store callback setup
_event_store_callback_registered = False


def _invalidate_event_stats():
    """Invalidate event stats cache (called when events are logged)"""
    with _event_stats_lock:
        _event_stats_cache["time"] = 0  # Force cache refresh


def _ensure_event_store_callback():
    """Ensure event stats invalidate callback is registered once"""
    global _event_store_callback_registered
    if not _event_store_callback_registered:
        try:
            event_store = get_event_store()
            event_store.set_stats_invalidate_callback(_invalidate_event_stats)
            _event_store_callback_registered = True
            logger.info("[Event Log] Stats cache callback registered")
        except Exception as e:
            logger.warning(f"[Event Log] Failed to register stats callback: {e}")

# Previous state for incremental updates
_prev_state = {}
_state_lock = Lock()


def calculate_state_diff(prev: dict, curr: dict) -> dict:
    """Calculate the difference between two states for incremental WebSocket updates."""
    if not prev:
        return curr  # First time, send full state

    diff = {}
    for key, value in curr.items():
        if key not in prev or prev[key] != value:
            if isinstance(value, dict) and key in prev and isinstance(prev.get(key), dict):
                # Recursively compare nested dictionaries
                nested_diff = calculate_state_diff(prev.get(key, {}), value)
                if nested_diff:
                    diff[key] = nested_diff
            else:
                # Value changed or different type
                diff[key] = value
    return diff


# =============================================================================
# WebSocket Channels (for subscription mode)
# =============================================================================

class Channel(Enum):
    """WebSocket 数据频道"""
    SENSORS = "sensors"       # 传感器状态 (1秒)
    ALERTS = "alerts"         # 告警 (实时)
    ROS2 = "ros2"            # ROS2 系统 (10秒)
    ROS2_CONTROL = "ros2_control"  # ROS2 控制 (5秒)
    ROSBAG = "rosbag"        # Rosbag (5秒)


@dataclass
class ConnectionInfo:
    """WebSocket 连接信息"""
    websocket: Any  # WebSocket object
    channels: Set[Channel]  # 订阅的频道
    connected_at: float  # 连接时间


# =============================================================================
# WebSocket Connection Manager (支持订阅模式)
# =============================================================================

class ConnectionManager:
    """支持订阅的连接管理器"""

    def __init__(self):
        # 新格式：connections[websocket] = ConnectionInfo
        self.connections: Dict[Any, ConnectionInfo] = {}
        self._lock = Lock()

    async def connect(
        self,
        websocket: WebSocket,
        channels: List[Channel] = None
    ):
        """接受新连接并设置默认订阅"""
        await websocket.accept()

        with self._lock:
            self.connections[websocket] = ConnectionInfo(
                websocket=websocket,
                channels=set(channels or [Channel.SENSORS, Channel.ALERTS, Channel.ROS2, Channel.ROS2_CONTROL, Channel.ROSBAG]),
                connected_at=time.time()
            )

        logger.info(
            f"[WS] Connected. Subscriptions: "
            f"{[c.value for c in self.connections[websocket].channels]}, "
            f"Total: {len(self.connections)}"
        )

    async def subscribe(self, websocket: WebSocket, channel: Channel):
        """订阅频道"""
        with self._lock:
            if websocket in self.connections:
                self.connections[websocket].channels.add(channel)
                logger.debug(f"[WS] Subscribed to {channel.value}")

    async def unsubscribe(self, websocket: WebSocket, channel: Channel):
        """取消订阅"""
        with self._lock:
            if websocket in self.connections:
                self.connections[websocket].channels.discard(channel)
                logger.debug(f"[WS] Unsubscribed from {channel.value}")

    async def broadcast_to_channel(
        self,
        channel: Channel,
        message: dict
    ):
        """向订阅了特定频道的客户端广播"""
        disconnected = []

        # Get connections that are subscribed to this channel
        with self._lock:
            target_connections = [(ws, info) for ws, info in self.connections.items()
                                  if channel in info.channels]

        # Send to all target connections (outside lock to avoid blocking)
        for ws, info in target_connections:
            try:
                await ws.send_json(message)
            except Exception as e:
                logger.debug(f"[WS] Send failed: {e}")
                disconnected.append(ws)

        # 清理断开的连接
        for ws in disconnected:
            await self._async_disconnect(ws)

    def disconnect(self, websocket: WebSocket):
        """Remove a WebSocket connection"""
        with self._lock:
            if websocket in self.connections:
                del self.connections[websocket]
        logger.info(f"[WS] Disconnected. Total: {len(self.connections)}")

    async def send_personal(self, message: dict, websocket: WebSocket):
        """Send a message to a specific WebSocket connection"""
        try:
            await websocket.send_json(message)
        except Exception as e:
            logger.error(f"Error sending to WebSocket: {e}")
            await self._async_disconnect(websocket)

    async def broadcast(self, message: dict):
        """Broadcast a message to all connected WebSocket clients (legacy, for alerts)"""
        disconnected = []

        # Copy connections list to avoid modification during iteration
        with self._lock:
            connections = list(self.connections.items())

        # Send to all connections (outside lock to avoid blocking)
        for connection, info in connections:
            try:
                await connection.send_json(message)
            except Exception as e:
                logger.debug(f"Failed to send to connection: {e}")
                disconnected.append(connection)

        # Remove disconnected clients (with proper locking)
        for ws in disconnected:
            await self._async_disconnect(ws)

    async def _async_disconnect(self, websocket: WebSocket):
        """Async version of disconnect for use within async context"""
        with self._lock:
            if websocket in self.connections:
                del self.connections[websocket]
        logger.info(f"[WS] Disconnected. Total: {len(self.connections)}")

    async def send_full_state(self, websocket: WebSocket, channels: Set[Channel] = None):
        """Send complete system state to a newly connected client.

        Uses cached version to avoid blocking when multiple clients connect rapidly.
        The cache is warmed by the background broadcaster every 5 seconds.

        Args:
            websocket: WebSocket 连接
            channels: 订阅的频道（可选，从 ConnectionInfo 获取）
        """
        # 如果没有指定频道，从连接信息获取
        if channels is None:
            with self._lock:
                info = self.connections.get(websocket)
                if info:
                    channels = info.channels
                else:
                    # Default channels - send all data needed by dashboard
                    channels = {Channel.SENSORS, Channel.ALERTS, Channel.ROS2, Channel.ROS2_CONTROL, Channel.ROSBAG}

        state = {}
        # Use parallel async check for sensors (faster, doesn't block)
        if Channel.SENSORS in channels:
            state["sensors"] = await collect_sensor_status_parallel()
        if Channel.ROS2 in channels:
            state["ros2"] = collect_ros2_status_cached()
        if Channel.ROS2_CONTROL in channels:
            state["ros2_control"] = collect_ros2_control_status()
        if Channel.ROSBAG in channels:
            state["rosbag"] = collect_rosbag_status()
        if Channel.ALERTS in channels:
            state["alerts"] = collect_active_alerts()

        await websocket.send_json({
            "type": "full_state",
            "data": state,
            "timestamp": time.time()
        })

        # 发送订阅确认
        await websocket.send_json({
            "type": "subscribed",
            "channels": [c.value for c in channels],
            "timestamp": time.time()
        })

    def get_connection_count(self) -> int:
        """Get the number of active WebSocket connections"""
        with self._lock:
            return len(self.connections)


manager = ConnectionManager()


# =============================================================================
# Message Compressor (for WebSocket message compression)
# =============================================================================

class MessageCompressor:
    """消息压缩器 - 缩短字段名和 gzip 压缩"""

    # 字段名映射（缩短常用字段）
    FIELD_MAP = {
        'sensors': 's',
        'ros2': 'r2',
        'ros2_control': 'r2c',
        'rosbag': 'rb',
        'alerts': 'a',
        'status': 'st',
        'message': 'msg',
        'frequency': 'freq',
        'timestamp': 'ts',
        'navi_lidar': 'nl',
        'uli_lidar': 'ul',
        'camera': 'cam',
        'imu': 'imu',
        'thruster': 'th',
        'battery': 'bat',
        'alert_type': 'at',
        'metric_value': 'mv',
        'created_at': 'ca',
        'resolved_at': 'ra',
    }

    @classmethod
    def minify_json(cls, data: dict) -> dict:
        """缩短 JSON 字段名"""
        if isinstance(data, dict):
            return {
                cls.FIELD_MAP.get(k, k): cls.minify_json(v)
                for k, v in data.items()
            }
        elif isinstance(data, list):
            return [cls.minify_json(item) for item in data]
        return data

    @classmethod
    def compress(cls, data: dict) -> bytes:
        """压缩消息（minify + gzip）"""
        import gzip as gzip_module
        # 先缩短字段名
        minified = cls.minify_json(data)
        # 转 JSON
        json_str = json.dumps(minified, separators=(',', ':'))
        # Gzip 压缩
        return gzip_module.compress(json_str.encode())


# =============================================================================
# Alert Broadcast Function (for real-time alert push)
# =============================================================================

async def broadcast_alert(alert: Any) -> None:
    """立即推送新告警到所有 WebSocket 客户端

    This function is called by AlertStore when a new alert is added.

    Args:
        alert: Alert 对象（来自 alerts.py）
    """
    try:
        # 转换 Alert 对象为字典
        if hasattr(alert, '_asdict'):
            alert_dict = alert._asdict()
        else:
            # 如果是普通对象，提取属性
            alert_dict = {
                'id': getattr(alert, 'id', None),
                'sensor': getattr(alert, 'sensor', ''),
                'alert_type': getattr(alert, 'alert_type', ''),
                'severity': getattr(alert, 'severity', ''),
                'message': getattr(alert, 'message', ''),
                'metric_value': getattr(alert, 'metric_value', 0.0),
                'threshold': getattr(alert, 'threshold', 0.0),
                'metadata': getattr(alert, 'metadata', ''),
                'created_at': getattr(alert, 'created_at', ''),
                'status': getattr(alert, 'status', 'active'),
            }

        await manager.broadcast({
            "type": "alert",
            "data": alert_dict,
            "timestamp": time.time()
        })
        logger.info(f"[WS] Alert broadcasted: {alert_dict.get('alert_type')} - {alert_dict.get('message')}")
    except Exception as e:
        logger.error(f"[WS] Failed to broadcast alert: {e}")


# =============================================================================
# Helper Functions
# =============================================================================

# =============================================================================
# Helper Functions
# =============================================================================

def _cache_set(key: str, data: dict):
    with _cache_lock:
        _cache[key] = {
            'ts': time.time(),
            'data': data,
        }


def _cache_get(key: str, max_age: int):
    with _cache_lock:
        entry = _cache.get(key)
        if not entry:
            with _cache_stats_lock:
                _cache_stats["misses"] += 1
            return None
        if time.time() - entry['ts'] > max_age:
            with _cache_stats_lock:
                _cache_stats["misses"] += 1
            return None
        with _cache_stats_lock:
            _cache_stats["hits"] += 1
        return entry['data']


def invalidate_cache_pattern(pattern: str) -> int:
    """Clear all cache entries matching the given pattern prefix."""
    with _cache_lock:
        keys_to_delete = [k for k in _cache.keys() if k.startswith(pattern)]
        for key in keys_to_delete:
            del _cache[key]
        count = len(keys_to_delete)
        if count > 0:
            logger.debug(f"[CACHE] Cleared {count} entries matching '{pattern}'")
        return count


def _resolve_log_path(category: str, session_id: str, filename: str):
    if category == 'application':
        if filename == 'diagnostic':
            return LOG_FILES.get('diagnostic'), None
        if filename == 'ros2':
            return LOG_FILES.get('ros2_control'), None
        return None, ({'success': False, 'error': f'Unknown application log: {filename}'}, 400)

    if category == 'session':
        if not session_id or not filename:
            return None, ({'success': False, 'error': 'Session ID and filename are required for session logs'}, 400)
        session_path = os.path.join(LOG_ROOT, session_id)
        log_path = os.path.normpath(os.path.join(session_path, filename))
        session_root = os.path.abspath(session_path) + os.sep
        if not log_path.startswith(session_root):
            return None, ({'success': False, 'error': 'Invalid log file path'}, 400)
        return log_path, None

    return None, ({'success': False, 'error': f'Unknown log category: {category}'}, 400)


def get_ros2_controller():
    """Get or create ROS2 controller instance"""
    global _ros2_controller
    with _ros2_controller_lock:
        if _ros2_controller is None:
            _ros2_controller = ROS2Controller({
                'ROS2_CONFIG': ROS2_CONFIG,
                'ROS2_CONTROL': ROS2_CONTROL,
                'LOG_FILES': LOG_FILES,
            })
        return _ros2_controller


def get_wireless_ip() -> str:
    """Get the wireless IP address of the host (internal, non-cached)"""
    import socket
    try:
        import psutil
        for interface, addrs in psutil.net_if_addrs().items():
            if interface.startswith('wl') or interface.startswith('wlan') or interface.startswith('wlp'):
                for addr in addrs:
                    if addr.family == socket.AF_INET:
                        return addr.address
    except Exception:
        pass

    try:
        s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        s.settimeout(0)
        s.connect(('10.254.254.254', 1))
        ip = s.getsockname()[0]
        s.close()
        return ip
    except Exception:
        pass

    return '127.0.0.1'


def get_wireless_ip_cached() -> str:
    """Get the wireless IP address with 30-second caching."""
    global _wireless_ip_cache
    cache_ttl = 30

    with _wireless_ip_lock:
        if _wireless_ip_cache["value"] and time.time() - _wireless_ip_cache["time"] < cache_ttl:
            return _wireless_ip_cache["value"]

        # Fetch new IP
        _wireless_ip_cache["value"] = get_wireless_ip()
        _wireless_ip_cache["time"] = time.time()
        return _wireless_ip_cache["value"]


def get_monitor(name: str):
    """Get or create monitor instance"""
    with _monitors_lock:
        if name not in _monitors:
            if name == 'ros2':
                _monitors[name] = ROS2Monitor({
                    'ROS2_CONFIG': ROS2_CONFIG,
                    'EXPECTED_NODES': EXPECTED_NODES,
                    'IGNORED_NODES': IGNORED_NODES,
                    'SENSOR_NODES': SENSOR_NODES,
                    'ROS2_TOPICS': ROS2_TOPICS,
                    'ENABLE_TOPIC_DETAILS': ENABLE_TOPIC_DETAILS,
                })
            elif name == 'navi_lidar':
                _monitors[name] = NaviLidarDiagnostic({
                    'SENSOR_THRESHOLDS': SENSOR_THRESHOLDS,
                    'SENSOR_IPS': SENSOR_IPS,
                    'ROS2_TOPICS': ROS2_TOPICS,
                    'ENABLE_TOPIC_DETAILS': ENABLE_TOPIC_DETAILS,
                })
            elif name == 'uli_lidar':
                _monitors[name] = UliLidarDiagnostic({
                    'SENSOR_THRESHOLDS': SENSOR_THRESHOLDS,
                    'SENSOR_IPS': SENSOR_IPS,
                    'ROS2_TOPICS': ROS2_TOPICS,
                    'ENABLE_TOPIC_DETAILS': ENABLE_TOPIC_DETAILS,
                })
            elif name == 'camera':
                _monitors[name] = CameraDiagnostic({
                    'SENSOR_THRESHOLDS': SENSOR_THRESHOLDS,
                    'SENSOR_IPS': SENSOR_IPS,
                    'ROS2_TOPICS': ROS2_TOPICS,
                    'ENABLE_TOPIC_DETAILS': ENABLE_TOPIC_DETAILS,
                })
            elif name == 'imu':
                _monitors[name] = IMUDiagnostic({
                    'SENSOR_THRESHOLDS': SENSOR_THRESHOLDS,
                    'SENSOR_IPS': SENSOR_IPS,
                    'ROS2_TOPICS': ROS2_TOPICS,
                    'ENABLE_TOPIC_DETAILS': ENABLE_TOPIC_DETAILS,
                })
            elif name == 'thruster':
                _monitors[name] = ThrusterDiagnostic({
                    'SENSOR_THRESHOLDS': SENSOR_THRESHOLDS,
                    'SENSOR_IPS': SENSOR_IPS,
                    'ROS2_TOPICS': ROS2_TOPICS,
                    'ENABLE_TOPIC_DETAILS': ENABLE_TOPIC_DETAILS,
                })
            elif name == 'battery':
                _monitors[name] = BatteryDiagnostic({
                    'SENSOR_THRESHOLDS': SENSOR_THRESHOLDS,
                    'SENSOR_IPS': SENSOR_IPS,
                    'ROS2_TOPICS': ROS2_TOPICS,
                    'ENABLE_TOPIC_DETAILS': ENABLE_TOPIC_DETAILS,
                })
        return _monitors[name]


def collect_all_state() -> Dict[str, Any]:
    """Collect complete system state for WebSocket broadcast"""
    state = {
        "sensors": collect_sensor_status(),
        "ros2": collect_ros2_status(),
        "ros2_control": collect_ros2_control_status(),
        "rosbag": collect_rosbag_status(),
        "alerts": collect_active_alerts(),
    }
    return state


def collect_all_state_cached() -> Dict[str, Any]:
    """Collect complete system state with caching for frequent operations."""
    state = {
        "sensors": collect_sensor_status_cached(),  # Uses parallel check internally
        "ros2": collect_ros2_status_cached(),
        "ros2_control": collect_ros2_control_status(),  # No cache - needs real-time status
        "rosbag": collect_rosbag_status(),  # No cache - needs real-time status
        "alerts": collect_active_alerts(),  # No cache - needs real-time status
    }
    return state


async def collect_all_state_async() -> Dict[str, Any]:
    """Collect complete system state with parallel sensor checks."""
    state = {
        "sensors": await collect_sensor_status_parallel(),  # Parallel execution
        "ros2": collect_ros2_status_cached(),
        "ros2_control": collect_ros2_control_status(),
        "rosbag": collect_rosbag_status(),
        "alerts": collect_active_alerts(),
    }
    return state


def get_ros2_processes_cached() -> List[Dict]:
    """Get ROS2 process list with 3-second caching."""
    cache_key = 'ros2:processes'
    cached = _cache_get(cache_key, max_age=3)
    if cached is not None:
        return cached

    import psutil
    processes = []
    for proc in psutil.process_iter(['pid', 'name', 'cmdline']):
        try:
            cmdline = proc.info.get('cmdline', [])
            if cmdline:
                cmdline_str = ' '.join(cmdline).lower()
                if 'ros2' in cmdline_str and 'diagnostic' not in cmdline_str:
                    processes.append({
                        'pid': proc.info['pid'],
                        'name': proc.info['name'],
                        'cmdline': cmdline_str[:100]
                    })
        except:
            continue

    _cache_set(cache_key, processes)
    return processes


def collect_sensor_status_cached() -> Dict[str, Any]:
    """Collect sensor status with caching (TTL from config)."""
    cache_key = 'sensors:status'
    cached = _cache_get(cache_key, max_age=CACHE_TTL.get('sensors', 2))
    if cached is not None:
        return cached

    result = collect_sensor_status()
    _cache_set(cache_key, result)
    return result


def _check_single_sensor(sensor_name: str) -> Dict[str, Any]:
    """Check a single sensor and return formatted result (internal, for parallel execution)."""
    try:
        monitor = get_monitor(sensor_name)
        result = monitor.check()
        summary = monitor.get_diagnostic_summary()

        metrics = result.metrics or {}
        frequency = None
        packet_loss = None
        connected = '--'
        gps_fix = None
        satellites = None
        topic_available = None
        node_available = None

        if sensor_name in ['navi_lidar', 'uli_lidar']:
            log_data = metrics.get('log_data', {})
            freq_value = log_data.get('measured_frequency')
            if freq_value is not None:
                frequency = f"{freq_value:.1f} Hz"
            network = metrics.get('network', {})
            connected = 'Connected' if network.get('reachable') else 'Disconnected'
        elif sensor_name == 'camera':
            log_data = metrics.get('log_data', {})
            fps_value = log_data.get('measured_frequency')
            if fps_value is not None:
                frequency = f"{fps_value:.1f} fps"
            latency_value = log_data.get('avg_processing_ms')
            if latency_value is not None:
                packet_loss = f"{latency_value:.1f} ms"
            network = metrics.get('network', {})
            connected = 'Connected' if network.get('reachable') else 'Disconnected'
        elif sensor_name == 'imu':
            log_data = metrics.get('log_data', {})
            freq_value = log_data.get('measured_frequency')
            if freq_value is not None:
                frequency = f"{freq_value:.1f} Hz"
            gps = metrics.get('gps', {})
            gps_fix = gps.get('fix_status')
            satellites = gps.get('satellites')
            connected = 'Connected' if metrics.get('serial', {}).get('connected') else 'Disconnected'
        elif sensor_name == 'thruster':
            # Thruster uses UDP heartbeat, stored in 'network' metrics
            network = metrics.get('network', {})
            udp = metrics.get('udp', {})
            connected = 'Connected' if network.get('reachable', False) else 'Disconnected'
            latency = network.get('latency_ms', 0)
            packet_loss = network.get('packet_loss', 0)

        # Extract topic and node availability using helper functions
        # This ensures consistent detection across all code paths
        topic_available = _get_topic_available(metrics, sensor_name)
        node_available = _get_node_available(sensor_name)

        # Calculate final status based on node/topic availability
        # Skip uli_lidar (no ROS driver)
        final_status = summary['status']
        final_color = summary['color']
        final_message = summary.get('message', '')

        if sensor_name != 'uli_lidar' and node_available is not None:
            if node_available and topic_available:
                # Both node and topic available - status is OK
                final_status = 'ok'
                final_color = 'green'
                # Update message to reflect full status
                sensor_display_names = {
                    'navi_lidar': 'Navi LiDAR',
                    'uli_lidar': 'U-LiDAR',
                    'camera': 'Camera',
                    'imu': 'IMU',
                    'thruster': 'Arduino (Thruster)',
                }
                display_name = sensor_display_names.get(sensor_name, sensor_name)
                if 'connected' in summary['status']:
                    final_message = f"{display_name} - OK (node and topic active)"
            elif node_available and not topic_available:
                # Node running but no topic data
                final_status = 'connected'
                final_color = 'blue'
            elif not node_available:
                # Node not running - use original status
                final_status = summary['status']
                final_color = summary['color']

        return {
            'status': final_status,
            'color': final_color,
            'value': summary.get('value', 'N/A'),
            'message': final_message,
            'frequency': frequency,
            'packet_loss': packet_loss,
            'connected': connected,
            'gps_fix': gps_fix,
            'satellites': satellites,
            'topic_available': topic_available,
            'node_available': node_available,
        }
    except Exception as e:
        logger.debug(f"Error checking {sensor_name}: {e}")
        return {
            'status': 'unknown',
            'color': '#6b7280',
            'value': 'N/A',
            'message': str(e),
            'connected': '--',
        }


async def check_sensor_async(sensor_name: str) -> Dict[str, Any]:
    """Async wrapper for sensor check using thread pool executor."""
    loop = asyncio.get_event_loop()
    return await loop.run_in_executor(None, _check_single_sensor, sensor_name)


async def collect_sensor_status_parallel() -> Dict[str, Any]:
    """Collect sensor status in parallel using asyncio."""
    sensor_names = ['navi_lidar', 'uli_lidar', 'camera', 'imu', 'thruster', 'battery']

    # Run all sensor checks in parallel
    tasks = [check_sensor_async(name) for name in sensor_names]
    results = await asyncio.gather(*tasks, return_exceptions=True)

    # Combine results
    sensors = {}
    for name, result in zip(sensor_names, results):
        if isinstance(result, Exception):
            logger.debug(f"Error collecting {name}: {result}")
            sensors[name] = {
                'status': 'unknown',
                'color': '#6b7280',
                'value': 'N/A',
                'message': str(result),
                'connected': '--',
            }
        else:
            sensors[name] = result

    # Calculate overall status
    statuses = [s['status'] for s in sensors.values()]
    if 'critical' in statuses:
        overall = 'critical'
    elif 'warning' in statuses:
        overall = 'warning'
    elif 'unknown' in statuses:
        overall = 'unknown'
    else:
        overall = 'ok'

    ok_count = sum(1 for s in sensors.values() if s['status'] == 'ok')

    result = {
        'sensors': sensors,
        'overall': overall,
        'summary': f"{ok_count}/{len(sensors)} OK",
    }

    # Update cache so that send_full_state can use it
    _cache_set('sensors:status', result)
    logger.debug("[CACHE] Warmed sensor status cache from parallel check")

    return result


def collect_ros2_status_cached() -> Dict[str, Any]:
    """Collect ROS2 status with caching (TTL from config)."""
    cache_key = 'ros2:status'
    cached = _cache_get(cache_key, max_age=CACHE_TTL.get('ros2', 3))
    if cached is not None:
        return cached

    result = collect_ros2_status()
    _cache_set(cache_key, result)
    return result


def _get_topic_available(metrics: dict, sensor_name: str) -> Optional[bool]:
    """Extract topic availability from sensor metrics.

    Args:
        metrics: Sensor metrics dict from monitor.check()
        sensor_name: Name of the sensor

    Returns:
        True if topic is available, False if not, None if unknown
    """
    # Specific topic names to check (more reliable than patterns)
    exact_topics = {
        'navi_lidar': '/navi_lidar/points',
        'uli_lidar': '/uli_lidar/points',
        'camera': '/image_raw',
        'imu': '/imu/data',
        'thruster': '/thruster_status_pwm',
    }

    # Topic patterns for fallback matching
    topic_patterns = {
        'navi_lidar': ['points', 'hesai'],
        'camera': ['image_raw', 'camera'],
        'imu': ['imu/data', 'sbg'],
        'thruster': ['thruster_status', 'thruster'],
    }

    # Method 1: Check from sensor metrics (most reliable if available)
    topics = metrics.get('topics', {})
    if topics:
        topic_field_map = {
            'navi_lidar': 'points_available',
            'uli_lidar': 'points_available',
            'camera': 'image_available',
            'imu': 'data_available',
            'thruster': 'status_available',
        }

        if sensor_name in topic_field_map:
            value = topics.get(topic_field_map[sensor_name])
            if value is not None:
                logger.debug(f"[{sensor_name}] Topic from metrics: {value}")
                return value

        # Generic fallback: look for any *_available field
        for key, value in topics.items():
            if key.endswith('_available'):
                logger.debug(f"[{sensor_name}] Topic from metrics field {key}: {value}")
                return value

    # Method 2: Use ROS2Monitor._check_topics() result
    try:
        from diagnostics import ROS2Monitor
        ros2_monitor = ROS2Monitor({
            'ROS2_CONFIG': ROS2_CONFIG,
            'EXPECTED_NODES': EXPECTED_NODES,
            'IGNORED_NODES': IGNORED_NODES,
        })
        check_result = ros2_monitor._check_topics()
        topics = check_result.get('metrics', {}).get('all', [])
        if topics and sensor_name in exact_topics:
            exact = exact_topics[sensor_name]
            if exact in topics:
                logger.debug(f"[{sensor_name}] Topic found via ROS2Monitor: {exact}")
                return True
        # Pattern matching
        if topics and sensor_name in topic_patterns:
            patterns = topic_patterns[sensor_name]
            for topic in topics:
                if any(pattern in topic.lower() for pattern in patterns):
                    logger.debug(f"[{sensor_name}] Topic pattern found: {topic}")
                    return True
    except Exception as e:
        logger.debug(f"[{sensor_name}] ROS2Monitor topic check failed: {e}")

    # Method 3: Use rclpy helper from ROS2Monitor
    try:
        from diagnostics import ROS2Monitor
        ros2_monitor = ROS2Monitor({
            'ROS2_CONFIG': ROS2_CONFIG,
            'EXPECTED_NODES': EXPECTED_NODES,
            'IGNORED_NODES': IGNORED_NODES,
        })
        helper = ros2_monitor._get_helper()
        if helper and helper.is_ready():
            topics_with_types = helper.get_topic_names_and_types()
            topic_names = [t[0] for t in topics_with_types]
            if sensor_name in exact_topics:
                exact = exact_topics[sensor_name]
                if exact in topic_names:
                    logger.debug(f"[{sensor_name}] Topic found via rclpy helper: {exact}")
                    return True
            if sensor_name in topic_patterns:
                patterns = topic_patterns[sensor_name]
                for topic in topic_names:
                    if any(pattern in topic.lower() for pattern in patterns):
                        logger.debug(f"[{sensor_name}] Topic pattern found via helper: {topic}")
                        return True
    except Exception as e:
        logger.debug(f"[{sensor_name}] rclpy helper topic check failed: {e}")

    # Method 4: Fallback to shell command
    if sensor_name in topic_patterns:
        try:
            import subprocess
            shell_result = subprocess.run(
                ['ros2', 'topic', 'list'],
                capture_output=True,
                text=True,
                timeout=2,
                env={**os.environ, 'ROS_DOMAIN_ID': str(_get_domain_id())}
            )
            if shell_result.returncode == 0:
                all_topics = [t.strip() for t in shell_result.stdout.strip().split('\n') if t.strip()]
                # Check exact match first
                if sensor_name in exact_topics:
                    exact = exact_topics[sensor_name]
                    if exact in all_topics:
                        logger.debug(f"[{sensor_name}] Topic found via shell: {exact}")
                        return True
                # Then pattern matching
                patterns = topic_patterns[sensor_name]
                found = any(
                    any(pattern in topic.lower() for pattern in patterns)
                    for topic in all_topics
                )
                if found:
                    logger.debug(f"[{sensor_name}] Topic pattern found via shell")
                return found
        except Exception as e:
            logger.debug(f"[{sensor_name}] Shell topic check failed: {e}")

    return None


def _get_node_available(sensor_name: str) -> Optional[bool]:
    """Check if ROS2 nodes for a sensor are running.

    Args:
        sensor_name: Name of the sensor

    Returns:
        True if nodes are found, False if not, None if ROS2 not running or error
    """
    node_patterns = {
        'navi_lidar': ['navi_lidar_driver', 'hesai', 'lidar'],
        'uli_lidar': ['uli', 'lidar'],
        'camera': ['galaxy_camera', 'camera'],
        'imu': ['sbg_device', 'imu'],
        'thruster': ['thruster_wifi_node', 'thruster'],
    }

    if sensor_name not in node_patterns:
        return None

    patterns = node_patterns[sensor_name]

    # Method 1: Use shell command directly (most reliable)
    try:
        import subprocess
        shell_result = subprocess.run(
            ['ros2', 'node', 'list'],
            capture_output=True,
            text=True,
            timeout=3,
            env={**os.environ, 'ROS_DOMAIN_ID': str(_get_domain_id())}
        )
        if shell_result.returncode == 0:
            nodes = [n.strip() for n in shell_result.stdout.strip().split('\n') if n.strip()]
            found = any(
                any(pattern in node.lower() for pattern in patterns)
                for node in nodes
            )
            if found:
                logger.debug(f"[{sensor_name}] Node found via shell: {patterns}")
            else:
                logger.debug(f"[{sensor_name}] No match. Nodes: {nodes[:3]}")
            return found
    except Exception as e:
        logger.debug(f"[{sensor_name}] Shell node check failed: {e}")

    # Method 2: Use ROS2Monitor._check_nodes() result
    try:
        from diagnostics import ROS2Monitor
        ros2_monitor = ROS2Monitor({
            'ROS2_CONFIG': ROS2_CONFIG,
            'EXPECTED_NODES': EXPECTED_NODES,
            'IGNORED_NODES': IGNORED_NODES,
        })
        check_result = ros2_monitor._check_nodes()
        nodes = check_result.get('metrics', {}).get('all', [])
        if nodes:
            for pattern in patterns:
                if any(pattern.lower() in node.lower() for node in nodes):
                    logger.debug(f"[{sensor_name}] Node found via ROS2Monitor: {pattern}")
                    return True
            logger.debug(f"[{sensor_name}] ROS2Monitor nodes but no match: {nodes[:3]}")
    except Exception as e:
        logger.debug(f"[{sensor_name}] ROS2Monitor check failed: {e}")

    # Method 3: Use rclpy helper from ROS2Monitor
    try:
        from diagnostics import ROS2Monitor
        ros2_monitor = ROS2Monitor({
            'ROS2_CONFIG': ROS2_CONFIG,
            'EXPECTED_NODES': EXPECTED_NODES,
            'IGNORED_NODES': IGNORED_NODES,
        })
        helper = ros2_monitor._get_helper()
        if helper and helper.is_ready():
            nodes = helper.get_node_names()
            if nodes:
                for pattern in patterns:
                    if any(pattern.lower() in node.lower() for node in nodes):
                        logger.debug(f"[{sensor_name}] Node found via rclpy helper: {pattern}")
                        return True
                logger.debug(f"[{sensor_name}] rclpy helper nodes: {nodes[:3]}")
    except Exception as e:
        logger.debug(f"[{sensor_name}] rclpy helper check failed: {e}")

    # Method 3: Fallback to shell command
    try:
        import subprocess
        shell_result = subprocess.run(
            ['ros2', 'node', 'list'],
            capture_output=True,
            text=True,
            timeout=2,
            env={**os.environ, 'ROS_DOMAIN_ID': str(_get_domain_id())}
        )
        if shell_result.returncode == 0:
            nodes = [n.strip() for n in shell_result.stdout.strip().split('\n') if n.strip()]
            found = any(
                any(pattern in node.lower() for pattern in patterns)
                for node in nodes
            )
            if found:
                logger.debug(f"[{sensor_name}] Node found via shell: {patterns}")
            return found
    except Exception as e:
        logger.debug(f"[{sensor_name}] Shell node check failed: {e}")

    return False


def _get_domain_id() -> int:
    """Get ROS2 domain ID from config."""
    return 42  # Default from config


def collect_sensor_status() -> Dict[str, Any]:
    """Collect status of all sensors (internal, non-cached)"""
    sensor_names = ['navi_lidar', 'uli_lidar', 'camera', 'imu', 'thruster', 'battery']
    sensors = {}

    for name in sensor_names:
        try:
            monitor = get_monitor(name)
            result = monitor.check()
            summary = monitor.get_diagnostic_summary()

            metrics = result.metrics or {}
            frequency = None
            packet_loss = None
            connected = '--'
            gps_fix = None
            satellites = None
            topic_available = None
            node_available = None

            if name in ['navi_lidar', 'uli_lidar']:
                log_data = metrics.get('log_data', {})
                freq_value = log_data.get('measured_frequency')
                if freq_value is not None:
                    frequency = f"{freq_value:.1f} Hz"
                network = metrics.get('network', {})
                connected = 'Connected' if network.get('reachable') else 'Disconnected'
            elif name == 'camera':
                log_data = metrics.get('log_data', {})
                fps_value = log_data.get('measured_frequency')
                if fps_value is not None:
                    frequency = f"{fps_value:.1f} fps"
                latency_value = log_data.get('avg_processing_ms')
                if latency_value is not None:
                    packet_loss = f"{latency_value:.1f} ms"
                network = metrics.get('network', {})
                connected = 'Connected' if network.get('reachable') else 'Disconnected'
            elif name == 'imu':
                log_data = metrics.get('log_data', {})
                freq_value = log_data.get('measured_frequency')
                if freq_value is not None:
                    frequency = f"{freq_value:.1f} Hz"
                gps = metrics.get('gps', {})
                gps_fix = gps.get('fix_status')
                satellites = gps.get('satellites')
                connected = 'Connected' if metrics.get('serial', {}).get('connected') else 'Disconnected'
            elif name == 'thruster':
                # Thruster uses UDP heartbeat, stored in 'network' metrics
                network = metrics.get('network', {})
                udp = metrics.get('udp', {})
                connected = 'Connected' if network.get('reachable', False) else 'Disconnected'
                latency = network.get('latency_ms', 0)
                packet_loss = network.get('packet_loss', 0)
            elif name == 'battery':
                # Battery uses ROS2 topic data
                topics = metrics.get('topics', {})
                voltages = topics.get('voltages', {})
                connected = 'Connected' if topics.get('data_available') else 'Disconnected'

            # Extract topic and node availability for frontend display
            topic_available = _get_topic_available(metrics, name)
            node_available = _get_node_available(name)

            # Calculate final status based on node/topic availability
            # Skip uli_lidar (no ROS driver)
            final_status = summary['status']
            final_color = summary['color']
            final_message = summary.get('message', '')

            if name != 'uli_lidar' and node_available is not None:
                if node_available and topic_available:
                    # Both node and topic available - status is OK
                    final_status = 'ok'
                    final_color = 'green'
                    # Update message to reflect full status
                    sensor_display_names = {
                        'navi_lidar': 'Navi LiDAR',
                        'uli_lidar': 'U-LiDAR',
                        'camera': 'Camera',
                        'imu': 'IMU',
                        'thruster': 'Arduino (Thruster)',
                        'battery': 'Battery',
                    }
                    display_name = sensor_display_names.get(name, name)
                    if 'connected' in summary['status']:
                        final_message = f"{display_name} - OK (node and topic active)"
                elif node_available and not topic_available:
                    # Node running but no topic data
                    final_status = 'connected'
                    final_color = 'blue'
                elif not node_available:
                    # Node not running - use original status
                    final_status = summary['status']
                    final_color = summary['color']

            sensors[name] = {
                'status': final_status,
                'color': final_color,
                'value': summary.get('value', 'N/A'),
                'message': final_message,
                'frequency': frequency,
                'packet_loss': packet_loss,
                'connected': connected,
                'gps_fix': gps_fix,
                'satellites': satellites,
                'topic_available': topic_available,
                'node_available': node_available,
                'voltages': summary.get('voltages', {}),
            }
        except Exception as e:
            logger.debug(f"Error collecting {name}: {e}")
            sensors[name] = {
                'status': 'unknown',
                'color': '#6b7280',
                'value': 'N/A',
                'message': str(e),
                'connected': '--',
                'topic_available': None,
                'node_available': None,
            }

    # Calculate overall status
    statuses = [s['status'] for s in sensors.values()]
    if 'critical' in statuses:
        overall = 'critical'
    elif 'warning' in statuses:
        overall = 'warning'
    elif 'unknown' in statuses:
        overall = 'unknown'
    else:
        overall = 'ok'

    ok_count = sum(1 for s in sensors.values() if s['status'] == 'ok')

    return {
        'sensors': sensors,
        'overall': overall,
        'summary': f"{ok_count}/{len(sensors)} OK",
    }


def collect_ros2_status() -> Dict[str, Any]:
    """Collect ROS2 system status"""
    try:
        monitor = get_monitor('ros2')
        result = monitor.check()

        nodes = result.metrics.get('nodes', {})
        topics = result.metrics.get('topics', {})

        return {
            'status': result.status.value,
            'message': result.message,
            'nodes': nodes.get('all', []),
            'nodes_running': nodes.get('running_count', 0),
            'nodes_expected_running': nodes.get('expected_running', []),
            'nodes_expected_missing': nodes.get('expected_missing', []),
            'topics': topics.get('all', []),
            'topics_count': topics.get('count', 0),
            'topics_important': topics.get('important', {}),
        }
    except Exception as e:
        logger.debug(f"Error collecting ROS2 status: {e}")
        return {
            'status': 'unknown',
            'message': str(e),
            'nodes': [],
            'nodes_running': 0,
            'topics': [],
            'topics_count': 0,
        }


def collect_ros2_control_status() -> Dict[str, Any]:
    """Collect ROS2 control status"""
    try:
        controller = get_ros2_controller()
        status = controller.check_running()
        return status
    except Exception as e:
        return {
            'running': False,
            'pid': None,
            'error': str(e)
        }


def collect_rosbag_status() -> Dict[str, Any]:
    """Collect rosbag recording status"""
    try:
        controller = get_rosbag_controller({
            'ROS2_CONFIG': ROS2_CONFIG,
            'ROSBAG_CONFIG': ROSBAG_CONFIG,
            'PROJECT_ROOT': PROJECT_ROOT,
        })
        status = controller.check_status()
        return status
    except Exception as e:
        return {
            'recording': False,
            'error': str(e)
        }


def collect_active_alerts() -> List[Dict]:
    """Collect active alerts"""
    try:
        store = get_alert_store()
        alerts = store.get_active_alerts(None)
        return [alert.__dict__ for alert in alerts]
    except Exception as e:
        logger.debug(f"Error collecting alerts: {e}")
        return []


# =============================================================================
# Background Broadcaster Task
# =============================================================================

# 频道配置（按更新频率分离）
CHANNEL_CONFIG = {
    Channel.SENSORS: {
        "interval": 1,        # 1 秒更新 (实时响应)
        "priority": "high",   # 高优先级
        "cache_ttl": 0.5,     # 使用 0.5 秒缓存 (最小化延迟)
    },
    Channel.ALERTS: {
        "interval": 0,        # 实时推送（由回调触发）
        "priority": "critical",
        "cache_ttl": 0,
    },
    Channel.ROS2: {
        "interval": 10,       # 10 秒更新
        "priority": "low",
        "cache_ttl": 5,
    },
    Channel.ROS2_CONTROL: {
        "interval": 5,
        "priority": "medium",
        "cache_ttl": 3,
    },
    Channel.ROSBAG: {
        "interval": 5,
        "priority": "medium",
        "cache_ttl": 2,
    },
}

async def background_broadcaster():
    """Async background task to broadcast updates to all WebSocket clients"""
    global _prev_state
    while True:
        try:
            # Collect state with parallel sensor checks for better performance
            new_state = await collect_all_state_async()

            # Calculate diff for incremental updates
            diff = calculate_state_diff(_prev_state, new_state)

            if diff:
                # Broadcast incremental update
                await manager.broadcast({
                    "type": "state_update",
                    "data": diff,
                    "timestamp": time.time()
                })

                # Update previous state
                with _state_lock:
                    _prev_state = new_state
            else:
                # No change, just update timestamp reference
                with _state_lock:
                    _prev_state = new_state

            logger.debug(f"Broadcasted state update to {manager.get_connection_count()} clients, diff keys: {list(diff.keys())}")

            await asyncio.sleep(5)
        except Exception as e:
            logger.error(f"Background broadcaster error: {e}")
            await asyncio.sleep(10)


async def background_broadcaster_channelized():
    """分频道的后台广播器 - 不同频道使用不同更新频率"""
    last_update = {channel: 0 for channel in Channel}

    while True:
        now = time.time()
        broadcast_tasks = []

        for channel, config in CHANNEL_CONFIG.items():
            interval = config["interval"]

            # 实时告警由回调处理，跳过
            if interval == 0:
                continue

            # 检查是否需要更新
            if now - last_update[channel] >= interval:
                # 根据频道收集数据
                try:
                    if channel == Channel.SENSORS:
                        data = await collect_sensor_status_parallel()
                    elif channel == Channel.ROS2:
                        data = collect_ros2_status_cached()
                    elif channel == Channel.ROS2_CONTROL:
                        data = collect_ros2_control_status()
                    elif channel == Channel.ROSBAG:
                        data = collect_rosbag_status()
                    else:
                        continue

                    broadcast_tasks.append(
                        manager.broadcast_to_channel(
                            channel,
                            {
                                "type": f"{channel.value}_update",
                                "data": data,
                                "timestamp": now
                            }
                        )
                    )
                    last_update[channel] = now
                except Exception as e:
                    logger.error(f"Error collecting {channel.value} data: {e}")

        # 并发广播
        if broadcast_tasks:
            await asyncio.gather(*broadcast_tasks, return_exceptions=True)

        await asyncio.sleep(1)  # 1 秒轮询


def background_collector_thread():
    """Background thread for data collection - uses parallel checks for better performance"""
    import time
    from concurrent.futures import ThreadPoolExecutor

    sensor_list = ['navi_lidar', 'uli_lidar', 'camera', 'imu', 'thruster']

    def check_single_sensor(sensor):
        """Check a single sensor, catching exceptions"""
        try:
            monitor = get_monitor(sensor)
            return monitor.check()
        except Exception as e:
            logger.debug(f"Background check error for {sensor}: {e}")
            return None

    while True:
        try:
            # Check sensors in parallel (max 3 workers to avoid overwhelming system)
            with ThreadPoolExecutor(max_workers=3) as executor:
                list(executor.map(check_single_sensor, sensor_list))
            time.sleep(5)
        except Exception as e:
            logger.error(f"Background collector error: {e}")
            time.sleep(10)


# =============================================================================
# FastAPI Lifespan
# =============================================================================

async def warm_cache_on_startup():
    """Warm up caches in background after startup to avoid blocking first connection"""
    logger.info("[CACHE] Starting cache warm-up...")
    start_time = time.time()

    try:
        # Warm sensor cache in parallel (non-blocking)
        sensors_data = await collect_sensor_status_parallel()
        logger.info(f"[CACHE] Sensor cache warmed in {time.time() - start_time:.2f}s")
    except Exception as e:
        logger.warning(f"[CACHE] Sensor cache warm-up failed: {e}")

    try:
        # Warm ROS2 status cache
        ros2_data = collect_ros2_status()
        logger.info(f"[CACHE] ROS2 cache warmed in {time.time() - start_time:.2f}s")
    except Exception as e:
        logger.warning(f"[CACHE] ROS2 cache warm-up failed: {e}")

    logger.info(f"[CACHE] Warm-up completed in {time.time() - start_time:.2f}s")


@asynccontextmanager
async def lifespan(app: FastAPI):
    """Manage application lifespan"""
    # Startup
    logger.info("Starting ROS2 System Diagnostic Server (FastAPI)...")
    logger.info(f"Project root: {PROJECT_ROOT}")
    logger.info(f"Access the web interface at: http://localhost:5000")
    logger.info(f"API docs at: http://localhost:5000/docs")

    # 启动后台初始化任务 (非阻塞，服务立即可用)
    asyncio.create_task(background_init())

    # Start background broadcaster (new channelized version)
    asyncio.create_task(background_broadcaster_channelized())

    # Start legacy collector thread
    collector_thread = Thread(target=background_collector_thread, daemon=True)
    collector_thread.start()

    yield

    # Shutdown
    logger.info("Shutting down...")

    # Stop ROS2 process if running
    try:
        if _ros2_controller is not None:
            status = _ros2_controller.check_running()
            if status.get('running'):
                logger.info("Stopping ROS2 process...")
                _ros2_controller.stop()
    except Exception as e:
        logger.warning(f"Error stopping ROS2: {e}")

    # Cancel all background tasks
    tasks = [t for t in asyncio.all_tasks() if t is not asyncio.current_task()]
    if tasks:
        logger.info(f"Cancelling {len(tasks)} background tasks...")
        for task in tasks:
            task.cancel()
        await asyncio.gather(*tasks, return_exceptions=True)

    logger.info("Shutdown complete")


# =============================================================================
# Background Initialization
# =============================================================================

async def background_init():
    """后台初始化任务 - 延迟执行非关键操作，让服务快速启动"""
    try:
        # 延迟初始化数据库和缓存，避免阻塞服务启动
        await asyncio.sleep(0.5)  # 让服务先完全启动

        # 1. 预热缓存
        await warm_cache_on_startup()

        # 2. 初始化告警存储和回调 (延迟到后台)
        from alerts import get_alert_store
        alert_store = get_alert_store()
        alert_store.set_alert_callback(broadcast_alert)
        logger.info("[WS] Alert callback registered (background)")

        # 2.5 初始化事件统计缓存回调
        _ensure_event_store_callback()

        # 3. 记录启动事件 (延迟到后台)
        if EVENT_LOG_CONFIG.get("enabled", True):
            event_store = get_event_store()
            event_store.log_event(EventLog(
                event_type='system_start',
                action='start',
                resource='diagnostic_system',
                message='ROS2 Diagnostic System started',
                created_at=datetime.now().isoformat(),
                success=True
            ))
            logger.info("[Event Log] System start event logged (background)")
    except Exception as e:
        logger.warning(f"[BG_INIT] Background init task failed: {e}")


# =============================================================================
# FastAPI App
# =============================================================================

app = FastAPI(
    title="ROS2 System Diagnostic",
    description="WebSocket-based real-time diagnostic system",
    version="2.0.0",
    lifespan=lifespan
)

# Mount static files and templates
app.mount("/static", StaticFiles(directory="static"), name="static")
templates = Jinja2Templates(directory="templates")


# =============================================================================
# Middleware
# =============================================================================

@app.middleware("http")
async def add_cache_control(request: Request, call_next):
    """Disable caching for JavaScript files in development"""
    response = await call_next(request)
    if '/static/js' in request.url.path or request.url.path.endswith('.js'):
        response.headers["Cache-Control"] = "no-store, no-cache, must-revalidate, max-age=0"
        response.headers["Pragma"] = "no-cache"
        response.headers["Expires"] = "0"
    return response


# =============================================================================
# Template Routes
# =============================================================================

@app.get("/")
async def index(request: Request):
    """Render dashboard page"""
    wireless_ip = get_wireless_ip_cached()
    return templates.TemplateResponse(
        "index.html",
        {
            "request": request,
            "page": "dashboard",
            "wireless_ip": wireless_ip,
            "refresh_interval": UI_CONFIG['refresh_interval']
        }
    )


@app.get("/sensors")
async def sensors(request: Request):
    """Render sensor details page"""
    return templates.TemplateResponse(
        "sensors.html",
        {
            "request": request,
            "page": "sensors",
            "refresh_interval": UI_CONFIG['refresh_interval']
        }
    )


@app.get("/tools")
async def tools(request: Request):
    """Render diagnostic tools page"""
    return templates.TemplateResponse(
        "tools.html",
        {
            "request": request,
            "page": "tools",
            "refresh_interval": UI_CONFIG['refresh_interval']
        }
    )


@app.get("/logs")
async def logs(request: Request):
    """Render system logs page"""
    return templates.TemplateResponse(
        "logs.html",
        {
            "request": request,
            "page": "logs",
            "log_root": LOG_ROOT,
            "project_root": PROJECT_ROOT,
            "refresh_interval": UI_CONFIG['refresh_interval']
        }
    )


@app.get("/events")
async def events(request: Request):
    """Render event log page"""
    return templates.TemplateResponse(
        "events.html",
        {
            "request": request,
            "page": "events",
            "refresh_interval": UI_CONFIG['refresh_interval']
        }
    )


# =============================================================================
# WebSocket Endpoint
# =============================================================================

@app.websocket("/ws")
async def websocket_endpoint(websocket: WebSocket):
    """WebSocket 端点 - 支持订阅/取消订阅"""
    await manager.connect(websocket)

    try:
        # Send initial full state（包含订阅确认）
        await manager.send_full_state(websocket)

        # 处理客户端消息
        while True:
            data = await websocket.receive_text()

            # 处理订阅请求
            if data == "ping":
                await websocket.send_text("pong")
            elif data.startswith("subscribe:"):
                channel_name = data.split(":", 1)[1]
                try:
                    channel = Channel(channel_name)
                    await manager.subscribe(websocket, channel)
                    await websocket.send_json({
                        "type": "subscribed",
                        "channel": channel_name,
                        "timestamp": time.time()
                    })
                except ValueError:
                    await websocket.send_json({
                        "type": "error",
                        "message": f"Unknown channel: {channel_name}",
                        "timestamp": time.time()
                    })
            elif data.startswith("unsubscribe:"):
                channel_name = data.split(":", 1)[1]
                try:
                    channel = Channel(channel_name)
                    await manager.unsubscribe(websocket, channel)
                    await websocket.send_json({
                        "type": "unsubscribed",
                        "channel": channel_name,
                        "timestamp": time.time()
                    })
                except ValueError:
                    pass  # 忽略无效频道
    except WebSocketDisconnect:
        manager.disconnect(websocket)
    except Exception as e:
        logger.error(f"WebSocket error: {e}")
        manager.disconnect(websocket)


# =============================================================================
# ROS2 Control API Routes (Kept for actions)
# =============================================================================

class StartStopResponse(BaseModel):
    success: bool
    message: str


@app.post("/api/ros2/control/start")
async def ros2_control_start() -> JSONResponse:
    """Start ROS2 sensor drivers"""
    event_store = get_event_store() if EVENT_LOG_CONFIG.get("enabled", True) else None
    try:
        controller = get_ros2_controller()
        result = controller.start()

        # Log event
        if event_store:
            event_store.log_event(EventLog(
                event_type='ros2_start',
                action='start',
                resource='ros2',
                message='ROS2 sensor drivers started',
                metadata=json.dumps({'pid': result.get('pid')}),
                created_at=datetime.now().isoformat(),
                success=result.get('success', False)
            ))

        return JSONResponse(content=result)
    except Exception as e:
        logger.error(f"Error starting ROS2: {e}")
        if event_store:
            event_store.log_event(EventLog(
                event_type='ros2_start',
                action='start',
                resource='ros2',
                message='ROS2 start failed',
                error=str(e),
                created_at=datetime.now().isoformat(),
                success=False
            ))
        return JSONResponse(
            content={"success": False, "message": f'Error starting ROS2: {str(e)}'},
            status_code=500
        )


@app.post("/api/ros2/control/stop")
async def ros2_control_stop() -> JSONResponse:
    """Stop ROS2 sensor drivers"""
    event_store = get_event_store() if EVENT_LOG_CONFIG.get("enabled", True) else None
    try:
        controller = get_ros2_controller()
        result = controller.stop()

        # Log event
        if event_store:
            event_store.log_event(EventLog(
                event_type='ros2_stop',
                action='stop',
                resource='ros2',
                message='ROS2 sensor drivers stopped',
                metadata=json.dumps({'killed_count': result.get('killed_count', 0)}),
                created_at=datetime.now().isoformat(),
                success=result.get('success', False)
            ))

        return JSONResponse(content=result)
    except Exception as e:
        logger.error(f"Error stopping ROS2: {e}")
        if event_store:
            event_store.log_event(EventLog(
                event_type='ros2_stop',
                action='stop',
                resource='ros2',
                message='ROS2 stop failed',
                error=str(e),
                created_at=datetime.now().isoformat(),
                success=False
            ))
        return JSONResponse(
            content={"success": False, "message": f'Error stopping ROS2: {str(e)}'},
            status_code=500
        )


@app.get("/api/ros2/control/logs")
async def ros2_control_logs(lines: int = 100) -> JSONResponse:
    """Get ROS2 runtime logs"""
    try:
        controller = get_ros2_controller()
        logs = controller.get_logs(lines)
        return JSONResponse(content={"success": True, "logs": logs})
    except Exception as e:
        logger.error(f"Error getting ROS2 logs: {e}")
        return JSONResponse(
            content={"success": False, "error": str(e)},
            status_code=500
        )


# =============================================================================
# Rosbag Recording API Routes (Kept for actions)
# =============================================================================

@app.post("/api/rosbag/start")
async def rosbag_start(request: Request) -> JSONResponse:
    """Start rosbag recording"""
    event_store = get_event_store() if EVENT_LOG_CONFIG.get("enabled", True) else None
    try:
        data = await request.json() if request.headers.get("content-type") == "application/json" else {}
        topics = data.get('topics')  # Optional topic override

        controller = get_rosbag_controller({
            'ROS2_CONFIG': ROS2_CONFIG,
            'ROSBAG_CONFIG': ROSBAG_CONFIG,
            'PROJECT_ROOT': PROJECT_ROOT,
        })
        result = controller.start_recording(topics)

        # Log event
        if event_store:
            bag_name = result.get('bag_name', 'unknown')
            event_store.log_event(EventLog(
                event_type='rosbag_start',
                action='start',
                resource='rosbag',
                message=f'Rosbag recording started: {bag_name}',
                metadata=json.dumps({'bag_name': bag_name, 'topics': topics}),
                created_at=datetime.now().isoformat(),
                success=result.get('success', False)
            ))

        return JSONResponse(content=result)
    except Exception as e:
        logger.error(f"Error starting rosbag recording: {e}")
        if event_store:
            event_store.log_event(EventLog(
                event_type='rosbag_start',
                action='start',
                resource='rosbag',
                message='Rosbag start failed',
                error=str(e),
                created_at=datetime.now().isoformat(),
                success=False
            ))
        return JSONResponse(
            content={"success": False, "message": f'Error starting recording: {str(e)}'},
            status_code=500
        )


@app.post("/api/rosbag/stop")
async def rosbag_stop() -> JSONResponse:
    """Stop rosbag recording"""
    event_store = get_event_store() if EVENT_LOG_CONFIG.get("enabled", True) else None
    try:
        controller = get_rosbag_controller({
            'ROS2_CONFIG': ROS2_CONFIG,
            'ROSBAG_CONFIG': ROSBAG_CONFIG,
            'PROJECT_ROOT': PROJECT_ROOT,
        })
        result = controller.stop_recording()

        # Log event
        if event_store:
            bag_name = result.get('bag_name', 'unknown')
            duration = result.get('duration', 0)
            event_store.log_event(EventLog(
                event_type='rosbag_stop',
                action='stop',
                resource='rosbag',
                message=f'Rosbag recording stopped: {bag_name}',
                metadata=json.dumps({'bag_name': bag_name, 'duration_sec': duration}),
                created_at=datetime.now().isoformat(),
                success=result.get('success', False)
            ))

        return JSONResponse(content=result)
    except Exception as e:
        logger.error(f"Error stopping rosbag recording: {e}")
        if event_store:
            event_store.log_event(EventLog(
                event_type='rosbag_stop',
                action='stop',
                resource='rosbag',
                message='Rosbag stop failed',
                error=str(e),
                created_at=datetime.now().isoformat(),
                success=False
            ))
        return JSONResponse(
            content={"success": False, "message": f'Error stopping recording: {str(e)}'},
            status_code=500
        )


# =============================================================================
# Log API Routes (Kept)
# =============================================================================

@app.get("/api/logs")
async def get_logs(log_type: str = "diagnostic", lines: int = 100) -> JSONResponse:
    """Get log file contents for log viewer"""
    log_paths = {
        'diagnostic': LOG_FILES.get('diagnostic'),
        'ros': LOG_FILES.get('ros2_control'),
        'ros2': LOG_FILES.get('ros2_control'),
    }

    log_path = log_paths.get(log_type)
    if not log_path:
        return JSONResponse(
            content={"success": False, "error": f'Unknown log type: {log_type}'},
            status_code=400
        )

    try:
        if os.path.exists(log_path):
            with open(log_path, 'r') as f:
                all_lines = f.readlines()
                logs = all_lines[-lines:] if len(all_lines) > lines else all_lines
                logs = [line.rstrip('\n') for line in logs]
            return JSONResponse(content={
                "success": True,
                "logs": logs,
                "path": log_path,
                "total_lines": len(all_lines)
            })
        else:
            return JSONResponse(
                content={"success": False, "error": f'Log file not found: {log_path}'},
                status_code=404
            )
    except Exception as e:
        logger.error(f"Error reading log file {log_path}: {e}")
        return JSONResponse(
            content={"success": False, "error": str(e)},
            status_code=500
        )


@app.get("/api/logs/sessions")
async def get_log_sessions() -> JSONResponse:
    """Get all ROS2 log sessions"""
    try:
        log_base = LOG_ROOT
        sessions = []

        if not os.path.exists(log_base):
            return JSONResponse(content={"success": True, "sessions": []})

        for d in sorted(os.listdir(log_base), reverse=True):
            session_path = os.path.join(log_base, d)
            if os.path.isdir(session_path) and d.startswith('20'):
                try:
                    year = d[0:4]
                    month = d[4:6]
                    day = d[6:8]
                    hour = d[9:11]
                    minute = d[11:13]
                    name = f"{month}/{day} {hour}:{minute}"

                    sessions.append({
                        'id': d,
                        'name': name,
                        'path': session_path
                    })
                except ValueError:
                    continue

        return JSONResponse(content={"success": True, "sessions": sessions})
    except Exception as e:
        logger.error(f"Error getting log sessions: {e}")
        return JSONResponse(content={"success": False, "error": str(e)}, status_code=500)


@app.get("/api/logs/session/{session_id}/files")
async def get_session_files(session_id: str) -> JSONResponse:
    """Get log files in a specific session"""
    try:
        log_base = LOG_ROOT
        session_path = os.path.join(log_base, session_id)

        if not os.path.exists(session_path) or not os.path.isdir(session_path):
            return JSONResponse(
                content={"success": False, "error": f'Session not found: {session_id}'},
                status_code=404
            )

        files = []
        for root, _, filenames in os.walk(session_path):
            for fname in filenames:
                if not fname.endswith('.log'):
                    continue
                file_path = os.path.join(root, fname)
                if not os.path.isfile(file_path):
                    continue
                size = os.path.getsize(file_path)
                rel_path = os.path.relpath(file_path, session_path)
                label = rel_path.replace('.log', '').replace('_', ' ').replace('/', ' / ').title()

                files.append({
                    'name': rel_path,
                    'label': label,
                    'size': size
                })

        files.sort(key=lambda f: f['name'])

        return JSONResponse(content={"success": True, "files": files})
    except Exception as e:
        logger.error(f"Error getting session files: {e}")
        return JSONResponse(content={"success": False, "error": str(e)}, status_code=500)


@app.get("/api/logs/read")
async def read_log_file(
    category: str = "application",
    session: str = "",
    file: str = "",
    lines: int = 100
) -> JSONResponse:
    """Read log file content"""
    try:
        log_path, error = _resolve_log_path(category, session, file)
        if error:
            payload, code = error
            return JSONResponse(content=payload, status_code=code)

        if not log_path or not os.path.exists(log_path):
            return JSONResponse(
                content={"success": False, "error": f'Log file not found: {log_path}'},
                status_code=404
            )

        with open(log_path, 'r', encoding='utf-8', errors='replace') as f:
            all_lines = f.readlines()
            logs = all_lines[-lines:] if len(all_lines) > lines else all_lines
            logs = [line.rstrip('\n\r') for line in logs]

        return JSONResponse(content={
            "success": True,
            "logs": logs,
            "path": log_path,
            "total_lines": len(all_lines),
            "category": category,
            "session": session,
            "file": file
        })
    except Exception as e:
        logger.error(f"Error reading log file: {e}")
        return JSONResponse(content={"success": False, "error": str(e)}, status_code=500)


@app.get("/api/logs/stream")
async def stream_log_file(
    category: str = "application",
    session: str = "",
    file: str = "",
    interval: float = 1.0
):
    """Stream log file content using Server-Sent Events (SSE)"""
    log_path, error = _resolve_log_path(category, session, file)
    if error:
        payload, code = error
        return JSONResponse(content=payload, status_code=code)
    if not log_path or not os.path.exists(log_path):
        return JSONResponse(
            content={"success": False, "error": f'Log file not found: {log_path}'},
            status_code=404
        )

    async def generate():
        last_size = 0
        while True:
            try:
                if not os.path.exists(log_path):
                    yield f"data: {json.dumps({'lines': [], 'eof': True, 'error': 'Log file missing'})}\n\n"
                    break
                current_size = os.path.getsize(log_path)
                if current_size < last_size:
                    last_size = 0
                if current_size > last_size:
                    with open(log_path, 'r', encoding='utf-8', errors='replace') as f:
                        f.seek(last_size)
                        chunk = f.read()
                    last_size = current_size
                    lines = [line.rstrip('\\n\\r') for line in chunk.splitlines()]
                    if lines:
                        yield f"data: {json.dumps({'lines': lines})}\n\n"
                await asyncio.sleep(interval)
            except Exception as exc:
                yield f"data: {json.dumps({'lines': [], 'error': str(exc)})}\n\n"
                await asyncio.sleep(interval)

    return StreamingResponse(generate(), media_type="text/event-stream", headers={
        "Cache-Control": "no-cache",
        "Connection": "keep-alive",
    })


# =============================================================================
# Alert API Routes (Kept for actions)
# =============================================================================

@app.post("/api/alerts/{alert_id}/resolve")
async def resolve_alert(alert_id: int) -> JSONResponse:
    """Mark an alert as resolved"""
    event_store = get_event_store() if EVENT_LOG_CONFIG.get("enabled", True) else None
    try:
        store = get_alert_store()
        success = store.resolve_alert(alert_id)

        # Log event
        if event_store:
            event_store.log_event(EventLog(
                event_type='alert_resolved',
                action='resolve',
                resource=f'alert_{alert_id}',
                message=f'Alert {alert_id} marked as resolved',
                metadata=json.dumps({'alert_id': alert_id}),
                created_at=datetime.now().isoformat(),
                success=success
            ))

        return JSONResponse(content={
            "success": success,
            "message": 'Alert resolved' if success else 'Alert not found'
        })
    except Exception as e:
        logger.error(f"Error resolving alert {alert_id}: {e}")
        return JSONResponse(content={"success": False, "error": str(e)}, status_code=500)


@app.post("/api/alerts/{alert_id}/ignore")
async def ignore_alert(alert_id: int) -> JSONResponse:
    """Mark an alert as ignored"""
    event_store = get_event_store() if EVENT_LOG_CONFIG.get("enabled", True) else None
    try:
        store = get_alert_store()
        success = store.ignore_alert(alert_id)

        # Log event
        if event_store:
            event_store.log_event(EventLog(
                event_type='alert_ignored',
                action='ignore',
                resource=f'alert_{alert_id}',
                message=f'Alert {alert_id} marked as ignored',
                metadata=json.dumps({'alert_id': alert_id}),
                created_at=datetime.now().isoformat(),
                success=success
            ))

        return JSONResponse(content={
            "success": success,
            "message": 'Alert ignored' if success else 'Alert not found'
        })
    except Exception as e:
        logger.error(f"Error ignoring alert {alert_id}: {e}")
        return JSONResponse(content={"success": False, "error": str(e)}, status_code=500)


@app.get("/api/alerts/stats")
async def get_alert_stats() -> JSONResponse:
    """Get alert statistics"""
    try:
        store = get_alert_store()
        stats = store.get_alert_stats()
        return JSONResponse(content={"success": True, "data": stats})
    except Exception as e:
        logger.error(f"Error getting alert stats: {e}")
        return JSONResponse(content={"success": False, "error": str(e)}, status_code=500)


@app.get("/api/alerts/sensor/{sensor}")
async def get_alerts_by_sensor(sensor: str, limit: int = 50) -> JSONResponse:
    """Get alerts for a specific sensor"""
    try:
        store = get_alert_store()
        alerts = store.get_alerts_by_sensor(sensor, limit)
        return JSONResponse(content={"success": True, "data": [alert.__dict__ for alert in alerts]})
    except Exception as e:
        logger.error(f"Error getting alerts for sensor {sensor}: {e}")
        return JSONResponse(content={"success": False, "error": str(e)}, status_code=500)


@app.get("/api/alerts/severity/{severity}")
async def get_alerts_by_severity(severity: str, limit: int = 50) -> JSONResponse:
    """Get alerts by severity level"""
    if severity not in ['critical', 'warning']:
        return JSONResponse(
            content={"success": False, "error": 'Invalid severity. Must be "critical" or "warning"'},
            status_code=400
        )

    try:
        store = get_alert_store()
        alerts = store.get_alerts_by_severity(severity, limit)
        return JSONResponse(content={"success": True, "data": [alert.__dict__ for alert in alerts]})
    except Exception as e:
        logger.error(f"Error getting alerts for severity {severity}: {e}")
        return JSONResponse(content={"success": False, "error": str(e)}, status_code=500)


# =============================================================================
# Event Log API Routes (Audit Trail)
# =============================================================================

@app.get("/api/events/logs")
async def get_event_logs(
    limit: int = 100,
    offset: int = 0,
    event_type: str = None,
    action: str = None,
    resource: str = None,
    start_date: str = None,
    end_date: str = None
) -> JSONResponse:
    """Get event log with optional filtering

    Query parameters:
        limit: Maximum number of events to return (default: 100)
        offset: Pagination offset (default: 0)
        event_type: Filter by event type
        action: Filter by action
        resource: Filter by resource
        start_date: Filter events after this ISO date
        end_date: Filter events before this ISO date
    """
    if not EVENT_LOG_CONFIG.get("enabled", True):
        return JSONResponse(
            content={"success": False, "error": "Event logging is disabled"},
            status_code=503
        )

    try:
        event_store = get_event_store()
        events = event_store.get_events(
            limit=limit,
            offset=offset,
            event_type=event_type,
            action=action,
            resource=resource,
            start_date=start_date,
            end_date=end_date
        )

        # Get total count for pagination
        all_events = event_store.get_events(limit=10000, offset=0, event_type=event_type, action=action, resource=resource, start_date=start_date, end_date=end_date)

        return JSONResponse(content={
            "success": True,
            "data": [event.__dict__ for event in events],
            "total": len(all_events),
            "limit": limit,
            "offset": offset
        })
    except Exception as e:
        logger.error(f"Error getting event logs: {e}")
        return JSONResponse(content={"success": False, "error": str(e)}, status_code=500)


@app.get("/api/events/stats")
async def get_event_stats() -> JSONResponse:
    """Get event statistics (with 60s cache)"""
    if not EVENT_LOG_CONFIG.get("enabled", True):
        return JSONResponse(
            content={"success": False, "error": "Event logging is disabled"},
            status_code=503
        )

    try:
        # Check cache first
        with _event_stats_lock:
            cached = _event_stats_cache.get("value")
            cache_time = _event_stats_cache.get("time", 0)
            if cached and (time.time() - cache_time) < _EVENT_STATS_TTL:
                return JSONResponse(content={"success": True, "data": cached})

        # Cache miss or expired, fetch fresh data
        event_store = get_event_store()
        stats = event_store.get_event_stats()

        # Update cache
        with _event_stats_lock:
            _event_stats_cache["value"] = stats
            _event_stats_cache["time"] = time.time()

        return JSONResponse(content={"success": True, "data": stats})
    except Exception as e:
        logger.error(f"Error getting event stats: {e}")
        return JSONResponse(content={"success": False, "error": str(e)}, status_code=500)


@app.get("/api/events/types")
async def get_event_types() -> JSONResponse:
    """Get all available event types"""
    event_types = [
        {'type': 'system_start', 'description': 'System startup'},
        {'type': 'ros2_start', 'description': 'ROS2 system started'},
        {'type': 'ros2_stop', 'description': 'ROS2 system stopped'},
        {'type': 'rosbag_start', 'description': 'Rosbag recording started'},
        {'type': 'rosbag_stop', 'description': 'Rosbag recording stopped'},
        {'type': 'alert_resolved', 'description': 'Alert marked as resolved'},
        {'type': 'alert_ignored', 'description': 'Alert marked as ignored'},
        {'type': 'user_action', 'description': 'User action'},
    ]
    return JSONResponse(content={"success": True, "data": event_types})


@app.get("/api/events/export")
async def export_event_logs(
    format: str = "csv",
    start_date: str = None,
    end_date: str = None
) -> StreamingResponse:
    """Export event logs to CSV or JSON

    Query parameters:
        format: Export format (csv or json)
        start_date: Optional start date filter (ISO 8601)
        end_date: Optional end date filter (ISO 8601)
    """
    if not EVENT_LOG_CONFIG.get("enabled", True):
        return JSONResponse(
            content={"success": False, "error": "Event logging is disabled"},
            status_code=503
        )

    try:
        event_store = get_event_store()

        if format == "csv":
            csv_data = event_store.export_to_csv(start_date=start_date, end_date=end_date)
            return StreamingResponse(
                io.StringIO(csv_data),
                media_type="text/csv",
                headers={
                    "Content-Disposition": f"attachment; filename=events_{datetime.now().strftime('%Y%m%d_%H%M%S')}.csv"
                }
            )
        elif format == "json":
            events = event_store.get_events(
                limit=10000,
                start_date=start_date,
                end_date=end_date
            )
            json_data = json.dumps([event.__dict__ for event in events], indent=2)
            return StreamingResponse(
                io.StringIO(json_data),
                media_type="application/json",
                headers={
                    "Content-Disposition": f"attachment; filename=events_{datetime.now().strftime('%Y%m%d_%H%M%S')}.json"
                }
            )
        else:
            return JSONResponse(
                content={"success": False, "error": "Invalid format. Use 'csv' or 'json'"},
                status_code=400
            )
    except Exception as e:
        logger.error(f"Error exporting event logs: {e}")
        return JSONResponse(content={"success": False, "error": str(e)}, status_code=500)


# =============================================================================
# Tools API Routes (Kept for actions)
# =============================================================================

class PingRequest(BaseModel):
    host: str
    count: int = 4
    timeout: int = 2


@app.post("/api/tools/ping")
async def tool_ping(req: PingRequest) -> JSONResponse:
    """Ping test tool"""
    try:
        from diagnostics.utils import ping_host
        result = ping_host(req.host, timeout=req.timeout, count=req.count)
        return JSONResponse(content={"success": True, "result": result})
    except Exception as e:
        logger.error(f"Error in ping tool: {e}")
        return JSONResponse(content={"success": False, "error": str(e)}, status_code=500)


class ConfigValidateRequest(BaseModel):
    type: str = "all"


@app.post("/api/tools/config-validate")
async def tool_config_validate(req: ConfigValidateRequest) -> JSONResponse:
    """Validate YAML configuration files"""
    try:
        results = {}
        config_files = TOOLS_CONFIG_FILES

        files_to_check = config_files if req.type == 'all' else {req.type: config_files.get(req.type)}

        for name, path in files_to_check.items():
            if path and os.path.exists(path):
                try:
                    with open(path, 'r') as f:
                        import yaml
                        yaml.safe_load(f)
                    results[name] = {'valid': True, 'path': path}
                except Exception as e:
                    results[name] = {'valid': False, 'path': path, 'error': str(e)}
            else:
                results[name] = {'valid': False, 'path': path, 'error': 'File not found'}

        return JSONResponse(content={"success": True, "results": results})
    except Exception as e:
        logger.error(f"Error in config validation: {e}")
        return JSONResponse(content={"success": False, "error": str(e)}, status_code=500)


# =============================================================================
# Legacy/Compatibility Routes
# =============================================================================

@app.get("/api/status")
async def legacy_get_status() -> JSONResponse:
    """Legacy status endpoint for compatibility"""
    try:
        monitor = get_monitor('ros2')
        result = monitor.check()

        running = result.status.value in ['ok', 'warning']
        pid = None

        # Always check process cache (helps warm up the cache)
        processes = get_ros2_processes_cached()
        if running and processes:
            pid = processes[0]['pid']

        return JSONResponse(content={
            'running': running,
            'pid': pid,
            'message': result.message,
        })
    except Exception as e:
        return JSONResponse(content={
            'running': False,
            'pid': None,
            'message': f"Error: {str(e)}"
        })


@app.get("/api/cache/stats")
async def get_cache_stats() -> JSONResponse:
    """Get cache hit/miss statistics for monitoring"""
    with _cache_stats_lock:
        hits = _cache_stats["hits"]
        misses = _cache_stats["misses"]
        total = hits + misses
        hit_rate = (hits / total * 100) if total > 0 else 0

    with _cache_lock:
        cache_size = len(_cache)

    return JSONResponse(content={
        "success": True,
        "stats": {
            "hits": hits,
            "misses": misses,
            "total_requests": total,
            "hit_rate": f"{hit_rate:.1f}%",
            "cache_entries": cache_size
        }
    })


@app.post("/api/cache/invalidate")
async def invalidate_cache(pattern: str = "") -> JSONResponse:
    """Invalidate cache entries matching a pattern prefix."""
    try:
        if pattern:
            count = invalidate_cache_pattern(pattern)
            return JSONResponse(content={
                "success": True,
                "message": f"Cleared {count} cache entries matching '{pattern}'"
            })
        else:
            with _cache_lock:
                _cache.clear()
            with _cache_stats_lock:
                _cache_stats = {"hits": 0, "misses": 0}
            return JSONResponse(content={
                "success": True,
                "message": "Cleared all cache entries"
            })
    except Exception as e:
        return JSONResponse(content={
            "success": False,
            "error": str(e)
        }, status_code=500)


@app.get("/api/sensors/status")
async def get_sensors_status() -> JSONResponse:
    """Get current sensor status for manual refresh"""
    try:
        data = collect_sensor_status()
        return JSONResponse(content={"success": True, "data": data})
    except Exception as e:
        logger.error(f"Error getting sensor status: {e}")
        return JSONResponse(content={"success": False, "error": str(e)}, status_code=500)


# =============================================================================
# One-time state endpoints (for initial load or manual refresh)
# ============================================================================= (for initial load or manual refresh)
# =============================================================================

@app.get("/api/ros2/topic/info")
async def get_ros2_topic_info(topic: str) -> JSONResponse:
    """Get detailed info about a specific topic"""
    if not topic:
        return JSONResponse(
            content={"success": False, "error": 'Topic parameter required'},
            status_code=400
        )

    try:
        monitor = get_monitor('ros2')
        info = monitor._get_topic_info(topic)

        if info:
            return JSONResponse(content={"success": True, "topic": info})
        else:
            return JSONResponse(
                content={"success": False, "error": 'Topic not found or error getting info'}
            )
    except Exception as e:
        logger.error(f"Error getting topic info: {e}")
        cached = _cache_get(f'ros2_topic:{topic}', CACHE_TTL.get('topics', 5))
        if cached:
            cached = dict(cached)
            cached['stale'] = True
            cached['error'] = str(e)
            return JSONResponse(content=cached)
        return JSONResponse(content={"success": False, "error": str(e)}, status_code=500)


# =============================================================================
# Main Entry Point
# =============================================================================

if __name__ == '__main__':
    # Create necessary directories using absolute paths
    # This ensures paths resolve correctly regardless of where the script is executed from
    _script_dir = os.path.dirname(os.path.abspath(__file__))

    os.makedirs(os.path.join(_script_dir, 'logs'), exist_ok=True)
    os.makedirs(os.path.join(_script_dir, 'static', 'css'), exist_ok=True)
    os.makedirs(os.path.join(_script_dir, 'static', 'js'), exist_ok=True)
    os.makedirs(os.path.join(_script_dir, 'templates'), exist_ok=True)

    # Change to script directory to ensure module resolution works correctly
    # This is necessary for uvicorn reload mode with string module reference
    _original_dir = os.getcwd()
    try:
        os.chdir(_script_dir)
        uvicorn.run(
            "main:app",
            host="0.0.0.0",
            port=5000,
            reload=True,
            log_level="info"
        )
    finally:
        os.chdir(_original_dir)
