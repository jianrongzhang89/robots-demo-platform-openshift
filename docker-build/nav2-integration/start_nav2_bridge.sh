#!/bin/bash
# Start ros_gz_bridge with cmd_vel bridging for Nav2 integration
#
# This script is called by the entrypoint to bridge ROS2 topics to Gazebo Transport.
# The DiffDrive plugin in Gazebo Harmonic subscribes to Gazebo Transport topics,
# not ROS2 topics directly, so we need this bridge for Nav2 cmd_vel to work.

export HOME=/tmp
source /opt/ros/jazzy/setup.bash

# Bridge /clock and /robot_2/cmd_vel between ROS2 and Gazebo
# Syntax: topic@ros_type@gz_type
exec ros2 run ros_gz_bridge parameter_bridge \
  /clock@rosgraph_msgs/msg/Clock[gz.msgs.Clock \
  /robot_2/cmd_vel@geometry_msgs/msg/Twist@gz.msgs.Twist \
  /robot_2/odom@nav_msgs/msg/Odometry@gz.msgs.Odometry
