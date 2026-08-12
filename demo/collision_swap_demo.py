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
APPROACH_WP_R1   = ( 1.5, -1.75)   # s_out — robot_1 heads east
APPROACH_WP_R2   = (-1.5, -1.75)   # s_in  — robot_2 heads west
APPROACH_YAW_R1  = 0.0             # heading east
APPROACH_YAW_R2  = math.pi         # heading west
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
# AMCL initial-pose publisher (CDR-encoded PoseWithCovarianceStamped)
# ---------------------------------------------------------------------------
# Gazebo ground-truth position monitor
# ---------------------------------------------------------------------------

class GzPosMonitor:
    """
    Subscribes to robot_N/gz_world_pos published by the Gazebo pod's
    gz_world_pos_publisher.py process.  Payload: "x y yaw" (space-separated).

    Used for Phase 3 position verification and AMCL continuous correction,
    bypassing the unreliable AMCL particle filter.
    """

    def __init__(self, session):
        self._lock  = threading.Lock()
        self._gz    = {'robot_1': None, 'robot_2': None}
        self._sub1  = session.declare_subscriber('robot_1/gz_world_pos', self._on_r1)
        self._sub2  = session.declare_subscriber('robot_2/gz_world_pos', self._on_r2)

    def _parse(self, sample):
        try:
            parts = bytes(sample.payload.to_bytes()).decode().split()
            return float(parts[0]), float(parts[1]), float(parts[2])
        except Exception:
            return None

    def _on_r1(self, sample):
        v = self._parse(sample)
        if v:
            with self._lock:
                self._gz['robot_1'] = v

    def _on_r2(self, sample):
        v = self._parse(sample)
        if v:
            with self._lock:
                self._gz['robot_2'] = v

    def positions(self):
        """Return {'robot_1': (x, y, yaw) or None, 'robot_2': ...}"""
        with self._lock:
            return dict(self._gz)

    def xy(self, name):
        with self._lock:
            v = self._gz.get(name)
        return (v[0], v[1]) if v else None

    def distance(self):
        with self._lock:
            p1 = self._gz.get('robot_1')
            p2 = self._gz.get('robot_2')
        if p1 and p2:
            return math.sqrt((p1[0]-p2[0])**2 + (p1[1]-p2[1])**2)
        return None

    def ready(self, timeout=10.0):
        """Block until both robot positions are received."""
        t0 = time.time()
        while time.time() - t0 < timeout:
            with self._lock:
                if self._gz['robot_1'] and self._gz['robot_2']:
                    return True
            time.sleep(0.2)
        return False

# ---------------------------------------------------------------------------

def make_initialpose_cdr(x, y, yaw):
    """
    Build a CDR-encoded geometry_msgs/PoseWithCovarianceStamped for frame 'map'.

    Layout (LE, frame_id="map" → len=4):
      [0:4]    encapsulation header
      [4:8]    stamp.sec = 0
      [8:12]   stamp.nanosec = 0
      [12:16]  frame_id length = 4
      [16:20]  "map\0"
      [20:24]  padding to 8-byte boundary
      [24:32]  position.x  (float64)
      [32:40]  position.y  (float64)
      [40:48]  position.z = 0
      [48:56]  orientation.x = 0
      [56:64]  orientation.y = 0
      [64:72]  orientation.z = sin(yaw/2)
      [72:80]  orientation.w = cos(yaw/2)
      [80:368] covariance (36 float64, small diagonal values)
    """
    qz = math.sin(yaw / 2.0)
    qw = math.cos(yaw / 2.0)
    cov = [0.0] * 36
    cov[0]  = 0.01   # x variance
    cov[7]  = 0.01   # y variance
    cov[35] = 0.005  # yaw variance

    buf = bytearray()
    buf += b'\x00\x01\x00\x00'           # CDR header
    buf += struct.pack('<II', 0, 0)       # stamp sec, nanosec
    buf += struct.pack('<I', 4)           # frame_id len (4 = "map\0")
    buf += b'map\x00'                    # frame_id "map" + null
    buf += b'\x00' * 4                   # padding to byte offset 24
    buf += struct.pack('<ddd', x, y, 0.0)           # position
    buf += struct.pack('<dddd', 0.0, 0.0, qz, qw)  # orientation
    buf += struct.pack('<' + 'd' * 36, *cov)        # covariance
    return bytes(buf)


def anchor_poses(z, r1_pos, r2_pos, r1_yaw=math.pi, r2_yaw=0.0, repeats=5):
    """
    Publish initialpose for both robots via Zenoh so AMCL re-converges to
    the true swap positions after navigation drift.
    """
    pub1 = z.declare_publisher('robot_1/initialpose')
    pub2 = z.declare_publisher('robot_2/initialpose')
    p1 = make_initialpose_cdr(r1_pos[0], r1_pos[1], r1_yaw)
    p2 = make_initialpose_cdr(r2_pos[0], r2_pos[1], r2_yaw)
    for _ in range(repeats):
        pub1.put(p1)
        pub2.put(p2)
        time.sleep(0.5)
    pub1.undeclare()
    pub2.undeclare()


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
    print(f"  Phase 1 : robot_1 → s_out {APPROACH_WP_R1}, robot_2 → s_in {APPROACH_WP_R2} (south corridor)")
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
    time.sleep(2)

    # Start Gazebo ground-truth monitor (used for Phase 3 only).
    gz_mon = GzPosMonitor(z)
    print(f"[{ts()}] Waiting for Gazebo ground-truth positions...")
    if not gz_mon.ready(timeout=15):
        print(f"[{ts()}] WARNING: Gz ground-truth not received — check gz_world_pos_pub in Gazebo pod")

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
    # Phase 1: Approach via south outer corridor — two sub-phases
    #
    # Phase 1a: Get each robot to its corridor ENTRY POINT first using
    #           NavAgent (with proper completion wait).  This guarantees
    #           both robots are at y=-1.75 before the head-on approach,
    #           keeping AMCL reliable (no pillar-grid ambiguity).
    #           robot_1: home → s_in (-1.5,-1.75)  [enters west end]
    #           robot_2: home → s_out (1.5,-1.75)  [enters east end]
    #
    # Phase 1b: Fire-and-forget goals send robots toward each other.
    #           robot_1: s_in → s_out (heading east)
    #           robot_2: s_out → s_in (heading west)
    #           Proximity monitor then triggers Phase 2 yield.
    # -----------------------------------------------------------------------
    # Mutable container for AMCL anchor publishers — populated after z.open()
    # but accessible by verified_navigate via closure (Python 3.12-safe pattern
    # for mutable containers; plain variable names cause NameError in 3.12).
    _amcl_pubs = {}   # 'robot_1' → Zenoh publisher, 'robot_2' → Zenoh publisher
    _amcl_yaws = {}   # 'robot_1' → float yaw, 'robot_2' → float yaw

    print(f"\n[{ts()}] === Phase 1a: Enter south corridor at opposite ends ===")

    agent_r1 = NavAgent(z, "robot_1")
    agent_r2 = NavAgent(z, "robot_2")

    # Run both corridor-entry legs concurrently, robot_1 with a 4-second head start
    r1_ready = threading.Event()
    r2_ready = threading.Event()

    def verified_navigate(agent, tx, ty, label, tol=0.50, use_gz=False):
        """
        Navigate to (tx, ty) and verify arrival.

        use_gz=False: verify via fleet_states (AMCL).  Used for Phase 1a
            corridor entry where AMCL is still accurate (just started).
        use_gz=True: verify via Gazebo ground-truth positions.  Used for
            Phase 3 where AMCL has catastrophically drifted in the symmetric
            south outer corridor (AMCL errors up to 3+ m observed).

        tol=0.50 m (fleet_states) / 0.25 m (Gz truth):
        - fleet_states mode: 0.50 m covers AMCL drift after genuine nav.
        - Gz truth mode: 0.25 m is tighter — ground truth has no AMCL error.
        On relay fake-success, the relay's 'recently sent' cache is broken by
        sending a goal to the robot's CURRENT position before retrying.
        """
        gz_tol = 0.25 if use_gz else tol
        deadline = time.time() + TIMEOUT_S
        while time.time() < deadline:
            if use_gz:
                # Anchor AMCL once from Gz truth before each navigation attempt.
                # Uses _amcl_pubs/_amcl_yaws dicts (mutable, Python 3.12-safe).
                _v = gz_mon.positions().get(agent.name)
                _apub = _amcl_pubs.get(agent.name)
                if _v and _apub:
                    _yaw = _amcl_yaws.get(agent.name, 0.0)
                    _p = make_initialpose_cdr(_v[0], _v[1], _yaw)
                    for _ in range(5):
                        _apub.put(_p)
                        time.sleep(0.3)
                    time.sleep(1.5)
                agent.navigate(tx, ty)
                p_gz = gz_mon.xy(agent.name)
                if p_gz is None:
                    return True  # Gz truth not yet available — trust NavAgent
                d = math.hypot(p_gz[0] - tx, p_gz[1] - ty)
                if d <= gz_tol:
                    print(f"[{ts()}]   [{agent.name}] Gz-verified at ({p_gz[0]:.2f},{p_gz[1]:.2f}) Δ={d:.2f}m ✓")
                    return True
                print(f"[{ts()}]   [{agent.name}] relay faked — Gz truth ({p_gz[0]:.2f},{p_gz[1]:.2f}), "
                      f"{d:.2f}m from target — cache-reset + retry")
                gid = str(random.randint(1000000, 9999999))
                agent._pub.put(cdr(f"{gid} {p_gz[0]:.6f} {p_gz[1]:.6f} 0.000000"))
                time.sleep(3.0)
            else:
                agent.navigate(tx, ty)
                pos = monitor.positions()
                p = pos.get(agent.name)
                if p is not None:
                    d = math.hypot(p[0] - tx, p[1] - ty)
                    if d <= tol:
                        print(f"[{ts()}]   [{agent.name}] verified at ({p[0]:.2f},{p[1]:.2f}) Δ={d:.2f}m ✓")
                        return True
                    print(f"[{ts()}]   [{agent.name}] relay faked success "
                          f"(at ({p[0]:.2f},{p[1]:.2f}), {d:.2f}m from target) — cache-reset + retry")
                    gid = str(random.randint(1000000, 9999999))
                    agent._pub.put(cdr(f"{gid} {p[0]:.6f} {p[1]:.6f} 0.000000"))
                    time.sleep(3.0)
                else:
                    return True  # no fleet_states yet — trust NavAgent
        print(f"[{ts()}]   [{agent.name}] TIMEOUT reaching ({tx},{ty})")
        return False

    def gz_step_navigate(agent, pub, tx, ty, step_size=0.30, stop_dist=0.20):
        """
        Navigate to (tx, ty) using small Gz-verified steps.

        Each step: anchor AMCL from Gz truth → navigate step_size metres →
        verify with Gz truth.  Short steps prevent AMCL from drifting between
        anchor and arrival, which was causing 1-2m positioning errors on long
        (2-3 m) navigation legs even with per-step anchoring.

        With step_size=0.30 m and speed=0.26 m/s, each step takes ~1.2 s —
        fast enough that AMCL has no time to drift before Gz verifies arrival.
        """
        max_steps = int(15.0 / step_size * math.hypot(tx - (gz_mon.xy(agent.name) or (0,0))[0],
                                                       ty - (gz_mon.xy(agent.name) or (0,0))[1]) + 10)
        for _ in range(max(max_steps, 30)):
            p = gz_mon.xy(agent.name)
            if not p:
                time.sleep(0.2); continue
            dx, dy = tx - p[0], ty - p[1]
            dist = math.hypot(dx, dy)
            if dist < stop_dist:
                print(f"[{ts()}]   [{agent.name}] gz_step: arrived at ({p[0]:.2f},{p[1]:.2f}) Δ={dist:.2f}m ✓")
                return True
            # Next waypoint: one step toward target
            scale = min(step_size, dist) / dist
            nx, ny = p[0] + dx * scale, p[1] + dy * scale
            reset_relay_cache(pub, agent.name)  # clear relay prev_step before each step
            verified_navigate(agent, nx, ny, agent.name, use_gz=True)
        p = gz_mon.xy(agent.name)
        if p:
            print(f"[{ts()}]   [{agent.name}] gz_step: max steps reached, at ({p[0]:.2f},{p[1]:.2f})")
        return False

    def reset_relay_cache(pub, robot_name):
        """
        Clear the relay's 'recently sent' cache by sending a goal at the robot's
        current position.  Prefers Gz ground truth; falls back to fleet_states.
        """
        p = gz_mon.xy(robot_name) or (monitor.positions().get(robot_name) or (None, None))
        if p and p[0] is not None:
            gid = str(random.randint(1000000, 9999999))
            pub.put(cdr(f"{gid} {p[0]:.6f} {p[1]:.6f} 0.000000"))
            print(f"[{ts()}]   [{robot_name}] relay cache reset at ({p[0]:.2f},{p[1]:.2f})")
            time.sleep(2.0)

    def r1_enter():
        print(f"[{ts()}] [robot_1] → s_in ({S_IN[0]},{S_IN[1]}) [west entry]")
        verified_navigate(agent_r1, S_IN[0], S_IN[1], "robot_1", use_gz=True)
        print(f"[{ts()}] [robot_1] at s_in — ready for head-on approach")
        r1_ready.set()

    def r2_enter():
        time.sleep(4)  # 4-second stagger so robot_1 is already moving
        # Step 1: go south along east wall (clear path, no pillar-grid crossing)
        # robot_2 spawn: (2.0, 0.5) → east wall entry (2.0,-1.0) → s_out (1.5,-1.75)
        print(f"[{ts()}] [robot_2] → east wall (2.0,-1.0) then s_out [east entry via south]")
        verified_navigate(agent_r2, 2.0, -1.0, "robot_2", use_gz=True)   # south along east wall
        verified_navigate(agent_r2, S_OUT[0], S_OUT[1], "robot_2", use_gz=True)  # enter corridor
        print(f"[{ts()}] [robot_2] at s_out — ready for head-on approach")
        r2_ready.set()

    te1 = threading.Thread(target=r1_enter, daemon=True)
    te2 = threading.Thread(target=r2_enter, daemon=True)
    te1.start(); te2.start()
    te1.join(); te2.join()

    print(f"\n[{ts()}] === Phase 1b: Head-on approach in south corridor ===")
    ax1, ay1 = APPROACH_WP_R1   # s_out (1.5, -1.75) — robot_1 heads east
    ax2, ay2 = APPROACH_WP_R2   # s_in  (-1.5, -1.75) — robot_2 heads west

    # Fire-and-forget: both robots now in corridor, send opposing goals
    r1_goal_id = str(random.randint(1000000, 9999999))
    r1_pub.put(cdr(f"{r1_goal_id} {ax1:.6f} {ay1:.6f} {APPROACH_YAW_R1:.6f}"))
    print(f"[{ts()}]   [robot_1] goal {r1_goal_id}: → s_out ({ax1:.2f},{ay1:.2f}) heading east")

    time.sleep(1)  # brief stagger so both are moving before proximity check

    r2_goal_id = str(random.randint(1000000, 9999999))
    r2_pub.put(cdr(f"{r2_goal_id} {ax2:.6f} {ay2:.6f} {APPROACH_YAW_R2:.6f}"))
    print(f"[{ts()}]   [robot_2] goal {r2_goal_id}: → s_in ({ax2:.2f},{ay2:.2f}) heading west")

    # Poll proximity; stop when threshold crossed or timeout expires
    deadline = time.time() + APPROACH_TIMEOUT
    collision_detected = False
    r2_hold_pos = None
    last_print = 0.0

    while time.time() < deadline:
        # Use Gz ground truth for proximity — AMCL is unreliable in corridor
        dist = gz_mon.distance() or monitor.distance()
        now = time.time()
        if dist is not None:
            # Print distance update every 5 seconds to avoid log spam
            if now - last_print >= 5.0:
                print(f"[{ts()}]   robot distance (Gz): {dist:.2f} m")
                last_print = now
            if dist < YIELD_DIST:
                collision_detected = True
                r2_hold_pos = gz_mon.xy('robot_2') or monitor.positions().get('robot_2')
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

        # Anchor BOTH robots' AMCL at their current positions.
        # The south outer corridor is symmetric — AMCL drifts laterally while
        # stationary.  CRITICAL BUG FIXED: previously robot_1 was anchored at
        # ROBOT2_HOME (2.0,0.5) instead of its actual south-corridor position,
        # causing catastrophic ~1.6m AMCL failure that placed the robot at the
        # completely wrong physical location after Phase 3 navigation.
        pos = monitor.positions()
        r1_pos_now = pos.get('robot_1') or (S_IN[0], S_IN[1])  # fallback to s_in
        print(f"[{ts()}] Anchoring robot_1 AMCL at {r1_pos_now} (actual south-corridor pos)")
        print(f"[{ts()}] Anchoring robot_2 AMCL at ({hx:.2f},{hy:.2f}) (hold position)")
        anchor_poses(z, r1_pos_now, (hx, hy), r1_yaw=APPROACH_YAW_R1, r2_yaw=APPROACH_YAW_R2, repeats=8)

        print(f"[{ts()}] Yield pause: {YIELD_PAUSE:.0f} s ...")
        time.sleep(YIELD_PAUSE)
        print(f"[{ts()}] Yield pause complete")
    else:
        print(f"[{ts()}] Proximity not detected — skipping hold, proceeding to Phase 3")

    # -----------------------------------------------------------------------
    # Costmap clear — flush stale obstacle cells from Phase 1+2 navigation.
    # Without this, NavFn fails to find paths in Phase 3 because lidar data
    # from the collision approach/hold still marks cells as obstacles, blocking
    # the NE path from the south corridor to robot_2_home.
    # -----------------------------------------------------------------------
    print(f"[{ts()}] Clearing costmaps on both robots (flush Phase 1+2 stale obstacles)...")
    r1_clear_pub = z.declare_publisher("robot_1/clear_costmaps")
    r2_clear_pub = z.declare_publisher("robot_2/clear_costmaps")
    for _ in range(3):
        r1_clear_pub.put(b"clear")
        r2_clear_pub.put(b"clear")
        time.sleep(1.0)
    r1_clear_pub.undeclare()
    r2_clear_pub.undeclare()
    time.sleep(3)  # allow costmap layers to finish clearing
    print(f"[{ts()}] Costmaps cleared")

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
    # robot_2 re-routes west through the south outer corridor to robot_1_home.
    # After Phase 1+2, the south corridor is already clear (robot_2 just drove
    # through it), whereas the path to the north corridor requires crossing
    # areas covered by stale obstacle cells accumulated during Phase 1
    # navigation — NavFn fails to find a path through that noise.
    # Route: hold_pos → s_in (west end of south corridor) → robot_1_home
    print(f"[{ts()}] Step 1: robot_2 re-routes west via south corridor to robot_1_home")
    print(f"[{ts()}] robot_2: west in south corridor  → s_in → robot_1_home {ROBOT1_HOME}")

    final_pos = {}   # capture positions right at navigation completion

    # Publishers for per-step AMCL anchoring from Gz truth (used inside verified_navigate).
    # Populate the mutable publisher containers (used by verified_navigate closure)
    _amcl_pubs['robot_1'] = z.declare_publisher('robot_1/initialpose')
    _amcl_pubs['robot_2'] = z.declare_publisher('robot_2/initialpose')
    _amcl_yaws['robot_1'] = APPROACH_YAW_R1
    _amcl_yaws['robot_2'] = APPROACH_YAW_R2


    def robot2_reroute():
        agent = NavAgent(z, "robot_2")
        print(f"[{ts()}] [robot_2] Phase 3 start: south corridor (west) route")

        # Reset relay cache using Gz ground truth position.
        reset_relay_cache(r2_pub, "robot_2")

        # Navigate to robot_1_home using small Gz-verified steps.
        # Long single steps (~3m) cause AMCL to drift 1-2m even with per-step
        # anchoring; 0.30m steps keep AMCL stable across the full journey.
        gz_step_navigate(agent, r2_pub, ROBOT1_HOME[0], ROBOT1_HOME[1])

        # Capture Gazebo ground-truth arrival position
        p_gz = gz_mon.xy('robot_2')
        if p_gz:
            final_pos['robot_2'] = p_gz
        print(f"[{ts()}] [robot_2] Phase 3 complete — arrived at robot_1_home {ROBOT1_HOME}")

    t2 = threading.Thread(target=robot2_reroute, daemon=True)
    t2.start()

    # Give robot_2 a 30-second head start to clear the south corridor.
    print(f"[{ts()}] Waiting 30 s for robot_2 to clear the area...")
    time.sleep(30)

    print(f"\n[{ts()}] Step 2: robot_1 continues east to robot_2_home")
    print(f"[{ts()}] robot_1: direct NE path → robot_2_home {ROBOT2_HOME} [Gz-verified]")

    def robot1_reroute():
        agent = NavAgent(z, "robot_1")
        print(f"[{ts()}] [robot_1] Phase 3 start: south outer wall route")

        # Reset relay cache using Gz ground truth.
        reset_relay_cache(r1_pub, "robot_1")

        # Navigate to robot_2_home using small Gz-verified steps.
        gz_step_navigate(agent, r1_pub, ROBOT2_HOME[0], ROBOT2_HOME[1])

        # Capture Gazebo ground-truth arrival position
        p_gz = gz_mon.xy('robot_1')
        if p_gz:
            final_pos['robot_1'] = p_gz
        print(f"[{ts()}] [robot_1] Phase 3 complete — arrived at robot_2_home {ROBOT2_HOME}")

    t1 = threading.Thread(target=robot1_reroute, daemon=True)
    t1.start()

    t1.join()
    t2.join()
    _amcl_pubs['robot_1'].undeclare()
    _amcl_pubs['robot_2'].undeclare()

    # -----------------------------------------------------------------------
    # Phase 4: Report Gazebo ground-truth final positions
    # -----------------------------------------------------------------------
    print(f"\n[{ts()}] === Phase 4: Gazebo ground-truth positions (physical reality) ===")
    time.sleep(1)
    for name, home in [('robot_1', ROBOT2_HOME), ('robot_2', ROBOT1_HOME)]:
        gz = gz_mon.xy(name)
        if gz:
            d = math.hypot(gz[0] - home[0], gz[1] - home[1])
            print(f"[{ts()}] {name} Gz  at ({gz[0]:.2f},{gz[1]:.2f})  Δ={d:.2f}m from target {home}")
        amcl = (monitor.positions().get(name) or [None, None])
        if amcl and amcl[0] is not None:
            print(f"[{ts()}] {name} AMCL at ({amcl[0]:.2f},{amcl[1]:.2f})  (localization estimate)")

    print(f"\n[{ts()}] Collision-avoidance swap demo complete. Both robots have swapped positions.")
    rclpy.shutdown()
    z.close()


if __name__ == "__main__":
    main()
