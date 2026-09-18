#!/usr/bin/env python3
"""Lifecycle-driven Nav2 launch for the one local hotel robot."""

import os

from launch import LaunchDescription
from launch.actions import DeclareLaunchArgument, IncludeLaunchDescription
from launch.substitutions import LaunchConfiguration
from launch.launch_description_sources import PythonLaunchDescriptionSource
from ament_index_python.packages import get_package_share_directory


def generate_launch_description():
    namespace = LaunchConfiguration("namespace")
    map_file = LaunchConfiguration("map")
    params_file = LaunchConfiguration("params_file")
    bringup = os.path.join(
        get_package_share_directory("nav2_bringup"), "launch", "bringup_launch.py")
    return LaunchDescription([
        DeclareLaunchArgument("namespace", default_value="robot_1"),
        DeclareLaunchArgument("map", default_value="/opt/ros2-demo/maps/hotel_L1.yaml"),
        DeclareLaunchArgument(
            "params_file",
            default_value="/opt/ros2-demo/config/nav2/hotel_nav2_params.yaml"),
        IncludeLaunchDescription(
            PythonLaunchDescriptionSource(bringup),
            launch_arguments={
                "namespace": namespace,
                "use_namespace": "True",
                "map": map_file,
                "params_file": params_file,
                "use_sim_time": "True",
                "autostart": "True",
                "use_composition": "False",
            }.items(),
        ),
    ])
