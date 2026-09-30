#!/usr/bin/env python3
import os
import time
import zenoh
import rclpy
from nav2_msgs.srv import LoadMap
from rclpy.node import Node


class MapRelay(Node):
    def __init__(self, session):
        super().__init__('federated_map_relay')
        self.client = self.create_client(LoadMap, '/map_server/load_map')
        robot = os.environ.get('ROBOT_NAME', 'robot_1')
        self.result = session.declare_publisher(f'{robot}/map_switch_result')
        self.sub = session.declare_subscriber(f'{robot}/map_switch', self.on_request)
        self.get_logger().info('Federated map-switch relay ready')

    def on_request(self, sample):
        try:
            level, path = sample.payload.to_string().split(' ', 1)
            path = path.replace('/canonical-rmf/maps/', '/opt/ros2-demo/maps/')
            if not self.client.wait_for_service(timeout_sec=10.0):
                self.result.put(f'{level} FAILED service_unavailable')
                return
            request = LoadMap.Request()
            request.map_url = path
            future = self.client.call_async(request)

            def _complete(done):
                try:
                    response = done.result()
                    ok = (response is not None and
                          response.result == LoadMap.Response.RESULT_SUCCESS)
                    self.result.put(f'{level} {"OK" if ok else "FAILED"}')
                except Exception as error:
                    self.get_logger().error(f'Map service failed: {error}')

            future.add_done_callback(_complete)
        except Exception as error:
            self.get_logger().error(f'Map request failed: {error}')


def main():
    rclpy.init()
    config = zenoh.Config()
    config.insert_json5('mode', '"client"')
    config.insert_json5('connect/endpoints', '["tcp/zenoh-router:7447"]')
    config.insert_json5('scouting/multicast/enabled', 'false')
    session = zenoh.open(config)
    node = MapRelay(session)
    try:
        rclpy.spin(node)
    finally:
        node.destroy_node()
        session.close()
        rclpy.shutdown()


if __name__ == '__main__':
    main()
