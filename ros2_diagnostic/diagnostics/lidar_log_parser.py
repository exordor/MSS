#!/usr/bin/env python3
"""
Navi LiDAR Log Parser
Parse point cloud statistics from log files
"""

import re
import threading
from collections import deque
from datetime import datetime
from typing import Optional
from dataclasses import dataclass
from pathlib import Path

# Log line regex
# Match format: [hesai_ros_driver_node-1] raw frame:49 points:115200 packet:450 start time:1602248443.495515 end time:1602248443.595332
LOG_PATTERN = re.compile(
    r'\[hesai_ros_driver_node-\d+\] '
    r'raw frame:(\d+) '
    r'points:(\d+) '
    r'packet:(\d+) '
    r'start time:([\d.]+) '
    r'end time:([\d.]+)'
)


@dataclass
class FrameData:
    """Single frame data"""
    frame_num: int
    points: int
    packets: int
    start_time: float
    end_time: float


@dataclass
class LidarStats:
    """LiDAR statistics"""
    frame_count: int
    total_points: int
    avg_points: float
    min_points: int
    max_points: int
    frequency: float
    last_frame_num: int
    last_timestamp: Optional[float]
    time_since_last_frame: float


class LidarLogParser:
    """Parse LiDAR data from log files

    Thread-safe log parser for extracting from navi_lidar logs:
    - Point cloud count
    - Frame rate (calculated from timestamps)
    - Packet count
    """

    def __init__(self,
                 log_file: str = None,
                 max_history: int = 100):
        self.log_file = log_file
        self.max_history = max_history

        # Parse cache
        self._frames: deque = deque(maxlen=max_history)
        self._last_pos = 0  # Last read position
        self._lock = threading.Lock()

        # Stats cache
        self._cached_stats: Optional[LidarStats] = None
        self._cache_time: float = 0
        self._cache_ttl: float = 0.5  # Cache for 0.5 seconds

    def _find_log_file(self) -> Optional[str]:
        """Find navi_lidar log file

        Priority:
        1. navi_lidar_driver.log (extracted by logging.sh)
        2. 00_master.log (raw master log)

        Log directory structure: logs/YYYYMMDD_HHMMSS/app/00_master.log
        """
        logs_dir = Path("logs")
        if not logs_dir.exists():
            return None

        # Find latest navi_lidar_driver.log (may be in app subdirectory)
        driver_logs = list(logs_dir.glob("*/app/navi_lidar_driver.log"))
        driver_logs.extend(list(logs_dir.glob("*/navi_lidar_driver.log")))
        if driver_logs:
            return str(max(driver_logs, key=lambda p: p.stat().st_mtime))

        # Fall back to 00_master.log (may be in app subdirectory)
        master_logs = list(logs_dir.glob("*/app/00_master.log"))
        master_logs.extend(list(logs_dir.glob("*/00_master.log")))
        if master_logs:
            return str(max(master_logs, key=lambda p: p.stat().st_mtime))

        return None

    def _read_new_lines(self) -> list:
        """Read new lines from log file"""
        log_path = self.log_file or self._find_log_file()
        if not log_path:
            return []

        try:
            with open(log_path, 'r') as f:
                # Continue reading from last position
                f.seek(self._last_pos)
                new_lines = f.readlines()
                self._last_pos = f.tell()
                return new_lines
        except (FileNotFoundError, IOError):
            return []

    def parse_new_frames(self) -> int:
        """Parse new frame data, returns number of new frames"""
        new_lines = self._read_new_lines()
        new_frames = []

        for line in new_lines:
            match = LOG_PATTERN.search(line)
            if match:
                frame = FrameData(
                    frame_num=int(match.group(1)),
                    points=int(match.group(2)),
                    packets=int(match.group(3)),
                    start_time=float(match.group(4)),
                    end_time=float(match.group(5))
                )
                new_frames.append(frame)

        with self._lock:
            self._frames.extend(new_frames)
            # Invalidate cache since data has been updated
            self._cached_stats = None

        return len(new_frames)

    def get_statistics(self) -> LidarStats:
        """Get statistics (with caching)"""
        # Parse new data first
        self.parse_new_frames()

        current_time = datetime.now().timestamp()

        # Check cache
        if self._cached_stats and (current_time - self._cache_time) < self._cache_ttl:
            return self._cached_stats

        with self._lock:
            frames = list(self._frames)

        if not frames:
            return LidarStats(
                frame_count=0,
                total_points=0,
                avg_points=0,
                min_points=0,
                max_points=0,
                frequency=0,
                last_frame_num=0,
                last_timestamp=None,
                time_since_last_frame=float('inf')
            )

        # Basic statistics
        points = [f.points for f in frames]
        frame_count = len(frames)

        # Calculate frequency (based on last 5 seconds of data)
        # Note: Log timestamps may use device time rather than system time
        # so use relative difference between log timestamps for frequency
        if len(frames) >= 2:
            # Use last 100 frames or all frames for frequency
            calc_frames = frames[-min(100, len(frames)):]
            duration = calc_frames[-1].start_time - calc_frames[0].start_time
            if duration > 0:
                frequency = (len(calc_frames) - 1) / duration
        else:
            frequency = 0

        # Time difference for last frame
        # Since log timestamps may use device time rather than system time,
        # use the difference between current time and last parse time as approximation
        time_since_last = current_time - self._cache_time if self._cache_time > 0 else 0

        # Get last frame info
        last_frame = frames[-1]

        stats = LidarStats(
            frame_count=frame_count,
            total_points=sum(points),
            avg_points=sum(points) / len(points),
            min_points=min(points),
            max_points=max(points),
            frequency=frequency,
            last_frame_num=last_frame.frame_num,
            last_timestamp=last_frame.end_time,
            time_since_last_frame=time_since_last
        )

        # Update cache
        self._cached_stats = stats
        self._cache_time = current_time

        return stats

    def reset(self):
        """Reset statistics"""
        with self._lock:
            self._frames.clear()
            self._cached_stats = None
            self._last_pos = 0
