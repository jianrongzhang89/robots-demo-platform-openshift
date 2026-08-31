#!/usr/bin/env python3
"""
Odometry to TF publisher for TinyBot robots.

Subscribes to odometry and publishes the odom→base_footprint TF transform.
This is needed because Gazebo's gz_ros_bridge doesn't automatically publish TF
from odometry messages.
"""

import sys
import rclpy
import rclpy.parameter
from rclpy.node import Node
from nav_msgs.msg import Odometry
from geometry_msgs.msg import TransformStamped
from tf2_ros import TransformBroadcaster


class OdomToTF(Node):
    def __init__(self, robot_name):
        super().__init__(f'{robot_name}_odom_to_tf',
                         parameter_overrides=[rclpy.parameter.Parameter('use_sim_time', rclpy.Parameter.Type.BOOL, True)])
        self.robot_name = robot_name

        # TF broadcaster
        self.tf_broadcaster = TransformBroadcaster(self)

        # Subscribe to odometry
        self.odom_sub = self.create_subscription(
            Odometry,
            f'/{robot_name}/odom',
            self.odom_callback,
            10
        )

        self.get_logger().info(f'Odometry to TF publisher started for {robot_name}')

    def odom_callback(self, msg):
        """Publish TF transform from odometry."""
        t = TransformStamped()

        # CRITICAL FIX: Use the odometry message's original timestamp
        # This ensures TF transforms are synchronized with simulation time
        # and can be matched with laser scan messages by slam_toolbox message_filter
        t.header.stamp = msg.header.stamp  # Use original odom timestamp, NOT now()
        t.header.frame_id = msg.header.frame_id  # Should be "tinyBot_X/odom"
        t.child_frame_id = msg.child_frame_id    # Should be "tinyBot_X/base_footprint"

        # Transform (from odometry pose)
        t.transform.translation.x = msg.pose.pose.position.x
        t.transform.translation.y = msg.pose.pose.position.y
        t.transform.translation.z = msg.pose.pose.position.z

        t.transform.rotation.x = msg.pose.pose.orientation.x
        t.transform.rotation.y = msg.pose.pose.orientation.y
        t.transform.rotation.z = msg.pose.pose.orientation.z
        t.transform.rotation.w = msg.pose.pose.orientation.w

        # Broadcast transform
        self.tf_broadcaster.sendTransform(t)


def main(args=None):
    if len(sys.argv) < 2:
        print("Usage: odom_to_tf.py <robot_name>")
        print("Example: odom_to_tf.py tinyBot_1")
        sys.exit(1)

    robot_name = sys.argv[1]

    rclpy.init(args=args)
    node = OdomToTF(robot_name)

    try:
        rclpy.spin(node)
    except KeyboardInterrupt:
        pass
    finally:
        node.destroy_node()
        rclpy.shutdown()


if __name__ == '__main__':
    main()
