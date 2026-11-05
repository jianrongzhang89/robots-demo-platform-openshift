#!/usr/bin/env bash
# ROS setup scripts reference optional variables that may be unset, so do not
# enable nounset here. Keep failures and pipeline errors fatal.
set -eo pipefail

export HOME=/tmp/phase6-nav2-home
export ROS_LOG_DIR=/tmp/phase6-nav2-logs
export ROS_DOMAIN_ID=86
export RMW_IMPLEMENTATION=rmw_cyclonedds_cpp
export ROS_DISTRO=jazzy
mkdir -p "$HOME" "$ROS_LOG_DIR"

source /opt/ros/jazzy/setup.bash
source /opt/semantic-costmap-ws/install/setup.bash
grep -Fqx 'source /opt/semantic-costmap-ws/install/setup.bash' \
  /entrypoint-nav2-federated.sh
test "$(ros2 pkg prefix demo_semantic_costmap)" = "/opt/semantic-costmap-ws/install"

params=/phase6-nav2/nav2-params.yaml
test -r "$params"
test -f /opt/semantic-costmap-ws/install/share/demo_semantic_costmap/plugins.xml

# Configure the Nav2 controller and planner servers, which own the local and
# global costmaps respectively. Do not activate either server, send an action
# goal, start a simulator, or connect a command bridge. The unique ROS domain
# and remap keep command output disconnected from running robots.
setsid \
  ros2 run nav2_controller controller_server --ros-args \
  --params-file "$params" \
  -p use_sim_time:=false \
  -r cmd_vel:=/phase6_demo/disconnected_cmd_vel \
  > /tmp/phase6-nav2-controller.log 2>&1 &
controller_pid=$!
setsid \
  ros2 run nav2_planner planner_server --ros-args \
  --params-file "$params" \
  -p use_sim_time:=false \
  > /tmp/phase6-nav2-planner.log 2>&1 &
planner_pid=$!
cleanup() {
  # ros2 run starts the actual Nav2 executable as a child. Signal each isolated
  # process group so the wrapper and server both exit; the ROS CLI daemon is
  # stopped separately below.
  kill -INT -- "-$controller_pid" 2>/dev/null || true
  kill -INT -- "-$planner_pid" 2>/dev/null || true
  sleep 2
  kill -TERM -- "-$controller_pid" 2>/dev/null || true
  kill -TERM -- "-$planner_pid" 2>/dev/null || true
  wait "$controller_pid" 2>/dev/null || true
  wait "$planner_pid" 2>/dev/null || true
  ros2 daemon stop >/dev/null 2>&1 || true
}
trap cleanup EXIT

wait_for_lifecycle() {
  server="$1"
  pid="$2"
  log_file="/tmp/phase6-nav2-${server%_server}.log"
  ready=false
  service="/$server/change_state"
for attempt in $(seq 1 60); do
  if ! kill -0 "$pid" 2>/dev/null; then
    cat "$log_file"
    exit 1
  fi
  if ros2 service list 2>/dev/null | grep -Fxq "$service"; then
    ready=true
    break
  fi
  sleep 1
done
if [ "$ready" != true ]; then
  cat "$log_file"
  echo "$server lifecycle service did not become ready" >&2
  exit 1
fi
}

wait_for_lifecycle controller_server "$controller_pid"
wait_for_lifecycle planner_server "$planner_pid"
ros2 lifecycle set /controller_server configure
controller_state=$(ros2 lifecycle get /controller_server)
ros2 lifecycle set /planner_server configure
planner_state=$(ros2 lifecycle get /planner_server)
case "$controller_state" in
  *inactive*) ;;
  *) cat /tmp/phase6-nav2-controller.log /tmp/phase6-nav2-planner.log
     echo "unexpected controller lifecycle state: $controller_state" >&2
     exit 1 ;;
esac
case "$planner_state" in
  *inactive*) ;;
  *) cat /tmp/phase6-nav2-controller.log /tmp/phase6-nav2-planner.log
     echo "unexpected planner lifecycle state: $planner_state" >&2
     exit 1 ;;
esac

# Each server owns one costmap; require the actual plugin to load in both while
# both lifecycle nodes remain inactive.
local_loads=$(grep -c 'Using plugin.*semantic_layer' /tmp/phase6-nav2-controller.log || true)
global_loads=$(grep -c 'Using plugin.*semantic_layer' /tmp/phase6-nav2-planner.log || true)
if [ "$local_loads" -lt 1 ] || [ "$global_loads" -lt 1 ]; then
  cat /tmp/phase6-nav2-controller.log /tmp/phase6-nav2-planner.log
  echo "expected semantic_layer in both costmaps; local=$local_loads global=$global_loads" >&2
  exit 1
fi

printf 'PHASE6_NAV2_PLUGIN_PREFLIGHT=PASS\n'
printf 'controller_state=%s\nplanner_state=%s\n' "$controller_state" "$planner_state"
printf 'local_semantic_layer_load_messages=%s\nglobal_semantic_layer_load_messages=%s\n' \
  "$local_loads" "$global_loads"
printf 'startup_overlay_source=PASS\n'
printf 'ros_domain_id=%s\ncommand_output=/phase6_demo/disconnected_cmd_vel\n' "$ROS_DOMAIN_ID"
grep 'Using plugin.*semantic_layer' /tmp/phase6-nav2-controller.log /tmp/phase6-nav2-planner.log
