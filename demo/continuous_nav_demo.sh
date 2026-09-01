#!/bin/bash
# Continuous navigation demo - sends navigation goals in a loop
# This keeps robots moving for demonstration purposes

NAMESPACE="ros2-rmf-hotel-nav2-federated"

echo "========================================="
echo "  Continuous Navigation Demo"
echo "========================================="
echo ""
echo "This will send navigation goals to robots in a loop."
echo "Press Ctrl+C to stop."
echo ""
echo "Robots will navigate between waypoints:"
echo "  - Northwest: (15, -25)"
echo "  - Northeast: (25, -25)"
echo "  - Southwest: (15, -35)"
echo "  - Southeast: (25, -35)"
echo "  - Center: (20, -30)"
echo ""
echo "========================================="
echo ""

# Waypoints (x, y)
WAYPOINTS=(
    "15 -25"   # Northwest
    "25 -25"   # Northeast
    "15 -35"   # Southwest
    "25 -35"   # Southeast
    "20 -30"   # Center
)

# Copy the nav goal script to all pods
for i in 0 1 2; do
    POD="nav2-tinybot-${i}"
    echo "Setting up ${POD}..."
    oc cp demo/send_nav_goal.py ${NAMESPACE}/${POD}:/tmp/send_nav_goal.py -c nav2 2>&1 | grep -v "Defaulting"
done

echo ""
echo "Starting continuous navigation..."
echo ""

counter=0
while true; do
    # Each robot gets a different waypoint
    for robot in 1 2 3; do
        # Cycle through waypoints
        idx=$(( (counter + robot - 1) % ${#WAYPOINTS[@]} ))
        waypoint="${WAYPOINTS[$idx]}"
        x=$(echo $waypoint | awk '{print $1}')
        y=$(echo $waypoint | awk '{print $2}')

        pod_idx=$((robot - 1))
        POD="nav2-tinybot-${pod_idx}"

        echo "[$(date +%H:%M:%S)] tinyBot_${robot} → ($x, $y)"

        oc exec -n ${NAMESPACE} ${POD} -c nav2 -- bash -c "
        . /opt/ros/jazzy/setup.sh
        export ROS_DOMAIN_ID=0
        export HOME=/tmp
        timeout 2 python3 /tmp/send_nav_goal.py tinyBot_${robot} ${x} ${y} 2>&1 | grep 'accepted'
        " 2>&1 | grep -v "Defaulting" &
    done

    # Wait for all robots to receive goals
    wait

    echo ""
    echo "Waiting 30 seconds for robots to navigate..."
    sleep 30

    counter=$((counter + 1))
    echo ""
    echo "--- Round $counter complete ---"
    echo ""
done
