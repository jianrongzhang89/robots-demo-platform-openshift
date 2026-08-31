#!/usr/bin/env python3
"""
Pose relay for slam_toolbox → Free Fleet compatibility
Relays /pose topic to /amcl_pose for Free Fleet adapter compatibility
"""

import sys
import rclpy
from rclpy.node import Node
from geometry_msgs.msg import PoseWithCovarianceStamped


class PoseRelay(Node):
    def __init__(self, robot_name):
        super().__init__(f'{robot_name}_pose_relay')
        self.robot_name = robot_name

        # Subscribe to slam_toolbox pose
        self.pose_sub = self.create_subscription(
            PoseWithCovarianceStamped,
            f'/{robot_name}/pose',
            self.pose_callback,
            10
        )

        # Publish to amcl_pose
        self.amcl_pose_pub = self.create_publisher(
            PoseWithCovarianceStamped,
            f'/{robot_name}/amcl_pose',
            10
        )

        self.get_logger().info(f'Pose relay started for {robot_name}')
        self.get_logger().info(f'Relaying /{robot_name}/pose → /{robot_name}/amcl_pose')

    def pose_callback(self, msg):
        """Relay pose to amcl_pose topic"""
        self.amcl_pose_pub.publish(msg)


def main(args=None):
    if len(sys.argv) < 2:
        print("Usage: pose_relay.py <robot_name>")
        print("Example: pose_relay.py tinyBot_1")
        sys.exit(1)

    robot_name = sys.argv[1]

    rclpy.init(args=args)
    node = PoseRelay(robot_name)

    try:
        rclpy.spin(node)
    except KeyboardInterrupt:
        pass
    finally:
        node.destroy_node()
        rclpy.shutdown()


if __name__ == '__main__':
    main()
