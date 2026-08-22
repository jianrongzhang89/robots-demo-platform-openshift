#!/usr/bin/env python3
"""
Hotel Demo — Continuous 4-Robot Patrol Loop
============================================
Runs inside the hotel-sim pod. Sends navigate commands directly to the
fleet_manager HTTP API (bypassing the crashed EasyFullControl C++ layer).

Each robot is assigned a dedicated non-overlapping patrol zone so they
never block each other via collision avoidance:

  Zone  Robot           Area                   Route
  ----  ------------   --------------------   ----------------------
  W     deliveryBot_1  West corridor (x<15)   v5(14.87,-28.77) <> v8(13.57,-21.79)
  CE    tinyBot_1      Center-east            (22,-26.5) <> (22,-30.0)
  SW    cleanerBotA_1  South-west lobby       (15,-30.5) <> (15,-35.0)
  S     cleanerBotA_2  South strip            (22,-33.5) <> (22,-37.0)

Usage (run inside pod):
  python3 /scripts/hotel_patrol_loop.py

Or via Makefile:
  make patrol-hotel NAMESPACE=ros2-rmf-hotel
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

FLEET_PORTS = {
    "deliveryBot_1":  22012,
    "tinyBot_1":      22011,
    "cleanerBotA_1":  22013,
    "cleanerBotA_2":  22013,
}

# Two waypoints per robot (alternating A <> B each cycle)
ROUTES = {
    "deliveryBot_1": [(14.87, -28.77), (13.57, -21.79)],
    "tinyBot_1":     [(22.0,  -26.5),  (22.0,  -30.0)],
    "cleanerBotA_1": [(15.0,  -30.5),  (15.0,  -35.0)],
    "cleanerBotA_2": [(22.0,  -33.5),  (22.0,  -37.0)],
}

SPEED = 0.65   # m/s slotcar speed
ARRIVE_THRESHOLD = 2.5   # metres — "close enough" to target
WAIT_TIMEOUT = 40        # seconds to wait for deliveryBot (slowest)


def _nav(robot, port, cmd, x, y):
    url = (
        f"http://localhost:{port}/open-rmf/rmf_demos_fm/navigate/"
        f"?robot_name={robot}&cmd_id={cmd}"
    )
    data = json.dumps(
        {"map_name": "L1", "destination": {"x": x, "y": y, "yaw": 0.0},
         "speed_limit": SPEED}
    ).encode()
    req = urllib.request.Request(
        url, data, {"Content-Type": "application/json"}, method="POST"
    )
    try:
        r = _opener.open(req, timeout=3)
        return json.loads(r.read()).get("success", False)
    except Exception:
        return False


def _pos(robot, port):
    try:
        r = urllib.request.urlopen(
            f"http://localhost:{port}/open-rmf/rmf_demos_fm/"
            f"status?robot_name={robot}",
            timeout=2,
        )
        d = json.loads(r.read())["data"]["position"]
        return d["x"], d["y"]
    except Exception:
        return None, None


def _wait_near(robot, port, tx, ty, timeout=WAIT_TIMEOUT):
    deadline = time.time() + timeout
    while time.time() < deadline:
        x, y = _pos(robot, port)
        if x is not None and math.sqrt((x - tx) ** 2 + (y - ty) ** 2) < ARRIVE_THRESHOLD:
            return True
        time.sleep(3)
    return False


def main():
    cmd = 20000
    cycle = 0
    print("Hotel patrol loop started — 4 dedicated zones, no overlap", flush=True)
    print("Ctrl-C to stop\n", flush=True)

    while True:
        cycle += 1
        phase = cycle % 2  # alternates 0 / 1

        # Dispatch all 4 robots to their phase waypoint simultaneously
        for robot, waypoints in ROUTES.items():
            wp = waypoints[phase]
            ok = _nav(robot, FLEET_PORTS[robot], cmd, wp[0], wp[1])
            print(f"  [{robot}] -> ({wp[0]},{wp[1]}) {'✓' if ok else '✗'}", flush=True)
            cmd += 1

        # Wait for deliveryBot (deepest route, sets the cadence)
        wp = ROUTES["deliveryBot_1"][phase]
        reached = _wait_near("deliveryBot_1", FLEET_PORTS["deliveryBot_1"], wp[0], wp[1])

        # Report all positions
        positions = []
        for robot, port in FLEET_PORTS.items():
            x, y = _pos(robot, port)
            if x is not None:
                positions.append(f"{robot.split('_')[0][:3]}({x:.0f},{y:.0f})")
        print(f"Cycle {cycle}: {' | '.join(positions)}", flush=True)

        time.sleep(4)


if __name__ == "__main__":
    main()
