#!/usr/bin/env bash
set -eo pipefail

# Open-RMF Hotel World — Federated RMF-core pod entrypoint.
#
# Runs RMF fleet management components:
#   - rmf-traffic-schedule
#   - rmf-task-dispatcher
#   - Fleet adapters (deliveryBot, tinyBot, cleanerBotA)
#   - rmf-web API server
#   - Dashboard
#   - Monotonic clock relay (Zenoh clock → /clock_bridge → /clock)
#
# Gazebo simulation runs in separate hotel-gazebo pod.
# Communication via Zenoh federation.

export HOME="/tmp/ros-home"
mkdir -p "${HOME}" "${HOME}/.ros" "${HOME}/.config"
export ROS_HOME="${HOME}/.ros"
export ROS_LOG_DIR="${HOME}/.ros/log"

source /opt/ros/jazzy/setup.bash
# Overlay A: rmf_ros2
if [ -f /opt/rmf_ros2_ws/install/setup.bash ]; then
  source /opt/rmf_ros2_ws/install/setup.bash
fi
# Overlay B: rmf_demos
if [ -f /opt/rmf_demos_ws/install/setup.bash ]; then
  source /opt/rmf_demos_ws/install/setup.bash
fi

export RMW_IMPLEMENTATION=rmw_cyclonedds_cpp
export ROS_DOMAIN_ID="${ROS_DOMAIN_ID:-55}"  # Separate from Gazebo domain 0
export PYTHONFAULTHANDLER=1

API_PORT="${API_PORT:-8000}"
DASHBOARD_PORT="${DASHBOARD_PORT:-3000}"
SERVER_URI="${SERVER_URI:-ws://localhost:8000/_internal}"

# --- Monotonic Clock Relay (same as rmf-core pod in tb3_sandbox demo) ---
echo "[hotel-rmf] Starting monotonic clock relay (Zenoh clock -> /clock_bridge -> /clock)..."
python3 - <<'PYEOF' &
import struct, threading, time
import zenoh

conf = zenoh.Config()
conf.insert_json5("connect/endpoints", '["tcp/zenoh-router:7447"]')
conf.insert_json5("mode", '"client"')
conf.insert_json5("scouting/multicast/enabled", "false")
z = zenoh.open(conf)

last_ns = 0
lock = threading.Lock()
RESTART_THRESHOLD_NS = 10 * 1_000_000_000  # 10s

# Publish filtered clock to clock_relay/clock_bridge
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

# Subscribe to Gazebo clock (published by hotel-gazebo pod's Zenoh bridge)
z.declare_subscriber('clock', on_clock)
print("[hotel-rmf] Monotonic clock relay active: clock -> clock_relay/clock_bridge")
while True:
    time.sleep(1)
PYEOF
CLOCK_RELAY_PID=$!
sleep 2

# --- Domain-55 /clock relay (for fleet adapters with use_sim_time) ---
echo "[hotel-rmf] Starting domain-55 clock relay (Zenoh clock -> ROS domain 55 /clock)..."
mkfifo /tmp/d55clock 2>/dev/null || true

cat > /tmp/d55_zenoh_half.py << 'D55_ZENOH_EOF'
import struct, time, sys, zenoh

conf = zenoh.Config()
conf.insert_json5("connect/endpoints", '["tcp/zenoh-router:7447"]')
conf.insert_json5("mode", '"client"')
conf.insert_json5("scouting/multicast/enabled", "false")
z = zenoh.open(conf)

last_ns = 0
RESTART_THRESHOLD_NS = 60 * 1_000_000_000

def on_clock(sample):
    global last_ns
    try:
        raw = bytes(sample.payload.to_bytes())
        if len(raw) < 12:
            return
        sec  = struct.unpack_from('<i', raw, 4)[0]
        nsec = struct.unpack_from('<I', raw, 8)[0]
        ns = sec * 1_000_000_000 + nsec
        if ns < last_ns:
            if (last_ns - ns) > RESTART_THRESHOLD_NS:
                last_ns = 0  # Gazebo restart
            else:
                return  # jitter
        last_ns = ns
        sys.stdout.write(f"{sec} {nsec}\n")
        sys.stdout.flush()
    except Exception:
        pass

z.declare_subscriber('clock', on_clock)
print("[d55-clock] Zenoh subscriber ready", file=sys.stderr)
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

rclpy.init(args=["domain55_clock_relay"])
node = Node("domain55_clock_relay")
qos = QoSProfile(depth=1, reliability=ReliabilityPolicy.BEST_EFFORT, history=HistoryPolicy.KEEP_LAST)
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

# --- rmf-web API server + dashboard ---
if python3 -c "import api_server" 2>/dev/null; then
  echo "[hotel-rmf] Starting rmf-web API server on port ${API_PORT}..."
  ( cd /opt/rmf-web/packages/api-server && python3 -m api_server ) &
  API_PID=$!
  echo "[hotel-rmf] Serving fleet dashboard on port ${DASHBOARD_PORT}..."
  ( cd /opt/rmf-dashboard && python3 -m http.server "${DASHBOARD_PORT}" 2>/dev/null ) &
  DASHBOARD_PID=$!
else
  echo "[hotel-rmf] rmf-web api_server not available — skipping dashboard."
  API_PID=""
  DASHBOARD_PID=""
fi

# --- Puppet controller (monitors /dispatch_states, sends navigate commands) ---
if [ -f /entrypoints/rmf_puppet_controller.py ]; then
  python3 /entrypoints/rmf_puppet_controller.py &
fi

# --- Publish 'map' TF root frame ---
ros2 run tf2_ros static_transform_publisher \
    --x 0 --y 0 --z 0 --roll 0 --pitch 0 --yaw 0 \
    --frame-id map --child-frame-id rmf_building \
    --ros-args -p use_sim_time:=true &

# --- Launch RMF components ---
echo "[hotel-rmf] Launching RMF traffic schedule..."
ros2 run rmf_traffic_ros2 rmf_traffic_schedule \
  --ros-args -p use_sim_time:=true &

echo "[hotel-rmf] Launching RMF task dispatcher..."
ros2 run rmf_task_ros2 rmf_task_dispatcher \
  -s "${SERVER_URI}" \
  --ros-args -p use_sim_time:=true &

sleep 5

# --- Launch fleet adapters ---
# Hotel has 3 fleets: TinyRobot, cleanerBotA, DeliveryRobot
# Each fleet adapter needs:
#   - Fleet configuration file
#   - Navigation graph
#   - Zenoh config (to receive robot state from Gazebo pod)
#   - use_sim_time for clock synchronization

echo "[hotel-rmf] Waiting for Zenoh bridges to establish routes..."
sleep 10

echo "[hotel-rmf] Launching fleet adapters (via Zenoh federation)..."

# Note: We need the fleet config files and nav graphs for the hotel world
# These should be in rmf_demos package or we need to create them
# For now, use the standard hotel launch approach but with Zenoh config

# Launch via the hotel launch file's fleet adapter components
# This is tricky - we may need to create custom launch files
# For now, let's try launching the common.launch.xml without Gazebo

ros2 launch rmf_demos common.launch.xml \
  use_sim_time:=True \
  server_uri:="${SERVER_URI}" &
LAUNCH_PID=$!

echo ""
echo "=================================================="
echo " Hotel RMF-core (Federated) Running"
echo "  RMF traffic schedule + task dispatcher + fleet adapters"
echo "  DDS domain : ${ROS_DOMAIN_ID}"
echo "  API server : port ${API_PORT}"
echo "  Dashboard  : port ${DASHBOARD_PORT}"
echo ""
echo " Gazebo simulation runs in separate hotel-gazebo pod"
echo " Connected via Zenoh federation with clock relay"
echo "=================================================="

term_handler() {
  echo "[hotel-rmf] Shutting down..."
  kill "${LAUNCH_PID:-}" "${API_PID:-}" "${DASHBOARD_PID:-}" \
       "${CLOCK_RELAY_PID:-}" "${D55_ZENOH_PID:-}" "${D55_ROS_PID:-}" 2>/dev/null || true
  pkill -P $$ 2>/dev/null || true
  wait "${LAUNCH_PID}" 2>/dev/null || true
}
trap term_handler SIGTERM SIGINT

wait "${LAUNCH_PID}"
