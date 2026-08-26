#!/usr/bin/env python3
"""
Minimal Nav2 Launch - No collision monitor, just essential navigation
"""

from launch import LaunchDescription
from launch_ros.actions import Node
from launch.actions import DeclareLaunchArgument
from launch.substitutions import LaunchConfiguration

def generate_launch_description():
    # Parameters
    params_file = LaunchConfiguration('params_file', default='/opt/nav2_config/nav2_params_robot2.yaml')
    use_sim_time = LaunchConfiguration('use_sim_time', default='True')

    return LaunchDescription([
        # Map server
        Node(
            package='nav2_map_server',
            executable='map_server',
            name='map_server',
            parameters=[{
                'use_sim_time': use_sim_time,
                'yaml_filename': '/tmp/hotel_L1_map.yaml'
            }]
        ),

        # AMCL
        Node(
            package='nav2_amcl',
            executable='amcl',
            name='amcl',
            parameters=[params_file]
        ),

        # Controller
        Node(
            package='nav2_controller',
            executable='controller_server',
            name='controller_server',
            parameters=[params_file],
            remappings=[('/cmd_vel', '/robot_2/cmd_vel')]
        ),

        # Planner
        Node(
            package='nav2_planner',
            executable='planner_server',
            name='planner_server',
            parameters=[params_file]
        ),

        # Behaviors
        Node(
            package='nav2_behaviors',
            executable='behavior_server',
            name='behavior_server',
            parameters=[params_file]
        ),

        # BT Navigator
        Node(
            package='nav2_bt_navigator',
            executable='bt_navigator',
            name='bt_navigator',
            parameters=[params_file]
        ),

        # Lifecycle manager - NO collision_monitor
        Node(
            package='nav2_lifecycle_manager',
            executable='lifecycle_manager',
            name='lifecycle_manager_navigation',
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
