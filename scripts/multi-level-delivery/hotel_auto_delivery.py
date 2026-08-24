#!/usr/bin/env python3
"""Auto multi-level delivery (non-interactive)."""
import json
import time
import urllib.request


def navigate(robot, port, cmd_id, level, x, y, desc=""):
    """Send navigation command."""
    url = f"http://localhost:{port}/open-rmf/rmf_demos_fm/navigate/?robot_name={robot}&cmd_id={cmd_id}"
    data = json.dumps({
        "map_name": level,
        "destination": {"x": x, "y": y, "yaw": 0.0},
        "speed_limit": 0.65
    }).encode()
    
    req = urllib.request.Request(url, data, {"Content-Type": "application/json"}, method="POST")
    
    try:
        opener = urllib.request.build_opener(urllib.request.HTTPRedirectHandler())
        r = opener.open(req, timeout=3)
        result = json.loads(r.read())
        if result.get("success"):
            print(f"✓ {desc}")
            return True
        else:
            print(f"✗ Failed: {desc}")
            return False
    except Exception as e:
        print(f"✗ Error {desc}: {e}")
        return False


print("╔══════════════════════════════════════════════════════════════╗")
print("║    AUTO MULTI-LEVEL DELIVERY - deliveryBot_1                ║")
print("╚══════════════════════════════════════════════════════════════╝")
print("")

robot = "deliveryBot_1"
port = 22012
cmd = 0

# Test 1: Navigate to Lift1 on L1
print("Test 1: Navigating to Lift1 (355, 340) on L1...")
cmd += 1
if navigate(robot, port, cmd, "L1", 355, 340, "Approaching Lift1 entrance"):
    print("  → Robot heading to lift position")
    time.sleep(10)  # Wait for robot to approach

print("")
print("Test 2: Attempting L2 navigation...")
cmd += 1  
if navigate(robot, port, cmd, "L2", 360, 340, "Requesting navigation to L2"):
    print("  → If lift supervisor is working, robot should call lift")
    print("  → Watch noVNC to see lift movement!")
    time.sleep(15)

print("")
print("Test 3: Attempting L3 navigation...")
cmd += 1
if navigate(robot, port, cmd, "L3", 360, 340, "Requesting navigation to L3"):
    print("  → Robot should take lift to L3")
    time.sleep(15)

print("")
print("Test 4: Return to L1...")
cmd += 1
if navigate(robot, port, cmd, "L1", 300, 435, "Returning to L1 via Lift2"):
    print("  → Robot returning to lobby")
    time.sleep(15)

print("")
print("╔══════════════════════════════════════════════════════════════╗")
print("║              DELIVERY TESTS DISPATCHED                      ║")
print("╚══════════════════════════════════════════════════════════════╝")
print("")
print("Watch noVNC to see if:")
print("  1. Robot navigates to lift")
print("  2. Lift doors open")
print("  3. Robot enters lift")
print("  4. Lift moves to requested floor")
print("  5. Robot exits on destination floor")
print("")
