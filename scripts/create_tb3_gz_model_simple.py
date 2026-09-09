#!/usr/bin/env python3
import os, sys

def create_model(output_dir):
    os.makedirs(output_dir, exist_ok=True)
    
    # Model config
    with open(os.path.join(output_dir, 'model.config'), 'w') as f:
        f.write("""<?xml version="1.0"?>
<model>
  <name>TurtleBot3 Waffle</name>
  <version>1.0</version>
  <sdf version="1.9">model.sdf</sdf>
  <description>TurtleBot3 Waffle with basic geometry</description>
</model>
""")
    
    # Model SDF
    with open(os.path.join(output_dir, 'model.sdf'), 'w') as f:
        f.write("""<?xml version="1.0" ?>
<sdf version="1.9">
  <model name="turtlebot3_waffle">
    <pose>0 0 0.01 0 0 0</pose>
    <link name="base_footprint">
      <inertial>
        <mass>0.001</mass>
        <inertia><ixx>0.0001</ixx><iyy>0.0001</iyy><izz>0.0001</izz><ixy>0</ixy><ixz>0</ixz><iyz>0</iyz></inertia>
      </inertial>
    </link>
    <link name="base_link">
      <inertial>
        <mass>1.37</mass>
        <inertia><ixx>0.0087</ixx><iyy>0.0086</iyy><izz>0.0146</izz><ixy>0</ixy><ixz>0</ixz><iyz>0</iyz></inertia>
      </inertial>
      <collision name="base_collision">
        <pose>-0.032 0 0.07 0 0 0</pose>
        <geometry><box><size>0.28 0.31 0.14</size></box></geometry>
      </collision>
      <visual name="base_visual">
        <pose>-0.032 0 0.07 0 0 0</pose>
        <geometry><box><size>0.28 0.31 0.14</size></box></geometry>
      </visual>
    </link>
    <link name="wheel_left_link">
      <pose>0 0.144 0.023 -1.57 0 0</pose>
      <inertial>
        <mass>0.028</mass>
        <inertia><ixx>1.1e-5</ixx><iyy>1.1e-5</iyy><izz>2.1e-5</izz><ixy>0</ixy><ixz>0</ixz><iyz>0</iyz></inertia>
      </inertial>
      <collision name="left_wheel_collision">
        <geometry><cylinder><radius>0.033</radius><length>0.018</length></cylinder></geometry>
        <surface><friction><ode><mu>100000</mu><mu2>100000</mu2></ode></friction></surface>
      </collision>
      <visual name="left_wheel_visual">
        <geometry><cylinder><radius>0.033</radius><length>0.018</length></cylinder></geometry>
      </visual>
    </link>
    <link name="wheel_right_link">
      <pose>0 -0.144 0.023 -1.57 0 0</pose>
      <inertial>
        <mass>0.028</mass>
        <inertia><ixx>1.1e-5</ixx><iyy>1.1e-5</iyy><izz>2.1e-5</izz><ixy>0</ixy><ixz>0</ixz><iyz>0</iyz></inertia>
      </inertial>
      <collision name="right_wheel_collision">
        <geometry><cylinder><radius>0.033</radius><length>0.018</length></cylinder></geometry>
        <surface><friction><ode><mu>100000</mu><mu2>100000</mu2></ode></friction></surface>
      </collision>
      <visual name="right_wheel_visual">
        <geometry><cylinder><radius>0.033</radius><length>0.018</length></cylinder></geometry>
      </visual>
    </link>
    <link name="lidar_link">
      <pose>-0.064 0 0.172 0 0 0</pose>
      <inertial>
        <mass>0.125</mass>
        <inertia><ixx>0.001</ixx><iyy>0.001</iyy><izz>0.001</izz><ixy>0</ixy><ixz>0</ixz><iyz>0</iyz></inertia>
      </inertial>
      <sensor name="lidar" type="gpu_lidar">
        <topic>/scan</topic>
        <update_rate>5</update_rate>
        <always_on>1</always_on>
        <visualize>true</visualize>
        <lidar>
          <scan><horizontal><samples>360</samples><resolution>1</resolution><min_angle>0</min_angle><max_angle>6.28</max_angle></horizontal></scan>
          <range><min>0.12</min><max>3.5</max><resolution>0.015</resolution></range>
        </lidar>
      </sensor>
    </link>
    <link name="imu_link">
      <pose>0 0 0.068 0 0 0</pose>
      <inertial>
        <mass>0.0001</mass>
        <inertia><ixx>0.0001</ixx><iyy>0.0001</iyy><izz>0.0001</izz><ixy>0</ixy><ixz>0</ixz><iyz>0</iyz></inertia>
      </inertial>
      <sensor name="imu" type="imu">
        <topic>/imu</topic>
        <update_rate>200</update_rate>
        <always_on>1</always_on>
      </sensor>
    </link>
    <joint name="base_joint" type="fixed"><parent>base_footprint</parent><child>base_link</child></joint>
    <joint name="left_wheel_joint" type="revolute"><parent>base_link</parent><child>wheel_left_link</child><axis><xyz>0 0 1</xyz></axis></joint>
    <joint name="right_wheel_joint" type="revolute"><parent>base_link</parent><child>wheel_right_link</child><axis><xyz>0 0 1</xyz></axis></joint>
    <joint name="lidar_joint" type="fixed"><parent>base_link</parent><child>lidar_link</child></joint>
    <joint name="imu_joint" type="fixed"><parent>base_link</parent><child>imu_link</child></joint>
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
</sdf>
""")
    print(f"Created TurtleBot3 model at {output_dir}")

if __name__ == '__main__':
    if len(sys.argv) != 2:
        print("Usage: create_tb3_gz_model_simple.py <output_directory>")
        sys.exit(1)
    create_model(sys.argv[1])
