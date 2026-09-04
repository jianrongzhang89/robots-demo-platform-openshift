# Free Fleet Map-Switching Implementation Plan

## Executive Summary

**Objective:** Enable multi-level navigation in Free Fleet by implementing dynamic map switching for Nav2 robots during lift transitions.

**Feasibility:** ✅ Architecturally viable

**Effort:** 3-4 weeks of development (~780 new lines of code)

**Complexity:** Medium-High

**Risk:** Moderate (tight integration with Nav2 lifecycle and RMF lift coordination)

---

## Current State Analysis

### What Free Fleet Already Has

**File:** `patches/nav2_robot_adapter.py` (lines 449-465)

```python
def _handle_navigate_to_pose(self, map_name: str, x, y, z, yaw, nav_handle):
    if map_name != self.map_name:
        self.replan_counts += 1
        self.node.get_logger().error(
            f'Destination is on map [{map_name}], while robot '
            f'is on map [{self.map_name}], replan count [{self.replan_counts}]'
        )
        self.update_handle.more().replan()  # Rejects the navigation request
        return
```

**Key Finding:** Free Fleet **detects** map mismatches but only triggers replanning. It never actually switches maps.

### Why Map Switching Wasn't Implemented

**Nav2 Map Server Constraint:**
- The `yaml_filename` parameter is set **once at node launch**
- No ROS2 service exists to dynamically load new map files at runtime
- Lifecycle nodes don't support runtime parameter reconfiguration

**Free Fleet's Original Scope:**
- Designed for single-level warehouse/factory environments
- Most deployments don't require multi-floor navigation
- Multi-level was out of scope for initial release

---

## Proposed Architecture

### High-Level Design

```
┌─────────────────────────────────────────────────────────┐
│ RMF (Domain 55)                                         │
│  └─ TaskPlanner sends navigation goal to different map │
└─────────────────────────────────────────────────────────┘
                          ↓
┌─────────────────────────────────────────────────────────┐
│ Free Fleet - Nav2RobotAdapter (ENHANCED)               │
│  ├─ Detects map mismatch                               │
│  ├─ Identifies lift required for transition            │
│  ├─ Executes Level Transition Workflow:                │
│  │   1. Navigate to lift cabin on current level        │
│  │   2. Wait for lift arrival (monitor /lift_states)   │
│  │   3. Enter lift cabin (detect via position)         │
│  │   4. Request lift travel to target floor            │
│  │   5. Wait for lift travel completion                │
│  │   6. Switch map (lifecycle state change)            │
│  │   7. Reinitialize AMCL at lift exit waypoint        │
│  │   8. Exit lift cabin and resume navigation          │
│  └─ Continue to final destination on new level         │
└─────────────────────────────────────────────────────────┘
                          ↓
┌─────────────────────────────────────────────────────────┐
│ Nav2 (Domain 0)                                         │
│  ├─ map_server_L1 (active) ──────→ publishes /map      │
│  ├─ map_server_L2 (inactive) ─┐                        │
│  ├─ map_server_L3 (inactive) ─┤ (pre-launched)         │
│  │                             │                        │
│  │ On map switch L1→L2:        │                        │
│  │  - Deactivate L1 ───────────┘                        │
│  │  - Activate L2 ──────────────→ now publishes /map   │
│  │                                                      │
│  └─ AMCL reinitializes localization on new map         │
└─────────────────────────────────────────────────────────┘
```

### Key Components

**1. Multiple Map Server Strategy**

Instead of trying to change a single map server's map file at runtime, we:
- Launch one `map_server` node per level at startup
- Keep only one active (publishing `/map`) at a time
- Switch between them using lifecycle state transitions

**Advantages:**
- No runtime parameter reconfiguration needed
- Faster switching (just activate/deactivate)
- Each map stays loaded in memory

**2. Level Tracking State**

Add to `Nav2RobotAdapter`:
```python
self.current_level: str          # "L1", "L2", or "L3"
self.target_level: str | None    # Level we're transitioning to
self.in_lift_transition: bool    # Flag during lift travel
self.level_maps: dict            # "L1" → "/opt/maps/hotel_L1.yaml"
```

**3. Lift Coordination**

Subscribe to RMF topics:
- **`/lift_states`** (rmf_lift_msgs/LiftState) - Monitor lift positions and door states
- **`/lift_requests`** (rmf_lift_msgs/LiftRequest) - Request lift travel

Detect cabin entry/exit via position matching:
```python
if distance(robot_pose, lift_cabin_waypoint) < 0.5:  # Inside cabin
```

**4. AMCL Reinitialization**

After map switch, reset localization with known pose:
```python
# Publish to /<robot>/initialpose
initial_pose = get_lift_exit_pose(new_level, lift_name)
amcl_initial_pose_pub.publish(initial_pose)
```

---

## Implementation Details

### Phase 1: Multi-Map Server Launch

**File:** `config/nav2/tinybot_nav2_launch.py`

**Current (single map server):**
```python
Node(
    package='nav2_map_server',
    executable='map_server',
    name='map_server',
    namespace=robot_name,
    parameters=[{
        'use_sim_time': use_sim_time,
        'yaml_filename': map_yaml_file  # One map only
    }]
)
```

**Enhanced (multiple map servers):**
```python
# Define map files per level
level_maps = {
    'L1': '/opt/maps/hotel_L1.yaml',
    'L2': '/opt/maps/hotel_L2.yaml',
    'L3': '/opt/maps/hotel_L3.yaml'
}

map_server_nodes = []
lifecycle_managers = []

for level, map_file in level_maps.items():
    # Create map server for this level
    map_server = Node(
        package='nav2_map_server',
        executable='map_server',
        name=f'map_server_{level}',
        namespace=robot_name,
        parameters=[{
            'use_sim_time': use_sim_time,
            'yaml_filename': map_file
        }]
    )
    map_server_nodes.append(map_server)
    
    # Create lifecycle manager for this map server
    # Start L1 as active, others as inactive
    initial_state = 'active' if level == 'L1' else 'inactive'
    
    lifecycle_mgr = Node(
        package='nav2_lifecycle_manager',
        executable='lifecycle_manager',
        name=f'lifecycle_manager_map_{level}',
        namespace=robot_name,
        parameters=[{
            'autostart': True,
            'node_names': [f'map_server_{level}'],
            'bond_timeout': 4.0,
            'initial_state': initial_state  # L1 starts active
        }]
    )
    lifecycle_managers.append(lifecycle_mgr)

# Add all nodes to launch description
for node in map_server_nodes + lifecycle_managers:
    ld.add_action(node)
```

**Result:** Three map servers launched, only L1 active initially.

---

### Phase 2: Level Tracking in Nav2RobotAdapter

**File:** `patches/nav2_robot_adapter.py`

**Location:** Add to `__init__` method (after line 128)

```python
def __init__(self, name, configuration, robot_config_yaml, ...):
    # ... existing initialization ...
    
    # EXISTING
    self.map_name = self.robot_config_yaml['initial_map']
    self.map_frame = self.robot_config_yaml.get('map_frame', 'map')
    self.robot_frame = self.robot_config_yaml.get('robot_frame', 'base_footprint')
    
    # NEW: Multi-level support
    self.current_level = self.robot_config_yaml['initial_map']  # "L1"
    self.target_level = None
    self.in_lift_transition = False
    
    # Load map definitions per level from config
    self.level_maps = {}
    maps_config = self.robot_config_yaml.get('maps', {})
    for level_name, map_config in maps_config.items():
        self.level_maps[level_name] = {
            'map_url': map_config['map_url'],
            'lift_exit_poses': map_config.get('lift_exit_poses', {})
        }
    
    self.node.get_logger().info(
        f'Multi-level navigation enabled: {list(self.level_maps.keys())}'
    )
    
    # Lift state tracking
    self.lift_states = {}  # lift_name → LiftState message
    
    # Create ROS2 service clients and publishers
    self._setup_map_switching_infrastructure()

def _setup_map_switching_infrastructure(self):
    """Create service clients and subscriptions for map switching."""
    
    # Service client for lifecycle state changes
    self.lifecycle_clients = {}
    for level in self.level_maps.keys():
        client = self.node.create_client(
            ChangeState,
            f'/{self.name}/map_server_{level}/change_state'
        )
        self.lifecycle_clients[level] = client
    
    # Publisher for AMCL initial pose
    self.amcl_initial_pose_pub = self.node.create_publisher(
        PoseWithCovarianceStamped,
        f'/{self.name}/initialpose',
        10
    )
    
    # Subscriber for lift states
    self.lift_state_sub = self.node.create_subscription(
        LiftState,
        '/lift_states',
        self._lift_state_callback,
        10
    )
    
    # Publisher for lift requests
    self.lift_request_pub = self.node.create_publisher(
        LiftRequest,
        '/lift_requests',
        10
    )
    
    self.node.get_logger().info('Map-switching infrastructure ready')

def _lift_state_callback(self, msg: LiftState):
    """Track lift positions and door states."""
    self.lift_states[msg.lift_name] = msg
```

---

### Phase 3: Map Switching Logic

**File:** `patches/nav2_robot_adapter.py`

**Location:** New methods in `Nav2RobotAdapter` class

```python
def switch_map(self, new_level: str) -> bool:
    """
    Switch Nav2's active map to a different level.
    
    Uses lifecycle state management to activate/deactivate map servers.
    Only one map server publishes /map at a time.
    
    Args:
        new_level: Target level name (e.g., "L2")
    
    Returns:
        True if switch successful, False otherwise
    """
    if new_level not in self.level_maps:
        self.node.get_logger().error(
            f'Unknown level [{new_level}], available: {list(self.level_maps.keys())}'
        )
        return False
    
    if new_level == self.current_level:
        self.node.get_logger().info(
            f'Already on level [{new_level}], no switch needed'
        )
        return True
    
    old_level = self.current_level
    self.node.get_logger().info(
        f'Switching map: {old_level} → {new_level}'
    )
    
    # Step 1: Deactivate old map server
    if not self._change_map_server_state(old_level, 'deactivate'):
        self.node.get_logger().error(f'Failed to deactivate map_server_{old_level}')
        return False
    
    # Step 2: Activate new map server
    if not self._change_map_server_state(new_level, 'activate'):
        self.node.get_logger().error(f'Failed to activate map_server_{new_level}')
        # Try to reactivate old map server
        self._change_map_server_state(old_level, 'activate')
        return False
    
    # Step 3: Update state
    self.current_level = new_level
    self.map_name = new_level
    
    self.node.get_logger().info(
        f'Successfully switched to map [{new_level}]'
    )
    return True

def _change_map_server_state(self, level: str, transition: str) -> bool:
    """
    Change lifecycle state of a map server.
    
    Args:
        level: Level name (e.g., "L1")
        transition: 'activate' or 'deactivate'
    
    Returns:
        True if successful, False otherwise
    """
    client = self.lifecycle_clients.get(level)
    if not client:
        self.node.get_logger().error(f'No lifecycle client for level {level}')
        return False
    
    # Wait for service to be available
    if not client.wait_for_service(timeout_sec=5.0):
        self.node.get_logger().error(
            f'Lifecycle service for map_server_{level} not available'
        )
        return False
    
    # Map transition names to lifecycle transition IDs
    transition_ids = {
        'configure': 1,
        'cleanup': 2,
        'activate': 3,
        'deactivate': 4,
        'shutdown': 5
    }
    
    request = ChangeState.Request()
    request.transition.id = transition_ids.get(transition, 0)
    
    # Call service synchronously (blocking)
    future = client.call_async(request)
    rclpy.spin_until_future_complete(self.node, future, timeout_sec=10.0)
    
    if future.result() is not None and future.result().success:
        self.node.get_logger().info(
            f'Successfully {transition}d map_server_{level}'
        )
        return True
    else:
        self.node.get_logger().error(
            f'Failed to {transition} map_server_{level}'
        )
        return False

def reinitialize_amcl(self, pose: list[float]):
    """
    Reset AMCL localization with new pose on current map.
    
    Args:
        pose: [x, y, yaw] on the current level's map
    """
    pose_msg = PoseWithCovarianceStamped()
    pose_msg.header.stamp = self.node.get_clock().now().to_msg()
    pose_msg.header.frame_id = 'map'
    
    # Set position
    pose_msg.pose.pose.position.x = pose[0]
    pose_msg.pose.pose.position.y = pose[1]
    pose_msg.pose.pose.position.z = 0.0
    
    # Set orientation from yaw
    quat = quaternion_from_euler(0, 0, pose[2])
    pose_msg.pose.pose.orientation.x = quat[0]
    pose_msg.pose.pose.orientation.y = quat[1]
    pose_msg.pose.pose.orientation.z = quat[2]
    pose_msg.pose.pose.orientation.w = quat[3]
    
    # Set covariance (initial uncertainty after map switch)
    # Format: [x, y, z, roll, pitch, yaw] (6x6 matrix flattened)
    pose_msg.pose.covariance = [
        0.25, 0.0,  0.0, 0.0, 0.0, 0.0,   # x: ±0.5m
        0.0,  0.25, 0.0, 0.0, 0.0, 0.0,   # y: ±0.5m
        0.0,  0.0,  0.0, 0.0, 0.0, 0.0,   # z: ignored
        0.0,  0.0,  0.0, 0.0, 0.0, 0.0,   # roll: ignored
        0.0,  0.0,  0.0, 0.0, 0.0, 0.0,   # pitch: ignored
        0.0,  0.0,  0.0, 0.0, 0.0, 0.068  # yaw: ±15°
    ]
    
    self.amcl_initial_pose_pub.publish(pose_msg)
    
    self.node.get_logger().info(
        f'Reinitialized AMCL at ({pose[0]:.2f}, {pose[1]:.2f}, '
        f'{np.degrees(pose[2]):.1f}°) on map [{self.current_level}]'
    )
```

---

### Phase 4: Lift Transition Coordinator

**File:** `patches/nav2_robot_adapter.py`

**Location:** New methods in `Nav2RobotAdapter` class

```python
def execute_level_transition(
    self,
    from_level: str,
    to_level: str,
    lift_name: str,
    final_destination: list[float]
) -> bool:
    """
    Execute complete level transition via lift.
    
    Workflow:
    1. Robot navigates to lift cabin on current level (RMF handles)
    2. Wait for lift arrival at current floor
    3. Detect robot entry into lift cabin
    4. Request lift travel to target floor
    5. Wait for lift travel completion
    6. Switch map to target level
    7. Reinitialize AMCL at lift exit waypoint
    8. Robot exits cabin and continues to destination (RMF handles)
    
    Args:
        from_level: Starting level (e.g., "L1")
        to_level: Destination level (e.g., "L2")
        lift_name: Lift to use (e.g., "Lift1")
        final_destination: Final [x, y, yaw] on target level
    
    Returns:
        True if transition successful, False otherwise
    """
    self.in_lift_transition = True
    self.target_level = to_level
    
    try:
        self.node.get_logger().info(
            f'Starting level transition: {from_level} → {to_level} via {lift_name}'
        )
        
        # Step 1: Wait for lift arrival at current floor
        self.node.get_logger().info(f'Waiting for {lift_name} arrival at {from_level}...')
        if not self.wait_for_lift_arrival(lift_name, from_level, timeout=60.0):
            self.node.get_logger().error('Lift arrival timeout')
            return False
        
        # Step 2: Wait for lift doors to open
        if not self.wait_for_lift_doors(lift_name, 'OPEN', timeout=30.0):
            self.node.get_logger().error('Lift doors did not open')
            return False
        
        # Step 3: Detect robot entry into cabin
        # Note: RMF path should navigate robot into cabin
        self.node.get_logger().info('Waiting for robot to enter cabin...')
        entry_timeout = 60.0
        start_time = time.time()
        while time.time() - start_time < entry_timeout:
            if self.detect_lift_entry(self.get_pose()):
                self.node.get_logger().info(f'Robot entered {lift_name} cabin')
                break
            time.sleep(0.1)
        else:
            self.node.get_logger().error('Robot did not enter cabin in time')
            return False
        
        # Step 4: Request lift travel to destination floor
        self.node.get_logger().info(f'Requesting {lift_name} travel to {to_level}...')
        self.request_lift_travel(lift_name, to_level)
        
        # Step 5: Wait for lift travel completion
        if not self.wait_for_lift_travel(lift_name, to_level, timeout=120.0):
            self.node.get_logger().error('Lift travel timeout')
            return False
        
        # Step 6: Switch map to destination level
        self.node.get_logger().info(f'Switching map to {to_level}...')
        if not self.switch_map(to_level):
            self.node.get_logger().error('Map switch failed')
            return False
        
        # Step 7: Reinitialize AMCL at lift exit waypoint
        lift_exit_pose = self.get_lift_exit_pose(to_level, lift_name)
        self.node.get_logger().info(f'Reinitializing AMCL at lift exit...')
        self.reinitialize_amcl(lift_exit_pose)
        
        # Step 8: Wait for doors to open on new level
        if not self.wait_for_lift_doors(lift_name, 'OPEN', timeout=30.0):
            self.node.get_logger().error('Lift doors did not open on new level')
            return False
        
        self.node.get_logger().info(
            f'Level transition complete: {from_level} → {to_level}'
        )
        
        # Robot will now exit cabin and navigate to final destination
        # (RMF handles this via the original navigation command)
        return True
        
    except Exception as e:
        self.node.get_logger().error(
            f'Level transition exception: {type(e).__name__}: {e}'
        )
        return False
    
    finally:
        self.in_lift_transition = False
        self.target_level = None

def detect_lift_entry(self, robot_pose: list[float]) -> bool:
    """
    Detect if robot is currently inside a lift cabin.
    
    Checks robot position against all lift cabin waypoints on current level.
    
    Args:
        robot_pose: Current robot [x, y, yaw]
    
    Returns:
        True if inside any lift cabin, False otherwise
    """
    # Get lift cabin waypoints for current level from nav graph
    # (This requires access to parsed nav graph data)
    
    # For now, use config-based approach
    cabin_threshold = 0.5  # meters
    
    # Check against known cabin positions from level_maps config
    level_config = self.level_maps.get(self.current_level, {})
    cabin_poses = level_config.get('lift_cabin_poses', {})
    
    for lift_name, cabin_pose in cabin_poses.items():
        dist = np.sqrt(
            (robot_pose[0] - cabin_pose[0])**2 +
            (robot_pose[1] - cabin_pose[1])**2
        )
        
        if dist < cabin_threshold:
            self.node.get_logger().debug(
                f'Robot inside {lift_name} cabin (distance: {dist:.2f}m)'
            )
            return True
    
    return False

def wait_for_lift_arrival(self, lift_name: str, floor: str, timeout: float = 60.0) -> bool:
    """Wait for lift to arrive at specified floor."""
    start_time = time.time()
    
    while time.time() - start_time < timeout:
        lift_state = self.lift_states.get(lift_name)
        
        if lift_state and lift_state.current_floor == floor:
            self.node.get_logger().info(
                f'{lift_name} arrived at {floor}'
            )
            return True
        
        time.sleep(0.1)
    
    return False

def wait_for_lift_doors(self, lift_name: str, state: str, timeout: float = 30.0) -> bool:
    """
    Wait for lift doors to reach specified state.
    
    Args:
        lift_name: Lift name
        state: 'OPEN' or 'CLOSED'
        timeout: Maximum wait time in seconds
    """
    start_time = time.time()
    
    while time.time() - start_time < timeout:
        lift_state = self.lift_states.get(lift_name)
        
        if lift_state and lift_state.door_state == state:
            self.node.get_logger().info(
                f'{lift_name} doors are {state}'
            )
            return True
        
        time.sleep(0.1)
    
    return False

def wait_for_lift_travel(self, lift_name: str, destination_floor: str, timeout: float = 120.0) -> bool:
    """Wait for lift to complete travel to destination floor."""
    start_time = time.time()
    
    while time.time() - start_time < timeout:
        lift_state = self.lift_states.get(lift_name)
        
        if lift_state and lift_state.current_floor == destination_floor:
            self.node.get_logger().info(
                f'{lift_name} reached {destination_floor}'
            )
            return True
        
        time.sleep(0.1)
    
    return False

def request_lift_travel(self, lift_name: str, destination_floor: str):
    """Request lift to travel to destination floor."""
    request = LiftRequest()
    request.lift_name = lift_name
    request.destination_floor = destination_floor
    request.request_type = LiftRequest.REQUEST_AGV_MODE
    request.door_state = LiftRequest.DOOR_OPEN
    
    self.lift_request_pub.publish(request)
    
    self.node.get_logger().info(
        f'Requested {lift_name} to {destination_floor}'
    )

def get_lift_exit_pose(self, level: str, lift_name: str) -> list[float]:
    """
    Get the pose where robot exits lift on specified level.
    
    Args:
        level: Level name (e.g., "L2")
        lift_name: Lift name (e.g., "Lift1")
    
    Returns:
        [x, y, yaw] pose on the level's map
    """
    level_config = self.level_maps.get(level, {})
    exit_poses = level_config.get('lift_exit_poses', {})
    
    if lift_name not in exit_poses:
        self.node.get_logger().warn(
            f'No exit pose defined for {lift_name} on {level}, using default'
        )
        return [0.0, 0.0, 0.0]
    
    return exit_poses[lift_name]

def find_lift_between_levels(self, from_level: str, to_level: str) -> tuple[str, list, list] | None:
    """
    Find a lift that connects two levels.
    
    Args:
        from_level: Starting level
        to_level: Destination level
    
    Returns:
        (lift_name, from_cabin_pose, to_cabin_pose) if found, None otherwise
    """
    # Query nav graph for lift_lanes connecting these levels
    # For now, use hardcoded mapping
    
    lift_connections = {
        ('L1', 'L2'): 'Lift1',
        ('L2', 'L1'): 'Lift1',
        ('L2', 'L3'): 'Lift2',
        ('L3', 'L2'): 'Lift2',
    }
    
    lift_name = lift_connections.get((from_level, to_level))
    
    if lift_name:
        return (lift_name, [], [])  # TODO: Add cabin poses
    
    return None
```

---

### Phase 5: Integration with RMF Navigation Callback

**File:** `patches/nav2_robot_adapter.py`

**Location:** Modify `_handle_navigate_to_pose` (replace lines 449-465)

```python
def _handle_navigate_to_pose(self, map_name: str, x, y, z, yaw, nav_handle):
    """
    Handle navigation command from RMF.
    
    If destination is on a different level, triggers level transition.
    Otherwise proceeds with normal navigation.
    """
    
    # Check if destination is on different map/level
    if map_name != self.current_level:
        self.node.get_logger().info(
            f'Cross-level navigation: {self.current_level} → {map_name}'
        )
        
        # Find lift connecting these levels
        lift_info = self.find_lift_between_levels(self.current_level, map_name)
        
        if lift_info:
            lift_name, _, _ = lift_info
            
            self.node.get_logger().info(
                f'Will use {lift_name} for level transition'
            )
            
            # Execute level transition
            destination_pose = [x, y, yaw]
            success = self.execute_level_transition(
                self.current_level,
                map_name,
                lift_name,
                destination_pose
            )
            
            if not success:
                self.node.get_logger().error(
                    'Level transition failed, requesting replan'
                )
                self.replan_counts += 1
                self.update_handle.more().replan()
                return
            
            # After successful transition, current_level is now map_name
            # Fall through to normal navigation to final destination
            
        else:
            # No lift found connecting these levels
            self.node.get_logger().error(
                f'No lift connects {self.current_level} and {map_name}, '
                f'cannot navigate'
            )
            self.replan_counts += 1
            self.update_handle.more().replan()
            return
    
    # Normal navigation on current level
    # ... existing navigation code continues ...
    self._send_nav2_goal(x, y, yaw, nav_handle)
```

---

### Phase 6: Configuration Changes

**File:** `config/free_fleet/tinybot_fleet_config_multilevel.yaml`

**Enhanced configuration with lift exit poses:**

```yaml
rmf_fleet:
  name: "turtlebot3"
  # ... existing fleet config ...
  
  robots:
    robot_1:
      charger: "charger_1"
      responsive_wait: False
      navigation_stack: 2
      init_timeout_sec: 60
      service_call_timeout_sec: 10.0
      initial_map: "L1"
      map_frame: "map"
      robot_frame: "base_footprint"
      
      # Map definitions per level
      maps:
        L1:
          map_url: "/opt/maps/hotel_L1.yaml"
          # Where robot exits each lift on this level
          lift_exit_poses:
            Lift1: [52.5, 27.5, 0.0]  # [x, y, yaw]
          # Where each lift cabin is on this level (for detection)
          lift_cabin_poses:
            Lift1: [52.5, 27.5]  # [x, y]
        
        L2:
          map_url: "/opt/maps/hotel_L2.yaml"
          lift_exit_poses:
            Lift1: [57.5, 27.5, 3.14159]  # Exit facing opposite direction
            Lift2: [112.5, 27.5, 0.0]
          lift_cabin_poses:
            Lift1: [57.5, 27.5]
            Lift2: [112.5, 27.5]
        
        L3:
          map_url: "/opt/maps/hotel_L3.yaml"
          lift_exit_poses:
            Lift2: [117.5, 27.5, 3.14159]
          lift_cabin_poses:
            Lift2: [117.5, 27.5]
```

---

## Map File Generation

**Challenge:** Current single map file contains all three levels horizontally. Need to split into separate map files per level.

**Option A: Manual Cropping**

Use image editing to crop `hotel_multilevel.png` into three sections:
- `hotel_L1.png` - X coordinates 5-45m
- `hotel_L2.png` - X coordinates 65-105m  
- `hotel_L3.png` - X coordinates 125-165m

Update corresponding `.yaml` files with cropped dimensions.

**Option B: Automated Script**

Create `scripts/generate_map_splits.py`:

```python
#!/usr/bin/env python3
"""Split hotel multi-level map into separate level maps."""

import yaml
from PIL import Image

# Define crop regions (x1, y1, x2, y2) in pixels
# Assuming 20 pixels/meter
CROP_REGIONS = {
    'L1': (100, 200, 900, 1000),   # Lobby area
    'L2': (1300, 200, 2100, 1000),  # Rooms area
    'L3': (2500, 200, 3300, 1000),  # Suites area
}

def split_map(input_image, input_yaml, output_dir):
    """Split single map into multiple level maps."""
    
    # Load original image
    img = Image.open(input_image)
    
    # Load original YAML
    with open(input_yaml) as f:
        base_yaml = yaml.safe_load(f)
    
    for level, crop_box in CROP_REGIONS.items():
        # Crop image
        cropped = img.crop(crop_box)
        output_img = f'{output_dir}/hotel_{level}.png'
        cropped.save(output_img)
        
        # Update YAML
        level_yaml = base_yaml.copy()
        level_yaml['image'] = f'hotel_{level}.png'
        
        # Adjust origin based on crop
        # ... calculate new origin ...
        
        output_yaml = f'{output_dir}/hotel_{level}.yaml'
        with open(output_yaml, 'w') as f:
            yaml.dump(level_yaml, f)
        
        print(f'Generated {output_img} and {output_yaml}')

if __name__ == '__main__':
    split_map(
        '/opt/maps/hotel_multilevel.png',
        '/opt/maps/hotel_multilevel.yaml',
        '/opt/maps'
    )
```

---

## Import Statements Required

**File:** `patches/nav2_robot_adapter.py`

Add to imports section:

```python
import time
import numpy as np
from lifecycle_msgs.srv import ChangeState
from geometry_msgs.msg import PoseWithCovarianceStamped, Pose, Point, Quaternion
from std_msgs.msg import Header
from rmf_lift_msgs.msg import LiftState, LiftRequest
from tf_transformations import quaternion_from_euler
```

---

## Testing Plan

### Unit Tests

**Test map switching:**
```python
def test_switch_map():
    adapter = Nav2RobotAdapter(...)
    assert adapter.current_level == "L1"
    
    success = adapter.switch_map("L2")
    assert success
    assert adapter.current_level == "L2"
```

**Test lift detection:**
```python
def test_detect_lift_entry():
    adapter = Nav2RobotAdapter(...)
    
    # Robot outside cabin
    robot_pose = [50.0, 27.5, 0.0]
    assert not adapter.detect_lift_entry(robot_pose)
    
    # Robot inside cabin
    robot_pose = [52.5, 27.5, 0.0]
    assert adapter.detect_lift_entry(robot_pose)
```

### Integration Tests

**Test with mock lift supervisor:**
1. Launch Nav2 with multiple map servers
2. Trigger map switch via service call
3. Verify `/map` topic content changes
4. Verify AMCL reinitializes on new map

**Test end-to-end level transition:**
1. Submit RMF task: L1 waypoint → L2 waypoint
2. Monitor robot navigation to lift cabin
3. Mock lift arrival and door opening
4. Verify map switch occurs
5. Verify robot completes navigation on L2

### Real-World Testing

**Prerequisites:**
- Multi-level Gazebo world with functioning lifts
- Lift supervisor node running
- Three separate map files for L1, L2, L3

**Test Cases:**
1. Single-level navigation (baseline)
2. Two-level navigation (L1 → L2)
3. Three-level navigation (L1 → L2 → L3)
4. Multi-robot coordination (2 robots using same lift)
5. Lift failure scenarios (timeout, door stuck)

---

## Estimated Timeline

### Week 1: Infrastructure Setup
- **Day 1-2:** Multi-map server launch file modifications
- **Day 3-4:** Map file generation/splitting
- **Day 5:** Lifecycle state management implementation

### Week 2: Core Map Switching
- **Day 1-2:** Level tracking state in Nav2RobotAdapter
- **Day 3-4:** Map switching logic and service clients
- **Day 5:** AMCL reinitialization

### Week 3: Lift Coordination
- **Day 1-2:** Lift state subscription and tracking
- **Day 2-3:** Cabin detection and lift request publishing
- **Day 4-5:** Complete level transition workflow

### Week 4: Integration & Testing
- **Day 1-2:** RMF navigation callback integration
- **Day 3:** Unit and integration testing
- **Day 4-5:** End-to-end testing, bug fixes, edge cases

**Total:** 20 working days (4 weeks)

---

## Risk Mitigation

### Risk 1: Timing Issues
- **Mitigation:** Generous timeouts (60s+), extensive logging
- **Fallback:** Create RMF issue ticket, cancel task

### Risk 2: Localization Drift
- **Mitigation:** Known lift exit poses, high initial covariance
- **Fallback:** Global localization service call if drift detected

### Risk 3: Multiple Robots
- **Mitigation:** Trust RMF lift supervisor queuing
- **Fallback:** Add queue detection in Free Fleet if needed

### Risk 4: Map Switch Latency
- **Mitigation:** Pre-launch all map servers (faster than restart)
- **Monitoring:** Log lifecycle transition times

### Risk 5: State Machine Deadlocks
- **Mitigation:** Comprehensive timeout handling at each step
- **Recovery:** `in_lift_transition` flag cleanup in finally block

---

## Success Criteria

**Phase 1 Complete:**
- ✅ Multiple map servers launched
- ✅ Only one publishes `/map` at a time
- ✅ Lifecycle state changes work

**Phase 2 Complete:**
- ✅ Level tracking state maintained correctly
- ✅ Service clients and publishers created
- ✅ Lift state messages received

**Phase 3 Complete:**
- ✅ Map switching function works
- ✅ AMCL reinitializes on new map
- ✅ TF tree remains valid after switch

**Phase 4 Complete:**
- ✅ Lift arrival detection works
- ✅ Cabin entry/exit detection works
- ✅ Complete transition workflow executes

**Final Integration:**
- ✅ RMF multi-level task assigned
- ✅ Robot navigates L1 → L2 successfully
- ✅ No manual intervention required
- ✅ Multi-robot scenarios handled

---

## Files Modified Summary

| File | Purpose | LOC | Complexity |
|------|---------|-----|------------|
| `patches/nav2_robot_adapter.py` | Core implementation | +400 | High |
| `patches/fleet_adapter.py` | Pass lift subscribers | +50 | Low |
| `config/nav2/tinybot_nav2_launch.py` | Multi-map servers | +100 | Medium |
| `config/free_fleet/tinybot_fleet_config_multilevel.yaml` | Lift exit poses | +30 | Low |
| `scripts/generate_map_splits.py` | NEW: Map splitting | +200 | Medium |

**Total:** ~780 lines of code

---

## Next Steps

**To Proceed with Implementation:**

1. **Generate map files** - Split hotel_multilevel into L1, L2, L3 maps
2. **Modify launch file** - Add multiple map server nodes
3. **Enhance Nav2RobotAdapter** - Add level tracking and map switching
4. **Integrate lift coordination** - Add lift state monitoring
5. **Test incrementally** - Validate each phase before moving to next

**To Defer Implementation:**

1. **Document current findings** (this document)
2. **Commit to repository** for future reference
3. **Continue with single-level demo** (working state)
4. **Revisit when resources available**

---

## References

- [Nav2 Lifecycle Management](https://navigation.ros.org/configuration/packages/configuring-lifecycle.html)
- [RMF Lift Integration](https://osrf.github.io/ros2multirobotbook/integration_lifts.html)
- [Free Fleet GitHub](https://github.com/open-rmf/free_fleet)
- [AMCL Configuration](https://navigation.ros.org/configuration/packages/configuring-amcl.html)

---

**Document Version:** 1.0  
**Date:** 2026-09-04  
**Author:** Research Agent (60,807 tokens)  
**Status:** Implementation plan ready for execution or deferral
