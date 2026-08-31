# slam_toolbox TF Timestamp Fix

## Problem Statement

slam_toolbox was dropping all laser scan messages with error:
```
[slam_toolbox] Message Filter dropping message: frame 'tinyBot_4/lidar_link/lidar' 
  at time 14475.000 for reason 'discarding message because the queue is full'
```

This prevented slam_toolbox from localizing, which blocked the entire RMF integration:
```
slam_toolbox (no /pose) → pose_relay (no /amcl_pose) → Free Fleet (segfault)
```

## Root Cause

**TF timestamp mismatch between static transforms and simulation-timestamped laser scans.**

### Issue 1: odom→base_footprint Transform Using Wall Time

The `odom_to_tf.py` script was publishing transforms with current wall time instead of the original odometry message timestamp:

```python
# WRONG - Uses wall time
t.header.stamp = self.get_clock().now().to_msg()
```

This caused a mismatch when:
- Laser scans arrived with simulation timestamps (e.g., `time=14475.000`)
- Odom transforms were published with different wall-time timestamps
- slam_toolbox's `tf2_ros::MessageFilter` couldn't synchronize them

### Issue 2: Static Transforms with timestamp=0

`static_transform_publisher` publishes transforms with `timestamp=0` even when `use_sim_time=true`:

```yaml
transforms:
- header:
    stamp:
      sec: 0      # Static transform - "valid at all times"
      nanosec: 0
  frame_id: tinyBot_4/base_footprint
  child_frame_id: tinyBot_4/lidar_link
```

slam_toolbox's message_filter needs to transform scans from `lidar_link/lidar` → `base_footprint` at the scan's timestamp, but TF2 cannot extrapolate from `time=0` to `time=14475`, causing the message_filter queue to fill up and drop ALL messages.

### Why This Breaks slam_toolbox

slam_toolbox uses `tf2_ros::MessageFilter` which:
1. Receives a laser scan with timestamp `T` (e.g., 14475.000)
2. Tries to lookup TF transform at timestamp `T`
3. If transform not available, queues the scan message
4. If queue fills up (size=5 hardcoded), drops new messages

The message_filter **cannot process scans without synchronized TF transforms**.

## Solution

### Fix 1: Use Original Odometry Timestamp in odom_to_tf.py

**File:** `scripts/odom_to_tf.py`

**Change:**
```python
# CORRECT - Use original odom message timestamp
t.header.stamp = msg.header.stamp  # From Gazebo simulation
```

**Why:** This ensures the `odom→base_footprint` transform has the exact same timestamp as the odometry message from Gazebo, maintaining time synchronization with laser scans.

**Source:** [ROS Answers #357762](https://answers.ros.org/question/357762/slam_toolbox-message-filter-dropping-message/)
> "My odometry transform was missing the timestamp. Adding it got the slam working!"

### Fix 2: Replace static_transform_publisher with dynamic_tf.py

**Problem:** `static_transform_publisher` always publishes with `timestamp=0`, which breaks message_filter synchronization in simulation.

**Solution:** Created `dynamic_tf.py` that publishes "static" transforms with current simulation time:

```python
def publish_transform(self):
    """Publish TF transform with current simulation time."""
    t = TransformStamped()
    
    # CRITICAL: Use current simulation time, not timestamp=0
    t.header.stamp = self.get_clock().now().to_msg()
    t.header.frame_id = self.frame_id
    t.child_frame_id = self.child_frame_id
    # ... (translation and rotation same as static_transform_publisher)
    
    self.tf_broadcaster.sendTransform(t)
```

Publishes at 10Hz to ensure fresh timestamps for slam_toolbox's message_filter.

**Why:** While the transform is geometrically static (constant offset), publishing it with current simulation timestamps allows TF2 to extrapolate/interpolate to scan timestamps.

**Source:** [GitHub Issue ros2/ros2#989](https://github.com/ros2/ros2/issues/989)
> "static_transform_publisher publishes with sec: 0, nanosec: 0 even when use_sim_time=true. This is intentional (static transforms are 'valid at all times'), but it breaks message_filters in simulation."

**Alternative:** [robot_state_publisher Issue #105](https://github.com/ros/robot_state_publisher/issues/105) suggests using `robot_state_publisher` with `use_tf_static=false`, but this requires a URDF file.

## Implementation

### Files Modified

1. **scripts/odom_to_tf.py**
   - Changed line 39: `t.header.stamp = msg.header.stamp`
   - Added comment explaining why

2. **scripts/dynamic_tf.py** (new)
   - Publishes periodic transforms with current simulation time
   - Replaces `static_transform_publisher` for base_footprint→lidar_link
   - 10Hz publication rate

3. **entrypoints/entrypoint-tinybot-nav2-slam.sh**
   - Replaced `ros2 run tf2_ros static_transform_publisher` with `python3 /opt/nav2_scripts/dynamic_tf.py`
   - Two transforms updated:
     - base_footprint → lidar_link (0.05, 0, 0.28)
     - lidar_link → lidar_link/lidar (identity)

4. **Containerfile.nav2-slam-rpp-fixed**
   - Added `COPY scripts/odom_to_tf.py`
   - Added `COPY scripts/dynamic_tf.py`
   - Made both executable with `chmod +x`

### Container Image

**New Image:** `quay.io/jianrzha/ros2-hotel-nav2-federated-nav2:v22-tf-timestamp-fix`

**Base Image:** `v21-rpp-fixed` (includes working DWB controller)

**Changes:**
- Fixed odom_to_tf.py timestamp
- Added dynamic_tf.py for time-synchronized static transforms
- Updated entrypoint to use dynamic_tf.py

## Expected Results

After deploying the fixed image:

1. ✅ slam_toolbox message_filter will process laser scans without dropping
2. ✅ slam_toolbox will publish `/tinyBot_X/pose` at ~1-10 Hz
3. ✅ pose_relay will relay to `/tinyBot_X/amcl_pose`
4. ✅ Free Fleet adapter will receive pose data and initialize without segfault
5. ✅ All 4 robots will be available for RMF task dispatch

## Verification Commands

After deployment:

```bash
# Check slam_toolbox is processing scans (no dropping messages)
oc exec nav2-tinybot-0 -c nav2 -- grep 'Message Filter dropping' \
  /tmp/ros_logs/nav2_tinyBot_1.log | wc -l
# Expected: 0 or very low count

# Verify TF timestamps are synchronized
oc exec nav2-tinybot-0 -c nav2 -- bash -c "
  export HOME=/tmp && . /opt/ros/jazzy/setup.sh && 
  ros2 topic echo /tf --field transforms[0].header.stamp --once"
# Expected: Non-zero timestamp matching simulation time

# Check /pose is publishing
oc exec nav2-tinybot-0 -c nav2 -- bash -c "
  export HOME=/tmp && . /opt/ros/jazzy/setup.sh && 
  ros2 topic hz /tinyBot_1/pose"
# Expected: ~1-10 Hz

# Verify Free Fleet adapter sees all robots
oc logs -n ros2-rmf-hotel-nav2-federated -l app=rmf-hotel-nav2 --tail=50 | grep -i initialized
# Expected: All 4 robots initialized
```

## References

### GitHub Issues

1. **[slam_toolbox #516](https://github.com/SteveMacenski/slam_toolbox/issues/516)** - MessageFilter drops ALL messages when TF latency > scan rate
2. **[slam_toolbox #576](https://github.com/SteveMacenski/slam_toolbox/issues/576)** - Queue full due to missing odom timestamp
3. **[robot_state_publisher #105](https://github.com/ros/robot_state_publisher/issues/105)** - use_tf_static problem with timestamp synchronization
4. **[ros2/ros2 #989](https://github.com/ros2/ros2/issues/989)** - static_transform_publisher publishes time=0 even with use_sim_time=true

### ROS Answers

- **[Question #357762](https://answers.ros.org/question/357762/slam_toolbox-message-filter-dropping-message/)** - "My odometry transform was missing the timestamp. Adding it got the slam working!"

### Source Code

- **[slam_toolbox source](http://docs.ros.org/en/melodic/api/slam_toolbox/html/slam__toolbox__common_8cpp_source.html)** - Shows MessageFilter setup with hardcoded queue size of 5

## Lessons Learned

1. **Simulation time synchronization is critical** for message_filters
2. **Static transforms (time=0) break message_filter** in simulation with timestamped scans
3. **Always use original message timestamps** when republishing TF from sensor data
4. **MessageFilter queue size is hardcoded** in slam_toolbox - can't be configured via parameters
5. **TF2 extrapolation** requires transform history; time=0 doesn't provide that in simulation context

## Future Improvements

Consider switching to `robot_state_publisher` with a proper URDF file:
- More maintainable (geometric model in URDF, not hardcoded)
- Standard ROS2 approach
- Can publish all robot transforms from single node
- Set `use_tf_static: false` to publish to `/tf` with proper timestamps

For now, `dynamic_tf.py` is a minimal fix that solves the immediate problem without requiring URDF changes.
