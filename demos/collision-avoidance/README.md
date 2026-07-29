# Demo: Collision Detection and Avoidance

Two TurtleBot3 Waffle robots swap positions, crossing paths in the middle of the
world.  The demo shows the robots meeting face-to-face, one robot pausing to
yield right-of-way, and both eventually reaching their destinations.

```
robot_1 (blue)  (-2, -0.5)  ──────────────────────► (2,  0.5)
                                      ✕  meet
robot_2 (red)   ( 2,  0.5)  ◄────────────────────── (-2, -0.5)
```

---

## Quick start

```bash
# 1. Deploy the platform (first time only)
make build-push
make deploy

# 2. Run the demo
make demo ROS_DEMO_NS=ros2-multi-robot

# 3. Reset robot positions between runs
make reset ROS_DEMO_NS=ros2-multi-robot
```

Watch the Gazebo simulation live via the **noVNC route**:

```bash
make routes ROS_DEMO_NS=ros2-multi-robot
# Open the printed URL in a browser
```

---

## Architecture

### Distributed execution model

Each robot's navigation script runs **on its own Nav2 pod**.  This is a hard
requirement: ROS 2 service calls (actions, lifecycle services) cannot be routed
cross-pod through Zenoh because Zenoh does not relay response messages.  Regular
pub/sub topics work reliably cross-pod.

```
┌─────────────────────────── OpenShift namespace: ros2-multi-robot ──────────────────────────────┐
│                                                                                                 │
│  robot-nav-robot-1 pod          robot-nav-robot-2 pod          gazebo-sim pod                 │
│  ┌─────────────────────────┐    ┌─────────────────────────┐    ┌─────────────────────────┐    │
│  │ meet_demo.py            │    │ meet_demo.py            │    │ Gazebo Harmonic          │    │
│  │  --namespace robot_1   │    │  --namespace robot_2   │    │ robot_1 + robot_2        │    │
│  │                         │    │                         │    │ noVNC GUI                │    │
│  │ Nav2 stack (namespace:  │    │ Nav2 stack (namespace:  │    │                          │    │
│  │   robot_1)              │    │   robot_2)              │    │ zenoh-bridge sidecar     │    │
│  │ • AMCL                  │    │ • AMCL                  │    └──────────┬───────────────┘    │
│  │ • DWB controller        │    │ • DWB controller        │               │                    │
│  │ • global / local        │    │ • global / local        │    zenoh-router pod                │
│  │   costmaps              │    │   costmaps              │    (central hub :7447)             │
│  │                         │    │                         │               │                    │
│  │ zenoh-bridge sidecar    │    │ zenoh-bridge sidecar    │    ◄──────────┘                    │
│  └─────────────────────────┘    └─────────────────────────┘                                   │
└─────────────────────────────────────────────────────────────────────────────────────────────────┘
```

### Cross-pod communication (Zenoh)

All topic data travels through the central `zenoh-router` pod via TCP.  The
sidecar `zenoh-bridge-ros2dds` in each pod bridges local DDS topics to/from the
Zenoh network transparently.

Topics confirmed to bridge reliably (pub/sub):

| Topic | Publisher | Subscriber(s) |
|---|---|---|
| `/robot_N/scan` | Gazebo pod | Nav2 pod (AMCL, costmap) |
| `/robot_N/odom` | Gazebo pod | Nav2 pod |
| `/robot_N/tf` | Gazebo pod, local RSP | Nav2 TF buffer |
| `/robot_N/tf_static` | local RSP | Nav2 TF buffer |
| `/robot_N/amcl_pose` | Nav2 pod | meet_demo.py on peer pod |
| `/robot_N/cmd_vel` | Nav2 pod | Gazebo pod (robot actuator) |
| `/clock` | Gazebo pod | all Nav2 nodes (sim time) |

### Navigation stack

Each robot runs a full **Nav2 Jazzy** stack with:

- **AMCL** — particle-filter localisation against the pre-built `tb3_sandbox` map
- **DWB local planner** — trajectory following and dynamic obstacle avoidance
- **NavFN global planner** — path planning around static map obstacles
- **Static + obstacle costmap layers** — walls (static map) and LiDAR scan obstacles

Nav2 is launched with `use_namespace:=True` so every node and topic is scoped
under `/robot_N/`, allowing two completely independent stacks to coexist in the
same Kubernetes namespace without topic collision.

### Simulation parameters

| Parameter | Value | Reason |
|---|---|---|
| `real_time_factor` | 0.5 | CPU-only llvmpipe rendering cannot sustain 1× real time; clock regressions at 1× cleared all TF buffers and broke navigation |
| `max_step_size` | 0.01 s (100 Hz) | Reduces CPU load; 1 ms steps at 0.5× was too heavy for the available nodes |
| `xy_goal_tolerance` | 0.15 m | Tighter than the 0.25 m default; robot arrives visibly at its destination |
| `yaw_goal_tolerance` | 0.5 rad | Relaxed so final yaw alignment does not block goal completion |

---

## Collision detection and avoidance

### Layer 1 — shared corridor waypoint (routing)

Both robots are given the same intermediate waypoint **(0.5, 0.1)** before their
final goals.  This point lies on the diagonal between the two spawn positions.
Without it the DWB planner may route each robot through a different corridor and
they never meet.

```
robot_1 path:  (-2,-0.5) ──► (0.5, 0.1) ──► (2, 0.5)
robot_2 path:  ( 2, 0.5) ──► (0.5, 0.1) ──► (-2,-0.5)
```

### Layer 2 — departure stagger (timing)

Robot_2 waits **5 real-seconds** after robot_1 starts before entering the
corridor.  At `real_time_factor=0.5` this equals 2.5 sim-seconds — long enough
for robot_1 to begin its approach so both robots are visibly moving simultaneously
rather than one sitting idle.

### Layer 3 — proximity yield (active avoidance)

Robot_2 subscribes to both robots' AMCL poses — these are ordinary Zenoh pub/sub
topics that bridge reliably across pods:

```
/robot_1/amcl_pose  →  robot1_pos  (robot_1's position in map frame)
/robot_2/amcl_pose  →  own_pos     (robot_2's own position)
```

Inside the navigation polling loop, robot_2 continuously computes the Euclidean
distance between the two positions:

```python
d = math.hypot(robot1_pos.x - own_pos.x,
               robot1_pos.y - own_pos.y)
if d < YIELD_TRIGGER_M:   # 2.0 m
    yield()
```

When the distance drops below **2.0 m** (before entering each other's 3.5 m
LiDAR range), robot_2:

1. **Cancels** its current Nav2 goal (`nav.cancelTask()`)
2. **Clears** its local costmap (`nav.clearLocalCostmap()`) — removes stale
   "robot_1 was here" obstacle cells left by the pause, so robot_2 can replan
   cleanly when it resumes
3. **Pauses 15 real-seconds** (7.5 sim-seconds) — enough time for robot_1 to
   travel ~1 m and clear the meeting area
4. **Re-issues** its goal and continues

Robot_1 always has **priority** and never pauses.

### Layer 4 — Nav2 LiDAR obstacle avoidance (passive)

Each robot's DWB local planner detects the other robot physically via its own
laser scanner when within ~3.5 m range.  The scan is processed into the local
costmap's obstacle layer, and DWB naturally plans trajectories that avoid the
detected obstacle.  This layer is independent of the application-level yield
and acts as a last-resort physical avoidance mechanism.

### Sequence diagram

```
T=0    robot_1 starts navigating toward (0.5, 0.1)
T=5s   robot_2 starts navigating toward (0.5, 0.1)  [5 s stagger]
T≈30s  distance < 2.0 m  →  robot_2 cancels goal, clears costmap, pauses
T≈45s  15 s pause complete  →  robot_2 re-issues goal toward (0.5, 0.1)
T≈60s  robot_1 reaches waypoint, continues to (2, 0.5)
T≈80s  robot_2 reaches waypoint, continues to (-2, -0.5)
T≈90s  both robots reach their destinations  [SUCCEEDED]
```

*Timings approximate; `real_time_factor=0.5` means 1 real-second = 0.5 sim-seconds.*

---

## Limitations

### No inter-robot costmap sharing

Each robot's costmap only contains obstacles detected by **its own LiDAR**.
Neither robot "knows" the other is a mobile robot vs. a static wall.  When
robot_2 pauses during the yield, its stopped body is visible in robot_1's LiDAR
as a static obstacle.  If the corridor is too narrow for robot_1 to plan around
it, robot_1 may also get stuck.

### Yield only on robot_2

Robot_1 always has priority and never pauses.  In a two-robot scenario this is
sufficient, but it would not scale to three or more robots without a proper
priority scheme.

### Fixed pause duration

The 15-second pause is calculated for the observed robot speed (~0.06 m/s real).
If robot_1 is slower than usual (due to recovery behaviours, pillar avoidance,
etc.) the pause may not be long enough for it to clear robot_2's position.

### Zenoh service routing

ROS 2 service calls (actions, lifecycle management) cannot be routed cross-pod
through Zenoh because Zenoh does not relay response messages.  This is why the
demo runs one script per pod rather than a single centralised controller.

### `real_time_factor=0.5`

The simulation runs at half speed.  All timeout parameters (goal tolerance,
stuck detection, pause durations) must account for this.  On a GPU-enabled node
`real_time_factor=1.0` is possible (see `make deploy --set gazebo.gpu=true`),
which would halve all real-time durations.

---

## Future enhancements

### Tier 1 — Inter-robot costmap sharing

Add each robot's scan as an observation source in the peer's local costmap:

```yaml
# nav2_params.yaml — robot_1 local costmap
voxel_layer:
  observation_sources: scan scan_peer
  scan_peer:
    topic: /robot_2/scan
    data_type: "LaserScan"
```

Requires a **TF bridge** (`entrypoints/tf_bridge.py` is included as a reference
implementation) to merge the peer robot's TF frames into the local TF tree so
the costmap can transform the peer scan into the local reference frame.  This
was attempted during development but Zenoh's `TRANSIENT_LOCAL` QoS bridging is
unreliable for `tf_static`, causing the static transforms to be missing on
pod startup.

### Tier 2 — Proper coordinator with Nav2 pause/resume

Use the Nav2 lifecycle manager's `manage_nodes` service to **pause** the peer
robot's navigation stack rather than cancelling its goal.  This avoids the
"stopped body becomes static obstacle" problem.  Requires a coordinator node
running on the same pod as the robot being paused (cross-pod service routing
does not work through Zenoh).

### Tier 3 — ORCA velocity obstacles

Implement Reciprocal Velocity Obstacles (ORCA) as a thin intercept layer between
Nav2's controller output and the robot's `cmd_vel` topic.  Each robot computes a
collision-free velocity independently in O(N) per timestep.  Scales to N robots
and handles the deadlock case mathematically.  Requires adding `pyrvo2` to the
container image.

### Non-holonomic path coordination

Use a Conflict-Based Search (CBS) or similar Multi-Agent Path Finding (MAPF)
algorithm to compute conflict-free, time-parameterised paths for both robots
**before departure**.  Zero runtime CPU; deterministic demo behaviour.  Works
best for fixed start/goal configurations.

---

## Files

| File | Purpose |
|---|---|
| `meet_demo.py` | Demo script — runs one robot per pod; implements stagger, waypoint routing, and proximity yield |
| `proposal.md` | Research proposal covering all five collision-avoidance tiers with trade-off analysis |
