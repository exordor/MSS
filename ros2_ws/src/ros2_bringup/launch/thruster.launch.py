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
            'thruster_wifi.yaml',
        ]),
        description='Absolute path to the thruster control YAML configuration file.'
    )

    thruster_node = Node(
        package='thruster_control',
        executable='thruster_wifi_node',
        name='thruster_wifi_node',
        output='screen',
        parameters=[LaunchConfiguration('config_file')],
    )

    return LaunchDescription([
        config_file_arg,
        thruster_node,
    ])
