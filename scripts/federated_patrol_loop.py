#!/usr/bin/env python3
"""
Continuous patrol loop for the federated 2-robot demo.

Dispatches patrol tasks for robot_1 and robot_2 in a continuous loop,
ensuring both robots are always patrolling.

Usage:
    python3 federated_patrol_loop.py
"""

import requests
import time
import sys
import os

# RMF API server endpoint
API_BASE = "http://localhost:8000"

# Fleet and robot configuration
FLEET_NAME = "turtlebot3_hotel"
ROBOTS = ["robot_1", "robot_2"]

# Patrol routes for each robot
PATROL_ROUTES = {
    "robot_1": {
        "waypoints": ["robot_1_home", "mid_west", "meeting_point"],
        "description": "West side patrol"
    },
    "robot_2": {
        "waypoints": ["robot_2_home", "mid_east", "meeting_point"],
        "description": "East side patrol"
    }
}

def dispatch_patrol(robot_name, waypoints, rounds=1):
    """Dispatch a patrol task via RMF API."""
    task_request = {
        "type": "robot_task_request",
        "robot": robot_name,
        "fleet": FLEET_NAME,
        "request": {
            "unix_millis_earliest_start_time": 0,
            "category": "patrol",
            "fleet_name": FLEET_NAME,
            "description": {
                "places": waypoints,
                "rounds": rounds
            }
        }
    }

    try:
        response = requests.post(
            f"{API_BASE}/tasks/dispatch_task_request",
            json=task_request,
            timeout=10
        )
        response.raise_for_status()
        result = response.json()

        if result.get("success"):
            task_id = result.get("state", {}).get("booking", {}).get("id", "unknown")
            print(f"✓ {robot_name}: Patrol dispatched (task: {task_id[:12]}...)")
            return task_id
        else:
            print(f"✗ {robot_name}: Dispatch failed - {result}")
            return None
    except Exception as e:
        print(f"✗ {robot_name}: API error - {e}")
        return None

def get_fleet_state():
    """Get current fleet state from RMF API."""
    try:
        response = requests.get(f"{API_BASE}/fleets/{FLEET_NAME}/state", timeout=5)
        response.raise_for_status()
        return response.json()
    except Exception as e:
        print(f"Warning: Could not get fleet state - {e}")
        return None

def is_robot_idle(robot_name, fleet_state):
    """Check if a robot is idle (not executing a task)."""
    if not fleet_state:
        return True  # Assume idle if we can't get state

    robots = fleet_state.get("robots", {})
    robot_state = robots.get(robot_name, {})
    task_id = robot_state.get("task_id", "")

    # Robot is idle if it has no task_id
    return not task_id or task_id == ""

def main():
    """Main continuous patrol loop."""
    print("=" * 60)
    print(" Continuous Patrol Loop - Federated Demo")
    print("=" * 60)
    print(f" Fleet: {FLEET_NAME}")
    print(f" Robots: {', '.join(ROBOTS)}")
    print(f" API: {API_BASE}")
    print("=" * 60)
    print()

    # Track active tasks per robot
    active_tasks = {robot: None for robot in ROBOTS}
    cycle_count = 0

    try:
        while True:
            cycle_count += 1
            print(f"\n[Cycle {cycle_count}] Checking robot status...")

            # Get current fleet state
            fleet_state = get_fleet_state()

            # Check each robot and dispatch patrol if idle
            for robot in ROBOTS:
                if is_robot_idle(robot, fleet_state):
                    print(f"  {robot}: Idle, dispatching new patrol...")
                    route = PATROL_ROUTES[robot]
                    task_id = dispatch_patrol(
                        robot,
                        route["waypoints"],
                        rounds=3  # 3 rounds per patrol
                    )
                    if task_id:
                        active_tasks[robot] = task_id
                else:
                    task_id = active_tasks.get(robot, "unknown")
                    if isinstance(task_id, str):
                        task_short = task_id[:12] + "..." if len(task_id) > 12 else task_id
                    else:
                        task_short = "unknown"
                    print(f"  {robot}: Active (task: {task_short})")

            # Wait before next check
            print(f"\nWaiting 30s before next check...")
            time.sleep(30)

    except KeyboardInterrupt:
        print("\n\n" + "=" * 60)
        print(" Patrol loop stopped by user")
        print("=" * 60)
        sys.exit(0)
    except Exception as e:
        print(f"\n\nERROR: {e}")
        sys.exit(1)

if __name__ == "__main__":
    main()
