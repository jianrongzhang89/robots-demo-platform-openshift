#!/usr/bin/env python3
"""
Create TurtleBot3 Waffle model compatible with Gazebo Harmonic (gz-sim).

This script creates a minimal TurtleBot3 Waffle model with:
  - Differential drive plugin (responds to /cmd_vel)
  - LiDAR sensor (360-degree scan, 3.5m range)
  - IMU sensor (for localization)
  - Proper collision and visual meshes

The model is designed to work with Nav2 navigation stack.
"""

import sys
import os
from pathlib import Path

# TurtleBot3 Waffle SDF model for Gazebo Harmonic
TB3_WAFFLE_SDF = """<?xml version="1.0" ?>
<sdf version="1.9">
  <model name="turtlebot3_waffle">
    <pose>0 0 0.01 0 0 0</pose>

    <link name="base_footprint"/>

    <link name="base_link">
      <inertial>
        <pose>-0.064 0 0.048 0 0 0</pose>
        <mass>1.3729096e+00</mass>
        <inertia>
          <ixx>8.7002718e-03</ixx>
          <ixy>-4.7576583e-05</ixy>
          <ixz>1.1160499e-04</ixz>
          <iyy>8.6195418e-03</iyy>
          <iyz>-3.5422299e-06</iyz>
          <izz>1.4612727e-02</izz>
        </inertia>
      </inertial>

      <collision name="base_collision">
        <pose>-0.064 0 0.048 0 0 0</pose>
        <geometry>
          <box>
            <size>0.281 0.306 0.141</size>
          </box>
        </geometry>
      </collision>

      <visual name="base_visual">
        <pose>-0.064 0 0 0 0 0</pose>
        <geometry>
          <mesh>
            <uri>https://fuel.gazebosim.org/1.0/OpenRobotics/models/Turtlebot3%20Waffle%20Pi/2/files/meshes/waffle_pi_base.dae</uri>
            <scale>0.001 0.001 0.001</scale>
          </mesh>
        </geometry>
      </visual>
    </link>

    <link name="wheel_left_link">
      <pose>0.0 0.144 0.023 -1.57 0 0</pose>
      <inertial>
        <mass>2.8498940e-02</mass>
        <inertia>
          <ixx>1.1175580e-05</ixx>
          <ixy>-4.2369783e-11</ixy>
          <ixz>-5.9381719e-09</ixz>
          <iyy>1.1192413e-05</iyy>
          <iyz>-1.4400107e-11</iyz>
          <izz>2.0712558e-05</izz>
        </inertia>
      </inertial>

      <collision name="wheel_left_collision">
        <geometry>
          <cylinder>
            <radius>0.033</radius>
            <length>0.018</length>
          </cylinder>
        </geometry>
        <surface>
          <friction>
            <ode>
              <mu>100000.0</mu>
              <mu2>100000.0</mu2>
            </ode>
          </friction>
        </surface>
      </collision>

      <visual name="wheel_left_visual">
        <geometry>
          <mesh>
            <uri>https://fuel.gazebosim.org/1.0/OpenRobotics/models/Turtlebot3%20Waffle%20Pi/2/files/meshes/left_tire.dae</uri>
            <scale>0.001 0.001 0.001</scale>
          </mesh>
        </geometry>
      </visual>
    </link>

    <link name="wheel_right_link">
      <pose>0.0 -0.144 0.023 -1.57 0 0</pose>
      <inertial>
        <mass>2.8498940e-02</mass>
        <inertia>
          <ixx>1.1175580e-05</ixx>
          <ixy>-4.2369783e-11</ixy>
          <ixz>-5.9381719e-09</ixz>
          <iyy>1.1192413e-05</iyy>
          <iyz>-1.4400107e-11</iyz>
          <izz>2.0712558e-05</izz>
        </inertia>
      </inertial>

      <collision name="wheel_right_collision">
        <geometry>
          <cylinder>
            <radius>0.033</radius>
            <length>0.018</length>
          </cylinder>
        </geometry>
        <surface>
          <friction>
            <ode>
              <mu>100000.0</mu>
              <mu2>100000.0</mu2>
            </ode>
          </friction>
        </surface>
      </collision>

      <visual name="wheel_right_visual">
        <geometry>
          <mesh>
            <uri>https://fuel.gazebosim.org/1.0/OpenRobotics/models/Turtlebot3%20Waffle%20Pi/2/files/meshes/right_tire.dae</uri>
            <scale>0.001 0.001 0.001</scale>
          </mesh>
        </geometry>
      </visual>
    </link>

    <link name="caster_back_right_link">
      <pose>-0.177 -0.064 -0.004 0 0 0</pose>
      <inertial>
        <mass>0.001</mass>
        <inertia>
          <ixx>0.00001</ixx>
          <ixy>0.0</ixy>
          <ixz>0.0</ixz>
          <iyy>0.00001</iyy>
          <iyz>0.0</iyz>
          <izz>0.00001</izz>
        </inertia>
      </inertial>
      <collision name="caster_back_right_collision">
        <geometry>
          <sphere>
            <radius>0.005</radius>
          </sphere>
        </geometry>
        <surface>
          <friction>
            <ode>
              <mu>0.0</mu>
              <mu2>0.0</mu2>
            </ode>
          </friction>
        </surface>
      </collision>
    </link>

    <link name="caster_back_left_link">
      <pose>-0.177 0.064 -0.004 0 0 0</pose>
      <inertial>
        <mass>0.001</mass>
        <inertia>
          <ixx>0.00001</ixx>
          <ixy>0.0</ixy>
          <ixz>0.0</ixz>
          <iyy>0.00001</iyy>
          <iyz>0.0</iyz>
          <izz>0.00001</izz>
        </inertia>
      </inertial>
      <collision name="caster_back_left_collision">
        <geometry>
          <sphere>
            <radius>0.005</radius>
          </sphere>
        </geometry>
        <surface>
          <friction>
            <ode>
              <mu>0.0</mu>
              <mu2>0.0</mu2>
            </ode>
          </friction>
        </surface>
      </collision>
    </link>

    <link name="lidar_link">
      <pose>-0.064 0 0.172 0 0 0</pose>
      <inertial>
        <mass>0.125</mass>
        <inertia>
          <ixx>0.001</ixx>
          <ixy>0.0</ixy>
          <ixz>0.0</ixz>
          <iyy>0.001</iyy>
          <iyz>0.0</iyz>
          <izz>0.001</izz>
        </inertia>
      </inertial>

      <collision name="lidar_collision">
        <geometry>
          <cylinder>
            <radius>0.0508</radius>
            <length>0.055</length>
          </cylinder>
        </geometry>
      </collision>

      <visual name="lidar_visual">
        <geometry>
          <mesh>
            <uri>https://fuel.gazebosim.org/1.0/OpenRobotics/models/Turtlebot3%20Waffle%20Pi/2/files/meshes/lds.dae</uri>
            <scale>0.001 0.001 0.001</scale>
          </mesh>
        </geometry>
      </visual>

      <sensor name="lidar" type="gpu_lidar">
        <topic>scan</topic>
        <update_rate>5</update_rate>
        <lidar>
          <scan>
            <horizontal>
              <samples>360</samples>
              <resolution>1</resolution>
              <min_angle>0.0</min_angle>
              <max_angle>6.28</max_angle>
            </horizontal>
          </scan>
          <range>
            <min>0.12</min>
            <max>3.5</max>
            <resolution>0.015</resolution>
          </range>
          <noise>
            <type>gaussian</type>
            <mean>0.0</mean>
            <stddev>0.01</stddev>
          </noise>
        </lidar>
        <alwaysOn>1</alwaysOn>
        <visualize>true</visualize>
      </sensor>
    </link>

    <link name="imu_link">
      <pose>-0.032 0 0.068 0 0 0</pose>
      <inertial>
        <mass>0.001</mass>
        <inertia>
          <ixx>0.0001</ixx>
          <ixy>0.0</ixy>
          <ixz>0.0</ixz>
          <iyy>0.0001</iyy>
          <iyz>0.0</iyz>
          <izz>0.0001</izz>
        </inertia>
      </inertial>

      <sensor name="imu" type="imu">
        <topic>imu</topic>
        <update_rate>200</update_rate>
        <imu>
          <angular_velocity>
            <x>
              <noise type="gaussian">
                <mean>0.0</mean>
                <stddev>2e-4</stddev>
              </noise>
            </x>
            <y>
              <noise type="gaussian">
                <mean>0.0</mean>
                <stddev>2e-4</stddev>
              </noise>
            </y>
            <z>
              <noise type="gaussian">
                <mean>0.0</mean>
                <stddev>2e-4</stddev>
              </noise>
            </z>
          </angular_velocity>
          <linear_acceleration>
            <x>
              <noise type="gaussian">
                <mean>0.0</mean>
                <stddev>1.7e-2</stddev>
              </noise>
            </x>
            <y>
              <noise type="gaussian">
                <mean>0.0</mean>
                <stddev>1.7e-2</stddev>
              </noise>
            </y>
            <z>
              <noise type="gaussian">
                <mean>0.0</mean>
                <stddev>1.7e-2</stddev>
              </noise>
            </z>
          </linear_acceleration>
        </imu>
        <alwaysOn>1</alwaysOn>
      </sensor>
    </link>

    <!-- Joints -->
    <joint name="base_joint" type="fixed">
      <parent>base_footprint</parent>
      <child>base_link</child>
      <pose>0.0 0.0 0.01 0 0 0</pose>
    </joint>

    <joint name="wheel_left_joint" type="revolute">
      <parent>base_link</parent>
      <child>wheel_left_link</child>
      <axis>
        <xyz>0 1 0</xyz>
        <limit>
          <lower>-1e16</lower>
          <upper>1e16</upper>
        </limit>
      </axis>
    </joint>

    <joint name="wheel_right_joint" type="revolute">
      <parent>base_link</parent>
      <child>wheel_right_link</child>
      <axis>
        <xyz>0 1 0</xyz>
        <limit>
          <lower>-1e16</lower>
          <upper>1e16</upper>
        </limit>
      </axis>
    </joint>

    <joint name="caster_back_right_joint" type="fixed">
      <parent>base_link</parent>
      <child>caster_back_right_link</child>
    </joint>

    <joint name="caster_back_left_joint" type="fixed">
      <parent>base_link</parent>
      <child>caster_back_left_link</child>
    </joint>

    <joint name="lidar_joint" type="fixed">
      <parent>base_link</parent>
      <child>lidar_link</child>
    </joint>

    <joint name="imu_joint" type="fixed">
      <parent>base_link</parent>
      <child>imu_link</child>
    </joint>

    <!-- Differential Drive Plugin -->
    <plugin filename="gz-sim-diff-drive-system" name="gz::sim::systems::DiffDrive">
      <left_joint>wheel_left_joint</left_joint>
      <right_joint>wheel_right_joint</right_joint>
      <wheel_separation>0.287</wheel_separation>
      <wheel_radius>0.033</wheel_radius>
      <odom_publish_frequency>50</odom_publish_frequency>
      <topic>cmd_vel</topic>
      <odom_topic>odom</odom_topic>
      <frame_id>odom</frame_id>
      <child_frame_id>base_footprint</child_frame_id>
    </plugin>

    <!-- Joint State Publisher -->
    <plugin filename="gz-sim-joint-state-publisher-system" name="gz::sim::systems::JointStatePublisher">
      <topic>joint_states</topic>
    </plugin>

    <!-- Pose Publisher -->
    <plugin filename="gz-sim-pose-publisher-system" name="gz::sim::systems::PosePublisher">
      <publish_link_pose>true</publish_link_pose>
      <publish_sensor_pose>true</publish_sensor_pose>
      <publish_collision_pose>false</publish_collision_pose>
      <publish_visual_pose>false</publish_visual_pose>
      <publish_nested_model_pose>true</publish_nested_model_pose>
      <update_frequency>50</update_frequency>
    </plugin>

  </model>
</sdf>
"""

TB3_MODEL_CONFIG = """<?xml version="1.0"?>
<model>
  <name>TurtleBot3 Waffle</name>
  <version>1.0</version>
  <sdf version="1.9">model.sdf</sdf>
  <author>
    <name>ROS 2 Multi-Robot Demo</name>
    <email>noreply@example.com</email>
  </author>
  <description>
    TurtleBot3 Waffle model for Gazebo Harmonic with differential drive,
    LiDAR, and IMU. Compatible with Nav2 navigation stack.
  </description>
</model>
"""


def main():
    if len(sys.argv) != 2:
        print(f"Usage: {sys.argv[0]} <model_directory>")
        sys.exit(1)

    model_dir = Path(sys.argv[1])
    model_dir.mkdir(parents=True, exist_ok=True)

    # Write model.sdf
    sdf_path = model_dir / "model.sdf"
    with open(sdf_path, 'w') as f:
        f.write(TB3_WAFFLE_SDF)
    print(f"Created {sdf_path}")

    # Write model.config
    config_path = model_dir / "model.config"
    with open(config_path, 'w') as f:
        f.write(TB3_MODEL_CONFIG)
    print(f"Created {config_path}")

    print(f"\nTurtleBot3 Waffle model created at {model_dir}")
    print("Model includes:")
    print("  - Differential drive plugin (listens to /cmd_vel)")
    print("  - 360-degree LiDAR (publishes to /scan)")
    print("  - IMU sensor (publishes to /imu)")
    print("  - Odometry (publishes to /odom)")


if __name__ == "__main__":
    main()
