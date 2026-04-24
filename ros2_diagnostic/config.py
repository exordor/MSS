#!/usr/bin/env python3
"""
ROS2 System Diagnostic Configuration
Loads settings from YAML with safe defaults.
"""

import os
from copy import deepcopy

import yaml


def _load_yaml(path: str) -> dict:
    if not path or not os.path.exists(path):
        return {}
    with open(path, "r", encoding="utf-8") as f:
        data = yaml.safe_load(f)
    return data or {}


def _deep_merge(dst: dict, src: dict) -> dict:
    for key, value in src.items():
        if isinstance(value, dict) and isinstance(dst.get(key), dict):
            _deep_merge(dst[key], value)
        else:
            dst[key] = value
    return dst


DEFAULT_CONFIG_PATH = os.path.join(os.path.dirname(__file__), "config.yaml")
CONFIG_PATH = os.environ.get("ROS2_DIAGNOSTIC_CONFIG", DEFAULT_CONFIG_PATH)

base_cfg = _load_yaml(DEFAULT_CONFIG_PATH)
cfg = deepcopy(base_cfg)

if CONFIG_PATH != DEFAULT_CONFIG_PATH:
    override_cfg = _load_yaml(CONFIG_PATH)
    _deep_merge(cfg, override_cfg)


PROJECT_ROOT = cfg.get("project_root") or os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def _resolve(path: str) -> str:
    if not path:
        return path
    if os.path.isabs(path):
        return path
    return os.path.normpath(os.path.join(PROJECT_ROOT, path))


logs_cfg = cfg.get("logs", {})
LOG_ROOT = _resolve(logs_cfg.get("base_dir", "logs"))
rotation_cfg = logs_cfg.get("rotation", {})

LOG_FILES = {
    "diagnostic": _resolve(logs_cfg.get("diagnostic_log", "ros2_diagnostic/logs/diagnostic.log")),
    "ros2_control": _resolve(logs_cfg.get("ros2_control_log", "ros2_diagnostic/logs/ros2.log")),
    "ros": _resolve(logs_cfg.get("ros_log_hint", "scripts/ros2/web_controller/test.log")),
}

LOG_ROTATION = {
    "enabled": bool(rotation_cfg.get("enabled", True)),
    "max_mb": float(rotation_cfg.get("max_mb", 20)),
    "backup_count": int(rotation_cfg.get("backup_count", 10)),
    "compress": bool(rotation_cfg.get("compress", True)),
    "encoding": rotation_cfg.get("encoding", "utf-8"),
}


ros2_cfg = cfg.get("ros2", {})
ROS2_CONFIG = {
    "domain_id": ros2_cfg.get("domain_id", 42),
    "source_cmd": ros2_cfg.get("source_cmd", "/opt/ros/humble/setup.bash"),
    "workspace": _resolve(ros2_cfg.get("workspace", "ros2_ws")),
    "launch_script": _resolve(ros2_cfg.get("launch_script", "scripts/ros2/run_ros2_all.sh")),
}

ros2_control_cfg = cfg.get("ros2_control", {})
ROS2_CONTROL = {
    "script_path": _resolve(ros2_control_cfg.get("script", "scripts/ros2/run_ros2_all.sh")),
    "repo_root": _resolve(ros2_control_cfg.get("repo_root", PROJECT_ROOT)),
    "log_file": LOG_FILES.get("ros2_control"),
    "domain_id": str(ros2_cfg.get("domain_id", 42)),
}

rosbag_cfg = cfg.get("rosbag", {})
ROSBAG_CONFIG = {
    "config_path": _resolve(rosbag_cfg.get("config_path", "config/rosbag/rosbag_ros2.yaml")),
    "output_folder": _resolve(rosbag_cfg.get("output_folder", "rosbags")),
    "start_service": rosbag_cfg.get("start_service", "start_recording"),
    "stop_service": rosbag_cfg.get("stop_service", "stop_recording"),
    "service_timeout_sec": float(rosbag_cfg.get("service_timeout_sec", 15.0)),
}


sensors_cfg = cfg.get("sensors", {})
SENSOR_IPS = sensors_cfg.get("ips", {})
SENSOR_THRESHOLDS = sensors_cfg.get("thresholds", {})
ROS2_TOPICS = sensors_cfg.get("topics", {})
SENSOR_I2C = sensors_cfg.get("i2c", {})

nodes_cfg = cfg.get("ros2_nodes", {})
EXPECTED_NODES = nodes_cfg.get("expected", [])
IGNORED_NODES = nodes_cfg.get("ignored", [])
SENSOR_NODES = nodes_cfg.get("sensor_nodes", {})

SENSOR_CONNECTION_TYPES = cfg.get("sensor_connections", {})

mqtt_cfg = cfg.get("mqtt", {})
MQTT_CONFIG = {
    "enabled": bool(mqtt_cfg.get("enabled", False)),
    "broker_host": mqtt_cfg.get("broker_host", "192.168.50.200"),
    "broker_port": int(mqtt_cfg.get("broker_port", 1883)),
    "client_id": mqtt_cfg.get("client_id", "ros2_diagnostic"),
    "data_timeout": float(mqtt_cfg.get("data_timeout", 10.0)),
    "arduino_topics": mqtt_cfg.get("arduino_topics", {}),
    "pi5_topics": mqtt_cfg.get("pi5_topics", {}),
}

monitor_cfg = cfg.get("monitoring", {})
ENABLE_TOPIC_DETAILS = bool(monitor_cfg.get("enable_topic_details", False))
CACHE_TTL = monitor_cfg.get("cache_ttl", {})

CHART_HISTORY = cfg.get("charts", {})
UI_CONFIG = cfg.get("ui", {})


websocket_cfg = cfg.get("websocket", {})
websocket_channels_cfg = websocket_cfg.get("channels", {})


def _websocket_channel_config(
    name: str,
    interval_sec: float,
    cache_ttl_sec: float,
    enabled: bool = True,
) -> dict:
    channel_cfg = websocket_channels_cfg.get(name, {})
    return {
        "enabled": bool(channel_cfg.get("enabled", enabled)),
        "interval_sec": float(channel_cfg.get("interval_sec", interval_sec)),
        "cache_ttl_sec": float(channel_cfg.get("cache_ttl_sec", cache_ttl_sec)),
    }


legacy_state_cfg = websocket_cfg.get("legacy_state_update", {})
WEBSOCKET_CONFIG = {
    "max_connections": int(websocket_cfg.get("max_connections", 10)),
    "client_ping_interval_sec": float(
        websocket_cfg.get(
            "client_ping_interval_sec",
            websocket_cfg.get("ping_interval", 30),
        )
    ),
    "ping_timeout_sec": float(
        websocket_cfg.get(
            "ping_timeout_sec",
            websocket_cfg.get("ping_timeout", 10),
        )
    ),
    "default_channels": list(websocket_cfg.get("default_channels", [
        "sensors",
        "connectivity",
        "alerts",
        "ros2",
        "ros2_control",
        "rosbag",
        "time",
    ])),
    "legacy_state_update": {
        "enabled": bool(legacy_state_cfg.get("enabled", True)),
        "interval_sec": float(
            legacy_state_cfg.get(
                "interval_sec",
                websocket_cfg.get("broadcast_interval", 5),
            )
        ),
    },
    "channels": {
        "sensors": _websocket_channel_config("sensors", 2.0, 0.5),
        "connectivity": _websocket_channel_config("connectivity", 0.5, 0.0),
        "alerts": _websocket_channel_config("alerts", 0.0, 0.0),
        "ros2": _websocket_channel_config("ros2", 10.0, 5.0),
        "ros2_control": _websocket_channel_config("ros2_control", 1.0, 3.0),
        "rosbag": _websocket_channel_config("rosbag", 5.0, 2.0),
        "time": _websocket_channel_config("time", 1.0, 1.0),
    },
}

tools_cfg = cfg.get("tools", {})
TOOLS_CONFIG_FILES = {
    key: _resolve(value) for key, value in tools_cfg.get("config_files", {}).items()
}
TOOLS_SCRIPTS = {
    "ptp_status": _resolve(tools_cfg.get("ptp_status_script", "scripts/ptp_status.sh")),
    "ptp_sync_verify": _resolve(tools_cfg.get("ptp_sync_verify_script", "scripts/ptp_sync_verify.sh")),
}

# Time synchronization / PHC configuration
time_cfg = cfg.get("time", {})
TIME_CONFIG = {
    "phc_device": _resolve(time_cfg.get("phc_device", "/dev/ptp0")),
    "phc_timeout": float(time_cfg.get("phc_timeout", 1.0)),
    "phc_ctl_path": _resolve(time_cfg.get("phc_ctl_path", "")),
}


# Event log configuration
event_cfg = cfg.get("event_log", {})
EVENT_LOG_CONFIG = {
    "enabled": bool(event_cfg.get("enabled", True)),
    "db_path": _resolve(event_cfg.get("db_path", "ros2_diagnostic/logs/events.db")),
    "retention_days": event_cfg.get("retention_days", None),  # None = permanent retention
}
