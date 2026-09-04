# Map-Switching Testing Guide

## Overview

This guide covers testing the multi-level navigation implementation with dynamic map switching for Nav2 robots using Free Fleet.

**Status:** Implementation complete, ready for testing

**Prerequisites:** Nav2 + Free Fleet integration with hotel world (not yet deployed)

---

## Testing Environment Setup

### 1. Enable Multi-Level Mode

Set environment variable in robot pod deployment:

```yaml
env:
  - name: ENABLE_MULTILEVEL
    value: "true"
  - name: MAP_LEVEL
    value: "L1"  # Initial level
```

### 2. Verify Map Files

Ensure all level-specific map files are available:

```bash
ls -lh /opt/maps/hotel_L*.{pgm,yaml}
```

Expected output:
```
/opt/maps/hotel_L1.pgm   (1.1M)
/opt/maps/hotel_L1.yaml  (129B)
/opt/maps/hotel_L2.pgm   (1.1M)
/opt/maps/hotel_L2.yaml  (130B)
/opt/maps/hotel_L3.pgm   (1.1M)
/opt/maps/hotel_L3.yaml  (131B)
```

### 3. Check Fleet Configuration

Verify `fleet_config.yaml` contains multi-level maps with lift poses:

```yaml
robots:
  robot_1:
    maps:
      L1:
        map_url: "/opt/maps/hotel_L1.yaml"
        lift_exit_poses:
          Lift1: [52.5, 27.5, 0.0]
        lift_cabin_poses:
          Lift1: [52.5, 27.5]
      # ... L2, L3
```

---

## Test Cases

### Test 1: Single-Level Navigation (Baseline)

**Purpose:** Verify single-level navigation still works

**Steps:**
1. Deploy robot on L1
2. Send navigation command to waypoint on same level
3. Verify robot navigates successfully

**Expected Result:**
- ✅ Navigation completes without errors
- ✅ No map switching occurs
- ✅ Logs show "Already on level [L1], no switch needed"

**RMF Command:**
```bash
ros2 run rmf_demos_tasks dispatch_patrol \
  -F turtlebot3 -R robot_1 \
  -p lobby_west lobby_east -n 1 \
  --use_sim_time
```

---

### Test 2: Map Server Lifecycle State Check

**Purpose:** Verify multiple map servers launched correctly

**Steps:**
```bash
# Inside robot pod
ros2 node list | grep map_server
# Expected: map_server_L1, map_server_L2, map_server_L3

ros2 lifecycle get /robot_1/map_server_L1
# Expected: active (since L1 is initial level)

ros2 lifecycle get /robot_1/map_server_L2
# Expected: inactive

ros2 lifecycle get /robot_1/map_server_L3
# Expected: inactive
```

**Expected Result:**
- ✅ Three map server nodes exist
- ✅ Only L1 is active initially
- ✅ L2 and L3 are inactive

---

### Test 3: Manual Map Switching

**Purpose:** Test map switching logic independently

**Steps:**
1. Monitor map topic in terminal 1:
   ```bash
   ros2 topic echo /robot_1/map --field info.map_load_time
   ```

2. Call map switch via ROS2 service (would need custom service):
   ```python
   # Inside robot pod Python shell
   adapter = <get adapter instance>
   result = adapter.switch_map("L2")
   print(f"Switch result: {result}")
   ```

3. Verify map topic receives new map

**Expected Result:**
- ✅ switch_map() returns True
- ✅ map_server_L1 transitions to inactive
- ✅ map_server_L2 transitions to active
- ✅ /map topic shows different map_load_time
- ✅ Logs show "Successfully switched to map [L2]"

---

### Test 4: Cross-Level Navigation (Full Integration)

**Purpose:** Test complete multi-level workflow

**Steps:**
1. Robot starts on L1 (lobby_west)
2. Dispatch task to L2 (L2_center)
3. Monitor robot behavior

**Expected Behavior:**
```
1. Robot receives cross-level navigation command
2. Logs: "Cross-level navigation: L1 → L2"
3. Logs: "Will use Lift1 for level transition"
4. Logs: "Step 1/8: Waiting for Lift1 arrival at L1..."
   ... (through all 8 steps)
5. Logs: "Level transition complete: L1 → L2"
6. Robot navigates to final destination on L2
```

**RMF Command:**
```bash
ros2 run rmf_demos_tasks dispatch_patrol \
  -F turtlebot3 -R robot_1 \
  -p lobby_center L2_center -n 1 \
  --use_sim_time
```

**Expected Result:**
- ✅ Task accepted by fleet adapter
- ✅ Level transition executes (8 steps logged)
- ✅ Map switches from L1 to L2
- ✅ AMCL reinitializes at lift exit
- ✅ Robot completes navigation to L2_center

**Failure Modes to Check:**
- ❌ Lift arrival timeout → triggers replan
- ❌ Map switch fails → triggers replan
- ❌ No lift found → triggers replan

---

### Test 5: Three-Level Navigation (L1 → L2 → L3)

**Purpose:** Test navigation across multiple lift transitions

**Steps:**
1. Robot starts on L1
2. Dispatch task to L3 (L3_center)
3. Verify robot uses both lifts

**Expected Behavior:**
```
1. Cross-level navigation: L1 → L3 detected
2. No direct lift found
3. RMF planner routes: L1 → (Lift1) → L2 → (Lift2) → L3
4. Two level transitions execute
5. Robot arrives at L3_center
```

**RMF Command:**
```bash
ros2 run rmf_demos_tasks dispatch_patrol \
  -F turtlebot3 -R robot_1 \
  -p lobby_center L3_center -n 1 \
  --use_sim_time
```

**Expected Result:**
- ✅ Task accepted
- ✅ Two level transitions (L1→L2, L2→L3)
- ✅ Two map switches
- ✅ Robot completes navigation

---

### Test 6: Multi-Robot Coordination

**Purpose:** Verify map switching works with multiple robots

**Steps:**
1. Deploy robot_1 on L1, robot_2 on L1
2. Send robot_1 to L2, robot_2 to L3
3. Monitor independent map switching

**Expected Result:**
- ✅ Each robot maintains independent current_level state
- ✅ Map servers switch per-robot (namespaced)
- ✅ No interference between robots

---

### Test 7: Localization After Map Switch

**Purpose:** Verify AMCL reinitializes correctly

**Steps:**
1. Monitor AMCL particle cloud before/after switch
2. Check TF tree remains valid
3. Verify robot knows its pose on new map

**Monitor Commands:**
```bash
# Terminal 1: AMCL pose
ros2 topic echo /robot_1/amcl_pose

# Terminal 2: TF tree
ros2 run tf2_ros tf2_echo map robot_1/base_footprint

# Terminal 3: Particle cloud
ros2 topic hz /robot_1/particle_cloud
```

**Expected Result:**
- ✅ AMCL publishes initialpose after switch
- ✅ Particle cloud resets at lift exit location
- ✅ map → robot_1/base_footprint TF valid
- ✅ Pose converges quickly (< 5 seconds)

---

## Debugging

### Check Logs

**Fleet Adapter:**
```bash
oc logs -n <namespace> -l app=rmf-core -c fleet-adapter --tail=200
```

**Robot Nav2:**
```bash
oc logs -n <namespace> -l app=robot-nav-robot-1 -c nav2 --tail=200
```

### Common Issues

**Issue: "Unknown level [L2]"**
- **Cause:** level_maps not configured
- **Fix:** Check fleet_config.yaml has maps section with all levels

**Issue: "No lifecycle client for level L2"**
- **Cause:** Multi-map servers not launched
- **Fix:** Set ENABLE_MULTILEVEL=true in robot pod

**Issue: "Lifecycle service not available"**
- **Cause:** Map server not running
- **Fix:** Check `ros2 node list | grep map_server`

**Issue: "Map switch failed, requesting replan"**
- **Cause:** Lifecycle state transition failed
- **Fix:** Check map server logs, verify map files exist

**Issue: "Robot did not enter cabin in time"**
- **Cause:** Lift cabin detection threshold too small
- **Fix:** Adjust cabin_threshold in detect_lift_entry() (default: 0.5m)

---

## Performance Metrics

### Expected Timings

| Operation | Expected Duration | Notes |
|-----------|------------------|-------|
| Map switch (lifecycle) | 0.5 - 1.5 seconds | Deactivate + activate |
| AMCL reinitialization | 2 - 5 seconds | Particle convergence |
| Lift door open | 3 - 5 seconds | Simulated lift timing |
| Lift travel L1→L2 | 10 - 15 seconds | Simulated elevator speed |
| Total level transition | 20 - 30 seconds | End-to-end |

### Success Criteria

✅ **Single-level navigation:** 100% success rate (baseline)
✅ **Cross-level navigation:** ≥90% success rate
✅ **Map switch success:** ≥95%
✅ **Localization after switch:** Pose error <0.5m within 5s
✅ **Multi-robot:** No interference, independent switching

---

## Integration with RMF Lift System

**Current Status:** Stub implementations

The following methods need RMF lift integration:
- `wait_for_lift_arrival()` - Subscribe to `/lift_states`
- `wait_for_lift_doors()` - Parse LiftState.door_state
- `wait_for_lift_travel()` - Monitor LiftState.current_floor
- `request_lift_travel()` - Publish to `/lift_requests`

**Required ROS2 Package:** `rmf_lift_msgs`

**Integration Steps:**
1. Add `rmf_lift_msgs` to package dependencies
2. Import LiftState, LiftRequest message types
3. Replace stub implementations with actual subscriptions/publishers
4. Test with real RMF lift supervisor

---

## Rollback Plan

If multi-level navigation causes issues:

**Option 1: Disable Multi-Level**
```yaml
env:
  - name: ENABLE_MULTILEVEL
    value: "false"
```
Reverts to single map server behavior.

**Option 2: Use Single Unified Map**
```yaml
maps:
  L1:
    map_url: "/opt/maps/hotel_multilevel.yaml"
  L2:
    map_url: "/opt/maps/hotel_multilevel.yaml"
  L3:
    map_url: "/opt/maps/hotel_multilevel.yaml"
```
All levels use same 2.5D map (original behavior).

---

## Next Steps

After successful testing:

1. **Document findings** - Update this guide with actual test results
2. **Performance tuning** - Adjust timeouts, thresholds based on observations
3. **RMF lift integration** - Replace stub methods with real lift coordination
4. **Edge case handling** - Add retry logic, failure recovery
5. **Production deployment** - Enable for hotel demo

---

**Implementation Date:** 2026-09-04  
**Status:** Code complete, awaiting deployment for testing  
**Estimated Test Duration:** 4-6 hours
