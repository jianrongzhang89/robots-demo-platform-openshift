# Free Fleet Adapter Crash - Root Cause Analysis

## Issue Summary

Free Fleet adapter crashes with segmentation fault (exit code -11) when trying to initialize robots.

**Error:**
```
[fleet_adapter.py-1] [INFO] Initializing robot [tinyBot_4], waiting for AMCL pose...
[fleet_adapter.py-1] Fatal Python error: Segmentation fault
[ERROR] [fleet_adapter.py-1]: process has died [pid 112, exit code -11]
```

## Investigation Findings

### 1. Adapter Successfully Discovers All 4 Robots ✅
```
Fleet: tinyRobot (4 robots)
```

The fleet configuration is correct and all robots are discovered.

### 2. Crash Happens During AMCL Pose Subscription

**Location:** `nav2_robot_adapter.py:131`

**Code:**
```python
# Spin the node a few times to let AMCL pose subscription receive data
init_timeout_sec = self.robot_config_yaml.get('init_timeout_sec', 10)
for i in range(init_timeout_sec * 2):  # Check every 0.5s
    rclpy.spin_once(self.node, timeout_sec=0.5)  # <-- CRASHES HERE
    if self.latest_pose is not None:
        break
```

The segfault happens during `rclpy.spin_once()` while waiting for `/amcl_pose` messages.

### 3. AMCL Pose Topics Exist But No Data ❌

**From RMF pod (domain 55):**
```bash
$ ros2 topic list | grep amcl_pose
/tinyBot_1/amcl_pose
/tinyBot_2/amcl_pose
/tinyBot_3/amcl_pose
/tinyBot_4/amcl_pose
```

Topics are visible (Zenoh bridging works ✅), but `ros2 topic echo` times out (no data being published ❌).

### 4. Root Cause Chain

```
slam_toolbox → /pose → pose_relay → /amcl_pose → Free Fleet adapter
     ❌          ❌         ⏸️            ❌              💥
```

**4.1. slam_toolbox Not Publishing /pose**

slam_toolbox is running but not localizing. Logs show:

```
[slam_toolbox] Message Filter dropping message: frame 'tinyBot_4/lidar_link/lidar' 
  at time 12157.800 for reason 'discarding message because the queue is full'
```

slam_toolbox's message filter queues up ALL incoming laser scans because it can't process them, eventually the queue fills up and it starts dropping messages.

**4.2. TF Transform Timing Issue**

Laser scans arrive with simulation timestamps (e.g., time=12157.800 sec):
```yaml
header:
  stamp:
    sec: 13553
    nanosec: 556000000
  frame_id: tinyBot_4/lidar_link/lidar
```

Static TF transforms are published with timestamp 0 (correct for static transforms):
```yaml
transforms:
- header:
    stamp:
      sec: 0      # Static transform
      nanosec: 0
    frame_id: tinyBot_4/base_footprint
  child_frame_id: tinyBot_4/lidar_link
```

slam_toolbox's message_filter needs to transform laser scans from `lidar_link/lidar` → `base_footprint`. 

**TF Tree (from `ros2 run tf2_tools view_frames`):**
```
map
  └─ tinyBot_4/odom (rate: 10Hz, time: 13504.2)
       └─ tinyBot_4/base_footprint (rate: 30Hz, time: 13503.3)
            └─ tinyBot_4/lidar_link (STATIC, time: 0.0)
                 └─ tinyBot_4/lidar_link/lidar (STATIC, time: 0.0)
```

The chain exists, but static transforms have `buffer_length: 0.000` and `most_recent_transform: 0.000`.

### 5. Why This Might Be Happening

**Hypothesis:** slam_toolbox's message_filter is trying to lookup transforms at the scan's timestamp (e.g., time=13553.556), but the TF2 buffer isn't properly extrapolating the static transforms (time=0) to the requested time.

Possible causes:
1. TF2 buffer configuration issue in slam_toolbox
2. Message filter timeout too short (`transform_timeout: 1.0` sec)
3. Static transforms not being latched properly
4. Race condition during initialization

### 6. Data Flow Verification

**All sensor data is flowing correctly:**

✅ **/clock** - Publishing at ~530 Hz
✅ **/tinyBot_4/scan** - Publishing at ~5 Hz  
✅ **/tinyBot_4/odom** - Publishing with timestamps
✅ **TF transforms** - All exist in the tree
✅ **Zenoh bridging** - Topics visible across domains

**What's NOT working:**
❌ slam_toolbox processing scans
❌ slam_toolbox publishing /pose
❌ pose_relay publishing /amcl_pose  
❌ Free Fleet adapter receiving pose data

## Attempted Solutions

### Tried: Verified All Configurations ✅

- [x] Zenoh bridge config includes `/amcl_pose` in publishers
- [x] pose_relay.py is running in all Nav2 pods
- [x] slam_toolbox configured with correct parameters
- [x] Static TF publishers have `use_sim_time:=true`
- [x] Robots spawned in Gazebo (odom and scan publishing)

### Tried: Checked Parameter Loading (/**/ prefix) ✅

slam_toolbox parameters are loading correctly with the `/**:` namespace prefix fix.

## Recommended Solutions

### Solution 1: Increase slam_toolbox Transform Tolerance

**File:** `config/nav2/tinybot_nav2_launch.py`

**Current:**
```python
'transform_timeout': 1.0,
```

**Try:**
```python
'transform_timeout': 5.0,  # Give more time for TF lookups
```

This gives slam_toolbox's message_filter more time to wait for transforms before dropping messages.

### Solution 2: Disable Message Filter Time Synchronization

Some slam_toolbox versions support a parameter to disable strict time matching for transforms:

```python
'use_scan_matching': True,
'use_scan_barycenter': False,
'minimum_travel_distance': 0.5,
'minimum_travel_heading': 0.5,
'scan_buffer_size': 25,  # Increase buffer
'scan_buffer_maximum_scan_distance': 20.0,
'link_match_minimum_response_fine': 0.1,
'link_scan_maximum_distance': 1.5,
```

### Solution 3: Use robot_state_publisher Instead of static_transform_publisher

Create a minimal URDF for tinyBot and use `robot_state_publisher` which publishes transforms with proper timestamps.

**Pros:** Transforms will have correct timestamps  
**Cons:** Requires URDF file and additional configuration

### Solution 4: Publish Periodic Transforms (Not Static)

Instead of `static_transform_publisher`, create a Python node that republishes the transform periodically with current simulation time.

### Solution 5: Check slam_toolbox tf_buffer_duration

Increase the TF buffer duration:

**Current:**
```python
'tf_buffer_duration': 30.0,
```

**Try:**
```python
'tf_buffer_duration': 60.0,
```

### Solution 6: Initialize slam_toolbox with /initialpose

Publish an initial pose estimate on `/initialpose` topic to help slam_toolbox bootstrap localization without waiting for scan matching.

### Solution 7: Switch to AMCL

If slam_toolbox continues to have issues, consider switching back to AMCL for localization:
- AMCL has more mature message_filter handling
- Better documented for multi-robot scenarios
- Trade-off: Less accurate than slam_toolbox

## Free Fleet Adapter Segfault

The segfault itself appears to be a secondary issue caused by waiting on a topic that never publishes data. Possible causes:

1. **rclpy bug:** Spinning while waiting for a non-publishing topic triggers segfault
2. **QoS mismatch:** Though unlikely since topic is visible
3. **Memory issue:** Related to Zenoh bridge or ROS 2 Jazzy

**Workaround:** Fix the slam_toolbox issue first. Once /amcl_pose is publishing, the adapter should work.

## Next Steps

1. Try Solution 1 (increase transform_timeout) - Simplest, low risk
2. If that doesn't work, try Solution 5 (increase tf_buffer_duration)
3. If still failing, enable slam_toolbox debug logging to see exact TF error:
   ```bash
   ros2 run slam_toolbox localization_slam_toolbox_node --ros-args --log-level debug
   ```
4. Consider Solution 3 (robot_state_publisher) for production deployment

## Files to Modify

- `config/nav2/tinybot_nav2_launch.py` - slam_toolbox parameters
- `entrypoints/entrypoint-tinybot-nav2-slam.sh` - TF publisher approach
- `scripts/pose_relay.py` - Add timeout/error handling (defensive)

## Success Criteria

✅ slam_toolbox processes scans without dropping messages  
✅ slam_toolbox publishes `/tinyBot_X/pose`  
✅ pose_relay publishes `/tinyBot_X/amcl_pose`  
✅ Free Fleet adapter receives pose and initializes without crash  
✅ All 4 robots show "Initialized" in adapter logs
