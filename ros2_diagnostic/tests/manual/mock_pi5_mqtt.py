#!/usr/bin/env python3
"""
Publish mock Pi5 MQTT payloads for manual end-to-end testing.
"""

import argparse
import json
import sys
import time
from copy import deepcopy
from datetime import datetime, timezone
from pathlib import Path


sys.path.insert(0, str(Path(__file__).parent.parent.parent))

from config import MQTT_CONFIG
from diagnostics.mqtt_client import MQTT_AVAILABLE

if MQTT_AVAILABLE:
    import paho.mqtt.client as mqtt
else:
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


def build_measurements_payload(sequence: int) -> dict:
    payload = deepcopy(MEASUREMENTS_PAYLOAD)
    payload["measurement_id"] = sequence
    payload["elapsed_s"] = round(MEASUREMENTS_PAYLOAD["elapsed_s"] + sequence * 30.0, 2)
    payload["timestamp_utc"] = datetime.now(timezone.utc).isoformat()
    return payload


def publish(topic: str, payload: dict, client: mqtt.Client):
    message = json.dumps(payload, ensure_ascii=False)
    info = client.publish(topic, message, qos=0, retain=False)
    info.wait_for_publish()
    print(f"published {topic}: {message}")


def main():
    parser = argparse.ArgumentParser(description="Publish mock Pi5 MQTT messages")
    parser.add_argument("--host", default=MQTT_CONFIG.get("broker_host", "127.0.0.1"))
    parser.add_argument("--port", type=int, default=int(MQTT_CONFIG.get("broker_port", 1883)))
    parser.add_argument("--count", type=int, default=1, help="Number of measurement messages to publish")
    parser.add_argument("--interval", type=float, default=1.0, help="Seconds between publishes")
    parser.add_argument("--with-ups", action="store_true", help="Also publish one UPS status message")
    args = parser.parse_args()

    if not MQTT_AVAILABLE:
        raise SystemExit("paho-mqtt not installed")

    topics = MQTT_CONFIG.get("pi5_topics", {})
    measurements_topic = topics.get("measurements", "modbus_logger/pi5/measurements")
    ups_topic = topics.get("ups_status", "modbus_logger/pi5/ups_status")

    client = mqtt.Client(
        callback_api_version=mqtt.CallbackAPIVersion.VERSION2,
        client_id="pi5_mock_publisher",
        protocol=mqtt.MQTTv311,
    )
    client.connect(args.host, args.port, keepalive=60)
    client.loop_start()

    try:
        if args.with_ups:
            publish(ups_topic, UPS_PAYLOAD, client)

        for idx in range(args.count):
            publish(measurements_topic, build_measurements_payload(idx + 1), client)
            if idx < args.count - 1:
                time.sleep(args.interval)
    finally:
        client.loop_stop()
        client.disconnect()


if __name__ == "__main__":
    main()
