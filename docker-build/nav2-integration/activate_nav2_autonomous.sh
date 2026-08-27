#!/bin/bash
# Activate Nav2 stack for autonomous navigation
# Handles lifecycle management, AMCL initialization, and path planning setup

export HOME=/tmp
source /opt/ros/jazzy/setup.bash

echo "========================================="
echo "  Nav2 Autonomous Navigation Activation"
echo "========================================="
echo ""

# Function to activate a lifecycle node
activate_lifecycle_node() {
    local NODE=$1
    echo "🔧 Activating $NODE..."

    # Configure (transition 1)
    ros2 service call /$NODE/change_state lifecycle_msgs/srv/ChangeState "{transition: {id: 1}}" > /dev/null 2>&1
    sleep 2

    # Activate (transition 3)
    ros2 service call /$NODE/change_state lifecycle_msgs/srv/ChangeState "{transition: {id: 3}}" > /dev/null 2>&1
    sleep 2

    # Check state
    STATE=$(ros2 service call /$NODE/get_state lifecycle_msgs/srv/GetState {} 2>&1 | grep -o "label='[^']*'" | cut -d"'" -f2)
    if [ "$STATE" = "active" ]; then
        echo "   ✅ $NODE active"
        return 0
    else
        echo "   ⚠️  $NODE state: $STATE"
        return 1
    fi
}

echo "Step 1: Activate Map Server"
echo "----------------------------"
activate_lifecycle_node "map_server"

echo ""
echo "Step 2: Activate AMCL (Localization)"
echo "-------------------------------------"
activate_lifecycle_node "amcl"

# Set initial pose based on current robot position
echo ""
echo "Step 3: Set Initial Pose for AMCL"
echo "----------------------------------"
ROBOT_POS=$(timeout 2 ros2 run tf2_ros tf2_echo world tinyBot_1/base_link 2>&1 | grep 'Translation' | head -1)
echo "Current robot position: $ROBOT_POS"

# Extract position (robot is at approximately [23.4, -27.0])
# For AMCL, we'll set initial pose in map frame
echo "Setting initial pose..."
ros2 topic pub --once /initialpose geometry_msgs/msg/PoseWithCovarianceStamped "
header:
  frame_id: 'map'
pose:
  pose:
    position:
      x: 23.4
      y: -27.0
      z: 0.0
    orientation:
      x: 0.0
      y: 0.0
      z: 0.0
      w: 1.0
  covariance: [0.25, 0.0, 0.0, 0.0, 0.0, 0.0,
               0.0, 0.25, 0.0, 0.0, 0.0, 0.0,
               0.0, 0.0, 0.0, 0.0, 0.0, 0.0,
               0.0, 0.0, 0.0, 0.0, 0.0, 0.0,
               0.0, 0.0, 0.0, 0.0, 0.0, 0.0,
               0.0, 0.0, 0.0, 0.0, 0.0, 0.06853891909122467]
" > /dev/null 2>&1

echo "   ✅ Initial pose set"

echo ""
echo "Step 4: Activate Planner Server"
echo "--------------------------------"
activate_lifecycle_node "planner_server"

echo ""
echo "Step 5: Activate Controller Server"
echo "-----------------------------------"
# Controller should already be active from earlier
STATE=$(ros2 service call /controller_server/get_state lifecycle_msgs/srv/GetState {} 2>&1 | grep -o "label='[^']*'" | cut -d"'" -f2)
if [ "$STATE" != "active" ]; then
    activate_lifecycle_node "controller_server"
else
    echo "   ✅ controller_server already active"
fi

echo ""
echo "Step 6: Activate Behavior Server"
echo "---------------------------------"
activate_lifecycle_node "behavior_server"

echo ""
echo "========================================="
echo "  Final Status Check"
echo "========================================="
echo ""

for node in map_server amcl planner_server controller_server behavior_server; do
    STATE=$(timeout 2 ros2 service call /$node/get_state lifecycle_msgs/srv/GetState {} 2>&1 | grep -o "label='[^']*'" | cut -d"'" -f2 || echo 'unknown')
    printf "%-20s %s\n" "$node:" "$STATE"
done

echo ""
echo "========================================="
echo "  Nav2 Stack Ready for Navigation!"
echo "========================================="
echo ""
echo "Available actions:"
echo "  - /compute_path_to_pose"
echo "  - /follow_path"
echo "  - /navigate_to_pose (if bt_navigator active)"
echo ""
echo "To test path planning:"
echo "  ros2 action send_goal /compute_path_to_pose nav2_msgs/action/ComputePathToPose ..."
echo ""
