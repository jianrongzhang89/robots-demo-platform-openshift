#!/usr/bin/env python3
"""Publish the single dynamic odom -> base_footprint TF edge.

Gazebo owns odometry values, but this node is the only process allowed to
publish the dynamic TF edge. robot_state_publisher owns the static robot
links; Nav2/AMCL owns map -> odom.
"""

import rclpy
import os
from geometry_msgs.msg import TransformStamped
from nav_msgs.msg import Odometry
from rclpy.node import Node
from rclpy.parameter import Parameter
from tf2_ros import TransformBroadcaster


class OdomTfAuthority(Node):
    def __init__(self):
        super().__init__("odom_tf_authority")
        self.set_parameters([Parameter("use_sim_time", Parameter.Type.BOOL, True)])
        self._latest = None
        self._initial_x = float(os.environ.get("INITIAL_X", "15.402"))
        self._initial_y = float(os.environ.get("INITIAL_Y", "-31.594"))
        self._broadcaster = TransformBroadcaster(self)
        self.create_subscription(Odometry, "/robot_1/odom", self._odom, 10)
        self.create_timer(0.02, self._publish)

    def _odom(self, message):
        self._latest = message

    def _publish(self):
        transform = TransformStamped()
        transform.header.stamp = self.get_clock().now().to_msg()
        transform.header.frame_id = "odom"
        transform.child_frame_id = "base_footprint"
        if self._latest is not None:
            transform.transform.translation.x = self._latest.pose.pose.position.x
            transform.transform.translation.y = self._latest.pose.pose.position.y
            transform.transform.translation.z = self._latest.pose.pose.position.z
            transform.transform.rotation = self._latest.pose.pose.orientation
        else:
            transform.transform.rotation.w = 1.0
        self._broadcaster.sendTransform(transform)
        map_to_odom = TransformStamped()
        map_to_odom.header.stamp = transform.header.stamp
        map_to_odom.header.frame_id = "map"
        map_to_odom.child_frame_id = "odom"
        map_to_odom.transform.translation.x = self._initial_x
        map_to_odom.transform.translation.y = self._initial_y
        map_to_odom.transform.rotation.w = 1.0
        self._broadcaster.sendTransform(map_to_odom)


def main():
    rclpy.init()
    node = OdomTfAuthority()
    try:
        rclpy.spin(node)
    finally:
        node.destroy_node()
        rclpy.shutdown()


if __name__ == "__main__":
    main()
