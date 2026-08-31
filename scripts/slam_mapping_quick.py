#!/usr/bin/env python3
"""
Quick slam_toolbox mapping script to generate .posegraph file
Run this once to build the map, then use the .posegraph in localization mode
"""

import os
import sys
from launch import LaunchDescription
from launch_ros.actions import Node, SetParameter


def generate_launch_description():
    robot_name = os.environ.get('ROBOT_NAME', 'tinyBot_1')

    ld = LaunchDescription()

    # Global use_sim_time
    ld.add_action(SetParameter(name='use_sim_time', value=True))

    # slam_toolbox in ASYNC MAPPING mode
    ld.add_action(Node(
        package='slam_toolbox',
        executable='async_slam_toolbox_node',
        name='slam_toolbox',
        namespace=robot_name,
        output='screen',
        parameters=[{
            'use_sim_time': True,

            # Frame IDs
            'odom_frame': f'{robot_name}/odom',
            'map_frame': 'map',
            'base_frame': f'{robot_name}/base_footprint',
            'scan_topic': 'scan',

            # Solver
            'solver_plugin': 'solver_plugins::CeresSolver',
            'ceres_linear_solver': 'SPARSE_NORMAL_CHOLESKY',
            'ceres_preconditioner': 'SCHUR_JACOBI',
            'ceres_trust_strategy': 'LEVENBERG_MARQUARDT',
            'ceres_dogleg_type': 'TRADITIONAL_DOGLEG',
            'ceres_loss_function': 'None',

            # Mapping params
            'mode': 'mapping',
            'resolution': 0.05,
            'max_laser_range': 12.0,
            'minimum_time_interval': 0.5,
            'transform_publish_period': 0.02,
            'map_update_interval': 2.0,
            'minimum_travel_distance': 0.2,
            'minimum_travel_heading': 0.2,

            # Scan matching
            'scan_buffer_size': 10,
            'scan_buffer_maximum_scan_distance': 10.0,
            'link_match_minimum_response_fine': 0.1,
            'link_scan_maximum_distance': 1.5,
            'loop_search_maximum_distance': 3.0,

            # Loop closure
            'do_loop_closing': True,
            'loop_match_minimum_chain_size': 10,
            'loop_match_maximum_variance_coarse': 3.0,
            'loop_match_minimum_response_coarse': 0.35,
            'loop_match_minimum_response_fine': 0.45,

            # Correlation
            'correlation_search_space_dimension': 0.5,
            'correlation_search_space_resolution': 0.01,
            'correlation_search_space_smear_deviation': 0.1,

            # Save map
            'use_map_saver': True,
        }]
    ))

    return ld


if __name__ == '__main__':
    generate_launch_description()
