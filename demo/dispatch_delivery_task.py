#!/usr/bin/env python3
"""
Dispatch a simple delivery task to test RMF integration with Free Fleet.

This script creates a delivery task and submits it via the RMF Task API.
The task will be assigned to an available robot in the tinyRobot fleet.
"""

import rclpy
from rclpy.node import Node
from rmf_task_msgs.msg import ApiRequest, TaskType
import json
import time
import sys


class TaskDispatcher(Node):
    def __init__(self):
        super().__init__('task_dispatcher')

        # Set use_sim_time parameter (may already be declared)
        try:
            self.declare_parameter('use_sim_time', True)
        except:
            pass  # Parameter already declared

        # Publisher for task API requests
        self.task_api_pub = self.create_publisher(
            ApiRequest,
            '/task_api_requests',
            10
        )

        # Subscriber for task API responses
        self.task_api_sub = self.create_subscription(
            ApiRequest,
            '/task_api_responses',
            self.task_response_callback,
            10
        )

        self.get_logger().info('Task dispatcher initialized')
        self.response_received = False
        self.last_response = None

    def task_response_callback(self, msg):
        """Handle task API responses"""
        self.get_logger().info(f'Received task response: {msg.request_id}')
        try:
            response_data = json.loads(msg.json_msg)
            self.get_logger().info(f'Response data: {json.dumps(response_data, indent=2)}')
            self.response_received = True
            self.last_response = response_data
        except Exception as e:
            self.get_logger().error(f'Error parsing response: {e}')

    def submit_delivery_task(self, pickup_place, dropoff_place, fleet_name='tinyRobot'):
        """
        Submit a delivery task.

        Args:
            pickup_place: Waypoint name for pickup location
            dropoff_place: Waypoint name for dropoff location
            fleet_name: Fleet name (default: tinyRobot)
        """
        request_id = f"delivery_{int(time.time())}"

        # Create delivery task request
        task_request = {
            "type": "delivery_request",
            "request": {
                "unix_millis_earliest_start_time": int(time.time() * 1000),
                "category": "delivery",
                "description": {
                    "category": "delivery",
                    "phases": [
                        {
                            "activity": {
                                "category": "go_to_place",
                                "description": pickup_place
                            }
                        },
                        {
                            "activity": {
                                "category": "go_to_place",
                                "description": dropoff_place
                            }
                        }
                    ]
                },
                "labels": [f"test_delivery_{request_id}"]
            }
        }

        # Create API request message
        msg = ApiRequest()
        msg.request_id = request_id
        msg.json_msg = json.dumps(task_request)

        self.get_logger().info(f'Submitting delivery task: {pickup_place} → {dropoff_place}')
        self.get_logger().info(f'Request ID: {request_id}')
        self.get_logger().info(f'Task request: {json.dumps(task_request, indent=2)}')

        # Publish the request
        self.task_api_pub.publish(msg)
        self.get_logger().info('Task request published')

    def submit_loop_task(self, places, num_loops=1, fleet_name='tinyRobot'):
        """
        Submit a loop task that visits multiple places.

        Args:
            places: List of waypoint names to visit in order
            num_loops: Number of times to repeat the loop
            fleet_name: Fleet name (default: tinyRobot)
        """
        request_id = f"loop_{int(time.time())}"

        # Create phases for each place
        phases = []
        for place in places * num_loops:
            phases.append({
                "activity": {
                    "category": "go_to_place",
                    "description": place
                }
            })

        task_request = {
            "type": "task_request",
            "request": {
                "unix_millis_earliest_start_time": int(time.time() * 1000),
                "category": "patrol",
                "description": {
                    "category": "patrol",
                    "phases": phases
                },
                "labels": [f"test_patrol_{request_id}"]
            }
        }

        # Create API request message
        msg = ApiRequest()
        msg.request_id = request_id
        msg.json_msg = json.dumps(task_request)

        self.get_logger().info(f'Submitting loop task: {" → ".join(places)} ({num_loops} loops)')
        self.get_logger().info(f'Request ID: {request_id}')

        # Publish the request
        self.task_api_pub.publish(msg)
        self.get_logger().info('Task request published')


def main(args=None):
    """Main function to dispatch a test task"""

    rclpy.init(args=args)
    dispatcher = TaskDispatcher()

    # Give it a moment to initialize
    time.sleep(1)

    # Example 1: Simple delivery task
    # lobby_north → lobby_south
    print("\n" + "="*60)
    print("EXAMPLE 1: Delivery Task")
    print("="*60)
    print("Task: Pick up at lobby_north, deliver to lobby_south")
    print()
    dispatcher.submit_delivery_task('lobby_north', 'lobby_south')

    # Spin for a bit to receive responses
    print("\nWaiting for task response...")
    start_time = time.time()
    while time.time() - start_time < 10.0:
        rclpy.spin_once(dispatcher, timeout_sec=0.5)
        if dispatcher.response_received:
            print("\n✓ Task response received!")
            break

    if not dispatcher.response_received:
        print("\n⚠ No response received within 10 seconds")
        print("  Task may still be processing...")

    # Example 2: Simple patrol loop
    # Uncomment to test:
    # print("\n" + "="*60)
    # print("EXAMPLE 2: Patrol Loop")
    # print("="*60)
    # print("Task: Patrol lobby_north → lobby_south → lobby_west → lobby_north")
    # print()
    # dispatcher.submit_loop_task(['lobby_north', 'lobby_south', 'lobby_west'], num_loops=2)
    #
    # time.sleep(1)
    # rclpy.spin_once(dispatcher, timeout_sec=5.0)

    print("\n" + "="*60)
    print("Task dispatch complete!")
    print("="*60)
    print("\nTo monitor task execution:")
    print("  ros2 topic echo /dispatch_states")
    print("  ros2 topic echo /tinyBot_1/robot_state")
    print()

    dispatcher.destroy_node()
    rclpy.shutdown()


if __name__ == '__main__':
    main()
