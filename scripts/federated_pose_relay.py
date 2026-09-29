#!/usr/bin/env python3
"""Publish continuous map-frame pose for the federated RMF adapter."""

import rclpy
from geometry_msgs.msg import PoseWithCovarianceStamped
from rclpy.node import Node
from rclpy.parameter import Parameter
from rclpy.qos import QoSProfile, ReliabilityPolicy, HistoryPolicy
from tf2_ros import Buffer, TransformListener


class PoseRelay(Node):
    def __init__(self):
        super().__init__(
            "federated_pose_relay",
            parameter_overrides=[Parameter("use_sim_time", Parameter.Type.BOOL, True)],
        )
        qos = QoSProfile(
            depth=10,
            reliability=ReliabilityPolicy.BEST_EFFORT,
            history=HistoryPolicy.KEEP_LAST,
        )
        self._buffer = Buffer()
        self._listener = TransformListener(self._buffer, self)
        self._pub = self.create_publisher(PoseWithCovarianceStamped, "/amcl_pose", qos)
        self.create_timer(0.1, self._publish_pose)

    def _publish_pose(self):
        try:
            tf = self._buffer.lookup_transform("map", "base_footprint", rclpy.time.Time())
        except Exception:
            return
        msg = PoseWithCovarianceStamped()
        msg.header = tf.header
        msg.header.frame_id = "map"
        msg.pose.pose.position.x = tf.transform.translation.x
        msg.pose.pose.position.y = tf.transform.translation.y
        msg.pose.pose.position.z = tf.transform.translation.z
        msg.pose.pose.orientation = tf.transform.rotation
        msg.pose.covariance[0] = 0.04
        msg.pose.covariance[7] = 0.04
        msg.pose.covariance[35] = 0.02
        self._pub.publish(msg)


rclpy.init()
node = PoseRelay()
rclpy.spin(node)
node.destroy_node()
rclpy.shutdown()
