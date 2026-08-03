#!/usr/bin/env python3
"""
Direct dual-patrol controller: commands both robots to meeting_point via Zenoh,
bypassing RMF traffic scheduler to avoid negotiation conflicts.

Robot_1: robot_1_home (-2.0,-0.5) → mid_west (-1.0,-0.25) → meeting_point (0,0)
Robot_2: robot_2_home (2.0,0.5) → meeting_point (0,0)

Uses CDR-encoded std_msgs/String on robot_N/rmf_navigate_cmd keys.
Subscribes to robot_N/rmf_navigate_result for completion confirmation.
"""
import zenoh, time, struct, threading, random, sys

ROUTER = "tcp/zenoh-router:7447"
TIMEOUT_S = 90  # max seconds to wait per leg

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
        self._pub = session.declare_publisher(f"{robot_name}/rmf_navigate_cmd")
        self._sub = session.declare_subscriber(
            f"{robot_name}/rmf_navigate_result", self._on_result
        )

    def _on_result(self, sample):
        try:
            raw = bytes(sample.payload.to_bytes())
            # CDR: 4-byte header + 4-byte length + string bytes
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
    print("[robot_1] Starting patrol: home → mid_west → meeting_point")
    agent.navigate(-2.0, -0.5)      # robot_1_home (immediate)
    agent.navigate(-1.0, -0.25)     # mid_west
    agent.navigate(0.0, 0.0)        # meeting_point
    print("[robot_1] Patrol complete")

def robot2_patrol(session):
    agent = NavAgent(session, "robot_2")
    print("[robot_2] Starting patrol: home → meeting_point")
    agent.navigate(2.0, 0.5)        # robot_2_home (immediate)
    agent.navigate(0.0, 0.0)        # meeting_point
    print("[robot_2] Patrol complete")


if __name__ == "__main__":
    print("Dual patrol: both robots converging at meeting_point (0,0)")
    print(f"Router: {ROUTER}")

    z = open_session()
    time.sleep(2)

    t1 = threading.Thread(target=robot1_patrol, args=(z,), daemon=True)
    t2 = threading.Thread(target=robot2_patrol, args=(z,), daemon=True)

    t1.start()
    t2.start()
    t1.join()
    t2.join()

    print("Both patrols complete. Closing.")
    z.close()
