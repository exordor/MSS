#!/usr/bin/env python3
"""
End-to-end browser test for Pi5 sensor data rendered on the sensors page.
"""

import json
import os
import socket
import subprocess
import sys
import time
from contextlib import closing
from pathlib import Path

import pytest
import requests
from playwright.sync_api import Page

from config import MQTT_CONFIG
from tests.ui.pages.sensors_page import SensorsPage

try:
    import paho.mqtt.client as mqtt
except ImportError:  # pragma: no cover - environment-dependent
    mqtt = None


MEASUREMENTS_PAYLOAD = {
    "run_id": "20260420T163905",
    "measurement_id": 15,
    "elapsed_s": 421.78,
    "timestamp_utc": "2026-04-20T16:46:07.850915+00:00",
    "results": {
        "C4E_Leitfaehigkeit": {
            "Temperatur_C": 18.495498657226562,
            "Leitfaehigkeit_uScm": 0.10004311054944992,
            "Salinitaet_ppt": 5.362310548662208e-05,
            "TDS_ppm": 0.05050176382064819,
        },
        "OPTOD_Sauerstoff": {
            "Temperatur_C": 18.799293518066406,
            "O2_Saettigung_pct": 0.0,
            "O2_mgL": 0.0,
            "O2_ppm": 0.0,
        },
        "pH_Redox": {
            "Temperatur_C": 18.928850173950195,
            "pH": 8.300199508666992,
            "Redox_mV": -4.05580997467041,
            "pH_mV": -66.920654296875,
        },
    },
}

UPS_PAYLOAD = {
    "component": "pi5_ups",
    "parameter": "battery_voltage",
    "value": 12.4,
    "state": "ok",
}


def _find_free_port() -> int:
    with closing(socket.socket(socket.AF_INET, socket.SOCK_STREAM)) as sock:
        sock.bind(("127.0.0.1", 0))
        sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        return sock.getsockname()[1]


def _mqtt_topics() -> tuple[str, str]:
    topics = MQTT_CONFIG.get("pi5_topics", {})
    return (
        topics.get("measurements", "modbus_logger/pi5/measurements"),
        topics.get("ups_status", "modbus_logger/pi5/ups_status"),
    )


def _publish_retained(topic: str, payload: dict | str) -> None:
    if mqtt is None:
        pytest.skip("paho-mqtt is not installed")

    client = mqtt.Client(
        callback_api_version=mqtt.CallbackAPIVersion.VERSION2,
        client_id="pi5_ui_test_publisher",
        protocol=mqtt.MQTTv311,
    )
    client.connect(MQTT_CONFIG.get("broker_host", "127.0.0.1"), int(MQTT_CONFIG.get("broker_port", 1883)), keepalive=60)
    client.loop_start()
    try:
        message = payload if isinstance(payload, str) else json.dumps(payload, ensure_ascii=False)
        info = client.publish(topic, message, qos=0, retain=True)
        info.wait_for_publish()
    finally:
        client.loop_stop()
        client.disconnect()


def _clear_retained_pi5_topics() -> None:
    measurements_topic, ups_topic = _mqtt_topics()
    _publish_retained(measurements_topic, "")
    _publish_retained(ups_topic, "")


@pytest.fixture(scope="session")
def live_server_url(project_root_path: Path):
    if mqtt is None:
        pytest.skip("paho-mqtt is not installed")

    broker_host = MQTT_CONFIG.get("broker_host", "127.0.0.1")
    broker_port = int(MQTT_CONFIG.get("broker_port", 1883))
    try:
        with socket.create_connection((broker_host, broker_port), timeout=2):
            pass
    except OSError as exc:
        pytest.skip(f"MQTT broker {broker_host}:{broker_port} is not available: {exc}")

    _clear_retained_pi5_topics()

    port = _find_free_port()
    base_url = f"http://127.0.0.1:{port}"
    server_log = project_root_path / "logs" / "ui_test_server.log"

    env = os.environ.copy()
    env["PYTHONUNBUFFERED"] = "1"

    with open(server_log, "w", encoding="utf-8") as log_handle:
        process = subprocess.Popen(
            [
                sys.executable,
                "-m",
                "uvicorn",
                "main:app",
                "--host",
                "127.0.0.1",
                "--port",
                str(port),
                "--log-level",
                "warning",
            ],
            cwd=str(project_root_path),
            env=env,
            stdout=log_handle,
            stderr=subprocess.STDOUT,
        )

    deadline = time.time() + 30
    last_error = None
    while time.time() < deadline:
        try:
            response = requests.get(f"{base_url}/sensors", timeout=1)
            if response.status_code == 200:
                break
        except requests.RequestException as exc:
            last_error = exc
        time.sleep(0.25)
    else:
        process.terminate()
        process.wait(timeout=5)
        log_text = server_log.read_text(encoding="utf-8") if server_log.exists() else ""
        raise RuntimeError(f"UI test server did not start: {last_error}\n{log_text}")

    yield base_url

    process.terminate()
    try:
        process.wait(timeout=10)
    except subprocess.TimeoutExpired:
        process.kill()
        process.wait(timeout=5)

    _clear_retained_pi5_topics()


@pytest.fixture(scope="session")
def base_url(live_server_url: str) -> str:
    return live_server_url


@pytest.fixture
def sensors_page(page: Page, base_url: str):
    sensors = SensorsPage(page, base_url)
    sensors.navigate_to_pi5_sensors()
    sensors.wait_for_pi5_panel_active()
    return sensors


@pytest.mark.ui
@pytest.mark.e2e
@pytest.mark.network
def test_pi5_values_render_on_sensors_page(sensors_page: SensorsPage):
    measurements_topic, _ups_topic = _mqtt_topics()

    _publish_retained(measurements_topic, MEASUREMENTS_PAYLOAD)

    sensors_page.wait_for_pi5_values(timeout=15000)
    snapshot = sensors_page.get_pi5_snapshot()

    assert snapshot["status"] == "OK"
    assert snapshot["network"] == "Online"
    assert snapshot["data_age"] == "Active"
    assert snapshot["c4e_temp"] == "18.50 °C"
    assert snapshot["conductivity"] == "0.10 µS/cm"
    assert snapshot["ph"] == "8.30"
    assert snapshot["redox"] == "-4.06 mV"
