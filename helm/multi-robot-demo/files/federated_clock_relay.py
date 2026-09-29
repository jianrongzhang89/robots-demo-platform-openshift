#!/usr/bin/env python3
import rclpy
import zenoh
from rclpy.node import Node
from rclpy.serialization import deserialize_message
from rosgraph_msgs.msg import Clock


class ClockRelay(Node):
    def __init__(self, session):
        super().__init__('federated_clock_relay')
        self.pub = self.create_publisher(Clock, '/clock', 10)
        self.subscribers = [
            session.declare_subscriber('clock_relay/clock_bridge', self.on_clock),
            session.declare_subscriber('clock', self.on_clock),
        ]
        self.get_logger().info(
            'Forwarding Zenoh clock_relay/clock_bridge and clock to ROS /clock')

    def on_clock(self, sample):
        try:
            self.pub.publish(deserialize_message(sample.payload.to_bytes(), Clock))
        except Exception as error:
            self.get_logger().error(f'Clock decode failed: {error}')


def main():
    rclpy.init()
    config = zenoh.Config()
    config.insert_json5('mode', '"client"')
    config.insert_json5('connect/endpoints', '["tcp/zenoh-router:7447"]')
    config.insert_json5('scouting/multicast/enabled', 'false')
    session = zenoh.open(config)
    node = ClockRelay(session)
    try:
        rclpy.spin(node)
    finally:
        node.destroy_node()
        session.close()
        rclpy.shutdown()


if __name__ == '__main__':
    main()
