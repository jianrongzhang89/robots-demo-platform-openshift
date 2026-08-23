---
name: rmf-hotel-world-plan
description: Hotel demo architecture, Option A decisions, Nav2 roadmap, and debug learnings from implementation
metadata:
  type: project
---

# RMF Hotel World Demo — Implementation Plan & Debug Learnings

## Option A: Faithful Upstream Slotcar Hotel (chosen)

Single pod, single localhost DDS domain. No Zenoh, no per-robot Nav2.
Gazebo (slotcar robots + lift/door plugins), RMF building map server, door/lift
supervisors, traffic schedule, task dispatcher, and 3 full_control fleet adapters.

## Image Details

- Base: `ros:jazzy` (Ubuntu 24.04) — needed for apt rmf packages
- Source-built: `rmf_demos` jazzy branch (hotel world assets, launch files)
- apt: rmf-dev, rmf-building-sim-gz-plugins, rmf-robot-sim-gz-plugins, rmf-building-map-tools, ros-gz
- Image: `quay.io/jianrzha/ros2-rmf-hotel:latest`

## Key Fixes Applied

1. **Xvfb → Xorg+dummy**: Xvfb uses direct DRI rendering that bypasses the X
   framebuffer; Xorg+dummy composites OpenGL properly for VNC capture.
   Config: `/etc/X11/xorg-dummy.conf`

2. **QT_QPA_PLATFORM=xcb**: Qt6 on Ubuntu 24.04 tries Wayland first; force X11.

3. **GZ_SIM_RESOURCE_PATH**: Slotcar robot models (TinyRobot, CleanerBotA,
   DeliveryRobot) live in `rmf_demos_assets/models/` but hotel.world references
   them as `model://Open-RMF/TinyRobot`. Created `/opt/gz-models/Open-RMF/`
   with symlinks.

4. **Furniture stub models**: hotel.world references 27 Gazebo Fuel furniture
   models not in any apt package (CoffeeTable, StorageRack, etc.). Empty stub
   SDF models in `/opt/gz-models/` prevent ECM crash at world load.

5. **Headless gz sim**: simulation.launch.xml's `if/unless` on `<let>` is
   unreliable with gz-sim8/ros:jazzy. Hardcoded `-s` in the gz sim command was
   tried but caused other issues; ultimately re-enabled GUI (Xorg+xcb works).

6. **map TF frame**: All RMF visualization markers use `frame_id: map` but
   nothing publishes the `map` TF root. Added `static_transform_publisher`
   for `map → rmf_building` in entrypoint.

## Critical Version Incompatibility (unsolved as of 2026-08-20)

**Problem**: fleet_adapter cannot execute tasks:
- apt `ros-jazzy-rmf-fleet-adapter`: **2.7.2** (Jun 2026)
- rmf_demos 2.3.0 C++ fleet_adapter: calls 2.3.x API → "no robots" error (API changed in 2.7.2)
- rmf_demos jazzy branch C++ fleet_adapter: crashes SIGSEGV at "Beginning new task... queue: 0"

**Root cause chain**:
1. Slotcar plugin (rmf_robot_sim_gz_plugins 2.3.3) does NOT publish to
   `/robot_state` ROS2 topic (0 publishers observed)
2. Python fleet_manager subscribes to `/robot_state` → gets no data → returns
   `all_robots: []` from REST API
3. Python fleet_adapter calls `api.get_data()` → None → `update_handle` stays
   None → robots never registered with EasyFullControl API
4. C++ fleet_adapter (jazzy branch) does register robots (different internal
   path), bids correctly, but SIGSEGV at task execution start
5. Building rmf_fleet_adapter from source fails OOM at 14 GB VM (largest package)

**What works**:
- Hotel world loads in Gazebo GUI (noVNC visible) ✓
- All 3 floors visible ✓
- Fleet adapters start and bid for tasks ✓
- RMF traffic schedule, task dispatcher, lifts, doors all running ✓
- `/fleet_states` publishes robot positions (C++ fleet_adapter in -sim mode reads slotcar internally) ✓
- Tasks can be queued/dispatched ✓
- Robots are visible in Gazebo (white rectangle = deliveryBot_1, blue dot = tinyBot) ✓

**What doesn't work**:
- Robots don't actually move autonomously ✗

## Attempted Fixes

1. `rmf_demos` tagged `2.3.0` — fleet_manager doesn't communicate with 2.7.2 API
2. Apt `ros-jazzy-rmf-demos-fleet-adapter` — Python, wrong type for Gazebo sim
3. Binary swap (cp apt binary over source binary) — Python vs C++ incompatible
4. `rmf_demos` jazzy branch + `rmf_ros2` from source — OOM at rmf_fleet_adapter (>14 GB needed)

## Potential Next Fix (not yet attempted)

**fleet_states → /robot_state bridge**: The C++ fleet_adapter (2.3.0 -sim mode)
CAN read slotcar positions and publishes `/fleet_states`. A small Python bridge
node could subscribe to `/fleet_states` and republish as `/robot_state`
(rmf_fleet_msgs/msg/RobotState). The Python fleet_manager would then get data,
Python fleet_adapter (jazzy) could register robots and dispatch navigation.

**Why:** `/robot_path_requests` is published by fleet_managers (3 publishers)
but subscriber count is unknown — if slotcar subscribes, navigation commands
would work once the fleet_manager has position data.

## Nav2 Roadmap (Step 2, deferred)

Add a Nav2 pod to the same namespace with `free_fleet_adapter`. RMF infrastructure
is fleet-agnostic; no changes to building_map_server, traffic schedule, or
task dispatcher needed. See `values-hotel.yaml` for Step 2 seam comments.

## Fedora vs Ubuntu Packaging

- Fedora + `copr tavie/ros2`: Gazebo + Nav2 work. NO rmf packages.
- Ubuntu `ros:jazzy` (apt): All rmf packages available. But `rmf-demos-gz`,
  `rmf-demos-maps`, `rmf-demos` NOT bloom-released as Jazzy debs; must build
  from source.
