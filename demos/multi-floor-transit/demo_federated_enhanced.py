#!/usr/bin/env python3
import rclpy
from rclpy.node import Node
from rclpy.qos import QoSProfile, ReliabilityPolicy, DurabilityPolicy, HistoryPolicy
from rmf_task_msgs.msg import ApiRequest
from rmf_fleet_msgs.msg import FleetState
import json
import time
from datetime import datetime

class EnhancedFederatedDemo(Node):
    def __init__(self):
        super().__init__('enhanced_federated_demo')
        
        qos = QoSProfile(
            reliability=ReliabilityPolicy.RELIABLE,
            durability=DurabilityPolicy.TRANSIENT_LOCAL,
            history=HistoryPolicy.KEEP_LAST,
            depth=10
        )
        
        self.task_pub = self.create_publisher(ApiRequest, '/task_api_requests', qos)
        self.fleet_sub = self.create_subscription(FleetState, '/fleet_states', self.fleet_cb, 10)
        
        self.floor = None
        self.pos = None
        self.battery = None
        
    def fleet_cb(self, msg):
        if msg.name == 'tinyRobot':
            for robot in msg.robots:
                if robot.name == 'tinyBot_1':
                    self.floor = robot.location.level_name
                    self.pos = (robot.location.x, robot.location.y)
                    self.battery = robot.battery_percent
                    
    def dispatch_task(self, target_place, description=""):
        request = ApiRequest()
        request.request_id = f'FED_ENHANCED_{target_place}_{int(time.time())}'
        
        task = {
            "type": "robot_task_request",
            "robot": "tinyBot_1",
            "fleet": "tinyRobot",
            "request": {
                "category": "patrol",
                "description": {
                    "places": [target_place],
                    "rounds": 1
                }
            }
        }
        
        request.json_msg = json.dumps(task)
        self.task_pub.publish(request)
        
        print(f"\n{'='*70}")
        print(f"🎬 {description}")
        print(f"{'='*70}")
        print(f"Task ID: {request.request_id}")
        print(f"Time: {datetime.now().strftime('%H:%M:%S')}")
        print(f"Target: {target_place}")
        print(f"Architecture: Zenoh-Federated")
        print(f"{'='*70}")
        time.sleep(2)
        
    def wait_for_floor(self, target_floor, timeout=180):
        print(f"\n📹 Waiting for {target_floor}...")
        print("-"*70)
        
        start = time.time()
        last_floor = self.floor
        last_update = 0
        
        while time.time() - start < timeout:
            rclpy.spin_once(self, timeout_sec=1.0)
            elapsed = int(time.time() - start)
            
            if elapsed - last_update >= 15 and elapsed > 0:
                last_update = elapsed
                print(f"[{elapsed}s] Floor: {self.floor}")
            
            if self.floor != last_floor:
                print(f"\n[{elapsed}s] 🛗 FLOOR CHANGE: {last_floor} → {self.floor}")
                last_floor = self.floor
                
            if self.floor == target_floor:
                print(f"[{elapsed}s] ✅ ARRIVED ON {target_floor}!")
                print(f"       Position: ({self.pos[0]:.2f}, {self.pos[1]:.2f})")
                print(f"       Battery: {self.battery}%")
                print("-"*70)
                return True, elapsed
        
        return False, int(time.time() - start)
        
    def wait_for_position(self, target_x, target_y, threshold=3.0, timeout=120):
        print(f"\n📹 Navigating to ({target_x:.1f}, {target_y:.1f})...")
        print("-"*70)
        
        start = time.time()
        last_update = 0
        
        while time.time() - start < timeout:
            rclpy.spin_once(self, timeout_sec=1.0)
            elapsed = int(time.time() - start)
            
            if self.pos:
                distance = ((self.pos[0] - target_x)**2 + (self.pos[1] - target_y)**2)**0.5
                
                if elapsed - last_update >= 10 and elapsed > 0:
                    last_update = elapsed
                    print(f"[{elapsed}s] Position: ({self.pos[0]:.1f}, {self.pos[1]:.1f}), Distance: {distance:.1f}m")
                
                if distance < threshold:
                    print(f"\n[{elapsed}s] ✅ REACHED DESTINATION!")
                    print(f"       Position: ({self.pos[0]:.2f}, {self.pos[1]:.2f})")
                    print(f"       Distance: {distance:.2f}m")
                    print(f"       Battery: {self.battery}%")
                    print("-"*70)
                    return True, elapsed
        
        return False, int(time.time() - start)

def main():
    rclpy.init()
    node = EnhancedFederatedDemo()
    
    print("\n" + "="*70)
    print("  🏨 ENHANCED ZENOH-FEDERATED MULTI-FLOOR DEMO")
    print("     L1 → L3 → Navigate to Visible Walkway")
    print("="*70)
    
    # Get initial state
    print("\n📍 Initial State...")
    for _ in range(10):
        rclpy.spin_once(node, timeout_sec=0.5)
        if node.floor:
            break
    
    if not node.floor:
        print("❌ Robot not available")
        rclpy.shutdown()
        return
    
    print(f"   Robot: tinyBot_1")
    print(f"   Floor: {node.floor}")
    print(f"   Position: ({node.pos[0]:.2f}, {node.pos[1]:.2f})")
    print(f"   Battery: {node.battery}%")
    print(f"   Namespace: ros2-rmf-hotel-federated")
    print(f"   Architecture: Zenoh Multi-Pod")
    
    print("\n🚀 Starting in 3 seconds...")
    time.sleep(3)
    
    # Phase 1: Navigate to L3
    node.dispatch_task("L3_room1", "PHASE 1: Multi-Floor Transit (L1 → L3)")
    success, time1 = node.wait_for_floor("L3", timeout=180)
    
    if not success:
        print("\n⏱️  Extending timeout...")
        success, extra = node.wait_for_floor("L3", timeout=60)
        time1 += extra
    
    if not success:
        print(f"\n❌ Phase 1 failed - robot still on {node.floor}")
        rclpy.shutdown()
        return
    
    print(f"\n✅ PHASE 1 COMPLETE - Arrived on L3 in {time1}s")
    
    # Wait a moment after elevator exit
    print("\n⏸️  Waiting 5 seconds after elevator exit...")
    time.sleep(5)
    
    # Phase 2: Navigate to visible walkway on L3
    print("\n" + "="*70)
    print("PHASE 2: Navigate to Visible Walkway on L3")
    print("="*70)
    print("Target: L3_room1 (14.18, -8.29)")
    print("This location is visible in noVNC view")
    print("="*70)
    
    target_x, target_y = 14.18, -8.29
    success, time2 = node.wait_for_position(target_x, target_y, threshold=3.0, timeout=120)
    
    if not success:
        print("\n⏱️  Extending timeout for Phase 2...")
        success, extra = node.wait_for_position(target_x, target_y, threshold=3.0, timeout=60)
        time2 += extra
    
    # Final summary
    print("\n" + "="*70)
    print("✅ ENHANCED FEDERATED DEMO COMPLETE!")
    print("="*70)
    print(f"Phase 1 (L1 → L3):        {time1}s")
    print(f"Phase 2 (Navigate L3):    {time2}s")
    print(f"Total Time:               {time1 + time2}s")
    print(f"Final Position:           ({node.pos[0]:.2f}, {node.pos[1]:.2f})")
    print(f"Battery Remaining:        {node.battery}%")
    print(f"Battery Used:             {100 - node.battery:.1f}%")
    print(f"Architecture:             Zenoh Multi-Pod Federated")
    print("\n📹 Demo shows:")
    print("   1. Robot on L1")
    print("   2. Navigate to elevator")
    print("   3. Enter elevator cabin")
    print("   4. Ascend to L3 (via Zenoh communication)")
    print("   5. Exit elevator on L3")
    print("   6. Navigate to visible walkway (L3_room1)")
    print("="*70)
    
    rclpy.shutdown()

if __name__ == '__main__':
    main()
