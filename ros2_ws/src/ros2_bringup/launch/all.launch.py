import os

import yaml

from launch import LaunchDescription
from launch.actions import DeclareLaunchArgument, OpaqueFunction, ExecuteProcess
from launch.substitutions import LaunchConfiguration, PathJoinSubstitution
from launch_ros.actions import Node
from launch_ros.substitutions import FindPackageShare


def generate_launch_description():
    lidar_config = DeclareLaunchArgument(
        'lidar_config',
        default_value=PathJoinSubstitution([
            FindPackageShare('ros2_bringup'),
            'config',
            'qt128.yaml',
        ]),
        description='Absolute path to the Navi LiDAR YAML configuration file.',
    )

    camera_config = DeclareLaunchArgument(
        'camera_config',
        default_value=PathJoinSubstitution([
            FindPackageShare('ros2_bringup'),
            'config',
            'camera.yaml',
        ]),
        description='Absolute path to the galaxy_camera YAML configuration file.',
    )

    imu_config = DeclareLaunchArgument(
        'imu_config',
        default_value=PathJoinSubstitution([
            FindPackageShare('ros2_bringup'),
            'config',
            'sbg.yaml',
        ]),
        description='Absolute path to the SBG device YAML configuration file.',
    )

    thruster_config = DeclareLaunchArgument(
        'thruster_config',
        default_value=PathJoinSubstitution([
            FindPackageShare('ros2_bringup'),
            'config',
            'thruster.yaml',
        ]),
        description='Absolute path to the thruster control YAML configuration file.',
    )

    bag_config = DeclareLaunchArgument(
        'bag_config',
        default_value=PathJoinSubstitution([
            FindPackageShare('ros2_bringup'),
            'config',
            'rosbag.yaml',
        ]),
        description='YAML file that defines rosbag topics/output for the combined bringup.',
    )

    record_bag = DeclareLaunchArgument(
        'record_bag',
        default_value='false',
        description='Set true to record a rosbag alongside bringup.',
    )

    record_topics = DeclareLaunchArgument(
        'record_topics',
        default_value='',
        description='Space-separated topics to record when record_bag is true.',
    )

    bag_output = DeclareLaunchArgument(
        'bag_output',
        default_value='',
        description='Bag output name (passed to ros2 bag record -o). Leave empty to use the YAML setting.',
    )

    lidar_node = Node(
        package='hesai_ros_driver',
        executable='hesai_ros_driver_node',
        name='navi_lidar_driver',
        output='screen',
        parameters=[{'config_path': LaunchConfiguration('lidar_config')}],
    )

    camera_node = Node(
        package='galaxy_camera',
        executable='galaxy_camera',
        name='galaxy_camera',
        output='screen',
        parameters=[LaunchConfiguration('camera_config')],
    )

    imu_node = Node(
        package='sbg_driver',
        executable='sbg_device',
        name='sbg_device',
        output='screen',
        parameters=[LaunchConfiguration('imu_config')],
    )

    thruster_node = Node(
        package='thruster_control',
        executable='thruster_node',
        name='thruster_node',
        output='screen',
        parameters=[LaunchConfiguration('thruster_config')],
    )

    def launch_bag_record(context, *args, **kwargs):
        record_enabled = LaunchConfiguration('record_bag').perform(context).lower() in ('true', '1', 'yes', 'on')
        if not record_enabled:
            return []

        topics_override = LaunchConfiguration('record_topics').perform(context).strip()
        output_override = LaunchConfiguration('bag_output').perform(context).strip()
        bag_config_path = LaunchConfiguration('bag_config').perform(context)

        topics = []
        output_name = ''

        if bag_config_path and os.path.exists(bag_config_path):
            try:
                with open(bag_config_path, 'r') as f:
                    data = yaml.safe_load(f) or {}
                topics = data.get('topics') or []
                output_name = data.get('output', '')
            except Exception as exc:  # pragma: no cover - best effort log
                print(f"[all.launch.py] Failed to load bag config {bag_config_path}: {exc}")
        else:
            print(f"[all.launch.py] Bag config not found: {bag_config_path}")

        if topics_override:
            topics = topics_override.split()
        if output_override:
            output_name = output_override

        if not topics:
            print("[all.launch.py] Recording enabled but no topics specified; rosbag will not start.")
            return []

        output_name = output_name or 'ros2_bringup_all'

        print(f"[all.launch.py] Starting rosbag2 record: output={output_name}, topics={topics}")

        return [ExecuteProcess(
            cmd=['ros2', 'bag', 'record', '-o', output_name, *topics],
            name='rosbag2_record',
            output='screen',
        )]

    return LaunchDescription([
        lidar_config,
        camera_config,
        imu_config,
        thruster_config,
        bag_config,
        record_bag,
        record_topics,
        bag_output,
        lidar_node,
        camera_node,
        imu_node,
        thruster_node,
        OpaqueFunction(function=launch_bag_record),
    ])
