# test_ros2_control_config.py - Unit tests for ROS2 control configuration

import pytest


@pytest.mark.unit
class TestROS2ControlConfig:
    """Tests for ROS2 control configuration"""

    def test_ros2_control_script_defaults_to_no_auto_record(self):
        """Verify default script does not auto-record"""
        from config import ROS2_CONTROL

        script_path = ROS2_CONTROL['script_path']
        assert 'run_ros2_all.sh' in script_path, f"Expected run_ros2_all.sh in script_path, got: {script_path}"
        assert 'record.sh' not in script_path, f"Script should not be record.sh, got: {script_path}"

    def test_ros2_control_script_path_exists(self):
        """Verify the configured script path exists"""
        from config import ROS2_CONTROL
        import os

        script_path = ROS2_CONTROL['script_path']
        assert os.path.exists(script_path), f"Script path does not exist: {script_path}"

    def test_ros2_control_has_required_fields(self):
        """Verify ROS2_CONTROL has all required fields"""
        from config import ROS2_CONTROL

        required_fields = ['script_path', 'repo_root', 'log_file', 'domain_id']
        for field in required_fields:
            assert field in ROS2_CONTROL, f"Missing required field: {field}"

    def test_ros2_control_domain_id_is_string(self):
        """Verify domain_id is a string (not int) for environment variables"""
        from config import ROS2_CONTROL

        domain_id = ROS2_CONTROL['domain_id']
        assert isinstance(domain_id, str), f"domain_id should be string, got {type(domain_id)}"

    def test_ros2_launch_script_uses_no_auto_record(self):
        """Verify launch_script does not force recording"""
        from config import ROS2_CONFIG

        launch_script = ROS2_CONFIG['launch_script']
        assert 'run_ros2_all.sh' in launch_script
        assert 'record.sh' not in launch_script
