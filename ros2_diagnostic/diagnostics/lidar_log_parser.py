#!/usr/bin/env python3
"""
Navi LiDAR Log Parser
从日志文件中解析点云统计数据
"""

import re
import threading
from collections import deque
from datetime import datetime
from typing import Optional
from dataclasses import dataclass
from pathlib import Path

# 日志行正则表达式
# 匹配格式: [hesai_ros_driver_node-1] raw frame:49 points:115200 packet:450 start time:1602248443.495515 end time:1602248443.595332
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
    """单帧数据"""
    frame_num: int
    points: int
    packets: int
    start_time: float
    end_time: float


@dataclass
class LidarStats:
    """LiDAR 统计数据"""
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
    """从日志文件解析 LiDAR 数据

    线程安全的日志解析器，用于从 navi_lidar 日志中提取：
    - 点云数量
    - 帧率 (通过时间戳计算)
    - 包数量
    """

    def __init__(self,
                 log_file: str = None,
                 max_history: int = 100):
        self.log_file = log_file
        self.max_history = max_history

        # 解析缓存
        self._frames: deque = deque(maxlen=max_history)
        self._last_pos = 0  # 上次读取位置
        self._lock = threading.Lock()

        # 统计缓存
        self._cached_stats: Optional[LidarStats] = None
        self._cache_time: float = 0
        self._cache_ttl: float = 0.5  # 缓存 0.5 秒

    def _find_log_file(self) -> Optional[str]:
        """查找 navi_lidar 日志文件

        优先级：
        1. navi_lidar_driver.log (由 logging.sh 提取)
        2. 00_master.log (原始主日志)

        日志目录结构: logs/YYYYMMDD_HHMMSS/app/00_master.log
        """
        logs_dir = Path("logs")
        if not logs_dir.exists():
            return None

        # 查找最新的 navi_lidar_driver.log (可能在 app 子目录)
        driver_logs = list(logs_dir.glob("*/app/navi_lidar_driver.log"))
        driver_logs.extend(list(logs_dir.glob("*/navi_lidar_driver.log")))
        if driver_logs:
            return str(max(driver_logs, key=lambda p: p.stat().st_mtime))

        # 回退到 00_master.log (可能在 app 子目录)
        master_logs = list(logs_dir.glob("*/app/00_master.log"))
        master_logs.extend(list(logs_dir.glob("*/00_master.log")))
        if master_logs:
            return str(max(master_logs, key=lambda p: p.stat().st_mtime))

        return None

    def _read_new_lines(self) -> list:
        """读取日志文件中的新增行"""
        log_path = self.log_file or self._find_log_file()
        if not log_path:
            return []

        try:
            with open(log_path, 'r') as f:
                # 从上次位置继续读取
                f.seek(self._last_pos)
                new_lines = f.readlines()
                self._last_pos = f.tell()
                return new_lines
        except (FileNotFoundError, IOError):
            return []

    def parse_new_frames(self) -> int:
        """解析新增的帧数据，返回新增帧数"""
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
            # 清除缓存，因为数据更新了
            self._cached_stats = None

        return len(new_frames)

    def get_statistics(self) -> LidarStats:
        """获取统计数据（带缓存）"""
        # 先解析新数据
        self.parse_new_frames()

        current_time = datetime.now().timestamp()

        # 检查缓存
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

        # 基本统计
        points = [f.points for f in frames]
        frame_count = len(frames)

        # 计算频率 (基于最近 5 秒的数据)
        # 注意：日志时间戳可能使用设备时间而非系统时间
        # 因此使用日志时间戳之间的相对差值来计算频率
        if len(frames) >= 2:
            # 使用最近 100 帧或所有帧计算频率
            calc_frames = frames[-min(100, len(frames)):]
            duration = calc_frames[-1].start_time - calc_frames[0].start_time
            if duration > 0:
                frequency = (len(calc_frames) - 1) / duration
        else:
            frequency = 0

        # 最后帧的时间差
        # 由于日志时间戳可能使用设备时间而非系统时间，
        # 使用当前时间与最后解析时间的差值作为近似
        time_since_last = current_time - self._cache_time if self._cache_time > 0 else 0

        # 获取最后一帧信息
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

        # 更新缓存
        self._cached_stats = stats
        self._cache_time = current_time

        return stats

    def reset(self):
        """重置统计数据"""
        with self._lock:
            self._frames.clear()
            self._cached_stats = None
            self._last_pos = 0
