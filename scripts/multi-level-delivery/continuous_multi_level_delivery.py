#!/usr/bin/env python3
"""
Continuous Multi-Level Delivery Loop
====================================
Demonstrates deliveryBot_1 continuously delivering between floors.

Delivery Pattern:
  1. L1 (lobby/kitchen) → L2 (room 201)
  2. L2 (room 201) → L3 (room 301)
  3. L3 (room 301) → L1 (lobby) 
  4. Repeat indefinitely

This showcases:
  - Automatic lift coordination by RMF
  - Multi-level navigation
  - Continuous operation
"""

import rclpy
from rclpy.node import Node
from rmf_task_msgs.msg import ApiRequest
from rmf_lift_msgs.msg import LiftState
import json
import uuid
import time


class ContinuousMultiLevelDelivery(Node):
    def __init__(self):
        super().__init__('continuous_multi_level_delivery')
        
        self.task_pub = self.create_publisher(
            ApiRequest,
            '/task_api_requests',
            10
        )
        
        # Monitor lift states
        self.lift_sub = self.create_subscription(
            LiftState,
            '/lift_states',
            self.lift_state_callback,
            10
        )
        
        self.lift_states = {}
        self.cycle_count = 0
        
        self.get_logger().info('Continuous multi-level delivery initialized')
        
    def lift_state_callback(self, msg):
        """Monitor lift positions."""
        self.lift_states[msg.lift_name] = {
            'floor': msg.current_floor,
            'door': msg.door_state,
            'motion': msg.motion_state
        }
        
    def dispatch_goto(self, level, x, y, description=""):
        """Dispatch go-to task for specific level and coordinates."""
        task_id = str(uuid.uuid4())
        
        task = {
            "type": "dispatch_task_request",
            "request": {
                "category": "compose",
                "description": {
                    "category": "delivery_pickup",
                    "phases": [{
                        "activity": {
                            "category": "go_to_place",
                            "description": {
                                "one_of": [{
                                    "map": level,
                                    "x": x,
                                    "y": y,
                                    "yaw": 0.0
                                }]
                            }
                        }
                    }]
                }
            }
        }
        
        msg = ApiRequest()
        msg.request_id = task_id
        msg.json_msg = json.dumps(task)
        
        self.task_pub.publish(msg)
        self.get_logger().info(f'{description} - Task ID: {task_id[:8]}...')
        
    def run_delivery_cycle(self):
        """Execute one complete delivery cycle across all floors."""
        self.cycle_count += 1
        
        print(f"\n{'='*60}")
        print(f"  DELIVERY CYCLE #{self.cycle_count}")
        print(f"{'='*60}\n")
        
        # Delivery 1: L1 → L2
        print("📦 Delivery 1: L1 (Lobby/Kitchen) → L2 (Room 201)")
        print("   └─ Robot will use Lift1 to reach L2")
        self.dispatch_goto("L1", 355.0, 340.0, "  Step 1: Approaching Lift1 on L1")
        time.sleep(5)
        self.dispatch_goto("L2", 360.0, 345.0, "  Step 2: Delivering to L2")
        time.sleep(15)  # Allow time for lift + delivery
        
        # Delivery 2: L2 → L3
        print("\n📦 Delivery 2: L2 (Room 201) → L3 (Room 301)")
        print("   └─ Robot will use Lift1 to reach L3")
        self.dispatch_goto("L2", 355.0, 340.0, "  Step 1: Returning to Lift1 on L2")
        time.sleep(5)
        self.dispatch_goto("L3", 360.0, 345.0, "  Step 2: Delivering to L3")
        time.sleep(15)
        
        # Delivery 3: L3 → L1 (return)
        print("\n📦 Delivery 3: L3 (Room 301) → L1 (Lobby) [Return]")
        print("   └─ Robot will use Lift2 to return to L1")
        self.dispatch_goto("L3", 305.0, 435.0, "  Step 1: Approaching Lift2 on L3")
        time.sleep(5)
        self.dispatch_goto("L1", 300.0, 430.0, "  Step 2: Returning to lobby")
        time.sleep(15)
        
        print(f"\n✓ Cycle #{self.cycle_count} complete!")
        print(f"  Lift states: {self.lift_states}")
        print("")


def main():
    rclpy.init()
    
    delivery = ContinuousMultiLevelDelivery()
    
    print("╔══════════════════════════════════════════════════════════════╗")
    print("║   CONTINUOUS MULTI-LEVEL DELIVERY DEMONSTRATION              ║")
    print("╚══════════════════════════════════════════════════════════════╝")
    print("")
    print("Robot: deliveryBot_1")
    print("Delivery Pattern:")
    print("  • L1 (Lobby) → L2 (Floor 2) via Lift1")
    print("  • L2 (Floor 2) → L3 (Floor 3) via Lift1")
    print("  • L3 (Floor 3) → L1 (Lobby) via Lift2")
    print("  • Repeat...")
    print("")
    print("Watch in noVNC:")
    print("  • Robot navigation")
    print("  • Automatic lift calls")
    print("  • Lift door operations")
    print("  • Floor changes")
    print("")
    print("Press Ctrl+C to stop")
    print("")
    
    # Allow time for connections
    time.sleep(2)
    
    try:
        # Run 3 complete cycles as demonstration
        for cycle in range(3):
            delivery.run_delivery_cycle()
            
            # Spin to process lift state updates
            for _ in range(10):
                rclpy.spin_once(delivery, timeout_sec=0.5)
            
            if cycle < 2:  # Don't wait after last cycle
                print(f"Waiting 10 seconds before next cycle...\n")
                time.sleep(10)
        
        print("\n╔══════════════════════════════════════════════════════════════╗")
        print("║         DEMONSTRATION COMPLETE                               ║")
        print("╚══════════════════════════════════════════════════════════════╝")
        print(f"\nCompleted {delivery.cycle_count} delivery cycles")
        print("Each cycle demonstrated multi-level navigation with lifts.")
        print("")
        
    except KeyboardInterrupt:
        print("\n\nStopped by user")
        
    delivery.destroy_node()
    rclpy.shutdown()


if __name__ == '__main__':
    main()
