#!/usr/bin/env python3
"""
U-LiDAR Diagnostic
Monitors U-LiDAR health (IP: 192.168.0.10)
Note: U-LiDAR has no ROS driver, web control only
"""

import logging
import subprocess
import time
from datetime import datetime
from typing import Any, Dict

from ..base import BaseDiagnostic, DiagnosticResult, StatusLevel
from ..utils import ping_host

logger = logging.getLogger(__name__)


class UliLidarDiagnostic(BaseDiagnostic):
    """Monitor U-LiDAR health - simplified (network only, no ROS driver)"""

    def __init__(self, config: dict):
        super().__init__("uli_lidar", config)
        self.ips = config.get('SENSOR_IPS', {})
        self.thresholds = config.get('SENSOR_THRESHOLDS', {}).get('uli_lidar', {})

        self.lidar_ip = self.ips.get('uli_lidar', '192.168.0.10')

        # Connection status
        self._last_ping_result = None
        self._last_ping_time = None

        # Connection state caching for resilience against transient failures
        self._last_successful_connection = 0  # timestamp of last successful connection
        self._consecutive_failures = 0
        self._connection_grace_period = float(self.thresholds.get('connection_grace_period', 30))
        self._max_consecutive_failures = int(self.thresholds.get('max_consecutive_failures', 3))
        self._ping_timeout = float(self.thresholds.get('ping_timeout', 2.0))
        self._ping_count = int(self.thresholds.get('ping_count', 2))

        # Alert tracking to avoid duplicate alerts
        self._last_alert_time = {}  # alert_type -> last_timestamp
        self._alert_cooldown = 60  # seconds between same alert type

        # Track previous connection state for disconnection alerts
        self._was_connected = True  # Assume connected on startup

    def check(self) -> DiagnosticResult:
        """Perform U-LiDAR diagnostic check - network only

        Status decision flow (no ROS driver):
        1. Physical connection failed? → DISCONNECTED
        2. Connected → OK (web control, no data stream to check)
        """
        metrics = {}
        details = {}

        # Network connectivity check
        ping_result = self._check_connectivity()
        metrics['network'] = ping_result
        details['network'] = ping_result

        network_ok = ping_result.get('reachable', False)
        latency = ping_result.get('latency_ms', 0)
        packet_loss = ping_result.get('packet_loss', 0)

        if not network_ok:
            # Record disconnection alert when transitioning from connected to disconnected
            if self._was_connected:
                current_time = time.time()
                if current_time - self._last_alert_time.get('sensor_disconnected', 0) > self._alert_cooldown:
                    self._record_alert(
                        alert_type='sensor_disconnected',
                        severity='critical',
                        message=f'U-LiDAR disconnected - network unreachable ({self.lidar_ip})',
                        metric_value=0,
                        threshold=1,
                        metadata={
                            'ip': self.lidar_ip,
                            'reason': 'network_unreachable'
                        }
                    )
                    self._last_alert_time['sensor_disconnected'] = current_time
                self._was_connected = False

            overall_status = StatusLevel.DISCONNECTED
            message = f"U-LiDAR - network unreachable ({self.lidar_ip})"
        elif packet_loss > 1:
            # Update connection state when network is reachable
            if not self._was_connected:
                self._was_connected = True

            overall_status = StatusLevel.WARNING
            message = f"U-LiDAR - OK, high packet loss ({packet_loss:.1f}%)"
        else:
            # Update connection state when network is reachable
            if not self._was_connected:
                self._was_connected = True

            overall_status = StatusLevel.OK
            message = f"U-LiDAR - OK ({latency:.0f}ms latency, web control)"

        self.last_check = datetime.now()
        self.check_count += 1

        self.last_result = DiagnosticResult(
            name=self.name,
            status=overall_status,
            message=message,
            timestamp=self.last_check,
            metrics=metrics,
            details=details
        )

        return self.last_result

    def _check_connectivity(self) -> Dict[str, Any]:
        """Check network connectivity to U-LiDAR

        Includes connection state caching to prevent false disconnections
        from transient network issues.
        """
        current_time = time.time()
        result = ping_host(self.lidar_ip, timeout=self._ping_timeout, count=self._ping_count)

        if result.get('reachable'):
            # Connection successful - update state
            self._last_ping_result = result
            self._last_ping_time = current_time
            self._last_successful_connection = current_time
            self._consecutive_failures = 0
            return {
                'ip': self.lidar_ip,
                'reachable': True,
                'latency_ms': result.get('avg_time_ms', 0),
                'packet_loss': result.get('packet_loss', 0),
            }

        # Ping failed - check if we should use cached success state
        time_since_last_success = current_time - self._last_successful_connection
        self._consecutive_failures += 1

        in_grace_period = time_since_last_success < self._connection_grace_period
        within_failure_limit = self._consecutive_failures <= self._max_consecutive_failures
        has_previous_success = self._last_successful_connection > 0

        if in_grace_period and within_failure_limit and has_previous_success:
            # Use cached success state
            cached_result = self._last_ping_result or {}
            return {
                'ip': self.lidar_ip,
                'reachable': True,
                'latency_ms': cached_result.get('avg_time_ms', 0),
                'packet_loss': cached_result.get('packet_loss', 0),
                'cached': True,
                'consecutive_failures': self._consecutive_failures,
            }

        # Genuine disconnection
        self._last_ping_result = result
        self._last_ping_time = current_time

        return {
            'ip': self.lidar_ip,
            'reachable': False,
            'latency_ms': 0,
            'packet_loss': 100,
            'consecutive_failures': self._consecutive_failures,
        }

    def _record_alert(self, alert_type: str, severity: str, message: str,
                      metric_value: float, threshold: float, metadata: dict):
        """Record alert to database

        Args:
            alert_type: Alert type
            severity: Severity level (critical, warning)
            message: Alert message
            metric_value: Trigger value
            threshold: Threshold value
            metadata: Additional metadata
        """
        try:
            import json
            from alerts import get_alert_store, Alert

            alert = Alert(
                sensor='uli_lidar',
                alert_type=alert_type,
                severity=severity,
                message=message,
                metric_value=metric_value,
                threshold=threshold,
                metadata=json.dumps(metadata),
                created_at=datetime.now().isoformat(),
                status='active'
            )

            alert_id = get_alert_store().add_alert(alert)
            logger.info(f"U-LiDAR alert recorded: ID={alert_id}, type={alert_type}, severity={severity}")
        except Exception as e:
            logger.error(f"Failed to record U-LiDAR alert: {e}")

    def get_diagnostic_summary(self) -> Dict[str, Any]:
        """Get summary for dashboard display"""
        if self.last_result is None:
            return {
                'name': 'U-LiDAR',
                'status': 'stopped',
                'icon': 'fa-solid fa-satellite-dish',
                'color': 'gray',
            }

        status_map = {
            StatusLevel.CRITICAL: ('critical', 'red'),
            StatusLevel.DISCONNECTED: ('disconnected', 'red'),
            StatusLevel.WARNING: ('warning', 'orange'),
            StatusLevel.STOPPED: ('stopped', 'gray'),
            StatusLevel.CONNECTED: ('connected', 'blue'),
            StatusLevel.OK: ('ok', 'green'),
        }

        status_str, color = status_map.get(self.last_result.status, ('stopped', 'gray'))
        reachable = self.last_result.metrics.get('network', {}).get('reachable', False)

        return {
            'name': 'U-LiDAR',
            'status': status_str,
            'icon': 'fa-solid fa-satellite-dish',
            'color': color,
            'value': "Connected" if reachable else "Disconnected",
            'message': self.last_result.message,
        }
