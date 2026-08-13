# Open-RMF in Production: Multi-Robot Management and Collision Avoidance

> **Purpose:** Research document examining how Open-RMF is used in real (non-simulated) production deployments, how multi-robot collision avoidance is implemented in such systems, and the implications for our collision-avoidance demo.
>
> **Sources:** ros2multirobotbook, open-rmf.org, open-rmf GitHub, Nav2 documentation, Ekumen Labs technical blog, industry safety literature, AMCL+QR hybrid paper (Scientific Reports 2024).

---

## 1. Open-RMF in Production

### What Open-RMF Actually Is

Open-RMF is **not a navigation system**. It is an **air traffic controller for robot fleets** — a coordination middleware that sits above individual robot navigation stacks and manages which robot goes where and when.

Open-RMF **never sends velocity commands**. It sends:
- High-level route waypoints on a navigation graph (for "Full Control" fleets)
- Pause / Resume signals (for "Traffic Light" fleets)

The robot's own navigation stack (e.g., Nav2) handles all path execution and local obstacle avoidance.

### Largest Known Deployment

**Whirlpool appliance factory (Intrinsic/Google):** 200+ autonomous forklifts, 75,000+ autonomous lifts per week. Open-RMF manages traffic, collision prevention, and trajectory optimization across the entire fleet. This is the only large-scale deployment with publicly disclosed operational metrics.

### Industries and Organizations

**Confirmed deployments/partners:**

| Industry | Examples |
|---|---|
| Manufacturing | Whirlpool factory (forklifts, Intrinsic) |
| Healthcare | Hospital corridors, Singapore (GovTech, IHiS — original target use case) |
| Aviation | Airport terminals (CAAS Singapore) |
| Warehousing | Swisslog, Dematic (named community partners) |
| Commercial facilities | Shopping malls, hotels (documented trials) |

**Named technology partners:** OTTO Motors, Mobile Industrial Robots (MiR), SESTO Robotics, Formant, InOrbit, dormakaba, Ekumen Labs, Panasonic.

### What RMF Does in Production

1. **Task allocation** — Broadcasts tasks via bid auction; fleet adapters compute cost and bid; RMF selects winner and dispatches `DispatchRequest`
2. **Traffic scheduling** — Maintains facility-wide trajectory database; detects conflicts ahead of time; re-routes robots *before* conflicts occur
3. **Shared infrastructure control** — Opens doors, calls elevators, activates dispensers, manages docking stations
4. **Battery management** — Automatically injects `ChargeBattery` tasks when charge is insufficient
5. **Multi-fleet interoperability** — Coordinates robots from different vendors/fleets without requiring them to know about each other

---

## 2. Open-RMF Architecture in Real Systems

### Traffic Schedule Database

A centralized, forward-looking database storing **intended future trajectories** for all registered robots. Key properties:

- **One authoritative instance** per RMF deployment
- Contains trajectories in space-time (position + timestamp at each point)
- Continuously monitored for emerging conflicts
- Platform-agnostic (`rmf_traffic` has no ROS 2 dependency; `rmf_traffic_ros2` wraps it)

### Schedule Mirror (Distributed Read Replica)

Every `rmf_fleet_adapter` maintains a **local read-replica** of the central Traffic Schedule Database, synchronized continuously via ROS 2. This enables distributed conflict detection without querying the central node at decision time:

```
Central Traffic Schedule DB (authoritative)
        ↕ sync
Fleet Adapter 1 Mirror ←→ Fleet Adapter 2 Mirror ←→ Fleet Adapter N Mirror
        ↓                          ↓
  Robot 1 Planner            Robot 2 Planner
```

When planning a new route, the fleet adapter's planner queries its *local mirror* — not the central node — for performance.

### Two-Level Deconfliction

#### Level 1 — Prevention (before the robot moves)

The `Planner` class in each fleet adapter runs a **time-dependent A\* search** — finding paths through *space and time*, not just space. It finds trajectories that are conflict-free against all committed trajectories in the local mirror.

Conflict detection uses two parameters:
- `footprint_radius`: physical size of the vehicle
- `vicinity_radius`: required clearance zone from other robots

A **schedule conflict** = one robot's footprint is scheduled to enter another's vicinity. Prevention eliminates this before it ever reaches the central schedule.

#### Level 2 — Negotiation (when prevention fails)

Triggered when the central scheduler detects an emerging conflict (due to delays, dynamic replanning, or ETA estimation errors). The negotiation sequence:

```
Central DB detects conflict
        ↓
Conflict notification → Fleet Adapters A and B
        ↓
Each adapter launches multi-threaded Negotiate service
        ↓
Adapter A computes proposal (revised trajectory)
Adapter B computes proposal (revised trajectory)
        ↓
If adapter A cannot accept B's proposal:
  → Rejects + offers 10–200 feasible alternatives
  → Adapter B replans to accommodate one of A's alternatives
        ↓
All participants agree on a valid combination
        ↓
Third-party Judge evaluates proposal tree
→ Selects winning combination (by any configured criterion)
        ↓
Fleet adapters execute selected proposals
```

**Forfeit mechanism:** If a participant's planner finds no valid trajectory at all (high-contention scenario), it forfeits. The negotiation continues with other branches. Stationary robots create a steady-state where convergence is "practically assured."

**Emergency priority:** A high-priority robot deliberately posts a conflicting trajectory; the judge is configured to always favor it, forcing other robots to clear the path.

**Mutex Groups:** For narrow corridors where full negotiation is expensive, the nav graph assigns intersections to mutex groups — only one robot holds the lock at a time, like a simple traffic light embedded in the map.

### Task Allocation Protocol

```
Task request arrives (UI or automated system)
        ↓
RMF Dispatcher broadcasts BidNotice to all fleet adapters
        ↓
Each capable adapter runs rmf_task::agv::TaskPlanner
→ Computes cost: completion time + disruption to existing schedule
→ Returns BidProposal
        ↓
Dispatcher selects winner (fastest, lowest cost, or custom criterion)
→ Sends DispatchRequest to winning adapter
        ↓
Winning adapter assigns task to a robot via RobotCommandHandle
→ Trickle-feeds waypoints to Nav2 as robot progresses
```

---

## 3. Collision Avoidance Layers in Real Systems

Real production AMR deployments use **four distinct, independent layers** of collision avoidance. Each layer handles a different timescale and failure mode. **All four run simultaneously.**

### Layer 1 — RMF Traffic Scheduling (Prevention)

| Property | Value |
|---|---|
| What | Open-RMF Traffic Schedule + time-dependent A\* planner |
| Scope | All robots, all fleets, whole facility |
| Horizon | Minutes ahead |
| Response time | Planning before robot moves; continuous updates |
| Handles | Path conflicts before they materialize |
| Cannot handle | Dynamic obstacles not in the schedule; humans |

### Layer 2 — RMF Traffic Negotiation (Resolution)

| Property | Value |
|---|---|
| What | rmf_traffic negotiation protocol |
| Scope | Conflicting robots (any fleets) |
| Horizon | Seconds to tens of seconds ahead |
| Response time | Asynchronously triggered when conflict detected |
| Handles | Replanning around delays and unanticipated route changes |
| Cannot handle | Conflicts arising faster than negotiation round-trip |

### Layer 3 — Nav2 Onboard Stack (Local Avoidance)

| Property | Value |
|---|---|
| What | Local costmap (VoxelLayer) + controller + Collision Monitor node |
| Scope | Single robot, ~3–5 m sensor radius |
| Horizon | Immediate (100 ms–1 s) |
| Response time | 10–20 Hz controller loop; Collision Monitor independent of BT |
| Handles | Dynamic obstacles (humans, rogue objects), close-range encounters |
| Cannot handle | Objects outside sensor FoV; very fast-moving obstacles |

The **Nav2 Collision Monitor** is a safety watchdog running outside the behavior tree. It monitors configurable polygons around the robot and applies velocity limiting, slowing, or full stop independently of navigation state. This is the last software-layer defense.

**MPPI Controller** (recommended for real hardware in Nav2 Jazzy): Samples thousands of trajectories per cycle, handles acceleration constraints, delay compensation, and non-circular footprints better than DWA. Increasingly used in production for complex environments.

### Layer 4 — Hardware Safety System (Physical E-Stop)

| Property | Value |
|---|---|
| What | Safety-rated laser scanners + Safety PLC (independent of all ROS software) |
| Scope | Single robot, 0–3 m configurable zones |
| Response time | Microseconds to milliseconds (hardware OSSD signal) |
| Handles | Physical intrusion into protection zone; motor power cutoff |
| Standard | ISO 3691-4 (industrial vehicles), ANSI/RIA R15.08 |

**This layer is mandatory.** ROS software (including Nav2 and RMF) is **never** trusted as a safety-critical system. The safety PLC directly interrupts motor power via an OSSD (Output Signal Switching Device) relay, operating even if all software crashes.

**Dynamic zone switching:** As a robot accelerates, protection zones enlarge automatically; at low speed, they shrink to reduce false stops at intersections. (Example: Pilz PSENscan supports 70 configurable zone banks.)

### Interaction Between Layers

```
Scenario: Two robots approaching each other in a narrow corridor

L1 (RMF Scheduling):  Detects the path conflict during planning.
                       Holds Robot B at a waypoint while Robot A proceeds.
                       → Ideal case: collision never physically approaches.

L2 (RMF Negotiation): If L1 fails (due to delay), triggers negotiation.
                       Proposes Robot B waits 15 s for Robot A to pass.
                       → Near-miss resolved without physical close approach.

L3 (Nav2 Local):      If L1+L2 fail, Robot B's local costmap detects
                       Robot A as an obstacle and slows/stops the controller.
                       Collision Monitor triggers if Robot A enters zone.
                       → Robots stop meters apart.

L4 (Hardware):        If all software fails, safety scanner detects Robot A
                       in Robot B's protection field and cuts motor power.
                       → Hard stop, no collision.
```

---

## 4. Nav2 on Real Hardware

### What Is the Same as Simulation

- URDF/TF tree structure: `map → odom → base_link → sensor_frames`
- Costmap pipeline (global + local, same plugin system)
- AMCL and slam_toolbox work identically (consume `sensor_msgs/LaserScan`)
- Nav2 action servers, behavior trees, and plugin APIs

### Critical Differences on Real Hardware

**Odometry fusion is mandatory.** Real hardware uses `robot_localization` (EKF) to fuse wheel encoders + IMU at 50–200 Hz. Raw encoder odometry alone is insufficient for stable localization. This EKF is the backbone; localization algorithms correct its accumulated drift against a map.

```
Wheel encoders → EKF (robot_localization) → /odom
IMU           ↗                             ↓
                                     Localization algorithm
                                     (AMCL / slam_toolbox / NDT)
                                             ↓
                                       map → odom TF
```

**Physical sensors need drivers:**
- 2D LiDAR: SICK LMS/S300, Hokuyo UTM/UST, RPLidar → `sensor_msgs/LaserScan`
- 3D LiDAR: Ouster, Velodyne → `sensor_msgs/PointCloud2`
- Depth cameras: RealSense, ZED X → stereo processing required

**`use_sim_time` must be `false`** on real hardware (common sim-to-hardware port bug).

**`TwistStamped` vs `Twist`** — Nav2 Jazzy changed the default `cmd_vel` type to `TwistStamped`; hardware motor drivers must match.

**Hardware safety PLC** is required alongside Nav2. ROS is never the safety layer.

### Known Real-Hardware Nav2 Issues

| Issue | Cause | Mitigation |
|---|---|---|
| LiDAR intensity saturation | Reflective tape causes phantom walls in scan | Validate raw scan in RViz before running Nav2 |
| Wheel slip on smooth floors | Odometry divergence | Increase IMU weight in EKF |
| WiFi dead zones | State update gaps desync RMF traffic schedule | Use wired Ethernet where possible; increase tolerances |
| EKF sensor frequency mismatch | IMU at 200 Hz, encoder at 50 Hz | Use `differential: false` and tune `delay` params |

---

## 5. Localization in Production: AMCL vs. Alternatives

### Why AMCL Alone Is Insufficient in Production

AMCL is a particle filter that estimates pose against a **known, static 2D map**. It fails or degrades in:

- **Symmetric corridors** — Walls look identical at different x-positions; particles spread laterally → catastrophic divergence (our observed 1–3 m drift)
- **Dynamic environments** — Moved shelving, open/closed doors; AMCL has no concept of dynamic objects
- **Non-planar terrain** — Ramps, uneven floors (AMCL assumes flat 2D)
- **Kidnapping** — If moved without odometry, re-localization takes seconds to minutes
- **High-reflectivity surfaces** — Shiny floors cause scan noise that degrades scan-matching

### Production Localization Stack

**Universal:** EKF fusion (encoder + IMU) via `robot_localization` — runs on every production system regardless of localization algorithm choice.

| Algorithm | Use case | Advantages vs. AMCL |
|---|---|---|
| **slam_toolbox (localization mode)** | Standard indoor AMRs; Nav2 default | Lifelong map updates; better in feature-rich environments; handles gentle symmetry better |
| **NDT (Normal Distributions Transform)** | Industrial AMRs with 3D LiDAR | Robust to noise and partial occlusion; handles reflective surfaces better |
| **LIO-SAM / LOAM** | 3D environments, outdoor robots | Full 3D localization; tightly couples IMU + LiDAR |
| **AMCL + QR code hybrid** | High-precision work points | AMCL for transit, QR for millimeter correction at delivery points |
| **AMCL alone** | Simple, static, feature-rich environments | Lowest compute cost; well-understood; inadequate for symmetric corridors |

**Nav2's own recommendation (Jazzy):** slam_toolbox is now the default SLAM/localization tool, replacing the previous recommendation of AMCL for localization-only use cases. From Nav2 docs: *"slam_toolbox is the defacto standard for ROS 2 mapping and localization."*

### slam_toolbox in Localization Mode

In **localization mode** (distinguished from mapping mode), slam_toolbox:
- Loads an existing serialized map (`.posegraph` + `.data` files)
- Publishes `map → odom` TF and the `/map` topic — exactly what AMCL publishes
- Uses **scan-matching** (not particle filter) to localize against the map
- Supports **lifelong map updates** — optionally updates the map when the environment changes

Because slam_toolbox uses scan-matching rather than particle filtering, it **does not have the particle divergence problem** that causes AMCL to fail in symmetric corridors. It finds the pose that maximizes scan correlation against the saved map, which produces a unique solution even in corridors that look similar from different x-positions, provided the scans differ enough when approaching from known positions.

```
Previous attempt note: slam_toolbox was tested in this repo (branch swap-nav2-planning,
commits 74215a1, 533727c, 0240f0a). It worked with lower drift (≤0.012m vs AMCL's
0.10–0.24m) but the map frame origin did not coincide with the Gazebo world frame origin,
breaking the static costmap layer. This is fixable with a coordinate offset correction.
```

---

## 6. Implications for the Collision-Avoidance Demo

### What an Authentic RMF + Nav2 Demo Would Show

| Layer | What's shown | How |
|---|---|---|
| RMF task planning | Both robots assigned convergent patrol tasks | `dispatch_patrol` for both simultaneously |
| RMF traffic scheduling | Scheduler detects path conflict; negotiates who yields | `responsive_wait: False` to let physical approach happen; or `True` to show RMF preventing it |
| Nav2 local avoidance | Onboard costmap detects the other robot; controller slows/stops | VoxelLayer marks the other robot as obstacle; RPP `near_collision_cost` threshold |
| RMF re-dispatch | Both robots sent to swap positions after yield | New `dispatch_patrol` calls |

### The Blocking Issue: AMCL Localization Failure

The south outer corridor is symmetric — AMCL's particle filter diverges, causing 1–3 m localization errors. All AMCL-dependent navigation in the south corridor produces wrong physical positions. This is not a tuning issue; it is a fundamental limitation of particle filter localization in symmetric environments.

**Solution: slam_toolbox in localization mode.** This replaces the particle filter with scan-matching, which produces correct localization even in symmetric corridors. The previous attempt failed due to a map frame offset issue (solvable), not a fundamental incompatibility.

### Recommended Enhancement Path

1. **Implement slam_toolbox in localization mode** (replaces AMCL)
2. **Validate localization accuracy** in the inner corridors (y ≈ ±0.55) and south outer corridor
3. **Add `s_in ↔ s_out` lane** to nav_graph so RMF can route robots through the south corridor
4. **Replace P-controller Phase 1 with RMF dispatch_patrol** — let RMF plan the convergent paths
5. **Phase 2 collision avoidance via Nav2** — rely on local costmap VoxelLayer to detect the other robot; demonstrate how RPP slows near obstacles
6. **Phase 3 re-dispatch via RMF** — new patrol tasks to swap positions

---

## 7. Key Takeaways

1. **Open-RMF is a coordinator, not a controller.** It manages schedules and negotiates conflicts; robots' own nav stacks handle execution and local safety.

2. **Real systems use 4 collision avoidance layers.** Hardware E-stop is mandatory and non-optional under ISO 3691-4. RMF and Nav2 are coordination/navigation layers, not safety systems.

3. **AMCL is inadequate for symmetric corridors.** Every production system that operates in symmetric environments (warehouses, hospital corridors) uses slam_toolbox, NDT, or a hybrid approach — not raw AMCL.

4. **EKF fusion is universal.** All production AMRs run `robot_localization` EKF to fuse odometry + IMU. This is not optional.

5. **RMF negotiation operates ahead of time.** It is not a real-time collision response mechanism; it operates seconds to minutes before conflicts physically occur. Real-time close-range collision response is Nav2's job (Layer 3) and the hardware safety system (Layer 4).

6. **The largest confirmed deployment is Whirlpool/Intrinsic.** 200+ forklifts, 75,000 lifts/week. This is the only publicly disclosed metric of Open-RMF at production scale.

---

## Appendix: Key Sources

| Source | URL |
|---|---|
| RMF Core Overview | https://osrf.github.io/ros2multirobotbook/rmf-core.html |
| RMF FAQ (negotiation details) | https://osrf.github.io/ros2multirobotbook/rmf-core_faq.html |
| Mobile Robot Fleet Integration | https://osrf.github.io/ros2multirobotbook/integration_fleets.html |
| OpenRMF ReadTheDocs | https://openrmf.readthedocs.io/ |
| rmf_traffic GitHub | https://github.com/open-rmf/rmf_traffic |
| Ekumen Nav2 + Open-RMF Deep Dive | https://ekumenlabs.com/blog/posts/nav2-open-rmf-fleet-coordination/ |
| Nav2 Documentation | https://docs.nav2.org/ |
| Nav2 Concepts | https://docs.nav2.org/concepts/index.html |
| AMCL + QR Hybrid (2024 paper) | https://www.nature.com/articles/s41598-024-85067-8 |
| AMR Safety Overview | https://mobile-industrial-robots.com/blog/amr-safety |
