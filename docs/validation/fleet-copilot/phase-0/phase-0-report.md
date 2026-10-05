# Fleet Copilot Phase 0 Evidence

- **Date:** October 5, 2026
- **Cluster:** OpenShift project `ros2-rmf-hotel`
- **Repository commit at start:** `54b28eec27e69e1a32fd7d9c80438db41bf4f47f`
- **Baseline command:** `lobby L3_middle_hallway lobby`, one patrol round
- **G0 result:** **Not accepted**
- **Reason:** The physical route succeeded in two runs, but RMF did not publish a terminal `completed` task status; the third run stopped after RMF published the first navigation command and produced no Nav2 relay result.

## 1. Environment Check

The cluster was reachable with:

```text
oc whoami: system:serviceaccount:default:jianrong
oc project: ros2-rmf-hotel
```

At the final observation, all four primary workloads were running:

| Workload | Pod | Ready |
|---|---|---:|
| `hotel-sim` | `hotel-sim-7d4bf86744-j7zw6` | 4/4 |
| `robot-nav-robot-1` | `robot-nav-robot-1-565c447864-nmm9n` | 9/9 |
| `rmf-core` | `rmf-core-fd66f6fc4-xpm7l` | 4/4 |
| `zenoh-router` | `zenoh-router-7fb94d6964-fmfdk` | 1/1 |

The deployment inventory captured before the first reset is in [deployments-before.txt](deployments-before.txt), [pods-before.txt](pods-before.txt), and [resources-before.txt](resources-before.txt). Deployment manifests are retained in [rmf-core-deployment.yaml](rmf-core-deployment.yaml), [hotel-sim-deployment.yaml](hotel-sim-deployment.yaml), [robot-nav-deployment.yaml](robot-nav-deployment.yaml), and [zenoh-deployment.yaml](zenoh-deployment.yaml).

## 2. Deployed Image Inventory

The final run used these image references:

| Workload | Image reference |
|---|---|
| Hotel simulation | `quay.io/jianrzha/ros2-rmf-hotel-sim:latest` |
| Nav2 | `quay.io/jianrzha/ros2-rmf-nav2:latest` |
| RMF core | `image-registry.openshift-image-registry.svc:5000/ros2-rmf-hotel/rmf-image:latest` |
| Zenoh router | `eclipse/zenoh:1.5.0` |
| Zenoh bridges | `docker.io/eclipse/zenoh-bridge-ros2dds@sha256:38f162ae5236412f4f02e77927e22585356f7e706db39ec1c6194b9bd0d05b18` |

Observed image IDs included:

- RMF image: `sha256:8c5a3247e494de0b89ac5c8a9cfaae7813511f3e326da951abf32444a5a8ea07`
- Nav2 image: `sha256:4299e1d4262482807bc95b7a0280859769151b61d401d4c5ad9af21d3491917e`
- Hotel image: `sha256:5bc870c989a3e0d390051424a7ef3dbb733e0ac1a7fcb5b39e7eeb2aa3d1d4c3`
- Zenoh router: `sha256:137310456cc7a75d955063513207c737f25071fbb74fd7641835c50ab8e3369f`

These are deployment references, not an immutable release policy. Phase 0 confirms that future evidence must record pod image IDs rather than only mutable tags.

## 3. Asset Inventory

The canonical assets mounted into `rmf-core` were hashed as follows:

| Asset | SHA-256 |
|---|---|
| `/canonical-rmf/nav_graph.yaml` | `5b4b20d29d3c21727f041022fbd976f6b9b0e9f3fc5b3577776552aaf1efbaf0` |
| `/canonical-rmf/fleet_config.yaml` | `570dfb1e0b70ebbb7d90c074529392ac81e819193dc83a6f9300ead97c294d8e` |
| `/canonical-rmf/hotel.building.yaml` | `da26a4a20ab842c822d27cbb9d8030816b4625d4c39cef2fcda10a1ef51360e5` |

The mounted map directory contained `hotel_L1.yaml`, `hotel_L2.yaml`, and `hotel_L3.yaml`. The building-map server logged missing PNG files for `hotel_L1.png`, `hotel_L2.png`, and `hotel_L3.png`; this did not prevent the navigation route but means the building-map visual/GeoJSON path is not fully healthy.

## 4. Transport, Clock, and State Findings

The final `rmf-core` ROS domain exposed:

- `/task_api_requests` and `/task_api_responses`
- `/dispatch_states`, `/task_summaries`, and `/fleet_states`
- `/robot_1/rmf_navigate_cmd`, `/robot_1/rmf_navigate_result`, `/robot_1/amcl_pose`, `/robot_1/odom`, and namespaced TF topics
- `/lift_requests`, `/lift_states`, `/door_requests`, and `/door_states`
- `/clock`, `/rmf_task/dispatch_request`, and `/rmf_task/dispatch_ack`

The existing startup sequence successfully established:

- Zenoh clock relay into `clock_relay/clock_bridge`.
- Domain-55 ROS `/clock` publication.
- RMF dispatcher startup.
- RMF Web API on `localhost:8000`.
- Free Fleet connection to `ws://localhost:8000/_internal`.
- Fleet registration for `hotel_nav2/robot_1`.

The RMF API server logged three missing building-map PNGs and the known incompatible `fire_alarm_trigger` QoS warning. The bridge also logged a late response for an already-removed RMF Web request ID; this is consistent with the documented pub/sub pseudo-service behavior and reinforces the need for durable request correlation in the copilot bridge.

## 5. Baseline Runs

### Run 0: pre-fix diagnostic attempt

This attempt is not one of the three G0 runs. It established that the original deployed profile seeded AMCL at `(0,0)` while the first RMF goal was `(19.44,-31.01)`. Nav2 repeatedly reported `Failed to make progress`; RMF remained in phase 1 `underway`.

The experiment initially changed the relay offset, but a subsequent run showed that the relay offset was not the correct fix: it produced an out-of-bounds local goal `(4.04,0.58)` while Nav2's planner pose was world-frame. That experiment was reverted.

### Run 1: route completed, terminal task state missing

- Reset: successful; RMF registered `robot_1`.
- Submission: `success=true`, `patrol.dispatch-0`, initial `status=queued`.
- Allocation: awarded to `hotel_nav2`, expected robot `robot_1`.
- Execution: all three phases completed; Lift2 transition and final lobby navigation succeeded.
- Final API projection after waiting: `status=standby`, `completed=[1,2,3]`, `pending=[]`, `active=3`.
- Result: **physical route pass; terminal RMF state not proven**.

### Run 2: route completed, terminal task state missing

- Reset: successful; RMF registered `robot_1`.
- Submission: `success=true`, `patrol.dispatch-0`, initial `status=queued`.
- Execution: route and lift sequence reproduced successfully.
- Final API projection: `status=standby`, `completed=[1,2,3]`, `pending=[]`, `active=3`.
- Result: **physical route pass; terminal RMF state not proven**.

### Run 3: first navigation result missing

- Reset: successful; RMF registered `robot_1`.
- Submission: `success=true`, `patrol.dispatch-0`, initial `status=queued`.
- Allocation: awarded to `hotel_nav2`, expected robot `robot_1`.
- RMF log: published the first goal command for lobby.
- After approximately six minutes: `status=underway`, `active=1`, `completed=[]`, `pending=[2,3]`.
- Nav2 relay log: no corresponding navigation command/result records in the inspected window.
- Result: **baseline failure; command/result transport or startup race remains unresolved**.

## 6. Configuration Change Made During Phase 0

The deployed chart initially set the main federated Nav2 container's `INITIAL_X/Y` from `nav2.mapOffsetX/Y`, which were both `0.0`. The hotel entrypoint uses those variables to seed AMCL. The phase-0 correction changes only the main container to use the robot's declared `initialPose.xPos/yPos`; the relay retains `MAP_OFFSET_X/Y=0.0`.

```diff
- value: {{ $.Values.nav2.mapOffsetX | default .initialPose.xPos | quote }}
+ value: {{ .initialPose.xPos | quote }}
- value: {{ $.Values.nav2.mapOffsetY | default .initialPose.yPos | quote }}
+ value: {{ .initialPose.yPos | quote }}
```

After this correction, AMCL published approximately `(15.41,-31.60)`, matching the hotel spawn, and Runs 1 and 2 completed the route. The change is in [deployment-nav2.yaml](../../../../helm/multi-robot-demo/templates/deployment-nav2.yaml).

## 7. G0 Decision and Blockers

**G0 is not accepted.** The following must be resolved before Phase 1:

1. Define and verify the RMF terminal-state path. A route with all phases completed is not sufficient if the application cannot distinguish `completed` from `standby` through a reliable, correlated terminal update.
2. Reproduce and fix Run 3's missing Nav2 relay command/result path after an independent reset. Inspect Zenoh route discovery timing, relay readiness, RMF command publication, and `rmf_navigate_result` receipt.
3. Add the missing building-map PNG assets or explicitly disable/document the building-map visual path for this profile.
4. Capture the exact deployed source/image build revisions in the release manifest; current deployments use mutable `latest` tags even though pod digests were recorded.

The phase-0 implementation should continue as a baseline stabilization work item, not advance to the language-model work. The next acceptance attempt should require three resets with three physical route passes, three correlated terminal task states, and no missing command/result path.

## 8. Proposed Next Checks

- Add a startup/readiness check that waits for the Nav2 relay subscriber, action server, and Zenoh command/result routes before RMF registration is considered ready.
- Capture `/robot_1/rmf_navigate_cmd` and `/robot_1/rmf_navigate_result` with timestamps during the first 30 seconds after dispatch.
- Compare the RMF adapter's first command timestamp with the relay's ROS subscription discovery timestamp.
- Inspect the detailed task WebSocket updates and RMF Web API projection at the point all phases become complete.
- Do not introduce a copilot bridge or model endpoint until these baseline conditions pass.
