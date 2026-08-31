# Nav2 Controller Issues - Complete Resolution

## Executive Summary

Successfully resolved all Nav2 controller initialization issues through systematic root cause analysis. All 4 Nav2 robot pods are now running with complete navigation stacks.

## Problems Solved

### 1. ✅ DWB Critics Loading Failure (Primary Issue)

**Error Message:**
```
[controller_server] Couldn't load critics! Caught exception: No critics defined for FollowPath
```

**Root Cause (GitHub Issue #2796):**
- ROS2 parameter loading bug when using namespaced nodes (`namespace=robot_name`)
- Parameters from YAML files fail to load into namespaced nodes
- Controller created DWBLocalPlanner successfully but `critics` parameter returned empty

**Investigation Method:**
- Research agent analyzed Nav2 source code: `nav2_dwb_controller/dwb_core/src/dwb_local_planner.cpp`
- Found parameter declaration with no default: `declare_parameter_if_not_declared(node, dwb_plugin_name_ + ".critics", rclcpp::PARAMETER_STRING_ARRAY)`
- Parameter retrieval throws if value is empty: `if (!node->get_parameter(...)) { throw std::runtime_error("No critics defined...") }`
- Discovered GitHub Issue #2796: "Couldn't load critics when launching in namespace"

**Solution:**
```yaml
# Added /**/ wildcard prefix to support all namespaces
/**:
  controller_server:
    ros__parameters:
      FollowPath:
        critics: ["RotateToGoal", "Oscillation", "BaseObstacle", ...]
```

**Verification:**
```
[controller_server] Using critic "RotateToGoal" (dwb_critics::RotateToGoalCritic)
[controller_server] Using critic "Oscillation" (dwb_critics::OscillationCritic)
[controller_server] Using critic "BaseObstacle" (dwb_critics::BaseObstacleCritic)
[controller_server] Using critic "GoalAlign" (dwb_critics::GoalAlignCritic)
[controller_server] Using critic "PathAlign" (dwb_critics::PathAlignCritic)
[controller_server] Using critic "PathDist" (dwb_critics::PathDistCritic)
[controller_server] Using critic "GoalDist" (dwb_critics::GoalDistCritic)
```

### 2. ✅ BT Navigator Duplicate Registration

**Error Message:**
```
[bt_navigator] Failed to create navigator id navigate_to_pose. Exception: ID [ComputePathToPose] already registered
[ERROR] [bt_navigator-8]: process has died [pid 21, exit code -11]
```

**Root Cause:**
- Nav2 Jazzy breaking change: built-in BT plugins auto-load automatically
- `plugin_lib_names` list caused duplicate registration
- Nav2 Humble/Iron required explicit plugin listing

**Solution:**
```yaml
bt_navigator:
  ros__parameters:
    # Built-in plugins are added automatically in Nav2 Jazzy
    # plugin_lib_names: []  # Commented out to prevent duplicates
```

**Verification:**
- bt_navigator starts successfully
- All navigator sub-nodes running: `bt_navigator`, `bt_navigator_navigate_to_pose_rclcpp_node`, `bt_navigator_navigate_through_poses_rclcpp_node`

### 3. ✅ StatefulSet Scaling Blocked

**Issue:**
- StatefulSet only created 1 of 4 requested pods
- Pod status: 1/2 Ready (nav2 container failing readiness probe)

**Root Cause:**
- Readiness probe checked for `/amcl` node
- System uses `slam_toolbox` for localization, not AMCL
- Probe never succeeded, blocking StatefulSet sequential pod creation

**Solution:**
```yaml
readinessProbe:
  exec:
    command:
    - /bin/sh
    - -c
    - ros2 node list | grep -q "/slam_toolbox"  # Changed from /amcl
```

**Verification:**
```
NAME             READY   STATUS    RESTARTS
nav2-tinybot-0   2/2     Running   0          (tinyBot_1)
nav2-tinybot-1   2/2     Running   0          (tinyBot_2)
nav2-tinybot-2   2/2     Running   0          (tinyBot_3)
nav2-tinybot-3   2/2     Running   0          (tinyBot_4)
```

## Final System Status

### All 4 Nav2 Pods Operational ✅

Each robot pod runs 23 ROS2 nodes:

**Navigation Core:**
- ✅ controller_server (DWB + 7 critics)
- ✅ planner_server (NavfnPlanner)
- ✅ bt_navigator (navigate_to_pose + navigate_through_poses)
- ✅ slam_toolbox (localization mode with posegraph)
- ✅ behavior_server (spin, backup, wait, etc.)
- ✅ collision_monitor
- ✅ velocity_smoother
- ✅ waypoint_follower
- ✅ smoother_server

**Costmaps:**
- ✅ local_costmap (voxel_layer + inflation_layer)
- ✅ global_costmap (static_layer + obstacle_layer + inflation_layer)
- ✅ map_server

**Lifecycle Management:**
- ✅ lifecycle_manager_navigation
- ✅ lifecycle_manager_localization
- ✅ lifecycle_manager_map

**Integration:**
- ✅ pose_relay (slam_toolbox → amcl_pose for Free Fleet)
- ✅ robot_state_publisher (Free Fleet discovery)
- ✅ odom_to_tf (odometry transform publisher)
- ✅ zenoh_bridge (RMF federation to domain 55)
- ✅ TF publishers (base_footprint → lidar_link)

### Topics Published Per Robot

```
/tinyBot_X/amcl_pose             (from pose_relay)
/tinyBot_X/pose                  (from slam_toolbox)
/tinyBot_X/cmd_vel               (to robot via zenoh)
/tinyBot_X/odom                  (from robot via zenoh)
/tinyBot_X/scan                  (from robot via zenoh)
/tinyBot_X/robot_state           (for Free Fleet)
/tinyBot_X/battery_state         (for Free Fleet)
```

## Files Modified

1. **config/nav2/tinybot_nav2_params_rpp.yaml**
   - Added `/**:` namespace prefix
   - Removed `plugin_lib_names` list
   - Fixed planner plugin: `nav2_navfn_planner::NavfnPlanner`

2. **StatefulSet nav2-tinybot** (via `oc patch`)
   - Updated readiness probe from `/amcl` to `/slam_toolbox`

## Research Methodology

Agent-assisted root cause analysis:
1. Searched Nav2 GitHub issues for exact error messages
2. Analyzed DWB source code to understand parameter loading
3. Found GitHub Issue #2796 documenting namespace parameter bug
4. Identified Nav2 Jazzy breaking changes (BT plugin auto-loading)
5. Recommended `/**:` wildcard prefix solution

## Remaining Work

**Free Fleet Adapter:**
- Still crashes with segfault (exit code -11)
- Successfully discovers all 4 robots: "Fleet: tinyRobot (4 robots)"
- Crashes during AMCL pose subscription in `nav2_robot_adapter.py:131`
- This is a separate issue from Nav2 controller problems

**Next Steps:**
- Debug Free Fleet adapter segfault
- Test RMF task dispatch once adapter is stable
- Demonstrate multi-level navigation (L1→L2→L3)

## Commits

1. `f5bb7d7` - fix: resolve 'No critics defined' error with /**/ namespace prefix
2. `9a7ca3d` - fix: resolve bt_navigator duplicate ID registration error
3. (Applied via oc patch) - Updated StatefulSet readiness probe

## Lessons Learned

1. **Namespace Parameter Loading:** ROS2 has known issues loading parameters for namespaced nodes. Always use `/**:` prefix for multi-robot deployments.

2. **Nav2 Jazzy Breaking Changes:** Built-in BT plugins auto-load. Don't list them in `plugin_lib_names`.

3. **StatefulSet Readiness Probes:** Must match actual node names. Switching localization algorithms requires updating probes.

4. **Research Before Coding:** Systematic investigation (GitHub issues + source code) found root causes faster than trial-and-error config changes.
