#!/usr/bin/env python3
"""
NaviLiDAR 告警触发测试

测试 NaviLidarDiagnostic 的告警记录功能:
- 丢帧告警 (critical 和 warning)
- 点数降低告警 (critical 和 warning)
- 告警冷却机制
- 正常情况不触发告警
"""

import pytest
import time
import json
from unittest.mock import Mock, patch, MagicMock
from datetime import datetime
from pathlib import Path

import sys
sys.path.insert(0, str(Path(__file__).parent.parent))


class TestNaviLidarAlertTriggering:
    """Navi LiDAR 告警触发逻辑测试"""

    @pytest.fixture
    def diagnostic(self, mock_navi_lidar_config, temp_db_path):
        """创建 NaviLidarDiagnostic 实例"""
        # 重置模块
        if 'alerts' in sys.modules:
            del sys.modules['alerts']

        # 导入并配置 AlertStore 使用临时数据库
        from alerts import AlertStore
        AlertStore._instance = None

        # 创建 store 并确保其初始化
        store = AlertStore(db_path=temp_db_path)

        from diagnostics.sensor_monitor.navi_lidar import NaviLidarDiagnostic
        diag = NaviLidarDiagnostic(mock_navi_lidar_config)
        return diag

    @patch('diagnostics.sensor_monitor.navi_lidar.ping_host')
    def test_frame_loss_critical_alert(self, mock_ping, diagnostic):
        """测试严重丢帧触发 critical 告警

        当频率 < min_frequency * 0.5 时应触发 critical 告警
        """
        mock_ping.return_value = {'reachable': True, 'avg_time_ms': 1.5, 'packet_loss': 0}

        # 模拟低频率统计数据 (3.5 < 8.0 * 0.5 = 4.0)
        with patch.object(diagnostic, '_log_parser') as mock_parser:
            mock_parser.get_statistics.return_value = Mock(
                frequency=3.5,
                avg_points=115200,
                frame_count=100,
                min_points=115000,
                max_points=120000,
                last_frame_num=99,
                last_timestamp=1602248443.595332,
                time_since_last_frame=0.1
            )

            # 模拟 ROS2 系统运行
            with patch.object(diagnostic, '_get_ros2_monitor') as mock_monitor_getter:
                mock_monitor = Mock()
                mock_monitor.is_system_running = Mock(return_value=True)
                with patch.object(diagnostic, '_ros2_monitor', mock_monitor):

                    with patch('diagnostics.sensor_monitor.navi_lidar.get_ros2_helper') as mock_ros2:
                        mock_helper = Mock()
                        mock_helper.get_node_names.return_value = ['navi_lidar_driver']
                        mock_helper.get_topic_names.return_value = ['/navi_lidar/points']
                        mock_ros2.return_value = mock_helper

                        # 执行诊断检查
                        result = diagnostic.check()

        # 验证诊断结果
        from diagnostics.base import StatusLevel
        assert result.status == StatusLevel.CRITICAL

        # 验证告警被记录
        from alerts import get_alert_store
        store = get_alert_store()
        alerts = store.get_active_alerts(sensor='navi_lidar')

        critical_alerts = [a for a in alerts if 'frame_loss_critical' in a.alert_type]
        assert len(critical_alerts) > 0
        assert critical_alerts[0].severity == 'critical'
        assert '3.5' in critical_alerts[0].message

    @patch('diagnostics.sensor_monitor.navi_lidar.ping_host')
    def test_frame_loss_warning_alert(self, mock_ping, diagnostic):
        """测试丢帧触发 warning 告警

        当频率 < min_frequency 但 >= min_frequency * 0.5 时应触发 warning 告警
        """
        mock_ping.return_value = {'reachable': True, 'avg_time_ms': 1.5, 'packet_loss': 0}

        # 模拟中低频率统计数据 (6.5 < 8.0, but >= 4.0)
        with patch.object(diagnostic, '_log_parser') as mock_parser:
            mock_parser.get_statistics.return_value = Mock(
                frequency=6.5,
                avg_points=115200,
                frame_count=100,
                min_points=115000,
                max_points=120000,
                last_frame_num=99,
                last_timestamp=1602248443.595332,
                time_since_last_frame=0.1
            )

            with patch.object(diagnostic, '_get_ros2_monitor') as mock_monitor_getter:
                mock_monitor = Mock()
                mock_monitor.is_system_running = Mock(return_value=True)
                with patch.object(diagnostic, '_ros2_monitor', mock_monitor):

                    with patch('diagnostics.sensor_monitor.navi_lidar.get_ros2_helper') as mock_ros2:
                        mock_helper = Mock()
                        mock_helper.get_node_names.return_value = ['navi_lidar_driver']
                        mock_helper.get_topic_names.return_value = ['/navi_lidar/points']
                        mock_ros2.return_value = mock_helper

                        result = diagnostic.check()

        # 验证诊断结果
        from diagnostics.base import StatusLevel
        assert result.status == StatusLevel.WARNING

        # 验证告警
        from alerts import get_alert_store
        store = get_alert_store()
        alerts = store.get_active_alerts(sensor='navi_lidar')

        warning_alerts = [a for a in alerts if a.alert_type == 'frame_loss']
        assert len(warning_alerts) > 0
        assert warning_alerts[0].severity == 'warning'
        assert '6.5' in warning_alerts[0].message

    @patch('diagnostics.sensor_monitor.navi_lidar.ping_host')
    def test_point_count_critical_alert(self, mock_ping, diagnostic):
        """测试点数严重不足触发 critical 告警

        当点数 < min_points * 0.5 时应触发 critical 告警
        """
        mock_ping.return_value = {'reachable': True, 'avg_time_ms': 1.5, 'packet_loss': 0}

        # 模拟极低点数 (20000 < 50000 * 0.5 = 25000)
        with patch.object(diagnostic, '_log_parser') as mock_parser:
            mock_parser.get_statistics.return_value = Mock(
                frequency=10.0,  # 正常频率
                avg_points=20000,  # 严重不足
                frame_count=100,
                min_points=18000,
                max_points=22000,
                last_frame_num=99,
                last_timestamp=1602248443.595332,
                time_since_last_frame=0.1
            )

            with patch.object(diagnostic, '_get_ros2_monitor') as mock_monitor_getter:
                mock_monitor = Mock()
                mock_monitor.is_system_running = Mock(return_value=True)
                with patch.object(diagnostic, '_ros2_monitor', mock_monitor):

                    with patch('diagnostics.sensor_monitor.navi_lidar.get_ros2_helper') as mock_ros2:
                        mock_helper = Mock()
                        mock_helper.get_node_names.return_value = ['navi_lidar_driver']
                        mock_helper.get_topic_names.return_value = ['/navi_lidar/points']
                        mock_ros2.return_value = mock_helper

                        result = diagnostic.check()

        # 验证告警
        from alerts import get_alert_store
        store = get_alert_store()
        alerts = store.get_active_alerts(sensor='navi_lidar')

        critical_alerts = [a for a in alerts if 'point_count_critical' in a.alert_type]
        assert len(critical_alerts) > 0
        assert critical_alerts[0].severity == 'critical'
        assert '20000' in critical_alerts[0].message

    @patch('diagnostics.sensor_monitor.navi_lidar.ping_host')
    def test_point_count_warning_alert(self, mock_ping, diagnostic):
        """测试点数降低触发 warning 告警

        当点数 < min_points 但 >= min_points * 0.5 时应触发 warning 告警
        """
        mock_ping.return_value = {'reachable': True, 'avg_time_ms': 1.5, 'packet_loss': 0}

        # 模拟偏低点数 (42000 < 50000, but >= 25000)
        with patch.object(diagnostic, '_log_parser') as mock_parser:
            mock_parser.get_statistics.return_value = Mock(
                frequency=10.0,
                avg_points=42000,
                frame_count=100,
                min_points=40000,
                max_points=44000,
                last_frame_num=99,
                last_timestamp=1602248443.595332,
                time_since_last_frame=0.1
            )

            with patch.object(diagnostic, '_get_ros2_monitor') as mock_monitor_getter:
                mock_monitor = Mock()
                mock_monitor.is_system_running = Mock(return_value=True)
                with patch.object(diagnostic, '_ros2_monitor', mock_monitor):

                    with patch('diagnostics.sensor_monitor.navi_lidar.get_ros2_helper') as mock_ros2:
                        mock_helper = Mock()
                        mock_helper.get_node_names.return_value = ['navi_lidar_driver']
                        mock_helper.get_topic_names.return_value = ['/navi_lidar/points']
                        mock_ros2.return_value = mock_helper

                        result = diagnostic.check()

        # 验证告警
        from alerts import get_alert_store
        store = get_alert_store()
        alerts = store.get_active_alerts(sensor='navi_lidar')

        warning_alerts = [a for a in alerts if a.alert_type == 'point_count_low']
        assert len(warning_alerts) > 0
        assert warning_alerts[0].severity == 'warning'

    @patch('diagnostics.sensor_monitor.navi_lidar.ping_host')
    def test_no_alert_when_normal(self, mock_ping, diagnostic):
        """测试正常情况不触发告警"""
        mock_ping.return_value = {'reachable': True, 'avg_time_ms': 1.5, 'packet_loss': 0}

        # 模拟正常统计数据
        with patch.object(diagnostic, '_log_parser') as mock_parser:
            mock_parser.get_statistics.return_value = Mock(
                frequency=10.0,  # 正常 (>= 8.0)
                avg_points=115200,  # 正常 (>= 50000)
                frame_count=100,
                min_points=110000,
                max_points=120000,
                last_frame_num=99,
                last_timestamp=1602248443.595332,
                time_since_last_frame=0.1
            )

            with patch.object(diagnostic, '_get_ros2_monitor') as mock_monitor_getter:
                mock_monitor = Mock()
                mock_monitor.is_system_running = Mock(return_value=True)
                with patch.object(diagnostic, '_ros2_monitor', mock_monitor):

                    with patch('diagnostics.sensor_monitor.navi_lidar.get_ros2_helper') as mock_ros2:
                        mock_helper = Mock()
                        mock_helper.get_node_names.return_value = ['navi_lidar_driver']
                        mock_helper.get_topic_names.return_value = ['/navi_lidar/points']
                        mock_ros2.return_value = mock_helper

                        result = diagnostic.check()

        # 验证状态正常
        from diagnostics.base import StatusLevel
        assert result.status == StatusLevel.OK

        # 验证没有告警
        from alerts import get_alert_store
        store = get_alert_store()
        alerts = store.get_active_alerts(sensor='navi_lidar')
        assert len(alerts) == 0

    @patch('diagnostics.sensor_monitor.navi_lidar.ping_host')
    def test_alert_cooldown(self, mock_ping, diagnostic):
        """测试告警冷却机制 - 避免重复告警

        连续两次检查相同问题应该只记录一次告警（在冷却期内）
        """
        mock_ping.return_value = {'reachable': True, 'avg_time_ms': 1.5, 'packet_loss': 0}

        with patch.object(diagnostic, '_log_parser') as mock_parser:
            mock_parser.get_statistics.return_value = Mock(
                frequency=3.5,  # Critical
                avg_points=115200,
                frame_count=100,
                min_points=115000,
                max_points=120000,
                last_frame_num=99,
                last_timestamp=1602248443.595332,
                time_since_last_frame=0.1
            )

            with patch.object(diagnostic, '_get_ros2_monitor') as mock_monitor_getter:
                mock_monitor = Mock()
                mock_monitor.is_system_running = Mock(return_value=True)
                with patch.object(diagnostic, '_ros2_monitor', mock_monitor):

                    with patch('diagnostics.sensor_monitor.navi_lidar.get_ros2_helper') as mock_ros2:
                        mock_helper = Mock()
                        mock_helper.get_node_names.return_value = ['navi_lidar_driver']
                        mock_helper.get_topic_names.return_value = ['/navi_lidar/points']
                        mock_ros2.return_value = mock_helper

                        # 第一次检查
                        diagnostic.check()

                        from alerts import get_alert_store
                        store = get_alert_store()
                        alerts_after_first = store.get_active_alerts(sensor='navi_lidar')
                        first_count = len(alerts_after_first)

                        # 立即第二次检查（在冷却期内）
                        diagnostic.check()
                        alerts_after_second = store.get_active_alerts(sensor='navi_lidar')
                        second_count = len(alerts_after_second)

                        # 告警数量不应该增加（由于冷却机制）
                        assert second_count == first_count

    @patch('diagnostics.sensor_monitor.navi_lidar.ping_host')
    def test_combined_critical_alerts(self, mock_ping, diagnostic):
        """测试同时触发多个 critical 告警"""
        mock_ping.return_value = {'reachable': True, 'avg_time_ms': 1.5, 'packet_loss': 0}

        # 模拟同时有丢帧和点数不足
        with patch.object(diagnostic, '_log_parser') as mock_parser:
            mock_parser.get_statistics.return_value = Mock(
                frequency=3.5,  # Critical
                avg_points=20000,  # Critical
                frame_count=100,
                min_points=18000,
                max_points=22000,
                last_frame_num=99,
                last_timestamp=1602248443.595332,
                time_since_last_frame=0.1
            )

            with patch.object(diagnostic, '_get_ros2_monitor') as mock_monitor_getter:
                mock_monitor = Mock()
                mock_monitor.is_system_running = Mock(return_value=True)
                with patch.object(diagnostic, '_ros2_monitor', mock_monitor):

                    with patch('diagnostics.sensor_monitor.navi_lidar.get_ros2_helper') as mock_ros2:
                        mock_helper = Mock()
                        mock_helper.get_node_names.return_value = ['navi_lidar_driver']
                        mock_helper.get_topic_names.return_value = ['/navi_lidar/points']
                        mock_ros2.return_value = mock_helper

                        result = diagnostic.check()

        # 验证状态
        from diagnostics.base import StatusLevel
        assert result.status == StatusLevel.CRITICAL

        # 验证两个告警都被记录
        from alerts import get_alert_store
        store = get_alert_store()
        alerts = store.get_active_alerts(sensor='navi_lidar')

        assert len(alerts) >= 2  # 可能同时有两个告警


class TestNaviLidarAlertMetadata:
    """测试告警元数据正确性"""

    @pytest.fixture
    def diagnostic(self, mock_navi_lidar_config, temp_db_path):
        # 重置模块
        if 'alerts' in sys.modules:
            del sys.modules['alerts']

        # 导入并配置 AlertStore 使用临时数据库
        from alerts import AlertStore
        AlertStore._instance = None

        # 创建 store 并确保其初始化
        store = AlertStore(db_path=temp_db_path)

        from diagnostics.sensor_monitor.navi_lidar import NaviLidarDiagnostic
        return NaviLidarDiagnostic(mock_navi_lidar_config)

    @patch('diagnostics.sensor_monitor.navi_lidar.ping_host')
    def test_alert_metadata_contains_stats(self, mock_ping, diagnostic):
        """测试告警 metadata 包含完整统计信息"""
        mock_ping.return_value = {'reachable': True, 'avg_time_ms': 1.5, 'packet_loss': 0}

        with patch.object(diagnostic, '_log_parser') as mock_parser:
            mock_parser.get_statistics.return_value = Mock(
                frequency=3.5,
                avg_points=115200,
                frame_count=100,
                min_points=115000,
                max_points=120000,
                last_frame_num=99,
                last_timestamp=1602248443.595332,
                time_since_last_frame=0.1
            )

            with patch.object(diagnostic, '_get_ros2_monitor') as mock_monitor_getter:
                mock_monitor = Mock()
                mock_monitor.is_system_running = Mock(return_value=True)
                with patch.object(diagnostic, '_ros2_monitor', mock_monitor):

                    with patch('diagnostics.sensor_monitor.navi_lidar.get_ros2_helper') as mock_ros2:
                        mock_helper = Mock()
                        mock_helper.get_node_names.return_value = ['navi_lidar_driver']
                        mock_helper.get_topic_names.return_value = ['/navi_lidar/points']
                        mock_ros2.return_value = mock_helper

                        diagnostic.check()

        # 验证 metadata 包含正确信息
        from alerts import get_alert_store
        store = get_alert_store()
        alerts = store.get_active_alerts(sensor='navi_lidar')

        assert len(alerts) > 0

        # 解析并验证 metadata
        alert = alerts[0]
        metadata = json.loads(alert.metadata)

        assert 'measured_frequency' in metadata
        assert metadata['measured_frequency'] == 3.5
        assert 'frame_count' in metadata
        assert 'avg_points' in metadata
