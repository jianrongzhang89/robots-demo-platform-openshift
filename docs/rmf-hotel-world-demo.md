# Open-RMF Hotel World Demo

A cloud-native robotics demo running the canonical Open-RMF hotel world on
OpenShift in a single pod. The hotel building has three levels (lobby + two
guest floors), two lifts, automatic doors, and three slotcar robot fleets
managed by RMF's full-control fleet adapters — with no per-robot Nav2 stack
required.

**Branch**: `rmf-hotel-world-demo`  
**Namespace**: `ros2-rmf-hotel`  
**Image**: `quay.io/jianrzha/ros2-rmf-hotel:latest`

---

## What the Demo Shows

The upstream [open-rmf/rmf_demos](https://github.com/open-rmf/rmf_demos)
hotel world with three robot fleets operating simultaneously:

| Fleet | Model | Nav graph | Floors |
|-------|-------|-----------|--------|
| `TinyRobot` | slotcar | 0 | Lobby (L1) |
| `cleanerBotA` | slotcar | 1 | L1 + L2 (uses Lift A) |
| `DeliveryRobot` | slotcar | 2 | L1 + L3 (uses Lift B) |

All fleets are managed by RMF `full_control` fleet adapters. Robots ride the
lifts automatically between floors when their patrol waypoints span levels.

### Default Dispatch

The `dispatch-hotel` Makefile target sends a `dispatch_patrol` task to the
first available robot in any fleet, requesting a two-waypoint patrol that
spans levels (lobby → level-3 room via Lift B):

```
L3_room1 → L3_room1   (loops, so the robot returns to L3_room1)
```

The robot leaves L1, enters Lift B, rides up to L3, navigates to `L3_room1`,
then returns — demonstrating automatic lift traversal.

---

## Architecture

Single pod, single DDS domain (`ROS_DOMAIN_ID=0`). All RMF processes run
in-process within the same Gazebo context — no Zenoh, no cross-pod bridging.

```
┌─────────────────── OpenShift namespace: ros2-rmf-hotel ───────────────────┐
│                                                                            │
│  ┌─────────────────────────────── Pod: hotel-sim ──────────────────────┐  │
│  │                                                                      │  │
│  │  Xvfb → openbox → x11vnc → websockify (noVNC :6080)                 │  │
│  │                                                                      │  │
│  │  gz sim                 hotel.world (3 levels, 2 lifts, doors)       │  │
│  │  ├── rmf_building_sim_gz_plugins  (lift + door controllers)          │  │
│  │  └── rmf_robot_sim_gz_plugins     (slotcar kinematic model)          │  │
│  │                                                                      │  │
│  │  ros2 launch rmf_demos_gz hotel.launch.xml                           │  │
│  │  ├── building_map_server  (serves building.yaml + nav graphs)        │  │
│  │  ├── door_supervisor                                                  │  │
│  │  ├── lift_supervisor                                                  │  │
│  │  ├── rmf_traffic_schedule                                             │  │
│  │  ├── rmf_task_ros2         (task dispatcher)                          │  │
│  │  ├── fleet_adapter (TinyRobot,  graph 0)                              │  │
│  │  ├── fleet_adapter (cleanerBotA, graph 1)                             │  │
│  │  └── fleet_adapter (DeliveryRobot, graph 2)                           │  │
│  │                                                                      │  │
│  │  Optional: rmf-web api-server :8000 + dashboard :3000                │  │
│  └──────────────────────────────────────────────────────────────────────┘  │
│                                                                            │
│  Route: hotel-novnc       → :6080  (noVNC browser view)                   │
│  Route: hotel-dashboard   → :3000  (rmf-web dashboard)                    │
└────────────────────────────────────────────────────────────────────────────┘
```

### Why Single Pod?

Slotcar robots are driven entirely by the Gazebo plugins — there is no
separate Nav2 stack or cross-pod communication to worry about. A single
pod eliminates all Zenoh/DDS bridge complexity from earlier demos and is
the correct architecture for this fleet type.

This is also the cleanest seam for adding a real Nav2 fleet later (Step 2):
spin up a second pod with Nav2 + free_fleet_adapter and connect it to the
same RMF traffic schedule.

---

## Quick-Start

### 1. Build and Push the Image

```bash
make build-push-hotel
# Builds Containerfile.hotel (Ubuntu ros:jazzy + source-built rmf_demos)
# and pushes to quay.io/jianrzha/ros2-rmf-hotel:latest
```

> The build clones and compiles `open-rmf/rmf_demos` (jazzy branch) from
> source — `rmf-demos-gz` and `rmf-demos-maps` are not available as Jazzy
> debs. Expect ~10-15 min for the first build.

### 2. Deploy

```bash
make deploy-hotel NAMESPACE=ros2-rmf-hotel
```

This installs only the hotel resources (single pod + 2 services + 2 routes)
while suppressing all Nav2/Zenoh/multi-pod templates via `hotel.enabled=true`.

### 3. Wait for Ready

The hotel pod takes ~3 min to start (Gazebo + RMF initialisation, RTF ≈ 0.5).
The liveness probe TCP-checks `:6080`; the pod enters `Running` once noVNC
is up.

```bash
oc get pod -n ros2-rmf-hotel -w
# Look for: hotel-sim-XXXXX   1/1   Running
```

### 4. Dispatch a Patrol

```bash
make dispatch-hotel NAMESPACE=ros2-rmf-hotel
# Sends a multi-level patrol: lobby → L3_room1 via Lift B
```

Override waypoints or loop count:
```bash
make dispatch-hotel NAMESPACE=ros2-rmf-hotel \
  HOTEL_WAYPOINTS="L1_n1 L1_n2" HOTEL_LOOPS=3
```

### 5. Watch in noVNC

```bash
make routes NAMESPACE=ros2-rmf-hotel
# Prints the hotel-novnc URL
```

Open the URL and switch the Gazebo camera to the lift area to watch the
robot ride between floors.

---

## Configuration

### values-hotel.yaml (key overrides)

```yaml
namespace: ros2-rmf-hotel

hotel:
  enabled: true
  image: quay.io/jianrzha/ros2-rmf-hotel:latest
  resolution: "1600x900x24"
  launchArgs: ""          # passed verbatim to hotel.launch.xml
  resources:
    requests: { cpu: "4", memory: "4Gi" }
    limits:   { cpu: "8", memory: "8Gi" }
```

### Launch File Arguments

The entrypoint runs:
```
ros2 launch rmf_demos_gz hotel.launch.xml ${HOTEL_LAUNCH_ARGS}
```

Set `launchArgs` in `values-hotel.yaml` or `--set hotel.launchArgs=...` to
pass arguments to the launch file (e.g., `use_sim_time:=true headless:=false`).

---

## Makefile Reference

```bash
make build-hotel           # Build hotel image (linux/amd64)
make push-hotel            # Push hotel image
make build-push-hotel      # Build + push
make deploy-hotel          # Helm install/upgrade with hotel values
make dispatch-hotel        # Dispatch multi-level patrol task
```

`dispatch-hotel` variables:

| Variable | Default | Description |
|----------|---------|-------------|
| `HOTEL_WAYPOINTS` | `L3_room1 L3_room1` | Space-separated patrol waypoints |
| `HOTEL_LOOPS` | `1` | Number of patrol loops (`-n`) |
| `NAMESPACE` | *(inherited)* | OpenShift namespace to exec into |

---

## Container Image

### Image: `quay.io/jianrzha/ros2-rmf-hotel:latest`

**Base**: `ros:jazzy` (Ubuntu 24.04)

**Contents**:
- ROS2 Jazzy + CycloneDDS
- Gazebo Harmonic + OSRF ros-gz bridge
- `rmf-building-sim-gz-plugins`, `rmf-robot-sim-gz-plugins` (apt)
- `rmf-building-map-tools`, `rmf-demos-tasks`, `rmf-demos-fleet-adapter` (apt)
- `rmf_demos` repo (jazzy branch) — source-built at `/opt/rmf_demos_ws/install`
  (provides `rmf_demos_gz`, `rmf_demos_maps`, `rmf_demos` launch files)
- noVNC stack: Xvfb + openbox + x11vnc + websockify
- Optional: rmf-web api-server + dashboard

**Build command**:
```bash
make build-push-hotel
# equivalent to:
podman build --platform linux/amd64 \
  -t quay.io/jianrzha/ros2-rmf-hotel:latest \
  -f Containerfile.hotel .
podman push quay.io/jianrzha/ros2-rmf-hotel:latest
```

**Image hierarchy** (independent from the Fedora/Nav2 line):
```
ubuntu:24.04 (ros:jazzy)
  └── quay.io/jianrzha/ros2-rmf-hotel:latest   ← this demo
```

**OCI Labels**:

| Label | Value |
|-------|-------|
| `org.opencontainers.image.title` | `Open-RMF Hotel World Demo` |
| `org.opencontainers.image.description` | Multi-level hotel world with slotcar fleets, lifts, and doors via Open-RMF |
| `org.opencontainers.image.source` | https://github.com/jianrongzhang89/robots-demo-platform-openshift |
| `org.opencontainers.image.branch` | `rmf-hotel-world-demo` |
| `io.openshift.tags` | `ros2,gazebo,open-rmf,rmf,hotel,robotics,jazzy` |

---

## Key Files

| File | Purpose |
|------|---------|
| `Containerfile.hotel` | Ubuntu ros:jazzy image; source-builds rmf_demos |
| `entrypoints/entrypoint-hotel.sh` | Single-pod entrypoint: noVNC + RMF launch |
| `helm/multi-robot-demo/values-hotel.yaml` | Hotel demo Helm overrides |
| `helm/multi-robot-demo/templates/deployment-hotel.yaml` | Hotel pod definition |
| `helm/multi-robot-demo/templates/services-routes-hotel.yaml` | noVNC + dashboard routes |

---

## Known Limitations

### 1. RTF ≈ 0.5 (Software Rendering)

Gazebo runs at ~half real-time with `LIBGL_ALWAYS_SOFTWARE=1` (Mesa llvmpipe).
All timeouts (lift travel, door open/close, fleet adapter response) are doubled
relative to upstream documentation. GPU-accelerated nodes would achieve RTF ≈ 1.

### 2. rmf_demos Source Build (~10–15 min)

`rmf-demos-gz` and `rmf-demos-maps` are not released as Jazzy debs. The
Containerfile clones and builds the `jazzy` branch at image build time. The
`build` and `log` directories are removed to keep the layer lean, but the
source checkout adds ~5 min to the build.

### 3. Waypoint Names Must Match Nav Graphs

The `HOTEL_WAYPOINTS` must exactly match waypoint names in the hotel nav graphs
(defined in `rmf_demos_maps`). Inspect them with:
```bash
POD=$(oc get pod -n ros2-rmf-hotel -l app=hotel-sim \
  -o jsonpath='{.items[0].metadata.name}')
oc exec -n ros2-rmf-hotel $POD -c hotel -- bash -c '
  source /opt/ros/jazzy/setup.bash
  source /opt/rmf_demos_ws/install/setup.bash
  ros2 run rmf_demos_tasks dispatch_patrol -h'
```

---

## Roadmap: Adding a Nav2 Fleet (Step 2)

The single-pod architecture is intentionally designed as a foundation. Adding
a real Nav2 fleet alongside the slotcar fleets requires:

1. A separate `robot-nav` pod (Fedora + Nav2) connected to the same
   `ros2-rmf-hotel` namespace via Zenoh.
2. A `free_fleet_adapter` instance in the hotel pod (or as a sidecar)
   with a nav graph that maps to the real building layout.
3. The `nav2_relay.py` pattern from the existing Nav2 demos.

The RMF infrastructure (building_map_server, traffic schedule, task dispatcher)
is already fleet-agnostic — it needs no changes to support a new fleet type.
See `values-hotel.yaml` for the commented Step 2 seam.
