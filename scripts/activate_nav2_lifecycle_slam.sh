#!/bin/bash
#
# Activate Nav2 Lifecycle Nodes (SLAM Toolbox version)
#
# This script activates all Nav2 lifecycle-managed nodes after they start.
# Needed because autostart may fail if dependencies aren't ready yet.
#
# Usage: activate_nav2_lifecycle_slam.sh <robot_namespace>
#

set -e

ROBOT_NS=${1:-tinyBot_1}

echo "==========================================="
echo "Activating Nav2 lifecycle nodes for: $ROBOT_NS"
echo "==========================================="

# Source ROS2
. /opt/ros/jazzy/setup.sh

# Wait for nodes to be discovered
echo "Waiting for Nav2 nodes to start (10s)..."
sleep 10

# Function to activate a lifecycle node
activate_node() {
    local node_name=$1
    echo "  → Activating $node_name..."

    # Configure
    if ros2 lifecycle set /$ROBOT_NS/$node_name configure 2>&1 | grep -q "Transitioning successful"; then
        # Activate
        if ros2 lifecycle set /$ROBOT_NS/$node_name activate 2>&1 | grep -q "Transitioning successful"; then
            echo "    ✓ $node_name activated"
            return 0
        fi
    fi
    echo "    ✗ $node_name failed to activate"
    return 1
}

# Activate map_server first (if it exists)
activate_node "map_server" || true

# Activate slam_toolbox localization
activate_node "slam_toolbox" || true

# Activate navigation nodes
activate_node "controller_server" || true
activate_node "planner_server" || true
activate_node "smoother_server" || true
activate_node "behavior_server" || true
activate_node "bt_navigator" || true
activate_node "waypoint_follower" || true
activate_node "velocity_smoother" || true
activate_node "collision_monitor" || true

echo ""
echo "==========================================="
echo "Nav2 lifecycle activation complete!"
echo "==========================================="

# Verify action servers are available
echo ""
echo "Checking action servers..."
timeout 5 ros2 action list | grep -E "navigate_to_pose|navigate_through_poses" || echo "  ⚠ Action servers not visible yet"

echo ""
echo "Nav2 stack ready for $ROBOT_NS"
