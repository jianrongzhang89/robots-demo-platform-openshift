# Collision Detection & Avoidance — Research Proposal

**Repository:** `robots-demo-platform-openshift`  
**Date:** 2026-07-27  
**Status:** Draft for review

---

## 1. Root Cause Analysis

The current demo has **three collision risks**, each with a different severity:

| Risk | Severity | Why it happens |
|---|---|---|
| Robot ↔ Robot (head-on crossing) | **Critical** | Both robots depart simultaneously via barrier sync; paths cross at the center (~(0, 0)); neither robot's costmap subscribes to the other's scan |
| Robot ↔ Static obstacle (wall/pillar) | Low | Already handled — each robot's AMCL + costmap uses its own LiDAR against the pre-built `tb3_sandbox.yaml` map |
| Robot ↔ Dynamic obstacle (unplanned) | Medium | Each robot's LiDAR physically detects the other robot body, but no inter-robot costmap sharing is configured |

### Why the current Nav2 stack doesn't prevent robot-robot collision

Each Nav2 pod is isolated: `robot_1`'s `controller_server` only has `/robot_1/scan` as an
obstacle source. Although `robot_1`'s LiDAR physically sees `robot_2` (they share the same
Gazebo world), the core problem is the **face-to-face deadlock**:

```
robot_1 ──────►  ◄────── robot_2
          both see each other,
          both stop, neither can
          replan because the other
          is blocking the only path
```

Nav2's DWA/MPPI local planner handles robots passing at angles well, but symmetric head-on
approach causes oscillation and an eventual `FAILED` result without explicit coordination.

### What Zenoh already gives us for free

A key architectural observation: the Zenoh bridge **already carries `/robot_2/scan` across
the network**. The Gazebo pod bridges all topics. Any node on any pod that subscribes to
`/robot_2/scan` will receive it via the router. Cross-robot costmap sharing therefore
requires **only a config change** — no bridge or topology changes needed.

---

## 2. Approaches — Ranked by CPU Cost

### Tier 0 — Zero CPU: Staggered Departure

**Principle:** Eliminate simultaneous crossing by staggering `robot_2`'s departure by
enough time for `robot_1` to clear the center.

At TurtleBot3 max speed (0.26 m/s), the center crossing zone (~1 m radius around origin) is
cleared in ~8 seconds from spawn at (-2, -0.5). A 6–8 second stagger removes all crossing risk.

**Change:** 2 lines in `demo/meet_demo.py`:

```python
# In navigate_robot(), after ready_event.wait():
if namespace == 'robot_2':
    time.sleep(STAGGER_DELAY_SEC)   # e.g. 6.0
```

| Property | Detail |
|---|---|
| CPU added | Zero |
| Code change | 2 lines in `meet_demo.py` |
| Collision prevention | Yes (timing-based) |
| Handles robot stall | No — if `robot_1` stalls, `robot_2` drives into it |
| Scales to N robots | No — stagger must be re-tuned per configuration |
| Demo quality | Good: clean, predictable choreography |

**Verdict:** Sufficient for controlled demos. Brittle for real autonomy.

---

### Tier 1 — Low CPU: Cross-Robot Costmap Sharing (Nav2 native)

**Principle:** Add each robot's LiDAR scan as an observation source in the other robot's
costmap. Both robots treat each other as dynamic obstacles. The Zenoh bridge delivers scans
cross-pod transparently.

**How Nav2 costmaps support this:**

```yaml
# nav2_params.yaml — robot_1 section
robot_1/local_costmap:
  local_costmap:
    ros__parameters:
      obstacle_layer:
        observation_sources: scan scan_robot2
        scan:
          topic: /robot_1/scan
          data_type: "LaserScan"
          marking: True
          clearing: True
        scan_robot2:
          topic: /robot_2/scan       # ← other robot's scan via Zenoh
          data_type: "LaserScan"
          marking: True
          clearing: True
          obstacle_max_range: 2.5
```

Both the local and global costmaps use this pattern. The entry for each robot is templated
so `robot_1` gets `robot_2`'s scan source and vice versa.

**Files changed:**

1. Add `config/nav2_params.yaml` to repo (extended from upstream with cross-robot scan sources)
2. Modify `entrypoint-nav2.sh` to pass `params_file:=` pointing to the custom file,
   templated per `ROBOT_NAME` so each robot subscribes to the correct peer scan topic
3. Mount the file via a new ConfigMap in the Nav2 Helm Deployment

| Property | Detail |
|---|---|
| CPU added | ~5% per Nav2 pod (one additional scan topic processed by costmap) |
| Code change | New `nav2_params.yaml` + 3-line entrypoint change |
| Collision prevention | Yes — each robot avoids the other as a dynamic obstacle |
| Deadlock handled | **No** — face-to-face still causes oscillation/failure |
| Scales to N robots | Yes — add N-1 scan sources per robot |
| Demo quality | Improved but can still fail on direct crossing without Tier 0 |

**Verdict:** Necessary foundation but not sufficient alone. Combine with Tier 0 or Tier 2.

---

### Tier 2 — Very Low CPU: Lightweight Pose Coordinator

**Principle:** A single Python ROS 2 node (`collision_coordinator.py`) watches both robots'
odometry, detects near-collision conditions, and temporarily cancels the lower-priority
robot's navigation goal. When distance recovers, it re-issues the goal. No sensor processing
— pure Euclidean distance on two odometry poses.

**Logic sketch:**

```python
STOP_DIST_M   = 0.8    # cancel robot_2 if closer than this
RESUME_DIST_M = 1.5    # re-issue goal once separation recovers
PRIORITY      = ['robot_1', 'robot_2']   # robot_1 never yields

def odom_callback():
    d = euclidean(pose['robot_1'], pose['robot_2'])
    if d < STOP_DIST_M and nav2['robot_2'].task_running:
        nav2['robot_2'].cancelTask()       # robot_2 yields
    elif d > RESUME_DIST_M and robot2_was_paused:
        nav2['robot_2'].goToPose(robot2_goal)   # robot_2 resumes
```

Uses the `BasicNavigator` API (same as `meet_demo.py`) — `cancelTask()` and `goToPose()`.
No changes to Nav2 internals.

**Deployment:** Run from the Gazebo pod alongside the demo, or as a sidecar in `robot_1`'s
Nav2 pod. No new Deployment required.

| Property | Detail |
|---|---|
| CPU added | < 1% (pure pose arithmetic at odom rate ~10 Hz) |
| Code change | ~120 lines new `demo/collision_coordinator.py` |
| Collision prevention | Yes — guaranteed minimum separation |
| Deadlock handled | Yes — lower-priority robot always yields |
| Wall/obstacle avoidance | Unchanged (existing Nav2 handles it) |
| Scales to N robots | Yes — extend priority list |
| Demo quality | High: observable "yield and proceed" behavior |

**Verdict:** Best balance of simplicity and correctness for the demo. Recommended primary approach.

---

### Tier 3 — Low CPU: ORCA Velocity Obstacles (Decentralized)

**Principle:** Reciprocal Velocity Obstacles (ORCA/RVO2) is a mathematical framework where
each robot independently computes a collision-free velocity given the positions and velocities
of all other robots. No central coordinator — each robot solves its own ORCA problem in O(N)
per timestep.

**How it fits into the Nav2 architecture:**

```
Nav2 controller_server
        │
        ▼ /robot_N/cmd_vel_nav   (raw intended velocity)
  orca_velocity_node
  (subscribes to both /odom topics,
   intercepts cmd_vel_nav,
   computes ORCA-safe velocity)
        │
        ▼ /robot_N/cmd_vel       (actual robot input)
```

The ORCA node projects Nav2's intended velocity onto the set of provably collision-free
velocities. Robots still plan paths with Nav2 — ORCA only adjusts fine-grained velocity output.

**Library:** `pyrvo2` (Python binding for the RVO2 C++ library, pip-installable):

```dockerfile
# Containerfile addition
RUN pip3 install pyrvo2
```

**Core parameters for TurtleBot3 Waffle:**

```python
import rvo2
sim = rvo2.PyRVOSimulator(
    timeStep        = 0.05,   # 20 Hz
    neighborDist    = 2.5,    # neighbor horizon (m)
    maxNeighbors    = 10,
    timeHorizon     = 5.0,    # seconds ahead to check
    timeHorizonObst = 5.0,
    radius          = 0.22,   # TurtleBot3 footprint half-width (m)
    maxSpeed        = 0.26    # TurtleBot3 max linear speed (m/s)
)
```

**Non-holonomic conversion:** ORCA outputs a 2D velocity vector (vx, vy). TurtleBot3 is
differential-drive, so a conversion step maps (vx, vy) → (linear.x, angular.z):

```python
linear  = math.hypot(vx, vy)
angular = math.atan2(vy, vx) - current_yaw   # heading correction
```

| Property | Detail |
|---|---|
| CPU added | < 2% per robot (50 µs per ORCA solve at 20 Hz) |
| Code change | ~200 lines new node + `pip3 install pyrvo2` in Containerfile |
| Collision prevention | Mathematical guarantee (if all robots use ORCA) |
| Deadlock handled | Yes — ORCA guarantees robots take opposite sides |
| Wall/obstacle avoidance | Can add wall line-segments to ORCA solver |
| Scales to N robots | Excellent — O(N) per robot per timestep |
| Demo quality | Highest — smooth, natural-looking simultaneous avoidance |

**Caveats:**
- `pyrvo2` requires a container image rebuild
- ORCA assumes holonomic motion; the non-holonomic conversion above is an approximation
  (works well at low speeds typical of TurtleBot3)
- Wall obstacles can be added as static line segments, but the existing Nav2 costmap
  already handles wall avoidance well

**Verdict:** Most elegant and scalable. Recommended when extending to 3+ robots or when
smooth simultaneous crossing is required.

---

### Tier 4 — Near-Zero Runtime CPU: Pre-Planned Conflict-Free Paths (MAPF)

**Principle:** Compute conflict-free, time-parameterized paths for all robots **offline**
before the demo. Feed robots a sequence of timed waypoints via Nav2 `FollowWaypoints`.
No runtime collision computation — the paths simply don't overlap in spacetime.

**Algorithm for 2 robots:**

1. Use Nav2 offline planner to compute global paths from both spawn to goal positions
2. Check for spacetime conflicts (same (x, y) at same time ± buffer)
3. Insert wait waypoints into `robot_2`'s path at conflict points
4. Encode as a `FollowWaypoints` action sequence in `meet_demo.py`

For 3+ robots: use CBS (Conflict-Based Search) — an optimal MAPF algorithm that runs in
milliseconds for small instances.

| Property | Detail |
|---|---|
| CPU added | Zero at runtime |
| Code change | Offline planning script + modified `meet_demo.py` |
| Collision prevention | Yes (deterministic) |
| Deadlock handled | Yes (by construction) |
| Robustness | Low — if a robot deviates from plan, no recovery |
| Demo quality | Good: predictable choreography |
| Reusable | Only for fixed start/goal configurations |

**Verdict:** Good for a fixed choreographed demo. Not suitable for general-purpose autonomy.

---

## 3. Approach Comparison Matrix

| Approach | CPU Added | New Code | Collision Prevention | Deadlock Prevention | Container Rebuild | Scales to N Robots |
|---|---|---|---|---|---|---|
| **Tier 0** — Staggered departure | Zero | 2 lines | Timing only | Yes | No | No |
| **Tier 1** — Costmap sharing | ~5% | Config + 3 lines | Yes | **No** | No | Yes |
| **Tier 1+0** — Costmap + stagger | ~5% | Config + 5 lines | Yes | Yes | No | Limited |
| **Tier 2** — Pose coordinator | < 1% | ~120 lines | Yes | Yes | No | Yes |
| **Tier 3** — ORCA velocity | < 2% | ~200 lines | Mathematical | Yes | Yes | Excellent |
| **Tier 4** — Pre-planned MAPF | Zero (runtime) | Offline script | Yes | Yes | No | Limited |

---

## 4. Recommended Implementation Plan

A two-phase approach, both achievable without a GPU and with minimal CPU overhead:

### Phase 1 — Quick Fix (no container rebuild)

**Combine Tier 1 + Tier 0.**

| Step | File | Change |
|---|---|---|
| 1 | `config/nav2_params.yaml` | New file: upstream `nav2_params.yaml` extended with cross-robot scan sources per robot |
| 2 | `entrypoints/entrypoint-nav2.sh` | Pass `params_file:=` to `bringup_launch.py`; substitute peer scan topic name from `ROBOT_NAME` |
| 3 | `helm/multi-robot-demo/templates/configmap-nav2.yaml` | New ConfigMap holding `nav2_params.yaml` |
| 4 | `helm/multi-robot-demo/templates/deployment-nav2.yaml` | Mount ConfigMap into Nav2 container |
| 5 | `demo/meet_demo.py` | Add `STAGGER_DELAY_SEC = 6.0`; sleep in `robot_2` thread after barrier |

**Outcome:** Each robot avoids the other as a dynamic obstacle; the 6-second stagger
prevents the face-to-face deadlock for the demo. No new pods, no image rebuild.

### Phase 2 — Proper Autonomy (one new Python file)

**Add Tier 2 coordinator.**

| Step | File | Change |
|---|---|---|
| 6 | `demo/collision_coordinator.py` | New file: pose monitor + Nav2 `cancelTask` / `goToPose` resume logic |
| 7 | `demo/meet_demo.py` | Remove `STAGGER_DELAY_SEC`; launch coordinator thread before navigation |

**Outcome:** Robots can depart simultaneously again. The coordinator yields `robot_2`
when robots approach within 0.8 m and resumes it once clear. Observable "polite yield"
behavior during the demo.

### Phase 3 — Scalable (future, requires image rebuild)

**Tier 3 ORCA node** — when the demo expands to 3+ robots or smooth simultaneous crossing
is required.

| Step | File | Change |
|---|---|---|
| 8 | `Containerfile` | Add `pip3 install pyrvo2` |
| 9 | `demo/orca_coordinator.py` | New file: ORCA velocity interceptor (cmd_vel remapping) |
| 10 | `helm/multi-robot-demo/templates/deployment-nav2.yaml` | Add topic remap: `cmd_vel` → `cmd_vel_nav`; ORCA node publishes actual `cmd_vel` |

---

## 5. Out of Scope

- **SLAM-based dynamic mapping:** Replacing the static AMCL map with SLAM (e.g., SLAM Toolbox)
  would allow unknown obstacles to be detected and mapped at runtime, but adds significant
  CPU overhead (~1 core per robot) and complicates multi-robot TF management. Not needed
  for this demo since the world is fixed and known.

- **GPU-accelerated planning:** Approaches such as CUDA-based trajectory optimization
  (e.g., STORM, iCEM) offer superior performance but require GPU allocation in the
  OpenShift cluster and are out of scope for the CPU-only target environment.

- **Full MAPF with CBS for dynamic replanning:** CBS is computationally feasible for 2–5
  robots offline, but online replanning with CBS on each new obstacle event adds latency
  unsuitable for a real-time demo at 10+ Hz.
