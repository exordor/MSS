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
        self._pi5_ip = config.get('SENSOR_IPS', {}).get('pi5', '192.168.50.73')

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
            logger.info(f"MQTT measurements received on {topic}: "
                        f"type={type(payload).__name__}, keys={list(payload.keys()) if isinstance(payload, dict) else 'N/A'}")
            now = time.time()
            wq = self._parse_measurements_payload(payload)

            if wq:
                logger.info(f"MQTT measurements parsed: {list(wq.keys())}")
                with self._lock:
                    self._latest_water_quality = wq
                    self._last_water_quality_time = now
            else:
                logger.warning(f"MQTT measurements: no known sensor keys found. "
                               f"Top-level keys: {list(payload.keys()) if isinstance(payload, dict) else type(payload).__name__}")
        except Exception as e:
            logger.warning(f"MQTT measurements parse error: {e}")

    @staticmethod
    def _copy_known_fields(source: Dict[str, Any], field_names: tuple[str, ...]) -> Dict[str, Any]:
        """Copy known measurement fields from a source dict without changing names."""
        return {
            field_name: source[field_name]
            for field_name in field_names
            if field_name in source
        }

    def _parse_measurements_payload(self, payload: Any) -> Dict[str, Any]:
        """Parse water-quality MQTT payloads from nested or flat formats."""
        if not isinstance(payload, dict):
            return {}

        flat_field_names = (
            'c4e_temp_c',
            'c4e_conductivity_uscm',
            'c4e_salinity_ppt',
            'c4e_tds_ppm',
            'optod_temp_c',
            'optod_o2_saturation_pct',
            'optod_o2_mgl',
            'optod_o2_ppm',
            'ph_temp_c',
            'ph_ph',
            'ph_redox_mv',
            'ph_mv',
        )
        flat_payload = self._copy_known_fields(payload, flat_field_names)
        if flat_payload:
            return flat_payload

        results = payload.get('results', {})
        if not isinstance(results, dict):
            logger.warning("MQTT measurements: invalid 'results' payload type")
            return {}

        if not results:
            logger.warning("MQTT measurements: no 'results' key in payload")
            return {}

        wq = {}

        if 'C4E_Leitfaehigkeit' in results and isinstance(results['C4E_Leitfaehigkeit'], dict):
            c = results['C4E_Leitfaehigkeit']
            wq['c4e_temp_c'] = c.get('Temperatur_C', 0)
            wq['c4e_conductivity_uscm'] = c.get('Leitfaehigkeit_uScm', 0)
            wq['c4e_salinity_ppt'] = c.get('Salinitaet_ppt', 0)
            wq['c4e_tds_ppm'] = c.get('TDS_ppm', 0)

        if 'OPTOD_Sauerstoff' in results and isinstance(results['OPTOD_Sauerstoff'], dict):
            o = results['OPTOD_Sauerstoff']
            wq['optod_temp_c'] = o.get('Temperatur_C', 0)
            wq['optod_o2_saturation_pct'] = o.get('O2_Saettigung_pct', 0)
            wq['optod_o2_mgl'] = o.get('O2_mgL', 0)
            wq['optod_o2_ppm'] = o.get('O2_ppm', 0)

        if 'pH_Redox' in results and isinstance(results['pH_Redox'], dict):
            p = results['pH_Redox']
            wq['ph_temp_c'] = p.get('Temperatur_C', 0)
            wq['ph_ph'] = p.get('pH', 0)
            wq['ph_redox_mv'] = p.get('Redox_mV', 0)
            wq['ph_mv'] = p.get('pH_mV', 0)

        return wq

    def _on_mqtt_ups_status(self, topic: str, payload):
        try:
            logger.debug(f"MQTT UPS received on {topic}: {payload}")
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
            logger.warning(f"MQTT UPS parse error: {e}")

    def _check_connectivity(self) -> dict:
        result = ping_host(self._pi5_ip, timeout=1, count=2)
        return {'reachable': result.get('reachable', False), 'latency_ms': result.get('avg_time_ms')}

    def check(self) -> DiagnosticResult:
        now = time.time()
        metrics = {}
        details = {}

        with self._lock:
            wq_fresh = (now - self._last_water_quality_time) < self._data_timeout
            ups_fresh = (now - self._last_ups_time) < self._data_timeout
            wq = dict(self._latest_water_quality)
            ups = dict(self._latest_ups)
            has_data = self._last_water_quality_time > 0 or self._last_ups_time > 0

        # MQTT data freshness is the connectivity indicator (like Arduino's UDP heartbeat)
        mqtt_online = wq_fresh or ups_fresh

        # Ping check
        ping_result = ping_host(self._pi5_ip, timeout=1, count=2)
        ping_ok = ping_result.get('reachable', False)
        metrics['ping_ms'] = ping_result.get('avg_time_ms')
        metrics['reachable'] = ping_ok

        metrics['water_quality_fresh'] = wq_fresh
        metrics['ups_fresh'] = ups_fresh
        metrics['water_quality_age_s'] = round(now - self._last_water_quality_time, 1) if self._last_water_quality_time > 0 else None
        metrics['ups_age_s'] = round(now - self._last_ups_time, 1) if self._last_ups_time > 0 else None

        # Determine status based on ping (stable) + MQTT data (supplementary)
        if not ping_ok:
            status = StatusLevel.DISCONNECTED
            message = "Pi5 unreachable (ping failed)"
        elif mqtt_online:
            status = StatusLevel.OK
            message = "Pi5 sensors online"
        elif has_data:
            status = StatusLevel.OK
            message = f"Pi5 online, MQTT data stale ({metrics['water_quality_age_s'] or metrics['ups_age_s']}s)"
        else:
            status = StatusLevel.CONNECTED
            message = "Pi5 online, no MQTT data yet"

        wq_summary = (f"pH={wq.get('ph_ph', '--')}, Redox={wq.get('ph_redox_mv', '--')}mV, "
                      f"O2={wq.get('optod_o2_mgl', '--')}mg/L, "
                      f"Cond={wq.get('c4e_conductivity_uscm', '--')}µS/cm, "
                      f"Temp={wq.get('c4e_temp_c', '--')}°C") if wq else 'no data'
        logger.info(f"Pi5 check: mqtt_online={mqtt_online} wq_age={metrics.get('water_quality_age_s')}s "
                    f"ping={ping_ok} status={status.name} | {wq_summary}")

        details['water_quality'] = wq if wq else None
        details['ups'] = ups if ups else None

        self.last_check = datetime.now()
        self.check_count += 1

        self.last_result = DiagnosticResult(
            name=self.name,
            status=status,
            message=message,
            timestamp=self.last_check,
            metrics=metrics,
            details=details,
        )
        return self.last_result

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

        summary = {
            'name': 'Pi5 Sensors',
            'status': status_str,
            'icon': 'fa-solid fa-water',
            'color': color,
            'value': value_str,
            'message': self.last_result.message,
            'water_quality': wq,
            'ups': self.last_result.details.get('ups') if self.last_result.details else None,
        }
        logger.info(
            "[PI5_DEBUG] summary status=%s value=%s has_wq=%s has_ups=%s",
            summary['status'],
            summary['value'],
            bool(summary.get('water_quality')),
            bool(summary.get('ups')),
        )
        return summary
