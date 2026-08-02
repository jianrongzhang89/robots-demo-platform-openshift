#!/usr/bin/env bash
set -eo pipefail

# RMF core pod entrypoint.
# Runs: rmf-traffic-schedule + rmf-task-dispatcher + free_fleet_adapter
#       + rmf-web API server (port 8000)
# Connects to robots via Zenoh router at zenoh-router:7447.
# All RMF core nodes communicate over localhost DDS (ROS_DOMAIN_ID=55).

export HOME="/tmp/ros-home"
mkdir -p "${HOME}" "${HOME}/.ros" "${HOME}/.config"
export ROS_HOME="${HOME}/.ros"
export ROS_LOG_DIR="${HOME}/.ros/log"

source /opt/ros/jazzy/setup.bash
if [ -f /opt/free_fleet/install/setup.bash ]; then
  source /opt/free_fleet/install/setup.bash
fi

export RMW_IMPLEMENTATION=rmw_cyclonedds_cpp
export ROS_DOMAIN_ID=55          # separate from robot pods on domain 0

FLEET_CONFIG="${FLEET_CONFIG:-/opt/ros2-demo/rmf/fleet_config.yaml}"
NAV_GRAPH="${NAV_GRAPH:-/opt/ros2-demo/rmf/nav_graph.yaml}"
SERVER_URI="${SERVER_URI:-ws://localhost:8000/_internal}"

# Relay sim clock from Zenoh into local ROS domain 55 so the fleet adapter's
# use_sim_time=True (-sim flag) gets a valid clock for TF timestamp lookups.
echo "[rmf-pod] Starting monotonic clock relays for Nav2 pods (robot_1/clock + robot_2/clock -> robot_N/clock_mono)..."
# These relays subscribe to the raw Gazebo sim clock for each robot, filter out
# backwards timestamps, and republish to robot_N/clock_mono. The Nav2 bridge
# maps clock_mono -> /clock on each Nav2 pod, giving tf2 a monotonic clock that
# never triggers "jump back in time" buffer clears.
python3 - <<'PYEOF' &
import struct, threading, time
import zenoh

conf = zenoh.Config()
conf.insert_json5("connect/endpoints", '["tcp/zenoh-router:7447"]')
conf.insert_json5("mode", '"client"')
conf.insert_json5("scouting/multicast/enabled", "false")
z = zenoh.open(conf)

# Gazebo's ros_gz_bridge publishes the sim clock to local DDS as /clock (not namespaced).
# The Gazebo bridge sidecar (no namespace prefix) forwards this to Zenoh key 'clock'.
# We subscribe to 'clock', filter monotonically, and publish to robot_N/clock_mono
# for EACH robot (same clock, different destination keys so each Nav2 bridge receives it).

last_ns = 0
lock = threading.Lock()
RESTART_THRESHOLD_NS = 60 * 1_000_000_000  # 60s: large backward jump = Gazebo restart
# Publish filtered clock to clock_relay/clock_bridge — the clock-bridge sidecar
# on each Nav2 pod (namespace "/clock_relay") subscribes to this and delivers
# to local DDS /clock_bridge. nav2_relay.py then relays /clock_bridge -> /clock.
pub1 = z.declare_publisher("clock_relay/clock_bridge")

def on_clock(sample):
    global last_ns
    try:
        raw = bytes(sample.payload.to_bytes())
        if len(raw) < 12:
            return
        sec  = struct.unpack_from('<i', raw, 4)[0]
        nsec = struct.unpack_from('<I', raw, 8)[0]
        ns = sec * 1_000_000_000 + nsec
        with lock:
            if ns < last_ns:
                if (last_ns - ns) > RESTART_THRESHOLD_NS:
                    # Large backward jump = Gazebo restart, reset filter
                    last_ns = 0
                else:
                    return  # small jitter, filter out
            last_ns = ns
        pub1.put(raw)
    except Exception:
        pass

# Gazebo bridge may publish clock under different keys depending on configuration:
# - "robot_1/clock" (namespaced, when spawned with namespace=robot_1)
# - "clock" (bare, when not namespaced)
# Subscribe to all three to handle both cases.
for key in ["robot_1/clock", "robot_2/clock", "clock"]:
    z.declare_subscriber(key, on_clock)
print("[rmf-pod] Monotonic clock relay active: clock -> clock_relay/clock_bridge")
while True:
    time.sleep(1)
PYEOF
CLOCK_RELAY_PID=$!
sleep 2

# cmd_vel Zenoh keepalive: subscribe to robot_N/cmd_vel from this Zenoh session.
# The nav bridge (zenoh-bridge-ros2dds) creates/maintains its DDS→Zenoh route for
# cmd_vel ONLY while there is a Zenoh subscriber. When the Gazebo bridge session
# changes (~90s after startup), the route drops. This persistent subscriber
# prevents the dropout by acting as an always-on consumer of the cmd_vel stream.
echo "[rmf-pod] Starting cmd_vel Zenoh keepalive (robot_1/cmd_vel + robot_2/cmd_vel)..."
python3 - <<'CMDVEL_KEEP_EOF' &
import zenoh, time

conf = zenoh.Config()
conf.insert_json5("connect/endpoints", '["tcp/zenoh-router:7447"]')
conf.insert_json5("mode", '"client"')
conf.insert_json5("scouting/multicast/enabled", "false")
z = zenoh.open(conf)

# Subscribe to cmd_vel for both robots — no-op callback keeps the routes alive
for key in ["robot_1/cmd_vel", "robot_2/cmd_vel"]:
    z.declare_subscriber(key, lambda s: None)

print("[rmf-pod] cmd_vel Zenoh keepalive active")
while True:
    time.sleep(10)
CMDVEL_KEEP_EOF
CMDVEL_KEEP_PID=$!
sleep 2

# Domain-55 /clock relay so free_fleet_adapter can run with -sim (sim time).
# Two-process pipeline through a FIFO avoids the segfault that occurs when
# rclpy (CycloneDDS) and zenoh share the same Python process.
#   Process 1: subscribe to Zenoh 'clock', write "sec nanosec" lines to FIFO
#   Process 2: read lines from FIFO, publish as ROS /clock on domain 55
echo "[rmf-pod] Starting domain-55 clock relay (Zenoh clock -> ROS domain 55 /clock)..."
mkfifo /tmp/d55clock 2>/dev/null || true

cat > /tmp/d55_zenoh_half.py << 'D55_ZENOH_EOF'
import struct, time, sys, zenoh

conf = zenoh.Config()
conf.insert_json5("connect/endpoints", '["tcp/zenoh-router:7447"]')
conf.insert_json5("mode", '"client"')
conf.insert_json5("scouting/multicast/enabled", "false")
z = zenoh.open(conf)

last_ns = 0

# Max backward jump we tolerate: 60 sim-seconds.
# Larger jumps = Gazebo restart (sim clock reset from thousands to ~0).
# When detected, reset the filter so the new clock flows through.
RESTART_THRESHOLD_NS = 60 * 1_000_000_000

def on_clock(s):
    global last_ns
    try:
        raw = bytes(s.payload.to_bytes())
        if len(raw) < 12:
            return
        sec  = struct.unpack_from('<i', raw, 4)[0]
        nsec = struct.unpack_from('<I', raw, 8)[0]
        ns = sec * 1_000_000_000 + nsec
        if ns < last_ns:
            if (last_ns - ns) > RESTART_THRESHOLD_NS:
                # Large backward jump = Gazebo restart, reset filter
                sys.stderr.write(f"[d55-clock] Gazebo restart detected (jump {last_ns//1_000_000_000}s -> {sec}s), resetting filter\n")
                last_ns = 0
            else:
                return  # small backward jitter, filter out
        last_ns = ns
        sys.stdout.write(f"{sec} {nsec}\n")
        sys.stdout.flush()
    except Exception:
        pass

for key in ["clock", "robot_1/clock", "robot_2/clock"]:
    z.declare_subscriber(key, on_clock)
sys.stderr.write("[d55-clock] Zenoh subscriber ready\n")
while True:
    time.sleep(1)
D55_ZENOH_EOF

cat > /tmp/d55_ros_half.py << 'D55_ROS_EOF'
import rclpy, sys, threading
from rclpy.node import Node
from rclpy.executors import SingleThreadedExecutor
from rclpy.qos import QoSProfile, ReliabilityPolicy, HistoryPolicy
from rosgraph_msgs.msg import Clock
from builtin_interfaces.msg import Time

rclpy.init(args=["domain55_clock"])
node = Node("domain55_clock_relay")
qos = QoSProfile(
    depth=1,
    reliability=ReliabilityPolicy.BEST_EFFORT,
    history=HistoryPolicy.KEEP_LAST,
)
pub = node.create_publisher(Clock, "/clock", qos)
executor = SingleThreadedExecutor()
executor.add_node(node)
threading.Thread(target=executor.spin, daemon=True).start()
node.get_logger().info("[d55-clock] ROS publisher ready on domain 55 /clock")
for line in sys.stdin:
    try:
        sec, nanosec = (int(x) for x in line.split())
        msg = Clock()
        msg.clock = Time(sec=sec, nanosec=nanosec)
        pub.publish(msg)
    except Exception:
        pass
D55_ROS_EOF

python3 /tmp/d55_zenoh_half.py > /tmp/d55clock &
D55_ZENOH_PID=$!
python3 /tmp/d55_ros_half.py < /tmp/d55clock &
D55_ROS_PID=$!
sleep 2

echo "[rmf-pod] Starting rmf-web API server on port 8000..."
if python3 -c "import api_server" 2>/dev/null; then
  cd /opt/rmf-web/packages/api-server
  python3 -m api_server &
  API_PID=$!
  cd /tmp/ros-home
  sleep 3
else
  echo "[rmf-pod] WARN: rmf-web api_server not found"
  API_PID=""
fi

# battery_soc=1.0 is hardcoded in the adapter patch — no relay needed.
# (fake CDR relay caused pycdr2 struct.error crashes in _battery_state_callback)

echo "[rmf-pod] Launching RMF traffic schedule..."
ros2 run rmf_traffic_ros2 rmf_traffic_schedule &
SCHEDULE_PID=$!
sleep 3

echo "[rmf-pod] Launching RMF task dispatcher..."
ros2 run rmf_task_ros2 rmf_task_dispatcher &
DISPATCHER_PID=$!
sleep 2

# Wait for both robots' AMCL to localize and publish amcl_pose before the
# adapter tries to initialize. At real_time_factor=0.5, AMCL convergence
# takes roughly 2× wall-clock time vs. a 1× simulation.
echo "[rmf-pod] Waiting 90s for AMCL to localize both robots (real_time_factor=0.5)..."
sleep 90

ZENOH_CONFIG="${ZENOH_CONFIG:-/opt/ros2-demo/zenoh/fleet-adapter-zenoh.json5}"
echo "[rmf-pod] Launching free_fleet adapter (fleet_adapter.py) with zenoh config: ${ZENOH_CONFIG}..."
# -sim flag: domain 55 /clock is now provided by d55_ros_half.py (Zenoh clock relay).
# This makes the traffic planner use sim time so its ETAs match actual navigation
# speed at real_time_factor=0.5 — prevents the 10-second wall-time replanning loop.
ros2 run free_fleet_adapter fleet_adapter.py \
  -c "${FLEET_CONFIG}" \
  -n "${NAV_GRAPH}" \
  --zenoh-config "${ZENOH_CONFIG}" \
  -sim \
  ${API_PID:+-s "${SERVER_URI}"} &
ADAPTER_PID=$!

echo ""
echo "=================================================="
echo " RMF core running"
echo "  Domain ID : 55 (separate from robot pods)"
echo "  Zenoh     : zenoh-router:7447"
echo "  Fleet cfg : ${FLEET_CONFIG}"
echo "  Nav graph : ${NAV_GRAPH}"
echo ""
echo " Dispatch tasks:"
echo "   ros2 run rmf_demos_tasks dispatch_patrol \\"
echo "     -p robot_1_home meeting_point robot_2_home \\"
echo "     -n 1 --use_sim_time"
echo "=================================================="

term_handler() {
  echo "[rmf-pod] Shutting down..."
  kill "${ADAPTER_PID:-}" "${DISPATCHER_PID:-}" "${SCHEDULE_PID:-}" \
       "${API_PID:-}" "${CLOCK_RELAY_PID:-}" \
       "${D55_ZENOH_PID:-}" "${D55_ROS_PID:-}" "${CMDVEL_KEEP_PID:-}" 2>/dev/null || true
  rm -f /tmp/d55clock /tmp/d55_zenoh_half.py /tmp/d55_ros_half.py
  pkill -P $$ 2>/dev/null || true
  wait "${ADAPTER_PID}" 2>/dev/null || true
}

trap term_handler SIGTERM SIGINT

wait "${ADAPTER_PID}"
