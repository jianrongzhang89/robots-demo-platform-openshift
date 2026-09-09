#!/bin/bash
# Spawn TurtleBot3 robot with diff-drive plugin directly embedded
set -e

ROBOT_NAME="${1:-robot_1}"
SPAWN_X="${2:-10.0}"
SPAWN_Y="${3:-30.0}"
SPAWN_YAW="${4:-0.0}"

export HOME=/tmp/ros-home
source /opt/ros/jazzy/setup.bash
source /opt/rmf_ros2_ws/install/setup.bash
source /opt/rmf_demos_ws/install/setup.bash
export GZ_SIM_RESOURCE_PATH="/opt/gz-models"

# Wait for Gazebo
for i in {1..180}; do
  if timeout 3 gz topic -l &>/dev/null; then
    sleep 10
    break
  fi
  sleep 1
done

# Spawn robot with embedded SDF (plugins must be in spawn request, not in included model)
gz service -s /world/sim_world/create \
  --reqtype gz.msgs.EntityFactory \
  --reptype gz.msgs.Boolean \
  --timeout 15000 \
  --req "sdf: '<?xml version=\"1.0\"?>
<sdf version=\"1.9\">
  <model name=\"${ROBOT_NAME}\">
    <pose>${SPAWN_X} ${SPAWN_Y} 0.01 0 0 ${SPAWN_YAW}</pose>
    <link name=\"base_footprint\"/>
    <link name=\"base_link\">
      <pose relative_to=\"base_footprint\">0 0 0.01 0 0 0</pose>
      <inertial><mass>1.0</mass></inertial>
      <collision name=\"collision\">
        <geometry><box><size>0.3 0.3 0.1</size></box></geometry>
      </collision>
      <visual name=\"visual\">
        <geometry><box><size>0.3 0.3 0.1</size></box></geometry>
      </visual>
    </link>

    <link name=\"wheel_left\">
      <pose relative_to=\"base_link\">0 0.144 0 -1.57 0 0</pose>
      <inertial><mass>0.03</mass></inertial>
      <collision name=\"collision\">
        <geometry><cylinder><radius>0.033</radius><length>0.018</length></cylinder></geometry>
      </collision>
      <visual name=\"visual\">
        <geometry><cylinder><radius>0.033</radius><length>0.018</length></cylinder></geometry>
      </visual>
    </link>

    <link name=\"wheel_right\">
      <pose relative_to=\"base_link\">0 -0.144 0 -1.57 0 0</pose>
      <inertial><mass>0.03</mass></inertial>
      <collision name=\"collision\">
        <geometry><cylinder><radius>0.033</radius><length>0.018</length></cylinder></geometry>
      </collision>
      <visual name=\"visual\">
        <geometry><cylinder><radius>0.033</radius><length>0.018</length></cylinder></geometry>
      </visual>
    </link>

    <joint name=\"base_joint\" type=\"fixed\">
      <parent>base_footprint</parent>
      <child>base_link</child>
    </joint>

    <joint name=\"left_wheel_joint\" type=\"revolute\">
      <parent>base_link</parent>
      <child>wheel_left</child>
      <axis><xyz>0 1 0</xyz></axis>
    </joint>

    <joint name=\"right_wheel_joint\" type=\"revolute\">
      <parent>base_link</parent>
      <child>wheel_right</child>
      <axis><xyz>0 1 0</xyz></axis>
    </joint>

    <plugin filename=\"gz-sim-diff-drive-system\" name=\"gz::sim::systems::DiffDrive\">
      <left_joint>left_wheel_joint</left_joint>
      <right_joint>right_wheel_joint</right_joint>
      <wheel_separation>0.287</wheel_separation>
      <wheel_radius>0.033</wheel_radius>
      <odom_publish_frequency>50</odom_publish_frequency>
      <topic>cmd_vel</topic>
      <odom_topic>odometry</odom_topic>
      <frame_id>odom</frame_id>
      <child_frame_id>base_footprint</child_frame_id>
    </plugin>
  </model>
</sdf>
'" && echo "[spawn] Robot ${ROBOT_NAME} spawned with diff-drive plugin!"
