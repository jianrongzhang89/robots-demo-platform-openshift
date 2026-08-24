# Multi-Level Navigation Exploration

**Branch:** `rmf-hotel-world-enhancements`  
**Date:** 2026-08-24  
**Status:** In Progress

## Objective

Enable deliveryBot_1 to deliver items between floors (L1, L2, L3) using hotel lifts.

## Hotel Building Configuration

### Lifts

The hotel world has **2 lifts** configured:

#### Lift1
- **Position:** (355, 340)
- **Size:** 2.7m × 2.7m
- **Levels served:** L1, L2, L3
- **Door:** lift1_door (sliding, type 2)
- **Initial floor:** L1
- **Plugins:** Enabled ✓

#### Lift2  
- **Position:** (305, 435)
- **Size:** 2.7m × 2.7m
- **Levels served:** L1, L2, L3
- **Door:** lift2_door (sliding, type 2)
- **Initial floor:** L1
- **Plugins:** Enabled ✓

### Building Levels

- **L1:** Lobby level (elevation: 0m)
- **L2:** Second floor  
- **L3:** Third floor

All levels have navigation graphs with waypoints and lanes defined.

## Current Demo Status

### ✅ What's Working

1. **Lift Supervisor Running**
   ```
   Process: /opt/rmf_ros2_ws/install/lib/rmf_fleet_adapter/lift_supervisor
   ```
   
2. **Lift Plugins Enabled**
   - Both lifts have `plugins: true` in building configuration
   - Lift doors configured with proper motion axis
   
3. **Navigation Graphs Exist**
   - All 3 levels have nav_graphs defined
   - Waypoints and lanes connect different areas

4. **Fleet Adapters Active**
   - deliveryBot fleet adapter running
   - tinyBot fleet adapter running
   - cleanerBotA fleet adapter running

### ⚠️  Current Limitations

1. **Fleet Manager HTTP API Not Accessible**
   - Ports 22011-22013 not responding
   - HTTP API might not be exposed in current configuration
   - Need to use RMF task dispatch API instead

2. **Robots Only Navigate on L1**
   - Current patrol script limited to L1 (lobby)
   - Uses direct (x,y) coordinates, not named waypoints
   - No multi-level tasks currently dispatched

3. **Lift Waypoints Not Clearly Named**
   - Navigation graph uses vertex indices, not semantic names
   - Lift entry/exit points not explicitly marked
   - Need to map vertex positions to lift locations

## Scripts Created

### 1. Multi-Level Delivery Script

**File:** `/tmp/hotel_multi_level_delivery.py`

Demonstrates delivery sequence:
1. L1 → L2 (via Lift1)
2. L2 → L3 (via Lift1)
3. L3 → L1 (via Lift2)

**Status:** Created but needs RMF task API instead of fleet HTTP API

### 2. Auto Delivery Script

**File:** `/tmp/hotel_auto_delivery.py`

Non-interactive version for automated testing.

**Status:** Connection refused - HTTP API not accessible

## Next Steps

### Phase 1: RMF Task API Integration

Instead of fleet manager HTTP API, use RMF task dispatch:

```python
import rclpy
from rmf_task_msgs.msg import TaskProfile, Delivery

# Create delivery task that spans multiple floors
task = Delivery()
task.pickup_place_name = "L1_lobby"
task.dropoff_place_name = "L2_room201"
# RMF planner will automatically use lifts
```

### Phase 2: Waypoint Mapping

Create semantic waypoint names:
- `L1_lift1_entry` - Lift1 entrance on L1
- `L2_lift1_exit` - Lift1 exit on L2
- `L3_lift1_exit` - Lift1 exit on L3
- Similar for Lift2

### Phase 3: Delivery Task Definition

Define proper delivery tasks:

```yaml
task:
  category: delivery
  pickup:
    place: L1_kitchen
    dispenser: food_dispenser
  dropoff:
    place: L3_room301
    ingestor: delivery_point
```

### Phase 4: Continuous Multi-Level Loop

Create continuous delivery loop:
- L1 (pickup) → L2 (delivery) → L1 (pickup) → L3 (delivery) → repeat

## Technical Insights

### Lift Integration Architecture

```
Robot Fleet Adapter
        ↓
   Lift Request
        ↓
  Lift Supervisor ← monitors → Lift State (Gazebo)
        ↓
   Lift Command
        ↓
  Gazebo Lift Plugin
```

The lift supervisor is already running and monitoring lift state. When a robot's path crosses a lift boundary, the fleet adapter should automatically:
1. Request lift to current floor
2. Wait for lift arrival & door open
3. Enter lift
4. Request lift to destination floor
5. Wait for arrival
6. Exit lift

### Why HTTP API Failed

The fleet manager HTTP API (ports 22011-22013) is designed for the EasyFullControl interface, which is a simplified control mode. In the federated architecture:

- **Domain separation:** Gazebo on domain 0, but HTTP might expect different domain
- **Port exposure:** Kubernetes services may not expose these ports
- **API mode:** The current demo uses full RMF task dispatch, not simplified HTTP mode

**Solution:** Use RMF task dispatch topics instead of HTTP.

## Files Modified

None yet - this is exploration phase.

## References

- Hotel building map: `/opt/rmf_demos_ws/install/share/rmf_demos_maps/hotel/hotel.building.yaml`
- Lift supervisor: Running in Gazebo pod
- RMF demos documentation: https://osrf.github.io/ros2multirobotbook/

## Conclusion

**Key Finding:** The infrastructure for multi-level navigation is already in place:
- ✅ Lifts configured
- ✅ Lift supervisor running
- ✅ Multi-level navigation graphs exist

**Blocker:** Need to use RMF task API instead of fleet manager HTTP API.

**Recommendation:** Implement Phase 1 (RMF Task API Integration) to enable actual multi-level deliveries.
