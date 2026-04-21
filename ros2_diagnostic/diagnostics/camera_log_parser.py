#!/usr/bin/env python3
"""
Camera Log Parser
Parse statistics from Galaxy Camera log files
"""

import re
import threading
from collections import deque
from datetime import datetime
from typing import Optional
from dataclasses import dataclass
from pathlib import Path


# Log line regex - matches BOTTLENECK ANALYSIS REPORT
# Format example:
# [1] FRAME STATUS: Total=3, Published=3, SDKIncomplete=0 | Data loss: 0.0%
# [2] NETWORK INTERFACE (eno1): RX packets=31946 (45.57 MB, 364.5 Mbps), errors=0, dropped=0
# [3] CALLBACK (SDK->Queue): Avg=2.97 ms, Min=2.62 ms, Max=3.42 ms | Queue: 0/16 frames
# [4] PROCESSING THREAD: Avg=49.75 ms (Conversion=27.96 ms, Publish=21.79 ms)
REPORT_PATTERN = re.compile(
    r'\[1\] FRAME STATUS: Total=(\d+), Published=(\d+), SDKIncomplete=(\d+).*?\n'
    r'.*?\[2\] NETWORK INTERFACE \([^\)]+\):.*?errors=(\d+), dropped=(\d+).*?\n'
    r'.*?\[3\] CALLBACK.*?Avg=([\d.]+) ms.*?\n'
    r'.*?\[4\] PROCESSING THREAD.*?Avg=([\d.]+) ms',
    re.DOTALL
)

# Single-line frame status pattern (for more frequent statistics)
# Frame 1 status=SUCCESS(0) ts=10155814645808 bytes=12288000/12288000
FRAME_PATTERN = re.compile(
    r'Frame (\d+) status=(\w+)\((\d+)\) ts=([\d.]+) bytes=(\d+)/(\d+)'
)


@dataclass
class ReportData:
    """BOTTLENECK ANALYSIS REPORT data"""
    timestamp: float
    total_frames: int
    published_frames: int
    incomplete_frames: int
    rx_errors: int
    rx_dropped: int
    avg_callback_ms: float
    avg_processing_ms: float


@dataclass
class CameraStats:
    """Camera statistics"""
    frame_count: int           # Total frames (accumulated from REPORT)
    published_count: int       # Successfully published frames
    incomplete_count: int      # SDK incomplete frames (frame loss)
    queue_dropped: int         # Queue dropped frames
    frequency: float           # Measured frame rate (Hz)
    avg_callback_ms: float     # Average callback latency
    avg_processing_ms: float   # Average processing latency
    rx_errors: int             # Network receive errors
    rx_dropped: int            # Network dropped packets
    last_report_time: Optional[float]  # Last report timestamp
    time_since_last_report: float      # Time since last report (seconds)


class CameraLogParser:
    """Parse Camera data from log files

    Thread-safe log parser for extracting from galaxy_camera logs:
    - Frame rate and frame loss statistics
    - Network errors and packet loss
    - Processing latency (callback, processing thread)
    """

    def __init__(self,
                 log_file: str = None,
                 max_history: int = 30):
        """
        Args:
            log_file: Log file path (None for auto-detect)
            max_history: Number of REPORTs to keep in history
        """
        self.log_file = log_file
        self.max_history = max_history

        # Parse cache
        self._reports: deque = deque(maxlen=max_history)
        self._last_pos = 0  # Last read position
        self._lock = threading.Lock()

        # Stats cache
        self._cached_stats: Optional[CameraStats] = None
        self._cache_time: float = 0
        self._cache_ttl: float = 0.5  # Cache for 0.5 seconds

        # Cumulative statistics (for frequency calculation)
        self._total_frames_seen = 0
        self._first_report_time: Optional[float] = None

    def _find_log_file(self) -> Optional[str]:
        """Find camera log file

        Priority:
        1. galaxy_camera.log (extracted by logging.sh)
        2. 00_master.log (raw master log)

        Log directory structure: logs/YYYYMMDD_HHMMSS/app/galaxy_camera.log
        """
        logs_dir = Path("logs")
        if not logs_dir.exists():
            return None

        # Find latest galaxy_camera.log (in app subdirectory)
        camera_logs = list(logs_dir.glob("*/app/galaxy_camera.log"))
        if camera_logs:
            return str(max(camera_logs, key=lambda p: p.stat().st_mtime))

        # Fall back to 00_master.log
        master_logs = list(logs_dir.glob("*/app/00_master.log"))
        if master_logs:
            return str(max(master_logs, key=lambda p: p.stat().st_mtime))

        return None

    def _read_new_lines(self) -> list:
        """Read new lines from log file"""
        log_path = self.log_file or self._find_log_file()
        if not log_path:
            return []

        try:
            with open(log_path, 'r', encoding='utf-8', errors='ignore') as f:
                # Continue reading from last position
                f.seek(self._last_pos)
                new_lines = f.readlines()
                self._last_pos = f.tell()
                return new_lines
        except (FileNotFoundError, IOError):
            return []

    def _extract_timestamp(self, line: str) -> Optional[float]:
        """Extract timestamp from log line

        Format: [1769539045.416759136] [INFO] [galaxy_camera] ...
        Returns: Unix timestamp (seconds.nanoseconds)
        """
        match = re.search(r'\[(\d+)\.(\d+)\]', line)
        if match:
            seconds = int(match.group(1))
            nanos = int(match.group(2))
            return seconds + nanos / 1e9
        return None

    def parse_new_reports(self) -> int:
        """Parse new REPORT data, returns number of new reports"""
        new_lines = self._read_new_lines()
        new_reports = []

        # Merge multi-line logs for REPORT matching
        log_text = ''.join(new_lines)

        # Find all REPORTs
        for match in REPORT_PATTERN.finditer(log_text):
            # Extract timestamp (search backwards from match position)
            start_pos = match.start()
            # Look backwards for a line containing timestamp
            lines_before = log_text[max(0, start_pos - 500):start_pos].split('\n')[-5:]
            timestamp = None
            for line in lines_before:
                ts = self._extract_timestamp(line)
                if ts:
                    timestamp = ts
                    break

            if timestamp is None:
                timestamp = datetime.now().timestamp()

            report = ReportData(
                timestamp=timestamp,
                total_frames=int(match.group(1)),
                published_frames=int(match.group(2)),
                incomplete_frames=int(match.group(3)),
                rx_errors=int(match.group(4)),
                rx_dropped=int(match.group(5)),
                avg_callback_ms=float(match.group(6)),
                avg_processing_ms=float(match.group(7))
            )
            new_reports.append(report)

        with self._lock:
            self._reports.extend(new_reports)
            # Invalidate cache since data has been updated
            self._cached_stats = None

            # Update cumulative statistics
            for report in new_reports:
                if self._first_report_time is None:
                    self._first_report_time = report.timestamp
                self._total_frames_seen += report.total_frames

        return len(new_reports)

    def get_statistics(self) -> CameraStats:
        """Get statistics (with caching)"""
        # Parse new data first
        self.parse_new_reports()

        current_time = datetime.now().timestamp()

        # Check cache
        if self._cached_stats and (current_time - self._cache_time) < self._cache_ttl:
            return self._cached_stats

        with self._lock:
            reports = list(self._reports)

        if not reports:
            return CameraStats(
                frame_count=0,
                published_count=0,
                incomplete_count=0,
                queue_dropped=0,
                frequency=0,
                avg_callback_ms=0,
                avg_processing_ms=0,
                rx_errors=0,
                rx_dropped=0,
                last_report_time=None,
                time_since_last_report=float('inf')
            )

        # Use the latest report
        latest = reports[-1]

        # Calculate frequency (based on all reports)
        if len(reports) >= 2 and self._first_report_time:
            duration = latest.timestamp - self._first_report_time
            if duration > 0:
                frequency = self._total_frames_seen / duration
            else:
                frequency = 0
        else:
            frequency = 0

        # Time difference
        time_since_last = current_time - latest.timestamp

        # Average values (using last 10 reports)
        recent_reports = reports[-min(10, len(reports)):]
        avg_callback = sum(r.avg_callback_ms for r in recent_reports) / len(recent_reports)
        avg_processing = sum(r.avg_processing_ms for r in recent_reports) / len(recent_reports)

        stats = CameraStats(
            frame_count=latest.total_frames,
            published_count=latest.published_frames,
            incomplete_count=latest.incomplete_frames,
            queue_dropped=0,  # Requires separate queue drop log parsing
            frequency=frequency,
            avg_callback_ms=avg_callback,
            avg_processing_ms=avg_processing,
            rx_errors=latest.rx_errors,
            rx_dropped=latest.rx_dropped,
            last_report_time=latest.timestamp,
            time_since_last_report=time_since_last
        )

        # Update cache
        self._cached_stats = stats
        self._cache_time = current_time

        return stats

    def reset(self):
        """Reset statistics"""
        with self._lock:
            self._reports.clear()
            self._cached_stats = None
            self._last_pos = 0
            self._total_frames_seen = 0
            self._first_report_time = None


# Convenience function
def parse_camera_log(log_file: str = None) -> CameraStats:
    """Parse camera log and return statistics

    Args:
        log_file: Log file path (None for auto-detect latest)

    Returns:
        CameraStats: Statistics data
    """
    parser = CameraLogParser(log_file=log_file)
    return parser.get_statistics()
