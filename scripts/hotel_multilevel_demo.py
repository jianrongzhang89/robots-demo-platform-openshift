#!/usr/bin/env python3
"""
Hotel Multi-Level Navigation Demonstration
==========================================
Demonstrates cross-level navigation using tinyBot_1 moving between L1 and L3
via lifts. Uses coordinate-based navigation as implemented in the hotel demo.

This script demonstrates the multi-level navigation capability by sending
tinyBot_1 on a tour across all 3 levels:
  L1 (restaurant) → Lift1 → L2 (L2_room1) → Lift2 → L3 (L3_master_suite)

Usage (run inside hotel-sim pod):
  python3 /scripts/hotel_multilevel_demo.py
"""

import json
import math
import time
import urllib.request


class _NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        return urllib.request.Request(
            newurl, req.data, req.headers, method=req.get_method()
        )


_opener = urllib.request.build_opener(_NoRedirect())

# tinyRobot fleet manager HTTP port
TINYBOT_PORT = 22011

# Multi-level tour waypoints (from nav_graphs/0.yaml)
# Format: (x, y, level_name, waypoint_name)
TOUR_WAYPOINTS = [
    (19.59, -15.81, "L1", "restaurant"),        # Start on L1
    (14.18, -8.29, "L2", "L2_room1"),           # Move to L2 (via Lift1)
    (4.49, -36.53, "L3", "L3_master_suite"),    # Move to L3 (via Lift2)
    (19.59, -15.81, "L1", "restaurant"),        # Return to L1
]

SPEED = 0.65  # m/s slotcar speed
ARRIVE_THRESHOLD = 2.5  # metres
TIMEOUT_PER_SEGMENT = 120  # seconds (lifts take time!)


def _nav(robot, port, cmd, x, y, level="L1"):
    """Send navigate command to fleet manager."""
    url = (
        f"http://localhost:{port}/open-rmf/rmf_demos_fm/navigate/"
        f"?robot_name={robot}&cmd_id={cmd}"
    )
    data = json.dumps({
        "map_name": level,
        "destination": {"x": x, "y": y, "yaw": 0.0},
        "speed_limit": SPEED
    }).encode()
    req = urllib.request.Request(
        url, data, {"Content-Type": "application/json"}, method="POST"
    )
    try:
        r = _opener.open(req, timeout=3)
        return json.loads(r.read()).get("success", False)
    except Exception as e:
        print(f"Navigation request failed: {e}")
        return False


def _pos(robot, port):
    """Get robot's current position."""
    try:
        r = urllib.request.urlopen(
            f"http://localhost:{port}/open-rmf/rmf_demos_fm/"
            f"status?robot_name={robot}",
            timeout=2,
        )
        d = json.loads(r.read())["data"]
        return d["position"]["x"], d["position"]["y"], d["map_name"]
    except Exception:
        return None, None, None


def _wait_near(robot, port, tx, ty, timeout=TIMEOUT_PER_SEGMENT):
    """Wait for robot to arrive near target coordinates."""
    deadline = time.time() + timeout
    print(f"  Waiting for {robot} to reach ({tx:.1f}, {ty:.1f})...", flush=True)

    while time.time() < deadline:
        x, y, level = _pos(robot, port)
        if x is not None:
            dist = math.sqrt((x - tx) ** 2 + (y - ty) ** 2)
            if dist < ARRIVE_THRESHOLD:
                print(f"  ✓ Arrived at ({x:.1f}, {y:.1f}) on {level}", flush=True)
                return True
            if int(time.time()) % 10 == 0:  # Progress update every 10s
                print(f"    Current: ({x:.1f}, {y:.1f}) | Distance: {dist:.1f}m", flush=True)
        time.sleep(3)

    print(f"  ✗ Timeout waiting for destination", flush=True)
    return False


def main():
    robot = "tinyBot_1"
    cmd_id = 30000

    print("=" * 60)
    print(" MULTI-LEVEL NAVIGATION DEMONSTRATION")
    print(" Robot: tinyBot_1 (tinyRobot fleet)")
    print("=" * 60)
    print()
    print("Tour Route:")
    for i, (x, y, level, name) in enumerate(TOUR_WAYPOINTS, 1):
        print(f"  {i}. {name} ({x:.1f}, {y:.1f}) on {level}")
    print()
    print("This demonstrates:")
    print("  - Cross-level navigation via Lift1 and Lift2")
    print("  - Multi-level path planning (L1 → L2 → L3 → L1)")
    print("  - Lift coordination and waiting")
    print()
    print("Starting tour...\n")

    # Execute multi-level tour
    for i, (tx, ty, level, name) in enumerate(TOUR_WAYPOINTS, 1):
        print(f"[Segment {i}/{len(TOUR_WAYPOINTS)}] Navigating to {name} on {level}")

        # Send navigation command
        ok = _nav(robot, TINYBOT_PORT, cmd_id, tx, ty, level)
        if not ok:
            print(f"  ✗ Failed to send navigation command")
            continue

        print(f"  ✓ Navigation command sent (cmd_id={cmd_id})")
        cmd_id += 1

        # Wait for arrival
        arrived = _wait_near(robot, TINYBOT_PORT, tx, ty)
        if not arrived:
            print(f"  ⚠ Continuing to next waypoint anyway...")

        print()

    # Final status
    x, y, level = _pos(robot, TINYBOT_PORT)
    print("=" * 60)
    print(f"Multi-level tour complete!")
    if x is not None:
        print(f"Final position: ({x:.1f}, {y:.1f}) on {level}")
    print("=" * 60)


if __name__ == "__main__":
    main()
