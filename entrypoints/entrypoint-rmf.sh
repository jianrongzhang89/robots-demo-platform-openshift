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
echo "[rmf-pod] Starting sim clock relay (Zenoh 'clock' -> ROS /clock on domain 55)..."
python3 - <<'PYEOF' &
import zenoh, rclpy, threading
from rclpy.node import Node
from rosgraph_msgs.msg import Clock as RosClock
from builtin_interfaces.msg import Time as RosTime
import struct

rclpy.init()
n = Node('rmf_clock_relay')
pub = n.create_publisher(RosClock, '/clock', 10)

def spin(): rclpy.spin(n)
threading.Thread(target=spin, daemon=True).start()

conf = zenoh.Config()
conf.insert_json5("connect/endpoints", """["tcp/zenoh-router:7447"]""")
conf.insert_json5("mode", "\"client\"")
conf.insert_json5("scouting/multicast/enabled", "false")
z = zenoh.open(conf)

def on_clock(sample):
    try:
        raw = bytes(sample.payload.to_bytes())
        # CDR Clock: 4-byte header + int32 sec + uint32 nanosec
        if len(raw) >= 12:
            sec  = struct.unpack_from('<i', raw, 4)[0]
            nsec = struct.unpack_from('<I', raw, 8)[0]
            msg = RosClock()
            msg.clock = RosTime(sec=sec, nanosec=nsec)
            pub.publish(msg)
    except Exception:
        pass

sub = z.declare_subscriber("clock", on_clock)
import time
while True:
    time.sleep(1)
PYEOF
CLOCK_RELAY_PID=$!
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
# No use_sim_time — domain 55 has no /clock, so wall time must be used
ros2 run rmf_traffic_ros2 rmf_traffic_schedule &
SCHEDULE_PID=$!
sleep 3

echo "[rmf-pod] Launching RMF task dispatcher..."
ros2 run rmf_task_ros2 rmf_task_dispatcher &
DISPATCHER_PID=$!
sleep 2

# Wait for both robots' AMCL to localize and publish TF before the adapter
# tries to initialize (it has only a 10-second window per robot).
echo "[rmf-pod] Waiting 60s for AMCL to localize both robots..."
sleep 60

ZENOH_CONFIG="${ZENOH_CONFIG:-/opt/ros2-demo/zenoh/fleet-adapter-zenoh.json5}"
echo "[rmf-pod] Launching free_fleet adapter (fleet_adapter.py) with zenoh config: ${ZENOH_CONFIG}..."
# NOTE: -sim flag removed — domain 55 has no /clock topic so sim time
# causes the dispatcher time_window timer to never fire (no task awards).
# Wall time always advances correctly.
ros2 run free_fleet_adapter fleet_adapter.py \
  -c "${FLEET_CONFIG}" \
  -n "${NAV_GRAPH}" \
  --zenoh-config "${ZENOH_CONFIG}" \
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
       "${API_PID:-}" "${CLOCK_RELAY_PID:-}" 2>/dev/null || true
  pkill -P $$ 2>/dev/null || true
  wait "${ADAPTER_PID}" 2>/dev/null || true
}

trap term_handler SIGTERM SIGINT

wait "${ADAPTER_PID}"
