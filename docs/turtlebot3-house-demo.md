# TurtleBot3 House Demo — Open-RMF + Nav2 in a 3D House Environment

A cloud-native robotics demo running two TurtleBot3 Waffle robots inside a
realistic 3D house world (`turtlebot3_house`) on OpenShift, demonstrating
[Open-RMF](https://www.open-rmf.org/) fleet management with
[Nav2](https://nav2.ros.org/) autonomous navigation.

**Branch**: `turtlebot3-house-demo`  
**Namespace**: `ros2-turtlebot3-house`  
**Image**: `quay.io/jianrzha/ros2-demo:turtlebot3-house`

---

## What the Demo Shows

Two TurtleBot3 Waffle robots patrol their respective corridors inside a
furnished 3D house:

- **Robot_1 (blue)** — patrols the **west corridor**: `robot_1_home (-1.5, -0.5)` ↔ `sw_open (-1.5, -1.5)`
- **Robot_2 (red)** — patrols the **east corridor**: `robot_2_home (1.5, -0.5)` ↔ `se_open (1.5, -1.5)`

Both robots are dispatched and tracked by **Open-RMF** using the `dispatch_patrol`
task with the `robot_task_request` API (direct robot assignment, bypassing the
bidding mechanism). Each robot's route is planned by the **RMF free_fleet_adapter**
against the house nav graph, and executed by **Nav2** (bt_navigator + Regulated
Pure Pursuit controller).

### Demo Sequence

```
[Operator] dispatch_patrol -R robot_1 -p robot_1_home sw_open -n 20
[Operator] dispatch_patrol -R robot_2 -p robot_2_home se_open -n 20

robot_1: robot_1_home → (south) → sw_open → (north) → robot_1_home → ...
robot_2: robot_2_home → (south) → se_open → (north) → robot_2_home → ...
```

---

## Architecture

```
┌─────────────────────── OpenShift namespace: ros2-turtlebot3-house ──────────────────────┐
│                                                                                          │
│  ┌────────────────────────┐                                                              │
│  │  Pod: zenoh-router     │  ← central Zenoh hub (TCP :7447)                            │
│  └──────────┬─────────────┘                                                              │
│             │                                                                            │
│   ▼                    ▼                        ▼                    ▼                   │
│  ┌──────────────────┐  ┌──────────────────┐  ┌──────────────────┐  ┌────────────────┐  │
│  │  Pod: gazebo-sim │  │ Pod: robot-nav-1 │  │ Pod: robot-nav-2 │  │ Pod: rmf-core  │  │
│  │                  │  │                  │  │                  │  │                │  │
│  │  gz sim (server) │  │  Nav2 bringup    │  │  Nav2 bringup    │  │ free_fleet_    │  │
│  │  turtlebot3_house│  │  slam_mapping    │  │  slam_mapping    │  │ adapter        │  │
│  │  robot_state_pub │  │  planner (A*)    │  │  planner (A*)    │  │ (both robots)  │  │
│  │  gz→ROS2 bridge  │  │  RPP controller  │  │  RPP controller  │  │                │  │
│  │                  │  │  nav2_relay.py   │  │  nav2_relay.py   │  │ RMF traffic    │  │
│  │                  │  │  odom→amcl relay │  │  odom→amcl relay │  │ manager        │  │
│  └──────────────────┘  └──────────────────┘  └──────────────────┘  └────────────────┘  │
└──────────────────────────────────────────────────────────────────────────────────────────┘
```

### Task Flow

```
dispatch_patrol -F turtlebot3 -R robot_1 -p robot_1_home sw_open --use_sim_time
  → RMF task dispatcher (rmf_task_ros2)
    → free_fleet_adapter (assigns task to robot_1)
      → rmf_navigate_cmd (Zenoh: robot_1/rmf_navigate_cmd)
        → nav2_relay.py (converts world→map frame, calls navigate_to_pose)
          → Nav2 bt_navigator → RPP controller → /cmd_vel → Gazebo
```

**Key difference from other demos**: `--use_sim_time` flag and `-F/-R` flags use
`robot_task_request` (direct assignment) instead of `dispatch_task_request`
(bidding), which avoids the RMF traffic schedule mirror deadlock.

---

## Localization: Online SLAM Mapping

Both robots use **slam_toolbox online mapping mode** (`async_slam_toolbox_node`
via `nav2_bringup bringup_launch.py slam:=True`).

### Why Online SLAM Instead of Localization

The `localization_slam_toolbox_node` (lifecycle node) crashes with a Ceres
solver segfault during `onActivate()` when laser scan messages arrive in a burst
during initialization. This is a known race condition that occurs consistently
after the second nav pod restart.

Online SLAM mapping avoids this entirely — it starts immediately from the first
laser scan without loading any posegraph.

### Position Tracking

Because slam_toolbox's `/pose` output is intermittent (only updates when scans
are processed), a dedicated **odom→amcl relay** converts the Gazebo odometry
to world-frame `amcl_pose` for the fleet adapter:

```
Gazebo → ros_gz_bridge → /robot_N/odom (Zenoh) → nav pod DDS /odom
  → odom_amcl_relay.py: world_x = odom_x + SPAWN_X, world_y = odom_y + SPAWN_Y
    → /amcl_pose (DDS) → Zenoh: robot_N/amcl_pose → free_fleet_adapter
```

This gives the fleet adapter continuous 1 Hz position updates regardless of
slam_toolbox state.

### Known Limitation: SLAM Map Accumulation

After robot_2 completes its first south-north patrol cycle:
- The slam map records walls in the east corridor
- On subsequent cycles, the global planner may route around these walls
  instead of going straight south
- Robot_2 eventually gets stuck (typically after 1–2 patrol rounds)

**Workaround**: restart robot_2's nav pod to get a fresh slam map:
```bash
oc rollout restart deployment/robot-nav-robot-2 -n ros2-turtlebot3-house
```
Robot_1 is unaffected — its west corridor path accumulates fewer blocking walls.

---

## Navigation Graph

The house nav graph defines the waypoints and lanes for fleet planning:

```
     robot_1_home      center_south     robot_2_home
     (-1.5, -0.5) ─────── (0, -0.5) ──── (1.5, -0.5)
           │                  │                 │
      left_north          [cross]          right_north
      (-2.0, +0.5)        lanes           (2.0, +0.5)
           │                  │                 │
       sw_open           south_center        se_open
      (-1.5, -1.5) ──── (0.0, -2.0) ──── (1.5, -1.5)
```

### Waypoint Table

| Index | Name | World (x, y) | Description |
|-------|------|-------------|-------------|
| 0 | `robot_1_home` | (-1.5, -0.5) | robot_1 spawn — west corridor |
| 1 | `robot_2_home` | (+1.5, -0.5) | robot_2 spawn — east corridor |
| 2 | `left_north` | (-2.0, +0.5) | north end of west corridor |
| 3 | `right_north` | (+2.0, +0.5) | north end of east corridor |
| 4 | `center_south` | (0.0, -0.5) | center of main corridor |
| 5 | `sw_open` | (-1.5, -1.5) | south-west open area |
| 6 | `se_open` | (+1.5, -1.5) | south-east open area |
| 7 | `south_center` | (0.0, -2.0) | south center |
| 10 | `cafe_w` | (5.0, -2.73) | west entry to kitchen cafe area |
| 11 | `cafe_nw` | (5.4, -1.6) | north-west of cafe tables |
| 12 | `cafe_ne` | (7.2, -1.6) | north-east of cafe tables |
| 13 | `cafe_se` | (7.2, -3.7) | south-east of cafe tables |

### Robot_1 Default Patrol

```
robot_1_home ↔ sw_open  (west outer corridor, 1.0m south-north)
```

### Robot_2 Default Patrol

```
robot_2_home ↔ se_open  (east outer corridor, 1.0m south-north)
```

### Optional: Cafe Table Circuit (robot_2)

The kitchen area east of robot_2's corridor has two cafe tables at
world (6.36, -2.28) and (6.36, -3.19). Waypoints 10–13 define a circuit
around them (requires navigating through the east doorway from the main corridor):

```
robot_2_home → cafe_w → cafe_nw → cafe_ne → cafe_se → cafe_w
```

---

## House World Furniture

Key furniture positions in world frame (from `model.sdf`):

| Model | World (x, y) | Notes |
|-------|-------------|-------|
| `Mailbox` | (0.88, -0.58) | Near main corridor center |
| `first_2015_trash_can` | (1.88, 1.91) | North of robot_2 spawn |
| `table` | (-2.66, 2.42) | Dining table, west-north area |
| `table_marble` | (4.88, 2.93) | Marble table, east-north area |
| `cafe_table_0` | (6.36, -2.28) | Kitchen, east side |
| `cafe_table` | (6.36, -3.19) | Kitchen, east side (south) |

---

## Quick-Start

### 1. Deploy

```bash
# Deploy house demo namespace
helm upgrade turtlebot3-house-demo helm/multi-robot-demo \
  --namespace ros2-turtlebot3-house \
  -f helm/multi-robot-demo/values.yaml \
  -f helm/multi-robot-demo/values-turtlebot3-house.yaml \
  --set image.tag=turtlebot3-house \
  --set rmf.image=quay.io/jianrzha/ros2-rmf:multi-demo \
  --set namespace=ros2-turtlebot3-house
```

### 2. Full Restart (Required Before Each Demo Run)

Gazebo odom accumulates across nav pod restarts. Only a Gazebo restart resets
odometry to (0,0), ensuring the fleet adapter sees robots at spawn positions.

```bash
NS=ros2-turtlebot3-house

# 1. Restart Gazebo first (resets odom)
oc rollout restart deployment/gazebo-sim -n $NS
oc rollout status deployment/gazebo-sim -n $NS --timeout=3m

# 2. Restart nav pods and RMF
oc rollout restart deployment/robot-nav-robot-1 deployment/robot-nav-robot-2 \
  deployment/rmf-core -n $NS

# 3. Wait for both bt_navigators to become active (~15-30s)
# Poll until: both "active [3]"
```

Or use the Makefile:
```bash
make restart NAMESPACE=ros2-turtlebot3-house
```

### 3. Dispatch Demo

Wait for both robots to appear in fleet_states at their spawn positions, then:

```bash
RMFPOD=$(oc get pod -n ros2-turtlebot3-house -l app=rmf-core \
  -o jsonpath='{.items[0].metadata.name}')

# robot_1: west corridor patrol
oc exec -n ros2-turtlebot3-house $RMFPOD -c rmf-core -- bash -c '
  source /opt/ros/jazzy/setup.bash
  /opt/ros/jazzy/lib/rmf_demos_tasks/dispatch_patrol \
    -F turtlebot3 -R robot_1 -p robot_1_home sw_open -n 20 --use_sim_time'

# robot_2: east corridor patrol
oc exec -n ros2-turtlebot3-house $RMFPOD -c rmf-core -- bash -c '
  source /opt/ros/jazzy/setup.bash
  /opt/ros/jazzy/lib/rmf_demos_tasks/dispatch_patrol \
    -F turtlebot3 -R robot_2 -p robot_2_home se_open -n 20 --use_sim_time'
```

Or use the Makefile:
```bash
make dispatch-house-patrol NAMESPACE=ros2-turtlebot3-house
```

### 4. Watch in noVNC

```
https://ros2-multi-robot-novnc-ros2-turtlebot3-house.apps.ai-dev02.kni.syseng.devcluster.openshift.com
```

---

## Key Configuration

### values-turtlebot3-house.yaml

```yaml
gazebo:
  world: turtlebot3_house

nav2:
  localizationMode: slam_mapping   # online slam (no posegraph loading)
  enableFootprintApproach: "false" # narrow corridors; no robot-robot collision avoidance needed

robots:
  - name: robot_1
    color: "0,0,1"                 # blue
    initialPose: {xPos: -1.5, yPos: -0.5, yaw: 0.0}
  - name: robot_2
    color: "1,0,0"                 # red
    initialPose: {xPos: 1.5, yPos: -0.5, yaw: 3.14159}
```

### Key Nav2 Parameters (auto-patched per entrypoint-nav2.sh)

| Parameter | Value | Reason |
|-----------|-------|--------|
| Controller | RPP (Regulated Pure Pursuit) | Stable in curved corridors |
| `use_collision_detection` | `false` | Prevents RPP stopping for walls |
| Global costmap inflation | 0.05m (AMCL) / 0.15m (slam) | Keeps doorways passable |
| Global costmap `robot_radius` | 0.0 (AMCL) / 0.22m (slam) | Allows planning from near-wall positions |
| `allow_unknown` | `true` | Plans through unmapped areas in slam mode |
| `planner.tolerance` | 0.5m | Accepts paths ending 0.5m from goal |
| `bond_timeout` | 300s | Allows slow AMCL convergence |
| `yaw_goal_tolerance` | π (3.14159) | Any final orientation accepted |

---

## Known Limitations

### 1. SLAM Map Accumulation (robot_2)

Robot_2 uses online SLAM mapping. After the first patrol round, the slam map
accumulates wall data that can block subsequent south-bound navigation. The
robot typically completes 1–2 cycles cleanly before getting stuck.

**Workaround**: restart robot_2's nav pod between demo cycles:
```bash
oc rollout restart deployment/robot-nav-robot-2 -n ros2-turtlebot3-house
```

**Root cause**: `localization_slam_toolbox_node` (which would use a static
posegraph and avoid this issue) crashes with a Ceres solver segfault during
`onActivate()` in Gazebo Harmonic + Nav2 Jazzy. This is an upstream
compatibility issue.

### 2. Odom Drift Across Nav Pod Restarts

The odom relay reports `world_pos = spawn + odom_displacement`. After robot_2
navigates south and returns, its Gazebo odom retains the displacement (Gazebo
odom is cumulative and only resets on full Gazebo restart). Subsequent nav pod
restarts without Gazebo restart result in the fleet adapter seeing robot_2 at a
drifted position (e.g., 0.63m east of spawn), which may exceed the 1.5m
`merge_radius` and prevent path planning.

**Workaround**: always do a **full restart** (including Gazebo) before each
demo recording session.

### 3. dispatch_patrol API: Use robot_task_request

The `dispatch_task_request` API uses bidding, which triggers the RMF traffic
schedule mirror — this mirror consistently deadlocks after task assignment
because the fleet adapter cannot submit trajectories without a synchronized
mirror view (chicken-and-egg).

**Fix**: always use `--use_sim_time` with `-F <fleet> -R <robot>` flags, which
uses the `robot_task_request` API (direct assignment, no bidding):
```bash
dispatch_patrol -F turtlebot3 -R robot_1 -p ... --use_sim_time
```

### 4. RTF ≈ 0.5 (Half Real-Time)

Gazebo runs at approximately half real-time (software Mesa/llvmpipe rendering).
A 1m corridor transit takes ~15–20 wall-clock seconds. GPU-accelerated nodes
would achieve RTF ≈ 1.0.

### 5. Cafe Table Circuit Not Reliable

The optional cafe table circuit (waypoints 10–13 in the kitchen east of the
main corridor) requires robot_2 to navigate ~5m east through the house. While
the waypoints are defined in the nav graph, reliable navigation to this area
has not been demonstrated — the east kitchen doorway is difficult to navigate
through with the current slam_mapping approach and narrow inflation radius.

---

## Technical Notes

### Why `robot_task_request` vs `dispatch_task_request`

The standard `dispatch_task_request` uses a bidding protocol that requires the
fleet adapter's traffic schedule mirror to be synchronized before submitting
robot trajectories. In this deployment, the mirror consistently deadlocks after
receiving the task assignment:

```
fleet_adapter → requests mirror update → timeout (20s)
             ← schedule sends version N → adapter needs N+1
             ← stuck: adapter can't submit trajectory without N+1
             ← but N+1 only happens when adapter submits trajectory
```

The `robot_task_request` with `--use_sim_time` bypasses bidding entirely and
directly assigns the task to a named robot. This works reliably.

### Nav2 Activation Race Condition Fix

When nav2 launches immediately (slam_mapping mode), the local costmap activation
requires the `odom→base_footprint` TF within 4 seconds (hardcoded C++ timeout in
Nav2 Jazzy). The Zenoh bridge may not have delivered the first `/odom` message
within this window.

The entrypoint's subshell implements an **auto-RESUME loop**:
```bash
# After nav2 launches, poll bt_navigator state every 5s
# If bt_navigator is "inactive [2]" (activation failed):
#   call RESUME on lifecycle_manager_navigation
# Repeat until bt_navigator is "active [3]"
```

This allows nav2 to self-recover from the TF race condition without manual
intervention.

### Zenoh Position Tracking

The fleet adapter subscribes to `robot_N/amcl_pose` via Zenoh to track robot
positions. In slam_mapping mode (no AMCL), a dedicated relay provides this:

```python
# odom_amcl_relay.py (1 Hz to avoid fleet adapter rapid replanning)
world_x = msg.pose.pose.position.x + SPAWN_X  # odom + spawn offset
world_y = msg.pose.pose.position.y + SPAWN_Y
publish to /amcl_pose (→ Zenoh → fleet adapter)
```

The 1 Hz rate is critical — publishing at 10 Hz (raw odom rate) caused the
fleet adapter to replan every 0.1s, creating a rapid goal cancel/replan loop
that overwhelmed the global planner.

---

## Container Images

### Image: `quay.io/jianrzha/ros2-demo:turtlebot3-house`

**Used by**: `gazebo-sim`, `robot-nav-robot-1`, `robot-nav-robot-2` pods

**Build**: layered on top of the shared `multi-demo` base image — only adds
house-specific assets (~35 MB of slam posegraphs + world SDF) without
re-downloading ROS packages.

```dockerfile
FROM quay.io/jianrzha/ros2-demo:multi-demo
```

**Contents**:
- ROS2 Jazzy + Nav2 + slam_toolbox + ros_gz_bridge (inherited from base)
- Gazebo Harmonic (inherited from base)
- `turtlebot3_house` 3D Gazebo model (downloaded at build time from ROBOTIS GitHub)
- `config/maps/turtlebot3_house.{pgm,yaml}` — 2D AMCL map
- `config/worlds/turtlebot3_house.sdf.xacro` — house world definition
- `entrypoints/entrypoint-gazebo.sh` — Gazebo launch with GZ_SIM_RESOURCE_PATH
- `entrypoints/entrypoint-nav2.sh` — Nav2 launch (slam_mapping mode + auto-RESUME)
- `entrypoints/nav2_relay.py` — RMF↔Nav2 bridge

**OCI Labels**:

| Label | Value |
|-------|-------|
| `org.opencontainers.image.title` | `ROS2 Multi-Robot Demo — TurtleBot3 House` |
| `org.opencontainers.image.description` | Two TurtleBot3 robots patrolling a 3D house via Open-RMF and Nav2 |
| `org.opencontainers.image.source` | https://github.com/jianrongzhang89/robots-demo-platform-openshift |
| `org.opencontainers.image.branch` | `turtlebot3-house-demo` |
| `org.opencontainers.image.base.name` | `quay.io/jianrzha/ros2-demo:multi-demo` |
| `io.openshift.tags` | `ros2,nav2,gazebo,open-rmf,turtlebot3,robotics,jazzy` |

**Build command**:
```bash
make build-push-house
# equivalent to:
podman build --platform linux/amd64 \
  -t quay.io/jianrzha/ros2-demo:turtlebot3-house \
  -f Containerfile.turtlebot3-house .
podman push quay.io/jianrzha/ros2-demo:turtlebot3-house
```

---

### Image: `quay.io/jianrzha/ros2-rmf:multi-demo`

**Used by**: `rmf-core` pod (shared with other multi-demo variants)

**Contents**:
- ROS2 Jazzy
- Open-RMF packages: `rmf_traffic_ros2`, `rmf_task_ros2`, `rmf_demos_tasks`
- `free_fleet_adapter` (patched for env-var spawn positions)
- RMF web dashboard and API server

**Build command**:
```bash
make build-push-rmf
```

---

### Base Image: `quay.io/jianrzha/ros2-demo:multi-demo`

**Used by**: inherited by `turtlebot3-house` and other demo images

**Contents**:
- ROS2 Jazzy full desktop
- Nav2 Jazzy
- slam_toolbox
- Gazebo Harmonic + ros_gz_bridge
- zenoh-bridge-ros2dds
- turtlebot3 packages

---

### Image Hierarchy

```
registry.fedoraproject.org/fedora:43
  └── quay.io/jianrzha/ros2-demo:latest          (base Nav2 + Gazebo)
        └── quay.io/jianrzha/ros2-demo:multi-demo (shared multi-demo base)
              └── quay.io/jianrzha/ros2-demo:turtlebot3-house  ← this demo
```

---

## System Components

| Pod | Image | Key Processes |
|-----|-------|---------------|
| `zenoh-router` | `eclipse/zenoh` | Zenoh router TCP :7447 |
| `gazebo-sim` | `quay.io/jianrzha/ros2-demo:turtlebot3-house` | Gazebo Harmonic, turtlebot3_house world, ros_gz_bridge |
| `robot-nav-robot-1` | same | Nav2 (slam_mapping), nav2_relay.py, odom_amcl_relay |
| `robot-nav-robot-2` | same | Same as robot-1 |
| `rmf-core` | `quay.io/jianrzha/ros2-rmf:multi-demo` | free_fleet_adapter (both robots), RMF traffic manager |

## Key Files

| File | Purpose |
|------|---------|
| `Containerfile.turtlebot3-house` | Layered image: multi-demo base + house assets |
| `config/worlds/turtlebot3_house.sdf.xacro` | House world SDF with furniture |
| `config/maps/turtlebot3_house.{pgm,yaml}` | 2D AMCL map of house floor plan |
| `helm/multi-robot-demo/values-turtlebot3-house.yaml` | House demo overrides |
| `helm/multi-robot-demo/files/nav_graph-turtlebot3_house.yaml` | RMF nav graph |
| `entrypoints/entrypoint-nav2.sh` | Nav2 pod startup (slam_mapping mode + auto-RESUME) |
| `entrypoints/nav2_relay.py` | RMF↔Nav2 bridge (navigate_to_pose dispatch) |

---

## Makefile Reference

```bash
make build-house           # Build turtlebot3-house image
make build-push-house      # Build and push
make dispatch-house-patrol # Dispatch robot_1 and robot_2 corridor patrols
make routes                # Print noVNC and rmf-web URLs
```
