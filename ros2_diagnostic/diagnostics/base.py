#!/usr/bin/env python3
"""
Base Diagnostic Classes
"""

from dataclasses import dataclass, field
from datetime import datetime
from typing import Any, Dict, Optional
import enum


class StatusLevel(enum.Enum):
    """Status level for diagnostic results

    Priority (severe → normal):
        1. CRITICAL    - Serious error (config error, hardware failure)
        2. DISCONNECTED - Physical connection lost (network unreachable, serial not connected)
        3. WARNING     - Warning (low frequency, high packet loss, etc.)
        4. STOPPED     - System not running, sensor not active
        5. CONNECTED   - Connected but no data (system running, sensor issue)
        6. OK          - Everything normal (connection + data flow)
    """
    CRITICAL = "critical"
    DISCONNECTED = "disconnected"
    WARNING = "warning"
    UNKNOWN = "unknown"
    STOPPED = "stopped"
    CONNECTED = "connected"
    OK = "ok"

    @classmethod
    def from_value(cls, value: str) -> 'StatusLevel':
        """Get StatusLevel from string value"""
        for level in cls:
            if level.value == value:
                return level
        return cls.STOPPED


# Status priority for comparison (lower = higher priority/severity)
STATUS_PRIORITY = {
    StatusLevel.CRITICAL: 0,      # Most severe
    StatusLevel.DISCONNECTED: 1,
    StatusLevel.WARNING: 2,
    StatusLevel.UNKNOWN: 3,
    StatusLevel.STOPPED: 3,
    StatusLevel.CONNECTED: 4,
    StatusLevel.OK: 5,            # Least severe (best status)
}


def get_higher_priority_status(s1: StatusLevel, s2: StatusLevel) -> StatusLevel:
    """Return the higher priority (more severe) status"""
    p1 = STATUS_PRIORITY.get(s1, 999)
    p2 = STATUS_PRIORITY.get(s2, 999)
    return s1 if p1 < p2 else s2


def _serialize_enum(obj: Any) -> Any:
    """Recursively convert StatusLevel enums to their string values"""
    if isinstance(obj, StatusLevel):
        return obj.value
    elif isinstance(obj, dict):
        return {k: _serialize_enum(v) for k, v in obj.items()}
    elif isinstance(obj, (list, tuple)):
        return type(obj)(_serialize_enum(v) for v in obj)
    return obj


@dataclass
class DiagnosticResult:
    """Result of a diagnostic check"""
    name: str
    status: StatusLevel
    message: str
    timestamp: datetime = field(default_factory=datetime.now)
    metrics: Dict[str, Any] = field(default_factory=dict)
    details: Dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict:
        """Convert to dictionary for JSON serialization"""
        return {
            'name': self.name,
            'status': self.status.value,
            'message': self.message,
            'timestamp': self.timestamp.isoformat(),
            'metrics': _serialize_enum(self.metrics),
            'details': _serialize_enum(self.details),
        }


class BaseDiagnostic:
    """Base class for all diagnostic modules"""

    def __init__(self, name: str, config: dict):
        self.name = name
        self.config = config
        self.last_check: Optional[datetime] = None
        self.last_result: Optional[DiagnosticResult] = None
        self.check_count = 0
        self.error_count = 0

    def check(self) -> DiagnosticResult:
        """
        Perform diagnostic check and return result.
        Subclasses must implement this method.
        """
        raise NotImplementedError(f"{self.__class__.__name__}.check() must be implemented")

    def get_status(self) -> StatusLevel:
        """Return current status based on last check"""
        if self.last_result is None:
            return StatusLevel.STOPPED
        return self.last_result.status

    def is_ok(self) -> bool:
        """Check if status is OK"""
        return self.get_status() == StatusLevel.OK

    def has_warning(self) -> bool:
        """Check if status is WARNING"""
        return self.get_status() == StatusLevel.WARNING

    def is_critical(self) -> bool:
        """Check if status is CRITICAL"""
        return self.get_status() == StatusLevel.CRITICAL

    def _determine_status(
        self,
        value: float,
        warning_threshold: Optional[float] = None,
        critical_threshold: Optional[float] = None,
        less_is_better: bool = True
    ) -> StatusLevel:
        """
        Determine status level based on value and thresholds.

        Args:
            value: The measured value
            warning_threshold: Warning threshold value
            critical_threshold: Critical threshold value
            less_is_better: If True, lower values are better (e.g., CPU usage)
                           If False, higher values are better (e.g., frequency)
        """
        if less_is_better:
            if critical_threshold and value >= critical_threshold:
                return StatusLevel.CRITICAL
            if warning_threshold and value >= warning_threshold:
                return StatusLevel.WARNING
        else:
            if critical_threshold and value <= critical_threshold:
                return StatusLevel.CRITICAL
            if warning_threshold and value <= warning_threshold:
                return StatusLevel.WARNING
        return StatusLevel.OK

    def _check_threshold(
        self,
        value: float,
        min_threshold: Optional[float] = None,
        max_threshold: Optional[float] = None
    ) -> StatusLevel:
        """
        Check if value is within acceptable range.

        Args:
            value: The measured value
            min_threshold: Minimum acceptable value (below = critical)
            max_threshold: Maximum acceptable value (above = critical)
        """
        if min_threshold is not None and value < min_threshold:
            return StatusLevel.CRITICAL
        if max_threshold is not None and value > max_threshold:
            return StatusLevel.CRITICAL
        return StatusLevel.OK


def format_bytes(bytes_value: int) -> str:
    """Format bytes to human readable string"""
    for unit in ['B', 'KB', 'MB', 'GB', 'TB']:
        if bytes_value < 1024.0:
            return f"{bytes_value:.1f} {unit}"
        bytes_value /= 1024.0
    return f"{bytes_value:.1f} PB"


def format_frequency(hz: float) -> str:
    """Format frequency to human readable string"""
    if hz >= 1:
        return f"{hz:.1f} Hz"
    else:
        return f"{hz * 1000:.0f} mHz"


def format_percent(value: float) -> str:
    """Format percentage"""
    return f"{value:.1f}%"
