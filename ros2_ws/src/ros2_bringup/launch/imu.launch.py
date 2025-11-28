from launch import LaunchDescription
from launch.actions import DeclareLaunchArgument
from launch.substitutions import LaunchConfiguration, PathJoinSubstitution
from launch_ros.actions import Node
from launch_ros.substitutions import FindPackageShare


def generate_launch_description():
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
    )

    return LaunchDescription([
        config_file_arg,
        sbg_node,
    ])
