# TurtleBot3 Spawn Failure — Root Cause and Fix

**Branch:** rmf-hotel-world-demo  
**Date:** 2026-09-09

## Problem Summary

TurtleBot3 robot spawn reported success but robot didn't materialize in Gazebo world.

### Symptoms

1. ✓ Spawn script returns: `Successfully spawned robot_1` + `data: true` response
2. ✗ Verification fails: `robot_1 not found in world model list`
3. ✓ DiffDrive plugin loads: `DiffDrive subscribing to twist messages on [cmd_vel]`
4. ✗ NO data published on `/robot_1/odom`, `/robot_1/joint_states` topics
5. ✓ DART physics engine active in hotel.world
6. ✗ gz-ros-bridge creates topics but they have no data

## Root Cause

**Wrong world name in spawn command**

The entrypoint script called the spawn script with:
```bash
--world sim_world
```

But the actual Open-RMF hotel world is named:
```bash
hotel
```

This caused:
- Gazebo service `/world/sim_world/create` returned success (request queued)
- But the robot was never created because world "sim_world" doesn't exist
- DiffDrive plugin loaded during SDF parsing (misleading success message)
- Topics created by gz-ros-bridge but no actual robot entity to publish data

## Fix

### 1. Correct world name in entrypoint

**File:** `entrypoints/entrypoint-hotel.sh`

**Changed line 165:**
```bash
# Before:
--world sim_world \

# After:
--world hotel \
```

### 2. Add DART-compatible friction parameters

**File:** `scripts/spawn_turtlebot3_hotel.py`

The spawn script used ODE-only friction tags, but hotel world uses DART physics engine. DART requires Bullet friction parameters (DART internally uses Bullet collision detection).

**Changed wheel collision surfaces (lines 50-56, 64-70):**
```xml
<!-- Before (ODE only): -->
<surface><friction><ode><mu>100000</mu><mu2>100000</mu2></ode></friction></surface>

<!-- After (ODE + Bullet for DART): -->
<surface>
  <friction>
    <ode><mu>100000</mu><mu2>100000</mu2></ode>
    <bullet><friction>100000</friction><friction2>100000</friction2></bullet>
  </friction>
</surface>
```

**Changed ground plane collision surface (lines 193-201):**
```xml
<!-- Before (ODE only): -->
<surface>
  <friction>
    <ode><mu>1.0</mu><mu2>1.0</mu2></ode>
  </friction>
</surface>

<!-- After (ODE + Bullet for DART): -->
<surface>
  <friction>
    <ode><mu>1.0</mu><mu2>1.0</mu2></ode>
    <bullet><friction>1.0</friction><friction2>1.0</friction2></bullet>
  </friction>
</surface>
```

## Why This Happened

1. **Misleading success response:** Gazebo service returns success when the request is queued, not when entity is created
2. **Silent world name mismatch:** No error when target world doesn't exist
3. **Plugin load message misleading:** DiffDrive subscription message appears during SDF parsing, before entity creation
4. **Physics engine assumption:** Spawn script assumed ODE physics (default in many Gazebo tutorials), but hotel world uses DART

## Verification After Fix

After rebuilding and redeploying:

```bash
# 1. Check robot appears in world model list
oc exec -n ros2-rmf-hotel-test <hotel-pod> -- gz model -l -w hotel | grep robot_1

# 2. Verify odometry data
oc exec -n ros2-rmf-hotel-test <hotel-pod> -- \
  ros2 topic echo --once /robot_1/odometry

# 3. Verify joint states
oc exec -n ros2-rmf-hotel-test <hotel-pod> -- \
  ros2 topic echo --once /robot_1/joint_states

# 4. Check Gazebo logs for DART physics confirmation
oc logs -n ros2-rmf-hotel-test <hotel-pod> | grep -i "dart\|physics"
```

## DART Physics Notes

- DART uses Bullet collision detection library internally
- Friction parameters must use `<bullet>` tags (not just `<ode>`)
- DART supports continuous joints (required for DiffDrive wheel odometry)
- ODE doesn't support continuous joints (silently converts to FIXED)

## Related Files

- `/opt/ros2-demo/scripts/spawn_turtlebot3_hotel.py` — spawn script
- `/entrypoint-hotel.sh` — hotel pod entrypoint
- `/opt/rmf_demos_ws/install/share/rmf_demos_maps/maps/hotel/hotel.world` — hotel world SDF (patched for DART at build time)
- `scripts/patch_hotel_physics_dart.py` — build-time DART physics patch

## References

- [Gazebo Physics Engines](https://gazebosim.org/api/gazebo/7/physics.html)
- [DART physics plugin](https://github.com/gazebosim/gz-physics/tree/gz-physics7/dartsim)
- Memory: `memory/rmf_nav2_pubsub_relay_fix.md` — fleet adapter must publish to ROS2 not Python Zenoh
- Memory: `memory/nav2_tf_wait_fix.md` — wait for TF frames before Nav2 launch
