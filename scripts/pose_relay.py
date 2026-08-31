#!/usr/bin/env python3
"""
Pose publisher for slam_toolbox → Free Fleet compatibility

Computes robot pose from TF tree (map→base_footprint) and publishes to /amcl_pose.
slam_toolbox localization mode publishes TF but not always /pose topic, so we
compute the pose from TF lookups instead.
"""

import sys
import rclpy
import rclpy.parameter
from rclpy.node import Node
from geometry_msgs.msg import PoseWithCovarianceStamped
from tf2_ros import TransformException, Buffer, TransformListener


class PosePublisher(Node):
    def __init__(self, robot_name):
        super().__init__(f'{robot_name}_pose_publisher',
                         parameter_overrides=[rclpy.parameter.Parameter('use_sim_time', rclpy.Parameter.Type.BOOL, True)])
        self.robot_name = robot_name

        # TF buffer and listener
        self.tf_buffer = Buffer()
        self.tf_listener = TransformListener(self.tf_buffer, self)

        # Publish to amcl_pose
        self.amcl_pose_pub = self.create_publisher(
            PoseWithCovarianceStamped,
            f'/{robot_name}/amcl_pose',
            10
        )

        # Timer to publish pose at 10Hz (Free Fleet needs continuous updates)
        self.timer = self.create_timer(0.1, self.publish_pose)

        self.get_logger().info(f'Pose publisher started for {robot_name}')
        self.get_logger().info(f'Publishing TF-based pose to /{robot_name}/amcl_pose at 10Hz')

    def publish_pose(self):
        """Compute pose from TF and publish to /amcl_pose"""
        try:
            # Lookup transform from map to base_footprint
            transform = self.tf_buffer.lookup_transform(
                'map',
                f'{self.robot_name}/base_footprint',
                rclpy.time.Time(),  # Latest available
                timeout=rclpy.duration.Duration(seconds=0.1)
            )

            # Convert transform to PoseWithCovarianceStamped
            pose_msg = PoseWithCovarianceStamped()
            pose_msg.header.stamp = self.get_clock().now().to_msg()
            pose_msg.header.frame_id = 'map'

            # Position
            pose_msg.pose.pose.position.x = transform.transform.translation.x
            pose_msg.pose.pose.position.y = transform.transform.translation.y
            pose_msg.pose.pose.position.z = transform.transform.translation.z

            # Orientation
            pose_msg.pose.pose.orientation.x = transform.transform.rotation.x
            pose_msg.pose.pose.orientation.y = transform.transform.rotation.y
            pose_msg.pose.pose.orientation.z = transform.transform.rotation.z
            pose_msg.pose.pose.orientation.w = transform.transform.rotation.w

            # Covariance (small values indicating good localization)
            # AMCL-like covariance: x, y, yaw have uncertainty, others are 0
            pose_msg.pose.covariance = [
                0.05, 0.0, 0.0, 0.0, 0.0, 0.0,   # x variance
                0.0, 0.05, 0.0, 0.0, 0.0, 0.0,   # y variance
                0.0, 0.0, 0.0, 0.0, 0.0, 0.0,    # z (unused)
                0.0, 0.0, 0.0, 0.0, 0.0, 0.0,    # roll (unused)
                0.0, 0.0, 0.0, 0.0, 0.0, 0.0,    # pitch (unused)
                0.0, 0.0, 0.0, 0.0, 0.0, 0.01    # yaw variance
            ]

            # Publish
            self.amcl_pose_pub.publish(pose_msg)

        except TransformException as ex:
            # Don't spam logs - TF may not be available during startup
            pass


def main(args=None):
    if len(sys.argv) < 2:
        print("Usage: pose_relay.py <robot_name>")
        print("Example: pose_relay.py tinyBot_1")
        sys.exit(1)

    robot_name = sys.argv[1]

    rclpy.init(args=args)
    node = PosePublisher(robot_name)

    try:
        rclpy.spin(node)
    except KeyboardInterrupt:
        pass
    finally:
        node.destroy_node()
        rclpy.shutdown()


if __name__ == '__main__':
    main()

