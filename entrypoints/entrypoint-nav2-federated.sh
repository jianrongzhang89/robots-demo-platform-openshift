#!/usr/bin/env bash
set -Eeo pipefail

export HOME=/tmp/ros-home
mkdir -p "${HOME}/.ros" "${HOME}/.config"
export ROS_HOME="${HOME}/.ros"
export ROS_LOG_DIR="${HOME}/.ros/log"
export ROS_DISTRO=jazzy
export ROS_DOMAIN_ID=0
export RMW_IMPLEMENTATION=rmw_cyclonedds_cpp

source /opt/ros/jazzy/setup.bash

echo "[nav2-federated] Starting canonical robot_state_publisher"
URDF=$(cat /usr/lib64/ros-jazzy/share/nav2_minimal_tb3_sim/urdf/turtlebot3_waffle.urdf)
ros2 run robot_state_publisher robot_state_publisher \
  --ros-args -p use_sim_time:=true -p robot_description:="${URDF}" &
RSP_PID=$!

echo "[nav2-federated] Waiting for canonical TF static data"
for _attempt in $(seq 1 30); do
  if timeout 3 ros2 topic echo /tf_static --once 2>/dev/null | grep -q frame_id; then
    break
  fi
  sleep 1
done

echo "[nav2-federated] Launching canonical hotel Nav2 parameters"
ros2 launch /opt/ros2-demo/nav2/hotel_nav2_federated_launch.py \
  map:=/opt/ros2-demo/maps/hotel_L1.yaml \
  params_file:=/opt/ros2-demo/nav2/hotel_nav2_params.yaml &
NAV2_PID=$!

echo "[nav2-federated] Seeding AMCL at (${INITIAL_X:-15.402}, ${INITIAL_Y:--31.594})"
for _attempt in $(seq 1 30); do
  ros2 topic pub /initialpose geometry_msgs/msg/PoseWithCovarianceStamped \
    "{header: {frame_id: map}, pose: {pose: {position: {x: ${INITIAL_X:-15.402}, y: ${INITIAL_Y:--31.594}}, orientation: {w: 1.0}}, covariance: [0.04,0,0,0,0,0, 0,0.04,0,0,0,0, 0,0,0,0,0,0, 0,0,0,0,0,0, 0,0,0,0,0,0, 0,0,0,0,0,0, 0,0,0,0,0,0.02]}}" \
    --qos-reliability reliable --times 1 >/dev/null 2>&1 || true
  if timeout 3 ros2 run tf2_ros tf2_echo map odom 2>/dev/null | grep -q Translation; then
    echo "[nav2-federated] AMCL map transform is available"
    break
  fi
  sleep 2
done

wait "${NAV2_PID}"
