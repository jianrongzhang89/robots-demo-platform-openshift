#!/usr/bin/env bash
set -Ee pipefail

# All processes in this container share one ROS graph. There is deliberately
# no Zenoh, domain relay, TF relay, clock relay, puppet, or Free Fleet process.
export HOME=/tmp/ros-home
mkdir -p "${HOME}/.ros" "${HOME}/.config"
export ROS_HOME="${HOME}/.ros"
export ROS_LOG_DIR="${HOME}/.ros/log"
export ROS_DOMAIN_ID="${ROS_DOMAIN_ID:-42}"
export RMW_IMPLEMENTATION=rmw_cyclonedds_cpp
export CYCLONEDDS_URI="${CYCLONEDDS_URI:-file:///opt/ros2-demo/config/cyclonedds.xml}"
# Keep Gazebo Transport local to this single-container simulation. Without an
# explicit address, discovery can crash during GUI startup in the pod network.
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
RESOLUTION="${RESOLUTION:-1600x900x24}"
VNC_PORT="${VNC_PORT:-5900}"
NOVNC_PORT="${NOVNC_PORT:-6080}"

pids=()
cleanup() {
  trap - TERM INT EXIT
  for pid in "${pids[@]:-}"; do kill "${pid}" 2>/dev/null || true; done
  wait || true
}
trap cleanup TERM INT EXIT

echo "[hotel-nav2-rmf] Starting Xorg/noVNC display on ${DISPLAY}"
Xorg "${DISPLAY}" -config /etc/X11/xorg-dummy.conf -nolisten tcp \
  -logfile /tmp/Xorg.hotel-nav2-rmf.log &
pids+=("$!")
sleep 2
openbox >/tmp/openbox.hotel-nav2-rmf.log 2>&1 &
pids+=("$!")
x11vnc -display "${DISPLAY}" -rfbport "${VNC_PORT}" -shared -forever -nopw -noxdamage -noscr &
pids+=("$!")
websockify --web /usr/share/novnc "${NOVNC_PORT}" "localhost:${VNC_PORT}" >/tmp/novnc.hotel-nav2-rmf.log 2>&1 &
pids+=("$!")

echo "[hotel-nav2-rmf] Starting Gazebo Harmonic from ${WORLD}"
mkdir -p /tmp/gz-gui-logs
gz sim --force-version 8 -r -s -v 2 "${WORLD}" >/tmp/gz-server.hotel-nav2-rmf.log 2>&1 &
GZ_SERVER_PID=$!
pids+=("${GZ_SERVER_PID}")
sleep 3
gz sim --force-version 8 -g -v 2 "${WORLD}" >/tmp/gz-gui.hotel-nav2-rmf.log 2>&1 &
GZ_GUI_PID=$!
pids+=("${GZ_GUI_PID}")
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
        for _topic_attempt in $(seq 1 20); do
          if gz topic -i -t /gui/track 2>/dev/null |
              grep -q 'Subscribers'; then
            break
          fi
          sleep 0.5
        done
        for _publish in $(seq 1 3); do
          timeout 2 gz topic -t /gui/track -m gz.msgs.CameraTrack \
            -p 'track_mode: FOLLOW_LOOK_AT follow_target: {name: "robot_1"} track_target: {name: "robot_1"} follow_offset: {x: 0 y: 0 z: 5} track_offset: {x: 0 y: 0 z: 0} follow_pgain: 0.02 track_pgain: 0.02' \
            >/dev/null 2>&1 || true
          sleep 0.5
        done
        echo "[hotel-nav2-rmf] Gazebo camera following robot_1"
      fi
      break
    fi
    sleep 1
  done
) &
pids+=("$!")
python3 /opt/ros2-demo/scripts/camera_follow_supervisor.py &
pids+=("$!")

wait_for_topic() {
  local topic="$1"
  local tries=60
  until ros2 topic list 2>/dev/null | grep -qx "${topic}"; do
    ((tries--)) || { echo "[hotel-nav2-rmf] timeout waiting for ${topic}" >&2; exit 1; }
    sleep 1
  done
}

echo "[hotel-nav2-rmf] Starting direct Gazebo ROS bridge"
ros2 run ros_gz_bridge parameter_bridge \
  /clock@rosgraph_msgs/msg/Clock[gz.msgs.Clock \
  /robot_1/cmd_vel@geometry_msgs/msg/Twist]gz.msgs.Twist \
  /robot_1/odom@nav_msgs/msg/Odometry[gz.msgs.Odometry \
  /scan@sensor_msgs/msg/LaserScan[gz.msgs.LaserScan \
  --ros-args \
  -r /scan:=/robot_1/scan &
pids+=("$!")

wait_for_topic /clock

ros2 run robot_state_publisher robot_state_publisher \
  --ros-args -p use_sim_time:=true \
  -p robot_description:="$(< /opt/ros2-demo/robot/turtlebot3_waffle.urdf)" \
  -r /tf:=/robot_1/tf -r /tf_static:=/robot_1/tf_static &
pids+=("$!")
python3 /opt/ros2-demo/scripts/odom_tf_authority.py \
  --ros-args -r /tf:=/robot_1/tf -r /tf_static:=/robot_1/tf_static &
pids+=("$!")
python3 /opt/ros2-demo/scripts/scan_frame_rewriter.py &
pids+=("$!")

echo "[hotel-nav2-rmf] Waiting for odom to base_footprint TF"
for attempt in $(seq 1 30); do
  if timeout 3 ros2 run tf2_ros tf2_echo odom base_footprint \
      --ros-args -r /tf:=/robot_1/tf -r /tf_static:=/robot_1/tf_static 2>/dev/null |
      grep -q Translation; then
    break
  fi
  [ "${attempt}" -eq 30 ] && { echo "odom TF unavailable" >&2; exit 1; }
  sleep 1
done

echo "[hotel-nav2-rmf] Starting lifecycle-driven Nav2"
ros2 launch /opt/ros2-demo/config/nav2/hotel_nav2_launch.py \
  namespace:=robot_1 map:=/opt/ros2-demo/maps/hotel_L1.yaml \
  params_file:=/opt/ros2-demo/config/nav2/hotel_nav2_params.yaml &
pids+=("$!")

echo "[hotel-nav2-rmf] Starting RMF schedule, map, lift, door, and dispatcher nodes"
ros2 run rmf_traffic_ros2 rmf_traffic_schedule --ros-args -p use_sim_time:=true &
pids+=("$!")
ros2 run rmf_traffic_ros2 rmf_traffic_blockade --ros-args -p use_sim_time:=true &
pids+=("$!")
ros2 run rmf_building_map_tools building_map_server "${ASSET_DIR}/hotel.building.yaml" \
  --ros-args -p use_sim_time:=true &
pids+=("$!")
python3 /opt/ros2-demo/scripts/lift_request_relay.py &
pids+=("$!")
ros2 run rmf_fleet_adapter door_supervisor --ros-args -p use_sim_time:=true &
pids+=("$!")
ros2 run rmf_task_ros2 rmf_task_dispatcher --ros-args \
  -p use_sim_time:=true \
  -p bidding_time_window:=2.0 \
  -p use_unique_hex_string_with_task_id:=true &
pids+=("$!")

for endpoint in /robot_1/navigate_to_pose /robot_1/map_server/load_map; do
  echo "[hotel-nav2-rmf] Waiting for ${endpoint}"
  for attempt in $(seq 1 90); do
    if ros2 action list 2>/dev/null | grep -qx "${endpoint}" || \
       ros2 service list 2>/dev/null | grep -qx "${endpoint}"; then break; fi
    [ "${attempt}" -eq 90 ] && { echo "endpoint unavailable: ${endpoint}" >&2; exit 1; }
    sleep 1
  done
done

echo "[hotel-nav2-rmf] Seeding AMCL on the initial floor"
for attempt in $(seq 1 30); do
  ros2 topic pub /robot_1/initialpose geometry_msgs/msg/PoseWithCovarianceStamped \
    "{header: {frame_id: map}, pose: {pose: {position: {x: ${INITIAL_X:-15.402}, y: ${INITIAL_Y:--31.594}}, orientation: {w: 1.0}}, covariance: [0.04,0,0,0,0,0, 0,0.04,0,0,0,0, 0,0,0,0,0,0, 0,0,0,0,0,0, 0,0,0,0,0,0, 0,0,0,0,0,0, 0,0,0,0,0,0.02]}}" \
    --qos-reliability reliable --times 1 >/dev/null 2>&1 || true
  sleep 1
  if timeout 3 ros2 run tf2_ros tf2_echo map base_footprint \
      --ros-args -r /tf:=/robot_1/tf -r /tf_static:=/robot_1/tf_static \
      2>&1 | grep -q "Translation:"; then
    echo "[hotel-nav2-rmf] AMCL map transform is available"
    break
  fi
  if [ "${attempt}" -eq 30 ]; then
    echo "[hotel-nav2-rmf] AMCL map transform not available yet; continuing startup" >&2
  fi
done

echo "[hotel-nav2-rmf] Waiting for RMF schedule startup"
for attempt in $(seq 1 60); do
  if ros2 topic list 2>/dev/null | grep -qx /rmf_traffic/schedule_startup; then
    break
  fi
  [ "${attempt}" -eq 60 ] && {
    echo "RMF schedule startup unavailable" >&2
    exit 1
  }
  sleep 1
done
sleep 3

echo "[hotel-nav2-rmf] Starting local EasyFullControl adapter"
python3 /opt/ros2-demo/scripts/local_nav2_fleet_adapter.py \
  --fleet-config /opt/ros2-demo/rmf/fleet_config.yaml \
  --nav-graph /opt/ros2-demo/rmf/nav_graph.yaml \
  --robot-name robot_1 --initial-map L1 \
  --initial-x "${INITIAL_X:-15.402}" \
  --initial-y "${INITIAL_Y:--31.594}" \
  --initial-yaw "${INITIAL_YAW:-0.0}" &
ADAPTER_PID=$!
pids+=("${ADAPTER_PID}")
wait "${ADAPTER_PID}"
