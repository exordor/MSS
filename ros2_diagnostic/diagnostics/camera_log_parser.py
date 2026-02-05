#!/usr/bin/env python3
"""
Camera Log Parser
从 Galaxy Camera 日志文件中解析统计数据
"""

import re
import threading
from collections import deque
from datetime import datetime
from typing import Optional
from dataclasses import dataclass
from pathlib import Path


# 日志行正则表达式 - 匹配 BOTTLENECK ANALYSIS REPORT
# 格式示例:
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

# 单行帧状态模式 (用于更频繁的统计)
# Frame 1 status=SUCCESS(0) ts=10155814645808 bytes=12288000/12288000
FRAME_PATTERN = re.compile(
    r'Frame (\d+) status=(\w+)\((\d+)\) ts=([\d.]+) bytes=(\d+)/(\d+)'
)


@dataclass
class ReportData:
    """BOTTLENECK ANALYSIS REPORT 数据"""
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
    """Camera 统计数据"""
    frame_count: int           # 总帧数 (从 REPORT 累计)
    published_count: int       # 成功发布帧数
    incomplete_count: int      # SDK 不完整帧数 (丢帧)
    queue_dropped: int         # 队列丢帧数
    frequency: float           # 测量帧率 (Hz)
    avg_callback_ms: float     # 平均回调耗时
    avg_processing_ms: float   # 平均处理耗时
    rx_errors: int             # 网络接收错误
    rx_dropped: int            # 网络丢包
    last_report_time: Optional[float]  # 最后报告时间戳
    time_since_last_report: float      # 距离最后报告的时间 (秒)


class CameraLogParser:
    """从日志文件解析 Camera 数据

    线程安全的日志解析器，用于从 galaxy_camera 日志中提取：
    - 帧率和丢帧统计
    - 网络错误和丢包
    - 处理延迟 (callback, processing thread)
    """

    def __init__(self,
                 log_file: str = None,
                 max_history: int = 30):
        """
        Args:
            log_file: 日志文件路径 (None 则自动查找)
            max_history: 保存多少个 REPORT 的历史
        """
        self.log_file = log_file
        self.max_history = max_history

        # 解析缓存
        self._reports: deque = deque(maxlen=max_history)
        self._last_pos = 0  # 上次读取位置
        self._lock = threading.Lock()

        # 统计缓存
        self._cached_stats: Optional[CameraStats] = None
        self._cache_time: float = 0
        self._cache_ttl: float = 0.5  # 缓存 0.5 秒

        # 累计统计 (用于计算频率)
        self._total_frames_seen = 0
        self._first_report_time: Optional[float] = None

    def _find_log_file(self) -> Optional[str]:
        """查找 camera 日志文件

        优先级：
        1. galaxy_camera.log (由 logging.sh 提取)
        2. 00_master.log (原始主日志)

        日志目录结构: logs/YYYYMMDD_HHMMSS/app/galaxy_camera.log
        """
        logs_dir = Path("logs")
        if not logs_dir.exists():
            return None

        # 查找最新的 galaxy_camera.log (在 app 子目录)
        camera_logs = list(logs_dir.glob("*/app/galaxy_camera.log"))
        if camera_logs:
            return str(max(camera_logs, key=lambda p: p.stat().st_mtime))

        # 回退到 00_master.log
        master_logs = list(logs_dir.glob("*/app/00_master.log"))
        if master_logs:
            return str(max(master_logs, key=lambda p: p.stat().st_mtime))

        return None

    def _read_new_lines(self) -> list:
        """读取日志文件中的新增行"""
        log_path = self.log_file or self._find_log_file()
        if not log_path:
            return []

        try:
            with open(log_path, 'r', encoding='utf-8', errors='ignore') as f:
                # 从上次位置继续读取
                f.seek(self._last_pos)
                new_lines = f.readlines()
                self._last_pos = f.tell()
                return new_lines
        except (FileNotFoundError, IOError):
            return []

    def _extract_timestamp(self, line: str) -> Optional[float]:
        """从日志行提取时间戳

        格式: [1769539045.416759136] [INFO] [galaxy_camera] ...
        返回: Unix 时间戳 (秒.纳秒)
        """
        match = re.search(r'\[(\d+)\.(\d+)\]', line)
        if match:
            seconds = int(match.group(1))
            nanos = int(match.group(2))
            return seconds + nanos / 1e9
        return None

    def parse_new_reports(self) -> int:
        """解析新增的 REPORT 数据，返回新增报告数"""
        new_lines = self._read_new_lines()
        new_reports = []

        # 将多行日志合并用于匹配 REPORT
        log_text = ''.join(new_lines)

        # 查找所有 REPORT
        for match in REPORT_PATTERN.finditer(log_text):
            # 提取时间戳 (从匹配位置往前找)
            start_pos = match.start()
            # 往前找包含时间戳的行
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
            # 清除缓存，因为数据更新了
            self._cached_stats = None

            # 更新累计统计
            for report in new_reports:
                if self._first_report_time is None:
                    self._first_report_time = report.timestamp
                self._total_frames_seen += report.total_frames

        return len(new_reports)

    def get_statistics(self) -> CameraStats:
        """获取统计数据（带缓存）"""
        # 先解析新数据
        self.parse_new_reports()

        current_time = datetime.now().timestamp()

        # 检查缓存
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

        # 使用最新的报告
        latest = reports[-1]

        # 计算频率 (基于所有报告)
        if len(reports) >= 2 and self._first_report_time:
            duration = latest.timestamp - self._first_report_time
            if duration > 0:
                frequency = self._total_frames_seen / duration
            else:
                frequency = 0
        else:
            frequency = 0

        # 时间差
        time_since_last = current_time - latest.timestamp

        # 平均值 (使用最近 10 个报告)
        recent_reports = reports[-min(10, len(reports)):]
        avg_callback = sum(r.avg_callback_ms for r in recent_reports) / len(recent_reports)
        avg_processing = sum(r.avg_processing_ms for r in recent_reports) / len(recent_reports)

        stats = CameraStats(
            frame_count=latest.total_frames,
            published_count=latest.published_frames,
            incomplete_count=latest.incomplete_frames,
            queue_dropped=0,  # 需要单独解析队列丢帧日志
            frequency=frequency,
            avg_callback_ms=avg_callback,
            avg_processing_ms=avg_processing,
            rx_errors=latest.rx_errors,
            rx_dropped=latest.rx_dropped,
            last_report_time=latest.timestamp,
            time_since_last_report=time_since_last
        )

        # 更新缓存
        self._cached_stats = stats
        self._cache_time = current_time

        return stats

    def reset(self):
        """重置统计数据"""
        with self._lock:
            self._reports.clear()
            self._cached_stats = None
            self._last_pos = 0
            self._total_frames_seen = 0
            self._first_report_time = None


# 便捷函数
def parse_camera_log(log_file: str = None) -> CameraStats:
    """解析 camera 日志并返回统计

    Args:
        log_file: 日志文件路径 (None 则自动查找最新)

    Returns:
        CameraStats: 统计数据
    """
    parser = CameraLogParser(log_file=log_file)
    return parser.get_statistics()
