#!/bin/bash
# Start complete Nav2 stack for robot_2
# Starts all Nav2 nodes with proper lifecycle management

export HOME=/tmp
source /opt/ros/jazzy/setup.bash

echo "[nav2-stack] Starting Nav2 nodes for robot_2..."

# Generate map if it doesn't exist
if [ ! -f /opt/nav2_maps/hotel_map.yaml ]; then
    echo "[nav2-stack] Generating hotel map..."
    /opt/nav2_scripts/generate_hotel_map.sh
fi

# Start controller server
echo "[nav2-stack] Starting controller_server..."
ros2 run nav2_controller controller_server \
    --ros-args --params-file /opt/nav2_config/nav2_params_robot2.yaml \
    -r __node:=controller_server > /tmp/nav2_controller.log 2>&1 &
CONTROLLER_PID=$!
sleep 3

# Start planner server
echo "[nav2-stack] Starting planner_server..."
ros2 run nav2_planner planner_server \
    --ros-args --params-file /opt/nav2_config/nav2_params_robot2.yaml \
    -r __node:=planner_server > /tmp/nav2_planner.log 2>&1 &
PLANNER_PID=$!
sleep 3

# Start map server
echo "[nav2-stack] Starting map_server..."
ros2 run nav2_map_server map_server \
    --ros-args --params-file /opt/nav2_config/nav2_params_robot2.yaml \
    -r __node:=map_server > /tmp/nav2_map.log 2>&1 &
MAP_PID=$!
sleep 3

# Start AMCL
echo "[nav2-stack] Starting amcl..."
ros2 run nav2_amcl amcl \
    --ros-args --params-file /opt/nav2_config/nav2_params_robot2.yaml \
    -r __node:=amcl > /tmp/nav2_amcl.log 2>&1 &
AMCL_PID=$!
sleep 3

# Start behavior server
echo "[nav2-stack] Starting behavior_server..."
ros2 run nav2_behaviors behavior_server \
    --ros-args --params-file /opt/nav2_config/nav2_params_robot2.yaml \
    -r __node:=behavior_server > /tmp/nav2_behavior.log 2>&1 &
BEHAVIOR_PID=$!
sleep 3

echo "[nav2-stack] All Nav2 nodes started."
echo "  Controller: PID $CONTROLLER_PID"
echo "  Planner: PID $PLANNER_PID"
echo "  Map: PID $MAP_PID"
echo "  AMCL: PID $AMCL_PID"
echo "  Behavior: PID $BEHAVIOR_PID"

# Activate lifecycle nodes
sleep 5
echo "[nav2-stack] Activating lifecycle nodes..."

# Configure and activate each node
for node in controller_server planner_server map_server amcl behavior_server; do
    echo "  Configuring $node..."
    ros2 service call /$node/change_state lifecycle_msgs/srv/ChangeState \
        "{transition: {id: 1}}" > /dev/null 2>&1
    sleep 1

    echo "  Activating $node..."
    ros2 service call /$node/change_state lifecycle_msgs/srv/ChangeState \
        "{transition: {id: 3}}" > /dev/null 2>&1
    sleep 1
done

echo "[nav2-stack] Nav2 stack activated and ready!"
echo ""
echo "Logs available at:"
echo "  /tmp/nav2_controller.log"
echo "  /tmp/nav2_planner.log"
echo "  /tmp/nav2_map.log"
echo "  /tmp/nav2_amcl.log"
echo "  /tmp/nav2_behavior.log"
