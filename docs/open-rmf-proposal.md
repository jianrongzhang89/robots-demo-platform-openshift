# Open-RMF Fleet Management Integration
## Proposal for Review

| | |
|---|---|
| **Status** | Draft — awaiting review |
| **Author** | Multi-Robot Demo Team |
| **Date** | 2026-07-22 |
| **Repo** | https://github.com/jianrongzhang89/robots-demo-platform-openshift |

---

## 1. Problem Statement

The current multi-robot demo runs two TurtleBot3 robots in separate OpenShift
pods. Each robot navigates independently using its own Nav2 stack, but **neither
robot knows the other exists**. When their paths cross, the Gazebo physics
engine stops them and they must be manually teleported back to their starting
positions to continue.

This limits the demo's ability to show true multi-robot coordination and makes
it fragile for live demonstrations.

---

## 2. Proposed Solution

Integrate **Open-RMF** — the Robot Middleware Framework — as a fleet management
layer above the existing Nav2 stacks. Open-RMF adds:

- **Traffic deconfliction** — detects path conflicts 2–5 seconds before they
  occur and autonomously reroutes one robot to avoid the collision
- **Task dispatch** — send patrol, delivery, and cleaning tasks via a web
  dashboard or CLI; RMF assigns them to the right robot
- **Fleet visibility** — real-time map showing both robots' positions and
  active tasks in a browser dashboard

The integration uses **`free_fleet`**, an Open-RMF adapter that connects to
Nav2 over Zenoh — the same Zenoh infrastructure already in the demo — without
modifying any existing Nav2 nodes.

---

## 3. Current vs. Proposed Architecture

### Current (4 pods)

```
┌─────────────────────────────────────────────────────────────────┐
│  OpenShift namespace: ros2-multi-robot                          │
│                                                                 │
│  zenoh-router ←──────────────────────────────────────────────┐ │
│       ↑                    ↑                     ↑           │ │
│  gazebo-sim           robot-nav-robot-1      robot-nav-robot-2│ │
│  (Gazebo + bridge)    (Nav2 + bridge)        (Nav2 + bridge)  │ │
│                                                               │ │
│  ✗ No inter-robot awareness                                   │ │
│  ✗ Collision = manual teleport                                │ │
└─────────────────────────────────────────────────────────────────┘
```

### Proposed (5 pods)

```
┌─────────────────────────────────────────────────────────────────┐
│  OpenShift namespace: ros2-multi-robot                          │
│                                                                 │
│  zenoh-router ←──────────────────────────────────────────────┐ │
│       ↑                    ↑                     ↑           │ │
│  gazebo-sim           robot-nav-robot-1      robot-nav-robot-2│ │
│  (unchanged)          (bridge config         (bridge config   │ │
│                        expanded)              expanded)        │ │
│                                                               │ │
│            ↑  new  ─────────────────────────────────────────┘ │
│       rmf-core pod                                             │
│       ├── free_fleet_adapter  (reads pose via TF over Zenoh)  │
│       ├── rmf-traffic-schedule (detects + resolves conflicts)  │
│       ├── rmf-task-dispatcher  (assigns tasks to robots)       │
│       ├── rmf-web api-server   (REST API, port 8000)           │
│       └── rmf-web dashboard    (browser UI, port 3000)         │
│                                                                │
│  ✓ Robots yield before colliding                               │
│  ✓ Tasks dispatched via dashboard                              │
│  ✓ Live fleet map in browser                                   │
└─────────────────────────────────────────────────────────────────┘
```

---

## 4. How Traffic Deconfliction Works

```
t=0s   Robot 1 dispatched: robot_1_home → robot_2_home
       Robot 2 dispatched: robot_2_home → robot_1_home

t=1s   rmf-traffic-schedule detects trajectories will intersect at t=4s
       Conflict notice sent to free_fleet_adapter

t=2s   free_fleet_adapter replans robot_2's route:
         robot_2_home → hold at waypoint → robot_1_home
       Robot 2 receives new NavigateToPose goal (hold position)

t=4s   Robot 1 passes through the intersection unobstructed

t=5s   Robot 2 receives new goal: proceed to robot_1_home
       Both robots complete their routes — no collision, no teleport
```

The conflict is detected using **continuous collision detection** on the planned
trajectory splines. The detection threshold is the robot's *vicinity radius*
(0.5 m for TurtleBot3 Waffle) — roughly one robot-length of clearance.

---

## 5. What `free_fleet` Does (and Doesn't Do)

### Does
- Read each robot's pose via TF (`/robot_N/tf`) over the existing Zenoh router
- Send `NavigateToPose` action goals to each robot over Zenoh
- Report robot positions and task status to the RMF traffic schedule

### Doesn't
- Modify any Nav2 node (AMCL, planner, controller remain unchanged)
- Replace the existing Zenoh bridge or router
- Require a new communication channel — uses the same `zenoh-router:7447`

The only change to existing pods is **expanding the Zenoh bridge allowlist**
on the Nav2 pods to pass through three additional interfaces:

| Interface | Direction | Purpose |
|---|---|---|
| `robot_N/tf` | robot → RMF | Robot pose (map→base_footprint) |
| `robot_N/battery_state` | robot → RMF | Battery level at 1 Hz |
| `robot_N/navigate_to_pose/_action/*` | RMF → robot | Navigation commands |

---

## 6. New Assets Required

Three new files must be authored before implementation can begin. These are
the critical path items.

### 6.1 Navigation graph (`0.yaml`)

An annotated overlay on the `tb3_sandbox` map defining where robots can travel.
Authored in the Open-RMF `traffic_editor` GUI tool.

Minimum viable graph for the demo:

```
Waypoints:
  robot_1_home   (-2.0, -0.5)   ← robot 1 spawn
  robot_2_home   ( 2.0,  0.5)   ← robot 2 spawn
  meeting_point  ( 0.0,  0.0)   ← midpoint
  charger_1      (-3.0, -1.0)   ← robot 1 charging station
  charger_2      ( 3.0,  1.0)   ← robot 2 charging station

Lanes (bidirectional):
  robot_1_home ↔ meeting_point ↔ robot_2_home
  robot_1_home ↔ charger_1
  robot_2_home ↔ charger_2
```

### 6.2 Building map (`tb3_sandbox.building.yaml`)

The `traffic_editor` project file that ties together the map image, nav graph,
and level definitions. Single level `L1`, no lifts or doors for this demo.

### 6.3 Coordinate transform calibration

`free_fleet` needs 4+ matching point pairs between the RMF traffic editor
coordinate system and the Nav2 map frame. The `free_fleet` repository already
provides calibration values for the `turtlebot3_world` simulation (which uses
the same underlying map), so this is a starting point, not a blank slate.

```yaml
# Starting values from free_fleet's existing tb3 example
reference_coordinates:
  L1:
    rmf:   [[8.9508, -6.6006], [7.1006, -9.1508],
             [12.3511, -9.2008], [11.0510, -11.8010]]
    robot: [[-1.04555, 2.5456], [-2.90519, 0.00186],
             [2.39611, -0.061773], [1.08783, -2.59750]]
```

---

## 7. Implementation Plan

### Phase 1 — Map authoring (Days 1–2)
- [ ] Install `traffic_editor` locally
- [ ] Open `tb3_sandbox.png`, place waypoints and lanes
- [ ] Export `0.yaml` nav graph and `tb3_sandbox.building.yaml`
- [ ] Verify coordinate transform against 4 known Nav2 map positions
- **Output:** Two new config files checked into `config/rmf/`

### Phase 2 — RMF core container image (Days 3–5)
- [ ] Write `Containerfile.rmf` based on `ros-jazzy-rmf-dev` apt package
- [ ] Build `free_fleet_adapter` from source (binary not in apt — known
  upstream issue [#166](https://github.com/open-rmf/rmf_demos/issues/166))
- [ ] Bundle `rmf-web` api-server + pre-built React dashboard
- [ ] Push to `quay.io/jianrzha/ros2-rmf:latest`
- **Output:** New container image

### Phase 3 — Zenoh bridge config update (Day 5)
- [ ] Add `tf`, `battery_state`, and `navigate_to_pose/_action/*` to the
  Nav2 pod bridge allowlist (`helm/multi-robot-demo/files/nav2-bridge.json5`)
- [ ] Verify with `oc exec` that RMF pod can echo `/robot_1/tf`
- **Output:** Updated `nav2-bridge.json5`

### Phase 4 — Helm chart additions (Days 6–7)
- [ ] Add `deployment-rmf-core.yaml` template
- [ ] Add `configmap-rmf.yaml` (building map, nav graph, fleet YAML)
- [ ] Add `service-rmf.yaml` + `route-rmf.yaml`
- [ ] Add `rmf` section to `values.yaml`
- [ ] `make deploy` to test full stack
- **Output:** Updated Helm chart, 5-pod deployment

### Phase 5 — Integration testing + documentation (Days 7–8)
- [ ] Verify conflict detection fires on head-on patrol scenario
- [ ] Verify negotiation resolves without teleport
- [ ] Open rmf-web dashboard, confirm both robots appear on map
- [ ] Dispatch patrol task via dashboard
- [ ] Update README, update `meet_demo.py` to use `dispatch_patrol`
- **Output:** Working demo, updated docs

**Total estimated effort: 8 working days**

---

## 8. Demo Scenarios Enabled

### Scenario A — Autonomous collision avoidance
Dispatch both robots toward each other's positions simultaneously.
RMF detects the conflict and holds one robot until the other passes.
**No manual teleport required.**

```bash
# From rmf-core pod
ros2 run rmf_demos_tasks dispatch_patrol \
  -p robot_1_home meeting_point robot_2_home -n 2 --use_sim_time
```

### Scenario B — Task dispatch via dashboard
1. Open the `rmf-web` dashboard route in a browser
2. See both robots on the `tb3_sandbox` map
3. Click a waypoint to dispatch a patrol task
4. Watch the robot navigate, and observe the traffic schedule yield
   the other robot when their paths overlap

### Scenario C — Simultaneous fleet missions
Dispatch two independent patrol routes that share the `meeting_point`
corridor. RMF time-slots the shared corridor so robots pass through
one at a time.

---

## 9. What This Does NOT Change

- Gazebo simulation pod — unchanged
- Nav2 stack on each robot pod — unchanged (AMCL, planner, controller)
- Zenoh router pod — unchanged
- Robot spawn positions, colors, or map
- Existing `make reset` and manual `cmd_vel` control commands

---

## 10. Risks

| Risk | Likelihood | Impact | Mitigation |
|---|---|---|---|
| Coordinate transform calibration requires iteration | Medium | Medium | Start from existing `free_fleet` tb3 values; compare AMCL pose to RMF map at 4 known points |
| `free_fleet_adapter` binary not in apt (issue #166) | High (confirmed) | Low | Build from source in `Containerfile.rmf` — well-documented process |
| rmf-web dashboard WebSocket through HAProxy | Medium | Low | Use `haproxy.router.openshift.io/websocket: "true"` annotation (already proven for noVNC) |
| Zenoh version mismatch (`free_fleet` pins 1.5.0) | Low | Low | Test with current router; pin router image to 1.5.0 only if needed |
| RMF core DDS communication across OVN-K8s | Low | High | Mitigated by running all RMF core in a single pod on localhost DDS |

---

## 11. Out of Scope

The following are intentionally excluded from this proposal to keep scope
manageable:

- Multi-floor navigation (lifts, doors) — tb3_sandbox is single-level
- Multi-fleet coordination — one fleet (`turtlebot3`) in this demo  
- Persistent task database (PostgreSQL) — SQLite sufficient for demo
- Authentication / Keycloak — auth bypass for demo mode (same approach as the
  reference open-rmf hotel example)
- More than 2 robots — the Helm `robots:` list already supports N; RMF
  supports N with no config change beyond adding robots to the fleet YAML

---

## 12. Decision Points

The following require a decision before implementation begins:

1. **Nav graph complexity** — Should the nav graph include only the minimal
   5-waypoint graph described above, or a richer graph covering the full
   navigable area of `tb3_sandbox`? A richer graph enables more varied
   patrol routes but requires more `traffic_editor` authoring time.

2. **Dashboard authentication** — Keep the auth-bypass (demo mode, no login
   required) or integrate with an existing OpenShift OAuth/OIDC provider?
   The bypass is simpler but removes user context from the task audit log.

3. **Container image strategy** — Build a new `Containerfile.rmf` (separate
   image, ~3 GB) or extend the existing `quay.io/jianrzha/ros2-demo` image
   with the RMF packages added? Separate image is cleaner; combined image
   avoids maintaining a second image.

---

## 13. References

| Resource | Link |
|---|---|
| `free_fleet` repository | https://github.com/open-rmf/free_fleet |
| `free_fleet` multi-TB3 fleet config | https://github.com/open-rmf/free_fleet/blob/main/free_fleet_examples/config/fleet/nav2_unique_multi_tb3_simulation_fleet_config.yaml |
| `free_fleet` Zenoh bridge config for multi-TB3 | https://github.com/open-rmf/free_fleet/blob/main/free_fleet_examples/config/zenoh/nav2_unique_multi_tb3_zenoh_bridge_ros2dds_client_config.json5 |
| Open-RMF rmf_ros2 (traffic schedule + task dispatcher) | https://github.com/open-rmf/rmf_ros2 |
| rmf-web (dashboard + api-server) | https://github.com/open-rmf/rmf-web |
| Open-RMF Kubernetes deployment template | https://github.com/open-rmf/rmf_deployment_template |
| Technical deep-dive (internal) | `open-rmf-integration-proposal.md` in this repo |
