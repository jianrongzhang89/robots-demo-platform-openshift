# TurtleBot3 Hotel Demo - Quick Start Guide

**Status:** ✅ Working  
**Build:** #24  
**Namespace:** ros2-rmf-hotel-test

---

## What's Working

A TurtleBot3 Waffle robot successfully moves in the Open-RMF hotel world simulation. The robot:
- ✅ Responds to `/robot_1/cmd_vel` velocity commands
- ✅ Publishes odometry on `/robot_1/odom` at 50 Hz
- ✅ Visible in Gazebo as a large red box (0.84m, 3x scaled)
- ✅ Controlled by gz-sim-diff-drive-system plugin

---

## Quick Test

### 1. Access the Pod
```bash
NS="ros2-rmf-hotel-test"
POD=$(oc get pods -n $NS -l app=hotel-sim -o jsonpath='{.items[0].metadata.name}')
oc exec -n $NS -it $POD -c hotel -- bash
```

### 2. Control the Robot
```bash
export HOME=/tmp
source /opt/ros/jazzy/setup.bash
export ROS_DOMAIN_ID=0

# Drive forward
ros2 topic pub /robot_1/cmd_vel geometry_msgs/msg/Twist '{linear: {x: 1.5}}' --rate 10

# Stop
ros2 topic pub /robot_1/cmd_vel geometry_msgs/msg/Twist '{linear: {x: 0.0}}' --once

# Circle pattern (forward + rotate)
ros2 topic pub /robot_1/cmd_vel geometry_msgs/msg/Twist '{linear: {x: 1.5}, angular: {z: 0.5}}' --rate 10
```

### 3. View in Browser
```bash
# Get noVNC URL
oc get route hotel-novnc -n ros2-rmf-hotel-test -o jsonpath='{.spec.host}'
```

Open: `https://<route-host>/vnc.html`

Look for the **large RED rectangular robot** in the hotel lobby.

---

## Critical Fixes Applied

### Fix #1: Plugin Path (Bug #10) - THE KEY FIX
**File:** `entrypoints/entrypoint-hotel.sh:68-71`

```bash
export GZ_SIM_SYSTEM_PLUGIN_PATH="${GZ_SIM_SYSTEM_PLUGIN_PATH}:/opt/ros/jazzy/opt/gz_sim_vendor/lib/gz-sim-8/plugins"
```

Without this, DiffDrive plugin cannot be found even though it's installed.

### Fix #2: Bridge Topics (Bug #9)
**File:** `entrypoints/entrypoint-hotel.sh:233-242`

```bash
ros2 run ros_gz_bridge parameter_bridge \
  /robot_1/cmd_vel@geometry_msgs/msg/Twist]gz.msgs.Twist \
  /robot_1/odometry@nav_msgs/msg/Odometry[gz.msgs.Odometry \
  --ros-args -r /robot_1/odometry:=/robot_1/odom
```

Bridge must use `/robot_1/*` topics, NOT `/model/robot_1/*`.

### Fix #3: Joint Type (Bug #8)
**File:** `scripts/patch_hotel_world_add_robot.py:139-152`

```xml
<joint name="left_wheel_joint" type="revolute">
  <axis>
    <limit>
      <lower>-1e16</lower>
      <upper>1e16</upper>
      <effort>1000</effort>
      <velocity>1000</velocity>
    </limit>
  </axis>
</joint>
```

Use revolute with huge limits instead of continuous (Gazebo Harmonic bug).

---

## Build & Deploy

### Build
```bash
oc start-build hotel-nav2-v3-fixed -n ros2-rmf-hotel-test --from-dir=. --follow
```

### Deploy
```bash
NS="ros2-rmf-hotel-test"
BUILD_NUM=24  # or latest

NEW_IMAGE=$(oc get build hotel-nav2-v3-fixed-${BUILD_NUM} -n $NS -o jsonpath='{.status.outputDockerImageReference}')
oc set image deployment/hotel-sim -n $NS hotel=$NEW_IMAGE
oc delete pod -l app=hotel-sim -n $NS --grace-period=5

# Wait for new pod
oc wait --for=condition=ready pod -l app=hotel-sim -n $NS --timeout=180s
```

---

## Verification Checklist

```bash
POD=$(oc get pods -n $NS -l app=hotel-sim -o jsonpath='{.items[0].metadata.name}')

# 1. Check DiffDrive loaded
oc logs -n $NS $POD -c hotel | grep "DiffDrive subscribing"
# Expected: "DiffDrive subscribing to twist messages on [/robot_1/cmd_vel]"

# 2. Check no DOF warnings
oc logs -n $NS $POD -c hotel | grep -i "DOF"
# Expected: No output (no warnings)

# 3. Check bridge running
oc exec -n $NS $POD -c hotel -- ps aux | grep ros_gz_bridge | grep robot_1
# Expected: 2 processes (clock bridge + robot_1 bridge)

# 4. Check odometry publishing
oc exec -n $NS $POD -c hotel -- bash -c "
  export HOME=/tmp
  source /opt/ros/jazzy/setup.bash
  export ROS_DOMAIN_ID=0
  ros2 topic hz /robot_1/odom
"
# Expected: ~50 Hz

# 5. Test movement (Gazebo Transport)
oc exec -n $NS $POD -c hotel -- bash -c "
  /opt/ros/jazzy/opt/gz_tools_vendor/bin/gz topic \
    -t /robot_1/cmd_vel -m gz.msgs.Twist -p 'linear: {x: 1.0}'
  
  sleep 2
  
  /opt/ros/jazzy/opt/gz_tools_vendor/bin/gz topic \
    -e -t /robot_1/odom -n 1 | grep position
"
# Expected: Position x value should be changing
```

---

## Troubleshooting

### Robot Not Moving

1. **Check plugin path:**
   ```bash
   oc exec $POD -c hotel -- bash -c "
     source /opt/ros/jazzy/setup.bash
     echo \$GZ_SIM_SYSTEM_PLUGIN_PATH
   "
   ```
   Must include: `/opt/ros/jazzy/opt/gz_sim_vendor/lib/gz-sim-8/plugins`

2. **Check bridge topics:**
   ```bash
   oc exec $POD -c hotel -- ps aux | grep ros_gz_bridge | grep robot_1
   ```
   Should show: `/robot_1/cmd_vel` and `/robot_1/odometry` (not `/model/robot_1/*`)

3. **Restart bridge if needed:**
   ```bash
   oc exec $POD -c hotel -- pkill -f 'ros_gz_bridge.*robot_1'
   # Wait for entrypoint to restart it automatically
   ```

### Odometry Not Publishing

Test Gazebo Transport directly:
```bash
oc exec $POD -c hotel -- bash -c "
  /opt/ros/jazzy/opt/gz_tools_vendor/bin/gz topic -e -t /robot_1/odom -n 1
"
```

If this works but ROS2 doesn't, bridge is the issue. Check bridge process.

---

## Files Changed

1. **entrypoints/entrypoint-hotel.sh**
   - Line 68-71: Added GZ_SIM_SYSTEM_PLUGIN_PATH
   - Line 233-242: Fixed ros_gz_bridge topics

2. **scripts/patch_hotel_world_add_robot.py**
   - Defines robot model with DiffDrive plugin
   - Joint type: revolute with huge limits

3. **scripts/patch_robot1_diffdrive_params.py**
   - Updates wheel_radius: 0.033 → 0.10
   - Updates wheel_separation: 0.287 → 0.288

---

## Next Steps

- [ ] Verify robot visible in noVNC
- [ ] Test patrol patterns
- [ ] Integrate Nav2 for autonomous navigation
- [ ] Add localization (slam_toolbox or AMCL)
- [ ] Create hotel world map
- [ ] Test multi-floor navigation with lifts

---

## Key Learnings

1. **Plugin Discovery:** Vendor plugins need explicit path in `GZ_SIM_SYSTEM_PLUGIN_PATH`
2. **Topic Naming:** DiffDrive creates `/robot_1/*` topics, not `/model/robot_1/*`
3. **Bridge Mapping:** Bridge must use exact topic names from DiffDrive config
4. **Joint Types:** Continuous joints broken in Gazebo Harmonic - use revolute with huge limits
5. **Pre-spawning:** Dynamic spawning creates 0 DOF joints - must pre-spawn in world file

---

**For detailed technical information, see:** `docs/turtlebot3-hotel-integration.md`
