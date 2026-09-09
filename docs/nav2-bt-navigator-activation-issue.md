# Nav2 bt_navigator Activation Issue

**Date:** 2026-09-09  
**Status:** ROOT CAUSE IDENTIFIED  
**Impact:** Navigation goals rejected, blocking multi-level demo execution

---

## Symptom

```
[bt_navigator] Action server is inactive. Rejecting the goal.
```

Navigation commands reach nav2_relay successfully but are rejected by bt_navigator.

---

## Root Cause Chain

### 1. **controller_server Crashed During Activation**

```
[controller_server-4] /usr/include/c++/15/bits/stl_vector.h:1358: 
std::vector<_Tp, _Alloc>::const_reference std::vector<_Tp, _Alloc>::front() const 
[with _Tp = unsigned char; _Alloc = std::allocator<unsigned char>; const_reference = const unsigned char&]: 
Assertion '!this->empty()' failed.
```

**Result:** controller_server process died completely.

**Verification:**
```bash
ros2 lifecycle get /controller_server
# Output: Node not found
```

### 2. **Why controller_server Crashed: Missing TF Frames**

During lifecycle activation, costmaps tried to check transforms:

```
[local_costmap.local_costmap]: Timed out waiting for transform from base_link to odom 
to become available, tf error: Invalid frame ID "odom" passed to canTransform 
argument target_frame - frame does not exist

[global_costmap.global_costmap]: Timed out waiting for transform from robot_1/base_link 
to map to become available, tf error: Invalid frame ID "robot_1/base_link" passed to 
canTransform argument source_frame - frame does not exist
```

**Issues:**
1. **"odom" frame doesn't exist** at activation time
2. **"robot_1/base_link" is wrong** - should be just "base_link" (namespace handled by bridge)
3. **TF buffer not filled yet** - transforms exist but with time extrapolation errors

### 3. **Lifecycle Activation Timing Issue**

```
Sequence:
1. Nav2 bringup launches (ros2 launch nav2_bringup navigation_launch.py)
2. lifecycle_manager_navigation tries to activate all nodes immediately
3. Costmaps check for transforms → TF buffer empty (10s fill time not elapsed)
4. controller_server crashes on assertion failure
5. bt_navigator activation fails because it needs controller_server's follow_path action
6. Result: bt_navigator stuck in inactive state
```

**Timeline:**
- T+0s: Nav2 launch starts
- T+0s: Lifecycle manager tries to activate
- T+0-10s: TF buffer filling (but activation already attempted)
- T+3s: Entrypoint tries to publish initial pose (but activation already failed)

---

## Why It Fails

### Frame Name Issues

**On Nav2 pod (Domain 0):**
- TF frames are bare: "map", "odom", "base_link"
- zenoh-bridge namespace="/robot_1" only affects Zenoh keys, NOT local frames

**In Nav2 params (incorrect):**
- Some params use "robot_1/base_link" ❌
- Should be just "base_link" ✅

### TF Buffer Not Ready

**TF2 buffer characteristics:**
- Needs ~10 seconds to fill with historical transforms
- During this time, queries cause "extrapolation into the past" errors
- Nav2 lifecycle activation doesn't wait for buffer readiness

**Evidence:**
```bash
ros2 run tf2_ros tf2_echo map base_link
# First few seconds: "Lookup would require extrapolation into the past"
# After ~10s: Transform available
```

---

## Failed Attempts

### 1. Manual Lifecycle Activation

```bash
ros2 service call /lifecycle_manager_navigation/manage_nodes \
  nav2_msgs/srv/ManageLifecycleNodes '{command: 2}'

# Result: success=False
# Reason: controller_server doesn't exist (crashed)
```

### 2. Direct bt_navigator Activation

```bash
ros2 lifecycle set /bt_navigator activate

# Result: Transitioning failed
# Error: "follow_path" action server not available
# Reason: Requires active controller_server
```

### 3. Watchdog Not Helping

The entrypoint watchdog checks every 10s and calls RESUME:

```bash
while true; do
  sleep 10
  BT_STATE=$(ros2 lifecycle get /bt_navigator 2>/dev/null | grep -oE "[a-z]+ \[[0-9]+\]")
  if ! echo "${BT_STATE}" | grep -q "active"; then
    ros2 service call /lifecycle_manager_navigation/manage_nodes \
      nav2_msgs/srv/ManageLifecycleNodes "{command: 2}"
  fi
done
```

**Problem:** Watchdog calls RESUME (command 2) but gets `success=False` because controller_server is dead.

---

## Solution Options

### Option A: Fix Nav2 Params (Recommended)

**Change frame names in nav2_params.yaml:**

```yaml
# BEFORE (wrong):
global_costmap:
  global_costmap:
    robot_base_frame: robot_1/base_link  # ❌

# AFTER (correct):
global_costmap:
  global_costmap:
    robot_base_frame: base_link  # ✅
```

**Why:** Local frames on Domain 0 don't have namespace prefix.

### Option B: Add TF Wait Before Activation

**In entrypoint-nav2.sh, before Nav2 launch:**

```bash
echo "[nav2-pod/${ROBOT_NAME}] Waiting for TF buffer to fill..."
for i in {1..30}; do
  if timeout 3 ros2 run tf2_ros tf2_echo map base_link 2>&1 | grep -q "translation"; then
    echo "[nav2-pod/${ROBOT_NAME}] TF ready"
    break
  fi
  sleep 1
done

# THEN launch Nav2
ros2 launch nav2_bringup navigation_launch.py ...
```

**Why:** Ensures TF buffer filled before lifecycle manager tries activation.

### Option C: Delay lifecycle Activation

**Set lifecycle manager to NOT auto-activate:**

```yaml
lifecycle_manager_navigation:
  autostart: false  # Don't activate on launch
```

**Then activate manually after initial pose published:**

```bash
# After AMCL converged
ros2 service call /lifecycle_manager_navigation/manage_nodes \
  nav2_msgs/srv/ManageLifecycleNodes '{command: 2}'
```

**Why:** Activation happens after TF and AMCL are ready.

### Option D: Restart Nav2 Pod

**Quick fix for testing:**

```bash
oc delete pod -n ros2-rmf-hotel -l app=robot-nav,robot=robot-1
# Wait for new pod to start
# May work if TF timing is luckier
```

**Why:** Fresh start, but doesn't solve underlying timing issue.

---

## Recommended Fix (Hybrid Approach)

### 1. Fix Frame Names in Nav2 Params

**File to modify:** Custom nav2_params.yaml or entrypoint Python patching code

```python
# In entrypoint-nav2.sh Python patching section:
# Replace robot_1/base_link → base_link
params_content = params_content.replace('robot_1/base_link', 'base_link')
params_content = params_content.replace('robot_1/base_footprint', 'base_footprint')
```

### 2. Add TF Wait Before Nav2 Launch

```bash
# After robot_state_publisher starts, before Nav2 launch
echo "[nav2-pod/${ROBOT_NAME}] Waiting for TF frames..."
timeout 30 bash -c 'until ros2 topic echo /tf --once 2>/dev/null | grep -q "frame_id"; do sleep 1; done'
echo "[nav2-pod/${ROBOT_NAME}] TF available"
sleep 5  # Extra buffer for TF2 buffer fill
```

### 3. Fix Watchdog to Detect Dead controller_server

```bash
while true; do
  sleep 10
  
  # Check if controller_server exists
  if ! ros2 lifecycle get /controller_server &>/dev/null; then
    echo "[nav2-pod/${ROBOT_NAME}] controller_server dead, restarting Nav2..."
    # Kill and restart Nav2 launch
    kill $NAV2_PID
    # Re-launch Nav2 (would need refactoring to support this)
  fi
  
  # Original bt_navigator check
  BT_STATE=$(ros2 lifecycle get /bt_navigator 2>/dev/null | grep -oE "[a-z]+ \[[0-9]+\]")
  if ! echo "${BT_STATE}" | grep -q "active"; then
    ros2 service call /lifecycle_manager_navigation/manage_nodes \
      nav2_msgs/srv/ManageLifecycleNodes "{command: 2}"
  fi
done
```

---

## Testing After Fix

### 1. Verify Frame Names

```bash
# Check TF is publishing correct frames
ros2 topic echo /tf --once

# Should see: frame_id: "map", child_frame_id: "odom"
# NOT: frame_id: "robot_1/map"
```

### 2. Verify Lifecycle States

```bash
# All should be active [3]
ros2 lifecycle get /controller_server
ros2 lifecycle get /planner_server  
ros2 lifecycle get /bt_navigator

# Expected: active [3]
```

### 3. Test Navigation Goal

```bash
# Direct ROS2 publish (bypass RMF)
ros2 topic pub --once /rmf_navigate_cmd std_msgs/msg/String \
  "{data: 'test-goal-123 15.0 20.0 0.0'}"

# Check nav2_relay logs - should see goal accepted
# Expected: [nav_relay] test-goal-123: navigate_to_pose (15.00,20.00) yaw=0.00
# Expected: Goal accepted by Nav2 (NOT "rejected by Nav2")
```

### 4. End-to-End RMF Test

```bash
# Dispatch multi-level task
ros2 run rmf_demos_tasks dispatch_patrol -p lobby_center L2_room2 -n 1 --use_sim_time

# Monitor execution
# Expected: Robot moves toward goal
```

---

## Related Issues

- **TF extrapolation warnings:** Normal during startup, should clear after 10s
- **"odom" frame doesn't exist:** Fixed by odom-tf-publisher sidecar
- **Zenoh namespace confusion:** Bridge namespace affects Zenoh keys only, not local frames

---

## Next Steps

1. ✅ **DONE:** Root cause identified
2. ✅ **DONE:** Implemented TF wait fix in `entrypoints/entrypoint-nav2.sh` (lines 49-75)
3. **TODO:** Rebuild container image with updated entrypoint
4. **TODO:** Deploy new image to OpenShift
5. **TODO:** Test with Nav2 pod restart and verify bt_navigator activation
6. **TODO:** Verify full multi-level navigation execution

---

## References

- **Main docs:** `docs/rmf-nav2-zenoh-multi-level-implementation.md`
- **Memory:** `memory/rmf_nav2_pubsub_relay_fix.md`
- **Logs location:** `oc logs -n ros2-rmf-hotel <robot-pod> -c nav2`
