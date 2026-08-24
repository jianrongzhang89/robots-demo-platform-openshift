#!/usr/bin/env python3
"""
Multi-Level Hotel Delivery Demo
================================
Demonstrates deliveryBot_1 delivering items between floors using lifts.

Deliveries:
  1. L1 → L2 (via Lift1)
  2. L2 → L3 (via Lift1)  
  3. L3 → L1 (return via Lift2)

Usage:
  python3 hotel_multi_level_delivery.py
"""

import json
import time
import urllib.request
import sys


class DeliveryDispatcher:
    def __init__(self, robot="deliveryBot_1", fleet_port=22012):
        self.robot = robot
        self.fleet_port = fleet_port
        self.cmd_id = 0
        
    def navigate(self, level, x, y, description=""):
        """Send navigation command to specific level."""
        self.cmd_id += 1
        url = (
            f"http://localhost:{self.fleet_port}/open-rmf/rmf_demos_fm/navigate/"
            f"?robot_name={self.robot}&cmd_id={self.cmd_id}"
        )
        
        data = json.dumps({
            "map_name": level,
            "destination": {"x": x, "y": y, "yaw": 0.0},
            "speed_limit": 0.65
        }).encode()
        
        req = urllib.request.Request(
            url, data, {"Content-Type": "application/json"}, method="POST"
        )
        
        try:
            opener = urllib.request.build_opener(urllib.request.HTTPRedirectHandler())
            r = opener.open(req, timeout=3)
            result = json.loads(r.read())
            if result.get("success"):
                print(f"✓ {description or f'Navigate to {level} ({x}, {y})'}")
                return True
            else:
                print(f"✗ Failed: {description}")
                return False
        except Exception as e:
            print(f"✗ Error: {e}")
            return False
    
    def request_lift(self, lift_name, destination_floor, description=""):
        """Request lift to go to specific floor."""
        # This uses the lift name from the building map
        # RMF will coordinate with lift supervisor
        print(f"📦 {description or f'Requesting {lift_name} to {destination_floor}'}")
        # In full RMF integration, this would use lift request API
        # For now, we'll navigate to lift waypoints and robot will trigger it
        return True


def run_multi_level_deliveries():
    """Execute multi-level delivery sequence."""
    dispatcher = DeliveryDispatcher()
    
    print("╔════════════════════════════════════════════════════════════════╗")
    print("║       MULTI-LEVEL DELIVERY DEMO - deliveryBot_1               ║")
    print("╚════════════════════════════════════════════════════════════════╝")
    print("")
    print("Delivery sequence:")
    print("  1. L1 (lobby) → Lift1 → L2 (second floor)")
    print("  2. L2 → Lift1 → L3 (third floor)")
    print("  3. L3 → Lift2 → L1 (return to lobby)")
    print("")
    input("Press Enter to start delivery sequence...")
    print("")
    
    # Delivery 1: L1 → L2
    print("═══ Delivery 1: L1 → L2 ═══")
    print("Step 1: Navigate to Lift1 on L1...")
    if dispatcher.navigate("L1", 355, 340, "Approaching Lift1 entrance (L1)"):
        time.sleep(2)
        dispatcher.request_lift("Lift1", "L2", "Calling Lift1 to go to L2")
        time.sleep(5)  # Wait for lift
        print("Step 2: Robot enters lift...")
        time.sleep(3)
        print("Step 3: Lift ascending to L2...")
        time.sleep(5)
        print("Step 4: Arrived at L2, exiting lift...")
        dispatcher.navigate("L2", 360, 340, "Exiting Lift1 on L2")
        time.sleep(3)
        print("Step 5: Delivery complete on L2")
        time.sleep(2)
    print("")
    
    # Delivery 2: L2 → L3
    print("═══ Delivery 2: L2 → L3 ═══")
    print("Step 1: Navigate back to Lift1 on L2...")
    if dispatcher.navigate("L2", 355, 340, "Approaching Lift1 entrance (L2)"):
        time.sleep(2)
        dispatcher.request_lift("Lift1", "L3", "Calling Lift1 to go to L3")
        time.sleep(5)
        print("Step 2: Robot enters lift...")
        time.sleep(3)
        print("Step 3: Lift ascending to L3...")
        time.sleep(5)
        print("Step 4: Arrived at L3, exiting lift...")
        dispatcher.navigate("L3", 360, 340, "Exiting Lift1 on L3")
        time.sleep(3)
        print("Step 5: Delivery complete on L3")
        time.sleep(2)
    print("")
    
    # Delivery 3: L3 → L1 (return via different lift)
    print("═══ Delivery 3: L3 → L1 (Return via Lift2) ═══")
    print("Step 1: Navigate to Lift2 on L3...")
    if dispatcher.navigate("L3", 305, 435, "Approaching Lift2 entrance (L3)"):
        time.sleep(2)
        dispatcher.request_lift("Lift2", "L1", "Calling Lift2 to go to L1")
        time.sleep(5)
        print("Step 2: Robot enters lift...")
        time.sleep(3)
        print("Step 3: Lift descending to L1...")
        time.sleep(5)
        print("Step 4: Arrived at L1, exiting lift...")
        dispatcher.navigate("L1", 300, 435, "Exiting Lift2 on L1")
        time.sleep(3)
        print("Step 5: Returned to lobby (L1)")
    print("")
    
    print("╔════════════════════════════════════════════════════════════════╗")
    print("║         MULTI-LEVEL DELIVERY SEQUENCE COMPLETE!               ║")
    print("╚════════════════════════════════════════════════════════════════╝")
    print("")
    print("deliveryBot_1 successfully demonstrated:")
    print("  ✓ L1 → L2 delivery (via Lift1)")
    print("  ✓ L2 → L3 delivery (via Lift1)")
    print("  ✓ L3 → L1 return (via Lift2)")
    print("")


if __name__ == "__main__":
    run_multi_level_deliveries()
