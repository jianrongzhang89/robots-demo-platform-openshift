#!/bin/bash
# Nav2-integrated entrypoint wrapper
# Starts ros_gz_bridge with cmd_vel bridging, then calls the original hotel entrypoint

# Start ros_gz_bridge in the background for Nav2 cmd_vel support
echo "[nav2-entrypoint] Starting ros_gz_bridge with cmd_vel bridging..."
/opt/nav2_scripts/start_nav2_bridge.sh > /tmp/nav2_bridge.log 2>&1 &
BRIDGE_PID=$!
echo "[nav2-entrypoint] Bridge started with PID $BRIDGE_PID"

# Give the bridge a moment to initialize
sleep 2

# Call the original hotel entrypoint
echo "[nav2-entrypoint] Starting hotel demo..."
exec /entrypoint-hotel.sh
