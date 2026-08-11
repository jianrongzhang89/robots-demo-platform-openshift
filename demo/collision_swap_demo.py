#!/usr/bin/env python3
"""
Collision-avoidance swap demo: three-phase demonstration.

Phase 1 — Approach: Both robots navigate toward shared waypoint (0.5, 0.1),
           forcing a head-on collision course.  robot_1 gets a 3-second head
           start.  Goals are sent fire-and-forget via raw Zenoh put().

Phase 2 — Detect & Yield: Proximity monitor (main thread) detects when the
           robots are within 2.0 m.  robot_2 receives a one-shot hold goal at
           its current position (bypasses NavAgent retry loop).  robot_1
           continues; Nav2 local costmap plans around robot_2 as a lidar
           obstacle.  After a 15-second yield pause, Phase 3 begins.

Phase 3 — Re-route: Both robots take the proven outer corridors to their final
           swap positions (robot_1 south → robot_2_home, robot_2 north →
           robot_1_home).  NavAgent.navigate() is used here for proper
           FAILED-retry handling.

Architecture: pure Zenoh CDR — no rclpy, no BasicNavigator.
  Goals  → robot_N/rmf_navigate_cmd   (CDR string: "goal_id x y yaw")
  Results← robot_N/rmf_navigate_result (CDR string: "goal_id OK|FAILED")
  Poses  ← robot_N/amcl_pose           (CDR PoseWithCovarianceStamped)
"""
import zenoh, time, struct, threading, random, math

ROUTER = "tcp/zenoh-router:7447"
TIMEOUT_S = 300  # max wall-clock seconds per NavAgent leg (Phase 3)

# Phase constants
APPROACH_WP      = (0.5, 0.1, math.pi)   # forced head-on meeting waypoint
YIELD_DIST       = 2.0                    # metres — trigger robot_2 hold
YIELD_PAUSE      = 15.0                   # seconds robot_2 yields
APPROACH_TIMEOUT = 90.0                   # seconds before giving up on Phase 1

# Known positions
ROBOT1_HOME = (-2.0, -0.5)
ROBOT2_HOME = ( 2.0,  0.5)

# Outer-corridor waypoints (match nav_graph.yaml)
S_IN  = (-1.5, -1.75)
S_OUT = ( 1.5, -1.75)
N_IN  = ( 1.5,  1.75)
N_OUT = (-1.5,  1.75)


# ---------------------------------------------------------------------------
# CDR helpers (copied verbatim from entrypoints/swap_patrol.py)
# ---------------------------------------------------------------------------

def cdr(text):
    d = text.encode() + b'\x00'
    return b'\x00\x01\x00\x00' + struct.pack('<I', len(d)) + d


def open_session():
    conf = zenoh.Config()
    conf.insert_json5("connect/endpoints", f'["{ROUTER}"]')
    conf.insert_json5("mode", '"client"')
    conf.insert_json5("scouting/multicast/enabled", "false")
    return zenoh.open(conf)


# ---------------------------------------------------------------------------
# NavAgent (copied verbatim from entrypoints/swap_patrol.py)
# ---------------------------------------------------------------------------

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


# ---------------------------------------------------------------------------
# AMCL pose decoder
# ---------------------------------------------------------------------------

def decode_amcl_pose(sample):
    """
    Decode a CDR-encoded geometry_msgs/PoseWithCovarianceStamped sample.

    CDR layout (little-endian):
      [0:4]        encapsulation header  0x00 0x01 0x00 0x00
      [4:8]        stamp.sec             uint32 LE
      [8:12]       stamp.nanosec         uint32 LE
      [12:16]      frame_id length       uint32 LE (includes null terminator)
      [16:16+len]  frame_id bytes + null
      [pad to 8-byte absolute boundary]
      [X:X+8]      position.x            float64 LE
      [X+8:X+16]   position.y            float64 LE

    For frame_id="map" (len=4): X=24.

    Returns (x, y) on success, (None, None) on any error.
    """
    try:
        raw = bytes(sample.payload.to_bytes())
        if len(raw) < 28:
            return None, None
        str_len = struct.unpack_from('<I', raw, 12)[0]
        # Pad end of string to the next 8-byte absolute-offset boundary
        x_offset = ((16 + str_len + 7) // 8) * 8
        if len(raw) < x_offset + 16:
            return None, None
        x = struct.unpack_from('<d', raw, x_offset)[0]
        y = struct.unpack_from('<d', raw, x_offset + 8)[0]
        return x, y
    except Exception:
        return None, None


# ---------------------------------------------------------------------------
# Pose monitor
# ---------------------------------------------------------------------------

class PoseMonitor:
    """
    Subscribes to both robots' amcl_pose topics over Zenoh and provides
    thread-safe position and distance queries.
    """

    def __init__(self, session):
        self._lock = threading.Lock()
        self._pos = {'robot_1': None, 'robot_2': None}
        self._sub1 = session.declare_subscriber('robot_1/amcl_pose', self._on_r1)
        self._sub2 = session.declare_subscriber('robot_2/amcl_pose', self._on_r2)

    def _on_r1(self, sample):
        x, y = decode_amcl_pose(sample)
        if x is not None:
            with self._lock:
                self._pos['robot_1'] = (x, y)

    def _on_r2(self, sample):
        x, y = decode_amcl_pose(sample)
        if x is not None:
            with self._lock:
                self._pos['robot_2'] = (x, y)

    def positions(self):
        """Return a snapshot dict {'robot_1': (x,y) or None, 'robot_2': ...}."""
        with self._lock:
            return dict(self._pos)

    def distance(self):
        """Return Euclidean distance between robots, or None if either pose is unknown."""
        with self._lock:
            p1 = self._pos['robot_1']
            p2 = self._pos['robot_2']
        if p1 is None or p2 is None:
            return None
        return math.sqrt((p1[0] - p2[0]) ** 2 + (p1[1] - p2[1]) ** 2)


# ---------------------------------------------------------------------------
# Timestamp helper
# ---------------------------------------------------------------------------

def ts():
    return time.strftime('%H:%M:%S')


# ---------------------------------------------------------------------------
# Main demo logic
# ---------------------------------------------------------------------------

def main():
    print(f"[{ts()}] Collision-avoidance swap demo starting")
    print(f"  Phase 1 : Both robots approach shared waypoint {APPROACH_WP[:2]}")
    print(f"  Phase 2 : Detect proximity < {YIELD_DIST} m → robot_2 yields {YIELD_PAUSE} s")
    print(f"  Phase 3 : Re-route via outer corridors → final swap positions")
    print(f"  Router  : {ROUTER}")

    z = open_session()
    time.sleep(2)  # let the zenoh session settle

    monitor = PoseMonitor(z)
    time.sleep(3)  # allow initial amcl_pose messages to arrive

    # Raw publishers for Phase 1 and Phase 2 hold goals.
    # Using raw pub.put() bypasses the NavAgent retry loop, which is essential
    # for the one-shot hold goal in Phase 2 (a hold goal that fails/succeeds
    # immediately should NOT be retried).
    r1_pub = z.declare_publisher("robot_1/rmf_navigate_cmd")
    r2_pub = z.declare_publisher("robot_2/rmf_navigate_cmd")

    # -----------------------------------------------------------------------
    # Phase 1: Approach
    # -----------------------------------------------------------------------
    print(f"\n[{ts()}] === Phase 1: APPROACH ===")
    ax, ay, ayaw = APPROACH_WP

    # robot_1 departs first (3-second head start)
    r1_goal_id = str(random.randint(1000000, 9999999))
    r1_pub.put(cdr(f"{r1_goal_id} {ax:.6f} {ay:.6f} {ayaw:.6f}"))
    print(f"[{ts()}]   [robot_1] goal {r1_goal_id}: ({ax:.2f}, {ay:.2f})  [head start]")

    time.sleep(3)

    # robot_2 departs 3 seconds later
    r2_goal_id = str(random.randint(1000000, 9999999))
    r2_pub.put(cdr(f"{r2_goal_id} {ax:.6f} {ay:.6f} {ayaw:.6f}"))
    print(f"[{ts()}]   [robot_2] goal {r2_goal_id}: ({ax:.2f}, {ay:.2f})")

    # Poll proximity; stop when threshold crossed or timeout expires
    deadline = time.time() + APPROACH_TIMEOUT
    collision_detected = False
    r2_hold_pos = None
    last_print = 0.0

    while time.time() < deadline:
        dist = monitor.distance()
        now = time.time()
        if dist is not None:
            # Print distance update every 5 seconds to avoid log spam
            if now - last_print >= 5.0:
                print(f"[{ts()}]   robot distance: {dist:.2f} m")
                last_print = now
            if dist < YIELD_DIST:
                collision_detected = True
                pos = monitor.positions()
                r2_hold_pos = pos.get('robot_2')
                print(f"[{ts()}]   COLLISION COURSE DETECTED — distance {dist:.2f} m < {YIELD_DIST} m")
                break
        time.sleep(0.5)

    if not collision_detected:
        print(f"[{ts()}]   WARNING: proximity threshold not reached within "
              f"{APPROACH_TIMEOUT:.0f} s — proceeding anyway")

    # -----------------------------------------------------------------------
    # Phase 2: Detect & Yield
    # -----------------------------------------------------------------------
    print(f"\n[{ts()}] === Phase 2: DETECT & YIELD ===")

    if collision_detected and r2_hold_pos is not None:
        hx, hy = r2_hold_pos
        print(f"[{ts()}] robot_2 YIELD: hold at current position ({hx:.2f}, {hy:.2f})")
        # One-shot hold goal — direct put() bypasses NavAgent retry loop.
        # With yaw_goal_tolerance: 3.14159 in nav2 params, Nav2 considers
        # the goal reached immediately → relay reports OK → robot_2 stops.
        hold_id = str(random.randint(1000000, 9999999))
        r2_pub.put(cdr(f"{hold_id} {hx:.6f} {hy:.6f} 0.000000"))
        print(f"[{ts()}] robot_1 continues — Nav2 local costmap plans around robot_2")
        print(f"[{ts()}] Yield pause: {YIELD_PAUSE:.0f} s ...")
        time.sleep(YIELD_PAUSE)
        print(f"[{ts()}] Yield pause complete")
    else:
        print(f"[{ts()}] Proximity not detected — skipping hold, proceeding to Phase 3")

    # -----------------------------------------------------------------------
    # Phase 3: Re-route via outer corridors
    # -----------------------------------------------------------------------
    print(f"\n[{ts()}] === Phase 3: RE-ROUTE via outer corridors ===")
    print(f"[{ts()}] robot_1: south corridor  s_in → s_out → robot_2_home {ROBOT2_HOME}")
    print(f"[{ts()}] robot_2: north corridor  n_in → n_out → robot_1_home {ROBOT1_HOME}")

    def robot1_reroute():
        agent = NavAgent(z, "robot_1")
        print(f"[{ts()}] [robot_1] Phase 3 start: south route")
        agent.navigate(S_IN[0],       S_IN[1])
        agent.navigate(S_OUT[0],      S_OUT[1])
        agent.navigate(ROBOT2_HOME[0], ROBOT2_HOME[1])
        print(f"[{ts()}] [robot_1] Phase 3 complete — arrived at robot_2_home {ROBOT2_HOME}")

    def robot2_reroute():
        agent = NavAgent(z, "robot_2")
        print(f"[{ts()}] [robot_2] Phase 3 start: north route")
        agent.navigate(N_IN[0],       N_IN[1])
        agent.navigate(N_OUT[0],      N_OUT[1])
        agent.navigate(ROBOT1_HOME[0], ROBOT1_HOME[1])
        print(f"[{ts()}] [robot_2] Phase 3 complete — arrived at robot_1_home {ROBOT1_HOME}")

    t1 = threading.Thread(target=robot1_reroute, daemon=True)
    t2 = threading.Thread(target=robot2_reroute, daemon=True)
    t1.start()
    t2.start()
    t1.join()
    t2.join()

    print(f"\n[{ts()}] Collision-avoidance swap demo complete. Both robots have swapped positions.")
    z.close()


if __name__ == "__main__":
    main()
