#!/usr/bin/env python3
"""
Add TurtleBot3 Waffle robot directly to hotel.world at build time.

DART physics engine in Gazebo Harmonic has a bug where dynamically spawned
models via /world/{name}/create service get all revolute/continuous joints
converted to FIXED (0 DOF). Pre-spawning the robot in the world file works.
"""

import sys
import xml.etree.ElementTree as ET
from pathlib import Path


TURTLEBOT3_MODEL = """
  <model name="robot_1">
    <pose>10 30 0.1 0 0 0</pose>
    <link name="base_footprint">
      <inertial>
        <mass>0.001</mass>
        <inertia><ixx>0.0001</ixx><iyy>0.0001</iyy><izz>0.0001</izz></inertia>
      </inertial>
    </link>
    <link name="base_link">
      <inertial>
        <mass>1.37</mass>
        <inertia><ixx>0.0087</ixx><iyy>0.0086</iyy><izz>0.0146</izz></inertia>
      </inertial>
      <collision name="base_collision">
        <pose>-0.032 0 0.07 0 0 0</pose>
        <geometry><box><size>0.28 0.31 0.14</size></box></geometry>
      </collision>
      <visual name="base_visual">
        <pose>-0.032 0 0.07 0 0 0</pose>
        <geometry><box><size>0.28 0.31 0.14</size></box></geometry>
        <material><ambient>0.0 0.0 1.0 1</ambient><diffuse>0.0 0.0 1.0 1</diffuse></material>
      </visual>
    </link>
    <link name="wheel_left_link">
      <pose>0 0.144 0.023 -1.57 0 0</pose>
      <inertial>
        <mass>0.028</mass>
        <inertia><ixx>1.1e-5</ixx><iyy>1.1e-5</iyy><izz>2.1e-5</izz></inertia>
      </inertial>
      <collision name="left_wheel_collision">
        <geometry><cylinder><radius>0.033</radius><length>0.018</length></cylinder></geometry>
        <surface>
          <friction>
            <ode><mu>100000</mu><mu2>100000</mu2></ode>
            <bullet><friction>100000</friction><friction2>100000</friction2></bullet>
          </friction>
        </surface>
      </collision>
      <visual name="left_wheel_visual">
        <geometry><cylinder><radius>0.033</radius><length>0.018</length></cylinder></geometry>
      </visual>
    </link>
    <link name="wheel_right_link">
      <pose>0 -0.144 0.023 -1.57 0 0</pose>
      <inertial>
        <mass>0.028</mass>
        <inertia><ixx>1.1e-5</ixx><iyy>1.1e-5</iyy><izz>2.1e-5</izz></inertia>
      </inertial>
      <collision name="right_wheel_collision">
        <geometry><cylinder><radius>0.033</radius><length>0.018</length></cylinder></geometry>
        <surface>
          <friction>
            <ode><mu>100000</mu><mu2>100000</mu2></ode>
            <bullet><friction>100000</friction><friction2>100000</friction2></bullet>
          </friction>
        </surface>
      </collision>
      <visual name="right_wheel_visual">
        <geometry><cylinder><radius>0.033</radius><length>0.018</length></cylinder></geometry>
      </visual>
    </link>
    <link name="base_scan">
      <pose>-0.032 0 0.172 0 0 0</pose>
      <inertial>
        <mass>0.114</mass>
        <inertia><ixx>0.001</ixx><iyy>0.001</iyy><izz>0.001</izz></inertia>
      </inertial>
      <collision name="lidar_collision">
        <geometry><cylinder><radius>0.0508</radius><length>0.055</length></cylinder></geometry>
      </collision>
      <visual name="lidar_visual">
        <geometry><cylinder><radius>0.0508</radius><length>0.055</length></cylinder></geometry>
      </visual>
      <sensor name="lidar" type="gpu_lidar">
        <pose>0 0 0.01 0 0 0</pose>
        <topic>scan</topic>
        <update_rate>5</update_rate>
        <lidar>
          <scan>
            <horizontal>
              <samples>360</samples>
              <resolution>1.0</resolution>
              <min_angle>0.0</min_angle>
              <max_angle>6.28</max_angle>
            </horizontal>
          </scan>
          <range>
            <min>0.12</min>
            <max>3.5</max>
            <resolution>0.015</resolution>
          </range>
        </lidar>
        <visualize>true</visualize>
        <frame_id>base_scan</frame_id>
      </sensor>
    </link>
    <link name="imu_link">
      <pose>0 0 0.068 0 0 0</pose>
      <inertial>
        <mass>0.001</mass>
        <inertia><ixx>0.0001</ixx><iyy>0.0001</iyy><izz>0.0001</izz></inertia>
      </inertial>
      <sensor name="tb3_imu" type="imu">
        <always_on>true</always_on>
        <update_rate>200</update_rate>
        <imu>
          <angular_velocity>
            <x><noise type="gaussian"><mean>0</mean><stddev>0.009</stddev></noise></x>
            <y><noise type="gaussian"><mean>0</mean><stddev>0.009</stddev></noise></y>
            <z><noise type="gaussian"><mean>0</mean><stddev>0.009</stddev></noise></z>
          </angular_velocity>
          <linear_acceleration>
            <x><noise type="gaussian"><mean>0</mean><stddev>0.017</stddev></noise></x>
            <y><noise type="gaussian"><mean>0</mean><stddev>0.017</stddev></noise></y>
            <z><noise type="gaussian"><mean>0</mean><stddev>0.017</stddev></noise></z>
          </linear_acceleration>
        </imu>
      </sensor>
    </link>
    <joint name="base_joint" type="fixed">
      <parent>base_footprint</parent>
      <child>base_link</child>
    </joint>
    <joint name="left_wheel_joint" type="continuous">
      <parent>base_link</parent>
      <child>wheel_left_link</child>
      <axis><xyz>0 0 1</xyz></axis>
    </joint>
    <joint name="right_wheel_joint" type="continuous">
      <parent>base_link</parent>
      <child>wheel_right_link</child>
      <axis><xyz>0 0 1</xyz></axis>
    </joint>
    <joint name="lidar_joint" type="fixed">
      <parent>base_link</parent>
      <child>base_scan</child>
    </joint>
    <joint name="imu_joint" type="fixed">
      <parent>base_link</parent>
      <child>imu_link</child>
    </joint>
    <plugin filename="gz-sim-diff-drive-system" name="gz::sim::systems::DiffDrive">
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
"""


def main():
    world_file = Path('/opt/rmf_demos_ws/install/share/rmf_demos_maps/maps/hotel/hotel.world')

    if not world_file.exists():
        print(f"ERROR: {world_file} not found")
        sys.exit(1)

    # Parse world file
    tree = ET.parse(world_file)
    root = tree.getroot()

    world = root.find('.//world')
    if world is None:
        print("ERROR: No <world> element found")
        sys.exit(1)

    # Check if robot_1 already exists
    if world.find(".//model[@name='robot_1']") is not None:
        print("INFO: robot_1 already exists in world file")
        sys.exit(0)

    # Parse robot model XML
    robot_elem = ET.fromstring(TURTLEBOT3_MODEL)

    # Insert robot before first <include> or at end
    first_include = world.find('include')
    if first_include is not None:
        # Insert before first include
        insert_index = list(world).index(first_include)
        world.insert(insert_index, robot_elem)
    else:
        # Append at end
        world.append(robot_elem)

    # Write back
    tree.write(world_file, encoding='utf-8', xml_declaration=True)

    print(f"SUCCESS: Added robot_1 to {world_file}")
    print("  TurtleBot3 Waffle with continuous wheel joints")
    print("  Spawned at (10, 30) in lobby area")
    sys.exit(0)


if __name__ == '__main__':
    main()
