import os

from launch import LaunchDescription
from launch.actions import DeclareLaunchArgument
from launch.substitutions import LaunchConfiguration, PathJoinSubstitution, TextSubstitution
from launch_ros.actions import Node
from launch_ros.substitutions import FindPackageShare


def generate_launch_description():
    log_level_arg = DeclareLaunchArgument(
        'log_level',
        default_value=os.environ.get('ROS_LOG_LEVEL', 'info'),
        description='ROS 2 log level (e.g. debug, info, warn, error, fatal).'
    )
    config_file_arg = DeclareLaunchArgument(
        'config_file',
        default_value=PathJoinSubstitution([
            FindPackageShare('ros2_bringup'),
            'config',
            'sbg.yaml',
        ]),
        description='Absolute path to the SBG device YAML config file.'
    )

    sbg_node = Node(
        package='sbg_driver',
        executable='sbg_device',
        name='sbg_device',
        output='screen',
        parameters=[LaunchConfiguration('config_file')],
        ros_arguments=['--log-level', LaunchConfiguration('log_level')],
    )

    return LaunchDescription([
        log_level_arg,
        config_file_arg,
        sbg_node,
    ])
