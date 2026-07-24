# Open-RMF Integration Proposal

## Executive Summary

This proposal describes how to integrate **Open-RMF** fleet management into the
existing multi-robot demo — adding true multi-robot traffic deconfliction,
autonomous task dispatch, and a real-time web dashboard — without modifying
any existing Nav2 nodes or Zenoh bridge infrastructure.

The integration uses **`free_fleet`**, an Open-RMF fleet adapter that already:
- Uses `zenoh-bridge-ros2dds` as its robot-communication layer (compatible with our Zenoh router)
- Has a 2-robot TurtleBot3 example that references the exact `tb3_sandbox` map we use
- Leaves Nav2 completely unmodified — bridges Nav2 actions over Zenoh

---

## Background

The current demo has no inter-robot collision avoidance. Each Nav2 pod has an
independent costmap that only knows about static walls; neither robot knows the
other exists. When paths conflict, Gazebo's physics engine stops them, requiring
a manual teleport to recover.

Open-RMF adds a **traffic schedule** layer above Nav2 that:
1. Maintains planned trajectories for all robots in a shared database
2. Detects conflicts using continuous collision detection (FCL) on trajectory splines
3. Runs a negotiation protocol to reroute one robot before a collision occurs
4. Dispatches tasks (patrol routes, deliveries) via a web dashboard

---

## Architecture

### Current (no RMF)

```
zenoh-router ←→ gazebo-sim (bridge: client)
             ←→ robot-nav-robot-1 (bridge: client)
             ←→ robot-nav-robot-2 (bridge: client)
```

### Proposed (with Open-RMF)

```
zenoh-router ←→ gazebo-sim (bridge: client, unchanged)
             ←→ robot-nav-robot-1 (bridge: client, expanded allowlist)
             ←→ robot-nav-robot-2 (bridge: client, expanded allowlist)
             ←→ rmf-core pod (free_fleet_adapter: Zenoh client)
                  │
                  ├── free_fleet_adapter  (reads TF, sends NavigateToPose)
                  ├── rmf-traffic-schedule (conflict detection + negotiation)
                  ├── rmf-task-dispatcher  (task allocation)
                  ├── rmf-web api-server   (:8000)
                  └── rmf-web dashboard    (:3000)
```

The `rmf-core` pod runs all RMF components on `localhost` DDS (`ROS_DOMAIN_ID=55`,
separate from the robots' domain 0), eliminating the OVN-Kubernetes multicast
problem for intra-RMF communication. It connects to the robots exclusively
through the existing Zenoh router.

### Data flow

```
Robot pod (ROS_DOMAIN_ID=0)           RMF pod (ROS_DOMAIN_ID=55)
─────────────────────────────         ──────────────────────────────
Nav2 AMCL publishes /tf          →    Zenoh router
  map → base_footprint                     → free_fleet_adapter
                                             reads TF, computes pose
                                             → rmf-traffic-schedule
                                               plans trajectory

rmf-traffic-schedule detects       →  free_fleet_adapter
  conflict, negotiates reroute           sends NavigateToPose action
                                       → Zenoh router
Nav2 controller_server receives →       robot_nav pod
  new NavigateToPose goal               executes rerouted path
```

---

## Key Component: free_fleet

`free_fleet` is the bridge between Open-RMF and unmodified Nav2 robots.

### How it reads robot pose

`free_fleet_adapter` subscribes to the Zenoh key `robot_N/tf`, deserializes
`TFMessage` payloads, injects them into a local `tf_buffer`, and calls
`lookup_transform(map_frame, base_footprint_frame)` to get the robot's current
pose. No changes to Nav2 or AMCL are required.

### How it sends navigation goals

`free_fleet_adapter` calls the Nav2 `NavigateToPose` action via Zenoh using
the key pattern `robot_N/navigate_to_pose/_action/send_goal`. The existing Nav2
action server handles it normally. The adapter polls `get_result` and calls
`more().replan()` if the action fails.

### Zenoh topics bridged per robot (additions to current config)

The Nav2 pod's zenoh-bridge allowlist needs to add three interfaces:

| Zenoh key pattern | Direction | Purpose |
|---|---|---|
| `robot_N/tf` | robot → RMF | Robot pose (map → base_footprint) |
| `robot_N/battery_state` | robot → RMF | Battery level (1 Hz) |
| `robot_N/navigate_to_pose/_action/*` | RMF → robot | Navigation goals from RMF |

All other topics (sensor data, cmd_vel) stay on their existing bridge config
between gazebo and Nav2 pods — no changes needed there.

---

## Traffic Deconfliction: How It Works

### Conflict detection

The `rmf-traffic-schedule` node maintains a trajectory database. Each
`free_fleet_adapter` submits planned routes as spline-interpolated trajectory
segments (position + time). The schedule runs FCL (Flexible Collision Library)
continuous collision detection against all pairs of robot trajectories:

1. **Bounding-box pre-check** (cheap): temporal overlap + spatial proximity
2. **FCL SplineMotion CCD** (if bounding boxes overlap): checks `footprint_A`
   (0.3m radius for TurtleBot3 Waffle) vs `vicinity_B` (0.5m radius)
3. If collision detected: publish `ConflictNotice` with robot IDs and time

### Negotiation protocol

Once a conflict is found:
1. Both fleet adapters receive `ConflictNotice`
2. Each runs a local A\* planner over the navigation graph with a
   `RouteValidator` that checks against the live trajectory schedule
3. One robot submits a rerouted `ConflictProposal`; the other accepts or rejects
4. Resolved within ~500ms; `ConflictConclusion` published; robots proceed
5. 30-second timeout with forced culling if negotiation stalls

The result: robots **yield to each other** before colliding, rather than
getting physically stuck.

---

## What Needs to Be Built

### 1. TurtleBot3 sandbox navigation graph

Open-RMF needs a navigation graph overlay on the `tb3_sandbox` map: a set of
named **waypoints** (positions where robots can stop, charge, or wait) and
**lanes** (bidirectional corridors between waypoints). This is authored in
`traffic_editor` and exported as a `0.yaml` nav graph file.

For the 2-robot demo, a minimal graph suffices:

```
Waypoints: robot_1_home (-2.0, -0.5), robot_2_home (2.0, 0.5),
           meeting_point (0.0, 0.0), charger_1 (-3.0, -1.0),
           charger_2 (3.0, 1.0)
Lanes: robot_1_home ↔ meeting_point ↔ robot_2_home
       charger_1 ↔ robot_1_home, charger_2 ↔ robot_2_home
```

### 2. Coordinate transform calibration (`reference_coordinates`)

The `free_fleet` fleet config requires 4+ matching point pairs between
RMF's traffic editor coordinate system and the robot's Nav2 map frame.
The `free_fleet_examples` already has calibration values for the
`turtlebot3_world` simulation — since `tb3_sandbox` uses the same physical
map, these values are a reasonable starting point and may need minor tuning.

```yaml
reference_coordinates:
  L1:
    rmf:   [[8.9508, -6.6006], [7.1006, -9.1508],
             [12.3511, -9.2008], [11.0510, -11.8010]]
    robot: [[-1.04555, 2.5456], [-2.90519, 0.00186],
             [2.39611, -0.061773], [1.08783, -2.59750]]
```

### 3. Building map file (`tb3_sandbox.building.yaml`)

A `traffic_editor` project file that references the map PNG
(`tb3_sandbox.png`), nav graph (`0.yaml`), and lift/door definitions.
For a 2-robot flat-floor demo: no lifts, no doors, single level `L1`.

### 4. Fleet configuration YAML

```yaml
rmf_fleet:
  name: "turtlebot3"
  profile:
    footprint: 0.3        # TurtleBot3 Waffle radius (m)
    vicinity: 0.5         # Conflict detection zone (m)
  limits:
    linear: [0.26, 0.5]   # max velocity, acceleration (m/s, m/s²)
    angular: [1.0, 2.0]
  task_capabilities:
    loop: true
  finishing_request: "park"
  account_for_battery_drain: false   # simpler for demo
  robots:
    robot_1:
      charger: "charger_1"
      navigation_stack: 2            # Nav2
      initial_map: "L1"
      maps:
        L1:
          map_url: "/nav2_bringup/maps/tb3_sandbox.yaml"
    robot_2:
      charger: "charger_2"
      navigation_stack: 2
      initial_map: "L1"
      maps:
        L1:
          map_url: "/nav2_bringup/maps/tb3_sandbox.yaml"
```

### 5. Updated zenoh bridge configs for Nav2 pods

Add `navigate_to_pose` action and `tf` to the `allow` list in the Nav2
zenoh bridge config (currently only sensor topics and cmd_vel flow through):

```json5
{
  plugins: {
    ros2dds: {
      allow: {
        publishers:     [".*/(tf|battery_state)"],
        subscribers:    [".*/navigate_to_pose/_action/.*"],
        service_servers:[".*/navigate_to_pose/_action/.*"]
      }
    }
  },
  mode: "client",
  connect: { endpoints: ["tcp/zenoh-router:7447"] }
}
```

### 6. New Helm templates

| Template | Resources |
|---|---|
| `deployment-rmf-core.yaml` | `rmf-core` Deployment (all RMF components + rmf-web) |
| `service-rmf.yaml` | ClusterIP for api-server (:8000), dashboard (:3000), trajectory (:8006) |
| `configmap-rmf.yaml` | Building map, nav graph, fleet YAML, bridge configs |
| `route-rmf.yaml` | OpenShift Routes for dashboard and api-server |

---

## Deployment Topology

```
Pods after integration:

  zenoh-router        (unchanged)
  gazebo-sim          (unchanged)
  robot-nav-robot-1   (updated zenoh bridge config)
  robot-nav-robot-2   (updated zenoh bridge config)
  rmf-core            (new)
    ├── free_fleet_adapter   (ROS_DOMAIN_ID=55, connects to Zenoh router)
    ├── rmf-traffic-schedule (ROS_DOMAIN_ID=55, localhost DDS)
    ├── rmf-task-dispatcher  (ROS_DOMAIN_ID=55, localhost DDS)
    ├── rmf-web api-server   (:8000)
    └── rmf-web dashboard    (:3000)
```

### Resource estimate for `rmf-core` pod

| Resource | Request | Limit |
|---|---|---|
| CPU | 2 cores | 4 cores |
| Memory | 2 Gi | 4 Gi |

RMF core nodes are lightweight. `rmf-web` (api-server + dashboard) is a
FastAPI + React stack that adds ~500 MB overhead.

---

## Demo Scenarios Enabled

### Scenario 1: Manual task dispatch (patrol)

```bash
ros2 run rmf_demos_tasks dispatch_patrol \
  -p robot_1_home meeting_point robot_2_home -n 2 \
  --use_sim_time
```

Watch both robots navigate the route, yielding to each other at the meeting
point waypoint rather than colliding.

### Scenario 2: Head-on conflict resolution

Dispatch robot_1 to `robot_2_home` and robot_2 to `robot_1_home`
simultaneously (the "meet demo" scenario). RMF's traffic schedule detects
the head-on conflict ~2 s before it would occur, negotiates a hold for
one robot, and lets the other pass first — autonomously, without a teleport.

### Scenario 3: Task dashboard

Open the rmf-web dashboard route in a browser. See both robots on the
`tb3_sandbox` map, dispatch tasks via the UI, and monitor task status
(queued → in_progress → completed).

---

## Implementation Phases

### Phase 1 — Map authoring (1–2 days)
- Install `traffic_editor`, open `tb3_sandbox.png`
- Place waypoints at robot homes, meeting point, and charger spots
- Draw lanes, export nav graph `0.yaml` and `tb3_sandbox.building.yaml`
- Verify coordinate transform against known Nav2 map coordinates

### Phase 2 — RMF core pod (2–3 days)
- Build a new container image (`ros-jazzy-rmf-dev` base) with:
  - `free_fleet_adapter` + `rmf_traffic_ros2` + `rmf_task_ros2`
  - `rmf-web` api-server + pre-built dashboard static files
- Write the `deployment-rmf-core.yaml` Helm template
- Configure `ROS_DOMAIN_ID=55`, `server_uri` wiring

### Phase 3 — Zenoh bridge config update (0.5 days)
- Extend Nav2 pod zenoh bridge `allow` list to include `tf`, `battery_state`,
  and `navigate_to_pose` action interfaces
- Test that `free_fleet_adapter` can read both robots' TF and send goals

### Phase 4 — Integration testing (1–2 days)
- Verify traffic schedule detects conflicts on the patrol route
- Verify negotiation resolves head-on scenarios without manual teleport
- Tune `vicinity` radius and conflict-check window if needed
- Validate rmf-web dashboard shows live robot positions

### Phase 5 — Helm chart and documentation (1 day)
- Add all new templates to `helm/multi-robot-demo/`
- Update `values.yaml` with RMF image and fleet config
- Update README and `meet_demo.py` to use `dispatch_patrol` instead of
  raw `cmd_vel`

---

## Risks and Mitigations

| Risk | Likelihood | Mitigation |
|---|---|---|
| Coordinate transform calibration is off — robots appear in wrong map position | Medium | Use the existing `free_fleet` tb3 calibration values as a baseline; compare AMCL pose against RMF map position at 3–4 known waypoints and adjust |
| `rmf_demos` binary packages excluded from apt (known issue #166) | High (confirmed) | Build `free_fleet_adapter` + `rmf_traffic_ros2` from source in the container image; binaries exist for `rmf-dev` |
| RMF nav graph needs to match actual navigable areas in tb3_sandbox | Medium | Draw lanes conservatively along wall-free corridors; test each lane with a manual `dispatch_patrol` before adding more |
| rmf-web WebSocket through OpenShift HAProxy | Medium | Use `haproxy.router.openshift.io/websocket: "true"` annotation (already used for noVNC); trajectory server on port 8006 may need plain HTTP route |
| `free_fleet` Zenoh version pinned to 1.5.0; our router runs latest | Low | Pin the `eclipse/zenoh` router image to 1.5.0 to match; or test current version and only pin if incompatible |

---

## What Open-RMF Does NOT Handle in This Demo

- **Physical lift/door coordination** — not needed for single-level sandbox
- **Multi-fleet task bidding** — only one fleet (`turtlebot3`) in this demo
- **Persistent task history** — api-server will use SQLite (no PostgreSQL)
- **Authentication** — dashboard will use the same auth-bypass pattern as the
  reference open-rmf example (no Keycloak)

---

## References

| Source | Relevance |
|---|---|
| [open-rmf/free_fleet](https://github.com/open-rmf/free_fleet) | Core integration library; Nav2 robot adapter; TurtleBot3 multi-robot example |
| [free_fleet multi-tb3 fleet config](https://github.com/open-rmf/free_fleet/blob/main/free_fleet_examples/config/fleet/nav2_unique_multi_tb3_simulation_fleet_config.yaml) | Baseline fleet YAML with coordinate transform for tb3_sandbox |
| [free_fleet zenoh bridge config](https://github.com/open-rmf/free_fleet/blob/main/free_fleet_examples/config/zenoh/nav2_unique_multi_tb3_zenoh_bridge_ros2dds_client_config.json5) | Exact allow-list for tf, battery_state, navigate_to_pose |
| [open-rmf/rmf_ros2](https://github.com/open-rmf/rmf_ros2) | rmf-traffic-schedule, rmf-task-dispatcher source |
| [open-rmf/rmf-web](https://github.com/open-rmf/rmf-web) | Dashboard + api-server |
| [open-rmf/rmf_deployment_template](https://github.com/open-rmf/rmf_deployment_template) | Helm chart reference for Kubernetes deployment |
| [lokeshrangineni/ros2-openshift-demo open-rmf](../../../rokesh-ros2-openshift-demo/examples/open-rmf/) | Existing OpenShift open-rmf example (hotel world, single pod, slot-car navigation — not Nav2) |
