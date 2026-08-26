#!/usr/bin/env python3
"""
Nav2 Launch for robot_2 (tinyBot_1) in Hotel Demo
Launches Nav2 stack with hotel L1 map
"""

import os
import sys
from launch import LaunchDescription
from launch.actions import DeclareLaunchArgument, SetEnvironmentVariable
from launch.substitutions import LaunchConfiguration
from launch_ros.actions import Node
from ament_index_python.packages import get_package_share_directory


def generate_launch_description():
    # Parameters
    use_sim_time = True
    params_file = '/opt/nav2_config/nav2_params_robot2.yaml'
    map_yaml_file = '/tmp/hotel_L1_map.yaml'

    # Check if map exists
    if not os.path.exists(map_yaml_file):
        print(f"ERROR: Map file not found: {map_yaml_file}")
        print("Please run: python3 /opt/nav2_scripts/map_gen_container.py")
        sys.exit(1)

    # Check if params exist
    if not os.path.exists(params_file):
        print(f"ERROR: Params file not found: {params_file}")
        sys.exit(1)

    return LaunchDescription([
        # Set use_sim_time for all nodes
        SetEnvironmentVariable('ROS_LOG_DIR', '/tmp/ros_logs'),

        # Map server
        Node(
            package='nav2_map_server',
            executable='map_server',
            name='map_server',
            output='screen',
            parameters=[{
                'use_sim_time': use_sim_time,
                'yaml_filename': map_yaml_file
            }]
        ),

        # AMCL
        Node(
            package='nav2_amcl',
            executable='amcl',
            name='amcl',
            output='screen',
            parameters=[params_file]
        ),

        # Controller server
        Node(
            package='nav2_controller',
            executable='controller_server',
            name='controller_server',
            output='screen',
            parameters=[params_file]
        ),

        # Planner server
        Node(
            package='nav2_planner',
            executable='planner_server',
            name='planner_server',
            output='screen',
            parameters=[params_file]
        ),

        # Behavior server
        Node(
            package='nav2_behaviors',
            executable='behavior_server',
            name='behavior_server',
            output='screen',
            parameters=[params_file]
        ),

        # BT Navigator
        Node(
            package='nav2_bt_navigator',
            executable='bt_navigator',
            name='bt_navigator',
            output='screen',
            parameters=[params_file]
        ),

        # Lifecycle manager
        Node(
            package='nav2_lifecycle_manager',
            executable='lifecycle_manager',
            name='lifecycle_manager_navigation',
            output='screen',
            parameters=[{
                'use_sim_time': use_sim_time,
                'autostart': True,
                'node_names': [
                    'map_server',
                    'amcl',
                    'controller_server',
                    'planner_server',
                    'behavior_server',
                    'bt_navigator'
                ]
            }]
        )
    ])


if __name__ == '__main__':
    generate_launch_description()
