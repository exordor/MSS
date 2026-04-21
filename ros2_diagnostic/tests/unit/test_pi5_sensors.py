#!/usr/bin/env python3
"""
Tests for Pi5 sensor diagnostics.
"""

import sys
import time
from pathlib import Path
from unittest.mock import patch

import pytest


sys.path.insert(0, str(Path(__file__).parent.parent.parent))

from diagnostics.sensor_monitor.pi5_sensors import Pi5SensorsDiagnostic


class TestPi5SensorsDiagnostic:
    """Regression tests for Pi5 MQTT-backed diagnostics."""

    @patch.object(Pi5SensorsDiagnostic, "_init_mqtt_listener", autospec=True)
    @patch("diagnostics.sensor_monitor.pi5_sensors.ping_host", return_value={"reachable": True, "avg_time_ms": 1.2})
    def test_check_persists_last_result_for_summary(self, _mock_ping, _mock_init_mqtt):
        monitor = Pi5SensorsDiagnostic({
            "MQTT": {"enabled": False, "data_timeout": 60.0},
            "SENSOR_IPS": {"pi5": "192.168.50.73"},
        })

        now = time.time()
        monitor._latest_water_quality = {
            "ph_ph": 7.23,
            "ph_redox_mv": 215.4,
            "optod_o2_mgl": 8.51,
        }
        monitor._last_water_quality_time = now
        monitor._latest_ups = {
            "component": "battery",
            "parameter": "voltage",
            "value": 12.4,
            "state": "ok",
        }
        monitor._last_ups_time = now

        result = monitor.check()
        summary = monitor.get_diagnostic_summary()

        assert monitor.last_result is result
        assert result.details["water_quality"]["ph_ph"] == 7.23
        assert summary["status"] == "ok"
        assert summary["water_quality"]["ph_ph"] == 7.23
        assert summary["ups"]["state"] == "ok"
        assert summary["value"] == "pH 7.23"

    @patch.object(Pi5SensorsDiagnostic, "_init_mqtt_listener", autospec=True)
    @patch("diagnostics.sensor_monitor.pi5_sensors.ping_host", return_value={"reachable": True, "avg_time_ms": 1.2})
    def test_measurements_callback_accepts_flat_payload(self, _mock_ping, _mock_init_mqtt):
        monitor = Pi5SensorsDiagnostic({
            "MQTT": {"enabled": False, "data_timeout": 60.0},
            "SENSOR_IPS": {"pi5": "192.168.50.73"},
        })

        flat_payload = {
            "run_id": "20260421T140543",
            "measurement_id": 77,
            "elapsed_s": 2300.481,
            "c4e_temp_c": 17.06191062927246,
            "c4e_conductivity_uscm": 0.11383127421140671,
            "c4e_salinity_ppt": 6.101356484577991e-05,
            "c4e_tds_ppm": 0.05746202915906906,
            "optod_temp_c": 16.885988235473633,
            "optod_o2_saturation_pct": 0.0,
            "optod_o2_mgl": 0.0,
            "optod_o2_ppm": 0.0,
            "ph_temp_c": 17.95061683654785,
            "ph_ph": 8.241888999938965,
            "ph_redox_mv": -4.48836612701416,
            "ph_mv": -61.941497802734375,
        }

        monitor._on_mqtt_measurements("modbus_logger/pi5/measurements", flat_payload)
        result = monitor.check()
        summary = monitor.get_diagnostic_summary()

        assert result.status.value == "ok"
        assert result.details["water_quality"] is not None
        assert set(result.details["water_quality"].keys()) == {
            "c4e_temp_c",
            "c4e_conductivity_uscm",
            "c4e_salinity_ppt",
            "c4e_tds_ppm",
            "optod_temp_c",
            "optod_o2_saturation_pct",
            "optod_o2_mgl",
            "optod_o2_ppm",
            "ph_temp_c",
            "ph_ph",
            "ph_redox_mv",
            "ph_mv",
        }
        assert result.details["water_quality"]["c4e_temp_c"] == pytest.approx(17.06191062927246)
        assert result.details["water_quality"]["ph_ph"] == pytest.approx(8.241888999938965)
        assert result.details["water_quality"]["ph_mv"] == pytest.approx(-61.941497802734375)
        assert summary["water_quality"]["optod_temp_c"] == pytest.approx(16.885988235473633)
        assert summary["value"] == "pH 8.24"

    @patch.object(Pi5SensorsDiagnostic, "_init_mqtt_listener", autospec=True)
    @patch("diagnostics.sensor_monitor.pi5_sensors.ping_host", return_value={"reachable": True, "avg_time_ms": 1.2})
    def test_measurements_callback_accepts_real_nested_payload(self, _mock_ping, _mock_init_mqtt):
        monitor = Pi5SensorsDiagnostic({
            "MQTT": {"enabled": False, "data_timeout": 60.0},
            "SENSOR_IPS": {"pi5": "192.168.50.73"},
        })

        nested_payload = {
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

        monitor._on_mqtt_measurements("modbus_logger/pi5/measurements", nested_payload)
        result = monitor.check()
        summary = monitor.get_diagnostic_summary()

        assert result.status.value == "ok"
        assert result.details["water_quality"]["c4e_temp_c"] == pytest.approx(18.495498657226562)
        assert result.details["water_quality"]["c4e_conductivity_uscm"] == pytest.approx(0.10004311054944992)
        assert result.details["water_quality"]["optod_temp_c"] == pytest.approx(18.799293518066406)
        assert result.details["water_quality"]["ph_ph"] == pytest.approx(8.300199508666992)
        assert result.details["water_quality"]["ph_redox_mv"] == pytest.approx(-4.05580997467041)
        assert result.details["water_quality"]["ph_mv"] == pytest.approx(-66.920654296875)
        assert summary["value"] == "pH 8.30"
