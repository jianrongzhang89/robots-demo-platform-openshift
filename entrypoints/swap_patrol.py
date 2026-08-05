#!/usr/bin/env python3
"""
Swap-position patrol: robot_1 and robot_2 travel to each other's spawn position.

Pillar layout: 3×3 grid, cylinders with radius 0.15 m, at
  x ∈ {-1.1, 0, 1.1}  ×  y ∈ {-1.1, 0, 1.1}

Effective clearance = pillar_radius (0.15) + robot_radius (0.15) = 0.30 m.
Nearest pillar row to y=-0.5 corridor is at y=-1.1 → 0.20 m clearance (too tight).

Safe detour corridors at y=±1.8 clear both pillar rows by 0.70 m → 0.40 m net
clearance. Use 1 m waypoint steps to keep dead-reckoning error per leg small.

  robot_1 (blue): home → south(y=-1.8) → east in 1 m steps → target(2,0.5)
  robot_2 (red):  home [+30 s] → north(y=+1.8) → west in 1 m steps → target(-2,-0.5)

Robots travel on opposite outer corridors, 3.6 m apart, so no collision risk.

Both robots use CDR-encoded direct Zenoh dispatch, bypassing the RMF traffic
scheduler.
"""
import zenoh, time, struct, threading, random

ROUTER = "tcp/zenoh-router:7447"
TIMEOUT_S = 300  # max wall-clock seconds to wait per leg (Nav2 planning can be slow)


def cdr(text):
    d = text.encode() + b'\x00'
    return b'\x00\x01\x00\x00' + struct.pack('<I', len(d)) + d


def open_session():
    conf = zenoh.Config()
    conf.insert_json5("connect/endpoints", f'["{ROUTER}"]')
    conf.insert_json5("mode", '"client"')
    conf.insert_json5("scouting/multicast/enabled", "false")
    return zenoh.open(conf)


class NavAgent:
    def __init__(self, session, robot_name):
        self.name = robot_name
        self._session = session
        self._done = threading.Event()
        self._ok = False
        self._goal_id = ""
        self._pub = session.declare_publisher(f"{robot_name}/rmf_navigate_cmd")
        self._sub = session.declare_subscriber(
            f"{robot_name}/rmf_navigate_result", self._on_result
        )

    def _on_result(self, sample):
        try:
            raw = bytes(sample.payload.to_bytes())
            if len(raw) < 9:
                return
            str_len = struct.unpack_from('<I', raw, 4)[0]
            text = raw[8:8 + str_len - 1].decode('utf-8', errors='ignore')
            parts = text.strip().split()
            if len(parts) >= 2 and parts[0] == self._goal_id:
                if parts[1] == 'OK':
                    self._ok = True
                # Wake on both OK and FAILED so retries happen quickly
                self._done.set()
        except Exception:
            pass

    def navigate(self, x, y, yaw=0.0):
        self._goal_id = str(random.randint(1000000, 9999999))
        self._done.clear()
        self._ok = False
        cmd = cdr(f"{self._goal_id} {x:.6f} {y:.6f} {yaw:.6f}")
        print(f"  [{self.name}] goal {self._goal_id}: ({x:.2f}, {y:.2f})")
        # Send ONCE. The relay's same-destination transfer keeps the active
        # Nav2 goal alive across RMF's CANCEL+NAVIGATE retry cycles.
        # Multi-send patterns race with fast ABORT results: by the time the
        # 2nd send arrives, state may have been cleared → new preempting goal.
        self._pub.put(cmd)
        deadline = time.time() + TIMEOUT_S
        while time.time() < deadline:
            remaining = deadline - time.time()
            self._done.wait(timeout=min(remaining, 30.0))
            if self._ok:
                print(f"  [{self.name}] REACHED ({x:.2f}, {y:.2f})")
                return True
            if self._done.is_set():
                # FAILED result received — send a fresh goal_id after a pause
                self._done.clear()
                self._ok = False
                time.sleep(3.0)
                self._goal_id = str(random.randint(1000000, 9999999))
                cmd = cdr(f"{self._goal_id} {x:.6f} {y:.6f} {yaw:.6f}")
                self._pub.put(cmd)
        print(f"  [{self.name}] TIMEOUT navigating to ({x:.2f}, {y:.2f})")
        return False


DETOUR_Y1 = -1.8   # south corridor for robot_1: 0.70 m from nearest pillar row
DETOUR_Y2 =  1.8   # north corridor for robot_2


def robot1_patrol(session):
    agent = NavAgent(session, "robot_1")
    print(f"[robot_1] Swap: home → south(y={DETOUR_Y1}) → east in 1 m steps → robot_2_home")
    agent.navigate(-2.0, -0.5)          # home (immediate)
    agent.navigate(-2.0, DETOUR_Y1)     # step south into clear corridor
    # Walk east in 1 m steps — short legs keep dead-reckoning error small
    agent.navigate(-1.0, DETOUR_Y1)
    agent.navigate( 0.0, DETOUR_Y1)
    agent.navigate( 1.0, DETOUR_Y1)
    agent.navigate( 2.0, DETOUR_Y1)     # arrived at east wall
    agent.navigate( 2.0,  0.5)          # step north to robot_2_home
    print("[robot_1] Swap patrol complete")


def robot2_patrol(session):
    agent = NavAgent(session, "robot_2")
    print("[robot_2] Waiting 30 s for robot_1 to clear south corridor...")
    time.sleep(30)
    print(f"[robot_2] Swap: home → north(y={DETOUR_Y2}) → west in 1 m steps → robot_1_home")
    agent.navigate( 2.0,  0.5)          # home (immediate)
    agent.navigate( 2.0, DETOUR_Y2)     # step north into clear corridor
    # Walk west in 1 m steps
    agent.navigate( 1.0, DETOUR_Y2)
    agent.navigate( 0.0, DETOUR_Y2)
    agent.navigate(-1.0, DETOUR_Y2)
    agent.navigate(-2.0, DETOUR_Y2)     # arrived at west wall
    agent.navigate(-2.0, -0.5)          # step south to robot_1_home
    print("[robot_2] Swap patrol complete")


if __name__ == "__main__":
    print("Swap patrol: robots travel to each other's spawn (collision-free)")
    print(f"  robot_1 (blue): home → south(y={DETOUR_Y1}) → east 1 m steps → robot_2_home(2,0.5)")
    print(f"  robot_2 (red):  home [+30s] → north(y={DETOUR_Y2}) → west 1 m steps → robot_1_home(-2,-0.5)")
    print(f"Router: {ROUTER}")

    z = open_session()
    time.sleep(2)

    t1 = threading.Thread(target=robot1_patrol, args=(z,), daemon=True)
    t2 = threading.Thread(target=robot2_patrol, args=(z,), daemon=True)

    t1.start()
    t2.start()
    t1.join()
    t2.join()

    print("Both swap patrols complete. Closing.")
    z.close()
