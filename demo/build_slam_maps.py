#!/usr/bin/env python3
"""
SLAM posegraph builder — drives both robots through the full tb3_sandbox
using the Gz P-controller so slam_toolbox records complete coverage.

Run this script while both nav2 pods are running with SLAM_BUILD_MODE=1.
When exploration finishes it calls /slam_toolbox/serialize_map on each pod.

Usage (from rmf-core pod after `make deploy-slam-build`):
  python3 /tmp/build_slam_maps.py
"""
import math, time, threading, struct, sys, subprocess
import zenoh

ROUTER = "tcp/zenoh-router:7447"

# ── Exploration waypoints ────────────────────────────────────────────────────
# Each robot traces a path that covers all corridors and the centre area.
# At 0.22 m/s and ~100 m total path per robot → ~8 minutes per robot.
# Run both robots concurrently to save time.

ROBOT1_WAYPOINTS = [
    # From spawn (-2.0,-0.5) heading east/south.
    # Dwell in south outer corridor to ensure posegraph covers full corridor width.
    (-1.5, -0.5),   # move east in the inner area
    (-2.0, -1.75),  # south along west wall to corridor entry (builds west wall coverage)
    (-1.5, -1.75),  # s_in — south outer corridor
    (-0.5, -1.75),  # east along corridor (more coverage)
    ( 0.0, -1.75),  # corridor midpoint
    ( 0.5, -1.75),  # more corridor coverage
    ( 1.5, -1.75),  # reach s_out
    ( 1.5,  0.0),   # north through east side
    ( 1.5,  1.75),  # north outer corridor east entry (n_in)
    ( 0.0,  1.75),  # west along north outer corridor
    (-1.5,  1.75),  # reach n_out
    (-1.5,  0.5),   # south on west side
    ( 0.0,  0.0),   # centre / meeting point
    (-0.5, -0.5),   # inner area coverage
    (-2.0, -0.5),   # return to spawn
]

ROBOT2_WAYPOINTS = [
    # From spawn (2.0, 0.5) heading west/south
    # Extra southern waypoints added to ensure posegraph map covers y=-1.75 corridor.
    # The robot must dwell at corridor positions so slam_toolbox builds coverage there.
    ( 1.5,  0.5),   # move west in the inner area
    ( 1.5, -1.50),  # south toward corridor (y=-1.50 builds coverage for y=-1.75)
    ( 1.5, -1.75),  # south outer corridor — full depth, builds map coverage
    ( 0.5, -1.75),  # move west within corridor (more coverage at y=-1.75)
    ( 0.0, -1.75),  # west along south outer corridor
    (-0.5, -1.75),  # more corridor coverage
    (-1.5, -1.75),  # reach s_in
    (-1.5,  0.0),   # north through west side
    (-1.5,  1.75),  # north outer corridor west entry (n_out)
    ( 0.0,  1.75),  # east along north outer corridor
    ( 1.5,  1.75),  # reach n_in
    ( 1.5,  0.5),   # south on east side
    ( 0.0,  0.0),   # centre / meeting point
    ( 0.5,  0.5),   # inner area coverage
    ( 2.0,  0.5),   # return to spawn
]


# ── Zenoh helpers ────────────────────────────────────────────────────────────

def open_zenoh():
    conf = zenoh.Config()
    conf.insert_json5("connect/endpoints", f'["{ROUTER}"]')
    conf.insert_json5("mode", '"client"')
    conf.insert_json5("scouting/multicast/enabled", "false")
    return zenoh.open(conf)


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

    def get(self, name):
        with self._lock:
            return self._gz.get(name)

    def ready(self, timeout=15.0):
        t0 = time.time()
        while time.time() - t0 < timeout:
            with self._lock:
                if self._gz['robot_1'] and self._gz['robot_2']:
                    return True
            time.sleep(0.3)
        return False


# ── Gz P-controller ──────────────────────────────────────────────────────────

def gz_drive_to(robot_name, nav_pub, monitor, tx, ty,
                stop_dist=0.25, max_v=0.22, max_w=1.0, timeout=120.0):
    """Drive robot_name to (tx, ty) using Gz ground-truth, publish cmd_vel."""
    zero = b'\x00\x01\x00\x00' + b'\x00' * 48

    def twist_cdr(vx, wz):
        buf = bytearray(b'\x00\x01\x00\x00')
        buf += struct.pack('<ddd', vx, 0.0, 0.0)
        buf += struct.pack('<ddd', 0.0, 0.0, wz)
        return bytes(buf)

    deadline = time.time() + timeout
    while time.time() < deadline:
        pos = monitor.get(robot_name)
        if pos is None:
            time.sleep(0.1)
            continue
        x, y, yaw = pos
        dx, dy = tx - x, ty - y
        dist = math.sqrt(dx*dx + dy*dy)
        if dist < stop_dist:
            nav_pub.put(zero)
            return True
        heading_err = math.atan2(dy, dx) - yaw
        while heading_err >  math.pi: heading_err -= 2*math.pi
        while heading_err < -math.pi: heading_err += 2*math.pi
        vx = max_v * min(1.0, dist) if abs(heading_err) < 0.8 else 0.0
        wz = max(min(2.0 * heading_err, max_w), -max_w)
        nav_pub.put(twist_cdr(vx, wz))
        time.sleep(0.04)

    nav_pub.put(zero)
    return False


def explore(robot_name, waypoints, z, monitor):
    """Drive robot through all waypoints for SLAM coverage."""
    pub = z.declare_publisher(f'{robot_name}/cmd_vel')
    print(f"[{robot_name}] Starting exploration ({len(waypoints)} waypoints)...")
    for i, (tx, ty) in enumerate(waypoints):
        print(f"[{robot_name}]   WP {i+1}/{len(waypoints)}: ({tx:.1f},{ty:.1f})")
        ok = gz_drive_to(robot_name, pub, monitor, tx, ty)
        if not ok:
            print(f"[{robot_name}]   TIMEOUT at WP {i+1} — continuing")
    print(f"[{robot_name}] Exploration complete.")
    pub.undeclare()


# ── Serialize maps ───────────────────────────────────────────────────────────

def serialize_map(robot_name, namespace):
    """Call /slam_toolbox/serialize_map on the robot's nav2 pod."""
    pod = subprocess.run(
        ['oc', 'get', 'pod', '-n', namespace,
         '-l', f'app=robot-nav-{robot_name.replace("_","-")}',
         '-o', 'jsonpath={.items[0].metadata.name}'],
        capture_output=True, text=True
    ).stdout.strip()
    if not pod:
        print(f"[{robot_name}] ERROR: pod not found in namespace {namespace}")
        return False

    outfile = f'/tmp/{robot_name}_slam'
    print(f"[{robot_name}] Serializing posegraph to {pod}:{outfile} ...")
    result = subprocess.run([
        'oc', 'exec', '-n', namespace, pod, '-c', 'nav2', '--',
        'bash', '-c',
        f'export HOME=/tmp/ros-home; source /usr/lib64/ros-jazzy/setup.bash; '
        f'timeout 30 ros2 service call /slam_toolbox/serialize_map '
        f'slam_toolbox/srv/SerializePoseGraph '
        f'"{{filename: \'{outfile}\'}}" 2>/dev/null'
    ], capture_output=True, text=True, timeout=60)

    if result.returncode != 0:
        print(f"[{robot_name}] WARN: serialize_map returned non-zero: {result.stderr}")
    else:
        print(f"[{robot_name}] Posegraph serialized to {outfile}.{{data,posegraph}}")
    return True


# ── Main ─────────────────────────────────────────────────────────────────────

def main():
    import os
    namespace = os.environ.get('ROS_DEMO_NS', 'ros2-multi-robot')

    z = open_zenoh()
    monitor = GzPosMonitor(z)

    print("Waiting for Gz position feeds...")
    if not monitor.ready(20):
        print("ERROR: No Gz positions — is Gazebo running?"); sys.exit(1)

    p1 = monitor.get('robot_1')
    p2 = monitor.get('robot_2')
    print(f"  robot_1 at ({p1[0]:.2f},{p1[1]:.2f})")
    print(f"  robot_2 at ({p2[0]:.2f},{p2[1]:.2f})")

    print("\nStarting concurrent exploration (both robots simultaneously)...")
    t1 = threading.Thread(target=explore,
                          args=('robot_1', ROBOT1_WAYPOINTS, z, monitor),
                          daemon=True)
    t2 = threading.Thread(target=explore,
                          args=('robot_2', ROBOT2_WAYPOINTS, z, monitor),
                          daemon=True)
    t1.start(); t2.start()
    t1.join(); t2.join()

    print("\nExploration done. Waiting 30s for slam_toolbox to process final scans...")
    time.sleep(30)

    print("\nSerializing posegraphs...")
    for name in ['robot_1', 'robot_2']:
        serialize_map(name, namespace)

    print("\nDone. Copy posegraphs from pods with:")
    for name in ['robot_1', 'robot_2']:
        pod_label = f'robot-nav-{name.replace("_","-")}'
        print(f"  oc cp {namespace}/$(oc get pod -n {namespace} -l app={pod_label} "
              f"-o jsonpath='{{.items[0].metadata.name}}'):"
              f"/tmp/{name}_slam.data slam_maps/{name}_slam.data -c nav2")
        print(f"  oc cp {namespace}/$(oc get pod -n {namespace} -l app={pod_label} "
              f"-o jsonpath='{{.items[0].metadata.name}}'):"
              f"/tmp/{name}_slam.posegraph slam_maps/{name}_slam.posegraph -c nav2")

    z.close()


if __name__ == '__main__':
    main()
