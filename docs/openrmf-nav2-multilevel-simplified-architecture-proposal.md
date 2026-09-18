# Simplified OpenRMF and Nav2 Multi-Level Architecture Proposal

**Date:** 2026-09-16
**Status:** Implemented baseline path; acceptance gates remain
**Scope:** One TurboBot/TurtleBot3-style robot navigating the multi-level OpenRMF hotel world using Nav2 and RMF-managed lifts, without Zenoh federation

## 1. Executive Summary

The first milestone should run Gazebo, Nav2, OpenRMF, and one robot in a single OpenShift pod, on one ROS 2 DDS domain, without Zenoh. This removes the transport, discovery, clock, TF, action, and namespace workarounds that obscured the underlying multi-level navigation problems.

The proposed system will use:

- Ubuntu 24.04
- ROS 2 Jazzy
- Gazebo Harmonic
- A pinned OpenRMF Jazzy release set
- The real upstream OpenRMF hotel world and lift plugins
- One normally scaled differential-drive robot with LiDAR
- One namespaced Nav2 stack
- A small EasyFullControl fleet adapter that calls Nav2 directly
- OpenRMF traffic schedule, task dispatcher, lift supervisor, and door supervisor

ROS 2 Lyrical is the intended future platform, but it should not be introduced while establishing the first working multi-level baseline. Jazzy remains supported until May 2029, while the required Lyrical OpenRMF binary dependency closure is not yet complete. Moving to Lyrical would also require simultaneous migration from Ubuntu 24.04 to 26.04 and Gazebo Harmonic to Jetty.

Zenoh should be added back only after repeated bidirectional lift navigation works reliably and is covered by automated acceptance tests.

## 2. Current Repository Findings

The repository contains three partially overlapping systems:

1. A working single-pod upstream hotel demo using slotcar robots, RMF lifts, and RMF doors.
2. Working single-floor Nav2 experiments with Zenoh and substantial clock, TF, localization, and transport workarounds.
3. An attempted hotel, Nav2, RMF, and Zenoh hybrid that delivered commands but did not complete autonomous multi-level execution.

The latest demonstrated hotel robot capability is manual velocity control and 50 Hz odometry, as documented in `HANDOVER.md:10-20`. Nav2, lift use, map switching, RMF integration, and Zenoh federation are listed as future work in `HANDOVER.md:201-230`.

### 2.1 Transport Complexity

The hybrid architecture splits Gazebo, Nav2, and RMF across ROS domains and OpenShift pods. Zenoh is then required to carry selected topics between them. This resulted in custom handling for:

- Simulation clock propagation and clock resets
- TF reconstruction and namespace translation
- ROS action request and response routing
- Custom String command and result topics
- Command route lifetime and keepalive behavior
- QoS mismatches
- Cancellation and stale goal handling

The custom `rmf_navigate_cmd` relay was introduced because ROS action responses did not work reliably through the selected Zenoh topology. See `docs/rmf-nav2-zenoh-multi-level-implementation.md:78-105`.

The current adapter publishes a command without assigning the resulting goal to its execution handle at `patches/nav2_robot_adapter.py:1235-1263`. Completion processing requires that missing goal identifier at `patches/nav2_robot_adapter.py:1092-1102`. Consequently, command delivery does not imply RMF command completion.

### 2.2 Multi-Level Gaps Independent of Zenoh

Removing Zenoh will not by itself solve the following issues:

- Correct per-floor Nav2 occupancy maps
- RMF-to-Nav2 coordinate calibration
- Nav2 map switching and AMCL reseeding
- Lift cabin entry and containment
- Physical transport of the robot by the Gazebo lift
- Correct use of EasyFullControl command identities
- Navigation success, cancellation, and failure reporting

The hand-authored 2.5D hotel world is not a functional lift simulation. It arranges three floor regions side by side and represents lifts using visual markers only. See `worlds/hotel_multilevel_2d.sdf:1-11` and `worlds/hotel_multilevel_2d.sdf:169-238`.

The associated graph has an empty `lifts` map and hand-authored cross-level lanes. See `helm/multi-robot-demo/files/hotel_nav_graph_multilevel_2d.yaml:10-12` and `helm/multi-robot-demo/files/hotel_nav_graph_multilevel_2d.yaml:127-135`. This does not match how the Jazzy RMF graph parser derives lift events from generated lift properties and aligned lift cabin waypoints.

### 2.3 Build and Simulation Risks

The current hotel image installs OpenRMF binary packages while also building mutable Jazzy branch heads of `rmf_ros2`, `rmf_simulation`, and `rmf_demos`. See `Containerfile.hotel:29-78`. This creates reproducibility and potential ABI compatibility risks.

The current robot is enlarged to approximately three times normal size at `Containerfile.hotel-nav2-v3:98-123`. That size is inconsistent with existing Nav2 footprint assumptions and increases the risk that the robot does not fit or remain contained inside the hotel lift.

## 3. Proposed Architecture

```text
OpenShift pod: hotel-nav2-rmf
ROS_DOMAIN_ID: one non-default value
RMW: CycloneDDS with one shared configuration

+---------------------------------------------------------------+
| Gazebo Harmonic                                               |
| - Generated upstream hotel world                              |
| - One TurboBot/TurtleBot3-style differential-drive robot      |
| - RMF lift and door simulation plugins                        |
+-------------------------------+-------------------------------+
                                |
                         ros_gz_bridge
                                |
                cmd_vel, odom, scan, TF, clock
                                |
+-------------------------------v-------------------------------+
| Nav2 namespace: /robot_1                                      |
| - map_server                                                  |
| - AMCL                                                        |
| - planner, controller, behavior and BT navigator              |
| - lifecycle managers                                          |
+-------------------------------+-------------------------------+
                                |
             NavigateToPose, LoadMap, initial pose, state
                                |
+-------------------------------v-------------------------------+
| EasyFullControl fleet adapter                                 |
| - Direct local Nav2 backend                                   |
| - Robot state and execution identity reporting                |
| - Map switching and destination-floor localization            |
+-------------------------------+-------------------------------+
                                |
+-------------------------------v-------------------------------+
| OpenRMF core                                                  |
| - Traffic schedule                                            |
| - Task dispatcher                                             |
| - Lift supervisor                                             |
| - Door supervisor                                             |
| - Optional building map server and visualization              |
+---------------------------------------------------------------+
```

Multiple containers may be used inside the pod, but they must share the same pod network namespace, DDS configuration, ROS domain, and simulation clock. DDS should be explicitly configured rather than relying on default interface selection.

## 4. Component Responsibilities

### 4.1 OpenRMF

OpenRMF is responsible for:

- Task bidding, allocation, and dispatch
- Planning over the generated RMF navigation graph
- Traffic schedule and itinerary management
- Segmenting plans into robot movement and infrastructure events
- Lift session acquisition, movement requests, and release
- Door requests when selected lanes cross managed doors
- Deciding when the robot may enter or exit a lift

EasyFullControl internally performs the RMF side of lift event sequencing. The robot backend must not duplicate that state machine.

### 4.2 Fleet Adapter

The fleet adapter is responsible for:

- Translating each RMF destination into a Nav2 goal
- Reporting the robot's current RMF level, pose, battery, and health
- Passing the active `execution.identifier()` with state updates
- Replacing or cancelling active Nav2 goals
- Rejecting results from stale or superseded goals
- Calling `execution.finished()` only for the matching successful command
- Implementing the destination-level localization callback
- Reporting navigation and localization failures without falsely completing commands

A small C++ EasyFullControl adapter is recommended. It avoids the patched Free Fleet transport layer and reduces dependence on Python binding and installation-path details.

### 4.3 Nav2

Nav2 is responsible for:

- Localization on the currently active floor
- Planning and controlling planar motion
- Obstacle avoidance and recovery
- Producing velocity commands
- Reporting navigation success, cancellation, or failure

Nav2 does not plan cross-floor routes or control lift sessions. It receives a sequence of same-floor destinations from EasyFullControl.

### 4.4 Gazebo

Gazebo is responsible for:

- Robot and building physics
- LiDAR, odometry, and simulation clock
- Applying Nav2 velocity commands
- Door and lift cabin motion
- Publishing lift states
- Physically transporting a robot that is correctly contained in the lift

The RMF Gazebo lift plugin does not rigidly attach arbitrary models to the cabin. An early acceptance test must prove that the selected robot model is recognized as a payload and follows cabin elevation while fully stopped inside the cabin.

## 5. World, Graph, and Map Strategy

### 5.1 Single Source of Truth

Maintain a pinned derivative of the upstream hotel `hotel.building.yaml` as the source of truth.

The derivative should:

- Remove all upstream slotcar robot spawn annotations
- Remove or avoid launching the upstream fleet adapters
- Add the single Nav2 robot at a valid charger or parking waypoint
- Add or select a fleet-specific `graph_idx`
- Preserve the real hotel levels, lift definitions, doors, and floor elevations
- Define lanes that the normally scaled robot can physically traverse

Generate the Gazebo world and RMF navigation graph together using the pinned Traffic Editor and building map tools. Do not manually add a `lift_lanes` extension.

### 5.2 Nav2 Maps

Create one occupancy map for each floor:

- `hotel_L1.yaml`
- `hotel_L2.yaml`
- `hotel_L3.yaml`

Maps may initially be produced through an offline SLAM survey or a deterministic map-generation process, but the resulting artifacts must be versioned and immutable at runtime.

For every floor, validate at least three non-collinear survey points between:

- Gazebo world coordinates
- RMF canonical graph coordinates
- Nav2 map coordinates

Prefer identity transforms by generating maps in the same metric coordinate convention as RMF. Otherwise, configure and test one RMF-to-robot coordinate transform per level.

### 5.3 Frames and Namespaces

Recommended semantic levels and TF frames:

```text
RMF level names: L1, L2, L3
TF chain:        map -> odom -> base_footprint -> base_link -> base_scan
```

RMF level names are not TF frame names. Nav2 should reuse one active `map` frame while the occupancy map changes between levels.

Recommended ROS interfaces:

```text
/robot_1/navigate_to_pose
/robot_1/map_server/load_map
/robot_1/initialpose
/robot_1/map
/robot_1/scan
/robot_1/odom
/robot_1/cmd_vel
/robot_1/tf
/robot_1/tf_static
```

Exactly one node must own each TF edge. The duplicate identity `odom -> base_footprint` publisher from the current hybrid deployment must not be retained.

## 6. Fleet Adapter Contract

### 6.1 Navigation

For every EasyFullControl navigation request, the adapter should:

1. Increment an execution generation or assign a unique command ID.
2. Cancel and await termination of any superseded Nav2 goal.
3. Send a local `nav2_msgs/action/NavigateToPose` goal.
4. Continuously report robot state with the matching RMF activity identifier.
5. Require the Nav2 action to return `SUCCEEDED`.
6. Verify a fresh final pose, acceptable yaw error, and stopped velocity.
7. Use a tighter cabin-center and footprint-containment check when `destination.inside_lift()` is set.
8. Call `execution.finished()` only when all checks pass for the current generation.

An aborted goal, missing TF, or timeout must create an RMF issue and trigger interruption or replanning. It must not be converted to success.

### 6.2 Stop and Cancellation

The stop callback should:

1. Match the requested RMF activity identifier against the active command.
2. Request cancellation of the corresponding Nav2 action goal.
3. Wait for cancellation acceptance and a terminal result.
4. Confirm zero commanded and measured velocity.
5. Prevent a late result from completing a replacement command.

### 6.3 Destination-Level Localization

When RMF invokes the localization callback after lift travel, the adapter should:

1. Cancel and terminate any active navigation goal.
2. Confirm the robot is stationary.
3. Call `/robot_1/map_server/load_map` for the destination floor.
4. Confirm a successful response and observe the newly published map.
5. Configure AMCL to accept subsequent maps, including `first_map_only: false` where applicable.
6. Publish `/robot_1/initialpose` in the configured global frame.
7. Clear global and local costmaps.
8. Wait for a fresh post-request scan-driven localization update.
9. Validate a fresh `map -> odom -> base_footprint` transform.
10. Validate pose and covariance against configured thresholds.
11. Atomically update the adapter's reported RMF level.
12. Call localization `execution.finished()`.

Use a bounded adapter-owned timeout. On failure, keep navigation inhibited and decommission or interrupt the robot for explicit recovery. Do not rely on RMF's longer internal timeout to provide safe failure behavior.

## 7. Lift Execution Sequence

The expected runtime sequence is:

1. RMF plans from the source-level waypoint to a destination on another level.
2. EasyFullControl issues same-floor Nav2 destinations up to the lift waiting point.
3. EasyFullControl internally begins a lift session and publishes an adapter lift request.
4. The lift supervisor arbitrates the session and requests the Gazebo lift.
5. RMF waits for the correct lift name, source floor, open door, and matching session ID.
6. EasyFullControl issues the lift cabin destination to Nav2.
7. The adapter verifies that the robot succeeded, stopped, and is fully inside the cabin.
8. RMF requests the destination floor while no Nav2 motion goal is active.
9. Gazebo closes the door, moves the cabin and payload, and opens at the destination.
10. RMF invokes the EasyFullControl destination-level localization callback.
11. The adapter loads the destination map, reseeds AMCL, and validates localization.
12. EasyFullControl issues the lift exit destination to Nav2.
13. RMF ends the lift session after the robot exits.

## 8. Minimum Runtime Components

Required:

- Gazebo hotel simulation
- RMF Gazebo lift plugin
- `ros_gz_bridge` for clock and robot interfaces
- Nav2 map server, AMCL, planner, controller, behavior server, BT navigator, and lifecycle managers
- Robot state publisher
- One odometry TF authority
- EasyFullControl fleet adapter
- RMF traffic schedule
- RMF task dispatcher
- RMF lift supervisor
- RMF door supervisor when selected lanes cross managed doors

Optional for the first milestone:

- Building map server
- RViz and RMF visualization
- rmf-web API server and dashboard
- Charging and battery-drain accounting
- Reservation and mutex supervisors not required by the selected graph

## 9. Delivery Plan and Acceptance Gates

### Phase 0: Reproducible Baseline

- Pin the Ubuntu/ROS base image digest.
- Pin the OpenRMF Jazzy release snapshot.
- Use binary RMF core packages rather than overlaying mutable core branches.
- Pin the required `rmf_demos` hotel source to an immutable Jazzy commit or tag.
- Generate the world and graph from one pinned building source.
- Confirm that no upstream slotcar robots or fleet adapters start.

Acceptance:

- The image rebuilds reproducibly.
- The graph parser recognizes every hotel lift and door used by the selected fleet graph.
- Lift cabin waypoints across floors are aligned within RMF's tolerance.

### Phase 1: Simulation and Robot I/O

- Restore the robot to normal physical scale.
- Validate `cmd_vel`, odometry, LiDAR, clock, and TF.
- Validate one TF authority per edge.
- Manually command unloaded lift movement.
- Place the stopped robot in the cabin and validate loaded lift movement.

Acceptance:

- The robot remains physically stable.
- The robot model elevation follows the cabin through repeated movements.
- The robot remains within the cabin bounds.

### Phase 2: Per-Floor Nav2

- Validate lifecycle-driven startup without fixed sleeps.
- Test each occupancy map independently.
- Run repeated goals and cancellation on L1, L2, and L3.

Acceptance:

- Nav2 remains active.
- Every selected RMF lane is physically navigable.
- Final pose and covariance meet configured tolerances.

### Phase 3: Same-Floor RMF and Nav2

- Register one robot with EasyFullControl.
- Dispatch same-floor patrol tasks.
- Validate direct Nav2 actions, state updates, completion, cancellation, and replanning.

Acceptance:

- RMF task completion corresponds to a matching Nav2 success and verified final pose.
- Stale action results cannot complete a replacement command.

### Phase 4: Map Switching

- Exercise L1-to-L2, L2-to-L1, L2-to-L3, and L3-to-L2 localization callbacks while the robot is stationary.
- Inject map load, missing scan, and localization timeout failures.

Acceptance:

- No old-floor obstacle data remains after switching.
- Navigation remains inhibited until fresh localization succeeds.
- Failures leave the robot stopped and visibly faulted in RMF.

### Phase 5: Lift Traversal

- Execute one L1-to-L2 task through one lift.
- Add the reverse direction.
- Add L2-to-L3 and reverse.
- Test cancellation and failures during approach, cabin entry, travel, localization, and exit.

Acceptance:

- The robot never enters before the correct floor, open door, and session ID are observed.
- The robot remains stopped during vertical travel.
- The destination map is localized before lift exit.
- Every completed traversal releases its lift session.

### Phase 6: Reliability

- Run at least 20 bidirectional multi-level patrol cycles.
- Restart the adapter and Nav2 between test runs.
- Inject unavailable lift, stale TF, Nav2 abort, map load failure, and localization failure.

Acceptance:

- No lifecycle drop, TF age error, leaked lift session, false completion, or increasing pose drift occurs.

## 10. Components to Reuse, Remove, and Defer

### Reuse

- Upstream hotel building and simulation assets
- RMF lift and door plugins and supervisors
- Working robot DiffDrive topic and plugin-path lessons
- Pre-spawned robot approach if dynamic spawning remains unreliable
- Nav2 lifecycle readiness and localization diagnostics
- OpenRMF EasyFullControl API

### Remove from the New Runtime

- Zenoh router
- All `zenoh-bridge-ros2dds` sidecars
- ROS domain split between RMF and Nav2
- Free Fleet runtime and patched adapter
- Custom `rmf_navigate_cmd` and result relay
- Clock relays and TF namespace relays
- Command keepalive workarounds
- Puppet controllers
- Duplicate TF publishers
- Hand-authored 2.5D hotel world and graph
- Upstream slotcar robots and fleet adapters
- Three-times robot scaling

The existing files may remain temporarily as historical references, but they should not be part of the new launch or deployment path.

### Defer

- Multiple robots and traffic negotiation demonstrations
- Cross-pod deployment
- Zenoh federation
- rmf-web and external OpenShift routes
- Battery drain and automatic charging
- Production monitoring and scaling

## 11. Future Zenoh Federation Seam

Define a transport-neutral robot backend now:

```text
navigate(command_id, map, pose, speed_limit)
cancel(command_id)
localize(command_id, map, pose)
state(map, pose, battery, active_command, health)
```

The first backend uses local ROS 2 actions, services, and subscriptions. A future backend may implement the same contract over Zenoh without modifying the RMF graph, lift behavior, EasyFullControl sequencing, or acceptance criteria.

When Zenoh returns:

- Keep RMF core and lift supervision central.
- Run a small robot-side agent next to Nav2.
- Exchange application-level commands, results, localization requests, and compact robot state.
- Do not transparently bridge all Nav2 action internals.
- Do not federate high-rate TF or sensor streams unless a measured requirement justifies it.
- Preserve command IDs, cancellation acknowledgements, generation checks, and explicit timeouts.

## 12. ROS 2 Distribution Decision

### Immediate Decision

Use ROS 2 Jazzy for the first working architecture.

Reasons:

- Jazzy is an LTS release supported until May 2029.
- OpenRMF currently documents support for Humble, Jazzy, Kilted, and Rolling, but not Lyrical.
- Jazzy has the required public RMF, Nav2, ros_gz, and Gazebo Harmonic dependency baseline.
- The current repository and working hotel simulation are already based on Ubuntu 24.04 and Gazebo Harmonic.
- The purpose of this milestone is to remove variables, not combine an architecture correction with an operating system and simulator migration.

### Lyrical Migration Policy

ROS 2 Lyrical is an LTS release supported until May 2031 and is the intended long-term successor. Its default platform is Ubuntu 26.04 with Gazebo Jetty.

Start a separate Lyrical migration only after these conditions are met:

- The Jazzy multi-level acceptance suite passes reliably.
- Required OpenRMF fleet adapter, task, simulation, and demo packages are available from the public Lyrical binary repository.
- Nav2 and `nav2_bringup` Lyrical metapackages are publicly available and synchronized.
- A pinned Resolute/Jetty image builds without mixing incompatible binary and source overlays.
- The migration branch passes the same maps, lift, localization, cancellation, and endurance tests.

Reassess Lyrical readiness periodically and plan migration before 2028, leaving at least one year before Jazzy reaches end of support.

## 13. Risks and Mitigations

| Risk | Mitigation |
|---|---|
| Robot is not transported by the Gazebo lift | Test payload recognition and model Z tracking before Nav2 or RMF lift work |
| Robot does not fit in the lift | Restore normal scale and validate footprint and cabin-center tolerances |
| RMF graph and Nav2 map are misaligned | Generate from one source and validate surveyed points on every floor |
| Localization succeeds on stale data | Require post-request map, scan, AMCL pose, TF, and covariance updates |
| Old action completes a new RMF command | Use command generations and match both Nav2 goal and RMF activity identifiers |
| Mixed RMF packages cause crashes | Use a coherent pinned release set and avoid mutable source overlays |
| Upstream hotel launch starts other fleets | Use a custom launch and remove spawn metadata from the derived building source |
| One pod still exposes DDS unexpectedly | Use one explicit RMW, domain, and CycloneDDS network configuration in every container |
| Nav2 deviates too far from RMF lanes | Refine graph coverage, maps, keepouts, and lift approach constraints |

## 14. Assumptions

- "TurboBot" refers to the current `robot_1` TurtleBot3-style differential-drive simulation robot. The final model name should be confirmed before implementation.
- The first milestone uses one robot and one fleet.
- The hotel simulation remains the authoritative multi-level physical environment.
- Physical lift behavior, rather than teleportation or a side-by-side 2.5D representation, is required.
- The initial deployment is allowed to keep all ROS processes within one OpenShift pod.

## 15. References

- [OpenRMF mobile robot fleet integration](https://osrf.github.io/ros2multirobotbook/integration_fleets.html)
- [OpenRMF EasyFullControl Jazzy API](https://github.com/open-rmf/rmf_ros2/blob/jazzy/rmf_fleet_adapter/include/rmf_fleet_adapter/agv/EasyFullControl.hpp)
- [OpenRMF Jazzy graph parser](https://github.com/open-rmf/rmf_ros2/blob/jazzy/rmf_fleet_adapter/src/rmf_fleet_adapter/agv/parse_graph.cpp)
- [OpenRMF lift request implementation](https://github.com/open-rmf/rmf_ros2/blob/jazzy/rmf_fleet_adapter/src/rmf_fleet_adapter/phases/RequestLift.cpp)
- [OpenRMF hotel building source](https://github.com/open-rmf/rmf_demos/blob/main/rmf_demos_maps/maps/hotel/hotel.building.yaml)
- [OpenRMF supported ROS distributions](https://github.com/open-rmf/rmf)
- [OpenRMF Jazzy release manifest](https://raw.githubusercontent.com/open-rmf/rmf/jazzy-release/rmf.repos)
- [Nav2 LoadMap service](https://github.com/ros-navigation/navigation2/blob/jazzy/nav2_msgs/srv/LoadMap.srv)
- [Free Fleet architecture and limitations](https://github.com/open-rmf/free_fleet)
- [ROS and Gazebo compatibility matrix](https://gazebosim.org/docs/latest/ros_installation/)
- [ROS 2 Lyrical package metadata](https://github.com/ros/rosdistro/blob/master/lyrical/distribution.yaml)

## 16. Repository Implementation

The first implementation is isolated behind the `hotelNav2Rmf` Helm profile so
the historical Zenoh deployment remains available for comparison:

- `Containerfile.hotel-nav2-rmf` builds the pinned Jazzy/RMF/Nav2 image and
  prepares a derivative of the upstream hotel assets.
- `entrypoints/entrypoint-hotel-nav2-rmf.sh` starts Gazebo, the local bridge,
  Nav2, RMF supervisors, dispatcher, and the local fleet adapter in one
  container and one DDS domain.
- `scripts/local_nav2_fleet_adapter.py` implements the direct local
  EasyFullControl backend, command generations, cancellation, final-pose
  validation, and `LoadMap` localization callbacks.
- `helm/multi-robot-demo/values-hotel-nav2-rmf.yaml` and the corresponding
  Deployment render one pod with no Zenoh resources.

Deploy with `make build-push-hotel-nav2-rmf` followed by
`make deploy-hotel-nav2-rmf`. The image build and runtime acceptance gates in
this proposal are intentionally still required before enabling the profile as
the default deployment.
