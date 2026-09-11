# TurtleBot3 Hotel World Integration - Technical Documentation

**Status:** ✅ Working (Build #24)  
**Date:** 2026-09-11  
**Objective:** Enable TurtleBot3 Waffle robot to move in Open-RMF hotel world simulation using Gazebo Harmonic DiffDrive plugin

---

## Overview

This document describes the successful integration of a TurtleBot3 Waffle robot into the Open-RMF hotel world demo, including all technical challenges encountered and their solutions. The robot is controlled via the Gazebo Harmonic `gz-sim-diff-drive-system` plugin and can be commanded through ROS2 topics.

### Key Components

- **Simulation:** Gazebo Harmonic (gz-sim 8.x)
- **Robot:** TurtleBot3 Waffle (differential drive, pre-spawned in world file)
- **Physics:** ODE physics engine
- **Control Plugin:** gz-sim-diff-drive-system
- **Bridge:** ros_gz_bridge (Gazebo Transport ↔ ROS2)
- **ROS2 Distro:** Jazzy
- **Deployment:** OpenShift multi-pod architecture

---

## Final Working Configuration

### Robot Specifications

**Physical Properties:**
- Base size: 0.84m × 0.93m × 0.42m (3x scaled from original 0.28m for visibility)
- Wheel radius: 0.10m (scaled)
- Wheel separation: 0.288m
- Color: Bright red (`<ambient>1.0 0.0 0.0 1</ambient>`)
- Spawn position: (10, 30, 0.1) in hotel world coordinates

**Joint Configuration:**
```xml
<joint name="left_wheel_joint" type="revolute">
  <parent>base_link</parent>
  <child>wheel_left_link</child>
  <axis>
    <xyz>0 0 1</xyz>
    <limit>
      <lower>-1e16</lower>
      <upper>1e16</upper>
      <effort>1000</effort>
      <velocity>1000</velocity>
    </limit>
    <dynamics><friction>0.1</friction></dynamics>
  </axis>
</joint>
```

**Critical:** Joints are `type="revolute"` with extremely large limits (-1e16 to +1e16) to simulate continuous rotation. This works around a Gazebo Harmonic bug where `type="continuous"` joints have 0 DOF.

### DiffDrive Plugin Configuration

```xml
<plugin filename="gz-sim-diff-drive-system" name="gz::sim::systems::DiffDrive">
  <left_joint>left_wheel_joint</left_joint>
  <right_joint>right_wheel_joint</right_joint>
  <wheel_separation>0.288</wheel_separation>
  <wheel_radius>0.10</wheel_radius>
  <odom_publish_frequency>50</odom_publish_frequency>
  <topic>/robot_1/cmd_vel</topic>
  <odom_topic>/robot_1/odom</odom_topic>
  <frame_id>odom</frame_id>
  <child_frame_id>base_footprint</child_frame_id>
  <tf_topic>/robot_1/tf</tf_topic>
</plugin>
```

**Critical:** All topic names must be absolute paths (starting with `/`) for correct Gazebo Transport topic creation.

### ros_gz_bridge Configuration

```bash
ros2 run ros_gz_bridge parameter_bridge \
  /robot_1/cmd_vel@geometry_msgs/msg/Twist]gz.msgs.Twist \
  /robot_1/odometry@nav_msgs/msg/Odometry[gz.msgs.Odometry \
  --ros-args \
  -r /robot_1/odometry:=/robot_1/odom
```

**Critical:** Bridge topics must match the DiffDrive plugin's topic names exactly:
- DiffDrive subscribes to: `/robot_1/cmd_vel` (Gazebo Transport)
- DiffDrive publishes to: `/robot_1/odom` (Gazebo Transport)
- Bridge maps these to ROS2 with same names

### Environment Configuration

**Critical addition to entrypoint-hotel.sh:**
```bash
export GZ_SIM_SYSTEM_PLUGIN_PATH="${GZ_SIM_SYSTEM_PLUGIN_PATH}:/opt/ros/jazzy/opt/gz_sim_vendor/lib/gz-sim-8/plugins"
```

Without this, the DiffDrive plugin `.so` file cannot be found by Gazebo even though it's installed.

---

## Issues Encountered and Solutions

### Bug #1: DiffDrive Plugin Parameters Mismatch (Build #15-16)
**Problem:** Robot scaled 3x (0.28m → 0.84m) but DiffDrive plugin still had original wheel_radius=0.033m  
**Solution:** Created `patch_robot1_diffdrive_params.py` to update wheel_radius to 0.10m and wheel_separation to 0.288m  
**File:** `scripts/patch_robot1_diffdrive_params.py`

### Bug #2: Missing Joint Effort/Velocity Limits (Build #16)
**Problem:** Wheel joints had no effort or velocity limits; physics engine didn't know how much force to apply  
**Solution:** Added `<limit><effort>1000</effort><velocity>1000</velocity></limit>` to joint definitions in `patch_hotel_world_add_robot.py`  

### Bug #3: Robot Position (Build #16-17)
**Problem:** Robot spawned at positive Y coordinates, but cleaner robots are at negative Y  
**Solution:** Created `patch_robot1_position_negative_y.py` to move robot to (20, -30, 0.1)  
**Note:** Later changed to (10, 30, 0.1) for better visibility  
**File:** `scripts/patch_robot1_position_negative_y.py`

### Bug #4: Joints Forced to Revolute Type Incorrectly (Build #18)
**Problem:** `patch_robot1_bullet_joints.py` was forcing joints from continuous → revolute with small limits  
**Solution:** Removed the Bullet joints patch from Containerfile  
**Note:** Eventually kept revolute type but with huge limits (-1e16 to +1e16)

### Bug #5: DiffDrive Topics Not Namespaced (Build #19)
**Problem:** DiffDrive using relative topic names (cmd_vel, odometry) instead of absolute ROS2 paths  
**Solution:** Changed `<topic>cmd_vel</topic>` → `<topic>/robot_1/cmd_vel</topic>` in DiffDrive plugin config  
**Result:** Enabled proper Gazebo Transport topic creation

### Bug #6: Missing ros_gz_bridge (Build #20)
**Problem:** DiffDrive publishes to Gazebo Transport, not ROS2 directly; no bridge between them  
**Solution:** Added ros_gz_bridge in entrypoint-hotel.sh to bridge Gazebo ↔ ROS2  
**File:** `entrypoints/entrypoint-hotel.sh:233-242`

### Bug #7: Continuous Joints with Limit Tags = 0 DOF (Build #21)
**Problem:** Continuous joints with `<limit>` tags create 0 DOF in Gazebo Harmonic  
**Solution:** Removed `<limit>` tags from continuous joints  
**Note:** This didn't work; still got 0 DOF warnings

### Bug #8: Physics Engine Bug - Continuous Joints = 0 DOF (Build #22)
**Problem:** Even without limit tags, continuous joints still created 0 DOF in ODE/DART/Bullet  
**Root Cause:** Known Gazebo Harmonic bug where continuous joints don't work properly  
**Solution:** Workaround - changed to `type="revolute"` with huge limits (-1e16 to +1e16) to simulate continuous rotation  
**Result:** Joints now have DOF=1, no warnings

### Bug #9: Wrong Bridge Topic Mapping (Build #23)
**Problem:** ros_gz_bridge was listening to wrong Gazebo topics  
```
DiffDrive subscribes to:  /robot_1/cmd_vel (Gazebo Transport)
Bridge was listening to:  /model/robot_1/cmd_vel ❌
```
**Solution:** Fixed bridge configuration to use correct topics:
```bash
# BEFORE (wrong):
/model/robot_1/cmd_vel -> remap to /robot_1/cmd_vel

# AFTER (correct):
/robot_1/cmd_vel -> /robot_1/cmd_vel (direct bridge)
/robot_1/odometry -> /robot_1/odom (direct bridge)
```
**File:** `entrypoints/entrypoint-hotel.sh:233-242`

### Bug #10: DiffDrive Plugin Path Missing (Build #24) ✅ FINAL FIX
**Problem:** DiffDrive plugin exists but Gazebo couldn't find it  
```
Plugin .so file exists at:
  /opt/ros/jazzy/opt/gz_sim_vendor/lib/gz-sim-8/plugins/libgz-sim-diff-drive-system.so

But GZ_SIM_SYSTEM_PLUGIN_PATH only had:
  /opt/ros/jazzy/lib/rmf_robot_sim_gz_plugins/
  /opt/ros/jazzy/lib/rmf_building_sim_gz_plugins/
```
**Solution:** Added vendor plugin path to environment in entrypoint-hotel.sh:
```bash
export GZ_SIM_SYSTEM_PLUGIN_PATH="${GZ_SIM_SYSTEM_PLUGIN_PATH}:/opt/ros/jazzy/opt/gz_sim_vendor/lib/gz-sim-8/plugins"
```
**Result:** Plugin now loads successfully and robot moves!  
**File:** `entrypoints/entrypoint-hotel.sh:68-71`

---

## Build Pipeline

### Containerfile Structure
File: `Containerfile.hotel-nav2-v3`

**Base Image:** `quay.io/jianrzha/ros2-rmf-hotel:latest`

**Applied Patches (in order):**
1. `patch_hotel_world.py` - Add Sensors system for gpu_lidar
2. `patch_hotel_world_complete.py` - Remove GUI plugins (RCL crash fix), add ground plane
3. `patch_physics_to_ode.py` - Ensure ODE physics (better joint support than Bullet)
4. `patch_hotel_world_add_robot.py` - Pre-spawn TurtleBot3 robot in world file
5. `patch_robot1_remove_static.py` - Remove static tag (allows physics movement)
6. `patch_robot1_scale_3x.py` - Scale robot 3x and make bright red
7. `patch_robot1_position_negative_y.py` - Position robot at (20, -30) initially
8. `patch_robot1_diffdrive_params.py` - Update wheel_radius and wheel_separation

**Runtime Configuration:**
- `entrypoint-hotel.sh` - Sets `GZ_SIM_SYSTEM_PLUGIN_PATH`, starts ros_gz_bridge with correct topics

### Build Command
```bash
oc start-build hotel-nav2-v3-fixed -n ros2-rmf-hotel-test --from-dir=. --follow
```

### Deployment
```bash
# Get new image reference
NEW_IMAGE=$(oc get build hotel-nav2-v3-fixed-24 -n ros2-rmf-hotel-test -o jsonpath='{.status.outputDockerImageReference}')

# Update deployment
oc set image deployment/hotel-sim -n ros2-rmf-hotel-test hotel=$NEW_IMAGE

# Delete pod to force recreation
oc delete pod -l app=hotel-sim -n ros2-rmf-hotel-test --grace-period=5
```

---

## Testing and Verification

### Check Plugin Loading
```bash
POD=$(oc get pods -n ros2-rmf-hotel-test -l app=hotel-sim -o jsonpath='{.items[0].metadata.name}')

# Check DiffDrive subscription message
oc logs -n ros2-rmf-hotel-test $POD -c hotel | grep -i "diffdrive"
# Expected: "[Msg] DiffDrive subscribing to twist messages on [/robot_1/cmd_vel]"

# Check if plugin .so file is accessible
oc exec -n ros2-rmf-hotel-test $POD -c hotel -- bash -c "
  ls -la /opt/ros/jazzy/opt/gz_sim_vendor/lib/gz-sim-8/plugins/libgz-sim-diff-drive-system.so
"
```

### Test Robot Movement (Gazebo Transport)
```bash
oc exec -n ros2-rmf-hotel-test $POD -c hotel -- bash -c "
  export HOME=/tmp
  source /opt/ros/jazzy/setup.bash
  
  # Send command via Gazebo Transport
  /opt/ros/jazzy/opt/gz_tools_vendor/bin/gz topic \
    -t /robot_1/cmd_vel \
    -m gz.msgs.Twist \
    -p 'linear: {x: 2.0}'
  
  # Check odometry (should show movement)
  timeout 3 /opt/ros/jazzy/opt/gz_tools_vendor/bin/gz topic \
    -e -t /robot_1/odom -n 1
"
```

### Test Robot Movement (ROS2)
```bash
oc exec -n ros2-rmf-hotel-test $POD -c hotel -- bash -c "
  export HOME=/tmp
  source /opt/ros/jazzy/setup.bash
  export ROS_DOMAIN_ID=0
  
  # Drive forward at 1.5 m/s
  ros2 topic pub /robot_1/cmd_vel geometry_msgs/msg/Twist \
    '{linear: {x: 1.5}, angular: {z: 0.0}}' --rate 10
  
  # In another terminal, check odometry
  ros2 topic echo /robot_1/odom --once
"
```

### Expected Results
- DiffDrive plugin loads without errors
- `/robot_1/cmd_vel` topic exists on both Gazebo Transport and ROS2
- `/robot_1/odom` topic publishes at 50 Hz
- Robot position in odometry changes when commands are sent
- No "DOF=0" warnings in logs
- ros_gz_bridge shows 2 publishers on `/robot_1/odom` (one RELIABLE, one BEST_EFFORT)

---

## Control Commands

### Basic Movement
```bash
# Forward
ros2 topic pub /robot_1/cmd_vel geometry_msgs/msg/Twist '{linear: {x: 1.5}}' --rate 10

# Backward
ros2 topic pub /robot_1/cmd_vel geometry_msgs/msg/Twist '{linear: {x: -1.0}}' --rate 10

# Rotate (turn in place)
ros2 topic pub /robot_1/cmd_vel geometry_msgs/msg/Twist '{angular: {z: 1.0}}' --rate 10

# Circle pattern
ros2 topic pub /robot_1/cmd_vel geometry_msgs/msg/Twist '{linear: {x: 1.5}, angular: {z: 0.5}}' --rate 10

# Stop
ros2 topic pub /robot_1/cmd_vel geometry_msgs/msg/Twist '{linear: {x: 0.0}, angular: {z: 0.0}}' --once
```

### Check Robot Status
```bash
# Current position
ros2 topic echo /robot_1/odom --once

# Topic info
ros2 topic info /robot_1/odom -v

# Publishing rate
ros2 topic hz /robot_1/odom
```

---

## Viewing the Simulation

### noVNC Access
```bash
# Get noVNC URL
ROUTE_HOST=$(oc get route hotel-novnc -n ros2-rmf-hotel-test -o jsonpath='{.spec.host}')
echo "https://${ROUTE_HOST}/vnc.html"
```

**Default URL:** https://hotel-novnc-ros2-rmf-hotel-test.apps.ai-dev02.kni.syseng.devcluster.openshift.com/vnc.html

### Camera Navigation in Gazebo
- Use mouse to rotate camera (click + drag)
- Scroll to zoom in/out
- Look for the **large RED box** - that's the TurtleBot3 robot
- Default spawn: (10, 30, 0.1) in hotel lobby area

---

## Architecture Details

### Topic Flow

```
ROS2 Client                    ros_gz_bridge              Gazebo Transport
    |                                |                            |
    |--/robot_1/cmd_vel (ROS2)----->|                            |
    |                                |--/robot_1/cmd_vel (gz)--->|
    |                                |                            |----> DiffDrive Plugin
    |                                |                            |
    |                                |<--/robot_1/odom (gz)-------|<---- DiffDrive Plugin
    |<--/robot_1/odom (ROS2)---------|                            |
    |                                |                            |
```

### ROS2 Topics
- `/robot_1/cmd_vel` (geometry_msgs/msg/Twist) - Velocity commands
- `/robot_1/odom` (nav_msgs/msg/Odometry) - Robot odometry
- `/robot_1/tf` (tf2_msgs/msg/TFMessage) - Transform tree
- `/robot_1/scan` (sensor_msgs/msg/LaserScan) - LiDAR data
- `/robot_1/imu` (sensor_msgs/msg/Imu) - IMU data
- `/robot_1/joint_states` (sensor_msgs/msg/JointState) - Joint positions/velocities

### Gazebo Transport Topics
- `/robot_1/cmd_vel` (gz.msgs.Twist) - DiffDrive command input
- `/robot_1/odom` (gz.msgs.Odometry) - DiffDrive odometry output
- `/model/robot_1/cmd_vel` (gz.msgs.Twist) - Model-level topic (not used)
- `/model/robot_1/odometry` (gz.msgs.Odometry) - Model-level topic (not used)

**Note:** DiffDrive plugin uses `/robot_1/*` namespace, NOT `/model/robot_1/*`.

---

## Known Limitations

1. **Physics Engine:** Currently using ODE. Bullet-Featherstone and DART both have issues with joint DOF.

2. **Joint Type:** Revolute joints with huge limits instead of continuous. This is a workaround for Gazebo Harmonic bug.

3. **ROS2 Odometry QoS:** Bridge publishes both RELIABLE and BEST_EFFORT QoS profiles. ROS2 clients must handle BEST_EFFORT for proper subscription.

4. **Robot Size:** Robot is 3x scaled (0.84m) for visibility. Nav2 integration will need to account for this size in costmaps.

5. **Pre-spawning Required:** Robot must be pre-spawned in world file. Dynamic spawning via `/world/{name}/create` service creates joints with 0 DOF (Gazebo Harmonic bug).

---

## Next Steps

### Immediate
- [ ] Verify robot visibility in noVNC with user
- [ ] Test circle/patrol patterns for demo
- [ ] Document spawn position best practices

### Short Term
- [ ] Integrate with Nav2 for autonomous navigation
- [ ] Add localization (AMCL or slam_toolbox)
- [ ] Create map of hotel world for Nav2
- [ ] Test multi-floor navigation with lifts

### Long Term
- [ ] Integrate with RMF fleet adapter for task dispatch
- [ ] Add collision avoidance with cleaner robots
- [ ] Test Zenoh federation for multi-pod Nav2
- [ ] Performance tuning (reduce resource usage)

---

## Troubleshooting

### Robot Not Moving

**Check 1: Is DiffDrive plugin loaded?**
```bash
oc logs $POD -c hotel | grep -i "diffdrive"
# Should see: "DiffDrive subscribing to twist messages on [/robot_1/cmd_vel]"
```

**Check 2: Is plugin path set correctly?**
```bash
oc exec $POD -c hotel -- bash -c "
  source /opt/ros/jazzy/setup.bash
  echo \$GZ_SIM_SYSTEM_PLUGIN_PATH
"
# Should include: /opt/ros/jazzy/opt/gz_sim_vendor/lib/gz-sim-8/plugins
```

**Check 3: Are bridge topics correct?**
```bash
oc exec $POD -c hotel -- bash -c "
  ps aux | grep ros_gz_bridge | grep robot_1
"
# Should show: /robot_1/cmd_vel and /robot_1/odometry (NOT /model/robot_1/*)
```

**Check 4: Do joints have DOF=1?**
```bash
oc logs $POD -c hotel | grep -i "DOF"
# Should NOT see any "joint has 0 while component has 1" warnings
```

### Odometry Not Publishing

**Check 1: Topic exists on Gazebo Transport**
```bash
oc exec $POD -c hotel -- bash -c "
  /opt/ros/jazzy/opt/gz_tools_vendor/bin/gz topic -l | grep robot_1
"
# Should include: /robot_1/odom
```

**Check 2: Bridge creating publishers**
```bash
oc exec $POD -c hotel -- bash -c "
  source /opt/ros/jazzy/setup.bash
  export ROS_DOMAIN_ID=0
  ros2 topic info /robot_1/odom
"
# Should show: Publisher count: 2
```

**Check 3: Test with Gazebo Transport directly**
```bash
oc exec $POD -c hotel -- bash -c "
  /opt/ros/jazzy/opt/gz_tools_vendor/bin/gz topic -e -t /robot_1/odom -n 1
"
# Should show position/velocity data
```

### Bridge Not Running

**Restart bridge manually:**
```bash
oc exec $POD -c hotel -- bash -c "
  export HOME=/tmp
  source /opt/ros/jazzy/setup.bash
  export ROS_DOMAIN_ID=0
  
  # Kill existing bridge
  pkill -f 'ros_gz_bridge.*robot_1'
  
  # Restart with correct topics
  ros2 run ros_gz_bridge parameter_bridge \
    /robot_1/cmd_vel@geometry_msgs/msg/Twist]gz.msgs.Twist \
    /robot_1/odometry@nav_msgs/msg/Odometry[gz.msgs.Odometry \
    --ros-args -r /robot_1/odometry:=/robot_1/odom &
"
```

---

## File Reference

### Modified Files
- `entrypoints/entrypoint-hotel.sh` - Added plugin path, corrected bridge topics
- `Containerfile.hotel-nav2-v3` - Build configuration with all patches

### Patch Scripts (Applied at Build Time)
- `scripts/patch_hotel_world.py` - Add Sensors system
- `scripts/patch_hotel_world_complete.py` - GUI fixes, ground plane
- `scripts/patch_physics_to_ode.py` - Force ODE physics
- `scripts/patch_hotel_world_add_robot.py` - Pre-spawn robot with DiffDrive plugin
- `scripts/patch_robot1_remove_static.py` - Remove static tag
- `scripts/patch_robot1_scale_3x.py` - Scale and color robot
- `scripts/patch_robot1_position_negative_y.py` - Position robot
- `scripts/patch_robot1_diffdrive_params.py` - Fix wheel parameters

### World File Location (Runtime)
- `/opt/rmf_demos_ws/install/share/rmf_demos_maps/maps/hotel/hotel.world`

---

## Contact & Handover Notes

**Current Status:** Build #24 is the working version deployed in `ros2-rmf-hotel-test` namespace.

**Critical Environment Variables:**
- `GZ_SIM_SYSTEM_PLUGIN_PATH` - MUST include vendor plugins directory
- `ROS_DOMAIN_ID=0` - For ROS2 topic access
- `GZ_SIM_RESOURCE_PATH` - For model loading

**Key Insights:**
1. Gazebo Harmonic continuous joints have a bug (0 DOF) - use revolute with huge limits
2. DiffDrive plugin topics must use absolute paths (`/robot_1/cmd_vel` not `cmd_vel`)
3. Bridge topics must match DiffDrive exactly (not `/model/robot_1/*`)
4. Vendor plugin path is NOT in default `GZ_SIM_SYSTEM_PLUGIN_PATH`
5. Pre-spawning in world file required (dynamic spawn creates 0 DOF joints)

**Testing Checklist for Verification:**
- [ ] DiffDrive plugin loads (check logs)
- [ ] No DOF=0 warnings in logs
- [ ] Robot responds to `/robot_1/cmd_vel` commands
- [ ] Odometry publishes on `/robot_1/odom`
- [ ] Robot visible in noVNC as large red box
- [ ] Position changes when driving commands sent

**Recommended Next Developer Actions:**
1. Review this document thoroughly
2. Test robot movement with provided commands
3. Verify in noVNC that robot is visible
4. Begin Nav2 integration using existing Nav2 packages
5. Create hotel world map for AMCL localization

---

**Document Version:** 1.0  
**Last Updated:** 2026-09-11  
**Build Version:** #24 (working)  
**Namespace:** ros2-rmf-hotel-test
