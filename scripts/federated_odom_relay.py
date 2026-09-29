#!/usr/bin/env python3
"""Forward the federated odometry key directly into the local ROS graph."""

import os
import threading

import rclpy
import zenoh
from nav_msgs.msg import Odometry
from rclpy.node import Node
from rclpy.qos import QoSProfile, ReliabilityPolicy
from rclpy.serialization import deserialize_message


class FederatedOdomRelay(Node):
    def __init__(self, session):
        super().__init__("federated_odom_relay")
        self._publisher = self.create_publisher(
            Odometry,
            "/odom",
            QoSProfile(depth=10, reliability=ReliabilityPolicy.RELIABLE),
        )
        self._count = 0
        robot = os.environ.get("ROBOT_NAME", "robot_1")
        self._subscriber = session.declare_subscriber(
            f"{robot}/odom", self._on_sample
        )
        self.get_logger().info(f"Forwarding Zenoh {robot}/odom to ROS /odom")

    def _on_sample(self, sample):
        try:
            message = deserialize_message(sample.payload.to_bytes(), Odometry)
            self._publisher.publish(message)
            self._count += 1
            if self._count % 100 == 0:
                self.get_logger().info(f"Forwarded {self._count} odometry messages")
        except Exception as error:
            self.get_logger().error(f"Failed to deserialize odometry: {error}")


def main():
    rclpy.init(args=["--ros-args", "-p", "use_sim_time:=true"])
    config = zenoh.Config()
    config.insert_json5("mode", '"client"')
    config.insert_json5(
        "connect/endpoints", '["tcp/zenoh-router:7447"]'
    )
    config.insert_json5("scouting/multicast/enabled", "false")
    session = zenoh.open(config)
    node = FederatedOdomRelay(session)
    try:
        rclpy.spin(node)
    finally:
        node.destroy_node()
        session.close()
        rclpy.shutdown()


if __name__ == "__main__":
    main()
