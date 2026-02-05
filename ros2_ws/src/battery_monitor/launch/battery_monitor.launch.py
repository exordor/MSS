#!/usr/bin/env python3

"""
Launch file for Battery Monitor Node

Battery voltage monitoring using ADS1115 ADC on I2C bus.
"""

from launch import LaunchDescription
from launch.actions import DeclareLaunchArgument
from launch.substitutions import LaunchConfiguration, PathJoinSubstitution
from launch_ros.actions import Node
from launch_ros.substitutions import FindPackageShare


def generate_launch_description():
    """Generate launch description for battery monitor node."""

    # Declare launch arguments
    config_arg = DeclareLaunchArgument(
        'config_file',
        default_value=PathJoinSubstitution([
            FindPackageShare('battery_monitor'),
            'config',
            'battery_monitor.yaml'
        ]),
        description='Path to the battery monitor configuration file'
    )

    log_level_arg = DeclareLaunchArgument(
        'log_level',
        default_value='info',
        description='Log level (debug, info, warn, error, fatal)'
    )

    # Battery monitor node
    battery_monitor_node = Node(
        package='battery_monitor',
        executable='battery_monitor_node',
        name='battery_monitor',
        output='screen',
        parameters=[LaunchConfiguration('config_file')],
        ros_arguments=[
            '--log-level',
            LaunchConfiguration('log_level')
        ],
    )

    return LaunchDescription([
        config_arg,
        log_level_arg,
        battery_monitor_node,
    ])
