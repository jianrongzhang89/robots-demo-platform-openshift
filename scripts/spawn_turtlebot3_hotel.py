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


# TurtleBot3 Waffle SDF model template
# This uses the standard TurtleBot3 Waffle model from turtlebot3_gazebo
TURTLEBOT3_WAFFLE_SDF_TEMPLATE = """<?xml version="1.0"?>
<sdf version="1.9">
  <model name="{robot_name}">
    <include>
      <uri>model://turtlebot3_waffle</uri>
    </include>
    <pose>{x} {y} 0.01 0 0 {yaw}</pose>
  </model>
</sdf>
"""


def wait_for_world(world_name='hotel', timeout=60):
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
    print(f"[spawn-tb3] SDF content:\n{sdf_content}")

    # Call gz service to create entity
    try:
        result = subprocess.run(
            [
                'gz', 'service',
                '-s', f'/world/{world_name}/create',
                '--reqtype', 'gz.msgs.EntityFactory',
                '--reptype', 'gz.msgs.Boolean',
                '--timeout', '5000',
                '--req', f'sdf: "{sdf_content}"'
            ],
            capture_output=True,
            text=True,
            timeout=10
        )

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
        default=60,
        help='Timeout waiting for world (default: 60s)'
    )

    args = parser.parse_args()

    # Wait for Gazebo world
    if not wait_for_world(args.world, args.wait_timeout):
        print(f"[spawn-tb3] ERROR: World '{args.world}' not ready")
        sys.exit(1)

    # Extra settle time
    print("[spawn-tb3] Waiting additional 5s for world to settle...")
    time.sleep(5)

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
