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
RETREAT_PT  = ( 2.5, -1.75)   # robot_2 retreats here to clear corridor

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

    t1 = threading.Thread(target=r1.navigate,
                          args=(*S_IN, YAW_EAST), daemon=True)
    t2 = threading.Thread(target=r2.navigate,
                          args=(*S_OUT, YAW_WEST), daemon=True)
    t1.start(); t2.start()
    t1.join(); t2.join()

    p1 = gz.xy('robot_1'); p2 = gz.xy('robot_2')
    print(f"[{ts()}]   robot_1 at ({p1[0]:.2f},{p1[1]:.2f}), "
          f"robot_2 at ({p2[0]:.2f},{p2[1]:.2f})")

    # ─────────────────────────────────────────────────────────────────────────
    # Phase 1b — Head-on approach
    # ─────────────────────────────────────────────────────────────────────────
    print(f"\n[{ts()}] === Phase 1b: Head-on approach ===")
    print(  f"  robot_1 → east toward s_out | robot_2 → west toward s_in")
    print(  f"  [Layer 2] robot_1's VoxelLayer marks robot_2 as obstacle →"
             f" RPP slows robot_1")
    print(  f"            collision_monitor fires when robot_2 enters approach polygon")

    # Launch both heading toward each other simultaneously
    t1 = threading.Thread(target=r1.navigate,
                          args=(*S_OUT, YAW_EAST), daemon=True)
    t2 = threading.Thread(target=r2.navigate,
                          args=(*S_IN,  YAW_WEST), daemon=True)
    t1.start(); t2.start()

    # Monitor distance until yield threshold
    yield_pos2 = None
    deadline   = time.time() + TIMEOUT
    while time.time() < deadline:
        dist = gz.distance()
        if dist is not None:
            sys.stdout.write(f"\r  Gz distance: {dist:.2f} m  (yield at < {YIELD_DIST} m)  ")
            sys.stdout.flush()
            if dist < YIELD_DIST:
                yield_pos2 = gz.xy('robot_2')
                print(f"\n[{ts()}]   PROXIMITY — {dist:.2f} m")
                break
        time.sleep(0.25)
    else:
        print(f"\n[{ts()}]   No proximity within {TIMEOUT}s — proceeding")

    # ─────────────────────────────────────────────────────────────────────────
    # Phase 2 — Application yield: robot_2 retreats east to clear corridor
    # ─────────────────────────────────────────────────────────────────────────
    print(f"\n[{ts()}] === Phase 2: Application yield ===")
    pos2 = gz.xy('robot_2') or yield_pos2 or S_OUT
    print(  f"  [Layer 3] robot_2 at ({pos2[0]:.2f},{pos2[1]:.2f}) — "
             f"retreating east to {RETREAT_PT} to clear path for robot_1")
    print(  f"  robot_1 continues east; watch LiDAR avoidance back off as robot_2 retreats")

    # Brief zero-vel hold while robot_2 goal is re-issued
    hold_t = threading.Thread(target=hold_zero_vel,
                              args=(z, 'robot_2', 2.0), daemon=True)
    hold_t.start()
    hold_t.join()

    # robot_2 retreats east — sends a new Nav2 goal eastward
    retreat_thread = threading.Thread(
        target=r2.navigate, args=(*RETREAT_PT, YAW_EAST), daemon=True)
    retreat_thread.start()

    # robot_1 continues east; monitor until robot_2 is clear (x > S_OUT[0])
    print(f"[{ts()}]   Waiting for robot_2 to clear east of s_out...")
    clear_deadline = time.time() + 60.0
    while time.time() < clear_deadline:
        p2 = gz.xy('robot_2')
        p1 = gz.xy('robot_1')
        if p2 and p2[0] > S_OUT[0] - 0.2:
            print(f"[{ts()}]   robot_2 cleared at ({p2[0]:.2f},{p2[1]:.2f}) — corridor open")
            break
        sys.stdout.write(
            f"\r  robot_2 retreating: ({p2[0]:.2f},{p2[1]:.2f}) | "
            f"robot_1 approaching: ({p1[0]:.2f},{p1[1]:.2f})  " if p2 and p1 else "")
        sys.stdout.flush()
        time.sleep(0.5)
    print()

    retreat_thread.join(timeout=5.0)

    # Clear costmaps so stale robot_2 obstacle cells don't block robot_1's path
    print(f"[{ts()}]   Clearing costmaps...")
    clear_costmaps(z, 'robot_1')
    clear_costmaps(z, 'robot_2')

    # ─────────────────────────────────────────────────────────────────────────
    # Phase 3 — Both route to final swap positions
    # ─────────────────────────────────────────────────────────────────────────
    print(f"\n[{ts()}] === Phase 3: Route to final swap positions ===")
    print(  f"  robot_1 → robot_2_home {ROBOT2_HOME}")
    print(  f"  robot_2 → robot_1_home {ROBOT1_HOME}")

    # Wait for t1 (robot_1 s_out goal) to complete before sending final goal
    t1.join(timeout=60.0)

    t3 = threading.Thread(target=r1.navigate,
                          args=(*ROBOT2_HOME,), daemon=True)
    t4 = threading.Thread(target=r2.navigate,
                          args=(*ROBOT1_HOME,), daemon=True)
    t3.start()
    time.sleep(3)   # slight stagger so routes don't conflict in the transition area
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
