#!/usr/bin/env python3
"""
Nav2 Launch for TinyBot in Hotel World - Federated Architecture
Using slam_toolbox localization mode with pre-built posegraph maps

Launches complete Nav2 stack for a single tinyBot robot.
Robot namespace and parameters are configured via environment variables.

Environment Variables:
  ROBOT_NAME: Robot namespace (e.g., tinyBot_1, tinyBot_2, etc.)
  ROBOT_X: Initial X position
  ROBOT_Y: Initial Y position
  ROBOT_YAW: Initial orientation (radians)
  MAP_LEVEL: Hotel level (L1, L2, or L3)

Usage:
  export ROBOT_NAME=tinyBot_1
  export ROBOT_X=23.5
  export ROBOT_Y=-27.4
  export ROBOT_YAW=0.0
  export MAP_LEVEL=L1
  ros2 launch /opt/nav2_launch/tinybot_nav2_launch.py
"""

import os
import sys
from launch import LaunchDescription
from launch.actions import DeclareLaunchArgument, SetEnvironmentVariable
from launch.substitutions import LaunchConfiguration, EnvironmentVariable
from launch_ros.actions import Node, SetParameter


def generate_launch_description():
    # Get environment variables
    robot_name = os.environ.get('ROBOT_NAME', 'tinyBot_1')
    robot_x = float(os.environ.get('ROBOT_X', '23.5'))
    robot_y = float(os.environ.get('ROBOT_Y', '-27.4'))
    robot_yaw = float(os.environ.get('ROBOT_YAW', '0.0'))
    map_level = os.environ.get('MAP_LEVEL', 'L1')

    # File paths (params file is substituted by entrypoint)
    params_file = f'/tmp/nav2_config/tinybot_nav2_params_{robot_name}.yaml'
    map_yaml_file = f'/opt/maps/hotel_{map_level}.yaml'
    slam_map_file = f'/opt/slam_maps/hotel_{map_level}_map'

    # Validate files exist
    if not os.path.exists(params_file):
        print(f"ERROR: Nav2 params file not found: {params_file}")
        print(f"Looking for file at: {params_file}")
        # Try original path as fallback
        params_file_fallback = '/opt/nav2_config/tinybot_nav2_params.yaml'
        if os.path.exists(params_file_fallback):
            print(f"Using fallback: {params_file_fallback}")
            params_file = params_file_fallback
        else:
            sys.exit(1)

    if not os.path.exists(map_yaml_file):
        print(f"WARNING: Map file not found: {map_yaml_file}")
        print(f"Using default map or SLAM mode")
        map_yaml_file = None

    print(f"==========================================")
    print(f"TinyBot Nav2 Launch Configuration")
    print(f"==========================================")
    print(f"Robot Name: {robot_name}")
    print(f"Initial Pose: ({robot_x}, {robot_y}, {robot_yaw})")
    print(f"Map Level: {map_level}")
    print(f"Map File: {map_yaml_file}")
    print(f"SLAM Map: {slam_map_file}")
    print(f"Params File: {params_file}")
    print(f"==========================================\n")

    # Use simulation time
    use_sim_time = True

    # Build launch description
    ld = LaunchDescription()

    # Set global parameters
    ld.add_action(SetEnvironmentVariable('ROS_LOG_DIR', '/tmp/ros_logs'))
    ld.add_action(SetParameter(name='use_sim_time', value=use_sim_time))

    # Create list of navigation nodes (to be wrapped in GroupAction with namespace)
    nav_nodes = []

    # Map server (if map file exists - used for costmaps)
    if map_yaml_file:
        ld.add_action(Node(
            package='nav2_map_server',
            executable='map_server',
            name='map_server',
            namespace=robot_name,
            output='screen',
            parameters=[{
                'use_sim_time': use_sim_time,
                'yaml_filename': map_yaml_file
            }]
        ))

        # Lifecycle manager for map server
        ld.add_action(Node(
            package='nav2_lifecycle_manager',
            executable='lifecycle_manager',
            name='lifecycle_manager_map',
            namespace=robot_name,
            output='screen',
            parameters=[{
                'use_sim_time': use_sim_time,
                'autostart': True,
                'node_names': ['map_server']
            }]
        ))

    # slam_toolbox localization with pre-built posegraph
    ld.add_action(Node(
        package='slam_toolbox',
        executable='localization_slam_toolbox_node',
        name='slam_toolbox',
        namespace=robot_name,
        output='screen',
        parameters=[{
            'use_sim_time': use_sim_time,
            'odom_frame': f'{robot_name}/odom',
            'map_frame': 'map',
            'base_frame': f'{robot_name}/base_footprint',
            'scan_topic': 'scan',

            # Load pre-built posegraph map
            'map_file_name': slam_map_file,
            'map_start_pose': [robot_x, robot_y, robot_yaw],

            # Localization parameters
            'resolution': 0.05,
            'max_laser_range': 12.0,
            'tf_buffer_duration': 60.0,  # Increased for better TF buffering
            'transform_publish_period': 0.02,
            'transform_timeout': 5.0,  # Increased to allow time for static TF extrapolation
            'minimum_time_interval': 0.5,

            # Scan matching
            'scan_buffer_size': 25,  # Increased buffer for better TF waiting
            'scan_buffer_maximum_scan_distance': 20.0,
            'link_match_minimum_response_fine': 0.1,
            'link_scan_maximum_distance': 1.5,

            # Loop closure (less important for localization)
            'loop_search_maximum_distance': 3.0,
            'do_loop_closing': False,
        }]
    ))

    # Controller server
    ld.add_action(Node(
        package='nav2_controller',
        executable='controller_server',
        name='controller_server',
        namespace=robot_name,
        output='screen',
        parameters=[params_file],
        remappings=[
            ('cmd_vel', f'/{robot_name}/cmd_vel')
        ]
    ))

    # Planner server
    ld.add_action(Node(
        package='nav2_planner',
        executable='planner_server',
        name='planner_server',
        namespace=robot_name,
        output='screen',
        parameters=[params_file]
    ))

    # Smoother server
    ld.add_action(Node(
        package='nav2_smoother',
        executable='smoother_server',
        name='smoother_server',
        namespace=robot_name,
        output='screen',
        parameters=[params_file]
    ))

    # Behavior server
    ld.add_action(Node(
        package='nav2_behaviors',
        executable='behavior_server',
        name='behavior_server',
        namespace=robot_name,
        output='screen',
        parameters=[params_file]
    ))

    # BT Navigator
    ld.add_action(Node(
        package='nav2_bt_navigator',
        executable='bt_navigator',
        name='bt_navigator',
        namespace=robot_name,
        output='screen',
        parameters=[params_file]
    ))

    # Waypoint follower
    ld.add_action(Node(
        package='nav2_waypoint_follower',
        executable='waypoint_follower',
        name='waypoint_follower',
        namespace=robot_name,
        output='screen',
        parameters=[params_file]
    ))

    # Velocity smoother
    ld.add_action(Node(
        package='nav2_velocity_smoother',
        executable='velocity_smoother',
        name='velocity_smoother',
        namespace=robot_name,
        output='screen',
        parameters=[params_file],
        remappings=[
            ('cmd_vel', 'cmd_vel_nav'),
            ('cmd_vel_smoothed', f'/{robot_name}/cmd_vel')
        ]
    ))

    # Collision monitor
    ld.add_action(Node(
        package='nav2_collision_monitor',
        executable='collision_monitor',
        name='collision_monitor',
        namespace=robot_name,
        output='screen',
        parameters=[params_file]
    ))

    # Lifecycle manager for navigation nodes
    ld.add_action(Node(
        package='nav2_lifecycle_manager',
        executable='lifecycle_manager',
        name='lifecycle_manager_navigation',
        namespace=robot_name,
        output='screen',
        parameters=[{
            'use_sim_time': use_sim_time,
            'autostart': True,
            'node_names': [
                'controller_server',
                'planner_server',
                'smoother_server',
                'behavior_server',
                'bt_navigator',
                'waypoint_follower',
                'velocity_smoother',
                'collision_monitor'
            ]
        }]
    ))

    # Lifecycle manager for localization
    ld.add_action(Node(
        package='nav2_lifecycle_manager',
        executable='lifecycle_manager',
        name='lifecycle_manager_localization',
        namespace=robot_name,
        output='screen',
        parameters=[{
            'use_sim_time': use_sim_time,
            'autostart': True,
            'node_names': ['slam_toolbox']
        }]
    ))

    return ld


if __name__ == '__main__':
    generate_launch_description()
