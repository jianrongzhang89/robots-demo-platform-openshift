#!/usr/bin/env python3
"""
RMF + Nav2 LiDAR collision-avoidance swap demo.

Three visible layers:
  Layer 1 — RMF traffic planning: both robots dispatched via dispatch_patrol,
             tasks flow through the free_fleet adapter and RMF traffic scheduler.
  Layer 2 — Nav2 LiDAR obstacle detection: as robots approach, each robot's
             VoxelLayer local costmap marks the other's body from its own lidar
             returns. RPP controller scales velocity down as costmap cost rises.
             The collision_monitor node (FootprintApproach polygon, min_points=12)
             applies an independent velocity brake at close range.
  Layer 3 — Application-layer yield: when Gz-truth distance < YIELD_DIST,
             robot_2 is held in place (direct cmd_vel=0 via Zenoh) while robot_1
             passes. This prevents the mutual deadlock that would occur in a
             narrow corridor if both robots blocked each other indefinitely.

Route: both robots use the SOUTH OUTER CORRIDOR.
  robot_1: robot_1_home → s_in → s_out → robot_2_home   (heading east)
  robot_2: robot_2_home → s_out → s_in → robot_1_home   (heading west)
"""
import subprocess, threading, time, math, struct, os, sys
import zenoh
import rclpy
from rclpy.node import Node
from rmf_fleet_msgs.msg import FleetState

# ── Tunable constants ────────────────────────────────────────────────────────
ROUTER        = "tcp/zenoh-router:7447"
YIELD_DIST    = 2.0    # metres — trigger yield when Gz distance < this
YIELD_HOLD    = 25.0   # seconds robot_2 holds position
PHASE_TIMEOUT = 300.0  # seconds max per dispatch_patrol call

# ── Spawn / waypoint positions (world frame) ─────────────────────────────────
ROBOT1_HOME = (-2.0, -0.5)
ROBOT2_HOME = ( 2.0,  0.5)
S_IN        = (-1.5, -1.75)
S_OUT       = ( 1.5, -1.75)


# ── Zenoh session ────────────────────────────────────────────────────────────

def open_zenoh():
    conf = zenoh.Config()
    conf.insert_json5("connect/endpoints", f'["{ROUTER}"]')
    conf.insert_json5("mode", '"client"')
    conf.insert_json5("scouting/multicast/enabled", "false")
    return zenoh.open(conf)


# ── Gz ground-truth position monitor ────────────────────────────────────────

class GzPosMonitor:
    """Subscribes to robot_N/gz_world_pos published by the Gazebo pod."""

    def __init__(self, session):
        self._lock = threading.Lock()
        self._gz   = {'robot_1': None, 'robot_2': None}
        session.declare_subscriber('robot_1/gz_world_pos', self._on_r1)
        session.declare_subscriber('robot_2/gz_world_pos', self._on_r2)

    def _parse(self, sample):
        try:
            parts = bytes(sample.payload.to_bytes()).decode().split()
            return float(parts[0]), float(parts[1]), float(parts[2])
        except Exception:
            return None

    def _on_r1(self, s):
        v = self._parse(s)
        if v:
            with self._lock: self._gz['robot_1'] = v

    def _on_r2(self, s):
        v = self._parse(s)
        if v:
            with self._lock: self._gz['robot_2'] = v

    def xy(self, name):
        with self._lock:
            v = self._gz.get(name)
        return (v[0], v[1]) if v else None

    def distance(self):
        with self._lock:
            p1, p2 = self._gz.get('robot_1'), self._gz.get('robot_2')
        if p1 and p2:
            return math.sqrt((p1[0]-p2[0])**2 + (p1[1]-p2[1])**2)
        return None

    def ready(self, timeout=15.0):
        t0 = time.time()
        while time.time()-t0 < timeout:
            with self._lock:
                if self._gz['robot_1'] and self._gz['robot_2']:
                    return True
            time.sleep(0.3)
        return False


# ── Fleet state monitor (AMCL/slam_toolbox positions via RMF) ────────────────

class FleetMonitor(Node):
    def __init__(self):
        super().__init__('rmf_lidar_swap_monitor')
        self._lock = threading.Lock()
        self._pos  = {'robot_1': None, 'robot_2': None}
        self.create_subscription(FleetState, '/fleet_states', self._cb, 10)

    def _cb(self, msg):
        with self._lock:
            for r in msg.robots:
                if r.name in self._pos:
                    loc = r.location
                    self._pos[r.name] = (loc.x, loc.y, loc.yaw)

    def pos(self, name):
        with self._lock:
            return self._pos.get(name)

    def ready(self, timeout=30.0):
        t0 = time.time()
        while time.time()-t0 < timeout:
            with self._lock:
                if self._pos['robot_1'] and self._pos['robot_2']:
                    return True
            time.sleep(0.5)
        return False


# ── RMF dispatch_patrol helper ───────────────────────────────────────────────

def dispatch_patrol(waypoints: list[str], robot_name: str | None = None) -> subprocess.Popen:
    """
    Call dispatch_patrol non-blocking; returns the Popen handle.
    If robot_name is provided, --robot is passed to target a specific robot.
    """
    cmd = [
        'ros2', 'run', 'rmf_demos_tasks', 'dispatch_patrol',
        '-p', *waypoints,
        '-n', '1',
        '--use_sim_time',
    ]
    if robot_name:
        cmd += ['--robot', robot_name]
    print(f"  [RMF] dispatch_patrol {' '.join(waypoints)}"
          + (f" → {robot_name}" if robot_name else ""))
    return subprocess.Popen(
        cmd,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
        env={**os.environ, 'HOME': '/tmp/ros-home'},
    )


# ── Hold robot_2 in place via direct Zenoh cmd_vel=0 ────────────────────────

def hold_robot2(z: zenoh.Session, duration: float):
    """
    Publish zero velocity directly to Gazebo for robot_2.
    Bypasses Nav2 velocity pipeline — robot_2 stops immediately.
    robot_1's Nav2 stack (VoxelLayer + RPP + collision_monitor) continues
    operating normally, slowing robot_1 as it approaches and passes.
    """
    pub = z.declare_publisher('robot_2/cmd_vel')
    # Twist CDR: 6 float64 (linear xyz, angular xyz) — all zero
    zero_twist = b'\x00\x01\x00\x00' + b'\x00' * 48
    deadline = time.time() + duration
    while time.time() < deadline:
        pub.put(zero_twist)
        time.sleep(0.04)   # 25 Hz
    pub.undeclare()


# ── Main demo ────────────────────────────────────────────────────────────────

def main():
    ts = lambda: time.strftime('%H:%M:%S')

    rclpy.init()
    fleet_monitor = FleetMonitor()
    spin_thread = threading.Thread(
        target=rclpy.spin, args=(fleet_monitor,), daemon=True)
    spin_thread.start()

    z = open_zenoh()
    gz = GzPosMonitor(z)

    print(f"\n[{ts()}] RMF + Nav2 LiDAR collision-avoidance swap demo")
    print(  f"  Layer 1 — RMF dispatch_patrol (traffic planning)")
    print(  f"  Layer 2 — Nav2 VoxelLayer + RPP + collision_monitor (LiDAR avoidance)")
    print(  f"  Layer 3 — Application yield (prevents narrow-corridor deadlock)")
    print(  f"  Router  : {ROUTER}\n")

    # ── Wait for sensor data ─────────────────────────────────────────────────
    print(f"[{ts()}] Waiting for Gz ground-truth positions...")
    if not gz.ready(timeout=20):
        print("  ERROR: Gz positions not received — is Gazebo running?")
        sys.exit(1)

    print(f"[{ts()}] Waiting for fleet_states...")
    if not fleet_monitor.ready(timeout=30):
        print("  WARNING: fleet_states not ready — proceeding anyway")

    # ── Phase 1: RMF dispatches both robots ──────────────────────────────────
    print(f"\n[{ts()}] === Phase 1: RMF dispatches both robots (south outer corridor) ===")
    print(  f"  robot_1: robot_1_home → s_in → s_out → robot_2_home  (heading east)")
    print(  f"  robot_2: robot_2_home → s_out → s_in → robot_1_home  (heading west)")
    print(  f"  RMF traffic scheduler detects head-on lane conflict on s_in↔s_out")
    print(  f"  and may delay one robot — if both enter, Nav2 LiDAR avoidance engages")

    p1 = dispatch_patrol(['robot_1_home', 's_in', 's_out', 'robot_2_home'])
    time.sleep(2)   # small stagger so robot_1 leads — more visually distinct
    p2 = dispatch_patrol(['robot_2_home', 's_out', 's_in', 'robot_1_home'])

    # ── Phase 2: Monitor for proximity ──────────────────────────────────────
    print(f"\n[{ts()}] === Phase 2: Monitoring — Nav2 LiDAR avoidance active ===")
    print(  f"  Watch robot_1 slow as robot_2 enters its VoxelLayer costmap.")
    print(  f"  collision_monitor (min_points=12) provides velocity brake at close range.")

    triggered = False
    deadline  = time.time() + PHASE_TIMEOUT
    while time.time() < deadline:
        dist = gz.distance()
        if dist is not None:
            sys.stdout.write(f"\r  Gz distance: {dist:.2f} m  (yield trigger < {YIELD_DIST} m)  ")
            sys.stdout.flush()
            if dist < YIELD_DIST and not triggered:
                triggered = True
                r2_xy = gz.xy('robot_2')
                print(f"\n[{ts()}]   PROXIMITY DETECTED — {dist:.2f} m < {YIELD_DIST} m")
                break
        time.sleep(0.3)

    if not triggered:
        r2_xy = gz.xy('robot_2')
        print(f"\n[{ts()}]   Proximity trigger not fired within {PHASE_TIMEOUT}s.")
        print(  f"  (RMF may have successfully held one robot at the lane entry.)")
        print(  f"  Continuing to wait for task completion...")
    else:
        # ── Phase 3: Application-layer yield ────────────────────────────────
        r2_pos_str = f"({r2_xy[0]:.2f},{r2_xy[1]:.2f})" if r2_xy else "(unknown)"
        print(f"[{ts()}] === Phase 3: Application yield ===")
        print(  f"  robot_2 held at {r2_pos_str} for {YIELD_HOLD:.0f} s")
        print(  f"  robot_1 continues — watch RPP slow as it passes robot_2's body")

        hold_thread = threading.Thread(
            target=hold_robot2, args=(z, YIELD_HOLD), daemon=True)
        hold_thread.start()

        for remaining in range(int(YIELD_HOLD), 0, -1):
            dist = gz.distance()
            d_str = f"{dist:.2f}m" if dist else "?"
            sys.stdout.write(f"\r  Yield: {remaining:3d}s remaining | Gz dist: {d_str}  ")
            sys.stdout.flush()
            time.sleep(1)
        hold_thread.join()
        print(f"\n[{ts()}]   Yield complete — clearing costmaps")

        # Clear costmaps so stale obstacle cells from yield don't block replanning
        clear_pub_1 = z.declare_publisher('robot_1/clear_costmaps')
        clear_pub_2 = z.declare_publisher('robot_2/clear_costmaps')
        for _ in range(3):
            clear_pub_1.put(b'clear')
            clear_pub_2.put(b'clear')
            time.sleep(0.5)
        clear_pub_1.undeclare()
        clear_pub_2.undeclare()
        print(f"[{ts()}]   Costmaps cleared — robot_2 resuming via RMF task")

    # ── Phase 4: Wait for completion ─────────────────────────────────────────
    print(f"\n[{ts()}] === Phase 4: Both robots routing to final swap positions ===")
    print(  f"  Monitoring Gz ground-truth until both reach targets (Δ < 0.3 m)...")

    deadline = time.time() + PHASE_TIMEOUT
    while time.time() < deadline:
        p1_xy = gz.xy('robot_1')
        p2_xy = gz.xy('robot_2')
        if p1_xy and p2_xy:
            d1 = math.sqrt((p1_xy[0]-ROBOT2_HOME[0])**2 + (p1_xy[1]-ROBOT2_HOME[1])**2)
            d2 = math.sqrt((p2_xy[0]-ROBOT1_HOME[0])**2 + (p2_xy[1]-ROBOT1_HOME[1])**2)
            sys.stdout.write(
                f"\r  robot_1→robot_2_home Δ={d1:.2f}m | "
                f"robot_2→robot_1_home Δ={d2:.2f}m  ")
            sys.stdout.flush()
            if d1 < 0.30 and d2 < 0.30:
                print(f"\n[{ts()}]   Both robots reached targets!")
                break
        time.sleep(1)
    else:
        print(f"\n[{ts()}]   Phase 4 timed out — reporting current positions")

    # ── Final report ─────────────────────────────────────────────────────────
    print(f"\n[{ts()}] === Final positions (Gazebo ground truth) ===")
    p1_xy = gz.xy('robot_1')
    p2_xy = gz.xy('robot_2')
    if p1_xy:
        d1 = math.sqrt((p1_xy[0]-ROBOT2_HOME[0])**2 + (p1_xy[1]-ROBOT2_HOME[1])**2)
        print(f"  robot_1 Gz  at ({p1_xy[0]:.2f},{p1_xy[1]:.2f})"
              f"  Δ={d1:.2f}m from target {ROBOT2_HOME}")
    if p2_xy:
        d2 = math.sqrt((p2_xy[0]-ROBOT1_HOME[0])**2 + (p2_xy[1]-ROBOT1_HOME[1])**2)
        print(f"  robot_2 Gz  at ({p2_xy[0]:.2f},{p2_xy[1]:.2f})"
              f"  Δ={d2:.2f}m from target {ROBOT1_HOME}")

    # Fleet state positions
    f1 = fleet_monitor.pos('robot_1')
    f2 = fleet_monitor.pos('robot_2')
    if f1:
        print(f"  robot_1 RMF at ({f1[0]:.2f},{f1[1]:.2f})  (fleet_states)")
    if f2:
        print(f"  robot_2 RMF at ({f2[0]:.2f},{f2[1]:.2f})  (fleet_states)")

    print(f"\n[{ts()}] Demo complete.")
    z.close()
    rclpy.shutdown()


if __name__ == '__main__':
    main()
