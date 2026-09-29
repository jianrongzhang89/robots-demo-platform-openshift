#!/usr/bin/env python3
"""Publish the federated Nav2 odom -> base_footprint TF edge."""

import rclpy
import os
from geometry_msgs.msg import TransformStamped
from nav_msgs.msg import Odometry
from rclpy.node import Node
from rclpy.parameter import Parameter
from rclpy.qos import QoSProfile, ReliabilityPolicy, HistoryPolicy
from tf2_ros import TransformBroadcaster


class OdomTfBroadcaster(Node):
    def __init__(self):
        super().__init__(
            "federated_odom_tf",
            parameter_overrides=[Parameter("use_sim_time", Parameter.Type.BOOL, True)],
        )
        self._broadcaster = TransformBroadcaster(self)
        self._map_x = float(os.environ.get("INITIAL_X", "15.402"))
        self._map_y = float(os.environ.get("INITIAL_Y", "-31.594"))
        self._last_stamp_ns = 0
        qos = QoSProfile(
            depth=10,
            reliability=ReliabilityPolicy.BEST_EFFORT,
            history=HistoryPolicy.KEEP_LAST,
        )
        self.create_subscription(Odometry, "/odom", self._publish, qos)

    def _publish(self, msg):
        stamp_ns = msg.header.stamp.sec * 1_000_000_000 + msg.header.stamp.nanosec
        if stamp_ns < self._last_stamp_ns:
            if self._last_stamp_ns - stamp_ns <= 30 * 1_000_000_000:
                return
            # Gazebo restarted; accept the new clock epoch.
            self._last_stamp_ns = 0
        if stamp_ns <= self._last_stamp_ns:
            return
        self._last_stamp_ns = stamp_ns
        tf = TransformStamped()
        tf.header = msg.header
        tf.header.frame_id = "odom"
        tf.child_frame_id = "base_footprint"
        tf.transform.translation.x = msg.pose.pose.position.x
        tf.transform.translation.y = msg.pose.pose.position.y
        tf.transform.translation.z = msg.pose.pose.position.z
        tf.transform.rotation = msg.pose.pose.orientation
        self._broadcaster.sendTransform(tf)

        map_tf = TransformStamped()
        map_tf.header.stamp = tf.header.stamp
        map_tf.header.frame_id = "map"
        map_tf.child_frame_id = "odom"
        map_tf.transform.translation.x = self._map_x
        map_tf.transform.translation.y = self._map_y
        map_tf.transform.rotation.w = 1.0
        self._broadcaster.sendTransform(map_tf)


rclpy.init()
node = OdomTfBroadcaster()
rclpy.spin(node)
node.destroy_node()
rclpy.shutdown()
