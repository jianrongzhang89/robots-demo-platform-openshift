# Free Fleet v2.0 + ROS Jazzy Investigation

## Issue Summary
Free Fleet adapter crashes with segmentation fault after initializing multiple robots (3 robots: tinyBot_1, tinyBot_2, tinyBot_3) in ROS 2 Jazzy environment.

## Investigation Findings

### 1. Compatibility Confirmation
- **Free Fleet v2.0.0** explicitly supports ROS 2 Jazzy (confirmed in README)
- Supports Ubuntu 24.04, ROS Jazzy, rmw-cyclonedds-cpp (all present in our setup)
- Our container uses `rmw_cyclonedds_cpp` (recommended by Free Fleet)

### 2. Known Issues in GitHub
Found similar crashes in Free Fleet repository:

#### Issue #207: "Free adapter crashes while launching for two robots" (CLOSED)
- **Symptoms**: Exit code -11 (segfault) when adding 2+ robots
- **Environment**: Ubuntu 22.04 + ROS Humble + Open-RMF Jazzy (from source)
- **Resolution**: "resolved by updating the libraries"
- **Key insight**: Multi-robot crashes are known, often due to library version mismatches

#### Issue #203: "Error when launching nav2_tb3_simulation_fleet_adapter.launch.xml" (CLOSED)
- **Symptoms**: Segfault in Transformation class constructor
- **Root Cause**: Python virtual environment causing library conflicts
- **Resolution**: Removing venv and using system packages
- **Key quote**: "No guarantee which python packages end up being used...packages of a different version causes broken behavior"

### 3. Upstream Code Analysis
Checked `free_fleet/main` branch fleet_adapter.py (current upstream):
- **STILL USES THREADING** with the problematic pattern:
  - Separate `update_thread` running asyncio event loop
  - `@parallel` decorator spawning thread pool workers
  - Multiple threads accessing rclpy simultaneously
- Uses `EventsExecutor` instead of `SingleThreadedExecutor`

### 4. Our Attempted Fixes
Applied comprehensive thread-safety patches:

#### Patch 1: Thread-safe pose access (`nav2_robot_adapter.py`)
```python
import threading

class Nav2RobotAdapter:
    def __init__(self, ...):
        self.pose_lock = threading.Lock()
        
    def _amcl_pose_callback(self, msg):
        with self.pose_lock:
            self.latest_pose = msg
    
    def get_pose(self):
        with self.pose_lock:
            # Copy pose data while holding lock
            ...
```

#### Patch 2: Sequential updates with ROS timer (`fleet_adapter.py`)
- Removed `@parallel` decorator
- Removed separate `update_thread`
- Replaced with `node.create_timer()` callback
- Added all robot nodes to single executor:
```python
def update_callback():
    for robot in robots.values():
        update_robot(robot)  # Sequential, no parallel

update_timer = node.create_timer(update_period, update_callback)
rclpy_executor = rclpy.executors.SingleThreadedExecutor()
rclpy_executor.add_node(node)
for robot in robots.values():
    rclpy_executor.add_node(robot.node)
rclpy_executor.spin()
```

### 5. Current Status
**Still crashes with segfault** despite all fixes

Crash shows 4 threads in traceback:
```
Thread 0x00007f24f1ffb6c0 (worker thread)
Thread 0x00007f24f27fc6c0 (worker thread)  
Thread 0x00007f24f37fe6c0 (worker thread)
Thread 0x00007f257a676740 (main executor)
```

**Analysis**: 3 worker threads still being created despite removing explicit threading code. Likely internal rclpy/RMW threading when multiple nodes with active subscriptions are added to executor.

### 6. Root Cause Hypothesis
The crash is likely due to **deep rclpy/rmw-cyclonedds threading conflicts** that occur when:
1. Multiple ROS nodes (one per robot adapter) are managed by single executor
2. Each node has active AMCL pose subscriptions receiving 5-8 Hz updates
3. Executor timer fires every 100ms (10 Hz robot state updates)
4. Concurrent callbacks from 3 robots' pose updates + timer callback
5. rclpy Python bindings are NOT thread-safe at C++ layer

Even with Python-level thread safety (locks, sequential updates), the underlying C++ rclpy/rmw layer still has race conditions when callbacks from multiple nodes fire simultaneously.

### 7. Possible Solutions

#### Option A: Use EventsExecutor (upstream approach)
Upstream uses `rclpy.experimental.EventsExecutor` instead of `SingleThreadedExecutor`:
```python
from rclpy.experimental import EventsExecutor
rclpy_executor = EventsExecutor()
```
EventsExecutor may handle multi-node callbacks better, but this doesn't eliminate the threading.

#### Option B: Separate executor per robot (isolation)
Don't add robot nodes to main executor - let them spin independently:
```python
# DON'T do: rclpy_executor.add_node(robot.node)
# Instead: robots manage their own callbacks
```
But this may cause other synchronization issues.

#### Option C: Single shared ROS node for all robots
Instead of one node per robot adapter, use a single shared node for all AMCL subscriptions. This eliminates multi-node executor complexity.

#### Option D: Use upstream EventsExecutor + keep threading
Revert to upstream threading pattern but use their EventsExecutor. This is what upstream runs in CI.

#### Option E: Upgrade to latest Free Fleet
Our base image may have an older Free Fleet build. Rebuild with latest `main` branch.

### 8. Comparison with Working Examples
Free Fleet CI tests pass successfully with:
- ROS 2 Jazzy
- Multiple robots (shown in nav2-integration-tests workflow)
- EventsExecutor
- Parallel updates with @parallel decorator
- Separate update thread with asyncio

**Key difference**: CI tests use the EXACT upstream code pattern we're trying to avoid.

### 9. Recommendations

**Immediate Next Step**: Try Option D (use upstream EventsExecutor pattern)

The upstream code works in their CI, suggesting the threading pattern + EventsExecutor combination is actually stable. Our "fixes" may have introduced NEW incompatibilities.

**Test**: Revert to original threading pattern but use `EventsExecutor`:
1. Keep `@parallel` decorator
2. Keep `update_thread` with asyncio
3. Change `SingleThreadedExecutor` → `EventsExecutor`
4. Remove the robot node additions to executor

**Alternative**: Investigate library versions
- Check if rmf_fleet_adapter_python is latest
- Check if rclpy is latest Jazzy version
- Ensure no version conflicts between packages

### 10. Files Modified
- `patches/fleet_adapter.py` - Multiple iterations of threading fixes
- `patches/nav2_robot_adapter.py` - Added threading.Lock for pose access
- `Containerfile.rmf-free-fleet-fixed-v4` - Container build with patches
- ConfigMap `free-fleet-adapter-patches` - Deployment configuration

### 11. Build Artifacts
- Container image: `quay.io/jianrzha/ros2-hotel-nav2-federated-rmf:v17-free-fleet-fixed-v4`
- Base image: `quay.io/jianrzha/ros2-hotel-nav2-federated-rmf:v16-amcl-spin-once`
- Deployment: `rmf-hotel-nav2` in namespace `ros2-rmf-hotel-nav2-federated`

## Conclusion
This is NOT a known Free Fleet + Jazzy incompatibility. Free Fleet v2.0 is designed for Jazzy and works in CI. The issue is likely:
1. Our base image has outdated Free Fleet build
2. Or our "thread-safety fixes" conflict with internal rclpy threading
3. Or we need to use EventsExecutor like upstream does

**Next action**: Test with upstream threading pattern + EventsExecutor before concluding it's unsolvable.
