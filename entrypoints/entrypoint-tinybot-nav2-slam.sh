#!/bin/sh
#
# Entrypoint for TinyBot Nav2 pod with SLAM Toolbox localization
#
# This pod runs:
#   - Nav2 stack with slam_toolbox localization
#   - Pose relay for Free Fleet compatibility
#   - Free Fleet Client (RMF integration)
#
# Robot is spawned in Gazebo pod and controlled via Zenoh-federated cmd_vel.
# Free Fleet Client receives waypoint goals from RMF and executes via Nav2.
#
# Environment Variables (set by Kubernetes deployment):
#   ROBOT_NAME: Robot namespace (e.g., tinyBot_1)
#   ROBOT_X: Initial X position
#   ROBOT_Y: Initial Y position
#   ROBOT_YAW: Initial orientation (radians)
#   MAP_LEVEL: Hotel level (L1, L2, or L3)
#   RMW_IMPLEMENTATION: ROS middleware (should be rmw_cyclonedds_cpp)
#

set -e

echo "=================================================="
echo "TinyBot Nav2 Pod - SLAM Toolbox Localization"
echo "=================================================="
echo ""

# Validate required environment variables
if [ -z "$ROBOT_NAME" ]; then
    echo "ERROR: ROBOT_NAME environment variable not set"
    exit 1
fi

echo "Robot Configuration:"
echo "  Name: $ROBOT_NAME"
echo "  Initial Position: (${ROBOT_X:-23.5}, ${ROBOT_Y:--27.4})"
echo "  Initial Yaw: ${ROBOT_YAW:-0.0}"
echo "  Map Level: ${MAP_LEVEL:-L1}"
echo "  RMW: ${RMW_IMPLEMENTATION:-rmw_cyclonedds_cpp}"
echo ""

# Set defaults if not provided
export ROBOT_X=${ROBOT_X:-23.5}
export ROBOT_Y=${ROBOT_Y:--27.4}
export ROBOT_YAW=${ROBOT_YAW:-0.0}
export MAP_LEVEL=${MAP_LEVEL:-L1}
export RMW_IMPLEMENTATION=${RMW_IMPLEMENTATION:-rmw_cyclonedds_cpp}

# Source ROS2 environment
. /opt/ros/jazzy/setup.sh

# Source Free Fleet workspace
if [ -f /opt/free_fleet_ws/install/setup.sh ]; then
  . /opt/free_fleet_ws/install/setup.sh
fi

# Create log directory
mkdir -p /tmp/ros_logs
export ROS_LOG_DIR=/tmp/ros_logs

# Substitute ROBOT_NAME in Nav2 params
echo "Preparing Nav2 parameters..."
mkdir -p /tmp/nav2_config
envsubst < /opt/nav2_config/tinybot_nav2_params.yaml > /tmp/nav2_config/tinybot_nav2_params_${ROBOT_NAME}.yaml

echo ""
echo "Starting Nav2 stack with slam_toolbox localization..."
echo "  Launch file: /opt/nav2_launch/tinybot_nav2_launch.py"
echo "  Params file: /tmp/nav2_config/tinybot_nav2_params_${ROBOT_NAME}.yaml"
echo "  SLAM map: /opt/slam_maps/hotel_${MAP_LEVEL}_map.posegraph"
echo "  Namespace: $ROBOT_NAME"

# Launch Nav2 stack in background
ros2 launch /opt/nav2_launch/tinybot_nav2_launch.py > /tmp/ros_logs/nav2_${ROBOT_NAME}.log 2>&1 &
NAV2_PID=$!

echo "  PID: $NAV2_PID"
echo ""

# Wait for Nav2 to initialize
echo "Waiting for Nav2 to initialize (30s)..."
sleep 30

# Activate lifecycle nodes
echo ""
echo "Activating Nav2 lifecycle nodes..."
if [ -f /opt/nav2_scripts/activate_nav2_lifecycle_slam.sh ]; then
    /opt/nav2_scripts/activate_nav2_lifecycle_slam.sh $ROBOT_NAME &
    LIFECYCLE_PID=$!
    echo "  Lifecycle activation PID: $LIFECYCLE_PID"
else
    echo "  WARNING: Lifecycle activation script not found"
fi

echo ""
echo "Publishing TF transforms for robot..."

# Odometry to TF publisher (odom → base_footprint from /odom topic)
bash -c ". /opt/ros/jazzy/setup.sh && export RMW_IMPLEMENTATION=rmw_cyclonedds_cpp && export ROS_DOMAIN_ID=0 && python3 /opt/nav2_scripts/odom_to_tf.py $ROBOT_NAME" > /tmp/ros_logs/odom_to_tf_${ROBOT_NAME}.log 2>&1 &
ODOM_TF_PID=$!
echo "  Odom→base_footprint TF publisher PID: $ODOM_TF_PID"

# base_footprint → lidar_link (from tinyBot model: lidar is at 0.05m forward, 0.28m up)
# Using dynamic_tf.py to publish with current simulation timestamps (not timestamp=0)
# This fixes slam_toolbox message_filter TF synchronization issue
bash -c ". /opt/ros/jazzy/setup.sh && export RMW_IMPLEMENTATION=rmw_cyclonedds_cpp && export ROS_DOMAIN_ID=0 && python3 /opt/nav2_scripts/dynamic_tf.py $ROBOT_NAME ${ROBOT_NAME}/base_footprint ${ROBOT_NAME}/lidar_link 0.05 0 0.28 0 0 0" > /tmp/ros_logs/tf_base_lidar_${ROBOT_NAME}.log 2>&1 &
TF_BASE_LIDAR_PID=$!
echo "  TF base_footprint→lidar_link publisher PID: $TF_BASE_LIDAR_PID"

# lidar_link → lidar_link/lidar (identity transform for frame ID compatibility)
# Using dynamic_tf.py to publish with current simulation timestamps (not timestamp=0)
bash -c ". /opt/ros/jazzy/setup.sh && export RMW_IMPLEMENTATION=rmw_cyclonedds_cpp && export ROS_DOMAIN_ID=0 && python3 /opt/nav2_scripts/dynamic_tf.py $ROBOT_NAME ${ROBOT_NAME}/lidar_link ${ROBOT_NAME}/lidar_link/lidar 0 0 0 0 0 0" > /tmp/ros_logs/tf_lidar_sensor_${ROBOT_NAME}.log 2>&1 &
TF_LIDAR_SENSOR_PID=$!
echo "  TF lidar_link→lidar_link/lidar publisher PID: $TF_LIDAR_SENSOR_PID"

# Note: slam_toolbox publishes map→odom transform dynamically, so no static TF needed

echo ""
echo "Launching pose relay for Free Fleet compatibility..."
bash -c ". /opt/ros/jazzy/setup.sh && export RMW_IMPLEMENTATION=rmw_cyclonedds_cpp && export ROS_DOMAIN_ID=0 && python3 /opt/nav2_scripts/pose_relay.py $ROBOT_NAME" > /tmp/ros_logs/pose_relay_${ROBOT_NAME}.log 2>&1 &
POSE_RELAY_PID=$!
echo "  Pose relay (/pose → /amcl_pose) PID: $POSE_RELAY_PID"

echo ""
echo "Launching robot_state publisher for Free Fleet discovery..."
bash -c ". /opt/ros/jazzy/setup.sh && export RMW_IMPLEMENTATION=rmw_cyclonedds_cpp && export ROS_DOMAIN_ID=0 && python3 /opt/nav2_scripts/robot_state_publisher.py $ROBOT_NAME" > /tmp/ros_logs/robot_state_${ROBOT_NAME}.log 2>&1 &
ROBOT_STATE_PID=$!
echo "  Robot state publisher PID: $ROBOT_STATE_PID"

echo ""
echo "=================================================="
echo "Nav2 stack started successfully!"
echo ""
echo "Components running:"
echo "  - Nav2 stack (slam_toolbox localization): PID $NAV2_PID"
echo "  - Pose relay: PID $POSE_RELAY_PID"
echo "  - Robot state publisher: PID $ROBOT_STATE_PID"
echo ""
echo "Robot: $ROBOT_NAME"
echo "Integration: Free Fleet v2.0 via Zenoh"
echo "Fleet adapter will connect via Zenoh bridge"
echo ""
echo "Namespaced topics (Zenoh-bridged):"
echo "  - /${ROBOT_NAME}/odom"
echo "  - /${ROBOT_NAME}/scan"
echo "  - /${ROBOT_NAME}/cmd_vel"
echo "  - /${ROBOT_NAME}/pose (slam_toolbox)"
echo "  - /${ROBOT_NAME}/amcl_pose (relayed for Free Fleet)"
echo "  - /${ROBOT_NAME}/robot_state (for Free Fleet discovery)"
echo "  - /${ROBOT_NAME}/battery_state"
echo "=================================================="

# Monitor Nav2 process
while true; do
    if ! kill -0 $NAV2_PID 2>/dev/null; then
        echo "ERROR: Nav2 stack exited unexpectedly!"
        echo "Check logs: /tmp/ros_logs/nav2_${ROBOT_NAME}.log"
        exit 1
    fi

    sleep 5
done
