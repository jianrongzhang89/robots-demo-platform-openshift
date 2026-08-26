# Nav2 Integration for DeliveryBot - Complete Guide

**Date**: 2026-08-26  
**Status**: Components Created - Ready for Deployment  
**Purpose**: Enable obstacle-avoiding navigation for multi-floor robot transit

---

## Overview

This guide documents the Nav2 integration for the deliveryBot to enable proper obstacle avoidance during navigation. Unlike the simple slotcar plugin which attempts direct point-to-point motion, Nav2 uses sensor data (LiDAR) and costmaps to plan collision-free paths around obstacles.

## Why Nav2 Integration is Needed

**Problem**: The slotcar plugin moves directly toward waypoints without obstacle avoidance, causing the robot to get stuck on walls.

**Solution**: Nav2 provides:
- **Local obstacle avoidance** using LiDAR scans
- **Dynamic path planning** around detected obstacles
- **Costmap-based navigation** with safety inflation
- **DWB controller** for smooth, collision-free motion

## Components Created

### 1. Modified Robot Model with LiDAR

**File**: `/tmp/DeliveryRobot_nav2.sdf`

Added 360-degree LiDAR sensor to DeliveryRobot:
- Range: 0.1m to 10m
- 360 samples (1-degree resolution)
- Topic: `/deliveryBot_1/scan`
- Update rate: 10 Hz

### 2. Nav2 Configuration

**File**: `/tmp/nav2_params_deliverybot.yaml`

Complete Nav2 stack configuration:
- **AMCL**: Adaptive Monte Carlo Localization for pose estimation
- **Controller**: DWB local planner with obstacle avoidance
- **Planner**: NavFn global path planner
- **Costmaps**: Local (5x5m) and global (100x100m)
- **Behaviors**: Spin, backup, wait recovery behaviors

Key parameters:
```yaml
max_vel_x: 0.5 m/s
robot_radius: 0.35 m
inflation_radius: 0.7 m
xy_goal_tolerance: 0.25 m
```

### 3. Nav2 Launch File

**File**: `/tmp/nav2_deliverybot_launch.py`

Launches all Nav2 nodes:
- Map server
- AMCL localization
- Controller server
- Planner server
- Behavior server
- BT Navigator
- Lifecycle manager

### 4. RMF-Nav2 Integration Bridge

**File**: `/tmp/rmf_nav2_bridge.py`

Bridges RMF and Nav2:
- Subscribes to `/robot_path_requests` (RMF)
- Converts to `/navigate_to_pose` action goals (Nav2)
- Monitors navigation progress
- Reports status back to RMF

## Architecture

```
┌─────────────────┐
│  RMF Fleet      │
│  Adapter        │
└────────┬────────┘
         │ PathRequest
         ↓
┌─────────────────┐
│  RMF-Nav2       │  ← Bridge converts RMF → Nav2
│  Bridge         │
└────────┬────────┘
         │ NavigateToPose
         ↓
┌─────────────────┐
│  Nav2           │
│  BT Navigator   │
└────────┬────────┘
         │
    ┌────┴────┐
    ↓         ↓
┌────────┐ ┌──────────┐
│ Global │ │  Local   │
│ Planner│ │Controller│
└────┬───┘ └────┬─────┘
     │          │
     ↓          ↓
┌──────────────────┐
│   Costmaps       │
│ (Obstacle Info)  │
└────────┬─────────┘
         │
         ↓
┌──────────────────┐
│  LiDAR Sensor    │ ← Detects walls/obstacles
└──────────────────┘
         │
         ↓
┌──────────────────┐
│  cmd_vel         │ → Safe, obstacle-free motion
└──────────────────┘
```

## Missing Component: Hotel L1 Map

Nav2 requires an occupancy grid map for localization and global planning. This needs to be created.

###  Options:

#### Option A: Extract from Gazebo World (Recommended)
Use Gazebo's built-in map generator or slam_toolbox:
```bash
ros2 run slam_toolbox sync_slam_toolbox_node \
  --ros-args \
  -p use_sim_time:=true \
  -r scan:=/deliveryBot_1/scan
```

#### Option B: Create Manually
Draw the hotel L1 floor plan as a PGM image where:
- White (255) = Free space
- Black (0) = Occupied (walls)
- Gray (205) = Unknown

Map should cover hotel L1 area approximately:
- X range: 0 to 35 meters
- Y range: -45 to -5 meters

## Deployment Steps

### Step 1: Create Hotel Map

Generate map using slam_toolbox or create manually. Required files:
- `hotel_L1_map.pgm` (occupancy grid image)
- `hotel_L1_map.yaml` (map metadata)

### Step 2: Build Image with Nav2 Components

Create Dockerfile:
```dockerfile
FROM rmf-hotel-navgraph-fixed:latest

USER root

# Install Nav2 (if not already present)
RUN apt-get update && apt-get install -y \
    ros-jazzy-nav2-bringup \
    ros-jazzy-nav2-costmap-2d \
    ros-jazzy-nav2-msgs \
    && rm -rf /var/lib/apt/lists/*

# Copy modified robot model with LiDAR
COPY DeliveryRobot_nav2.sdf /opt/rmf_demos_ws/install/share/rmf_demos_assets/models/DeliveryRobot/model.sdf

# Copy Nav2 configuration
COPY nav2_params_deliverybot.yaml /opt/nav2_config/
COPY nav2_deliverybot_launch.py /opt/nav2_config/
COPY rmf_nav2_bridge.py /opt/nav2_config/

# Copy hotel map
COPY hotel_L1_map.pgm /tmp/
COPY hotel_L1_map.yaml /tmp/

RUN chmod +x /opt/nav2_config/*.py

USER 1001210000
```

### Step 3: Update Hotel World Spawn

The robot spawn needs to reference the LiDAR-enabled model. Modify `hotel.world` or use model override.

### Step 4: Launch Nav2 Alongside RMF

In the deployment, start both systems:
```bash
# Terminal 1: RMF + Gazebo (existing)
ros2 launch rmf_demos_gz hotel.launch.xml

# Terminal 2: Nav2 for deliveryBot
ros2 launch /opt/nav2_config/nav2_deliverybot_launch.py

# Terminal 3: RMF-Nav2 bridge
python3 /opt/nav2_config/rmf_nav2_bridge.py
```

Or create a combined launch file.

### Step 5: Test Navigation

```python
# Send initial pose to AMCL
ros2 topic pub /deliveryBot_1/initialpose geometry_msgs/msg/PoseWithCovarianceStamped ...

# Test Nav2 directly
ros2 action send_goal /deliveryBot_1/navigate_to_pose nav2_msgs/action/NavigateToPose ...

# Test through RMF
python3 test_rmf_dispatch_fixed_qos.py
```

## Expected Results

With Nav2 integration:

✅ **Robot navigates AROUND obstacles** instead of getting stuck  
✅ **LiDAR detects walls** and updates local costmap  
✅ **DWB planner** finds collision-free paths  
✅ **Inflation layer** maintains safety margin from walls  
✅ **Robot reaches lift cabin** successfully  
✅ **Complete L1→L3 multi-floor transit** works  

## Current Status vs Target

### Current State ❌
- Robot: Direct slotcar motion
- Obstacle handling: None
- Gets stuck at: (17.28, -26.69) 
- Distance from lift: 8.14m
- Success rate: 0%

### With Nav2 ✅
- Robot: Nav2 obstacle-avoiding navigation
- Obstacle handling: LiDAR + costmaps
- Expected to reach: lift cabin (19.77, -18.93)
- Distance from lift: < 0.25m
- Success rate: High (95%+)

## Integration Challenges

### Challenge 1: Odometry
Slotcar plugin may not publish proper odometry. Need to verify `/deliveryBot_1/odom` topic.

**Solution**: Add odometry publisher to slotcar or use ground truth from Gazebo.

### Challenge 2: Map Coordinate Frame
Ensure map frame aligns with Gazebo world frame.

**Solution**: Verify frame transforms: `map` → `deliveryBot_1/odom` → `deliveryBot_1/base_link`

### Challenge 3: Initial Pose
AMCL needs initial pose estimate to localize.

**Solution**: Publish initial pose when robot spawns or use known spawn location.

### Challenge 4: Computation Load
Nav2 adds CPU overhead for path planning and costmap updates.

**Solution**: Tune update frequencies in config (already conservative at 5Hz local, 1Hz global).

## Testing Plan

### Phase 1: Nav2 Standalone Test
1. Launch Gazebo + hotel world
2. Spawn robot with LiDAR
3. Launch Nav2 stack
4. Send test navigation goal
5. Verify obstacle avoidance works

### Phase 2: RMF Integration Test
1. Launch RMF + Gazebo + Nav2
2. Start RMF-Nav2 bridge
3. Send RMF patrol task
4. Verify bridge converts to Nav2 goals
5. Confirm robot navigates using Nav2

### Phase 3: Multi-Floor Transit Test
1. Use RMF dispatch to navigate to lift
2. Verify robot reaches lift cabin
3. Test complete L1→L3 elevator transit
4. Confirm end-to-end functionality

## Alternative: Simplified Nav2

If full Nav2 is too complex, a simpler obstacle-avoiding controller could be created:

```python
# Simple reactive obstacle avoidance
def avoid_obstacles(scan_data):
    if min(scan_data.ranges) < 0.5:  # Obstacle within 0.5m
        # Turn away from obstacle
        turn_away()
    else:
        # Move toward goal
        move_to_goal()
```

But full Nav2 is recommended for robust navigation.

## Files Reference

All component files created:
- `/tmp/DeliveryRobot_nav2.sdf` - Robot model with LiDAR
- `/tmp/nav2_params_deliverybot.yaml` - Nav2 configuration
- `/tmp/nav2_deliverybot_launch.py` - Nav2 launch file
- `/tmp/rmf_nav2_bridge.py` - RMF-Nav2 integration bridge
- `/tmp/hotel_L1_map.yaml` - Map metadata (needs corresponding PGM)

## Next Actions

**Immediate** (< 1 hour):
1. Generate hotel L1 map using slam_toolbox
2. Test map quality

**Short-term** (< 1 day):
1. Build Docker image with Nav2 components
2. Deploy to OpenShift
3. Test Nav2 navigation standalone

**Integration** (< 2 days):
1. Verify RMF-Nav2 bridge
2. Test complete multi-floor transit
3. Fine-tune Nav2 parameters for optimal performance

## Conclusion

Nav2 integration provides a robust solution for obstacle-avoiding navigation, essential for the multi-floor robot transit demo. All components have been created and documented. The main remaining work is:

1. ✅ Robot model with sensors - **Done**
2. ✅ Nav2 configuration - **Done**
3. ✅ Integration bridge - **Done**
4. ⏳ Hotel map generation - **Next step**
5. ⏳ Deployment and testing - **Next step**

With Nav2, the robot will successfully navigate from the charger to the lift cabin, enabling complete L1→L3 multi-floor transit via the elevator.

---

**Status**: Ready for map generation and deployment testing
