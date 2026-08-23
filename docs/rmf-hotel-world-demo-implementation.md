# Open-RMF Hotel World Demo — Implementation Notes

This document covers the **current working implementation** of the hotel demo
on OpenShift (branch `rmf-hotel-world-demo`). For the target architecture and
roadmap, see [`rmf-hotel-world-demo.md`](rmf-hotel-world-demo.md).

---

## What is Running

Four robots patrol continuously across the hotel lobby (L1) in dedicated
non-overlapping zones, all dispatched and tracked by Open-RMF:

| Robot | Color | Fleet | Patrol Zone |
|-------|-------|-------|-------------|
| `deliveryBot_1` | 🔴 **Red** | `deliveryRobot` | West corridor — up to 17 m deep |
| `tinyBot_1` | Blue | `tinyRobot` | Center-east lobby, N ↔ S |
| `cleanerBotA_1` | Gray | `cleanerBotA` | South-west lobby, N ↔ S |
| `cleanerBotA_2` | Gray | `cleanerBotA` | South strip, N ↔ S |

**noVNC URL:**  
`https://hotel-novnc-ros2-rmf-hotel.apps.ai-dev02.kni.syseng.devcluster.openshift.com`

---

## How to Run the Demo

### Prerequisites

- `oc` CLI logged into the cluster
- Repo on branch `rmf-hotel-world-demo`
- Namespace `ros2-rmf-hotel` with `hotel-image-build` BuildConfig

### 1. Deploy

```bash
make deploy-hotel NAMESPACE=ros2-rmf-hotel \
  IMAGE_HOTEL_REF=quay.io/jianrzha/ros2-rmf-hotel:latest
```

### 2. Wait ~90 s for initialization

```bash
# Confirm all 4 robots registered:
oc logs -n ros2-rmf-hotel \
  $(oc get pod -n ros2-rmf-hotel -l app=hotel-sim \
    -o jsonpath='{.items[0].metadata.name}') \
  | grep "Successfully added"
# Expected: deliveryBot_1, tinyBot_1, cleanerBotA_1, cleanerBotA_2
```

### 3. Start continuous patrol

```bash
make patrol-hotel NAMESPACE=ros2-rmf-hotel
# Runs until Ctrl-C; prints position report each cycle
```

### 4. Open noVNC

```bash
make routes NAMESPACE=ros2-rmf-hotel
```

---

## Image Build

The image must be built on the **OpenShift cluster** (not locally) because
compiling `rmf_fleet_adapter` from source needs ~28 GB RAM.

```bash
cd <repo-root>
oc start-build hotel-image-build --from-dir=. -n ros2-rmf-hotel
# Monitor:
oc logs hotel-image-build-N-build -n ros2-rmf-hotel -f
# Takes ~20 min; pushes automatically to quay.io/jianrzha/ros2-rmf-hotel:latest
```

### Build stages

| Stage | Workspace | Contents |
|-------|-----------|---------|
| A | `/opt/rmf_ros2_ws` | `rmf_ros2` + `rmf_simulation` — source-built for ABI consistency |
| B | `/opt/rmf_demos_ws` | `rmf_demos` — hotel world assets, nav graphs, launch files |

### Build-time patches (applied after Stage B)

| Script | Effect |
|--------|--------|
| `scripts/hotel-build/create_stubs.py` | Creates 27 zero-geometry SDF stub models for furniture (`CoffeeTable`, `Sofa`, etc.) — without them gz sim exits before loading any plugin |
| `scripts/hotel-build/patch_cleaner_spawns.py` | Moves `cleanerBotA_1/2` spawn from enclosed rooms (behind locked doors) to open south lobby at (19,-32) and (23,-32); patches nav graph charger waypoints to match |
| `scripts/hotel-build/patch_delivery_robot_color.py` | Sets DeliveryRobot body material to red (RGBA 0.8 0 0 1) for visibility |
| `scripts/hotel-build/patch_fleet_adapter.py` | Wraps Python callbacks in daemon threads — prevents GC and Python 3.12 / pybind11 threading crash |

---

## Known Limitation — EasyFullControl SIGSEGV

`librmf_fleet_adapter.so 2.7.2` (apt) crashes with SIGSEGV the moment
EasyFullControl tries to execute any navigation task. Root cause: pybind11
invokes a Python callback from a non-Python C++ thread without proper GIL
setup on Python 3.12.

**Workaround — `rmf_puppet_controller.py`:**

1. Monitors `/dispatch_states` for task assignments
2. Calls fleet_manager `POST /navigate` → publishes `PathRequest` to `/robot_path_requests`
3. Slotcar subscribes to `/robot_path_requests` and moves the robot

RMF task dispatch, bidding, and fleet management all work. Only the C++
execution path is bypassed. The result is identical from the user's perspective.

---

## Patrol Loop Details

The continuous patrol (`scripts/hotel_patrol_loop.py`) assigns each robot
a non-overlapping zone and alternates between two waypoints per cycle:

| Robot | Waypoint A | Waypoint B |
|-------|-----------|-----------|
| `deliveryBot_1` | (14.87, -28.77) = v5 | (13.57, -21.79) = v8 |
| `tinyBot_1` | (22.0, -26.5) | (22.0, -30.0) |
| `cleanerBotA_1` | (15.0, -30.5) | (15.0, -35.0) |
| `cleanerBotA_2` | (22.0, -33.5) | (22.0, -37.0) |

**Zones must not overlap** — robots within 1.5 m of each other trigger
collision avoidance and deadlock. The current zones were tuned against the
hotel building's wall layout.

**`cleanerBotA_2` south-only constraint**: the robot cannot navigate north
of y ≈ −31.6 from x ≈ 26 — there is a building wall at that boundary.
Its zone is therefore restricted to y < −32.

---

## Visualization Stack

```
gz sim GUI → Xorg :99 (dummy driver, Mesa llvmpipe software GL)
                ↓
           x11vnc :5900
                ↓
        websockify :6080
                ↓
        Browser ← OpenShift Route (TLS edge)
```

**Why Xorg+dummy (not Xvfb)**: Xvfb uses direct DRI rendering which bypasses
the X framebuffer; x11vnc cannot capture it. Xorg+dummy composites OpenGL
into a shared-memory framebuffer that x11vnc captures.

**Why `QT_QPA_PLATFORM=xcb`**: Qt6 probes for Wayland first; without this
flag the Gazebo GUI creates an off-screen EGL surface that never appears in VNC.

---

## RTF and Timing

| Parameter | Value |
|-----------|-------|
| Gazebo RTF | ≈ 0.5 (software rendering, no GPU) |
| Slotcar patrol speed | 0.65 m/s configured |
| Effective wall-clock speed | ≈ 0.33 m/s |
| deliveryBot corridor (17 m) | ≈ 90 s wall-clock |
| Full 4-robot patrol cycle | ≈ 3–5 minutes |

---

## Key Files

| File | Purpose |
|------|---------|
| `Containerfile.hotel` | Two-stage build: rmf_ros2 + rmf_simulation + rmf_demos |
| `entrypoints/entrypoint-hotel.sh` | Pod start: Xorg, map TF frame, puppet controller, RMF launch |
| `entrypoints/rmf_puppet_controller.py` | Monitors `/dispatch_states`, drives robots via fleet_manager HTTP |
| `scripts/hotel_patrol_loop.py` | Continuous 4-robot patrol loop (`make patrol-hotel`) |
| `scripts/hotel-build/` | Build-time patch scripts (stubs, spawns, color, callbacks) |
| `config/hotel/xorg-dummy.conf` | Xorg dummy driver config for headless GL rendering |
| `helm/multi-robot-demo/values-hotel.yaml` | Helm overrides: namespace, image, resources |
