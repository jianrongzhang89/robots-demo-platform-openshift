#!/bin/bash
# Quick script to run slam_toolbox in mapping mode to generate .posegraph
# Run this in nav2-tinybot-0 pod to build the map

set -e

ROBOT_NAME=${ROBOT_NAME:-tinyBot_1}

echo "Starting slam_toolbox in MAPPING mode for $ROBOT_NAME"
echo "This will generate a .posegraph file that can be used for localization"
echo ""

. /opt/ros/jazzy/setup.sh
export RMW_IMPLEMENTATION=rmw_cyclonedds_cpp
export ROS_DOMAIN_ID=0

# Run slam_toolbox in async mapping mode
ros2 run slam_toolbox async_slam_toolbox_node \
  --ros-args \
  --remap /scan:=/${ROBOT_NAME}/scan \
  -r __ns:=/${ROBOT_NAME} \
  -p use_sim_time:=true \
  -p odom_frame:=${ROBOT_NAME}/odom \
  -p map_frame:=map \
  -p base_frame:=${ROBOT_NAME}/base_footprint \
  -p scan_topic:=scan \
  -p mode:=mapping \
  -p resolution:=0.05 \
  -p max_laser_range:=12.0 \
  -p minimum_time_interval:=0.5 \
  -p transform_publish_period:=0.02 \
  -p map_update_interval:=2.0 \
  -p minimum_travel_distance:=0.2 \
  -p minimum_travel_heading:=0.2 \
  -p do_loop_closing:=true \
  -p use_map_saver:=true
