# conftest.py - Shared fixtures for ros2_diagnostic tests

import pytest
import os
import sys
import tempfile
import shutil
from pathlib import Path
from typing import Generator, Dict, Any
import logging
import time
from unittest.mock import Mock, patch

# Add parent directory to path for imports
project_root = Path(__file__).parent.parent
sys.path.insert(0, str(project_root))

# Configure test logging
logging.basicConfig(
    level=logging.DEBUG,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)


@pytest.fixture(scope="session")
def project_root_path() -> Path:
    """Get the project root directory"""
    return Path(__file__).parent.parent


@pytest.fixture(scope="session")
def test_config(project_root_path: Path) -> Dict[str, Any]:
    """Get test configuration"""
    return {
        "ROS2_CONFIG": {
            "domain_id": 42,
            "source_cmd": "/opt/ros/humble/setup.bash",
            "workspace": str(project_root_path.parent / "ros2_ws"),
        },
        "ROSBAG_CONFIG": {
            "config_path": str(project_root_path.parent / "config" / "rosbag" / "rosbag_ros2.yaml"),
            "output_folder": "/tmp/test_rosbags",
            "start_service": "start_recording",
            "stop_service": "stop_recording",
            "service_timeout_sec": 5.0,
        },
        "PROJECT_ROOT": str(project_root_path.parent),
    }


@pytest.fixture
def temp_rosbag_dir() -> Generator[Path, None, None]:
    """Create a temporary directory for test rosbag files"""
    temp_dir = Path(tempfile.mkdtemp(prefix="test_rosbags_"))
    yield temp_dir
    # Cleanup
    if temp_dir.exists():
        shutil.rmtree(temp_dir)


@pytest.fixture
def mock_rosbag_config(test_config, temp_rosbag_dir) -> Dict[str, Any]:
    """Create a mocked rosbag configuration with temp directory"""
    config = test_config.copy()
    config["ROSBAG_CONFIG"] = config["ROSBAG_CONFIG"].copy()
    config["ROSBAG_CONFIG"]["output_folder"] = str(temp_rosbag_dir)
    return config


@pytest.fixture
def sample_topics() -> list:
    """Sample topics list for testing"""
    return [
        "/navi_lidar/points",
        "/image_raw",
        "/imu/data",
        "/thruster_status_pwm"
    ]


@pytest.fixture
def sample_status_response(temp_rosbag_dir) -> Dict[str, Any]:
    """Sample status API response"""
    return {
        "success": True,
        "data": {
            "is_recording": False,
            "current_bag": None,
            "duration": None,
            "topics_count": 4,
            "topics": ["/navi_lidar/points", "/image_raw", "/imu/data"],
            "config_loaded": True,
            "pid": None
        }
    }


@pytest.fixture
def sample_start_response(temp_rosbag_dir) -> Dict[str, Any]:
    """Sample start recording API response"""
    return {
        "success": True,
        "message": "Recording started",
        "bag_path": str(temp_rosbag_dir / "rosbag_20250127_123456")
    }


@pytest.fixture
def sample_stop_response() -> Dict[str, Any]:
    """Sample stop recording API response"""
    return {
        "success": True,
        "message": "Recording stopped"
    }


@pytest.fixture
def mock_pgrep_no_process():
    """Mock pgrep when no recording process is running"""
    with patch('subprocess.run') as mock_run:
        mock_result = Mock()
        mock_result.returncode = 1  # No process found
        mock_result.stdout = ""
        mock_run.return_value = mock_result
        yield mock_run


@pytest.fixture
def mock_pgrep_with_process(temp_rosbag_dir):
    """Mock pgrep when recording process is running"""
    with patch('subprocess.run') as mock_run:
        def run_side_effect(cmd, **kwargs):
            mock_result = Mock()
            if 'pgrep' in str(cmd):
                # Simulate running recording process
                mock_result.returncode = 0
                bag_path = temp_rosbag_dir / "rosbag_20250127_123456"
                mock_result.stdout = f"12345 ros2 bag record -o {bag_path} /topic1 /topic2"
            else:
                mock_result.returncode = 0
                mock_result.stdout = "success=True"
            mock_result.stderr = ""
            return mock_result

        with patch('subprocess.run', side_effect=run_side_effect):
            yield


@pytest.fixture
def mock_subprocess_run_success():
    """Mock subprocess.run for successful ROS2 service calls"""
    with patch('subprocess.run') as mock_run:
        mock_result = Mock()
        mock_result.returncode = 0
        mock_result.stdout = "response: tuc_interfaces.srv.StartRecording_Response(success=True, message='Recording started')"
        mock_result.stderr = ""
        mock_run.return_value = mock_result
        yield mock_run


@pytest.fixture(scope="session")
def base_url() -> str:
    """Get base URL for testing"""
    return os.environ.get("TEST_BASE_URL", "http://localhost:5000")


# ROS2 status detection - shared state for all tests
_ros2_running_state = {"running": None, "checked": False}


def check_ros2_status(base_url: str) -> bool:
    """Check if ROS2 system is running via API.

    This function checks the ROS2 control status endpoint to determine
    if the ROS2 system is available for recording tests.

    Returns:
        True if ROS2 is running, False otherwise
    """
    # Return cached result if already checked
    if _ros2_running_state["checked"]:
        return _ros2_running_state["running"]

    try:
        import requests
        response = requests.get(
            f"{base_url}/api/ros2/control/status",
            timeout=5
        )
        if response.status_code == 200:
            data = response.json()
            if data.get('success') and data.get('data', {}).get('running'):
                _ros2_running_state["running"] = True
                _ros2_running_state["checked"] = True
                logger.info("[INFO] ROS2 系统正在运行 ✓")
                return True
    except Exception as e:
        logger.debug(f"ROS2 status check failed: {e}")

    _ros2_running_state["running"] = False
    _ros2_running_state["checked"] = True
    logger.warning("[WARNING] ROS2 系统未运行，录制测试将被跳过")
    return False


@pytest.fixture(scope="session")
def ros2_running(base_url: str) -> bool:
    """Check if ROS2 system is running for recording tests.

    This fixture is session-scoped to avoid repeated checks.
    Tests that require actual recording should use this fixture
    or check_ros2_status() to conditionally skip.

    Example:
        @pytest.mark.skipif(not ros2_running, reason="ROS2 not running")
        def test_actual_recording(ros2_running):
            # Test code that requires ROS2
            ...
    """
    return check_ros2_status(base_url)


# =============================================================================
# Alert System Fixtures
# =============================================================================

@pytest.fixture
def temp_db_path(tmp_path):
    """临时数据库路径 for AlertStore testing"""
    return str(tmp_path / "test_alerts.db")


@pytest.fixture
def fresh_alert_store(temp_db_path):
    """每次测试创建新的 AlertStore 实例

    这个 fixture 会:
    1. 重置单例模块
    2. 创建新的 AlertStore
    3. 使用临时数据库路径
    4. 测试结束后关闭连接
    """
    # 重置 alerts 模块以清除单例
    if 'alerts' in sys.modules:
        del sys.modules['alerts']

    from alerts import AlertStore
    # 重置 AlertStore 单例类变量
    AlertStore._instance = None

    store = AlertStore(db_path=temp_db_path)

    yield store

    # 清理
    store.close()
    # 重置单例以便下次测试
    AlertStore._instance = None


@pytest.fixture
def sample_alert():
    """示例 Alert 对象 - 单个告警"""
    from alerts import Alert
    return Alert(
        id=1,
        sensor="navi_lidar",
        alert_type="frame_loss",
        severity="warning",
        message="Frame loss detected: 6.2 Hz",
        metric_value=6.2,
        threshold=8.0,
        metadata='{"measured_frequency": 6.2, "frame_count": 50}',
        created_at="2026-01-27T10:30:00",
        resolved_at=None,
        status="active"
    )


@pytest.fixture
def sample_alerts():
    """多个示例 Alert 对象

    包含:
    - 1 个 navi_lidar critical 告警 (活动)
    - 1 个 navi_lidar warning 告警 (活动)
    - 1 个 camera critical 告警 (已解决)
    """
    from alerts import Alert
    return [
        Alert(
            id=1,
            sensor="navi_lidar",
            alert_type="frame_loss_critical",
            severity="critical",
            message="Severe frame loss: 3.5 Hz (expected >= 8.0 Hz)",
            metric_value=3.5,
            threshold=8.0,
            metadata='{"measured_frequency": 3.5}',
            created_at="2026-01-27T10:25:00",
            status="active"
        ),
        Alert(
            id=2,
            sensor="navi_lidar",
            alert_type="point_count_low",
            severity="warning",
            message="Point count reduced: 42000 (expected >= 50000)",
            metric_value=42000.0,
            threshold=50000.0,
            metadata='{"avg_points": 42000}',
            created_at="2026-01-27T10:30:00",
            status="active"
        ),
        Alert(
            id=3,
            sensor="camera",
            alert_type="connectivity",
            severity="critical",
            message="Camera unreachable",
            metric_value=0.0,
            threshold=1.0,
            metadata='{}',
            created_at="2026-01-27T10:35:00",
            status="resolved",
            resolved_at="2026-01-27T10:40:00"
        ),
    ]


@pytest.fixture
def mock_navi_lidar_config():
    """模拟 Navi LiDAR 配置 for alert testing"""
    return {
        'SENSOR_THRESHOLDS': {
            'navi_lidar': {
                'min_frequency': 8.0,
                'min_points_per_frame': 50000,
                'max_packet_loss': 1.0,
            }
        },
        'SENSOR_IPS': {
            'navi_lidar': '192.168.0.201'
        },
        'ROS2_TOPICS': {
            'navi_lidar': {
                'points': '/navi_lidar/points'
            }
        },
        'ENABLE_TOPIC_DETAILS': False,
    }


@pytest.fixture
def client(temp_db_path):
    """FastAPI 测试客户端

    为 Alert API 测试提供配置好的 FastAPI 测试客户端
    """
    # 重置模块
    for mod in ['alerts', 'app', 'main']:
        if mod in sys.modules:
            del sys.modules[mod]

    # 导入 alerts 模块并重置单例
    from alerts import AlertStore
    AlertStore._instance = None

    # 导入 main (FastAPI app)
    from main import app

    # 确保 AlertStore 使用临时数据库
    AlertStore._instance = None
    store = AlertStore(db_path=temp_db_path)

    # FastAPI TestClient
    from fastapi.testclient import TestClient
    client = TestClient(app)

    yield client


@pytest.fixture
def mock_ping_success():
    """模拟 ping 成功响应"""
    return {
        'reachable': True,
        'avg_time_ms': 1.5,
        'packet_loss': 0.0,
        'min_time_ms': 1.2,
        'max_time_ms': 1.8
    }


@pytest.fixture
def mock_ping_failure():
    """模拟 ping 失败响应"""
    return {
        'reachable': False,
        'avg_time_ms': None,
        'packet_loss': 100.0,
        'min_time_ms': None,
        'max_time_ms': None
    }
