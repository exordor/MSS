#!/usr/bin/env python3
"""
Shared MQTT Client for ROS2 Diagnostic System

Provides a thread-safe MQTT client with topic-based callback routing.
Any sensor module can register callbacks for specific topics.
"""

import json
import logging
import threading
import time
from typing import Any, Callable, Dict, List, Optional

logger = logging.getLogger(__name__)

try:
    import paho.mqtt.client as mqtt
    MQTT_AVAILABLE = True
except ImportError:
    MQTT_AVAILABLE = False


class MqttClient:
    """Shared MQTT client with per-topic callback routing."""

    _instance: Optional['MqttClient'] = None
    _lock = threading.Lock()

    def __init__(self):
        self._client: Optional[mqtt.Client] = None
        self._callbacks: Dict[str, List[Callable[[str, dict], None]]] = {}
        self._connected = False
        self._broker_host = ""
        self._broker_port = 1883
        self._subscribed_topics: set = set()

    @classmethod
    def get_instance(cls) -> 'MqttClient':
        with cls._lock:
            if cls._instance is None:
                cls._instance = cls()
            return cls._instance

    def connect(self, broker_host: str, broker_port: int = 1883,
                client_id: str = "ros2_diagnostic") -> bool:
        if not MQTT_AVAILABLE:
            logger.warning("paho-mqtt not installed, MQTT disabled")
            return False

        with MqttClient._lock:
            if self._connected and self._broker_host == broker_host:
                return True

            if self._client is not None and not self._connected:
                return True

            self._broker_host = broker_host
            self._broker_port = broker_port

            try:
                self._client = mqtt.Client(
                    callback_api_version=mqtt.CallbackAPIVersion.VERSION2,
                    client_id=client_id,
                    protocol=mqtt.MQTTv311,
                )
                self._client.on_connect = self._on_connect
                self._client.on_message = self._on_message
                self._client.on_disconnect = self._on_disconnect

                self._client.connect_async(broker_host, broker_port, keepalive=60)
                self._client.loop_start()

                logger.info(f"MQTT connecting to {broker_host}:{broker_port}")
                return True
            except Exception as e:
                logger.error(f"MQTT connect failed: {e}")
                return False

    def disconnect(self):
        if self._client:
            self._client.loop_stop()
            self._client.disconnect()
            self._connected = False

    def subscribe(self, topic: str, callback: Callable[[str, Any], None]):
        self._callbacks.setdefault(topic, []).append(callback)

        if self._connected and topic not in self._subscribed_topics:
            self._client.subscribe(topic, qos=0)
            self._subscribed_topics.add(topic)
            logger.debug(f"MQTT subscribed: {topic}")

    def publish(self, topic: str, payload: str, qos: int = 0, retain: bool = False) -> bool:
        if not self._connected or not self._client:
            return False
        try:
            self._client.publish(topic, payload, qos=qos, retain=retain)
            return True
        except Exception as e:
            logger.error(f"MQTT publish failed: {e}")
            return False

    def is_connected(self) -> bool:
        return self._connected

    def _on_connect(self, client, userdata, flags, rc, properties=None):
        if rc == 0:
            self._connected = True
            logger.info(f"MQTT connected to {self._broker_host}:{self._broker_port}")
            for topic in self._subscribed_topics:
                client.subscribe(topic, qos=0)
                logger.debug(f"MQTT re-subscribed: {topic}")
            for topic in list(self._callbacks.keys()):
                if topic not in self._subscribed_topics:
                    client.subscribe(topic, qos=0)
                    self._subscribed_topics.add(topic)
        else:
            logger.error(f"MQTT connect failed with code {rc}")

    def _on_disconnect(self, client, userdata, flags, rc, properties=None):
        self._connected = False
        if rc != 0:
            logger.warning(f"MQTT unexpected disconnect (rc={rc}), auto-reconnecting")

    def _on_message(self, client, userdata, msg):
        topic = msg.topic
        payload_str = msg.payload.decode('utf-8', errors='ignore')

        try:
            payload = json.loads(payload_str)
        except (json.JSONDecodeError, ValueError):
            payload = payload_str

        callbacks = self._callbacks.get(topic, [])
        for cb in callbacks:
            try:
                cb(topic, payload)
            except Exception as e:
                logger.error(f"MQTT callback error for {topic}: {e}")
