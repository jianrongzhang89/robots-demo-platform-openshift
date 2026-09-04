# Hotel + Nav2 Integration Design

## Objective

Integrate Nav2 robots with the hotel world to enable multi-level navigation testing with real TurtleBot3 robots (not slotcar plugins).

**Status:** Design phase

**Date:** 2026-09-04

---

## Current Architecture Analysis

### Hotel Mode (hotel.enabled=true)

**Single Pod Deployment:**
```
┌─────────────────────────────────────────────────┐
│ hotel-sim Pod                                   │
│  ├─ Gazebo (hotel world + slotcar robots)      │
│  ├─ RMF building_map_server                    │
│  ├─ RMF door_supervisor, lift_supervisor       │
│  ├─ RMF traffic_schedule, task_dispatcher      │
│  ├─ 3x fleet_adapters (slotcar fleets)         │
│  └─ rmf_puppet_controller.py (HTTP workaround) │
│                                                 │
│ Domain: 0 (localhost DDS)                       │
│ No Zenoh, No Nav2                               │
└─────────────────────────────────────────────────┘
```

**Characteristics:**
- ✅ Hotel world with 3 levels, lifts, doors
- ✅ RMF full stack working
- ✅ 4 robots patrolling (deliveryBot, tinyBot, 2x cleanerBot)
- ❌ Uses slotcar plugin (not Nav2)
- ❌ Single pod (not distributed)
- ❌ No Zenoh federation
- ❌ Violates hard requirements

### Multi-Robot Mode (hotel.enabled=false)

**Multi-Pod Deployment:**
```
┌──────────────────────┐
│ gazebo-sim Pod       │
│  └─ Gazebo world     │
│     (turtlebot3_*)   │
│ Domain: 0            │
└──────────────────────┘
         ↕ Zenoh
┌──────────────────────┐
│ zenoh-router Pod     │
│  └─ Zenoh router     │
│     tcp:7447         │
└──────────────────────┘
         ↕ Zenoh
┌──────────────────────┐  ┌──────────────────────┐
│ robot-nav-robot-1    │  │ robot-nav-robot-2    │
│  ├─ Nav2 stack       │  │  ├─ Nav2 stack       │
│  └─ Zenoh bridge     │  │  └─ Zenoh bridge     │
│ Domain: 0            │  │ Domain: 0            │
└──────────────────────┘  └──────────────────────┘
         ↕ Zenoh              ↕ Zenoh
┌──────────────────────┐
│ rmf-core Pod         │
│  ├─ Fleet adapters   │
│  ├─ Dispatcher       │
│  └─ Free Fleet       │
│ Domain: 55           │
└──────────────────────┘
```

**Characteristics:**
- ✅ Multi-pod architecture
- ✅ Nav2 robots (TurtleBot3)
- ✅ Zenoh federation
- ✅ Meets hard requirements
- ❌ Uses turtlebot3_house/world (not hotel)
- ❌ No lifts, no multi-level

---

## Target Architecture: Hotel + Nav2 Hybrid

### Design Option A: Minimal Changes (Recommended)

**Keep hotel-sim pod, add Nav2 pods and Zenoh**

```
┌─────────────────────────────────────────────────┐
│ hotel-sim Pod (MODIFIED)                        │
│  ├─ Gazebo (hotel world)                        │
│  │   └─ TurtleBot3 robots (NOT slotcar)        │
│  ├─ RMF building_map_server                     │
│  ├─ RMF door_supervisor, lift_supervisor        │
│  ├─ RMF traffic_schedule, task_dispatcher       │
│  ├─ Fleet adapters (removed - moved to rmf-core)│
│  └─ Zenoh bridge (NEW - publish Gazebo topics)  │
│                                                  │
│ Domain: 0                                        │
└─────────────────────────────────────────────────┘
         ↕ Zenoh
┌─────────────────────────────────────────────────┐
│ zenoh-router Pod (NEW)                          │
│  └─ Zenoh router tcp:7447                       │
└─────────────────────────────────────────────────┘
         ↕ Zenoh
┌──────────────────────┐  ┌──────────────────────┐
│ robot-nav-robot-1    │  │ robot-nav-robot-2    │
│  ├─ Nav2 stack       │  │  ├─ Nav2 stack       │
│  │   (AMCL, planners)│  │  │   (with map-switch)│
│  └─ Zenoh bridge     │  │  └─ Zenoh bridge     │
│ Domain: 0            │  │ Domain: 0            │
└──────────────────────┘  └──────────────────────┘
         ↕ Zenoh
┌─────────────────────────────────────────────────┐
│ rmf-core Pod (NEW)                              │
│  ├─ Free Fleet adapters (turtlebot3 fleet)     │
│  │   └─ Multi-level map-switching enabled      │
│  ├─ Task dispatcher (from hotel-sim)            │
│  └─ Zenoh bridge (Domain 0 ↔ 55)               │
│                                                  │
│ Domain: 55                                       │
└─────────────────────────────────────────────────┘
```

**Changes Required:**

1. **hotel-sim pod:**
   - Remove slotcar robot spawns
   - Spawn TurtleBot3 robots instead
   - Add Zenoh bridge sidecar
   - Move fleet adapters to rmf-core pod
   - Keep supervisors (door, lift), building_map_server

2. **NEW zenoh-router pod:**
   - Reuse existing deployment-zenoh-router.yaml

3. **NEW robot-nav pods:**
   - Reuse existing deployment-nav2.yaml
   - Set ENABLE_MULTILEVEL=true
   - Use hotel_L{1,2,3}.yaml maps

4. **NEW rmf-core pod:**
   - Reuse existing deployment-rmf-core.yaml
   - Use hotel nav_graph.yaml
   - Use hotel fleet_config.yaml

---

### Design Option B: Full Separation

**Separate Gazebo from RMF supervisors**

```
┌──────────────────────┐
│ gazebo-hotel Pod     │
│  └─ Gazebo + hotel   │
│     + TurtleBot3     │
│ Domain: 0            │
└──────────────────────┘
         ↕ Zenoh
┌──────────────────────┐
│ zenoh-router Pod     │
└──────────────────────┘
         ↕ Zenoh
┌──────────────────────┐  ┌──────────────────────┐
│ robot-nav-robot-1    │  │ robot-nav-robot-2    │
│ Domain: 0            │  │ Domain: 0            │
└──────────────────────┘  └──────────────────────┘
         ↕ Zenoh
┌─────────────────────────────────────────────────┐
│ rmf-hotel-core Pod                              │
│  ├─ building_map_server                         │
│  ├─ door_supervisor, lift_supervisor            │
│  ├─ traffic_schedule, task_dispatcher           │
│  ├─ Free Fleet adapters                         │
│  └─ Zenoh bridge                                │
│ Domain: 55                                       │
└─────────────────────────────────────────────────┘
```

**Pros:**
- ✅ Clean separation of concerns
- ✅ Gazebo can be restarted without affecting RMF

**Cons:**
- ❌ More changes required
- ❌ Need to split hotel-sim entrypoint
- ❌ More complex configuration

**Verdict:** Option A is simpler and faster to implement.

---

## Implementation Plan: Option A

### Phase 1: Modify Hotel Robot Spawns

**Goal:** Replace slotcar with TurtleBot3 in hotel world

**Files to Modify:**
- Hotel launch file or SDF
- Remove slotcar plugin references
- Add TurtleBot3 model spawns

**Challenge:** Hotel world uses custom spawn scripts for slotcar fleets
- Need to find where deliveryBot, tinyBot, cleanerBot are spawned
- Replace with TurtleBot3 SDF includes

**Location:** Likely in `rmf_demos/rmf_demos_gz/worlds/hotel.sdf` or launch files

---

### Phase 2: Add Zenoh Bridge to Hotel Pod

**Goal:** Publish Gazebo topics (clock, model states, sensors) to Zenoh

**Sidecar Container:**
```yaml
- name: zenoh-bridge-gazebo
  image: eclipse/zenoh-bridge-ros2dds:0.11.0
  args: ["-c", "/zenoh-config/gazebo-bridge.json5"]
  env:
    - name: ROS_DOMAIN_ID
      value: "0"
  volumeMounts:
    - name: zenoh-config
      mountPath: /zenoh-config/gazebo-bridge.json5
      subPath: gazebo-bridge.json5
```

**Zenoh Config (gazebo-bridge.json5):**
```json5
{
  mode: "client",
  connect: {
    endpoints: ["tcp/zenoh-router:7447"]
  },
  plugins: {
    ros2dds: {
      domain: 0,
      allow: {
        publishers: [
          "/clock",
          "/world/hotel/model/.*/link/.*/sensor/.*",
          "/model/.*"
        ],
        subscribers: [
          "/model/.*/cmd_vel"
        ]
      }
    }
  }
}
```

---

### Phase 3: Deploy Separate Pods

**Deploy in order:**

1. **zenoh-router**
   ```bash
   # Already exists in templates
   # Just enable in values-hotel-nav2.yaml
   ```

2. **hotel-sim (modified)**
   ```bash
   # TurtleBot3 robots + Zenoh bridge
   # Supervisors + building_map_server only
   ```

3. **robot-nav pods**
   ```bash
   # Set ENABLE_MULTILEVEL=true
   # Set MAP_LEVEL=L1 (initial)
   # Use hotel map files
   ```

4. **rmf-core**
   ```bash
   # Free Fleet adapter
   # Nav graph: hotel multilevel
   # Fleet config: hotel with lift poses
   ```

---

### Phase 4: Configuration Files

**Create:** `values-hotel-nav2.yaml`

```yaml
namespace: ros2-hotel-nav2

# Enable multi-pod components
hotel:
  enabled: true  # Still need hotel-sim for Gazebo + supervisors
  spawnSlotcars: false  # NEW FLAG: disable slotcar spawns
  spawnTurtleBot3: true  # NEW FLAG: enable TurtleBot3 spawns

# Enable other pods
gazebo:
  enabled: false  # hotel-sim includes Gazebo

zenohRouter:
  enabled: true  # NEW: Enable Zenoh federation

rmf:
  enabled: true  # NEW: Enable rmf-core pod
  image: <rmf-image-with-free-fleet>
  navGraph: /opt/rmf/hotel_nav_graph_multilevel_true.yaml
  fleetConfig: /opt/rmf/fleet_config.yaml

robots:
  - name: robot_1
    initialPose:
      xPos: 20.0
      yPos: 30.0
      yaw: 0.0
  - name: robot_2
    initialPose:
      xPos: 10.0
      yPos: 30.0
      yaw: 0.0

nav2:
  enableMultilevel: true
  initialLevel: L1
  maps:
    L1: /opt/maps/hotel_L1.yaml
    L2: /opt/maps/hotel_L2.yaml
    L3: /opt/maps/hotel_L3.yaml
```

---

## Challenges and Solutions

### Challenge 1: TurtleBot3 Spawning in Hotel World

**Problem:** Hotel world expects slotcar robots, not TurtleBot3

**Solution:**
- Modify hotel launch file to accept robot type parameter
- Add TurtleBot3 model includes to hotel.sdf
- Position robots at charger waypoints from nav graph

**Alternative:** Use `gz service` to spawn robots at runtime

```bash
gz service -s /world/hotel/create \
  --reqtype gz.msgs.EntityFactory \
  --reptype gz.msgs.Boolean \
  --timeout 2000 \
  --req 'sdf: "<model name=\"robot_1\">...</model>"'
```

---

### Challenge 2: Map Coordinate Alignment

**Problem:** Hotel world coordinates vs. map coordinates

**Current State:**
- Hotel world origin: Gazebo (0,0,0)
- Hotel map origin: [-5.0, -30.0, 0.0]

**Solution:**
- Keep map origin as-is
- Spawn robots at map coordinates
- AMCL will localize correctly

**Verification:**
- Charger_1 nav graph: (8.0, 35.0) in map frame
- Should match Gazebo coordinates after spawn

---

### Challenge 3: Multi-Level Map Files in Container

**Problem:** Need hotel_L{1,2,3}.yaml files in all pods

**Solution:**
- Add maps to ConfigMap or build into image
- Mount in robot-nav pods at /opt/maps/
- Reference in fleet_config.yaml

**ConfigMap:**
```yaml
apiVersion: v1
kind: ConfigMap
metadata:
  name: hotel-maps
data:
  hotel_L1.yaml: |
    image: hotel_L1.pgm
    resolution: 0.05
    origin: [0.0, -30.0, 0.0]
    ...
```

---

### Challenge 4: Lift Supervisor Integration

**Problem:** Lift supervisor needs to control Gazebo lifts

**Current State:**
- Hotel world has lift plugins
- Subscribes to `/lift_requests`
- Publishes `/lift_states`

**Solution:**
- Keep lift supervisor in hotel-sim pod (Domain 0)
- Zenoh bridge publishes lift topics to Domain 55
- RMF core (Domain 55) can coordinate lifts

**Bridge Config:**
```json5
publishers: [
  "/lift_states"
],
subscribers: [
  "/lift_requests"
]
```

---

## Testing Plan

### Test 1: Hotel World with TurtleBot3

**Verify:**
- Hotel world loads in Gazebo
- 2 TurtleBot3 robots spawn
- Robots have sensors (LiDAR)
- No slotcar robots

**Command:**
```bash
oc logs -n ros2-hotel-nav2 -l app=hotel-sim | grep "model.*robot"
```

---

### Test 2: Zenoh Federation

**Verify:**
- Zenoh router running
- Bridges connected
- Topics visible cross-domain

**Commands:**
```bash
# In hotel-sim pod (Domain 0)
ros2 topic list | grep clock

# In rmf-core pod (Domain 55)
ros2 topic list | grep clock  # Should see via Zenoh
```

---

### Test 3: Nav2 Localization

**Verify:**
- AMCL publishes pose
- TF tree valid (map → robot_1/base_footprint)
- Particle cloud converges

**Commands:**
```bash
ros2 topic echo /robot_1/amcl_pose
ros2 run tf2_ros tf2_echo map robot_1/base_footprint
```

---

### Test 4: Free Fleet Registration

**Verify:**
- Robots register to fleet
- RMF sees robot states
- Tasks can be assigned

**Commands:**
```bash
# Check fleet states
ros2 topic echo /fleet_states

# Expected: turtlebot3 fleet with robot_1, robot_2
```

---

### Test 5: Single-Level Navigation

**Verify:**
- Nav2 navigation works
- RMF task dispatch works
- Robot completes patrol on L1

**Command:**
```bash
ros2 run rmf_demos_tasks dispatch_patrol \
  -F turtlebot3 -R robot_1 \
  -p lobby_west lobby_east -n 1 \
  --use_sim_time
```

---

### Test 6: Multi-Level Navigation

**Verify:**
- Cross-level task accepted
- Map switching executes
- Level transition completes
- Robot arrives on L2

**Command:**
```bash
ros2 run rmf_demos_tasks dispatch_patrol \
  -F turtlebot3 -R robot_1 \
  -p lobby_center L2_center -n 1 \
  --use_sim_time
```

---

## Timeline Estimate

| Phase | Task | Estimated Time |
|-------|------|----------------|
| 1 | Modify hotel robot spawns | 2-4 hours |
| 2 | Add Zenoh bridge to hotel-sim | 1 hour |
| 3 | Create values-hotel-nav2.yaml | 1 hour |
| 4 | Deploy and verify pods | 2 hours |
| 5 | Test single-level navigation | 2 hours |
| 6 | Test multi-level navigation | 4 hours |
| **Total** | **12-16 hours** | **2 days** |

---

## Rollback Plan

If integration fails:

**Option 1: Disable Nav2, revert to slotcar**
```yaml
hotel:
  spawnSlotcars: true
  spawnTurtleBot3: false
```

**Option 2: Use turtlebot3_house world**
- Faster to get Nav2 + Free Fleet working
- Lose multi-level capability
- Good for testing map-switching in single-level scenario

---

## Success Criteria

✅ **Minimum Viable:**
- TurtleBot3 robots spawn in hotel world
- Nav2 navigation works on single level
- Free Fleet registration successful

✅ **Full Success:**
- Multi-level tasks assigned and executed
- Map switching occurs during lift transitions
- AMCL reinitializes correctly
- Robots complete cross-level navigation

---

## Next Steps

1. **Locate hotel robot spawn mechanism**
   - Find where slotcar robots are defined
   - Determine how to replace with TurtleBot3

2. **Create hotel-nav2 Helm values**
   - Based on Option A architecture
   - Enable multi-pod components

3. **Implement and test incrementally**
   - Start with single TurtleBot3 spawn
   - Add Nav2 pod once spawn works
   - Add RMF once Nav2 works
   - Test multi-level last

---

**Status:** Design complete, ready for implementation  
**Next:** Locate hotel robot spawn code
