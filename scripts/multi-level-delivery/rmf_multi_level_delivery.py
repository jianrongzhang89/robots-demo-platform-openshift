#!/usr/bin/env python3
"""
RMF Multi-Level Delivery using Task Dispatch
=============================================
Uses proper RMF task dispatch to send deliveryBot_1 to different floors.
The lift supervisor will automatically coordinate lift usage.
"""

import rclpy
from rclpy.node import Node
from rmf_task_msgs.msg import ApiRequest, ApiResponse
import json
import time
import uuid


class MultiLevelDeliveryDispatcher(Node):
    def __init__(self):
        super().__init__('multi_level_delivery_dispatcher')
        
        # Publisher for task requests
        self.task_pub = self.create_publisher(
            ApiRequest,
            '/task_api_requests',
            10
        )
        
        # Subscriber for task responses
        self.response_sub = self.create_subscription(
            ApiResponse,
            '/task_api_responses',
            self.response_callback,
            10
        )
        
        self.responses = []
        
        self.get_logger().info('Multi-level delivery dispatcher initialized')
        
    def response_callback(self, msg):
        """Handle task API responses."""
        self.get_logger().info(f'Received response: {msg.json_msg}')
        self.responses.append(msg)
        
    def dispatch_delivery_task(self, pickup_place, dropoff_place, description="Delivery"):
        """Dispatch a delivery task between two places."""
        
        task_id = str(uuid.uuid4())
        
        # Create task request in RMF format
        task_request = {
            "type": "dispatch_task_request",
            "request": {
                "category": "compose",
                "description": {
                    "category": "delivery",
                    "phases": [
                        {
                            "activity": {
                                "category": "go_to_place",
                                "description": {
                                    "one_of": [
                                        {"waypoint": pickup_place}
                                    ]
                                }
                            }
                        },
                        {
                            "activity": {
                                "category": "go_to_place", 
                                "description": {
                                    "one_of": [
                                        {"waypoint": dropoff_place}
                                    ]
                                }
                            }
                        }
                    ]
                }
            }
        }
        
        # Create API request message
        msg = ApiRequest()
        msg.request_id = task_id
        msg.json_msg = json.dumps(task_request)
        
        self.get_logger().info(f'Dispatching task: {description}')
        self.get_logger().info(f'  Pickup: {pickup_place}')
        self.get_logger().info(f'  Dropoff: {dropoff_place}')
        
        self.task_pub.publish(msg)
        
        return task_id
        
    def dispatch_goto_task(self, level, x, y, description="Go to location"):
        """Dispatch a simple go-to task to specific coordinates on a level."""
        
        task_id = str(uuid.uuid4())
        
        task_request = {
            "type": "dispatch_task_request",
            "request": {
                "category": "compose",
                "description": {
                    "category": "patrol",
                    "phases": [
                        {
                            "activity": {
                                "category": "go_to_place",
                                "description": {
                                    "one_of": [
                                        {
                                            "map": level,
                                            "x": x,
                                            "y": y,
                                            "yaw": 0.0
                                        }
                                    ]
                                }
                            }
                        }
                    ]
                }
            }
        }
        
        msg = ApiRequest()
        msg.request_id = task_id
        msg.json_msg = json.dumps(task_request)
        
        self.get_logger().info(f'Dispatching: {description}')
        self.get_logger().info(f'  Level: {level}, Position: ({x}, {y})')
        
        self.task_pub.publish(msg)
        
        return task_id


def main():
    rclpy.init()
    
    dispatcher = MultiLevelDeliveryDispatcher()
    
    print("╔══════════════════════════════════════════════════════════════╗")
    print("║     RMF MULTI-LEVEL DELIVERY - deliveryBot_1                ║")
    print("╚══════════════════════════════════════════════════════════════╝")
    print("")
    print("This will dispatch tasks that require lift usage.")
    print("Watch noVNC to see:")
    print("  • Robot navigating to lift")
    print("  • Lift being called automatically")
    print("  • Robot entering lift")
    print("  • Lift moving between floors")
    print("  • Robot exiting on destination floor")
    print("")
    
    # Give ROS time to establish connections
    time.sleep(2)
    
    # Test 1: Navigate to Lift1 position on L1
    print("═══ Test 1: Navigate to Lift1 on L1 ═══")
    dispatcher.dispatch_goto_task("L1", 355.0, 340.0, "Approaching Lift1")
    
    # Spin to process responses
    for _ in range(10):
        rclpy.spin_once(dispatcher, timeout_sec=0.5)
    
    time.sleep(3)
    
    # Test 2: Request navigation to L2
    print("\n═══ Test 2: Navigate to L2 (should use lift) ═══")
    dispatcher.dispatch_goto_task("L2", 360.0, 340.0, "Going to L2 via Lift1")
    
    for _ in range(10):
        rclpy.spin_once(dispatcher, timeout_sec=0.5)
    
    time.sleep(3)
    
    # Test 3: Request navigation to L3
    print("\n═══ Test 3: Navigate to L3 (should use lift) ═══")
    dispatcher.dispatch_goto_task("L3", 360.0, 340.0, "Going to L3 via Lift1")
    
    for _ in range(10):
        rclpy.spin_once(dispatcher, timeout_sec=0.5)
    
    time.sleep(3)
    
    # Test 4: Return to L1
    print("\n═══ Test 4: Return to L1 ═══")
    dispatcher.dispatch_goto_task("L1", 300.0, 435.0, "Returning to L1 via Lift2")
    
    for _ in range(10):
        rclpy.spin_once(dispatcher, timeout_sec=0.5)
    
    print("\n╔══════════════════════════════════════════════════════════════╗")
    print("║         MULTI-LEVEL TASKS DISPATCHED                        ║")
    print("╚══════════════════════════════════════════════════════════════╝")
    print("")
    print(f"Total responses received: {len(dispatcher.responses)}")
    print("")
    print("Monitor noVNC to see robot movement and lift coordination!")
    print("The lift supervisor should automatically handle lift requests.")
    print("")
    
    # Keep node alive for a bit to receive more responses
    print("Monitoring for 30 seconds...")
    for _ in range(60):
        rclpy.spin_once(dispatcher, timeout_sec=0.5)
    
    dispatcher.destroy_node()
    rclpy.shutdown()


if __name__ == '__main__':
    main()
