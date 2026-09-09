#!/bin/bash
# Spawn TurtleBot3 robot in Gazebo and bridge its topics to ROS2
set -e

ROBOT_NAME="${ROBOT_NAME:-robot_1}"
SPAWN_X="${SPAWN_X:-10.0}"
SPAWN_Y="${SPAWN_Y:-30.0}"
SPAWN_Z="${SPAWN_Z:-0.01}"
SPAWN_YAW="${SPAWN_YAW:-0.0}"

echo "[spawn-bridge] Waiting for Gazebo to be ready..."
for i in {1..60}; do
    if gz topic -l > /dev/null 2>&1; then
        echo "[spawn-bridge] Gazebo is ready!"
        break
    fi
    if [ $i -eq 60 ]; then
        echo "[spawn-bridge] ERROR: Gazebo did not become ready in 60 seconds"
        exit 1
    fi
    sleep 1
done

echo "[spawn-bridge] Spawning ${ROBOT_NAME} at position (${SPAWN_X}, ${SPAWN_Y}, ${SPAWN_Z}) with yaw ${SPAWN_YAW}..."

# Convert yaw to quaternion (simple case: rotation around Z axis)
qw=$(echo "scale=6; c(${SPAWN_YAW}/2)" | bc -l)
qz=$(echo "scale=6; s(${SPAWN_YAW}/2)" | bc -l)

# Spawn the robot using gz service
gz service -s /world/hotel/create \
  --reqtype gz.msgs.EntityFactory \
  --reptype gz.msgs.Boolean \
  --timeout 10000 \
  --req "sdf: '
<sdf version=\"1.9\">
  <model name=\"${ROBOT_NAME}\">
    <pose>${SPAWN_X} ${SPAWN_Y} ${SPAWN_Z} 0 0 ${SPAWN_YAW}</pose>
    <include>
      <uri>model://turtlebot3_waffle</uri>
    </include>
  </model>
</sdf>
'" || {
    echo "[spawn-bridge] ERROR: Failed to spawn robot"
    exit 1
}

echo "[spawn-bridge] Robot ${ROBOT_NAME} spawned successfully!"

# Start ros_gz_bridge to bridge Gazebo topics to ROS2
echo "[spawn-bridge] Starting ros_gz_bridge for ${ROBOT_NAME}..."

source /opt/ros/jazzy/setup.bash

# Bridge configuration:
# Gazebo -> ROS2 (sensors from simulation)
# ROS2 -> Gazebo (commands to simulation)
exec ros_gz_bridge \
  --ros-args \
  -r __ns:=/${ROBOT_NAME} \
  -p config_file:=/dev/stdin <<EOF
- topic_name: "cmd_vel"
  ros_type_name: "geometry_msgs/msg/Twist"
  gz_type_name: "gz.msgs.Twist"
  direction: ROS_TO_GZ

- topic_name: "odom"
  ros_type_name: "nav_msgs/msg/Odometry"
  gz_type_name: "gz.msgs.Odometry"
  direction: GZ_TO_ROS

- topic_name: "scan"
  ros_type_name: "sensor_msgs/msg/LaserScan"
  gz_type_name: "gz.msgs.LaserScan"
  direction: GZ_TO_ROS

- topic_name: "imu"
  ros_type_name: "sensor_msgs/msg/Imu"
  gz_type_name: "gz.msgs.IMU"
  direction: GZ_TO_ROS

- topic_name: "joint_states"
  ros_type_name: "sensor_msgs/msg/JointState"
  gz_type_name: "gz.msgs.Model"
  direction: GZ_TO_ROS
EOF
