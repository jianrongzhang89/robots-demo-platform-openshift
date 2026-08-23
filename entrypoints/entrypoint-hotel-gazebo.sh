#!/usr/bin/env bash
set -eo pipefail

# Open-RMF Hotel World Gazebo — Federated architecture entrypoint.
#
# Runs ONLY the hotel building simulation (Gazebo with door/lift plugins).
# Does NOT spawn slotcar robots — real TurtleBot3 robots are spawned by
# separate Nav2 pods and bridge topics via Zenoh.
#
# Env vars:
#   ROBOTS         space-separated "name:x:y:yaw:r,g,b" tuples
#   WORLD_NAME     unused (always hotel)
#   DISPLAY_NUM    Xvfb display number (default: 99)
#   RESOLUTION     Xvfb resolution (default: 1600x900x24)

export HOME="/tmp/ros-home"
mkdir -p "${HOME}" "${HOME}/.ros" "${HOME}/.config" "${HOME}/.gz"
export ROS_HOME="${HOME}/.ros"
export ROS_LOG_DIR="${HOME}/.ros/log"

source /opt/ros/jazzy/setup.bash
# Overlay: rmf_demos (hotel world, building assets, door/lift plugins)
if [ -f /opt/rmf_demos_ws/install/setup.bash ]; then
  source /opt/rmf_demos_ws/install/setup.bash
fi

export RMW_IMPLEMENTATION=rmw_cyclonedds_cpp
export PYTHONFAULTHANDLER=1
export ROS_DOMAIN_ID="${ROS_DOMAIN_ID:-0}"

# CPU software rendering (no GPU)
export LIBGL_ALWAYS_SOFTWARE=1
export GALLIUM_DRIVER=llvmpipe

# Force Qt6 to use X11 (xcb) platform
export QT_QPA_PLATFORM=xcb
export QT_X11_NO_MITSHM=1

# Gazebo model search path
# hotel world expects Open-RMF/ models and rmf_demos_assets
export GZ_SIM_RESOURCE_PATH="/opt/gz-models:/opt/rmf_demos_ws/install/share/rmf_demos_assets/models:/opt/rmf_demos_ws/install/share/rmf_demos_maps"

WEB_PORT="${WEB_PORT:-8080}"
VNC_PORT="${VNC_PORT:-5900}"
NOVNC_PORT="${NOVNC_PORT:-6080}"
DISPLAY_NUM="${DISPLAY_NUM:-99}"
RESOLUTION="${RESOLUTION:-1600x900x24}"

# Space-separated "name:x:y:yaw:r,g,b" robot definitions
# These will be spawned as TurtleBot3 Waffles (not slotcar)
ROBOTS="${ROBOTS:-robot_1:14.87:-28.77:0.0:1,0,0 robot_2:22.0:-26.5:0.0:0,0.5,1 robot_3:15.0:-30.5:0.0:0.5,0.5,0.5 robot_4:22.0:-33.5:0.0:0.5,0.5,0.5}"
ROBOT_NAMES="${ROBOT_NAMES:-robot_1 robot_2 robot_3 robot_4}"

export DISPLAY=":${DISPLAY_NUM}"

# --- 1. Display server (Xorg + dummy driver) ---
echo "[hotel-gazebo-pod] Starting Xorg (dummy driver) on display ${DISPLAY}..."
Xorg "${DISPLAY}" -config /etc/X11/xorg-dummy.conf \
    -nolisten tcp -logfile /tmp/Xorg.${DISPLAY_NUM}.log &
XVFB_PID=$!
sleep 2

# --- 2. Window manager ---
echo "[hotel-gazebo-pod] Starting openbox window manager..."
openbox &

# --- 3. VNC server ---
echo "[hotel-gazebo-pod] Starting x11vnc on port ${VNC_PORT}..."
x11vnc -display "${DISPLAY}" -rfbport "${VNC_PORT}" -shared -forever -nopw -noxdamage -noscr &

# --- 4. noVNC web proxy ---
echo "[hotel-gazebo-pod] Starting noVNC on port ${NOVNC_PORT}..."
websockify --web /usr/share/novnc "${NOVNC_PORT}" "localhost:${VNC_PORT}" &

# --- 5. Web landing page ---
echo "[hotel-gazebo-pod] Starting web landing page on port ${WEB_PORT}..."
python3 -m http.server "${WEB_PORT}" --directory /opt/ros2-demo/www &

# --- 6. Launch hotel building simulation (WITHOUT fleet adapters or slotcar robots) ---
# We launch only the Gazebo simulation with the hotel building, doors, and lifts.
# Real TurtleBot3 robots will be spawned below and managed by separate Nav2 pods.
echo "[hotel-gazebo-pod] Launching hotel building simulation..."
echo "  Note: NOT launching slotcar fleet adapters — using Nav2 robots instead"

# Create a minimal launch configuration that only starts Gazebo with the hotel world
# We'll manually launch gz sim with the hotel world instead of using the full hotel.launch.xml
HOTEL_WORLD="/opt/rmf_demos_ws/install/share/rmf_demos_maps/maps/hotel/hotel.world.sdf"

if [ ! -f "$HOTEL_WORLD" ]; then
  echo "[hotel-gazebo-pod] ERROR: hotel world file not found at $HOTEL_WORLD"
  echo "  Searching for hotel world files..."
  find /opt/rmf_demos_ws/install/share/rmf_demos_maps -name "*hotel*" -type f
  exit 1
fi

echo "[hotel-gazebo-pod] Starting Gazebo with hotel world..."
gz sim -r -s -v 4 "${HOTEL_WORLD}" &
GZ_SERVER_PID=$!

# --- 7. Wait for Gazebo to be ready ---
echo "[hotel-gazebo-pod] Waiting for Gazebo server to start..."
for i in $(seq 1 60); do
  if gz topic -l 2>/dev/null | grep -q "/world/"; then
    WORLD_NAME=$(gz topic -l 2>/dev/null | grep "/world/" | head -1 | cut -d'/' -f3)
    echo "[hotel-gazebo-pod] Gazebo server detected after $((i * 2))s, world: ${WORLD_NAME}"
    break
  fi
  sleep 2
done

# --- 8. Spawn TurtleBot3 robots in the hotel lobby (L1) ---
# These replace the slotcar robots with real Nav2-capable TurtleBot3 Waffles
SIM_DIR="/opt/ros/jazzy/share/nav2_minimal_tb3_sim"
BASE_SDF="${SIM_DIR}/urdf/gz_waffle.sdf.xacro"

if [ ! -f "$BASE_SDF" ]; then
  echo "[hotel-gazebo-pod] ERROR: TurtleBot3 Waffle SDF not found at $BASE_SDF"
  echo "  This demo requires nav2_minimal_tb3_sim package"
  exit 1
fi

echo "[hotel-gazebo-pod] Spawning TurtleBot3 robots: ${ROBOTS}"
SPAWN_PIDS=()
for spec in ${ROBOTS}; do
  IFS=: read -r rname rx ry ryaw rcolor <<< "${spec}"
  rcolor="${rcolor:-1,1,1}"
  # Convert comma-separated r,g,b to space-separated for SDF diffuse tag
  diffuse="$(echo "${rcolor}" | tr ',' ' ')"

  # Generate a color-patched SDF xacro for this robot
  PATCHED_SDF="/tmp/${rname}_waffle.sdf.xacro"
  python3 -c "
content = open('${BASE_SDF}').read()
content = content.replace('<diffuse>1 1 1</diffuse>', '<diffuse>${diffuse}</diffuse>')
open('${PATCHED_SDF}', 'w').write(content)
"
  echo "[hotel-gazebo-pod] Spawning ${rname} at (${rx}, ${ry}, yaw=${ryaw}) color=(${diffuse})..."
  ros2 launch nav2_minimal_tb3_sim spawn_tb3.launch.py \
    use_sim_time:=True \
    namespace:="${rname}" \
    robot_name:="${rname}" \
    x_pose:="${rx}" \
    y_pose:="${ry}" \
    z_pose:=0.01 \
    yaw_pose:="${ryaw}" \
    robot_sdf:="${PATCHED_SDF}" &
  SPAWN_PIDS+=($!)

  # robot_state_publisher per robot — remap /tf to /robot_N/tf for Zenoh routing
  ros2 run robot_state_publisher robot_state_publisher \
    --ros-args \
    --remap __ns:=/"${rname}" \
    --remap /tf:=/"${rname}"/tf \
    --remap /tf_static:=/"${rname}"/tf_static \
    -p use_sim_time:=true \
    -p robot_description:="$(cat ${SIM_DIR}/urdf/turtlebot3_waffle.urdf)" &
done

# Wait for all spawn jobs to complete
for pid in "${SPAWN_PIDS[@]}"; do
  wait "${pid}" 2>/dev/null || echo "[hotel-gazebo-pod] Spawn job ${pid} completed"
done

# --- 9. Start gz_world_pos_pub.py to publish robot positions ---
# This publishes world-frame positions of all robots to /robot_N/gz_world_pos
echo "[hotel-gazebo-pod] Starting gz_world_pos_pub.py for robot position tracking..."
cat > /tmp/gz_world_pos_pub.py << 'GZ_POS_EOF'
import subprocess, re, zenoh, time, os, signal, math

ROUTER  = "tcp/zenoh-router:7447"
ROBOTS  = os.environ.get('ROBOT_NAMES', 'robot_1 robot_2 robot_3 robot_4').split()
WORLD   = os.environ.get('WORLD_NAME', 'hotel')
TOPIC   = f'/world/{WORLD}/dynamic_pose/info'
GZ_ENV  = {**os.environ,
            'GZ_SIM_RESOURCE_PATH': '/opt/rmf_demos_ws/install/share',
            'HOME': '/tmp'}

signal.signal(signal.SIGTERM, lambda s, f: None)
signal.signal(signal.SIGINT,  lambda s, f: None)

while True:
    try:
        conf = zenoh.Config()
        conf.insert_json5('connect/endpoints', f'["{ROUTER}"]')
        conf.insert_json5('mode', '"client"')
        conf.insert_json5('scouting/multicast/enabled', 'false')
        z = zenoh.open(conf)
        pubs = {r: z.declare_publisher(f'{r}/gz_world_pos') for r in ROBOTS}
        print('[gz-pos] Gazebo world-pos publisher started', flush=True)

        while True:
            try:
                res = subprocess.run(
                    ['gz', 'topic', '-e', '-t', TOPIC, '-n', '1'],
                    capture_output=True, text=True, timeout=3, env=GZ_ENV)
                txt = res.stdout
                for robot in ROBOTS:
                    m = re.search(
                        rf'name: "{robot}".*?'
                        r'position \{\s*x: ([-\d.e+]+)\s*y: ([-\d.e+]+).*?'
                        r'orientation \{\s*x: ([-\d.e+]+)\s*y: ([-\d.e+]+)'
                        r'\s*z: ([-\d.e+]+)\s*w: ([-\d.e+]+)',
                        txt, re.DOTALL)
                    if m:
                        px, py = float(m.group(1)), float(m.group(2))
                        qz, qw = float(m.group(5)), float(m.group(6))
                        yaw = 2.0 * math.atan2(qz, qw)
                        pubs[robot].put(f'{px:.6f} {py:.6f} {yaw:.6f}'.encode())
            except subprocess.TimeoutExpired:
                pass
            except Exception as e:
                print(f'[gz-pos] query error: {e}', flush=True)
            time.sleep(0.3)
    except BaseException as e:
        print(f'[gz-pos] restarting after: {e}', flush=True)
        time.sleep(3)
GZ_POS_EOF
python3 /tmp/gz_world_pos_pub.py &

echo ""
echo "=================================================="
echo " Hotel World Gazebo (Federated) Running"
echo "  World      : ${WORLD_NAME}"
echo "  Robots     : ${ROBOT_NAMES}"
echo "  DDS domain : ${ROS_DOMAIN_ID}"
echo "  noVNC      : port ${NOVNC_PORT}"
echo ""
echo " Real TurtleBot3 robots spawned in hotel lobby."
echo " Fleet management via rmf-core pod + Zenoh federation."
echo "=================================================="

term_handler() {
  echo "[hotel-gazebo-pod] Shutting down..."
  kill "${GZ_SERVER_PID:-}" "${XVFB_PID:-}" 2>/dev/null || true
  pkill -P $$ 2>/dev/null || true
  wait "${GZ_SERVER_PID}" 2>/dev/null || true
}
trap term_handler SIGTERM SIGINT

wait "${GZ_SERVER_PID}"
