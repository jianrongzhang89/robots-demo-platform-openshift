#!/usr/bin/env bash
set -Eeo pipefail

export HOME=/tmp/ros-home
mkdir -p "${HOME}/.ros" "${HOME}/.config" /tmp/semantic-navigation
export ROS_HOME="${HOME}/.ros"
export ROS_LOG_DIR="${HOME}/.ros/log"
export ROS_DOMAIN_ID="${ROS_DOMAIN_ID:-0}"
export RMW_IMPLEMENTATION=rmw_cyclonedds_cpp
export GZ_IP="${GZ_IP:-127.0.0.1}"
export GZ_PARTITION="${GZ_PARTITION:-hotel_nav2_rmf}"

source /opt/ros/jazzy/setup.bash
source /opt/rmf_demos_ws/install/setup.bash
if [[ "${SEMANTIC_CAPTURE_TRACE:-0}" == "1" ]]; then
  export LD_LIBRARY_PATH="/opt/semantic-navigation/capture-lib:${LD_LIBRARY_PATH:-}"
fi
set -u

ASSET_DIR=/opt/ros2-demo/hotel-assets
WORLD=/tmp/semantic-navigation/hotel.world
cp "${ASSET_DIR}/hotel.world" "${WORLD}"
if [[ "${SEMANTIC_PHASE2_SCENE:-0}" == "1" ]]; then
  python3 /opt/semantic-navigation/install_phase1_camera.py "${WORLD}" --phase2-targets
else
  python3 /opt/semantic-navigation/install_phase1_camera.py "${WORLD}"
fi
export GZ_SIM_RESOURCE_PATH="${ASSET_DIR}/models:${ASSET_DIR}:/opt/rmf_demos_ws/install/share/rmf_demos_assets/models:${GZ_SIM_RESOURCE_PATH:-}"
export GZ_SIM_SYSTEM_PLUGIN_PATH="/opt/ros/jazzy/opt/gz_sim_vendor/lib/gz-sim-8/plugins:${GZ_SIM_SYSTEM_PLUGIN_PATH:-}"
export QT_QPA_PLATFORM=xcb
export QT_X11_NO_MITSHM=1
export DISPLAY="${DISPLAY:-:99}"
VNC_PORT="${VNC_PORT:-5900}"
NOVNC_PORT="${NOVNC_PORT:-6080}"

pids=()
cleanup() {
  trap - TERM INT EXIT
  for pid in "${pids[@]:-}"; do kill "${pid}" 2>/dev/null || true; done
  wait || true
}
trap cleanup TERM INT EXIT

Xorg "${DISPLAY}" -config /etc/X11/xorg-dummy.conf -nolisten tcp \
  -logfile /tmp/Xorg.semantic-navigation.log & pids+=("$!")
sleep 2
openbox >/tmp/openbox.semantic-navigation.log 2>&1 & pids+=("$!")
x11vnc -display "${DISPLAY}" -rfbport "${VNC_PORT}" -shared -forever -nopw -noxdamage -noscr \
  >/tmp/x11vnc.semantic-navigation.log 2>&1 & pids+=("$!")
websockify --web /usr/share/novnc "${NOVNC_PORT}" "localhost:${VNC_PORT}" \
  >/tmp/novnc.semantic-navigation.log 2>&1 & pids+=("$!")

gz sim --force-version 8 -r -s -v 2 "${WORLD}" >/tmp/gz-server.semantic-navigation.log 2>&1 &
pids+=("$!")
sleep 3
gz sim --force-version 8 -g -v 2 "${WORLD}" >/tmp/gz-gui.semantic-navigation.log 2>&1 &
pids+=("$!")
# Match rmf-hotel-world-openshift-ai's smoothed overhead GUI follow mode.
# The supervisor below handles recovery, but does not attach at startup.
# Wait for both the service and tracking subscriber: publishing earlier races
# the GUI scene. Bounded startup retries leave later manual pan/zoom alone.
initialize_camera_follow() {
  for _attempt in $(seq 1 90); do
    if timeout 3 gz service -i -s /gui/follow 2>/dev/null |
        grep -q 'gz.msgs.StringMsg, gz.msgs.Boolean' &&
        timeout 4 gz service -s /gui/follow \
          --reqtype gz.msgs.StringMsg --reptype gz.msgs.Boolean \
          --timeout 3000 --req 'data: "robot_1"' 2>/dev/null |
        grep -q 'data: true' &&
        timeout 4 gz service -s /gui/follow/offset \
          --reqtype gz.msgs.Vector3d --reptype gz.msgs.Boolean \
          --timeout 3000 --req 'x: 0 y: 0 z: 5' 2>/dev/null |
        grep -q 'data: true' &&
        timeout 3 gz topic -i -t /gui/track 2>/dev/null |
        grep -q 'Subscribers'; then
      for _publish in $(seq 1 3); do
        timeout 2 gz topic -t /gui/track -m gz.msgs.CameraTrack \
          -p 'track_mode: FOLLOW_LOOK_AT follow_target: {name: "robot_1"} track_target: {name: "robot_1"} follow_offset: {x: 0 y: 0 z: 5} track_offset: {x: 0 y: 0 z: 0} follow_pgain: 0.02 track_pgain: 0.02' \
          >/dev/null 2>&1 || true
        sleep 0.5
      done
      echo "[semantic-navigation] Gazebo camera following robot_1 (overhead)"
      return 0
    fi
    sleep 1
  done
  echo "[semantic-navigation] camera follow initialization timed out" >&2
  return 1
}
initialize_camera_follow >/tmp/camera-follow-startup.semantic-navigation.log 2>&1 &
pids+=("$!")
python3 /opt/ros2-demo/scripts/camera_follow_supervisor.py >/tmp/camera-follow.semantic-navigation.log 2>&1 &
pids+=("$!")
ros2 run robot_state_publisher robot_state_publisher \
  --ros-args -p use_sim_time:=true \
  -p robot_description:="$(< /opt/ros2-demo/robot/turtlebot3_waffle.urdf)" \
  -r /tf:=/robot_1/tf -r /tf_static:=/robot_1/tf_static \
  >/tmp/robot-state-publisher.semantic-navigation.log 2>&1 &
pids+=("$!")

ros2 run ros_gz_bridge parameter_bridge \
  /clock@rosgraph_msgs/msg/Clock[gz.msgs.Clock \
  /robot_1/cmd_vel@geometry_msgs/msg/Twist]gz.msgs.Twist \
  /robot_1/odom@nav_msgs/msg/Odometry[gz.msgs.Odometry \
  /scan@sensor_msgs/msg/LaserScan[gz.msgs.LaserScan \
  --ros-args -r /scan:=/robot_1/scan >/tmp/gz-bridge.semantic-navigation.log 2>&1 &
pids+=("$!")
ros2 launch ros_gz_bridge ros_gz_bridge.launch.py \
  bridge_name:=semantic_camera_bridge \
  config_file:=/opt/ros2-demo/config/semantic-camera-bridge.yaml \
  >/tmp/rgbd-bridge.semantic-navigation.log 2>&1 &
pids+=("$!")

echo "[semantic-navigation] isolated hotel simulator with RGB-D camera ready"
wait "${pids[4]}"
