#!/usr/bin/env python3
"""
Dispatch a multi-level navigation task for RMF Hotel Demo.

This script dispatches a task that requires the robot to navigate between floors
using lifts, demonstrating RMF's multi-level coordination capabilities.
"""

import rclpy
from rclpy.node import Node
from rclpy.qos import QoSProfile, ReliabilityPolicy, DurabilityPolicy, HistoryPolicy
from rmf_task_msgs.msg import ApiRequest, ApiResponse
import json
import time
import sys


class MultiLevelTaskDispatcher(Node):
    def __init__(self):
        super().__init__('multilevel_task_dispatcher')

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

        self.get_logger().info('Multi-Level Task Dispatcher initialized')
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

    def submit_multilevel_task(self, start_waypoint, end_waypoint, robot_name=None):
        """
        Submit a multi-level navigation task.

        Args:
            start_waypoint: Starting waypoint (e.g., "lobby_east" on L1)
            end_waypoint: Destination waypoint on another floor (e.g., "L2_room1")
            robot_name: Specific robot to assign (optional, e.g., "tinyBot_1")
        """
        request_id = f"multilevel_{int(time.time())}"

        # Build multi-level navigation task
        # RMF will automatically plan the lift usage
        task_description = {
            "category": "compose",
            "phases": [
                {
                    "activity": {
                        "category": "go_to_place",
                        "description": {
                            "waypoint": start_waypoint
                        }
                    }
                },
                {
                    "activity": {
                        "category": "go_to_place",
                        "description": {
                            "waypoint": end_waypoint
                        }
                    }
                }
            ]
        }

        task_request = {
            "type": "dispatch_task_request",
            "request": {
                "unix_millis_earliest_start_time": int(time.time() * 1000),
                "category": "delivery",  # Use "delivery" category, fleet has this capability
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
        self.get_logger().info(f'🏨 MULTI-LEVEL NAVIGATION TASK')
        self.get_logger().info(f'Route: {start_waypoint} → {end_waypoint}')
        if robot_name:
            self.get_logger().info(f'Robot: {robot_name}')
        self.get_logger().info(f'Request ID: {request_id}')
        self.get_logger().info('='*70)

        # Publish the request
        self.task_api_pub.publish(msg)
        self.get_logger().info('✅ Task request published!')

        return request_id


def main(args=None):
    """Main function"""

    # Parse command line arguments
    robot = "tinyBot_1" if len(sys.argv) <= 1 else sys.argv[1]
    start = "lobby_east" if len(sys.argv) <= 2 else sys.argv[2]
    destination = "L2_room1" if len(sys.argv) <= 3 else sys.argv[3]

    rclpy.init(args=args)
    dispatcher = MultiLevelTaskDispatcher()

    # Give it a moment to initialize
    time.sleep(1)

    # Submit multi-level navigation task
    print("\n" + "="*70)
    print("🏨 RMF MULTI-LEVEL NAVIGATION DEMO")
    print("="*70)
    print(f"Robot: {robot}")
    print(f"Start: {start} (L1)")
    print(f"Destination: {destination} (L2)")
    print("")
    print("Expected behavior:")
    print("  1. Robot navigates to lift on L1")
    print("  2. Robot requests and enters lift")
    print("  3. Lift travels to L2")
    print("  4. Robot exits lift on L2")
    print("  5. Robot navigates to destination")
    print("="*70 + "\n")

    request_id = dispatcher.submit_multilevel_task(start, destination, robot)

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
        print("\n⚠️  No responses received within 15 seconds")

    print("\n" + "="*70)
    print("📊 To monitor task execution:")
    print("  ros2 topic echo /dispatch_states")
    print(f"  ros2 topic echo /{robot}/robot_state")
    print("  ros2 topic echo /lift_states")
    print("="*70 + "\n")

    dispatcher.destroy_node()
    rclpy.shutdown()


if __name__ == '__main__':
    main()
