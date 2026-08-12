# Two-Robot Collision-Avoidance Swap Demo

## Overview

This demo shows two TurtleBot3 Waffle robots performing a **position swap with autonomous collision avoidance** in a shared arena on OpenShift. The robots start at opposite ends of the sandbox map, deliberately drive toward each other on a collision course, detect the impending collision, negotiate a yield, and then each re-routes to the other robot's starting position using Gazebo ground-truth positioning.

```
Before:  robot_1 (-2.0,-0.5) [BLUE]      robot_2 (2.0,0.5) [RED]
          ←──────────────────────────────────────────→
                     head-on approach

After:   robot_2_home (2.0,0.5) [BLUE]   robot_1_home (-2.0,-0.5) [RED]
```

**Run the demo:**
```bash
make dispatch-collision-swap ROS_DEMO_NS=ros2-multi-robot
```

This single command handles everything: pod restart, spawn teleport, readiness polling, and the three-phase demo script.

---

## System Architecture

### Pod Layout

```
OpenShift cluster (ros2-multi-robot namespace)
│
├── gazebo-sim pod
│   ├── gazebo              (Gazebo Harmonic physics + rendering)
│   ├── zenoh-bridge        (bridges DDS↔Zenoh for all robot topics)
│   └── gz_world_pos_pub    (publishes Gz ground truth via Zenoh)
│
├── robot-nav-robot-1 pod
│   ├── nav2                (Nav2 Jazzy autonomy stack)
│   ├── zenoh-bridge        (namespaced /robot_1/*, relays cmd_vel, TF, AMCL)
│   ├── zenoh-clock-bridge  (delivers sim clock without namespace prefix)
│   └── zenoh-cmdvel-keepalive (prevents cmd_vel Zenoh route GC)
│
├── robot-nav-robot-2 pod
│   └── (same 4 containers as robot-1)
│
├── rmf-core pod
│   └── rmf-core            (Open-RMF traffic scheduler + free_fleet adapter)
│
└── zenoh-router pod
    └── zenoh               (central message broker, all bridges connect here)
```

### Data Flow

```
Gazebo physics
    │ /robot_N/cmd_vel (DDS) ← Zenoh bridge ← robot_N/cmd_vel (Zenoh)
    │                                              ↑
    │                                    cmdvel_zenoh_pub.py (nav2 pod)
    │                                              ↑
    │                                    /cmd_vel (DDS, nav2 pod)
    │                                              ↑
    │                               Nav2 velocity_smoother
    │
    │ /robot_N/odom  (DDS) → Zenoh bridge → robot_N/odom (Zenoh)
    │                                              ↓
    │                                    nav2 pod /odom (DDS)
    │                                              ↓
    │                                    odom_tf_broadcaster.py
    │                                              ↓
    │                                    odom→base_footprint TF
    │
    │ /world/tb3_sandbox/dynamic_pose/info (gz-transport)
    │                                              ↓
    │                                    gz_world_pos_pub.py
    │                                              ↓
    │                              robot_N/gz_world_pos (Zenoh)
    │                                              ↓
    │                              demo script GzPosMonitor
```

### Coordinate System

The Gazebo world frame is identical to the Nav2 map frame (identity transform). All coordinates in this document are in metres in this shared frame.

| Location | x | y | Notes |
|---|---|---|---|
| robot_1 spawn (`robot_1_home`) | -2.0 | -0.5 | West side, facing east (yaw=0) |
| robot_2 spawn (`robot_2_home`) | 2.0 | 0.5 | East side, facing west (yaw=π) |
| South outer corridor west (`s_in`) | -1.5 | -1.75 | Outer corridor entry |
| South outer corridor east (`s_out`) | 1.5 | -1.75 | Outer corridor exit |
| Pillar grid | ±1.1 | ±1.1 | 3×3 grid, radius 0.15 m each |
| Corner wall segments | ±1.9 | ±1.8 | Blocks NavFn at x=±2.0 — use ±1.5 |

---

## How Open-RMF, Nav2, and Other Pieces Work Together

### Role of Each Component

#### Open-RMF (`rmf-core` pod, `ROS_DOMAIN_ID=55`)

Open-RMF provides **fleet management and traffic scheduling**. In the standard swap demo (`dispatch-swap-patrol`), the RMF dispatcher:
- Accepts `patrol` tasks via `dispatch_patrol`
- Assigns tasks to robots via the `free_fleet_adapter`
- Sends navigation goals to the nav2_relay inside each robot pod via Zenoh key `robot_N/rmf_navigate_cmd`

In the **collision-avoidance demo**, the demo script (`collision_swap_demo.py`) runs inside the `rmf-core` pod but bypasses the RMF task dispatcher entirely. It publishes navigation goals directly to Zenoh and drives robots with a P-controller. RMF's fleet adapter still provides robot position data via `/fleet_states`.

#### Nav2 (`nav2` container, `ROS_DOMAIN_ID=0`)

Each robot's Nav2 stack handles:
- **Localisation:** AMCL particle filter against the pre-built `tb3_sandbox.pgm` map
- **Global planning:** NavFn A* planner (finds paths through the pillar grid)
- **Local control:** Regulated Pure Pursuit controller (follows paths at 0.22 m/s)
- **Lifecycle management:** `lifecycle_manager_navigation` + `lifecycle_manager_localization`

The `nav2_relay.py` node bridges RMF navigation commands (Zenoh CDR strings) to Nav2's `navigate_to_pose` action server.

#### Zenoh Router + Bridges

Zenoh is the cross-pod communication backbone:

| Bridge | Namespace | Key mappings |
|---|---|---|
| Gazebo bridge | none | DDS `/robot_N/cmd_vel` ↔ Zenoh `robot_N/cmd_vel` |
| Nav2 bridge (robot_1) | `/robot_1` | DDS `/tf` → Zenoh `robot_1/tf`; Zenoh `robot_1/rmf_navigate_cmd` → DDS `/rmf_navigate_cmd` |
| Nav2 bridge (robot_2) | `/robot_2` | same pattern |
| Clock bridge | none | Zenoh `clock` → DDS `/clock` (no namespace prefix) |
| Keepalive sidecar | none | Subscribes Zenoh `robot_N/cmd_vel` to prevent GC |

**Key Zenoh topics:**

| Zenoh key | Direction | Purpose |
|---|---|---|
| `robot_N/cmd_vel` | rmf-core/demo → Gazebo | Velocity commands (P-controller or Nav2) |
| `robot_N/rmf_navigate_cmd` | rmf-core → nav2 pod | Navigation goals (`"goal_id x y yaw"`) |
| `robot_N/rmf_navigate_result` | nav2 pod → rmf-core | Navigation outcomes (`"goal_id OK|FAILED"`) |
| `robot_N/amcl_pose` | nav2 pod → rmf-core | AMCL position estimates |
| `robot_N/gz_world_pos` | Gazebo pod → rmf-core | Physics engine ground truth (`"x y yaw"`) |
| `robot_N/clear_costmaps` | rmf-core → nav2 pod | Triggers costmap flush |
| `robot_N/initialpose` | rmf-core → nav2 pod | AMCL re-anchoring |

#### Gazebo Ground-Truth Publisher (`gz_world_pos_pub.py`)

Runs as a background process in the Gazebo pod. Every 0.3 s it calls:
```bash
gz topic -e -t /world/tb3_sandbox/dynamic_pose/info -n 1
```
and parses the physics-engine world-frame positions of `robot_1` and `robot_2`, publishing them to Zenoh as `"x.xxxxxx y.yyyyyy yaw.yyyyyy"`. This is the **only reliable position source** in the demo — AMCL drifts up to 3 m in the symmetric south outer corridor.

---

## Three-Phase Demo Flow

### Phase 1a — Corridor Entry (P-controller)

Both robots use the P-controller to navigate from their spawn positions into the south outer corridor at y = -1.75:

- **robot_1:** spawn (-2.0, -0.5) → `s_in` (-1.5, -1.75) directly
- **robot_2:** spawn (2.0, 0.5) → east wall staging (2.0, -1.75) → `s_out` (1.5, -1.75)

robot_2 uses a two-step path because the direct diagonal from spawn crosses the pillar-grid area where the global planner can fail. Going south along the east wall is a clean, obstacle-free path.

The P-controller achieves **Δ ≈ 0.14–0.15 m** at each waypoint.

### Phase 1b — Head-On Approach (P-controller)

Both robots drive toward each other within the south outer corridor:
- robot_1 → `s_out` (1.5, -1.75) heading east
- robot_2 → `s_in` (-1.5, -1.75) heading west

A **proximity monitor** samples `gz_mon.distance()` every 0.5 s. When distance < 2.0 m, the collision-course condition is triggered.

```
robot_1 ──────→────── ·· ─────←────── robot_2
         s_in              s_out
              ↑ collision detected here
              (distance ≈ 1.65–2.00 m)
```

### Phase 2 — Detect & Yield

When the proximity threshold fires:

1. **Stop both robots** via direct Zenoh `cmd_vel` (0, 0)
2. **robot_2 yields** — a one-shot hold goal is published to `robot_2/rmf_navigate_cmd` at its current Gz position. With `yaw_goal_tolerance = π`, Nav2 considers the goal immediately reached → velocity_smoother stops → robot_2 holds.
3. **robot_1 continues** — Nav2's local costmap detects robot_2 via lidar as an obstacle and the BT navigator plans around it (or robot_1 also stops if the corridor is too narrow).
4. **AMCL re-anchoring** — both robots' AMCL particle filters are re-seeded with their actual Gz positions via `robot_N/initialpose` Zenoh publication. This is critical: prior to this fix, robot_1 was incorrectly anchored at robot_2_home (2.0, 0.5), causing catastrophic 3 m+ localization errors.
5. **20 s yield pause** (`YIELD_PAUSE`)
6. **Costmap flush** — `robot_N/clear_costmaps` signals both nav2 pods to call `clear_entirely_global_costmap` and `clear_entirely_local_costmap`, removing stale obstacle cells accumulated during Phase 1.

### Phase 3 — Re-route to Swap Positions (P-controller, staggered)

After the yield, both robots re-route to their target positions using the P-controller. The 30 s stagger ensures robot_2 is clear before robot_1 starts:

1. **robot_2 dispatched first:** P-ctrl drives directly from hold position to `robot_1_home` (-2.0, -0.5). Arrival confirmed by Gz truth (Δ < 0.15 m). Then holds position with continuous 0 cmd_vel for 90 s.
2. **30 s delay:** robot_2 clears the area; robot_1's lidar can re-raytrace the east side.
3. **robot_1 dispatched:** P-ctrl drives directly from its south-corridor position to `robot_2_home` (2.0, 0.5). Arrival confirmed by Gz truth. Then holds with continuous 0 cmd_vel for 30 s.

**Why P-controller for Phase 3?** Nav2's bt_navigator plans from AMCL positions, which drift catastrophically (1–3 m) in the geometrically symmetric south outer corridor. Every Nav2-based approach — direct navigation, small-step verified navigation, per-step AMCL anchoring — failed due to the particle filter jumping to wrong map locations. The Gz-truth P-controller is the only reliable approach.

### Phase 4 — Verification

Reports both Gz ground-truth positions and AMCL estimates at arrival:

```
robot_1 Gz  at (1.98, 0.36)  Δ=0.14m from target (2.0, 0.5)
robot_2 Gz  at (-1.94, -0.63)  Δ=0.14m from target (-2.0, -0.5)
```

---

## Nav2 Navigation Configuration

### Why Regulated Pure Pursuit (RPP) Instead of DWB

The `tb3_sandbox` map has a 3×3 pillar grid in the centre. DWB (Dynamic Window Approach) generates trajectory samples and evaluates them with multiple critics. In the pillar grid, many trajectories score identically (zero critic differentiation), producing zero-velocity output (local minimum). RPP computes a single "carrot point" on the planned path and drives toward it unconditionally — no sampling, no critic ties.

### Global Planner Settings

```yaml
NavfnPlanner:
  use_astar: true        # A* finds shorter paths than Dijkstra
  tolerance: 0.5        # 0.5 m goal tolerance for intermediate waypoints
```

**`robot_radius: 0.0` on the global costmap** — this is essential. Without it, NavFn treats the robot's own footprint as an obstacle when starting from a position inside the pillar inflation zone, causing `ComputePathToPose` to abort immediately. Setting radius to 0 (point robot) allows planning from any position.

### Costmap Inflation

| Costmap | Inflation radius | Purpose |
|---|---|---|
| Global | 0.15 m | Route paths ≥ 0.15 m from pillar surfaces |
| Local | 0.10 m | Real-time obstacle avoidance during execution |

The outer south corridor gap (between the pillar grid at y = -1.1 and the south wall at y ≈ -2.5) is ~1.3 m wide. At 0.10 m local inflation, the robot (radius 0.22 m) has ~0.86 m of free space — enough to navigate but tight enough to require accurate paths.

### Lifecycle Startup Sequence

Nav2 uses managed lifecycle nodes. The startup sequence is:

```
entrypoint-nav2.sh starts
│
├── gz_world_pos_pub.py background (if in Gazebo pod)
├── odom_tf_broadcaster.py background (restart loop)
│   └── Publishes odom→base_footprint TF from /odom
│       (workaround: QoS mismatch prevents Gazebo's DiffDrive TF from crossing Zenoh)
│
├── cmdvel_zenoh_pub.py background (restart loop)
│   └── Forwards /cmd_vel DDS → Zenoh robot_N/cmd_vel at 20 Hz
│       (workaround: Zenoh bridge route GC'd at ~82 s idle)
│
├── ros2 launch nav2_bringup bringup_launch.py
│   ├── lifecycle_manager_localization → configures/activates:
│   │   ├── map_server (loads tb3_sandbox.yaml)
│   │   └── amcl (particle filter, needs odom→base_footprint TF first)
│   │
│   └── lifecycle_manager_navigation → configures/activates:
│       ├── controller_server   (RPP)
│       ├── smoother_server
│       ├── planner_server      (NavFn A*, global costmap)
│       │   └── global_costmap needs base_link→map TF (from AMCL)
│       │       transform_tolerance: 30 s (waits for AMCL to converge)
│       ├── behavior_server
│       ├── bt_navigator
│       ├── waypoint_follower
│       └── velocity_smoother
│
├── Poll for AMCL node ACTIVE
│
├── Publish /initialpose (5 messages at configured spawn position)
│   └── AMCL particle filter re-seeds around spawn → publishes map→odom TF
│
├── Wait for map→odom TF to appear (confirms AMCL is localized)
│
├── Zenoh keepalive: python3 subscribes robot_N/cmd_vel (prevents Zenoh GC)
│
└── Navigation watchdog loop (10 s poll):
    └── If bt_navigator leaves active [3] → call lifecycle RESUME
```

**Common startup failure:** `lifecycle_manager_navigation` times out waiting for `planner_server` to activate because the global_costmap's `base_link→map` transform lookup fails. This happens when AMCL hasn't published its first `map→odom` TF. The `transform_tolerance: 30.0` parameter gives AMCL 30 seconds to converge before the costmap activation times out.

**Manual recovery** (when auto-fix fails):
```bash
NAV2POD=$(oc get pod -n ros2-multi-robot -l app=robot-nav-robot-N ...)
oc exec -n ros2-multi-robot $NAV2POD -c nav2 -- bash -c '
  ros2 topic pub /initialpose geometry_msgs/msg/PoseWithCovarianceStamped \
    "{header: {frame_id: map}, pose: {pose: {position: {x: X, y: Y}}, ...}}" \
    --times 5 2>/dev/null; sleep 6;
  timeout 45 ros2 service call /lifecycle_manager_navigation/manage_nodes \
    nav2_msgs/srv/ManageLifecycleNodes "{command: 2}"'
```

### Critical Nav2 Workarounds

#### 1. `odom→base_footprint` TF Not Arriving

**Problem:** The Gazebo `ros_gz_bridge` publishes the DiffDrive odometry TF to `/robot_N/tf` (DDS), but a QoS mismatch with the Zenoh bridge's DDS subscriber prevents it from reaching the Nav2 pod. Without this TF, AMCL cannot localize.

**Fix:** `odom_tf_broadcaster.py` subscribes to `/odom` (which flows correctly via Zenoh) and re-derives the `odom→base_footprint` TF from the position field of the Odometry message.

#### 2. `cmd_vel` Zenoh Route Garbage-Collected at ~82 s

**Problem:** The Zenoh broker's idle-subscriber timer garbage-collects the `robot_N/cmd_vel` route ~82 seconds after the last message. Between navigation goals, the route goes dead and cmd_vel stops reaching Gazebo.

**Fix (two-layer):**
- `cmdvel_zenoh_pub.py` (entrypoint-nav2.sh): A dedicated Python process maintains a persistent Zenoh publisher for `robot_N/cmd_vel` by continuously forwarding the nav2 pod's `/cmd_vel` DDS topic.
- Zenoh cmdvel-keepalive sidecar: A separate Zenoh bridge container (no namespace) subscribes to exact keys `robot_1/cmd_vel` and `robot_2/cmd_vel`, keeping bridge-level interest declarations alive.
- Nav2 bridge config includes `.*/cmd_vel` in `subscribers` list.

#### 3. AMCL Catastrophic Drift in South Outer Corridor

**Problem:** The south outer corridor (y ≈ -1.75) is geometrically symmetric — laser scan profiles look identical from any x-position. AMCL particles spread laterally over time and converge to wrong locations (errors up to 3+ m observed), making all AMCL-dependent navigation unreliable for Phase 3.

**Fix:** The collision-avoidance demo uses Gazebo physics ground truth (via `gz_world_pos_pub.py`) exclusively for Phase 3 positioning and control, bypassing AMCL entirely.

#### 4. `map_server` DDS Service Timeout

**Problem:** During high cluster load, the lifecycle_manager's DDS service call to `map_server/change_state` times out (~10 s), leaving `amcl` and all navigation nodes in `unconfigured [1]` state. The lifecycle_manager then deadlocks.

**Fix:** Restart the affected nav2 pod. The Makefile's polling loop (`dispatch-collision-swap`) automatically injects `initialpose` + calls lifecycle `RESUME` when `bt_navigator` is detected in `inactive [2]`. For `unconfigured [1]`, a pod restart is required.

---

## P-Controller: Bypassing Nav2 for Phase 3

The `gz_drive_to()` function provides reliable, AMCL-independent positioning:

```python
def gz_drive_to(robot_name, nav_pub, tx, ty,
                stop_dist=0.15, max_v=0.26, max_w=1.0, timeout=120.0):
    """
    Drive robot_name to (tx, ty) using Gazebo ground-truth P-controller.

    Publishes cmd_vel directly to Zenoh robot_N/cmd_vel at 25 Hz.
    Reads position from GzPosMonitor (robot_N/gz_world_pos).
    Returns True when Gz distance < stop_dist, False on timeout.
    """
```

**Control law:**
```python
angle_to_target = atan2(ty - py, tx - px)
heading_err = (angle_to_target - yaw + π) % (2π) - π   # normalise [-π, π]

vx = max_v * min(1.0, dist)  if |heading_err| < 0.6 rad  else 0.0
wz = clamp(2.0 * heading_err, -max_w, max_w)

cmd_vel = Twist(linear=(vx,0,0), angular=(0,0,wz))
publish to Zenoh robot_N/cmd_vel every 40 ms (25 Hz)
```

**Why not use Nav2 for Phase 3?**

| Approach | Result |
|---|---|
| Direct NavAgent goal (2–3 m leg) | AMCL drifts 1–2 m during navigation; robot stops at wrong physical position |
| Per-step AMCL anchoring (0.3 m steps) | TF jitter from frequent `initialpose` resets causes costmap corruption and immediate bt_navigator failures |
| Continuous AMCL correction at 2 Hz | Same TF jitter, same result |
| Gz-truth P-controller | 0.14–0.15 m accuracy, reliable, deterministic |

**Interference with Nav2 velocity smoother:** When the P-controller is active, Nav2's velocity smoother still publishes 0 m/s at 20 Hz (forwarded by `cmdvel_zenoh_pub.py`). The P-controller publishes at 25 Hz. Both arrive at Gazebo, with the P-controller's commands arriving more frequently. Net effect: robot moves at ~60–70% of commanded speed — sufficient to reach targets in ~15–20 s. After arrival, continuous zero-velocity publishing (at 10 Hz for 30–90 s) prevents the velocity smoother from resuming and drifting the robot.

---

## Known Limitations

| Limitation | Root cause | Mitigation |
|---|---|---|
| AMCL 1–3 m drift in south corridor | Symmetric laser-scan profiles; particle filter has no distinguishing features | Gz ground-truth P-controller replaces AMCL for Phase 3 |
| `bt_navigator inactive [2]` on startup | AMCL convergence race with 30 s costmap transform timeout | Polling loop auto-injects `initialpose` + calls lifecycle RESUME |
| `unconfigured [1]` deadlock | `map_server` DDS service call timeout under cluster load | Pod restart |
| Zenoh route GC at ~82 s | Zenoh broker idle-subscriber timer | cmdvel_zenoh_pub.py + keepalive sidecar + `.*/cmd_vel` in bridge subscribers |
| Relay fake-success (`retry of recently sent`) | nav2_relay caches previous destinations; bt_navigator failure triggers immediate retry | Gz-truth verification; relay cache reset before each step |
| P-ctrl robot drift after arrival | nav2 velocity smoother resumes 0 m/s; occasional non-zero outputs persist | Continuous 10 Hz stop publishing for 30–90 s after arrival |

---

## Running the Demo

### Full Self-Contained Run

```bash
make dispatch-collision-swap ROS_DEMO_NS=ros2-multi-robot
```

This performs:
1. **Pod restart** (Gazebo first, then nav2 × 2 + rmf-core) — clears nav2_relay stale state
2. **Readiness polling** (up to 60 × 5 s) — auto-fixes `inactive [2]` with `initialpose` + RESUME
3. **Robot teleport** — `gz service set_pose` resets both robots to spawn positions
4. **Demo script** — copies and runs `collision_swap_demo.py` in the rmf-core pod

### Manual Position Verification

After the demo, verify physical positions via Gazebo ground truth:
```bash
GZPOD=$(oc get pod -n ros2-multi-robot -l app=gazebo-sim -o jsonpath='{.items[0].metadata.name}')
oc exec -n ros2-multi-robot $GZPOD -c gazebo -- bash -c '
  for d in /usr/lib64/ros-jazzy/opt/*/lib64; do
    [ -d "$d" ] && export LD_LIBRARY_PATH="${d}:${LD_LIBRARY_PATH:-}"; done;
  gz topic -e -t /world/tb3_sandbox/dynamic_pose/info -n 1 2>/dev/null \
  | grep -A5 "robot_1\|robot_2"'
```

Expected output:
```
robot_1: x ≈ 1.98, y ≈ 0.35  (near robot_2_home 2.0, 0.5)   Δ ≈ 0.15 m
robot_2: x ≈ -1.94, y ≈ -0.63  (near robot_1_home -2.0, -0.5)  Δ ≈ 0.15 m
```

### Checking Fleet State (AMCL estimates)

```bash
make rmf-status ROS_DEMO_NS=ros2-multi-robot
```

Note: AMCL positions may differ from Gz ground truth by 0.2–0.5 m due to localization drift. Gz truth is authoritative for what is visible in noVNC.

---

## File Structure

```
demo/collision_swap_demo.py         # Main demo script (runs in rmf-core pod)
entrypoints/entrypoint-nav2.sh      # Nav2 pod startup + background services
entrypoints/entrypoint-gazebo.sh    # Gazebo pod startup + gz_world_pos_pub
helm/multi-robot-demo/
  files/nav_graph.yaml              # RMF traffic graph (22 waypoints)
  files/fleet_config.yaml           # RMF fleet parameters
  templates/deployment-nav2.yaml    # 4-container nav2 pod spec
  templates/configmap-zenoh.yaml    # Per-robot Zenoh bridge configs
Makefile                            # dispatch-collision-swap target
```
