#!/usr/bin/env python3
"""
Swap-position patrol: robot_1 and robot_2 travel to each other's spawn position.

The tb3_sandbox has a 3×3 grid of internal pillars at
  x ∈ {-1.1, 0, 1.1}  ×  y ∈ {-1.1, 0, 1.1}
which block diagonal cross-sandbox paths. Safe clear corridors exist at y=±0.6
(≥0.5 m from both pillar rows) and along the outer boundary (x=±2, no pillars).

Routes:
  robot_1 (blue): home → meeting_pt(0,0) → south(0,-0.6) → east(2,-0.6) → robot_2_home(2,0.5)
  robot_2 (red):  home → [30s delay] → meeting_pt → north(0,0.6) → west(-2,0.6) → robot_1_home(-2,-0.5)

Collision avoidance: robot_2 starts 30 s after robot_1 to avoid sharing the
meeting_point area. After meeting_point, robot_1 uses the south corridor (y=-0.6)
and robot_2 uses the north corridor (y=+0.6), keeping 1.2 m separation.

Both robots use CDR-encoded direct Zenoh dispatch, bypassing the RMF traffic
scheduler.
"""
import zenoh, time, struct, threading, random

ROUTER = "tcp/zenoh-router:7447"
TIMEOUT_S = 90  # max wall-clock seconds to wait per leg


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
            if len(parts) >= 2 and parts[0] == self._goal_id and parts[1] == 'OK':
                self._ok = True
                self._done.set()
        except Exception:
            pass

    def navigate(self, x, y, yaw=0.0):
        self._goal_id = str(random.randint(1000000, 9999999))
        self._done.clear()
        self._ok = False
        cmd = cdr(f"{self._goal_id} {x:.6f} {y:.6f} {yaw:.6f}")
        print(f"  [{self.name}] goal {self._goal_id}: ({x:.2f}, {y:.2f})")
        for _ in range(4):
            self._pub.put(cmd)
            time.sleep(0.8)
        self._done.wait(timeout=TIMEOUT_S)
        if self._ok:
            print(f"  [{self.name}] REACHED ({x:.2f}, {y:.2f})")
            return True
        else:
            print(f"  [{self.name}] TIMEOUT navigating to ({x:.2f}, {y:.2f})")
            return False


def robot1_patrol(session):
    agent = NavAgent(session, "robot_1")
    print("[robot_1] Swap: home → meeting_pt → south(0,-0.6) → east(2,-0.6) → robot_2_home")
    agent.navigate(-2.0, -0.5)   # robot_1_home (immediate)
    agent.navigate( 0.0,  0.0)   # meeting_point
    agent.navigate( 0.0, -0.6)   # move south into clear corridor (y=-0.6, ≥0.5m from pillars)
    agent.navigate( 2.0, -0.6)   # travel east along clear corridor
    agent.navigate( 2.0,  0.5)   # robot_2_home (no pillars at x=2)
    print("[robot_1] Swap patrol complete")


def robot2_patrol(session):
    agent = NavAgent(session, "robot_2")
    # Delay so robot_1 clears the meeting_point region first (~30 s)
    print("[robot_2] Waiting 30 s for robot_1 to clear meeting_point corridor...")
    time.sleep(30)
    print("[robot_2] Swap: home → meeting_pt → north(0,0.6) → west(-2,0.6) → robot_1_home")
    agent.navigate( 2.0,  0.5)   # robot_2_home (immediate)
    agent.navigate( 0.0,  0.0)   # meeting_point
    agent.navigate( 0.0,  0.6)   # move north into clear corridor (y=+0.6, ≥0.5m from pillars)
    agent.navigate(-2.0,  0.6)   # travel west along clear corridor
    agent.navigate(-2.0, -0.5)   # robot_1_home (no pillars at x=-2)
    print("[robot_2] Swap patrol complete")


if __name__ == "__main__":
    print("Swap patrol: robots travel to each other's spawn (collision-free)")
    print(f"  robot_1 (blue): home → center → south-corridor(y=-0.6) → robot_2_home(2,0.5)")
    print(f"  robot_2 (red):  home → [30s] → center → north-corridor(y=+0.6) → robot_1_home(-2,-0.5)")
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
