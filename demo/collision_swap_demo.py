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

Architecture:
  Goals  → robot_N/rmf_navigate_cmd   (Zenoh CDR string: "goal_id x y yaw")
  Results← robot_N/rmf_navigate_result (Zenoh CDR string: "goal_id OK|FAILED")
  Poses  ← /fleet_states               (ROS2 topic via rclpy — 60 Hz, reliable)

Position monitoring uses rclpy + /fleet_states rather than raw Zenoh
amcl_pose subscription.  The zenoh-bridge-ros2dds only forwards amcl_pose
to Zenoh when a *bridge-protocol* subscriber declares interest (not a raw
Zenoh Python client), so the Zenoh approach silently receives nothing.
The fleet adapter already subscribes and republishes positions at 60 Hz
via /fleet_states, making rclpy the reliable path.
"""
import zenoh, time, struct, threading, random, math  # struct kept for CDR helpers

import rclpy
from rclpy.node import Node
from rmf_fleet_msgs.msg import FleetState

ROUTER = "tcp/zenoh-router:7447"
TIMEOUT_S = 300  # max wall-clock seconds per NavAgent leg (Phase 3)

# Phase constants
#
# Phase 1 routes both robots through the SOUTH OUTER CORRIDOR (y=-1.75) —
# NOT through the pillar-grid centre.  Using the centre ((0.5,0.1) from
# the main branch) causes severe AMCL drift: after navigating through the
# pillar grid, AMCL loses track and Phase 3 global-planner calls fail
# immediately because the robot's estimated position is wrong.  The outer
# corridor is easy to localise in (clear walls, no symmetric pillars) and is
# the same path Phase 3 uses, so robots stay well-localised throughout.
#
# robot_1 enters from the WEST end (home → s_in) and drives east toward s_out.
# robot_2 enters from the EAST end (home → s_out first, but nav2 approaches
#   from s_out side heading west toward s_in).
# They meet head-on somewhere around x=0, y=-1.75.
APPROACH_WP_R1   = S_OUT   # robot_1 heads east through south corridor
APPROACH_WP_R2   = S_IN    # robot_2 heads west through south corridor
APPROACH_YAW_R1  = 0.0     # heading east
APPROACH_YAW_R2  = math.pi # heading west
YIELD_DIST       = 2.0     # metres — trigger robot_2 hold
YIELD_PAUSE      = 20.0    # seconds robot_2 yields (extra time for robot_1 to pass)
APPROACH_TIMEOUT = 120.0   # seconds before giving up on Phase 1

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
# Position monitor via rclpy + /fleet_states
# ---------------------------------------------------------------------------

class FleetStateMonitor(Node):
    """
    ROS2 node that subscribes to /fleet_states (published by the free_fleet
    adapter at robot_state_update_frequency Hz) and provides thread-safe
    position and distance queries.

    This is reliable because the fleet adapter already holds bridge-protocol
    Zenoh subscriptions for amcl_pose — raw Python Zenoh clients cannot
    receive amcl_pose directly (zenoh-bridge-ros2dds only forwards when a
    bridge-protocol subscriber announces interest).
    """

    def __init__(self):
        super().__init__('collision_swap_monitor')
        self._lock = threading.Lock()
        self._pos = {'robot_1': None, 'robot_2': None}
        self.create_subscription(FleetState, '/fleet_states', self._cb, 10)

    def _cb(self, msg):
        with self._lock:
            for robot in msg.robots:
                if robot.name in self._pos:
                    self._pos[robot.name] = (robot.location.x, robot.location.y)

    def positions(self):
        with self._lock:
            return dict(self._pos)

    def distance(self):
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

    # Start rclpy in a background thread for fleet_states position monitoring.
    rclpy.init()
    monitor = FleetStateMonitor()
    spin_thread = threading.Thread(
        target=rclpy.spin, args=(monitor,), daemon=True)
    spin_thread.start()

    z = open_session()
    time.sleep(2)  # let the zenoh session settle

    # Wait for first fleet_states to arrive (confirms fleet adapter is running)
    print(f"[{ts()}] Waiting for fleet_states positions...")
    for _ in range(20):
        if monitor.distance() is not None:
            break
        time.sleep(0.5)
    else:
        print(f"[{ts()}] WARNING: no fleet_states received — positions may be stale")
    time.sleep(1)

    # Raw publishers for Phase 1 and Phase 2 hold goals.
    # Using raw pub.put() bypasses the NavAgent retry loop, which is essential
    # for the one-shot hold goal in Phase 2 (a hold goal that fails/succeeds
    # immediately should NOT be retried).
    r1_pub = z.declare_publisher("robot_1/rmf_navigate_cmd")
    r2_pub = z.declare_publisher("robot_2/rmf_navigate_cmd")

    # -----------------------------------------------------------------------
    # Phase 1: Approach via south outer corridor
    # -----------------------------------------------------------------------
    print(f"\n[{ts()}] === Phase 1: APPROACH (south outer corridor y=-1.75) ===")
    ax1, ay1 = APPROACH_WP_R1   # robot_1 → s_out (1.5, -1.75)  heading east
    ax2, ay2 = APPROACH_WP_R2   # robot_2 → s_in  (-1.5, -1.75) heading west
    print(f"[{ts()}]   robot_1 → s_out ({ax1},{ay1})  robot_2 → s_in ({ax2},{ay2})")

    # robot_1 departs first with a 4-second head start
    r1_goal_id = str(random.randint(1000000, 9999999))
    r1_pub.put(cdr(f"{r1_goal_id} {ax1:.6f} {ay1:.6f} {APPROACH_YAW_R1:.6f}"))
    print(f"[{ts()}]   [robot_1] goal {r1_goal_id}: ({ax1:.2f}, {ay1:.2f})  [head start]")

    time.sleep(4)

    # robot_2 departs 4 seconds later
    r2_goal_id = str(random.randint(1000000, 9999999))
    r2_pub.put(cdr(f"{r2_goal_id} {ax2:.6f} {ay2:.6f} {APPROACH_YAW_R2:.6f}"))
    print(f"[{ts()}]   [robot_2] goal {r2_goal_id}: ({ax2:.2f}, {ay2:.2f})")

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

    # Guard: treat (0,0) as invalid — it means no real position was received
    if r2_hold_pos is not None and math.hypot(*r2_hold_pos) < 0.01:
        r2_hold_pos = None
        collision_detected = False
        print(f"[{ts()}]   WARNING: hold position was (0,0) — fleet_states not yet populated, skipping yield")

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
    # Phase 3: Re-route via outer corridors (staggered to avoid re-collision)
    # -----------------------------------------------------------------------
    print(f"\n[{ts()}] === Phase 3: RE-ROUTE via outer corridors ===")
    #
    # After Phase 2, robot_1 is somewhere west-of-hold in the south corridor
    # (still trying to reach s_out), and robot_2 is stopped at the hold pos.
    # We stagger dispatch:
    #   1. Dispatch robot_2 north FIRST — it exits the south corridor so
    #      robot_1 no longer has an obstacle blocking s_out.
    #   2. Wait 20 s for robot_2 to clear the corridor.
    #   3. Dispatch robot_1 to continue east toward robot_2_home.
    # This prevents robot_1 from getting a fresh "Goal failed" because
    # robot_2 is still blocking the south corridor.
    #
    print(f"[{ts()}] Step 1: robot_2 exits south corridor via north route")
    print(f"[{ts()}] robot_2: north corridor  n_in → n_out → robot_1_home {ROBOT1_HOME}")

    def robot2_reroute():
        agent = NavAgent(z, "robot_2")
        print(f"[{ts()}] [robot_2] Phase 3 start: north route")
        agent.navigate(N_IN[0],        N_IN[1])
        agent.navigate(N_OUT[0],       N_OUT[1])
        agent.navigate(ROBOT1_HOME[0], ROBOT1_HOME[1])
        print(f"[{ts()}] [robot_2] Phase 3 complete — arrived at robot_1_home {ROBOT1_HOME}")

    t2 = threading.Thread(target=robot2_reroute, daemon=True)
    t2.start()

    # Give robot_2 time to clear the south corridor before robot_1 continues
    print(f"[{ts()}] Waiting 20 s for robot_2 to clear south corridor...")
    time.sleep(20)

    print(f"\n[{ts()}] Step 2: robot_1 continues east to robot_2_home")
    print(f"[{ts()}] robot_1: south corridor  s_out → robot_2_home {ROBOT2_HOME}")

    def robot1_reroute():
        agent = NavAgent(z, "robot_1")
        print(f"[{ts()}] [robot_1] Phase 3 start: south route (continuing east)")
        # robot_1 is already in the south corridor heading east;
        # s_out may already be reached — navigate directly to robot_2_home.
        agent.navigate(S_OUT[0],       S_OUT[1])
        agent.navigate(ROBOT2_HOME[0], ROBOT2_HOME[1])
        print(f"[{ts()}] [robot_1] Phase 3 complete — arrived at robot_2_home {ROBOT2_HOME}")

    t1 = threading.Thread(target=robot1_reroute, daemon=True)
    t1.start()

    t1.join()
    t2.join()

    print(f"\n[{ts()}] Collision-avoidance swap demo complete. Both robots have swapped positions.")
    rclpy.shutdown()
    z.close()


if __name__ == "__main__":
    main()
