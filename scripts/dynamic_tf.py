#!/usr/bin/env python3
"""
Dynamic TF publisher for TinyBot robots.

Publishes "static" transforms with current simulation timestamps to avoid
message_filter issues with slam_toolbox.

This replaces static_transform_publisher which publishes with timestamp=0,
causing TF synchronization problems with simulation-timestamped laser scans.
"""

import sys
import rclpy
import rclpy.parameter
from rclpy.node import Node
from geometry_msgs.msg import TransformStamped
from tf2_ros import TransformBroadcaster
import math


class DynamicTFPublisher(Node):
    def __init__(self, robot_name, frame_id, child_frame_id, x, y, z, roll, pitch, yaw):
        super().__init__(f'{robot_name}_dynamic_tf',
                         parameter_overrides=[rclpy.parameter.Parameter('use_sim_time', rclpy.Parameter.Type.BOOL, True)])

        self.robot_name = robot_name
        self.frame_id = frame_id
        self.child_frame_id = child_frame_id
        self.x = x
        self.y = y
        self.z = z

        # Convert roll, pitch, yaw to quaternion
        cy = math.cos(yaw * 0.5)
        sy = math.sin(yaw * 0.5)
        cp = math.cos(pitch * 0.5)
        sp = math.sin(pitch * 0.5)
        cr = math.cos(roll * 0.5)
        sr = math.sin(roll * 0.5)

        self.qw = cr * cp * cy + sr * sp * sy
        self.qx = sr * cp * cy - cr * sp * sy
        self.qy = cr * sp * cy + sr * cp * sy
        self.qz = cr * cp * sy - sr * sp * cy

        # TF broadcaster
        self.tf_broadcaster = TransformBroadcaster(self)

        # Publish transform at 10Hz (faster than slam_toolbox needs)
        self.timer = self.create_timer(0.1, self.publish_transform)

        self.get_logger().info(
            f'Dynamic TF publisher started: {frame_id} → {child_frame_id} '
            f'({x}, {y}, {z}, {roll}, {pitch}, {yaw})'
        )

    def publish_transform(self):
        """Publish TF transform with current simulation time."""
        t = TransformStamped()

        # CRITICAL: Use current simulation time, not timestamp=0
        t.header.stamp = self.get_clock().now().to_msg()
        t.header.frame_id = self.frame_id
        t.child_frame_id = self.child_frame_id

        # Translation
        t.transform.translation.x = self.x
        t.transform.translation.y = self.y
        t.transform.translation.z = self.z

        # Rotation (quaternion)
        t.transform.rotation.x = self.qx
        t.transform.rotation.y = self.qy
        t.transform.rotation.z = self.qz
        t.transform.rotation.w = self.qw

        # Broadcast transform
        self.tf_broadcaster.sendTransform(t)


def main(args=None):
    if len(sys.argv) < 9:
        print("Usage: dynamic_tf.py <robot_name> <frame_id> <child_frame_id> <x> <y> <z> <roll> <pitch> <yaw>")
        print("Example: dynamic_tf.py tinyBot_1 tinyBot_1/base_footprint tinyBot_1/lidar_link 0.05 0 0.28 0 0 0")
        sys.exit(1)

    robot_name = sys.argv[1]
    frame_id = sys.argv[2]
    child_frame_id = sys.argv[3]
    x = float(sys.argv[4])
    y = float(sys.argv[5])
    z = float(sys.argv[6])
    roll = float(sys.argv[7])
    pitch = float(sys.argv[8])
    yaw = float(sys.argv[9])

    rclpy.init(args=args)
    node = DynamicTFPublisher(robot_name, frame_id, child_frame_id, x, y, z, roll, pitch, yaw)

    try:
        rclpy.spin(node)
    except KeyboardInterrupt:
        pass
    finally:
        node.destroy_node()
        rclpy.shutdown()


if __name__ == '__main__':
    main()
