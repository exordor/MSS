import os

from launch import LaunchDescription
from launch.actions import DeclareLaunchArgument
from launch.substitutions import LaunchConfiguration, PathJoinSubstitution
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
            'compressor.yaml',
        ]),
        description='Absolute path to the sensor_compressor YAML configuration file.'
    )

    input_topic_arg = DeclareLaunchArgument(
        'input_topic',
        default_value='/navi_lidar/points',
        description='Input PointCloud2 topic to downsample.'
    )

    output_topic_arg = DeclareLaunchArgument(
        'output_topic',
        default_value='/points_downsampled',
        description='Output downsampled PointCloud2 topic.'
    )

    compressor_node = Node(
        package='sensor_compressor',
        executable='sensor_compressor',
        name='sensor_downsample_node',
        output='screen',
        parameters=[LaunchConfiguration('config_file')],
        remappings=[
            ('/navi_lidar/points', LaunchConfiguration('input_topic')),
            ('/points_downsampled', LaunchConfiguration('output_topic')),
        ],
        ros_arguments=['--log-level', LaunchConfiguration('log_level')],
    )

    return LaunchDescription([
        log_level_arg,
        config_file_arg,
        input_topic_arg,
        output_topic_arg,
        compressor_node,
    ])
