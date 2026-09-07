#!/usr/bin/env python3
"""
Create a hybrid-mode hotel launch file that skips built-in fleet adapters.

When SPAWN_TURTLEBOT3=true, we're in hybrid Nav2 mode and want to use Free Fleet
instead of the built-in slotcar fleet adapters. This script creates a modified
launch file that conditionally includes the fleet adapters based on environment.

The modified launch file will:
  - Always start Gazebo with hotel world
  - Always start RMF infrastructure (building map, door/lift supervisors, traffic schedule)
  - Conditionally start fleet adapters ONLY if SPAWN_TURTLEBOT3=false
"""

import os
from pathlib import Path


def create_hybrid_launch():
    """Create hotel_hybrid.launch.xml that skips fleet adapters in hybrid mode."""

    launch_dir = Path("/opt/rmf_demos_ws/install/share/rmf_demos_gz/launch")
    launch_dir.mkdir(parents=True, exist_ok=True)

    hybrid_launch = launch_dir / "hotel_hybrid.launch.xml"

    # Read the original hotel.launch.xml
    original_launch = launch_dir / "hotel.launch.xml"
    if not original_launch.exists():
        print(f"WARNING: {original_launch} not found, creating from scratch")
        content = create_launch_from_scratch()
    else:
        with open(original_launch, 'r') as f:
            content = f.read()

        # Wrap fleet adapter includes in a condition
        # Look for the fleet adapter launch includes
        content = wrap_fleet_adapters(content)

    # Write the hybrid launch file
    with open(hybrid_launch, 'w') as f:
        f.write(content)

    print(f"Created {hybrid_launch}")
    print("Hybrid launch file will skip fleet adapters when SPAWN_TURTLEBOT3=true")

    # Update entrypoint to use hotel_hybrid.launch.xml in hybrid mode
    update_entrypoint()


def wrap_fleet_adapters(content):
    """Wrap fleet adapter includes in environment-based conditionals."""

    # Add a comment explaining the modification
    header = """<!--
  HYBRID MODE MODIFICATION:
  Fleet adapters are only launched when SPAWN_TURTLEBOT3 != "true".
  In hybrid mode (SPAWN_TURTLEBOT3=true), we use Free Fleet from rmf-core pod instead.
-->\n\n"""

    # Find and wrap fleet adapter includes
    # Look for patterns like: <include file="...fleet_adapter..." />
    import re

    # Pattern to match fleet adapter include lines
    pattern = r'(<include\s+file="[^"]*fleet_adapter[^"]*"[^/]*/?>)'

    def replace_with_condition(match):
        include_line = match.group(1)
        # Skip if already wrapped in a condition
        if 'unless=' in include_line or 'if=' in include_line:
            return include_line
        # Wrap in unless condition
        return f'<group unless="$(env SPAWN_TURTLEBOT3 false)">\n    {include_line}\n  </group>'

    modified_content = re.sub(pattern, replace_with_condition, content)

    # Add header if we made changes
    if modified_content != content:
        modified_content = header + modified_content

    return modified_content


def create_launch_from_scratch():
    """Create a minimal hotel launch file from scratch if original doesn't exist."""

    return """<?xml version='1.0' ?>
<launch>
  <!--
    Hotel World Hybrid Launch

    Launches hotel world with conditional fleet adapters.
    When SPAWN_TURTLEBOT3=true, skips built-in slotcar fleet adapters
    and relies on Free Fleet in rmf-core pod for robot control.
  -->

  <!-- Simulation -->
  <include file="$(find-pkg-share rmf_demos_gz)/launch/simulation.launch.xml">
    <arg name="world_name" value="hotel"/>
    <arg name="headless" value="$(var headless)"/>
  </include>

  <!-- Building Map Server -->
  <node pkg="rmf_building_map_tools" exec="building_map_server" name="building_map_server">
    <param name="map_path" value="$(find-pkg-share rmf_demos_maps)/hotel/hotel.building.yaml"/>
  </node>

  <!-- Door Supervisor -->
  <node pkg="rmf_fleet_adapter" exec="door_supervisor" name="door_supervisor">
    <param name="use_sim_time" value="true"/>
  </node>

  <!-- Lift Supervisor -->
  <node pkg="rmf_fleet_adapter" exec="lift_supervisor" name="lift_supervisor">
    <param name="use_sim_time" value="true"/>
  </node>

  <!-- RMF Traffic Schedule -->
  <node pkg="rmf_traffic_ros2" exec="rmf_traffic_schedule" name="rmf_traffic_schedule">
    <param name="use_sim_time" value="true"/>
  </node>

  <!-- RMF Task Dispatcher -->
  <node pkg="rmf_task_ros2" exec="rmf_task_dispatcher" name="rmf_task_dispatcher">
    <param name="use_sim_time" value="true"/>
  </node>

  <!-- Fleet Adapters (ONLY when not in hybrid mode) -->
  <group unless="$(env SPAWN_TURTLEBOT3 false)">
    <!-- TinyRobot Fleet -->
    <include file="$(find-pkg-share rmf_demos_gz)/launch/fleet_adapter.launch.xml">
      <arg name="fleet_name" value="tinyRobot"/>
      <arg name="config_file" value="$(find-pkg-share rmf_demos)/config/hotel/tinyRobot_config.yaml"/>
      <arg name="nav_graph" value="$(find-pkg-share rmf_demos_maps)/maps/hotel/nav_graphs/0.yaml"/>
    </include>

    <!-- CleanerBotA Fleet -->
    <include file="$(find-pkg-share rmf_demos_gz)/launch/fleet_adapter.launch.xml">
      <arg name="fleet_name" value="cleanerBotA"/>
      <arg name="config_file" value="$(find-pkg-share rmf_demos)/config/hotel/cleanerBotA_config.yaml"/>
      <arg name="nav_graph" value="$(find-pkg-share rmf_demos_maps)/maps/hotel/nav_graphs/1.yaml"/>
    </include>

    <!-- DeliveryRobot Fleet -->
    <include file="$(find-pkg-share rmf_demos_gz)/launch/fleet_adapter.launch.xml">
      <arg name="fleet_name" value="deliveryRobot"/>
      <arg name="config_file" value="$(find-pkg-share rmf_demos)/config/hotel/deliveryRobot_config.yaml"/>
      <arg name="nav_graph" value="$(find-pkg-share rmf_demos_maps)/maps/hotel/nav_graphs/2.yaml"/>
    </include>
  </group>

</launch>
"""


def update_entrypoint():
    """Update entrypoint-hotel.sh to use hotel_hybrid.launch.xml when in hybrid mode."""

    entrypoint_path = Path("/entrypoint-hotel.sh")
    if not entrypoint_path.exists():
        print(f"WARNING: {entrypoint_path} not found, skipping entrypoint update")
        return

    with open(entrypoint_path, 'r') as f:
        content = f.read()

    # Replace hotel.launch.xml with hotel_hybrid.launch.xml when SPAWN_TURTLEBOT3=true
    # Look for the launch command line
    import re
    pattern = r'(HOTEL_LAUNCH_FILE="\${HOTEL_LAUNCH_FILE:-)[^}]+(}")'
    replacement = r'\1hotel_hybrid.launch.xml\2'

    modified_content = re.sub(pattern, replacement, content)

    if modified_content != content:
        with open(entrypoint_path, 'w') as f:
            f.write(modified_content)
        print(f"Updated {entrypoint_path} to use hotel_hybrid.launch.xml")
    else:
        print(f"NOTE: {entrypoint_path} already uses correct launch file or pattern not found")


if __name__ == "__main__":
    create_hybrid_launch()
    print("\nHybrid hotel launch configuration complete!")
    print("\nWhen deployed with SPAWN_TURTLEBOT3=true:")
    print("  - Gazebo hotel world: ✓ Running")
    print("  - RMF infrastructure: ✓ Running (doors, lifts, traffic, dispatcher)")
    print("  - Slotcar fleet adapters: ✗ Disabled")
    print("  - Free Fleet (rmf-core): ✓ Handles robot_1 via Nav2")
