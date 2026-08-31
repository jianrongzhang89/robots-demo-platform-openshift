#!/usr/bin/env python3
"""
Dispatch RMF task using the Task API.

This script creates a simple delivery task between lobby waypoints
and submits it to the RMF task dispatcher.
"""

import rclpy
from rclpy.node import Node
from rclpy.qos import QoSProfile, ReliabilityPolicy, DurabilityPolicy, HistoryPolicy
from rmf_task_msgs.msg import ApiRequest, ApiResponse
import json
import time
import sys


class RMFTaskDispatcher(Node):
    def __init__(self):
        super().__init__('rmf_task_dispatcher')

        # QoS profile for task API (TRANSIENT_LOCAL durability required)
        task_api_qos = QoSProfile(
            reliability=ReliabilityPolicy.RELIABLE,
            durability=DurabilityPolicy.TRANSIENT_LOCAL,
            history=HistoryPolicy.KEEP_LAST,
            depth=10
        )

        # Publisher for task API requests
        self.task_api_pub = self.create_publisher(
            ApiRequest,
            '/task_api_requests',
            task_api_qos
        )

        # Subscriber for task API responses
        self.task_api_sub = self.create_subscription(
            ApiResponse,
            '/task_api_responses',
            self.task_response_callback,
            task_api_qos
        )

        self.get_logger().info('RMF Task Dispatcher initialized')
        self.responses = []

    def task_response_callback(self, msg):
        """Handle task API responses"""
        self.get_logger().info(f'Received response: type={msg.type}, request_id={msg.request_id}')
        try:
            response_data = json.loads(msg.json_msg)
            self.get_logger().info(f'Response: {json.dumps(response_data, indent=2)}')
            self.responses.append(response_data)
        except Exception as e:
            self.get_logger().error(f'Error parsing response: {e}')

    def submit_delivery_task(self, pickup, dropoff, robot_name=None):
        """
        Submit a delivery task.

        Args:
            pickup: Waypoint name for pickup location
            dropoff: Waypoint name for dropoff location
            robot_name: Specific robot to assign (optional)
        """
        request_id = f"delivery_{int(time.time())}"

        # Build delivery task
        task_description = {
            "category": "compose",
            "phases": [
                {
                    "activity": {
                        "category": "go_to_place",
                        "description": {
                            "waypoint": pickup
                        }
                    }
                },
                {
                    "activity": {
                        "category": "perform_action",
                        "description": {
                            "unix_millis_action_duration_estimate": 5000,
                            "category": "wait",
                            "description": {}
                        }
                    }
                },
                {
                    "activity": {
                        "category": "go_to_place",
                        "description": {
                            "waypoint": dropoff
                        }
                    }
                }
            ]
        }

        task_request = {
            "type": "dispatch_task_request",
            "request": {
                "unix_millis_earliest_start_time": int(time.time() * 1000),
                "category": "delivery",
                "description": task_description
            }
        }

        # Add robot assignment if specified
        if robot_name:
            task_request["request"]["assignments"] = [robot_name]

        # Create API request message
        msg = ApiRequest()
        msg.request_id = request_id
        msg.json_msg = json.dumps(task_request)

        self.get_logger().info('='*70)
        self.get_logger().info(f'Submitting delivery task: {pickup} → {dropoff}')
        if robot_name:
            self.get_logger().info(f'Assigned to robot: {robot_name}')
        self.get_logger().info(f'Request ID: {request_id}')
        self.get_logger().info('='*70)

        # Publish the request
        self.task_api_pub.publish(msg)
        self.get_logger().info('Task request published!')

        return request_id


def main(args=None):
    """Main function"""

    rclpy.init(args=args)
    dispatcher = RMFTaskDispatcher()

    # Give it a moment to initialize
    time.sleep(1)

    # Submit a delivery task: lobby_west → lobby_southeast
    print("\n" + "="*70)
    print("RMF DELIVERY TASK DISPATCH")
    print("="*70)
    print("Task: Deliver from lobby_west to lobby_southeast")
    print("Fleet: tinyRobot (any available robot)")
    print("="*70 + "\n")

    request_id = dispatcher.submit_delivery_task('lobby_west', 'lobby_southeast')

    # Spin for a bit to receive responses
    print("Waiting for task responses...")
    start_time = time.time()
    while time.time() - start_time < 15.0:
        rclpy.spin_once(dispatcher, timeout_sec=0.5)

    print("\n" + "="*70)
    print(f"Received {len(dispatcher.responses)} response(s)")
    print("="*70)

    if dispatcher.responses:
        for i, resp in enumerate(dispatcher.responses):
            print(f"\nResponse {i+1}:")
            print(json.dumps(resp, indent=2))
    else:
        print("\nNo responses received within 15 seconds")
        print("Check /dispatch_states topic for task status:")
        print("  ros2 topic echo /dispatch_states")

    print("\n" + "="*70)
    print("To monitor task execution:")
    print("  ros2 topic echo /dispatch_states")
    print("  ros2 topic echo /tinyBot_2/robot_state")
    print("  ros2 topic echo /tinyBot_3/robot_state")
    print("="*70 + "\n")

    dispatcher.destroy_node()
    rclpy.shutdown()


if __name__ == '__main__':
    main()
