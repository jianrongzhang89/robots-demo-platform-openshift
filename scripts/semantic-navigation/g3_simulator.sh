#!/usr/bin/env bash
# Private headless sensor fixture; no navigation, planner, RMF or command producer.
set -Ee -o pipefail
export HOME=/tmp/ros-home ROS_LOG_DIR=/tmp/ros-home/.ros/log
mkdir -p "$ROS_LOG_DIR" /tmp/g3
source /opt/ros/jazzy/setup.bash
source /opt/rmf_demos_ws/install/setup.bash
export LD_LIBRARY_PATH="/opt/semantic-navigation/capture-lib:${LD_LIBRARY_PATH:-}"
export GZ_SIM_RESOURCE_PATH="/opt/ros2-demo/hotel-assets/models:/opt/ros2-demo/hotel-assets:/opt/rmf_demos_ws/install/share/rmf_demos_assets/models:${GZ_SIM_RESOURCE_PATH:-}"
export GZ_SIM_SYSTEM_PLUGIN_PATH="/opt/ros/jazzy/opt/gz_sim_vendor/lib/gz-sim-8/plugins:${GZ_SIM_SYSTEM_PLUGIN_PATH:-}"
cp /opt/ros2-demo/hotel-assets/hotel.world /tmp/g3/hotel.world
python3 /opt/semantic-navigation/install_phase1_camera.py /tmp/g3/hotel.world --phase2-targets
pids=()
cleanup() { trap - TERM INT EXIT; for pid in "${pids[@]}"; do kill "$pid" 2>/dev/null || true; done; wait || true; }
trap cleanup TERM INT EXIT
gz sim --force-version 8 --headless-rendering -r -s -v 2 /tmp/g3/hotel.world > /tmp/g3/gz-server.log 2>&1 & pids+=("$!")
ros2 run robot_state_publisher robot_state_publisher --ros-args -p use_sim_time:=true -p robot_description:="$(cat /opt/ros2-demo/robot/turtlebot3_waffle.urdf)" -r /tf:=/robot_1/tf -r /tf_static:=/robot_1/tf_static > /tmp/g3/robot-state.log 2>&1 & pids+=("$!")
ros2 run ros_gz_bridge parameter_bridge '/clock@rosgraph_msgs/msg/Clock[gz.msgs.Clock' '/robot_1/cmd_vel@geometry_msgs/msg/Twist]gz.msgs.Twist' '/robot_1/odom@nav_msgs/msg/Odometry[gz.msgs.Odometry' '/scan@sensor_msgs/msg/LaserScan[gz.msgs.LaserScan' --ros-args -r /scan:=/robot_1/scan > /tmp/g3/bridge.log 2>&1 & pids+=("$!")
ros2 launch ros_gz_bridge ros_gz_bridge.launch.py bridge_name:=semantic_camera_bridge config_file:=/opt/ros2-demo/config/semantic-camera-bridge.yaml > /tmp/g3/camera-bridge.log 2>&1 & pids+=("$!")
python3 /g3-config/g3_odom_tf.py > /tmp/g3/odom-tf.log 2>&1 & pids+=("$!")
wait "${pids[0]}"
