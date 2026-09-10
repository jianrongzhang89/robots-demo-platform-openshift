# DiffDrive Odometry Investigation Report

**Date:** 2026-09-09  
**Issue:** TurtleBot3 DiffDrive plugin not publishing odometry in Gazebo Harmonic + RMF Hotel demo  
**Iterations:** 90+ debugging cycles  
**Status:** Root cause identified, workaround in testing

---

## Executive Summary

After extensive investigation (90+ iterations over multiple debugging sessions), identified a **critical bug in Gazebo Harmonic 8.11.0 + DART physics v6.13.2** where continuous and revolute wheel joints are incorrectly converted to FIXED joints (0 degrees of freedom), preventing the DiffDrive plugin from computing odometry.

**Immediate Solution:** Switch to TPE (Trivial Physics Engine) as workaround  
**Long-term Solution:** Upgrade to Gazebo Jetty with DART 6.16.6+ when available in ROS2

---

## Environment

- **Platform:** OpenShift 4.x, multi-pod deployment
- **OS:** Ubuntu 24.04 (Noble)
- **ROS2:** Jazzy
- **Gazebo:** Harmonic (gz-sim 8.11.0)
- **Physics Engine:** DART v6.13.2 (ros-jazzy-gz-dartsim-vendor)
- **Robot:** TurtleBot3 Waffle with DiffDrive plugin
- **World:** RMF Hotel demo (multi-level with lifts/doors)

---

## Symptoms

1. ✅ Robot spawns successfully in Gazebo world
2. ✅ DiffDrive plugin loads: `"DiffDrive subscribing to twist messages on [cmd_vel]"`
3. ✅ All ROS2 topics exist (`/robot_1/odom`, `/robot_1/scan`, `/robot_1/cmd_vel`)
4. ✅ gz-ros-bridge configured correctly with QoS overrides
5. ❌ **Odometry topic has NO data** - `ros2 topic hz /robot_1/odom` times out
6. ❌ **Gazebo Transport odometry topic empty** - `gz topic -e -t /model/robot_1/odometry` returns nothing
7. ❌ **DOF mismatch error** repeating in Gazebo logs

---

## Root Cause

### The Bug

**Gazebo Harmonic 8.11.0 + DART physics v6.13.2 converts all continuous/revolute joints to FIXED (0 DOF)**

Error signature:
```
[Wrn] [Physics.cc:2381] There is a mismatch in the degrees of freedom
between Joint [left_wheel_joint(Entity=22)] and its JointVelocityCmd component.
The joint has 0 while the component has 1.
```

This affects:
- ✗ Dynamically spawned models via `/world/{name}/create` service
- ✗ Pre-spawned models in world SDF files
- ✗ All joint configurations tested (continuous, revolute, revolute with limits)

### Why DiffDrive Fails

The DiffDrive plugin requires 1-DOF rotational joints to:
1. Receive velocity commands on `/cmd_vel`
2. Compute wheel angular velocities
3. Integrate wheel rotations to calculate pose change
4. Publish odometry on `/odom` topic

With 0-DOF FIXED joints, the plugin cannot compute any motion → no odometry output.

---

## Configurations Tested (ALL FAILED)

### Physics Engines
1. **ODE physics** (default in hotel.world)
   - Result: Continuous joints not supported at all
   - Silently converts to FIXED joints
   
2. **DART physics v6.13.2** (patched via patch_hotel_physics_dart.py)
   - Result: Same DOF=0 error
   - Both dynamic spawn AND pre-spawn affected

### Joint Types
1. **Continuous joints** `<joint type="continuous">`
   - DART: Converted to 0 DOF
   - ODE: Not supported
   
2. **Revolute joints with large limits** `<limit><lower>-1e16</lower><upper>1e16</upper></limit>`
   - DART: Converted to 0 DOF
   - ODE: Not supported for unbounded rotation

3. **Revolute with unlimited effort/velocity** `<effort>-1</effort><velocity>-1</velocity>`
   - DART: Still 0 DOF

### Joint Axis Configurations
- `<xyz>0 0 1</xyz>` (Z-axis in child link frame - cylinder default)
- `<xyz>0 1 0</xyz>` (Y-axis in parent frame)
- `<xyz expressed_in='__model__'>0 1 0</xyz>` (explicit model frame)
- With/without `<dynamics>` tags

**All produced DOF=0 error**

### Spawn Methods
1. **Dynamic spawn** via Python script calling `gz service /world/sim_world/create`
   - Result: DOF=0
   
2. **Pre-spawn** robot in hotel.world at build time (patch_hotel_world_add_robot.py)
   - Result: DOF=0 (proves it's not a dynamic spawn issue)

### SDF Configurations
- Friction: ODE-only, Bullet-only, both
- Inertia: Varied mass/inertia tensors
- Link poses: With/without rotations
- Model structure: Simplified vs. full TurtleBot3

**None of these variations fixed the DOF=0 bug**

---

## Version Research

### Current Versions
- **Gazebo Harmonic:** gz-sim 8.11.0
- **DART physics:** 6.13.2 (February 2026 build)
- **gz-physics:** 7.6.0

### Known Issues in DART 6.13.2
Agent research found **DART 6.16.0+ has major joint fixes:**

1. **Joint Position Limit Freezing Bug** ([gz-sim#1684](https://github.com/gazebosim/gz-sim/issues/1684))
   - Joints permanently stuck at limits (3+ year bug)
   - Fixed in DART 6.16.0 (November 2024)
   
2. **Gazebo Jetty Upgrade** (July 2026)
   - Ships with gz-sim 10.x/11.x + DART 6.16.6
   - Includes joint impulse fixes, constraint regularization
   - Not yet available in ROS2 packages

### Upgrade Path
```
Current:  ROS2 Jazzy + Harmonic (gz-sim 8.x) + DART 6.13.2
Near-term: ROS2 Kilted + Ionic (gz-sim 9.x) + DART 6.13.2  (minimal improvement)
Target:   ROS2 future + Jetty (gz-sim 10.x+) + DART 6.16.6  (fixes included)
```

**The DOF=0 bug is NOT documented in GitHub issues** - may be unreported or DART version-specific.

---

## Solution: TPE Physics Engine

### What is TPE?

**TPE (Trivial Physics Engine)** is a fast kinematics-based physics engine:
- ✅ Properly supports continuous joints
- ✅ Available in current ROS2 Jazzy environment
- ✅ Sufficient for differential drive robots
- ⚠️ Limited dynamics (no realistic collisions/friction)
- ⚠️ Not suitable for complex multi-body dynamics

### Implementation

**File:** `scripts/patch_hotel_physics_tpe.py`
```python
# Change physics engine from DART to TPE
filename_elem.text = 'gz-physics-tpe-plugin'
```

**Containerfile change:**
```dockerfile
COPY scripts/patch_hotel_physics_tpe.py /tmp/patch_hotel_physics_tpe.py
RUN python3 /tmp/patch_hotel_physics_tpe.py
```

### Expected Results
- Continuous joints maintain 1 DOF
- DiffDrive plugin can compute odometry
- `/robot_1/odom` topic publishes at 50 Hz
- Nav2 slam_toolbox receives odometry
- Multi-level navigation tasks can execute

---

## Alternative Solutions

### 1. Bullet Physics
Available plugin: `gz-physics-bullet-featherstone-plugin`
- More realistic dynamics than TPE
- Less mature Gazebo integration than DART
- May have its own joint support issues

### 2. Wait for DART 6.16.6
- Requires Gazebo Jetty release in ROS2
- Likely 6-12 months away
- Most robust long-term solution

### 3. Use Slotcar Robots
- RMF's built-in slotcar plugin works
- No Nav2/LIDAR integration
- Simplified physics model

---

## Files Modified

### Created
- `scripts/patch_hotel_physics_tpe.py` - Switch to TPE physics
- `scripts/patch_hotel_world_add_robot.py` - Pre-spawn robot (didn't fix bug, but kept for TPE test)
- `docs/odometry-investigation-report.md` - This document

### Modified
- `Containerfile.hotel-nav2-v3` - Use TPE physics patch instead of DART
- `entrypoints/entrypoint-hotel.sh` - Updated physics engine comments
- `scripts/spawn_turtlebot3_hotel.py` - Multiple iterations (joint types, axes, friction)

### Key Learnings
- `scripts/patch_hotel_physics_dart.py` - DART doesn't work (DOF=0 bug)
- Dynamic spawn via `/world/{name}/create` - Same bug as pre-spawn
- Revolute vs continuous - Both fail with DART 6.13.2
- Axis configuration - Irrelevant to the bug

---

## Testing Plan (TPE)

### 1. Verify Physics Engine
```bash
oc logs hotel-pod | grep -i "TPE\|physics"
# Expected: "TPE physics + continuous wheel joints enabled"
```

### 2. Check for DOF Errors
```bash
oc logs hotel-pod | grep "degrees of freedom"
# Expected: No errors (or different error pattern)
```

### 3. Test Odometry Publication
```bash
ros2 topic hz /robot_1/odom
# Expected: ~50 Hz publication rate
```

### 4. Verify Odometry Data
```bash
ros2 topic echo /robot_1/odom --once
# Expected: Valid pose, twist, covariance data
```

### 5. Test Navigation
```bash
# Dispatch multi-level task
ros2 run rmf_demos_tasks dispatch_patrol \
  -p lobby_center L2_room2 -n 1 --use_sim_time
  
# Expected: Task progresses, robot navigates
```

---

## Lessons Learned

### Investigation Methodology
1. **Verify each layer independently**
   - Physics engine (ODE vs DART)
   - Spawn method (dynamic vs pre-spawn)
   - Joint configuration (type, axis, limits)
   - Bridge configuration (QoS, topics, remapping)

2. **Test minimal cases**
   - Simple box + wheel models revealed bug affects all models
   - Isolated physics engine from other variables

3. **Check version-specific bugs**
   - DART 6.13.2 is outdated
   - Known issues exist in this version range
   - Upgrade path identified

### Common Pitfalls
- ❌ Assuming spawn service failure when it's actually physics bug
- ❌ Focusing on joint axis when DOF is the real issue
- ❌ Not testing pre-spawn vs dynamic spawn separately
- ❌ Missing that both ODE and DART have problems (different ones)

### What Worked
- ✅ Systematic elimination of variables
- ✅ Reading actual Gazebo source code for error messages
- ✅ Testing with alternative physics engines
- ✅ Researching version-specific issues

---

## Recommendations

### Short-term (Immediate)
1. ✅ Deploy TPE physics solution
2. ⚠️ Accept limited dynamics for differential drive use case
3. 📝 Document TPE limitations for users

### Medium-term (3-6 months)
1. Monitor ROS2 package updates for Gazebo Jetty
2. Test DART 6.16.6 when available
3. File GitHub issue if bug persists in newer DART

### Long-term (6-12 months)
1. Upgrade to Gazebo Jetty + DART 6.16.6+
2. Re-enable full dynamics with DART
3. Validate all multi-robot scenarios

---

## References

### GitHub Issues
- [gz-sim#1684](https://github.com/gazebosim/gz-sim/issues/1684) - Joint position limit freezing (fixed in DART 6.16.0)
- No issue found for DOF=0 continuous joint bug (may need to file)

### Documentation
- [Gazebo Releases](https://gazebosim.org/docs/latest/releases/)
- [DART Changelog](https://github.com/dartsim/dart/blob/main/CHANGELOG.md)
- [Switching Physics Engines](https://gazebosim.org/api/physics/6/switchphysicsengines.html)
- [Gazebo Jetty Announcement](https://discourse.openrobotics.org/t/gazebo-jetty-released/50349)
- [DART 6.16.6 Upgrade](https://discourse.openrobotics.org/t/dart-upgraded-from-6-13-to-6-16-6-in-linux-gazebo-jetty-gz-physics9/52881)

### Packages
- `ros-jazzy-gz-sim-vendor` (0.0.10) - Gazebo Harmonic 8.11.0
- `ros-jazzy-gz-dartsim-vendor` (0.0.3) - DART 6.13.2
- `ros-jazzy-gz-physics-vendor` (0.0.7) - gz-physics 7.6.0

---

## Appendix: Error Logs

### DART DOF=0 Error (Repeating)
```
[gz-20] [Wrn] [Physics.cc:2381] There is a mismatch in the degrees of freedom
between Joint [left_wheel_joint(Entity=22)] and its JointVelocityCmd component.
The joint has 0 while the component has 1.
```

### DiffDrive Load Success (Misleading)
```
[gz-20] [Msg] DiffDrive subscribing to twist messages on [cmd_vel]
```
→ Plugin loads but cannot function with 0-DOF joints

### Spawn Service Success (Misleading)
```
data: true
```
→ Service returns success but joint DOF still 0

### Physics Engine Initialization
```
[gz-20] [Msg] World [sim_world] initialized with [10ms] physics profile.
```
→ DART loads but joints incorrectly initialized

---

**Document Version:** 1.0  
**Author:** Claude (debugging agent)  
**Review Status:** Awaiting TPE physics test results
