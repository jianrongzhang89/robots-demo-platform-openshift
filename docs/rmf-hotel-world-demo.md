# Open-RMF Hotel World Demo

A cloud-native robotics demo running the Open-RMF hotel world on OpenShift
in a **single pod**. The hotel building has three levels (lobby + two guest
floors), two lifts, automatic doors, and four slotcar robots managed by
RMF's full-control fleet adapters — with no per-robot Nav2 stack required.

**Branch**: `rmf-hotel-world-demo`  
**Namespace**: `ros2-rmf-hotel`  
**Image**: `quay.io/jianrzha/ros2-rmf-hotel:latest`  
**Build**: OpenShift BuildConfig `hotel-image-build` (~20 min on cluster)

---

## What the Demo Shows

Four robots patrolling dedicated zones across the hotel lobby floor (L1),
all managed and dispatched by Open-RMF:

| Robot | Color | Fleet | Zone | Movement |
|-------|-------|-------|------|----------|
| `deliveryBot_1` | 🔴 Red | `deliveryRobot` | West corridor | Up to 17m — deepest into the building |
| `tinyBot_1` | Blue | `tinyRobot` | Center-east lobby | N ↔ S sweep |
| `cleanerBotA_1` | Gray | `cleanerBotA` | South-west lobby | N ↔ S sweep |
| `cleanerBotA_2` | Gray | `cleanerBotA` | South strip | N ↔ S sweep |

The demo illustrates:
- **RMF task dispatch and bidding** — tasks are auctioned to the cheapest fleet
- **Puppet Controller** — drives robots via the fleet_manager REST API (see [Known Limitation](#known-limitation--easyfullcontrol-sigsegv))
- **Gazebo 3D visualization** — hotel building with 3 floors visible over noVNC
- **Continuous autonomous patrol** — robots run indefinitely without intervention

---

## Quick-Start (Repeating the Demo)

### Prerequisites

- OpenShift cluster with the `ros2-rmf-hotel` namespace and `hotel-image-build` BuildConfig
- `oc` CLI logged in and targeting the correct cluster
- This repo checked out on the `rmf-hotel-world-demo` branch

### 1. Deploy

```bash
make deploy-hotel NAMESPACE=ros2-rmf-hotel \
  IMAGE_HOTEL_REF=quay.io/jianrzha/ros2-rmf-hotel:latest
```

### 2. Wait for initialization (~90 seconds)

```bash
oc get pod -n ros2-rmf-hotel -w
# Wait for: hotel-sim-XXXXX   1/1   Running
```

Look for these lines in the logs to confirm everything is ready:

```bash
oc logs -n ros2-rmf-hotel $(oc get pod -n ros2-rmf-hotel -l app=hotel-sim \
  -o jsonpath='{.items[0].metadata.name}') | grep "Successfully added"
# Should show: deliveryBot_1, tinyBot_1, cleanerBotA_1, cleanerBotA_2
```

### 3. Start continuous patrol

```bash
make patrol-hotel NAMESPACE=ros2-rmf-hotel
```

This runs the 4-robot patrol loop (prints a position report every cycle).
Press **Ctrl-C** to stop.

### 4. Watch in noVNC

```bash
make routes NAMESPACE=ros2-rmf-hotel
# Prints the hotel-novnc URL
```

Open the URL in a browser. In the Gazebo view you will see:
- 🔴 Red delivery robot moving through the western hotel corridor
- Blue tinyBot sweeping across the center-east lobby
- Two gray cleaner robots patrolling the south lobby

---

## Architecture

Single pod, single localhost DDS domain (`ROS_DOMAIN_ID=0`). No Zenoh,
no cross-pod bridging.

```
┌─────────────────── OpenShift namespace: ros2-rmf-hotel ───────────────────┐
│                                                                            │
│  ┌─────────────────────────── Pod: hotel-sim ──────────────────────────┐  │
│  │                                                                      │  │
│  │  Xorg (dummy driver) → x11vnc → websockify → noVNC :6080            │  │
│  │                                                                      │  │
│  │  gz sim (server + GUI) ── hotel.world (3 floors, 2 lifts, doors)    │  │
│  │    ├── rmf_building_sim_gz_plugins  (lift + door controllers)        │  │
│  │    └── rmf_robot_sim_gz_plugins     (slotcar kinematic drive)        │  │
│  │                                                                      │  │
│  │  ros2 launch rmf_demos_gz hotel.launch.xml                           │  │
│  │    ├── building_map_server   (hotel building YAML + nav graphs)      │  │
│  │    ├── door_supervisor / lift_supervisor                              │  │
│  │    ├── rmf_traffic_schedule + rmf_task_ros2                           │  │
│  │    ├── fleet_adapter × 3    (tinyRobot, cleanerBotA, deliveryRobot)  │  │
│  │    └── fleet_manager × 3    (REST servers :22011/:22012/:22013)      │  │
│  │                                                                      │  │
│  │  rmf_puppet_controller.py   (monitors /dispatch_states, drives       │  │
│  │                              robots via fleet_manager HTTP API)      │  │
│  │                                                                      │  │
│  │  static_transform_publisher (map TF root frame for RViz2)            │  │
│  └──────────────────────────────────────────────────────────────────────┘  │
│                                                                            │
│  Route: hotel-novnc     → :6080  (Gazebo GUI over noVNC)                   │
│  Route: hotel-dashboard → :3000  (rmf-web dashboard, if available)         │
└────────────────────────────────────────────────────────────────────────────┘
```

---

## Patrol Zones

Each robot is assigned a dedicated non-overlapping zone to avoid collision
avoidance deadlocks. The zone boundaries are tuned to the hotel building's
wall layout:

```
   X →  12    15    19    23    27
Y        │     │     │     │     │
-22  ────┤deliveryBot north turn  │
         │  (west corridor)       │
-27  ────┤   tinyBot_1 patrol     │──── cleanerBotA_1 ───┤
         │   x=22, y=-26 to -30  │   x=15, y=-30 to -35 │
-30  ────┤                       │                       │
         │                       │   cleanerBotA_2       │
-35  ────┤deliveryBot south turn  │   x=22, y=-33 to -37 │
         │   v5 (14.87,-28.77)   │                       │
```

The delivery robot travels the deepest route (up to 17 m) through the
western hotel corridor via proven waypoints v5→v7→v8→v9.

---

## Makefile Reference

```bash
# Image lifecycle (local Podman build — needs 14+ GB VM)
make build-hotel           # Build image locally
make push-hotel            # Push to quay.io
make build-push-hotel      # Build + push

# Cluster build (recommended — uses OpenShift node RAM, ~20 min)
oc start-build hotel-image-build --from-dir=. -n ros2-rmf-hotel

# Deployment
make deploy-hotel NAMESPACE=ros2-rmf-hotel \
  IMAGE_HOTEL_REF=quay.io/jianrzha/ros2-rmf-hotel:latest

# Demo
make patrol-hotel NAMESPACE=ros2-rmf-hotel   # continuous 4-robot patrol loop
make dispatch-hotel NAMESPACE=ros2-rmf-hotel # one-off RMF task dispatch
```

---

## Key Files

| File | Purpose |
|------|---------|
| `Containerfile.hotel` | Image build: Ubuntu ros:jazzy, source-builds rmf_ros2 + rmf_simulation + rmf_demos |
| `entrypoints/entrypoint-hotel.sh` | Pod entrypoint: Xorg, map TF, puppet controller, RMF launch |
| `entrypoints/rmf_puppet_controller.py` | Monitors `/dispatch_states`, drives robots via fleet_manager HTTP |
| `scripts/hotel_patrol_loop.py` | Continuous 4-robot patrol loop (called by `make patrol-hotel`) |
| `scripts/hotel-build/create_stubs.py` | Creates stub SDF models for 27 furniture items not in apt packages |
| `scripts/hotel-build/patch_cleaner_spawns.py` | Moves cleaner spawns from locked rooms to open lobby; patches nav graph charger waypoints |
| `scripts/hotel-build/patch_delivery_robot_color.py` | Sets DeliveryRobot body material to red for visibility |
| `scripts/hotel-build/patch_fleet_adapter.py` | Thread-safe callback wrappers (GC + Python 3.12 fix) |
| `helm/multi-robot-demo/values-hotel.yaml` | Helm overrides: namespace, image, resources |
| `helm/multi-robot-demo/templates/deployment-hotel.yaml` | Hotel pod spec |
| `helm/multi-robot-demo/templates/services-routes-hotel.yaml` | noVNC + dashboard routes |
| `config/hotel/xorg-dummy.conf` | Xorg dummy driver for headless OpenGL rendering over VNC |

---

## Build Details

The image is built on the OpenShift cluster (not locally) because compiling
`rmf_fleet_adapter` from source requires ~28 GB RAM which exceeds local VM limits.

### Stages

**Stage A — `rmf_ros2` + `rmf_simulation`** (`/opt/rmf_ros2_ws`):
Builds `rmf_fleet_adapter`, `rmf_traffic_ros2`, `rmf_task_ros2`, and
`rmf_robot_sim_gz_plugins` from the jazzy branch. This ensures ABI
compatibility between all C++ RMF components.

**Stage B — `rmf_demos`** (`/opt/rmf_demos_ws`):
Builds the hotel world assets (hotel.world, nav graphs, building maps,
launch files) from the jazzy branch, sourcing Stage A's overlay.

**Build-time patches** (applied after Stage B):
- `create_stubs.py` — 27 zero-geometry SDF stub models for furniture that
  gz sim would otherwise fail to load (exits before plugin init without them)
- `patch_cleaner_spawns.py` — moves `cleanerBotA_1/2` spawn from enclosed
  rooms (behind locked doors) to the open south lobby; also patches the nav
  graph charger waypoints so the fleet adapter's startup parking task keeps
  robots in the lobby
- `patch_delivery_robot_color.py` — DeliveryRobot body → red (RGBA 0.8 0 0 1)
- `patch_fleet_adapter.py` — wraps Python callbacks in daemon threads to
  prevent GC and Python 3.12/pybind11 threading issues

### Triggering a Rebuild

```bash
cd <repo-root>
oc start-build hotel-image-build --from-dir=. -n ros2-rmf-hotel
# Monitor:
oc logs hotel-image-build-N-build -n ros2-rmf-hotel -f
```

---

## Known Limitation — EasyFullControl SIGSEGV

The `librmf_fleet_adapter.so 2.7.2` (apt-installed) crashes with SIGSEGV
the moment the EasyFullControl C++ tries to execute any navigation task.
Root cause: pybind11 calls a Python callback from a non-Python C++ thread
without proper GIL setup on Python 3.12.

**Workaround — `rmf_puppet_controller.py`**:

The Puppet Controller bypasses the crashing C++ execution path entirely:

1. Monitors `/dispatch_states` (published by the RMF task dispatcher)
2. When a task is awarded to a robot, reads the destination waypoint
3. Sends an HTTP `POST /navigate` to the fleet_manager REST server
4. The fleet_manager publishes a `PathRequest` to `/robot_path_requests`
5. The slotcar plugin subscribes and drives the robot to the destination

RMF task management (bidding, awarding, scheduling) works correctly; only
the C++ task *execution* path is bypassed.

**Effect on the demo**: robots move autonomously in response to RMF tasks.
The EasyFullControl crash does not affect the visible behaviour — the patrol
loop (`make patrol-hotel`) keeps all four robots cycling continuously.

---

## Visualization Stack

The Gazebo GUI renders on a headless Xorg display (dummy driver) and is
exposed over VNC:

```
gz sim GUI → Xorg :99 (dummy driver, llvmpipe software GL)
                ↓
           x11vnc :5900
                ↓
        websockify :6080 (noVNC web proxy)
                ↓
        Browser ← OpenShift Route (TLS edge, 10 min timeout)
```

**Why Xorg+dummy, not Xvfb**: Xvfb uses direct DRI rendering which bypasses
the X framebuffer. x11vnc cannot capture direct-rendered GL content. Xorg with
the dummy video driver uses a shared-memory framebuffer that x11vnc can capture.

**Why `QT_QPA_PLATFORM=xcb`**: Qt6 on Ubuntu 24.04 probes for Wayland first.
Without this env var, the Gazebo GUI creates an off-screen EGL surface that
never composites to the X display, leaving the noVNC canvas black.

---

## RTF and Timing

Gazebo runs at approximately **RTF ≈ 0.5** (software llvmpipe rendering on
cluster nodes without GPU). All motion is half real-time:

| Metric | Value |
|--------|-------|
| Nominal slotcar speed | 0.65 m/s |
| Effective speed (RTF 0.5) | ~0.33 m/s wall-clock |
| deliveryBot corridor traversal | ~90 s for 17 m route |
| Full patrol cycle (all 4 robots) | ~3–5 minutes |

---

## Roadmap — Adding a Nav2 Fleet (Step 2)

The RMF infrastructure (building_map_server, traffic schedule, task
dispatcher) is fleet-agnostic. Adding a Nav2-driven robot requires:

1. A separate `robot-nav` pod (Fedora + Nav2) in the same namespace
2. A `free_fleet_adapter` sidecar with a nav graph for the hotel corridors
3. The `nav2_relay.py` pattern from the existing Nav2 demos

See `values-hotel.yaml` for the Step 2 seam comments.
