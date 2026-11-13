#!/usr/bin/env bash
set -Eeo pipefail

export HOME=/tmp/phase8-rmf-home
export ROS_HOME="$HOME/.ros"
export ROS_LOG_DIR="$ROS_HOME/log"
mkdir -p "$ROS_LOG_DIR"
source /opt/ros/jazzy/setup.bash
source /opt/rmf_demos_ws/install/setup.bash

ros2 run rmf_traffic_ros2 rmf_traffic_schedule --ros-args \
  -p use_sim_time:=true &
schedule_pid=$!
ros2 run rmf_task_ros2 rmf_task_dispatcher --ros-args \
  -p use_sim_time:=true \
  -p bidding_time_window:=2.0 \
  -p use_unique_hex_string_with_task_id:=true &
dispatcher_pid=$!
trap 'kill "$dispatcher_pid" "$schedule_pid" 2>/dev/null || true; wait || true' TERM INT EXIT

for _ in $(seq 1 90); do
  if ! kill -0 "$schedule_pid" 2>/dev/null || ! kill -0 "$dispatcher_pid" 2>/dev/null; then
    echo "RMF schedule or task dispatcher exited during startup" >&2
    exit 1
  fi
  if ros2 node list 2>/dev/null | grep -q rmf_traffic_schedule_node && \
     ros2 topic list 2>/dev/null | grep -qx /task_api_requests; then
    echo "Phase 8 RMF schedule and task API are ready"
    wait -n "$schedule_pid" "$dispatcher_pid"
    exit 1
  fi
  sleep 1
done
echo "Timed out waiting for Phase 8 RMF task API" >&2
exit 1
