# Gazebo GUI Crash Fix - Implementation Report

## Summary

Successfully fixed the Gazebo GUI crash that was preventing visualization of the multi-level navigation demo. The simulation now runs with GUI visualization available via noVNC.

## Problem

Gazebo GUI was crashing on startup with RCL context error:
```
terminate called after throwing an instance of 'rclcpp::exceptions::RCLError'
  what():  failed to create guard condition: the given context is not valid
[gz-20] Aborted (Signal sent by tkill() 349)
```

**Root Cause:** The `toggle_floors` and `toggle_charging` GUI plugins in hotel.world were trying to access ROS2 (rclcpp) before the RCL context was initialized, causing a fatal crash that killed both the GUI and simulation server.

## Solution Implemented

### 1. Runtime World File Patching

Modified `entrypoints/entrypoint-hotel.sh` to patch hotel.world at pod startup:

```bash
# Copy world file to writable location
mkdir -p /tmp/hotel_world_patched/maps/hotel
cp hotel.world /tmp/hotel_world_patched/maps/hotel/

# Patch using Python regex to remove problematic plugins
python3 - "${HOTEL_WORLD}" <<'EOF'
import re, sys
content = open(sys.argv[1]).read()
# Remove toggle_charging plugin
content = re.sub(r'<plugin filename="toggle_charging".*?/?>', '<!-- DISABLED -->', content)
# Remove toggle_floors plugin (multi-line)
content = re.sub(r'<plugin name="toggle_floors".*?</plugin>', '<!-- DISABLED -->', content, flags=re.DOTALL)
open(sys.argv[1], 'w').write(content)
EOF

# Update GZ_SIM_RESOURCE_PATH to use patched version
export GZ_SIM_RESOURCE_PATH="/tmp/hotel_world_patched:${GZ_SIM_RESOURCE_PATH}"
```

### 2. ROS Distro Auto-Detection

Added auto-detection for ROS distro to support both Jazzy and Lyrical:

```bash
if [ -z "${ROS_DISTRO}" ]; then
  for distro in lyrical jazzy humble; do
    if [ -f "/opt/ros/${distro}/setup.bash" ]; then
      export ROS_DISTRO="${distro}"
      break
    fi
  done
fi
source /opt/ros/${ROS_DISTRO}/setup.bash
```

### 3. Image Build

Built fixed image: `hotel-nav2-v3-fixed-20260910`
- Base: `quay.io/jianrzha/ros2-rmf-hotel:latest` (Jazzy)
- Added: Nav2, TurtleBot3 model, patched entrypoint
- Build time: 3m 15s

## Results

### ✅ Fixed
- **Gazebo GUI crash**: GUI now runs without RCL errors
- **Simulation clock**: Publishing at ~1691 Hz (expected high rate)
- **Visualization**: noVNC shows Gazebo GUI successfully
- **World file patching**: Automatic removal of problematic plugins works

### ✅ Accessible
- **noVNC**: https://hotel-novnc-ros2-rmf-hotel-test.apps.ai-dev02.kni.syseng.devcluster.openshift.com
- **RMF Dashboard**: https://rmf-dashboard-ros2-rmf-hotel-test.apps.ai-dev02.kni.syseng.devcluster.openshift.com

### ⚠️ Known Issues

**Robot sensors not publishing data:**
- Topics exist (`/robot_1/scan`, `/robot_1/odom`) but timeout when checking hz
- Robot spawn script completes but sensors don't activate
- Likely causes:
  - Physics engine configuration (Bullet vs DART)
  - Sensor plugin not loading correctly
  - Robot model missing sensor definitions

**Impact:** Multi-level navigation cannot proceed without sensor data for slam_toolbox and Nav2.

## Verification Steps

```bash
# 1. Check Gazebo is running
oc exec -n ros2-rmf-hotel-test hotel-sim-xxx -c hotel -- \
  ps aux | grep "gz sim"
# Expected: gz sim gui and gz sim server processes

# 2. Verify clock publishing
oc exec -n ros2-rmf-hotel-test hotel-sim-xxx -c hotel -- bash -c "
  source /opt/ros/jazzy/setup.bash
  timeout 3 ros2 topic hz /clock
"
# Expected: ~1600-2000 Hz

# 3. Check GUI patch applied
oc logs -n ros2-rmf-hotel-test hotel-sim-xxx -c hotel | grep "GUI plugins patched"
# Expected: "[hotel-pod] GUI plugins patched successfully"

# 4. Access visualization
# Open noVNC URL in browser - should show Gazebo GUI without black screen
```

## Next Steps

To complete multi-level navigation demo:

1. **Fix robot sensor publishing**
   - Debug why robot model sensors aren't active
   - Check if robot actually spawned in Gazebo world
   - Verify sensor plugins in robot SDF
   - Test with simple world first to isolate issue

2. **Alternative approach: Pre-spawn in world file**
   - Add robot directly to hotel.world during image build
   - Avoid runtime spawn issues
   - Containerfile already has patch_hotel_world_add_robot.py

3. **Test with working robot**
   - Verify slam_toolbox receives scan data
   - Check Nav2 can localize and navigate
   - Test multi-level task dispatch end-to-end

## Files Modified

- `entrypoints/entrypoint-hotel.sh` - Added world file patching logic
- `Containerfile.hotel-nav2-v3` - Includes fixed entrypoint
- Build #hotel-nav2-v3-fixed-1 - Deployed image with fix

## Commits

- `92da0cb` - fix: patch hotel.world to remove RCL-crashing GUI plugins
- `6d116a7` - fix: auto-detect ROS distro in hotel entrypoint
- `cd0b9d5` - fix: copy hotel.world to writable location before patching

## Deployment

```bash
# Current deployment
NS=ros2-rmf-hotel-test
IMAGE=image-registry.openshift-image-registry.svc:5000/ros2-rmf-hotel-test/ros2-rmf-hotel:hotel-nav2-v3-fixed-20260910

oc set image deployment/hotel-sim -n $NS hotel=$IMAGE
```

## Conclusion

The primary goal (fix Gazebo GUI crash for visualization) has been **successfully achieved**. The demo environment is now ready for visual monitoring. The remaining sensor publishing issue is a separate problem that needs investigation but does not prevent visualization of the simulation environment.
