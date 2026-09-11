#!/usr/bin/env python3
"""
Spawn TurtleBot3 Waffle robot in hotel world via Gazebo service.

This script spawns a single TurtleBot3 robot at runtime in the hotel world,
replacing the need for slotcar robots for Nav2 integration testing.

Usage:
    python3 spawn_turtlebot3_hotel.py --name robot_1 --x 10.0 --y 30.0 --yaw 0.0
"""

import argparse
import subprocess
import sys
import time


# TurtleBot3 Waffle SDF model template with embedded full model definition
# This embeds the complete model instead of using <include> to avoid model:// resolution issues
TURTLEBOT3_WAFFLE_SDF_TEMPLATE = """<?xml version="1.0"?>
<sdf version="1.9">
  <model name="{robot_name}">
    <pose>{x} {y} 0.1 0 0 {yaw}</pose>
    <link name="base_footprint">
      <inertial>
        <mass>0.001</mass>
        <inertia><ixx>0.0001</ixx><iyy>0.0001</iyy><izz>0.0001</izz><ixy>0</ixy><ixz>0</ixz><iyz>0</iyz></inertia>
      </inertial>
    </link>
    <link name="base_link">
      <inertial>
        <mass>1.37</mass>
        <inertia><ixx>0.0087</ixx><iyy>0.0086</iyy><izz>0.0146</izz><ixy>0</ixy><ixz>0</ixz><iyz>0</iyz></inertia>
      </inertial>
      <collision name="base_collision">
        <pose>-0.032 0 0.07 0 0 0</pose>
        <geometry><box><size>0.28 0.31 0.14</size></box></geometry>
      </collision>
      <visual name="base_visual">
        <pose>-0.032 0 0.07 0 0 0</pose>
        <geometry><box><size>0.28 0.31 0.14</size></box></geometry>
      </visual>
    </link>
    <link name="wheel_left_link">
      <pose>0 0.144 0.023 -1.57 0 0</pose>
      <inertial>
        <mass>0.028</mass>
        <inertia><ixx>1.1e-5</ixx><iyy>1.1e-5</iyy><izz>2.1e-5</izz><ixy>0</ixy><ixz>0</ixz><iyz>0</iyz></inertia>
      </inertial>
      <collision name="left_wheel_collision">
        <geometry><cylinder><radius>0.033</radius><length>0.018</length></cylinder></geometry>
        <surface>
          <friction>
            <ode><mu>100000</mu><mu2>100000</mu2></ode>
            <bullet><friction>100000</friction><friction2>100000</friction2></bullet>
          </friction>
        </surface>
      </collision>
      <visual name="left_wheel_visual">
        <geometry><cylinder><radius>0.033</radius><length>0.018</length></cylinder></geometry>
      </visual>
    </link>
    <link name="wheel_right_link">
      <pose>0 -0.144 0.023 -1.57 0 0</pose>
      <inertial>
        <mass>0.028</mass>
        <inertia><ixx>1.1e-5</ixx><iyy>1.1e-5</iyy><izz>2.1e-5</izz><ixy>0</ixy><ixz>0</ixz><iyz>0</iyz></inertia>
      </inertial>
      <collision name="right_wheel_collision">
        <geometry><cylinder><radius>0.033</radius><length>0.018</length></cylinder></geometry>
        <surface>
          <friction>
            <ode><mu>100000</mu><mu2>100000</mu2></ode>
            <bullet><friction>100000</friction><friction2>100000</friction2></bullet>
          </friction>
        </surface>
      </collision>
      <visual name="right_wheel_visual">
        <geometry><cylinder><radius>0.033</radius><length>0.018</length></cylinder></geometry>
      </visual>
    </link>
    <link name="base_scan">
      <pose>-0.064 0 0.172 0 0 0</pose>
      <inertial>
        <mass>0.125</mass>
        <inertia><ixx>0.001</ixx><iyy>0.001</iyy><izz>0.001</izz><ixy>0</ixy><ixz>0</ixz><iyz>0</iyz></inertia>
      </inertial>
      <sensor name="lidar" type="gpu_lidar">
        <topic>/scan</topic>
        <frame_id>base_scan</frame_id>
        <update_rate>5</update_rate>
        <always_on>1</always_on>
        <visualize>true</visualize>
        <lidar>
          <scan><horizontal><samples>360</samples><resolution>1</resolution><min_angle>0</min_angle><max_angle>6.28</max_angle></horizontal></scan>
          <range><min>0.12</min><max>3.5</max><resolution>0.015</resolution></range>
        </lidar>
      </sensor>
    </link>
    <link name="imu_link">
      <pose>0 0 0.068 0 0 0</pose>
      <inertial>
        <mass>0.0001</mass>
        <inertia><ixx>0.0001</ixx><iyy>0.0001</iyy><izz>0.0001</izz><ixy>0</ixy><ixz>0</ixz><iyz>0</iyz></inertia>
      </inertial>
      <sensor name="imu" type="imu">
        <topic>/imu</topic>
        <update_rate>200</update_rate>
        <always_on>1</always_on>
      </sensor>
    </link>
    <joint name="base_joint" type="fixed"><parent>base_footprint</parent><child>base_link</child></joint>
    <joint name="left_wheel_joint" type="revolute">
      <parent>base_link</parent>
      <child>wheel_left_link</child>
      <axis>
        <xyz>0 0 1</xyz>
        <limit>
          <lower>-10000000000000000</lower>
          <upper>10000000000000000</upper>
          <effort>-1</effort>
          <velocity>-1</velocity>
        </limit>
        <dynamics>
          <damping>0.0</damping>
          <friction>0.0</friction>
        </dynamics>
      </axis>
    </joint>
    <joint name="right_wheel_joint" type="revolute">
      <parent>base_link</parent>
      <child>wheel_right_link</child>
      <axis>
        <xyz>0 0 1</xyz>
        <limit>
          <lower>-10000000000000000</lower>
          <upper>10000000000000000</upper>
          <effort>-1</effort>
          <velocity>-1</velocity>
        </limit>
        <dynamics>
          <damping>0.0</damping>
          <friction>0.0</friction>
        </dynamics>
      </axis>
    </joint>
    <joint name="lidar_joint" type="fixed"><parent>base_link</parent><child>base_scan</child></joint>
    <joint name="imu_joint" type="fixed"><parent>base_link</parent><child>imu_link</child></joint>
    <plugin filename="gz-sim-diff-drive-system" name="gz::sim::systems::DiffDrive">
      <left_joint>left_wheel_joint</left_joint>
      <right_joint>right_wheel_joint</right_joint>
      <wheel_separation>0.287</wheel_separation>
      <wheel_radius>0.033</wheel_radius>
      <odom_publish_frequency>50</odom_publish_frequency>
      <topic>cmd_vel</topic>
      <odom_topic>odometry</odom_topic>
      <frame_id>odom</frame_id>
      <child_frame_id>base_footprint</child_frame_id>
    </plugin>
  </model>
</sdf>
"""


def wait_for_world(world_name='hotel', timeout=180):
    """Wait for Gazebo world to be ready."""
    print(f"[spawn-tb3] Waiting for Gazebo world '{world_name}' to be ready...")

    start_time = time.time()
    while time.time() - start_time < timeout:
        try:
            result = subprocess.run(
                ['gz', 'topic', '-l'],
                capture_output=True,
                text=True,
                timeout=5
            )

            if f'/world/{world_name}/' in result.stdout:
                print(f"[spawn-tb3] World '{world_name}' is ready!")
                return True

        except subprocess.TimeoutExpired:
            pass
        except Exception as e:
            print(f"[spawn-tb3] Error checking world status: {e}")

        time.sleep(2)

    print(f"[spawn-tb3] Timeout waiting for world '{world_name}'")
    return False


def spawn_ground_plane(world_name='hotel'):
    """
    Spawn a static ground plane to provide collision support.
    The hotel world's mesh-based floor collisions don't work in Gazebo Harmonic.
    """
    ground_sdf = """<?xml version="1.0"?>
<sdf version="1.9">
  <model name="ground_plane">
    <static>true</static>
    <pose>0 0 -0.05 0 0 0</pose>
    <link name="ground_link">
      <collision name="ground_collision">
        <geometry>
          <box><size>100 100 0.1</size></box>
        </geometry>
        <surface>
          <friction>
            <ode><mu>1.0</mu><mu2>1.0</mu2></ode>
            <bullet><friction>1.0</friction><friction2>1.0</friction2></bullet>
          </friction>
        </surface>
      </collision>
    </link>
  </model>
</sdf>
"""

    import tempfile
    import os

    try:
        fd, sdf_path = tempfile.mkstemp(suffix='.sdf', prefix='ground_plane_')
        with os.fdopen(fd, 'w') as f:
            f.write(ground_sdf)

        print(f"[spawn-tb3] Adding ground plane collision support...")

        result = subprocess.run(
            [
                'gz', 'service',
                '-s', f'/world/{world_name}/create',
                '--reqtype', 'gz.msgs.EntityFactory',
                '--reptype', 'gz.msgs.Boolean',
                '--timeout', '5000',
                '--req', f'sdf_filename: "{sdf_path}"'
            ],
            capture_output=True,
            text=True,
            timeout=10
        )

        if result.returncode == 0:
            print(f"[spawn-tb3] Ground plane added successfully")
            return True
        else:
            print(f"[spawn-tb3] Failed to add ground plane: {result.stderr}")
            return False

    except Exception as e:
        print(f"[spawn-tb3] Exception adding ground plane: {e}")
        return False


def spawn_robot(robot_name, x, y, yaw, world_name='hotel'):
    """
    Spawn TurtleBot3 robot using Gazebo service.

    Args:
        robot_name: Name of the robot (e.g., "robot_1")
        x: X position in world frame
        y: Y position in world frame
        yaw: Yaw orientation in radians
        world_name: Name of the Gazebo world

    Returns:
        True if successful, False otherwise
    """
    # Generate SDF
    sdf_content = TURTLEBOT3_WAFFLE_SDF_TEMPLATE.format(
        robot_name=robot_name,
        x=x,
        y=y,
        yaw=yaw
    )

    print(f"[spawn-tb3] Spawning {robot_name} at ({x}, {y}, yaw={yaw})...")

    # Write SDF to temporary file (gz service --req cannot handle multi-line XML strings)
    # Use sdf_filename parameter instead of sdf parameter to avoid protobuf text parsing issues
    import tempfile
    import os

    try:
        # Create temporary file
        fd, sdf_path = tempfile.mkstemp(suffix='.sdf', prefix=f'{robot_name}_')
        with os.fdopen(fd, 'w') as f:
            f.write(sdf_content)

        print(f"[spawn-tb3] Wrote SDF to {sdf_path}")

        # Call gz service to create entity using sdf_filename
        result = subprocess.run(
            [
                'gz', 'service',
                '-s', f'/world/{world_name}/create',
                '--reqtype', 'gz.msgs.EntityFactory',
                '--reptype', 'gz.msgs.Boolean',
                '--timeout', '5000',
                '--req', f'sdf_filename: "{sdf_path}"'
            ],
            capture_output=True,
            text=True,
            timeout=10
        )

        # NOTE: Do NOT delete the temp file immediately - Gazebo server reads it asynchronously!
        # The gz service command returns as soon as the request is queued, but gz-server
        # opens the file later. Deleting too early causes "Unable to read file" errors.
        # Let the container's /tmp cleanup handle it (file is only ~4KB).

        if result.returncode == 0:
            print(f"[spawn-tb3] Successfully spawned {robot_name}")
            print(f"[spawn-tb3] Response: {result.stdout}")
            return True
        else:
            print(f"[spawn-tb3] Failed to spawn {robot_name}")
            print(f"[spawn-tb3] Error: {result.stderr}")
            return False

    except subprocess.TimeoutExpired:
        print(f"[spawn-tb3] Timeout spawning {robot_name}")
        return False
    except Exception as e:
        print(f"[spawn-tb3] Exception spawning {robot_name}: {e}")
        return False


def verify_spawn(robot_name, world_name='hotel', timeout=10):
    """Verify robot was spawned by checking model list."""
    print(f"[spawn-tb3] Verifying {robot_name} spawn...")

    start_time = time.time()
    while time.time() - start_time < timeout:
        try:
            result = subprocess.run(
                ['gz', 'model', '-l', '-w', world_name],
                capture_output=True,
                text=True,
                timeout=5
            )

            if robot_name in result.stdout:
                print(f"[spawn-tb3] ✓ {robot_name} confirmed in world model list")
                return True

        except Exception as e:
            print(f"[spawn-tb3] Error verifying spawn: {e}")

        time.sleep(1)

    print(f"[spawn-tb3] ✗ {robot_name} not found in world model list")
    return False


def main():
    parser = argparse.ArgumentParser(
        description='Spawn TurtleBot3 Waffle in hotel world'
    )
    parser.add_argument(
        '--name',
        default='robot_1',
        help='Robot name (default: robot_1)'
    )
    parser.add_argument(
        '--x',
        type=float,
        default=10.0,
        help='X position in meters (default: 10.0)'
    )
    parser.add_argument(
        '--y',
        type=float,
        default=30.0,
        help='Y position in meters (default: 30.0)'
    )
    parser.add_argument(
        '--yaw',
        type=float,
        default=0.0,
        help='Yaw orientation in radians (default: 0.0)'
    )
    parser.add_argument(
        '--world',
        default='hotel',
        help='Gazebo world name (default: hotel)'
    )
    parser.add_argument(
        '--wait-timeout',
        type=int,
        default=180,
        help='Timeout waiting for world (default: 180s)'
    )

    args = parser.parse_args()

    # Wait for Gazebo world
    if not wait_for_world(args.world, args.wait_timeout):
        print(f"[spawn-tb3] ERROR: World '{args.world}' not ready")
        sys.exit(1)

    # Extra settle time
    print("[spawn-tb3] Waiting additional 5s for world to settle...")
    time.sleep(5)

    # Add ground plane for collision support (hotel world's mesh collisions don't work)
    if not spawn_ground_plane(args.world):
        print("[spawn-tb3] WARNING: Failed to add ground plane - robot may fall through floor")
        # Continue anyway in case floor collision works

    time.sleep(2)  # Let ground plane settle

    # Spawn robot
    if not spawn_robot(args.name, args.x, args.y, args.yaw, args.world):
        print(f"[spawn-tb3] ERROR: Failed to spawn {args.name}")
        sys.exit(1)

    # Verify spawn
    if not verify_spawn(args.name, args.world):
        print(f"[spawn-tb3] WARNING: Could not verify {args.name} spawn")
        # Don't exit with error - spawn might have succeeded

    print(f"[spawn-tb3] ✓ {args.name} spawn complete")
    print(f"[spawn-tb3]   Position: ({args.x}, {args.y})")
    print(f"[spawn-tb3]   Yaw: {args.yaw} rad")
    sys.exit(0)


if __name__ == '__main__':
    main()
