#!/bin/bash
# Quick fix for Nav2 bt_navigator activation issue
# Root cause: controller_server crashed during activation due to missing TF frames
# Solution: Restart Nav2 pod to get fresh start, then verify activation

set -e

NAMESPACE="ros2-rmf-hotel"
ROBOT="robot-1"

echo "=== Nav2 Activation Quick Fix ==="
echo ""
echo "This script will:"
echo "1. Restart the Nav2 pod to clear crashed controller_server"
echo "2. Wait for TF frames to be available"
echo "3. Verify lifecycle states"
echo "4. Test navigation goal"
echo ""
read -p "Continue? (y/n) " -n 1 -r
echo
if [[ ! $REPLY =~ ^[Yy]$ ]]; then
    exit 1
fi

echo ""
echo "[1/4] Restarting Nav2 pod..."
oc delete pod -n $NAMESPACE -l app=robot-nav,robot=$ROBOT
echo "Waiting for pod to restart..."
sleep 10

# Wait for pod to be ready
echo "Waiting for pod to be Running..."
while true; do
    STATUS=$(oc get pods -n $NAMESPACE -l app=robot-nav,robot=$ROBOT --no-headers 2>/dev/null | awk '{print $3}' | head -1)
    if [ "$STATUS" = "Running" ]; then
        echo "Pod is Running"
        break
    fi
    echo "  Status: $STATUS"
    sleep 5
done

# Wait for containers to be ready
echo "Waiting for all containers to be ready..."
while true; do
    READY=$(oc get pods -n $NAMESPACE -l app=robot-nav,robot=$ROBOT --no-headers 2>/dev/null | awk '{print $2}' | head -1)
    if [ "$READY" = "6/6" ]; then
        echo "All containers ready: $READY"
        break
    fi
    echo "  Ready: $READY"
    sleep 5
done

echo ""
echo "[2/4] Waiting for TF frames and Nav2 initialization (60s)..."
sleep 60

POD=$(oc get pods -n $NAMESPACE -l app=robot-nav,robot=$ROBOT --no-headers | awk '{print $1}' | head -1)
echo "Using pod: $POD"

echo ""
echo "[3/4] Checking lifecycle states..."

echo "  controller_server:"
oc exec -n $NAMESPACE $POD -c nav2 -- bash -c "
source /usr/lib64/ros-jazzy/setup.bash
export HOME=/tmp
timeout 5 ros2 lifecycle get /controller_server 2>&1 || echo 'NOT FOUND'
"

echo "  planner_server:"
oc exec -n $NAMESPACE $POD -c nav2 -- bash -c "
source /usr/lib64/ros-jazzy/setup.bash
export HOME=/tmp
timeout 5 ros2 lifecycle get /planner_server 2>&1 || echo 'NOT FOUND'
"

echo "  bt_navigator:"
oc exec -n $NAMESPACE $POD -c nav2 -- bash -c "
source /usr/lib64/ros-jazzy/setup.bash
export HOME=/tmp
timeout 5 ros2 lifecycle get /bt_navigator 2>&1 || echo 'NOT FOUND'
"

echo ""
echo "[4/4] Testing navigation goal..."
echo "Publishing test navigation command to /rmf_navigate_cmd..."

oc exec -n $NAMESPACE $POD -c nav2 -- bash -c "
source /usr/lib64/ros-jazzy/setup.bash
export HOME=/tmp
timeout 5 ros2 topic pub --once /rmf_navigate_cmd std_msgs/msg/String \"{data: 'test-goal-$(date +%s) 15.0 20.0 0.0'}\" 2>&1
"

echo ""
echo "Checking nav2_relay logs for test goal..."
sleep 2
oc logs -n $NAMESPACE $POD -c nav2 --since=10s | grep -E "nav_relay.*test-goal" | tail -5

echo ""
echo "=== Quick Fix Complete ==="
echo ""
echo "Next steps:"
echo "1. If bt_navigator is 'active [3]' and goal was accepted → SUCCESS!"
echo "2. If still inactive or goal rejected → See docs/nav2-bt-navigator-activation-issue.md for detailed fix"
echo "3. Try dispatching RMF task: ros2 run rmf_demos_tasks dispatch_patrol -p lobby_center L2_room2 -n 1 --use_sim_time"
