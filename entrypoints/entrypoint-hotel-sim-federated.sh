#!/usr/bin/env bash
set -Eeo pipefail

# Federated Gazebo role using the canonical hotel assets. Nav2 and RMF run in
# separate pods; this process owns only the simulator, robot bridge, and GUI.
export HOME=/tmp/ros-home
mkdir -p "${HOME}/.ros" "${HOME}/.config"
export ROS_HOME="${HOME}/.ros"
export ROS_LOG_DIR="${HOME}/.ros/log"
export ROS_DOMAIN_ID="${ROS_DOMAIN_ID:-0}"
export RMW_IMPLEMENTATION=rmw_cyclonedds_cpp
export GZ_IP="${GZ_IP:-127.0.0.1}"
export GZ_PARTITION="${GZ_PARTITION:-hotel_nav2_rmf}"

source /opt/ros/jazzy/setup.bash
source /opt/rmf_demos_ws/install/setup.bash
set -u

ASSET_DIR=/opt/ros2-demo/hotel-assets
WORLD="${ASSET_DIR}/hotel.world"
export GZ_SIM_RESOURCE_PATH="${ASSET_DIR}/models:${ASSET_DIR}:/opt/rmf_demos_ws/install/share/rmf_demos_assets/models:${GZ_SIM_RESOURCE_PATH:-}"
export GZ_SIM_SYSTEM_PLUGIN_PATH="/opt/ros/jazzy/opt/gz_sim_vendor/lib/gz-sim-8/plugins:${GZ_SIM_SYSTEM_PLUGIN_PATH:-}"
export QT_QPA_PLATFORM=xcb
export QT_X11_NO_MITSHM=1
export DISPLAY="${DISPLAY:-:99}"
VNC_PORT="${VNC_PORT:-5900}"
NOVNC_PORT="${NOVNC_PORT:-6080}"
RESOLUTION="${RESOLUTION:-1600x900x24}"

pids=()
cleanup() {
  trap - TERM INT EXIT
  for pid in "${pids[@]:-}"; do kill "${pid}" 2>/dev/null || true; done
  wait || true
}
trap cleanup TERM INT EXIT

echo "[hotel-sim] Starting canonical hotel world from ${WORLD}"
Xorg "${DISPLAY}" -config /etc/X11/xorg-dummy.conf -nolisten tcp \
  -logfile /tmp/Xorg.hotel-sim.log &
pids+=("$!")
sleep 2
openbox >/tmp/openbox.hotel-sim.log 2>&1 &
pids+=("$!")
x11vnc -display "${DISPLAY}" -rfbport "${VNC_PORT}" -shared -forever -nopw -noxdamage -noscr &
pids+=("$!")
websockify --web /usr/share/novnc "${NOVNC_PORT}" "localhost:${VNC_PORT}" \
  >/tmp/novnc.hotel-sim.log 2>&1 &
pids+=("$!")

gz sim --force-version 8 -r -s -v 2 "${WORLD}" >/tmp/gz-server.hotel-sim.log 2>&1 &
pids+=("$!")
sleep 3
gz sim --force-version 8 -g -v 2 "${WORLD}" >/tmp/gz-gui.hotel-sim.log 2>&1 &
pids+=("$!")

# Match the canonical single-pod camera behavior: follow robot_1 and keep the
# camera attached after Gazebo GUI/plugin restarts.
(
  for _attempt in $(seq 1 90); do
    if gz service -i -s /gui/follow 2>/dev/null |
        grep -q 'gz.msgs.StringMsg, gz.msgs.Boolean'; then
      if gz service -s /gui/follow \
          --reqtype gz.msgs.StringMsg --reptype gz.msgs.Boolean \
          --timeout 3000 --req 'data: "robot_1"' 2>/dev/null |
          grep -q 'data: true'; then
        gz service -s /gui/follow/offset \
          --reqtype gz.msgs.Vector3d --reptype gz.msgs.Boolean \
          --timeout 3000 --req 'x: 0 y: 0 z: 5' >/dev/null 2>&1 || true
        echo "[hotel-sim] Gazebo camera following robot_1"
      fi
      break
    fi
    sleep 1
  done
) &
pids+=("$!")
python3 /opt/ros2-demo/scripts/camera_follow_supervisor.py &
pids+=("$!")

echo "[hotel-sim] Starting ROS 2 bridge for canonical robot_1"
ros2 run ros_gz_bridge parameter_bridge \
  /clock@rosgraph_msgs/msg/Clock[gz.msgs.Clock \
  /robot_1/cmd_vel@geometry_msgs/msg/Twist]gz.msgs.Twist \
  /robot_1/odom@nav_msgs/msg/Odometry[gz.msgs.Odometry \
  /scan@sensor_msgs/msg/LaserScan[gz.msgs.LaserScan \
  --ros-args -r /scan:=/robot_1/scan &
pids+=("$!")

echo "[hotel-sim] Canonical federated Gazebo simulation ready"
wait "${pids[4]}"
