#!/usr/bin/env python3
"""
Pi5 Sensors Diagnostic
Monitors water quality and UPS status from Pi5 via MQTT.
"""

import logging
import threading
import time
from datetime import datetime
from typing import Any, Dict, Optional

from ..base import BaseDiagnostic, DiagnosticResult, StatusLevel
from ..mqtt_client import MqttClient, MQTT_AVAILABLE
from ..utils import ping_host

logger = logging.getLogger(__name__)


class Pi5SensorsDiagnostic(BaseDiagnostic):
    """Monitor water quality and UPS status from Pi5 via MQTT."""

    def __init__(self, config: dict):
        super().__init__("pi5_sensors", config)
        self._mqtt_config = config.get('MQTT', {})
        self._data_timeout = float(self._mqtt_config.get('data_timeout', 10.0))
        self._pi5_ip = config.get('SENSOR_IPS', {}).get('pi5', '192.168.50.100')

        self._lock = threading.Lock()

        # Water quality cache
        self._latest_water_quality: Dict[str, Any] = {}
        self._last_water_quality_time: float = 0

        # UPS status cache
        self._latest_ups: Dict[str, Any] = {}
        self._last_ups_time: float = 0

        self._init_mqtt_listener()

    def _init_mqtt_listener(self):
        if not MQTT_AVAILABLE or not self._mqtt_config.get('enabled'):
            logger.info("Pi5 MQTT disabled or paho-mqtt not installed")
            return

        pi5_topics = self._mqtt_config.get('pi5_topics', {})
        if not pi5_topics:
            return

        mqtt_client = MqttClient.get_instance()
        broker_host = self._mqtt_config.get('broker_host', '192.168.50.200')
        broker_port = self._mqtt_config.get('broker_port', 1883)
        client_id = self._mqtt_config.get('client_id', 'ros2_diagnostic')

        if not mqtt_client.connect(broker_host, broker_port, client_id):
            logger.warning("Pi5 MQTT connection failed")
            return

        topic_map = {
            'measurements': self._on_mqtt_measurements,
            'ups_status': self._on_mqtt_ups_status,
        }

        for key, callback in topic_map.items():
            topic = pi5_topics.get(key)
            if topic:
                mqtt_client.subscribe(topic, callback)
                logger.info(f"Pi5 MQTT subscribed: {topic}")

    def _on_mqtt_measurements(self, topic: str, payload):
        try:
            now = time.time()
            results = payload.get('results', {})
            wq = {}

            if 'C4E_Leitfaehigkeit' in results:
                c = results['C4E_Leitfaehigkeit']
                wq['c4e_temp_c'] = c.get('Temperatur_C', 0)
                wq['c4e_conductivity_uscm'] = c.get('Leitfaehigkeit_uScm', 0)
                wq['c4e_salinity_ppt'] = c.get('Salinitaet_ppt', 0)
                wq['c4e_tds_ppm'] = c.get('TDS_ppm', 0)

            if 'OPTOD_Sauerstoff' in results:
                o = results['OPTOD_Sauerstoff']
                wq['optod_temp_c'] = o.get('Temperatur_C', 0)
                wq['optod_o2_saturation_pct'] = o.get('O2_Saettigung_pct', 0)
                wq['optod_o2_mgl'] = o.get('O2_mgL', 0)

            if 'pH_Redox' in results:
                p = results['pH_Redox']
                wq['ph_temp_c'] = p.get('Temperatur_C', 0)
                wq['ph_ph'] = p.get('pH', 0)
                wq['ph_redox_mv'] = p.get('Redox_mV', 0)

            with self._lock:
                self._latest_water_quality = wq
                self._last_water_quality_time = now
        except Exception as e:
            logger.debug(f"MQTT measurements parse error: {e}")

    def _on_mqtt_ups_status(self, topic: str, payload):
        try:
            now = time.time()
            ups = {
                'component': payload.get('component', ''),
                'parameter': payload.get('parameter', ''),
                'value': payload.get('value', 0),
                'state': payload.get('state', ''),
            }
            with self._lock:
                self._latest_ups = ups
                self._last_ups_time = now
        except Exception as e:
            logger.debug(f"MQTT UPS parse error: {e}")

    def check(self) -> DiagnosticResult:
        now = time.time()
        metrics = {}
        details = {}

        # Network connectivity check
        ping_result = ping_host(self._pi5_ip, timeout=1, count=1)
        reachable = ping_result.get('reachable', False)
        metrics['ping_ms'] = ping_result.get('avg_time_ms')
        metrics['reachable'] = reachable

        with self._lock:
            wq_fresh = (now - self._last_water_quality_time) < self._data_timeout
            ups_fresh = (now - self._last_ups_time) < self._data_timeout
            wq = dict(self._latest_water_quality)
            ups = dict(self._latest_ups)

        # Determine status
        if not reachable:
            status = StatusLevel.DISCONNECTED
            message = f"Pi5 unreachable ({self._pi5_ip})"
        elif wq_fresh or ups_fresh:
            status = StatusLevel.OK
            message = "Pi5 sensors online"
        else:
            has_ever = self._last_water_quality_time > 0 or self._last_ups_time > 0
            if has_ever:
                status = StatusLevel.WARNING
                message = f"Pi5 data stale (>{self._data_timeout:.0f}s)"
            else:
                status = StatusLevel.CONNECTED
                message = "Pi5 online, no MQTT data yet"

        metrics['water_quality_fresh'] = wq_fresh
        metrics['ups_fresh'] = ups_fresh
        metrics['water_quality_age_s'] = round(now - self._last_water_quality_time, 1) if self._last_water_quality_time > 0 else None
        metrics['ups_age_s'] = round(now - self._last_ups_time, 1) if self._last_ups_time > 0 else None

        details['water_quality'] = wq if wq else None
        details['ups'] = ups if ups else None

        return DiagnosticResult(
            name=self.name,
            status=status,
            message=message,
            timestamp=datetime.now(),
            metrics=metrics,
            details=details,
        )

    def get_diagnostic_summary(self) -> Dict[str, Any]:
        if self.last_result is None:
            return {
                'name': 'Pi5 Sensors',
                'status': 'stopped',
                'icon': 'fa-solid fa-water',
                'color': 'gray',
            }

        status_map = {
            StatusLevel.CRITICAL: ('critical', 'red'),
            StatusLevel.DISCONNECTED: ('disconnected', 'red'),
            StatusLevel.WARNING: ('warning', 'orange'),
            StatusLevel.STOPPED: ('stopped', 'gray'),
            StatusLevel.CONNECTED: ('connected', 'blue'),
            StatusLevel.OK: ('ok', 'green'),
            StatusLevel.UNKNOWN: ('unknown', 'gray'),
        }

        status_str, color = status_map.get(self.last_result.status, ('stopped', 'gray'))
        wq = self.last_result.details.get('water_quality') if self.last_result.details else None

        if wq and wq.get('ph_ph') is not None:
            value_str = f"pH {wq['ph_ph']:.2f}"
        else:
            value_str = 'Online' if status_str == 'ok' else 'Offline'

        return {
            'name': 'Pi5 Sensors',
            'status': status_str,
            'icon': 'fa-solid fa-water',
            'color': color,
            'value': value_str,
            'message': self.last_result.message,
            'water_quality': wq,
            'ups': self.last_result.details.get('ups') if self.last_result.details else None,
        }
