#!/usr/bin/env python3
"""
Simple navigation test using Free Fleet's rmf_navigate_cmd protocol.

This directly sends navigation commands to robots via Zenoh, bypassing
the RMF Task API complexity. Good for testing if basic navigation works.
"""

import zenoh
import struct
import time
import sys


# Hotel lobby waypoints (from nav graph)
WAYPOINTS = {
    'lobby_north': (20.0, -25.0, 0.0),
    'lobby_south': (20.0, -35.0, 0.0),
    'lobby_west': (15.0, -30.0, 0.0),
    'lobby_east': (25.0, -30.0, 0.0),
    'lobby_northwest': (15.0, -25.0, 0.0),
    'lobby_northeast': (25.0, -25.0, 0.0),
    'lobby_southwest': (15.0, -35.0, 0.0),
    'lobby_southeast': (25.0, -35.0, 0.0),
}


def cdr_encode(text):
    """Encode text message in CDR format for ROS2 String message"""
    data = text.encode() + b'\x00'
    return b'\x00\x01\x00\x00' + struct.pack('<I', len(data)) + data


def open_zenoh_session():
    """Open Zenoh session connected to router"""
    conf = zenoh.Config()
    conf.insert_json5("connect/endpoints", '["tcp/zenoh-router:7447"]')
    conf.insert_json5("mode", '"client"')
    conf.insert_json5("scouting/multicast/enabled", "false")
    return zenoh.open(conf)


def send_navigate_command(session, robot_name, x, y, yaw=0.0):
    """
    Send navigation command to robot via rmf_navigate_cmd.

    Format: "<goal_id> <x> <y> <yaw>"
    """
    goal_id = f"goal_{int(time.time())}"
    cmd = f"{goal_id} {x:.6f} {y:.6f} {yaw:.6f}"

    topic = f"{robot_name}/rmf_navigate_cmd"
    payload = cdr_encode(cmd)

    print(f"[{robot_name}] Sending: {cmd}")
    session.put(topic, payload)
    return goal_id


def navigate_to_waypoint(session, robot_name, waypoint_name):
    """Navigate robot to named waypoint"""
    if waypoint_name not in WAYPOINTS:
        print(f"ERROR: Unknown waypoint '{waypoint_name}'")
        print(f"Available: {', '.join(WAYPOINTS.keys())}")
        return None

    x, y, yaw = WAYPOINTS[waypoint_name]
    print(f"\n[{robot_name}] Navigating to {waypoint_name}: ({x:.1f}, {y:.1f}, {yaw:.2f})")
    return send_navigate_command(session, robot_name, x, y, yaw)


def cancel_navigation(session, robot_name, goal_id):
    """Cancel ongoing navigation"""
    cmd = f"{goal_id} CANCEL"
    topic = f"{robot_name}/rmf_navigate_cmd"
    payload = cdr_encode(cmd)

    print(f"[{robot_name}] Canceling goal: {goal_id}")
    session.put(topic, payload)


def monitor_result(session, robot_name, goal_id, timeout=60.0):
    """
    Monitor navigation result for a specific goal.

    Returns: True if OK, False if FAILED or timeout
    """
    result_topic = f"{robot_name}/rmf_navigate_result"
    result = {'done': False, 'ok': False}

    def on_result(sample):
        try:
            raw = bytes(sample.payload.to_bytes())
            if len(raw) < 9:
                return
            slen = struct.unpack_from('<I', raw, 4)[0]
            text = raw[8:8 + slen - 1].decode('utf-8', errors='ignore').strip()
            parts = text.split()

            if len(parts) >= 2 and parts[0] == goal_id:
                if parts[1] == 'OK':
                    print(f"[{robot_name}] ✓ Navigation succeeded!")
                    result['ok'] = True
                    result['done'] = True
                elif parts[1] == 'FAILED':
                    print(f"[{robot_name}] ✗ Navigation failed!")
                    result['done'] = True
                else:
                    print(f"[{robot_name}] Result: {parts[1]}")
        except Exception as e:
            pass

    # Subscribe to result topic
    sub = session.declare_subscriber(result_topic, on_result)

    # Wait for result
    print(f"[{robot_name}] Waiting for navigation result (timeout: {timeout}s)...")
    start_time = time.time()
    while time.time() - start_time < timeout:
        if result['done']:
            break
        time.sleep(0.5)

    sub.undeclare()

    if not result['done']:
        print(f"[{robot_name}] ⚠ Timeout waiting for result")

    return result['ok']


def main():
    """Main test function"""

    print("=" * 70)
    print("Free Fleet Navigation Test")
    print("=" * 70)
    print()

    # Open Zenoh session
    print("Connecting to Zenoh router...")
    session = open_zenoh_session()
    print("✓ Connected to Zenoh")
    print()

    # Test 1: Send tinyBot_2 to lobby_south
    print("-" * 70)
    print("TEST 1: Navigate tinyBot_2 to lobby_south")
    print("-" * 70)

    goal_id = navigate_to_waypoint(session, 'tinyBot_2', 'lobby_south')

    if goal_id:
        # Monitor result
        success = monitor_result(session, 'tinyBot_2', goal_id, timeout=120.0)

        if success:
            print("\n✓ TEST 1 PASSED: tinyBot_2 reached lobby_south")
        else:
            print("\n✗ TEST 1 FAILED: tinyBot_2 did not reach goal")

    print()

    # Test 2: Send tinyBot_3 to lobby_west
    print("-" * 70)
    print("TEST 2: Navigate tinyBot_3 to lobby_west")
    print("-" * 70)

    goal_id = navigate_to_waypoint(session, 'tinyBot_3', 'lobby_west')

    if goal_id:
        success = monitor_result(session, 'tinyBot_3', goal_id, timeout=120.0)

        if success:
            print("\n✓ TEST 2 PASSED: tinyBot_3 reached lobby_west")
        else:
            print("\n✗ TEST 2 FAILED: tinyBot_3 did not reach goal")

    print()
    print("=" * 70)
    print("Navigation test complete!")
    print("=" * 70)

    session.close()


if __name__ == '__main__':
    main()
