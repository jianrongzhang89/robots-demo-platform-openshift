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
if [[ "${PHASE8_MULTILEVEL_SEMANTIC:-0}" == "1" ]]; then
  if [[ -f /opt/semantic-costmap-ws/install/setup.bash ]]; then
    source /opt/semantic-costmap-ws/install/setup.bash
  else
    source /opt/rmf_demos_ws/install/setup.bash
  fi
  export LD_LIBRARY_PATH="/opt/semantic-navigation/capture-lib:${LD_LIBRARY_PATH:-}"
  export SEMANTIC_CAPTURE_TRACE=1
fi
set -u

ASSET_DIR=/opt/ros2-demo/hotel-assets
WORLD="${ASSET_DIR}/hotel.world"
MAP_DIR=/opt/ros2-demo/maps
ROBOT_URDF=/opt/ros2-demo/robot/turtlebot3_waffle.urdf
if [[ "${PHASE8_MULTILEVEL_SEMANTIC:-0}" == "1" ]]; then
  WORLD=/tmp/phase8-multilevel-hotel.world
  cp "${ASSET_DIR}/hotel.world" "${WORLD}"
  ROBOT_URDF=/tmp/phase8-robot.urdf
  MAP_DIR=/tmp/phase8-maps
  export HOTEL_MAP_TEMPLATE=/tmp/phase8-maps/hotel_{level}.yaml
  python3 /opt/ros2-demo/scripts/phase8_lift_maps.py \
    --source /opt/ros2-demo/maps --models "${ASSET_DIR}/models" --output "${MAP_DIR}"
  python3 - "${WORLD}" <<'PY'
import sys
import os
import xml.etree.ElementTree as ET

from pathlib import Path
sys.path.insert(0, "/opt/ros2-demo/scripts")
from support_geometry import add_rear_casters
path = sys.argv[1]
world, urdf = add_rear_casters(Path(path).read_text(),
    Path("/opt/ros2-demo/robot/turtlebot3_waffle.urdf").read_text())
Path(path).write_text(world)
Path("/tmp/phase8-robot.urdf").write_text(urdf)
tree = ET.parse(path)
# Resolve the small wheel contacts on floors. During vertical travel,
# the detachable payload joint supplies support for the wheel-driven robot;
# contact alone on the inherited thin platform was not reliable.
tree.getroot().find('.//physics/max_step_size').text = '0.005'
robot = tree.getroot().find(".//model[@name='robot_1']")
robot.find('pose').text = f"{os.environ.get('INITIAL_X', '15.402')} {os.environ.get('INITIAL_Y', '-31.594')} 0.02 0 0 {os.environ.get('INITIAL_YAW', '0')}"
for lift_name in ('Lift1', 'Lift2'):
    component = tree.getroot().find(f".//model[@name='{lift_name}']/plugin/component[@name='Lift']")
    component.find('v_max_cabin').text = '1.0'
    component.find('a_max_cabin').text = '0.6'
    component.find('a_nom_cabin').text = '0.5'
lift = tree.getroot().find(".//model[@name='Lift2']")
plugin = ET.SubElement(lift, 'plugin', {'filename':'gz-sim-detachable-joint-system',
                                      'name':'gz::sim::systems::DetachableJoint'})
for key, value in {'parent_link':'platform', 'child_model':'robot_1',
                   'child_link':'base_link', 'attach_topic':'/phase8/lift2/attach',
                   'detach_topic':'/phase8/lift2/detach',
                   'output_topic':'/phase8/lift2/joint_state'}.items():
    ET.SubElement(plugin, key).text = value
sensors = [s for s in tree.getroot().iter("sensor")
           if s.get("name") == "rgbd_camera"]
if len(sensors) != 1:
    raise SystemExit(f"expected one semantic RGB-D camera, found {len(sensors)}")
sensors[0].find("update_rate").text = "5"
mat = tree.getroot().find(".//model[@name='semantic_target_mat']")
if mat is None:
    raise SystemExit("Phase 8 semantic target mat is missing from the world")
mat.find("pose").text = (
    f"{os.environ.get('PHASE8_MAT_X', '15.138498')} "
    f"{os.environ.get('PHASE8_MAT_Y', '-30.180363')} 0.005 0 0 "
    f"{os.environ.get('PHASE8_MAT_YAW', '1.755291')}")
mat.find("./link[@name='surface']/visual/geometry/box/size").text = (
    f"{os.environ.get('PHASE8_MAT_SIZE_X', '1.0')} "
    f"{os.environ.get('PHASE8_MAT_SIZE_Y', '1.4')} 0.012")
tree.write(path, encoding="utf-8", xml_declaration=True)
print("[hotel-nav2-rmf] Phase 8 RGB-D sensor set to 5 Hz and red mat rotated across the direct L1 spawn-to-lift route")
PY
  # Give the actual L1 spawn vertex a stable RMF place name so the patrol can
  # finish at its starting point. Keep the source hotel asset untouched.
  export PHASE8_BUILDING_MAP=/tmp/phase8-hotel.building.yaml
  export PHASE8_NAV_GRAPH=/tmp/phase8-nav-graph.yaml
  cp "${ASSET_DIR}/hotel.building.yaml" "${PHASE8_BUILDING_MAP}"
  cp /opt/ros2-demo/rmf/nav_graph.yaml "${PHASE8_NAV_GRAPH}"
  python3 - "${PHASE8_BUILDING_MAP}" "${PHASE8_NAV_GRAPH}" <<'PY'
import sys
import yaml
from pathlib import Path

building_path, graph_path = map(Path, sys.argv[1:])
building = yaml.safe_load(building_path.read_text())
vertices = building["levels"]["L1"]["vertices"]
spawn = vertices[0]
if len(spawn) < 4 or abs(float(spawn[0]) - 127.862) > 0.01 or abs(float(spawn[1]) - 550.573) > 0.01:
    raise SystemExit(f"unexpected L1 spawn vertex in building map: {spawn}")
spawn[3] = "phase8_spawn"
building_path.write_text(yaml.safe_dump(building, sort_keys=False))

graph = yaml.safe_load(graph_path.read_text())
graph_spawn = graph["levels"]["L1"]["vertices"][0]
if abs(float(graph_spawn[0]) - 15.4022548269) > 0.1 or abs(float(graph_spawn[1]) + 31.5937207011) > 0.1:
    raise SystemExit(f"unexpected L1 spawn vertex in RMF graph: {graph_spawn}")
graph_spawn[2]["name"] = "phase8_spawn"
graph_path.write_text(yaml.safe_dump(graph, sort_keys=False))
print("[hotel-nav2-rmf] Named the L1 spawn vertex phase8_spawn in RMF maps")
PY
fi
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
# Keep the client GUI's Gazebo config and log directory separate from the
# server's. Sharing ~/.gz between the two processes can crash GUI startup in
# the pod, leaving noVNC connected to an empty X desktop.
GZ_GUI_HOME=/tmp/gz-gui-home
GZ_GUI_RUNTIME=/tmp/gz-gui-runtime
mkdir -p "${GZ_GUI_HOME}/.gz" "${GZ_GUI_RUNTIME}"
chmod 700 "${GZ_GUI_RUNTIME}"
(export HOME="${GZ_GUI_HOME}" XDG_RUNTIME_DIR="${GZ_GUI_RUNTIME}"
  exec gz sim --force-version 8 -g -v 2 "${WORLD}") \
  >/tmp/gz-gui.hotel-nav2-rmf.log 2>&1 &
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
ODOM_ROS_TOPIC=/robot_1/odom
if [[ "${PHASE8_MULTILEVEL_SEMANTIC:-0}" == "1" ]]; then
  ODOM_ROS_TOPIC=/robot_1/wheel_odom
  python3 /opt/ros2-demo/scripts/phase8_sim_odometry.py >/tmp/phase8-sim-odometry.log 2>&1 &
  pids+=("$!")
fi
ros2 run ros_gz_bridge parameter_bridge \
  /clock@rosgraph_msgs/msg/Clock[gz.msgs.Clock \
  /robot_1/cmd_vel@geometry_msgs/msg/Twist]gz.msgs.Twist \
  /robot_1/odom@nav_msgs/msg/Odometry[gz.msgs.Odometry \
  /scan@sensor_msgs/msg/LaserScan[gz.msgs.LaserScan \
  --ros-args \
  -r /scan:=/robot_1/scan -r /robot_1/odom:="${ODOM_ROS_TOPIC}" &
pids+=("$!")

if [[ "${PHASE8_MULTILEVEL_SEMANTIC:-0}" == "1" ]]; then
  echo "[hotel-nav2-rmf] Starting the Phase 8 RGB-D bridge and camera compressor"
  ros2 launch ros_gz_bridge ros_gz_bridge.launch.py \
    bridge_name:=phase8_rgbd_camera_bridge \
    config_file:=/opt/ros2-demo/config/phase8-rgbd-camera-bridge.yaml &
  pids+=("$!")
  for attempt in $(seq 1 90); do
    if timeout 3 ros2 topic info /robot_1/camera/capture_trace 2>/dev/null |
         grep -q "Publisher count: 1"; then
      break
    fi
    [ "${attempt}" -eq 90 ] && {
      echo "Phase 8 camera capture-trace bridge did not start" >&2
      exit 1
    }
    sleep 1
  done
  SEMANTIC_RAW_INPUT=ros SEMANTIC_COMPRESSION_TRACE=1 \
    python3 /opt/ros2-demo/scripts/camera_compressor.py \
    >/tmp/phase8-camera-compressor.log 2>&1 &
  pids+=("$!")
fi

wait_for_topic /clock

ros2 run robot_state_publisher robot_state_publisher \
  --ros-args -p use_sim_time:=true \
  -p robot_description:="$(< "${ROBOT_URDF}")" \
  -r /tf:=/robot_1/tf -r /tf_static:=/robot_1/tf_static &
pids+=("$!")
python3 /opt/ros2-demo/scripts/odom_tf_authority.py \
  --ros-args -r /tf:=/robot_1/tf -r /tf_static:=/robot_1/tf_static &
pids+=("$!")
python3 /opt/ros2-demo/scripts/scan_frame_rewriter.py &
pids+=("$!")

if [[ "${PHASE8_MULTILEVEL_SEMANTIC:-0}" == "1" ]]; then
  python3 /opt/ros2-demo/scripts/phase8_physics_monitor.py >/tmp/phase8-physics.log 2>&1 &
  pids+=("$!")
fi

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
  namespace:=robot_1 map:="${MAP_DIR}/hotel_L1.yaml" \
  params_file:="${NAV2_PARAMS:-/opt/ros2-demo/config/nav2/hotel_nav2_params.yaml}" &
pids+=("$!")

echo "[hotel-nav2-rmf] Starting RMF schedule, map, lift, door, and dispatcher nodes"
ros2 run rmf_traffic_ros2 rmf_traffic_schedule --ros-args -p use_sim_time:=true &
pids+=("$!")
ros2 run rmf_traffic_ros2 rmf_traffic_blockade --ros-args -p use_sim_time:=true &
pids+=("$!")
ros2 run rmf_building_map_tools building_map_server "${PHASE8_BUILDING_MAP:-${ASSET_DIR}/hotel.building.yaml}" \
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
  --nav-graph "${PHASE8_NAV_GRAPH:-/opt/ros2-demo/rmf/nav_graph.yaml}" \
  --robot-name robot_1 --initial-map L1 \
  --initial-x "${INITIAL_X:-15.402}" \
  --initial-y "${INITIAL_Y:--31.594}" \
  --initial-yaw "${INITIAL_YAW:-0.0}" &
ADAPTER_PID=$!
pids+=("${ADAPTER_PID}")
wait "${ADAPTER_PID}"
