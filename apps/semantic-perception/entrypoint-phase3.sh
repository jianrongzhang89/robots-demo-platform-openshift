#!/usr/bin/env bash
set -eo pipefail
export HOME="${HOME:-/tmp/sam3-home}"
export ROS_LOG_DIR="${ROS_LOG_DIR:-/tmp/ros-log}"
mkdir -p "$HOME" "$ROS_LOG_DIR"
source /opt/ros/jazzy/setup.bash
exec /opt/sam3-venv/bin/python /opt/semantic-perception/sam3_ros_node.py
