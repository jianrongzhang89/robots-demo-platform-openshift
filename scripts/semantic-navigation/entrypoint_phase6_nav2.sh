#!/usr/bin/env bash
# Candidate-only Phase 6D Nav2 launch. The simulator is the sole publisher of
# robot-state transforms, so this deliberately skips the canonical entrypoint's
# extra robot_state_publisher and initial-pose seeding. The D1 bridge has no
# Nav2 publishers, so this launch cannot send commands to the simulator.
set -Ee -o pipefail

export HOME="${HOME:-/tmp/phase6-nav2-home}"
export ROS_HOME="${ROS_HOME:-${HOME}/.ros}"
export ROS_LOG_DIR="${ROS_LOG_DIR:-${ROS_HOME}/log}"
mkdir -p "${ROS_LOG_DIR}"

source /opt/ros/jazzy/setup.bash
source /opt/semantic-costmap-ws/install/setup.bash

exec ros2 launch /opt/ros2-demo/nav2/hotel_nav2_federated_launch.py \
  map:="${PHASE6_MAP:-/opt/ros2-demo/maps/hotel_L1.yaml}" \
  params_file:="${PHASE6_PARAMS:-/phase6-config/phase6-demo-nav2-candidate.yaml}"
