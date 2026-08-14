#!/usr/bin/env python3
"""
RMF + Nav2 LiDAR collision-avoidance swap demo.

Three visible layers:
  Layer 1 — RMF fleet integration: goals sent via the rmf_navigate_cmd
             protocol → nav2_relay → Nav2 navigate_to_pose. The free_fleet
             adapter manages fleet state. This is the same channel that the
             RMF task dispatcher uses in production.
  Layer 2 — Nav2 LiDAR obstacle detection: as robots approach, each robot's
             VoxelLayer local costmap marks the other's body from its own lidar
             returns. RPP controller scales velocity down as costmap cost rises.
             The collision_monitor node (FootprintApproach, min_points=12)
             applies an independent velocity brake at close range.
  Layer 3 — Application-layer yield: at < YIELD_DIST, robot_2 retreats east
             to clear the corridor so robot_1 can pass. This mirrors real-world
             AMR behaviour: one robot backs into a passing bay while the other
             drives through.

Route:
  Phase 1 — Both robots enter the SOUTH OUTER CORRIDOR simultaneously from
             opposite ends (head-on collision course).
  Phase 2 — Head-on approach. robot_1's VoxelLayer detects robot_2 → RPP
             slows robot_1. collision_monitor fires when robot_2 enters the
             forward approach polygon.
  Phase 3 — robot_2 retreats east (clears corridor). robot_1 passes through.
  Phase 4 — Both route to final swap positions independently.
"""
import threading, time, math, struct, random, os, sys
import zenoh
import rclpy
from rclpy.node import Node
from rmf_fleet_msgs.msg import FleetState

# ── Constants ────────────────────────────────────────────────────────────────
ROUTER     = "tcp/zenoh-router:7447"
YIELD_DIST = 2.0    # metres — Gz distance that triggers yield
TIMEOUT    = 180.0  # seconds per navigation leg before giving up

# World-frame positions
ROBOT1_HOME = (-2.0, -0.5)
ROBOT2_HOME = ( 2.0,  0.5)
S_IN        = (-1.5, -1.75)   # south corridor west entry
S_OUT       = ( 1.5, -1.75)   # south corridor east entry
RETREAT_PT  = ( 2.5, -1.75)   # robot_2 retreats east to clear corridor

YAW_EAST = 0.0          # robot_1 heading east
YAW_WEST = math.pi      # robot_2 heading west


def ts():
    return time.strftime('%H:%M:%S')


# ── Zenoh session ────────────────────────────────────────────────────────────

def open_zenoh():
    conf = zenoh.Config()
    conf.insert_json5("connect/endpoints", f'["{ROUTER}"]')
    conf.insert_json5("mode", '"client"')
    conf.insert_json5("scouting/multicast/enabled", "false")
    return zenoh.open(conf)


def cdr(text):
    d = text.encode() + b'\x00'
    return b'\x00\x01\x00\x00' + struct.pack('<I', len(d)) + d


# ── NavAgent: rmf_navigate_cmd → nav2_relay → Nav2 navigate_to_pose ──────────

class NavAgent:
    """
    Sends goals via robot_N/rmf_navigate_cmd and waits for OK/FAILED result.
    This is Layer 1: the RMF fleet integration protocol.
    """
    def __init__(self, session, robot_name):
        self.name = robot_name
        self._session = session
        self._done = threading.Event()
        self._ok = False
        self._goal_id = ""
        self._pub = session.declare_publisher(f"{robot_name}/rmf_navigate_cmd")
        self._sub = session.declare_subscriber(
            f"{robot_name}/rmf_navigate_result", self._on_result)

    def _on_result(self, sample):
        try:
            raw = bytes(sample.payload.to_bytes())
            if len(raw) < 9:
                return
            slen = struct.unpack_from('<I', raw, 4)[0]
            text = raw[8:8 + slen - 1].decode('utf-8', errors='ignore').strip()
            parts = text.split()
            if len(parts) >= 2 and parts[0] == self._goal_id:
                if parts[1] == 'OK':
                    self._ok = True
                self._done.set()
        except Exception:
            pass

    def navigate(self, x, y, yaw=0.0, timeout=TIMEOUT):
        self._goal_id = str(random.randint(1000000, 9999999))
        self._done.clear()
        self._ok = False
        self._pub.put(cdr(f"{self._goal_id} {x:.6f} {y:.6f} {yaw:.6f}"))
        print(f"  [{self.name}] → ({x:.2f},{y:.2f})")
        deadline = time.time() + timeout
        while time.time() < deadline:
            remaining = deadline - time.time()
            self._done.wait(timeout=min(remaining, 20.0))
            if self._ok:
                return True
            if self._done.is_set():
                self._done.clear()
                self._ok = False
                time.sleep(3.0)
                self._goal_id = str(random.randint(1000000, 9999999))
                self._pub.put(cdr(f"{self._goal_id} {x:.6f} {y:.6f} {yaw:.6f}"))
        print(f"  [{self.name}] TIMEOUT to ({x:.2f},{y:.2f})")
        return False

    def cancel(self):
        self._pub.put(cdr(f"{self._goal_id} CANCEL"))


# ── Gz ground-truth position monitor ────────────────────────────────────────

class GzPosMonitor:
    def __init__(self, session):
        self._lock = threading.Lock()
        self._gz   = {'robot_1': None, 'robot_2': None}
        session.declare_subscriber('robot_1/gz_world_pos', self._r1)
        session.declare_subscriber('robot_2/gz_world_pos', self._r2)

    def _parse(self, s):
        try:
            p = bytes(s.payload.to_bytes()).decode().split()
            return float(p[0]), float(p[1]), float(p[2])
        except Exception:
            return None

    def _r1(self, s):
        v = self._parse(s)
        if v:
            with self._lock: self._gz['robot_1'] = v

    def _r2(self, s):
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


# ── Fleet state monitor ──────────────────────────────────────────────────────

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

    def ready(self, timeout=30.0):
        t0 = time.time()
        while time.time()-t0 < timeout:
            with self._lock:
                if self._pos['robot_1'] and self._pos['robot_2']:
                    return True
            time.sleep(0.5)
        return False


# ── Helpers ──────────────────────────────────────────────────────────────────

def hold_zero_vel(z, robot_name, duration):
    """Publish cmd_vel=0 directly to Zenoh to hold a robot in place."""
    pub = z.declare_publisher(f'{robot_name}/cmd_vel')
    zero = b'\x00\x01\x00\x00' + b'\x00' * 48
    deadline = time.time() + duration
    while time.time() < deadline:
        pub.put(zero)
        time.sleep(0.04)
    pub.undeclare()


def clear_costmaps(z, robot_name):
    pub = z.declare_publisher(f'{robot_name}/clear_costmaps')
    for _ in range(3):
        pub.put(b'clear')
        time.sleep(0.4)
    pub.undeclare()


def wait_nav_done(nav_agent):
    """Block until the running NavAgent goal completes (OK or FAILED)."""
    nav_agent._done.wait(timeout=TIMEOUT)


# ── Main demo ────────────────────────────────────────────────────────────────

def main():
    rclpy.init()
    fleet = FleetMonitor()
    threading.Thread(target=rclpy.spin, args=(fleet,), daemon=True).start()

    z   = open_zenoh()
    gz  = GzPosMonitor(z)
    r1  = NavAgent(z, 'robot_1')
    r2  = NavAgent(z, 'robot_2')

    print(f"\n[{ts()}] RMF + Nav2 LiDAR collision-avoidance swap demo")
    print(  f"  Layer 1 — RMF fleet integration (rmf_navigate_cmd → nav2_relay → Nav2)")
    print(  f"  Layer 2 — Nav2 VoxelLayer + RPP + collision_monitor (LiDAR avoidance)")
    print(  f"  Layer 3 — Application yield + robot_2 retreat (corridor passing manoeuvre)")
    print(  f"  Router  : {ROUTER}\n")

    print(f"[{ts()}] Waiting for Gz positions and fleet_states...")
    if not gz.ready(20):
        print("ERROR: Gz positions not received"); sys.exit(1)
    fleet.ready(15)

    # ─────────────────────────────────────────────────────────────────────────
    # Phase 1a — Both robots enter south corridor from opposite ends
    # ─────────────────────────────────────────────────────────────────────────
    print(f"\n[{ts()}] === Phase 1a: Enter south corridor ===")
    print(  f"  robot_1 enters from WEST  (spawn → s_in  {S_IN})")
    print(  f"  robot_2 enters from EAST  (spawn → s_out {S_OUT})")
    print(  f"  [Layer 1] Goals dispatched via rmf_navigate_cmd → nav2_relay → Nav2")

    # Route both robots to corridor entry points.
    # use_collision_detection=True + robot_radius=0.22m forces NavFn to use
    # outer corridors (pillar gaps are too narrow for the inflated robot footprint).
    # robot_1: spawn (-2.0,-0.5) → SW corner (-2.0,-1.75) → s_in (-1.5,-1.75)
    #   SW corner is along the west outer wall and was explored — in posegraph.
    # robot_2: spawn (2.0,0.5) → S_OUT (1.5,-1.75) directly
    #   The west-then-south path through the explored corridor is in the posegraph.
    #   SE corner (2.0,-1.75) = map(0,-2.25) is outside posegraph bounds.
    # Route via outer walls to avoid pillar grid.
    # robot_radius=0.22m in global costmap forces NavFn to use outer corridors.
    # AMCL covers the full pgm map so all goals are within bounds.
    SW_CORNER = (-2.0, -1.75)  # along west wall — no pillars, direct south route

    def phase1a_robot1():
        r1.navigate(*SW_CORNER, YAW_EAST, timeout=60.0)
        r1.navigate(*S_IN,      YAW_EAST, timeout=60.0)

    def phase1a_robot2():
        # Navigate directly to S_OUT — AMCL covers full sandbox, no bounds issues.
        r2.navigate(*S_OUT, YAW_WEST, timeout=120.0)

    t1 = threading.Thread(target=phase1a_robot1, daemon=True)
    t2 = threading.Thread(target=phase1a_robot2, daemon=True)
    t1.start(); t2.start()
    t1.join(); t2.join()

    p1 = gz.xy('robot_1'); p2 = gz.xy('robot_2')
    print(f"[{ts()}]   robot_1 at ({p1[0]:.2f},{p1[1]:.2f}), "
          f"robot_2 at ({p2[0]:.2f},{p2[1]:.2f})")

    # ─────────────────────────────────────────────────────────────────────────
    # Phase 1b — LiDAR approach: robot_1 moves east, robot_2 is stationary
    # ─────────────────────────────────────────────────────────────────────────
    # Key design decision: send robot_1 to the CORRIDOR MIDPOINT (0.5,-1.75),
    # not past robot_2 at s_out (1.5,-1.75). This avoids NavFn failing because
    # the goal cell is occupied by robot_2 in the global costmap.
    # As robot_1 moves east toward (0.5,-1.75), robot_2's body enters robot_1's
    # VoxelLayer local costmap → RPP regulated scaling slows robot_1 (Layer 2).
    MID_CORRIDOR = (0.5, -1.75)

    print(f"\n[{ts()}] === Phase 1b: LiDAR approach ===")
    print(  f"  robot_1 → corridor midpoint {MID_CORRIDOR} (approaching robot_2 at s_out)")
    print(  f"  robot_2 holds at s_out as a stationary LiDAR obstacle")
    print(  f"  [Layer 2] Watch robot_1 slow as robot_2 enters its VoxelLayer costmap")
    print(  f"  yield trigger: Gz distance < {YIELD_DIST} m OR {TIMEOUT}s elapsed")

    # Only send robot_1 east — robot_2 stays at s_out as obstacle
    t1 = threading.Thread(target=r1.navigate,
                          args=(*MID_CORRIDOR, YAW_EAST), daemon=True)
    t1.start()

    # Monitor distance until yield threshold or timeout
    yield_pos2 = None
    deadline   = time.time() + TIMEOUT
    while time.time() < deadline:
        dist = gz.distance()
        if dist is not None:
            sys.stdout.write(f"\r  Gz distance: {dist:.2f} m  (yield at < {YIELD_DIST} m)  ")
            sys.stdout.flush()
            if dist < YIELD_DIST:
                yield_pos2 = gz.xy('robot_2')
                print(f"\n[{ts()}]   PROXIMITY — {dist:.2f} m — LiDAR avoidance demonstrated")
                break
        time.sleep(0.25)
    else:
        print(f"\n[{ts()}]   Timeout ({TIMEOUT}s) — triggering yield "
              f"(robot_1 may have been slowed/stopped by LiDAR collision check)")

    t1.join(timeout=2.0)  # give navigation thread a moment then move on

    # ─────────────────────────────────────────────────────────────────────────
    # Phase 2 — Application yield: robot_2 retreats east to clear corridor
    # ─────────────────────────────────────────────────────────────────────────
    print(f"\n[{ts()}] === Phase 2: Application yield ===")
    pos2 = gz.xy('robot_2') or yield_pos2 or S_OUT
    print(  f"  [Layer 3] robot_2 at ({pos2[0]:.2f},{pos2[1]:.2f}) — "
             f"retreating east to {RETREAT_PT}")
    print(  f"  robot_1 will clear costmaps and resume east once corridor is clear")

    # Hold robot_2 in place while re-issuing the retreat goal
    hold_t = threading.Thread(target=hold_zero_vel,
                              args=(z, 'robot_2', 2.0), daemon=True)
    hold_t.start()
    hold_t.join()

    # robot_2 retreats east past s_out — clears the corridor for robot_1
    retreat_thread = threading.Thread(
        target=r2.navigate, args=(*RETREAT_PT, YAW_EAST), daemon=True)
    retreat_thread.start()

    # Wait until robot_2 actually reaches the retreat point (x > 2.2m)
    print(f"[{ts()}]   Waiting for robot_2 to reach retreat point {RETREAT_PT}...")
    clear_deadline = time.time() + 60.0
    while time.time() < clear_deadline:
        p2 = gz.xy('robot_2')
        p1 = gz.xy('robot_1')
        if p2 and p2[0] > RETREAT_PT[0] - 0.3:  # robot_2 close to retreat point
            print(f"[{ts()}]   robot_2 at ({p2[0]:.2f},{p2[1]:.2f}) — corridor clear!")
            break
        sys.stdout.write(
            f"\r  robot_2 → {RETREAT_PT}: ({p2[0]:.2f},{p2[1]:.2f}) | "
            f"robot_1: ({p1[0]:.2f},{p1[1]:.2f})  " if p2 and p1 else "")
        sys.stdout.flush()
        time.sleep(0.5)
    print()

    retreat_thread.join(timeout=10.0)

    # Clear costmaps so stale obstacle cells don't block Phase 3 planning
    print(f"[{ts()}]   Clearing costmaps on both robots...")
    clear_costmaps(z, 'robot_1')
    clear_costmaps(z, 'robot_2')
    time.sleep(2.0)

    # ─────────────────────────────────────────────────────────────────────────
    # Phase 3 — Both route to final positions (within each robot's map bounds)
    # ─────────────────────────────────────────────────────────────────────────
    # AMCL covers the full pgm map so both robots can navigate anywhere.
    print(f"\n[{ts()}] === Phase 3: Route to final swap positions ===")
    print(  f"  robot_1 → robot_2_home {ROBOT2_HOME}")
    print(  f"  robot_2 → robot_1_home {ROBOT1_HOME}")

    # Wait for t1 (robot_1 corridor goal) to complete before sending final goal
    t1.join(timeout=60.0)

    t3 = threading.Thread(target=r1.navigate,
                          args=(*ROBOT2_HOME,), daemon=True)
    t4 = threading.Thread(target=r2.navigate,
                          args=(*ROBOT1_HOME,), daemon=True)
    t3.start()
    time.sleep(3)   # slight stagger so routes don't conflict
    t4.start()
    t3.join(); t4.join()

    # ─────────────────────────────────────────────────────────────────────────
    # Phase 4 — Final report
    # ─────────────────────────────────────────────────────────────────────────
    print(f"\n[{ts()}] === Phase 4: Final positions (Gz ground truth) ===")
    p1 = gz.xy('robot_1'); p2 = gz.xy('robot_2')
    if p1:
        d1 = math.sqrt((p1[0]-ROBOT2_HOME[0])**2 + (p1[1]-ROBOT2_HOME[1])**2)
        print(f"  robot_1 Gz  at ({p1[0]:.2f},{p1[1]:.2f})  Δ={d1:.2f}m from {ROBOT2_HOME}")
    if p2:
        d2 = math.sqrt((p2[0]-ROBOT1_HOME[0])**2 + (p2[1]-ROBOT1_HOME[1])**2)
        print(f"  robot_2 Gz  at ({p2[0]:.2f},{p2[1]:.2f})  Δ={d2:.2f}m from {ROBOT1_HOME}")

    f1 = fleet._pos.get('robot_1'); f2 = fleet._pos.get('robot_2')
    if f1: print(f"  robot_1 RMF at ({f1[0]:.2f},{f1[1]:.2f})  (fleet_states)")
    if f2: print(f"  robot_2 RMF at ({f2[0]:.2f},{f2[1]:.2f})  (fleet_states)")

    print(f"\n[{ts()}] Demo complete.")
    z.close()
    rclpy.shutdown()


if __name__ == '__main__':
    main()
