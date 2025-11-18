from launch import LaunchDescription
from launch.actions import DeclareLaunchArgument
from launch.substitutions import LaunchConfiguration, PathJoinSubstitution
from launch_ros.actions import Node
from launch_ros.substitutions import FindPackageShare


def generate_launch_description():
    config_arg = DeclareLaunchArgument(
        'config',
        default_value=PathJoinSubstitution([
            FindPackageShare('ros2_bringup'),
            'config',
            'qt128.yaml',
        ]),
        description='Absolute path to the Navi LiDAR YAML configuration file.'
    )

    lidar_node = Node(
        package='hesai_ros_driver',
        executable='hesai_ros_driver_node',
        name='navi_lidar_driver',
        output='screen',
        parameters=[{'config_path': LaunchConfiguration('config')}]
    )

    return LaunchDescription([
        config_arg,
        lidar_node,
    ])
