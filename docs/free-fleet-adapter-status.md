# Free Fleet Adapter Issue - Current Status

## Progress Summary

### Issues Fixed ✅

**1. Launch File Import Error**
- **Error:** `ImportError: cannot import name 'PushRosNamespace' from 'launch.actions'`
- **Fix:** Removed unused `GroupAction` and `PushRosNamespace` imports
- **Result:** nav2-tinybot-3 now starts successfully (2/2 Ready)

**2. slam_toolbox Message Dropping**
- **Before:** ~100% of messages dropped ("queue is full")
- **Fix:** Increased slam_toolbox timeouts:
  - `transform_timeout`: 1.0 → 5.0 seconds
  - `tf_buffer_duration`: 30.0 → 60.0 seconds
  - `scan_buffer_size`: 10 → 25
  - `scan_buffer_maximum_scan_distance`: 10.0 → 20.0
- **Result:** Only 7 messages dropped, significantly improved

**3. All 4 Nav2 Pods Running**
```
NAME             READY   STATUS    RESTARTS   AGE
nav2-tinybot-0   2/2     Running   0          64m
nav2-tinybot-1   2/2     Running   0          63m
nav2-tinybot-2   2/2     Running   0          63m
nav2-tinybot-3   2/2     Running   0          108s  ✅ FIXED
```

### Remaining Issue ❌

**slam_toolbox Not Publishing Pose**

**Symptoms:**
- `/tinyBot_4/slam_toolbox` node is running
- `/tinyBot_4/pose` topic exists but no data
- `/tinyBot_4/amcl_pose` topic exists but no data (relayed from /pose)
- TF warnings: "Lookup would require extrapolation into the past"

**Example Error:**
```
[global_costmap] Timed out waiting for transform from tinyBot_4/base_footprint to map
  tf error: Lookup would require extrapolation into the past. 
  Requested time 14241.920000 but the earliest data is at time 14245.900000
```

**Analysis:**
The error shows slam_toolbox published its first map→odom transform at time 14245.900, but the costmaps/planner are requesting transforms from earlier times (14241.920). This is a cold-start timing issue - slam_toolbox takes time to localize and publish its first transform.

**Why This Blocks Free Fleet:**
```
slam_toolbox (no /pose) → pose_relay (no /amcl_pose) → Free Fleet (segfault waiting for data)
```

## Current System State

### What's Working ✅
- Gazebo simulation running
- All 4 robots spawned (tinyBot_1, tinyBot_2, tinyBot_3, tinyBot_4)
- Sensor data flowing: scan ~5Hz, odom ~30Hz, clock ~530Hz
- Zenoh bridging operational (topics visible across domains)
- Nav2 stack fully activated (controller, planner, bt_navigator, etc.)
- slam_toolbox node running and processing some scans
- TF tree complete (map → odom → base_footprint → lidar_link → lidar_link/lidar)

### What's NOT Working ❌
- slam_toolbox not publishing /pose
- pose_relay can't relay /amcl_pose
- Free Fleet adapter crashes waiting for pose data

## Next Steps

### Step 1: Wait for slam_toolbox to Stabilize ⏳

slam_toolbox needs time to:
1. Receive enough scan data
2. Match scans against the posegraph map
3. Establish initial localization
4. Start publishing map→odom transform
5. Start publishing /pose topic

**Action:** Wait 2-3 minutes after pod startup for slam_toolbox to localize.

### Step 2: Verify Localization 🔍

Once slam_toolbox stabilizes, verify:
```bash
# Check if pose is publishing
ros2 topic hz /tinyBot_4/pose

# Check if amcl_pose is publishing (relayed)
ros2 topic hz /tinyBot_4/amcl_pose

# Verify transform chain
ros2 run tf2_ros tf2_echo map tinyBot_4/base_footprint
```

### Step 3: Alternative Solution - Publish Initial Pose 📍

If slam_toolbox fails to localize automatically, publish an initial pose estimate:

```python
# On /tinyBot_4/initialpose topic
geometry_msgs/PoseWithCovarianceStamped:
  header:
    frame_id: "map"
  pose:
    pose:
      position: {x: 22.0, y: -33.5, z: 0.0}
      orientation: {x: 0.0, y: 0.0, z: 0.0, w: 1.0}
    covariance: [0.25, 0, 0, ..., 0.25]  # Small uncertainty
```

This tells slam_toolbox where the robot is, kickstarting localization.

### Step 4: If Still Failing - Switch to AMCL 🔄

If slam_toolbox localization continues to fail:

**Pros of AMCL:**
- More mature message_filter handling
- Better documented for multi-robot scenarios
- Faster initialization
- Less sensitive to TF timing issues

**Cons:**
- Less accurate than slam_toolbox
- Needs pre-built map (we have hotel_L1.pgm ✅)

**Implementation:**
1. Change launch file to use `amcl` instead of `localization_slam_toolbox_node`
2. Update readiness probe to check for `/amcl` instead of `/slam_toolbox`
3. No need to change pose_relay (already subscribes to /amcl_pose)

### Step 5: Restart Free Fleet Adapter 🔄

Once /amcl_pose is publishing:
```bash
oc delete pod -n ros2-rmf-hotel-nav2-federated -l app=rmf-hotel-nav2
```

The adapter should initialize successfully and discover all 4 robots.

## Diagnostic Commands

```bash
# Check slam_toolbox status
oc exec nav2-tinybot-3 -c nav2 -- bash -c "
  export HOME=/tmp && . /opt/ros/jazzy/setup.sh && 
  ros2 lifecycle get /tinyBot_4/slam_toolbox"

# Check if scans are being processed
oc exec nav2-tinybot-3 -c nav2 -- grep 'Message Filter dropping' \
  /tmp/ros_logs/nav2_tinyBot_4.log | wc -l

# Check TF transform availability
oc exec nav2-tinybot-3 -c nav2 -- bash -c "
  export HOME=/tmp && . /opt/ros/jazzy/setup.sh && 
  ros2 run tf2_ros tf2_echo map tinyBot_4/base_footprint"

# Monitor pose publication
oc exec nav2-tinybot-3 -c nav2 -- bash -c "
  export HOME=/tmp && . /opt/ros/jazzy/setup.sh && 
  ros2 topic echo /tinyBot_4/pose --once"
```

## Success Criteria

✅ slam_toolbox processes scans without excessive dropping  
✅ slam_toolbox publishes /tinyBot_4/pose at ~1-10 Hz  
✅ pose_relay relays to /tinyBot_4/amcl_pose  
✅ Free Fleet adapter initializes without segfault  
✅ Free Fleet adapter logs show all 4 robots initialized  
✅ RMF can dispatch tasks to robots  

## Timeline Estimate

- **If slam_toolbox works:** 2-5 minutes for localization to stabilize
- **If need initial pose:** +5 minutes to test
- **If switch to AMCL:** +15 minutes to modify and redeploy

Total: 10-30 minutes to full operation.
