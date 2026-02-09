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

LOG_FILES = {
    "diagnostic": _resolve(logs_cfg.get("diagnostic_log", "ros2_diagnostic/logs/diagnostic.log")),
    "ros2_control": _resolve(logs_cfg.get("ros2_control_log", "ros2_diagnostic/logs/ros2.log")),
    "ros": _resolve(logs_cfg.get("ros_log_hint", "scripts/ros2/web_controller/test.log")),
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

monitor_cfg = cfg.get("monitoring", {})
ENABLE_TOPIC_DETAILS = bool(monitor_cfg.get("enable_topic_details", False))
CACHE_TTL = monitor_cfg.get("cache_ttl", {})

CHART_HISTORY = cfg.get("charts", {})
UI_CONFIG = cfg.get("ui", {})

TOOLS_CONFIG_FILES = {
    key: _resolve(value) for key, value in cfg.get("tools", {}).get("config_files", {}).items()
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
