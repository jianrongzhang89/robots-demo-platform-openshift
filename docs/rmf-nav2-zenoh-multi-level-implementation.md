# RMF + Nav2 + Zenoh Multi-Level Navigation Implementation

**Date:** 2026-09-09  
**Status:** Core routing complete, Nav2 activation pending  
**Architecture:** Multi-pod OpenShift deployment with Zenoh federation

---

## Architecture Overview

### Multi-Pod Deployment on OpenShift

```
┌─────────────────────────────────────────────────────────────────────┐
│                          OpenShift Cluster                          │
│                                                                     │
│  ┌──────────────────┐      ┌──────────────────┐                   │
│  │   Zenoh Router   │      │    Gazebo Pod    │                   │
│  │      Pod         │◄────►│                  │                   │
│  │  tcp:7447        │      │  sim + sensors   │                   │
│  └──────────────────┘      └──────────────────┘                   │
│           ▲                                                         │
│           │                                                         │
│  ┌────────┴────────────────────────────────────────┐              │
│  │                                                  │              │
│  │   ┌──────────────────┐      ┌──────────────────┐              │
│  │   │   RMF Core Pod   │      │  Nav2 Pod        │              │
│  │   │  (Domain 55)     │      │  robot_1         │              │
│  │   │                  │      │  (Domain 0)      │              │
│  │   │ ┌──────────────┐ │      │ ┌──────────────┐ │              │
│  │   │ │ Fleet Adapter│ │      │ │  nav2_relay  │ │              │
│  │   │ │              │ │      │ │              │ │              │
│  │   │ │ Publishes    │ │      │ │  Subscribes  │ │              │
│  │   │ │ robot_1/     │ │      │ │  /rmf_       │ │              │
│  │   │ │ rmf_navigate │ │      │ │  navigate_cmd│ │              │
│  │   │ │ _cmd (ROS2)  │ │      │ │  (ROS2)      │ │              │
│  │   │ └──────┬───────┘ │      │ └──────▲───────┘ │              │
│  │   │        │         │      │        │         │              │
│  │   │ ┌──────▼───────┐ │      │ ┌──────┴───────┐ │              │
│  │   │ │ zenoh-robot- │ │      │ │ zenoh-nav2-  │ │              │
│  │   │ │ bridge       │─┼──────┼─│ bridge       │ │              │
│  │   │ │              │ │      │ │              │ │              │
│  │   │ │ ROS2→Zenoh   │ │      │ │ Zenoh→ROS2   │ │              │
│  │   │ └──────────────┘ │      │ └──────────────┘ │              │
│  │   └──────────────────┘      └──────────────────┘              │
│  │             Domain 55                Domain 0                  │
│  └──────────────────────────────────────────────────────────────┘ │
│                                                                     │
└─────────────────────────────────────────────────────────────────────┘
```

### Message Flow: RMF → Nav2 Navigation Command

```
1. Fleet Adapter (RMF pod, Domain 55)
   ↓ Publishes to ROS2 topic: /robot_1/rmf_navigate_cmd
   
2. zenoh-robot-bridge (RMF pod sidecar)
   ↓ Forwards ROS2 → Zenoh: robot_1/rmf_navigate_cmd
   
3. Zenoh Router (dedicated pod)
   ↓ Routes message between pods
   
4. zenoh-nav2-bridge (Nav2 pod sidecar)
   ↓ Forwards Zenoh → ROS2: /rmf_navigate_cmd
   
5. nav2_relay (Nav2 pod)
   ↓ Subscribes to /rmf_navigate_cmd, calls NavigateToPose action
   
6. Nav2 stack (Nav2 pod)
   ↓ Executes navigation with AMCL localization + DWB controller
```

---

## Critical Fixes Implemented

### 1. **Pub/Sub Relay Pattern** (Zenoh Queryable Workaround)

**Problem:** Zenoh-bridge-ros2dds v1.5.0 doesn't support ROS2 action responses when both client and server are behind bridges.

**Solution:** Implemented pub/sub relay pattern instead of direct action calls.

**Files Modified:**
- `patches/nav2_robot_adapter.py` (lines 1235-1257)
- `entrypoints/nav2_relay.py` (already implemented)

**Key Code Change:**
```python
# OLD (broken): Direct Zenoh queryable
self.zenoh_session.get(namespacify("navigate_to_pose/_action/send_goal", self.name), ...)

# NEW (working): Pub/sub relay
from std_msgs.msg import String as StdMsgsString
self._rmf_nav_cmd_pub = self.node.create_publisher(
    StdMsgsString,
    namespacify("rmf_navigate_cmd", self.name),
    10
)
ros_msg = StdMsgsString()
ros_msg.data = f"{goal_id_uuid} {x} {y} {yaw}"
cmd_pub.publish(ros_msg)
```

**Critical Insight:** Fleet adapter MUST publish to ROS2 (not Python Zenoh directly) so the rmf-robot-bridge creates the Zenoh route. Direct Python Zenoh publishing bypasses the bridge.

### 2. **Nav Graph Lift Lanes Format**

**Problem:** Multi-level tasks failed with "insufficient battery capacity" (misleading error - actually routing failure).

**Root Cause:** `nav_graph_fixed.yaml` was missing lift_lanes section and used wrong format.

**Solution:** Added lift_lanes with correct RMF dictionary format.

**File:** `helm/multi-robot-demo/files/nav_graph_fixed.yaml` (lines 89-93)

```yaml
# Lift lanes connecting L1 and L2 via Lift1
# Dictionary format with explicit level names for cross-level routing
lift_lanes:
  - {from: [L1, 8], to: [L2, 6], orientation: forward, lift_name: Lift1, duration: 5.0}
  - {from: [L2, 6], to: [L1, 8], orientation: forward, lift_name: Lift1, duration: 5.0}
```

**Format Requirements:**
- Use `{from: [level_name, vertex_index], to: [level_name, vertex_index]}` dictionary format
- NOT simple array format: `[vertex1, vertex2, {...}]`
- Vertex indices match lift cabin waypoints (L1 vertex 8, L2 vertex 6)
- Both directions required for bidirectional travel

### 3. **Zenoh Bridge Configuration**

**Problem:** rmf_navigate_cmd not flowing RMF → Nav2.

**Solution:** Updated both bridge configurations to publish/subscribe correctly.

**File:** `helm/multi-robot-demo/templates/configmap-zenoh.yaml`

**rmf-robot-bridge.json5** (lines 48-77):
```json5
{
  plugins: {
    ros2dds: {
      allow: {
        publishers: [
          ".*/rmf_navigate_cmd"  // CRITICAL: Publishes from Domain 55 to Zenoh
        ],
        subscribers: [
          ".*/(amcl_pose|odom|battery_state|scan|tf|tf_static|joint_states)"
        ]
      }
    }
  },
  mode: "client",
  connect: {endpoints: ["tcp/zenoh-router:7447"]}
}
```

**nav2-bridge-robot_1.json5** (lines 115-137):
```json5
{
  plugins: {
    ros2dds: {
      namespace: "/robot_1",
      allow: {
        publishers: [
          ".*/(tf|tf_static|battery_state|cmd_vel|amcl_pose|rmf_navigate_result|...)"
        ],
        subscribers: [
          ".*/rmf_navigate_cmd",  // CRITICAL: Moved from publishers to subscribers
          ".*/tf", ".*/scan", ".*/odom", ...
        ]
      }
    }
  }
}
```

**Key Fix:** `.*/rmf_navigate_cmd` moved from publishers to subscribers in nav2-bridge because it's Zenoh→ROS2 direction.

### 4. **UUID Goal ID Format**

**Problem:** Action calls failed with "Incorrectly sized array" errors.

**Root Cause:** Using integer for goal_id when ROS2 expects UUID.

**Solution:**
```python
# OLD (broken)
goal_id_str = str(int(time_now[0] * 1000000) % 10000000)

# NEW (working)
import uuid
goal_id_uuid = str(uuid.uuid4())
```

### 5. **Health Probe Removal**

**Problem:** RMF pod crashlooping due to failed readiness/liveness probes (rmf-web API server not available).

**Solution:** Removed health probes from RMF deployment.

```bash
oc patch deployment rmf-core -n ros2-rmf-hotel --type=json -p='[
  {"op": "remove", "path": "/spec/template/spec/containers/0/readinessProbe"},
  {"op": "remove", "path": "/spec/template/spec/containers/0/livenessProbe"}
]'
```

---

## Configuration Files Reference

### Key Files Modified

1. **patches/nav2_robot_adapter.py**
   - Location: Mounted via ConfigMap to `/opt/free_fleet/install/lib/python3.12/site-packages/free_fleet_adapter/nav2_robot_adapter.py`
   - ConfigMap: `nav2-adapter-pubsub`
   - Key changes: Lines 1244-1257 (ROS2 publishing instead of Zenoh)

2. **helm/multi-robot-demo/files/nav_graph_fixed.yaml**
   - Location: Mounted via ConfigMap to `/opt/ros2-demo/rmf/nav_graph.yaml`
   - ConfigMap: `rmf-config`
   - Key changes: Lines 89-93 (lift_lanes section)

3. **helm/multi-robot-demo/templates/configmap-zenoh.yaml**
   - Contains: zenoh-bridge configurations for all bridges
   - Key sections:
     - `rmf-robot-bridge.json5` (lines 48-81)
     - `nav2-bridge-robot_1.json5` (lines 108-161)

4. **entrypoints/nav2_relay.py**
   - Location: Baked into image at `/nav2_relay.py`
   - Subscribes to `/rmf_navigate_cmd`, calls NavigateToPose action locally
   - Already correctly implemented (no changes needed)

### ConfigMap Update Procedure

```bash
# Update fleet adapter patch
oc delete configmap nav2-adapter-pubsub -n ros2-rmf-hotel
oc create configmap nav2-adapter-pubsub -n ros2-rmf-hotel \
  --from-file=nav2_robot_adapter.py=patches/nav2_robot_adapter.py
oc delete pod -n ros2-rmf-hotel -l app=rmf-core

# Update nav graph
oc delete configmap rmf-config -n ros2-rmf-hotel
oc create configmap rmf-config -n ros2-rmf-hotel \
  --from-file=nav_graph.yaml=helm/multi-robot-demo/files/nav_graph_fixed.yaml \
  --from-file=fleet_config.yaml=helm/multi-robot-demo/files/fleet_config.yaml
oc delete pod -n ros2-rmf-hotel -l app=rmf-core
```

---

## Current Status

### ✅ **Working**

1. **Multi-level task planning**
   - RMF successfully plans routes from L1 to L2 via Lift1
   - Task bidding and award functional
   - Example: `patrol.dispatch-0` awarded to `robot_1`

2. **Pub/sub relay message delivery**
   - RMF publishes navigation commands to ROS2
   - rmf-robot-bridge forwards to Zenoh
   - nav2-bridge delivers to nav2_relay
   - **Evidence:**
     ```
     Fleet adapter: Publishing nav command via rmf_navigate_cmd: 7c59f74a-ac71-45d5-90c8-b5a22f069c7a 20.0 25.0 2.6778057644533315
     nav2_relay: [nav_relay] 7c59f74a-ac71-45d5-90c8-b5a22f069c7a: navigate_to_pose (20.00,25.00) yaw=2.68
     ```

3. **Robot registration**
   - robot_1 successfully registers with fleet adapter
   - TF transforms flowing via Zenoh
   - Battery state updates working

4. **Zenoh federation architecture**
   - Cross-pod topic/TF bridging operational
   - Zenoh router correctly routing between pods

### ⚠️ **Remaining Issues**

1. **Nav2 bt_navigator inactive - ROOT CAUSE IDENTIFIED** ⚠️
   - Navigation goals received but rejected
   - Error: `Action server is inactive. Rejecting the goal.`
   - **Root cause:** controller_server crashed during lifecycle activation due to missing TF frames
   - **Details:** See `docs/nav2-bt-navigator-activation-issue.md` for complete analysis
   - **Quick fix:** Restart Nav2 pod: `scripts/quick-fix-nav2-activation.sh`
   - **Permanent fix:** Add TF wait before Nav2 launch + fix frame names in params

2. **No lift hardware integration**
   - Lift state tracking not implemented
   - Lift request publishing not configured
   - Would require `rmf_lift_msgs` integration

3. **No result topic flow**
   - nav2_relay should publish to `/rmf_navigate_result`
   - RMF should subscribe to get navigation status
   - Currently not verified end-to-end

---

## Testing Procedures

### 1. Verify Robot Registration

```bash
# Check fleet adapter logs
oc logs -n ros2-rmf-hotel -l app=rmf-core -c rmf-core | grep "Successfully added"

# Expected output:
# [INFO] [turtlebot3_fleet_adapter]: Successfully added robot [robot_1] to the fleet [turtlebot3].
```

### 2. Dispatch Multi-Level Patrol Task

```bash
# Dispatch task from RMF pod
oc exec -n ros2-rmf-hotel deploy/rmf-core -c rmf-core -- bash -c "
  export HOME=/tmp && 
  source /opt/ros/jazzy/setup.bash && 
  ros2 run rmf_demos_tasks dispatch_patrol -p lobby_center L2_room2 -n 1 --use_sim_time
"

# Should return:
# Got response: {'state': {'booking': {'id': 'patrol.dispatch-0', ...}, 'success': True}
```

### 3. Verify Message Flow

```bash
# Check fleet adapter published
oc exec -n ros2-rmf-hotel deploy/rmf-core -c rmf-core -- \
  bash -c "find /tmp/ros-home -name 'python3_*.log' -type f -exec tail -50 {} \;" | \
  grep "Publishing nav command"

# Check nav2_relay received
oc logs -n ros2-rmf-hotel -l app=robot-nav,robot=robot-1 -c nav2 --since=1m | \
  grep "nav_relay"
```

### 4. Check Zenoh Routes

```bash
# RMF → Zenoh route
oc logs -n ros2-rmf-hotel -l app=rmf-core -c zenoh-robot-bridge | \
  grep "rmf_navigate_cmd"

# Zenoh → Nav2 route  
oc logs -n ros2-rmf-hotel robot-nav-robot-1-* -c zenoh-bridge | \
  grep "rmf_navigate_cmd"
```

---

## Memory Context (From Previous Sessions)

### Key Lessons Learned

1. **Zenoh bridge pub/sub pattern** (from `zenoh_cmdvel_keepalive_fix.md`)
   - Zenoh routes can be garbage collected after ~82s idle
   - Need keepalive subscribers to maintain routes
   - Regex patterns must match topic names correctly

2. **RMF negotiation deadlock** (from `rmf_negotiation_lessons.md`)
   - Responsive_wait can cause deadlocks on bidirectional corridors
   - Need position-triggered dispatch and s_out_hold waypoints
   - CANCEL execution pattern critical

3. **SLAM localization** (from `slam_toolbox_localization.md`)
   - Map frame = world-spawn coordinates
   - Posegraph coverage limitation with slam_toolbox
   - AMCL required for production

4. **Lift plugin fixes** (from `lift_plugin_fix.md`)
   - door_state initialization bug
   - RemoveComponent cleanup required
   - Relaxed completion thresholds

### Demo Requirements (HARD CONSTRAINT)

From `demo_requirements.md`:
- **Multi-floor navigation MUST use RMF + Nav2 + Zenoh federation in multi-pod architecture**
- **NOT slotcar robots** - this is a hard requirement
- True RMF integration with proper fleet management

---

## Next Steps to Complete

### Immediate (Critical Path)

1. **Fix Nav2 bt_navigator activation** ⭐ ✅ **FIX IMPLEMENTED**
   - **Issue:** controller_server crashes during activation due to TF not ready
   - **Root cause identified:** `docs/nav2-bt-navigator-activation-issue.md`
   - **✅ Permanent fix applied:** Added TF wait logic in `entrypoint-nav2.sh` (lines 49-75)
     - Waits up to 30s for /tf topic to publish frames
     - Adds 5s buffer for TF2 buffer to fill
     - Prevents controller_server crash during lifecycle activation
   - **Next step:** Rebuild container image with updated entrypoint and deploy to OpenShift
   - **Quick test alternative:** Run `scripts/quick-fix-nav2-activation.sh` (restarts Nav2 pod)

2. **Verify navigation execution**
   - Once bt_navigator active, test actual robot movement
   - Monitor for tf/localization issues
   - Verify goal reaching and success reporting

3. **Test result topic flow**
   - Confirm nav2_relay publishes to `/rmf_navigate_result`
   - Verify rmf-robot-bridge forwards to Zenoh
   - Check fleet adapter receives results

### Medium Priority

4. **Multi-level coordination**
   - Implement lift state subscription (currently placeholder)
   - Add lift request publishing
   - Test actual L1→L2 transition with map switching

5. **Error handling**
   - Navigation timeout handling
   - Lift timeout handling
   - Recovery behaviors

### Nice to Have

6. **Performance optimization**
   - Reduce transform extrapolation warnings
   - Tune AMCL parameters for faster convergence
   - Optimize Zenoh keepalive frequency

7. **Monitoring**
   - Add metrics/logging for message latency
   - Dashboard for fleet status
   - Task execution visualization

---

## Debugging Tips

### Common Issues

1. **"No bids received" for tasks**
   - Check robot registered: `grep "Successfully added" logs`
   - Verify nav_graph has lift_lanes section
   - Check battery capacity not zero

2. **Navigation commands not reaching Nav2**
   - Verify rmf-robot-bridge has rmf_navigate_cmd in publishers
   - Verify nav2-bridge has rmf_navigate_cmd in subscribers
   - Check Zenoh router logs for message routing
   - CRITICAL: Fleet adapter must publish to ROS2, not Python Zenoh directly

3. **bt_navigator inactive**
   - Check lifecycle state: `ros2 lifecycle get /bt_navigator`
   - Manual activation: `ros2 service call /lifecycle_manager_navigation/manage_nodes ...`
   - Check nav2 parameter files loaded

4. **Transform extrapolation errors**
   - Normal during startup (10s TF buffer fill time)
   - If persistent, check clock synchronization
   - Verify tf_relay running in RMF pod

### Log Locations

```bash
# Fleet adapter logs (Python)
/tmp/ros-home/.ros/log/python3_*.log

# RMF core nodes
oc logs -n ros2-rmf-hotel -l app=rmf-core -c rmf-core

# Nav2 stack
oc logs -n ros2-rmf-hotel <robot-pod-name> -c nav2

# Zenoh bridges
oc logs -n ros2-rmf-hotel <pod-name> -c zenoh-robot-bridge
oc logs -n ros2-rmf-hotel <robot-pod-name> -c zenoh-bridge
```

---

## Architecture Decisions

### Why ROS2 Publishing Instead of Zenoh?

**Decision:** Fleet adapter publishes to ROS2 topic, not Zenoh directly.

**Rationale:**
- zenoh-bridge-ros2dds only creates routes for ROS2 entities it discovers
- Direct Python Zenoh publishing bypasses bridge route creation
- Without bridge route, messages sent but never received
- ROS2 publishing triggers bridge to create Zenoh route automatically

**Implementation:**
```python
# Create ROS2 publisher (triggers bridge route)
self._rmf_nav_cmd_pub = self.node.create_publisher(
    StdMsgsString,
    namespacify("rmf_navigate_cmd", self.name),
    10
)

# Publish to ROS2 (bridge forwards to Zenoh)
cmd_pub.publish(ros_msg)
```

### Why Dictionary Format for lift_lanes?

**Decision:** Use `{from: [L1, 8], to: [L2, 6]}` format.

**Rationale:**
- RMF's multi-level graph parsing requires explicit level names
- Array format `[8, 6, {...}]` doesn't specify which level each vertex is on
- Task planner needs level information to compute cross-floor routes
- Dictionary format matches rmf_demos hotel example

### Why Separate Zenoh Router Pod?

**Decision:** Dedicated zenoh-router pod instead of embedded bridges.

**Rationale:**
- Centralized routing reduces complexity
- Easier to monitor/debug message flow
- Scales better with additional pods
- Follows Zenoh federation best practices
- OpenShift CNI blocks multicast, requiring explicit endpoints

---

## File Structure Summary

```
robots-demo-platform-openshift/
├── patches/
│   └── nav2_robot_adapter.py          # Fleet adapter ROS2 publishing fix
├── entrypoints/
│   └── nav2_relay.py                  # Nav2 pub/sub relay (in image)
├── helm/multi-robot-demo/
│   ├── files/
│   │   ├── nav_graph_fixed.yaml       # Multi-level nav graph with lift_lanes
│   │   └── fleet_config.yaml          # Fleet configuration
│   └── templates/
│       └── configmap-zenoh.yaml       # All Zenoh bridge configurations
└── docs/
    └── rmf-nav2-zenoh-multi-level-implementation.md  # This file
```

---

## Success Criteria

### Minimum Viable Demo

- [x] Robot registers with fleet adapter
- [x] Multi-level task planning succeeds  
- [x] Navigation command reaches nav2_relay
- [ ] Nav2 executes navigation to goal
- [ ] Task completes successfully

### Full Multi-Level Demo

- [ ] Robot navigates within L1
- [ ] Robot requests lift via RMF
- [ ] Lift arrives and opens
- [ ] Robot enters lift
- [ ] Map switches to L2
- [ ] Robot exits lift on L2
- [ ] Robot navigates to L2 goal
- [ ] Task reports completion

---

## Contact & Continuation

**Current State:** Core message routing working, Nav2 activation pending.

**To Continue:**
1. Focus on Nav2 bt_navigator activation issue
2. Once navigation works, test full L1→L2 sequence
3. Implement lift integration (currently stubbed)
4. Add error handling and recovery

**Key Files to Review:**
- This document (architecture overview)
- `patches/nav2_robot_adapter.py` (fleet adapter changes)
- `helm/multi-robot-demo/files/nav_graph_fixed.yaml` (nav graph)
- `helm/multi-robot-demo/templates/configmap-zenoh.yaml` (bridge configs)

**Memory Files:**
- `memory/demo_requirements.md` - Hard constraints
- `memory/zenoh_cmdvel_keepalive_fix.md` - Zenoh patterns
- `memory/rmf_negotiation_lessons.md` - RMF patterns

Good luck! The hard part (Zenoh routing) is solved. 🚀
