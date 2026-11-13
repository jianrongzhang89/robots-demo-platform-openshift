#!/usr/bin/env python3
"""Publish Phase 8 odom -> base_footprint TF and leave map -> odom to AMCL."""

import rclpy
import math
from geometry_msgs.msg import PoseWithCovarianceStamped, TransformStamped
from nav_msgs.msg import Odometry
from rclpy.node import Node
from rclpy.parameter import Parameter
from rclpy.qos import HistoryPolicy, QoSProfile, ReliabilityPolicy
from tf2_ros import TransformBroadcaster


class OdomTf(Node):
    def __init__(self):
        super().__init__("phase8_odom_tf")
        self.set_parameters([Parameter("use_sim_time", Parameter.Type.BOOL, True)])
        self.broadcaster = TransformBroadcaster(self)
        self.initial_pose = None
        self.map_to_odom = None
        qos = QoSProfile(depth=10,
                         reliability=ReliabilityPolicy.BEST_EFFORT,
                         history=HistoryPolicy.KEEP_LAST)
        self.create_subscription(Odometry, "/odom", self._odom, qos)
        self.create_subscription(PoseWithCovarianceStamped, "/initialpose",
                                 self._initial_pose, 10)

    @staticmethod
    def _yaw(orientation):
        return math.atan2(2.0 * (orientation.w * orientation.z +
                                 orientation.x * orientation.y),
                          1.0 - 2.0 * (orientation.y ** 2 + orientation.z ** 2))

    def _initial_pose(self, message):
        self.initial_pose = message.pose.pose
        self.map_to_odom = None

    def _odom(self, message):
        transform = TransformStamped()
        transform.header = message.header
        transform.header.frame_id = "odom"
        transform.child_frame_id = "base_footprint"
        transform.transform.translation.x = message.pose.pose.position.x
        transform.transform.translation.y = message.pose.pose.position.y
        transform.transform.translation.z = message.pose.pose.position.z
        transform.transform.rotation = message.pose.pose.orientation
        self.broadcaster.sendTransform(transform)

        if self.initial_pose is not None and self.map_to_odom is None:
            odom_pose = message.pose.pose
            yaw = (self._yaw(self.initial_pose.orientation) -
                   self._yaw(odom_pose.orientation))
            cosine, sine = math.cos(yaw), math.sin(yaw)
            self.map_to_odom = (
                self.initial_pose.position.x -
                (cosine * odom_pose.position.x - sine * odom_pose.position.y),
                self.initial_pose.position.y -
                (sine * odom_pose.position.x + cosine * odom_pose.position.y),
                yaw,
            )
            self.get_logger().info(
                "Rebased map -> odom from the staged initial pose and live odometry")

        if self.map_to_odom is not None:
            map_tf = TransformStamped()
            map_tf.header = transform.header
            map_tf.header.frame_id = "map"
            map_tf.child_frame_id = "odom"
            map_tf.transform.translation.x = self.map_to_odom[0]
            map_tf.transform.translation.y = self.map_to_odom[1]
            map_tf.transform.rotation.z = math.sin(self.map_to_odom[2] / 2.0)
            map_tf.transform.rotation.w = math.cos(self.map_to_odom[2] / 2.0)
            self.broadcaster.sendTransform(map_tf)


def main():
    rclpy.init()
    node = OdomTf()
    try:
        rclpy.spin(node)
    finally:
        node.destroy_node()
        rclpy.shutdown()


if __name__ == "__main__":
    main()
