#!/usr/bin/env python3
import rclpy
from rclpy.node import Node
from rclpy.qos import QoSProfile, ReliabilityPolicy, DurabilityPolicy, HistoryPolicy
from rmf_task_msgs.msg import ApiRequest
from rmf_fleet_msgs.msg import FleetState
import json
import time
from datetime import datetime

class FederatedDemo(Node):
    def __init__(self):
        super().__init__('federated_demo')
        
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
                    
    def dispatch_to_l3(self):
        request = ApiRequest()
        request.request_id = f'FEDERATED_TINYBOT_L1_L3_{int(time.time())}'
        
        task = {
            "type": "robot_task_request",
            "robot": "tinyBot_1",
            "fleet": "tinyRobot",
            "request": {
                "category": "patrol",
                "description": {
                    "places": ["L3_room1"],
                    "rounds": 1
                }
            }
        }
        
        request.json_msg = json.dumps(task)
        self.task_pub.publish(request)
        
        print(f"\n" + "="*70)
        print("🎬 ZENOH-FEDERATED DEMO: L1 → L3 TRANSIT")
        print("="*70)
        print(f"Task ID: {request.request_id}")
        print(f"Time: {datetime.now().strftime('%H:%M:%S')}")
        print(f"Robot: tinyBot_1")
        print(f"Fleet: tinyRobot")
        print(f"Namespace: ros2-rmf-hotel-federated")
        print(f"Architecture: Zenoh Multi-Pod")
        print("="*70)
        time.sleep(2)
        
    def monitor(self, timeout=180):
        print("\n📹 MONITORING ZENOH-FEDERATED DEMO...")
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
                
            if self.floor == 'L3':
                print(f"[{elapsed}s] ✅ ARRIVED ON L3!")
                print(f"       Position: ({self.pos[0]:.2f}, {self.pos[1]:.2f})")
                print(f"       Battery: {self.battery}%")
                print("-"*70)
                print(f"\n✅ ZENOH-FEDERATED DEMO COMPLETE!")
                print("="*70)
                print(f"Transit Time: {elapsed}s")
                print(f"Namespace: ros2-rmf-hotel-federated")
                print(f"Communication: Zenoh Router (cross-pod)")
                print(f"Architecture: Multi-Pod Federated")
                print(f"Status: SUCCESS ✅")
                print("="*70)
                return True
        
        return False

def main():
    rclpy.init()
    node = FederatedDemo()
    
    print("\n" + "="*70)
    print("  🏨 ZENOH-FEDERATED MULTI-FLOOR TRANSIT DEMO")
    print("     ros2-rmf-hotel-federated Namespace")
    print("="*70)
    
    for _ in range(10):
        rclpy.spin_once(node, timeout_sec=0.5)
        if node.floor:
            break
    
    if not node.floor:
        print("❌ Robot not available")
        rclpy.shutdown()
        return
    
    print(f"\n📍 Initial State:")
    print(f"   Robot: tinyBot_1")
    print(f"   Fleet: tinyRobot")
    print(f"   Floor: {node.floor}")
    print(f"   Battery: {node.battery}%")
    print(f"   Architecture: Zenoh-Federated")
    print(f"   Namespace: ros2-rmf-hotel-federated")
    
    print("\n🚀 Starting in 3 seconds...")
    time.sleep(3)
    
    node.dispatch_to_l3()
    success = node.monitor(timeout=180)
    
    if not success:
        print("\n⏱️  Extending timeout...")
        success = node.monitor(timeout=60)
    
    print("\n" + "="*70)
    rclpy.shutdown()

if __name__ == '__main__':
    main()
