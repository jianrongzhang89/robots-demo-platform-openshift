# Multi-Robot ROS2 on OpenShift: Research Report & Deployment Proposal

> **Research methodology:** 103 agents · 21 sources fetched · 84 claims extracted · 25 adversarially verified (16 confirmed, 9 killed)
>
> **Reference implementation:** [lokeshrangineni/ros2-openshift-demo — distributed-zenoh](https://github.com/lokeshrangineni/ros2-openshift-demo/tree/main/examples/distributed-zenoh)

---

## Table of Contents

1. [Building Block 1: Namespacing](#building-block-1-namespacing)
2. [Building Block 2: Centralized vs. Distributed Bringup](#building-block-2-centralized-vs-distributed-bringup)
3. [Building Block 3: Application Launchers with Gazebo](#building-block-3-application-launchers-with-gazebo)
4. [Zenoh Bridge Architecture for OpenShift](#part-2-zenoh-bridge-architecture-for-openshift)
5. [OpenShift Deployment Proposal](#part-3-openshift-deployment-proposal)
6. [Mapping to distributed-zenoh Pattern](#mapping-to-lokeshrangineiros2-openshift-demo-distributed-zenoh-pattern)
7. [Caveats & Open Questions](#caveats--open-questions)
8. [Sources](#sources)

---

## Part 1: ROBOTIS Multi-Robot Architecture — Three Core Building Blocks

### Building Block 1: Namespacing

**Mechanism: `PushRosNamespace` at launch time, not `tf_prefix`**

ROBOTIS TurtleBot3's official hardware bringup (`turtlebot3_bringup/launch/robot.launch.py`, `ros2` branch) declares a `namespace` launch argument and applies `PushRosNamespace(namespace)`, which prefixes all downstream nodes, topics, and services under that path:

```bash
ros2 launch turtlebot3_bringup robot.launch.py namespace:=TB3_1
# produces: /TB3_1/cmd_vel, /TB3_1/odom, /TB3_1/scan, ...
```

**Critical TF caveat (verified, 2-1 vote):** `tf2::TransformListener` hardcodes subscriptions to the absolute paths `/tf` and `/tf_static` regardless of node namespace (confirmed via `geometry2` PR #390, Issue #433). The ROBOTIS eManual explicitly notes: *"Namespace is not necessary for /tf and /tf_static... instead, frame_ids in /tf & /tf_static must be unique."* The Nav2 workaround is to add remapping arguments:

```python
# In the robot_state_publisher or Nav2 nodes:
remappings=[('/tf', 'tf'), ('/tf_static', 'tf_static')]
```

This yields per-robot TF topics `/tb1/tf`, `/tb2/tf` (confirmed via Nav2 issue #5449). `tf_prefix` is deprecated — do not use it.

**Community pattern (arshadlab/tb3_multi_robot, verified 3-0):** Externalise robot definitions to a `robots.yaml` ConfigMap:

```yaml
# config/robots.yaml
- name: tb1
  x_pose: 0.0
  y_pose: 0.0
  z_pose: 0.01
  enabled: true
- name: tb2
  x_pose: 2.0
  y_pose: 0.0
  z_pose: 0.01
  enabled: true
```

The `name` field becomes the ROS2 namespace directly.

---

### Building Block 2: Centralized vs. Distributed Bringup

Nav2 ships **two launch files with opposite scalability profiles** (both verified 3-0):

| Launch File | Pattern | Scalability |
|---|---|---|
| `cloned_multi_tb3_simulation_launch.py` | `robots` arg as semicolon-separated YAML dicts; `ForEach` loop | N robots, no script edits |
| `unique_multi_tb3_simulation_launch.py` | Static Python `list[RobotConfig]` for exactly 2 robots | Requires script edits to scale |

The cloned launch format (the recommended foundation for OpenShift):

```bash
ros2 launch nav2_bringup cloned_multi_tb3_simulation_launch.py \
  robots:="{name: tb1, pose: {x: 0.0, y: 0.0, z: 0.0, roll: 0.0, pitch: 0.0, yaw: 0.0}};{name: tb2, pose: {x: 2.0, y: 0.0, z: 0.0, roll: 0.0, pitch: 0.0, yaw: 0.0}}"
```

**Two-launch-file separation pattern (verified 3-0):** Community best practice separates:

1. `tb3_world.launch.py` — Gazebo world + model spawning (runs once, shared)
2. `tb3_nav2.launch.py` — Per-robot Nav2 stack; reads `robots.yaml`, calls `nav2_bringup/bringup_launch.py` once per enabled robot under its namespace

**ROBOTIS `multi_robot.launch.py` important correction (3-0 refuted):** The official ROBOTIS file in `turtlebot3_simulations` (Humble branch only — absent from `main` and `jazzy`) uses **hardcoded Python variables** (`number_of_robots = 4`, `namespace = 'TB3'`), not proper `LaunchConfiguration` parameters. Users must edit the script directly to reconfigure it. Use Nav2's `cloned_multi_tb3_simulation_launch.py` instead.

**Nav2 Simple Commander API (verified 3-0):** PR #3803 added a `namespace` constructor parameter to enable programmatic per-robot control:

```python
from nav2_simple_commander.robot_navigator import BasicNavigator
tb1_nav = BasicNavigator(namespace='tb1')
tb2_nav = BasicNavigator(namespace='tb2')
```

---

### Building Block 3: Application Launchers with Gazebo

The standard multi-robot Gazebo launch structure:

```
gazebo_launch.py              ← world server (headless), gzserver
  └── spawn_entity ×N         ← one per robot, unique entity name + namespace
nav2_bringup ×N               ← one Nav2 stack per robot under /tbN/ namespace
  ├── amcl
  ├── nav2_controller
  ├── nav2_planner
  ├── nav2_bt_navigator
  └── map_server (per-robot or shared)
```

**Gazebo entity name uniqueness (verified):** Attempting to spawn two robots with the same entity name fails with `Entity [burger] already exists`. Each robot needs a unique `--robot-name` flag passed to `spawn_entity`.

**`spawn_entity` TF remapping note:** The Nav2 README historically noted that `spawn_entity` "could not remap /tf and /tf_static in the launch file yet" — this language uses "yet" indicating a temporary limitation. The recommended approach is to apply remapping inside the SDF plugin's `<ros>` tag or in `robot_state_publisher` arguments rather than relying on launch-file-level remapping of `spawn_entity`.

---

## Part 2: Zenoh Bridge Architecture for OpenShift

### Why DDS Fails in Kubernetes/OpenShift (verified 3-0)

- ROS2 DDS/RTPS embeds IP addresses and ports directly in packets; Kubernetes Services perform NAT/PAT which breaks RTPS communication
- CNI overlays (Calico, Flannel, and likely OVN-Kubernetes on OpenShift 4.12+) block multicast, preventing DDS peer discovery
- Multiple ROS2 containers in one Pod cause loopback port collisions — one ROS2 node per Pod is required

### The `zenoh-bridge-ros2dds` Solution

**Critical choice: use `zenoh-bridge-ros2dds`, NOT `rmw_zenoh`** (verified 3-0)

`rmw_zenoh` and `zenoh-bridge-ros2dds` use **incompatible Zenoh key expression schemas** and cannot interoperate. Pick one uniformly across all pods.

`zenoh-bridge-ros2dds` advantages for this use case:
- Runs as a sidecar alongside existing DDS nodes — no ROS2 node code changes required
- Prefixes **all** routed topics (including absolute-path system topics `/rosout`, `/tf`, `/tf_static`) with a configured namespace
- Eliminates the need to reconfigure individual Nav2 nodes with namespaces

**Hard architectural prerequisite (verified 3-0):** Per-pod DDS isolation via `ROS_LOCALHOST_ONLY=1` or unique `ROS_DOMAIN_ID` per pod. Without it, bridged traffic between hosts loops or duplicates.

**Zenoh router requirement (verified 2-1):** A centralized Zenoh router Pod is required for node discovery since multicast is disabled by default. Clients connect via TCP to port 7447:

```bash
# Per-robot pod environment variables
ROS_LOCALHOST_ONLY=1
ROS_DOMAIN_ID=1                          # unique per robot pod
ZENOH_CONFIG_OVERRIDE='mode="client";connect/endpoints=["tcp/zenoh-router:7447"]'
ZENOH_BRIDGE_NAMESPACE=/tb1              # unique per robot bridge sidecar
```

**Performance note (verified 3-0, medium confidence):** On Ethernet (intra-cluster OpenShift traffic), CycloneDDS outperforms Zenoh in raw latency (~1.29ms vs ~1.98ms). Zenoh's value here is **architectural** — circumventing CNI multicast incompatibility — not latency optimization. Zenoh's latency advantage appears on wireless/WAN links.

---

## Part 3: OpenShift Deployment Proposal

### Pod Topology

```
OpenShift Namespace: ros2-multi-robot
│
├── [Deployment] zenoh-router              ← 1 replica
│     Image: eclipse/zenoh-router:latest
│     ClusterIP Service :7447
│
├── [Deployment] gazebo-sim                ← 1 replica (headless)
│     Image: your-registry/gazebo-headless:humble
│     ENV: ROS_LOCALHOST_ONLY=1
│     Sidecar: Xvfb (virtual framebuffer)
│     Runs: gzserver + spawn_entity ×N
│     Mounts: robots-config ConfigMap
│
├── [Deployment] tb1-nav2                  ← 1 replica per robot
│     containers:
│       - nav2  (ROS2 Nav2 stack, namespace=tb1)
│       - zenoh-bridge  (sidecar, ZENOH_BRIDGE_NAMESPACE=/tb1)
│     ENV: ROS_LOCALHOST_ONLY=1, ROS_DOMAIN_ID=1
│
├── [Deployment] tb2-nav2
│     containers:
│       - nav2  (namespace=tb2)
│       - zenoh-bridge  (ZENOH_BRIDGE_NAMESPACE=/tb2)
│     ENV: ROS_LOCALHOST_ONLY=1, ROS_DOMAIN_ID=2
│
└── [Deployment] foxglove-bridge           ← 1 replica
      Image: ghcr.io/foxglove/bridge:latest
      WebSocket :8765
      OpenShift Route (TLS edge) → external browser
      Subscribes to all /tbN/* topics via Zenoh
```

### ConfigMap: `robots-config`

```yaml
apiVersion: v1
kind: ConfigMap
metadata:
  name: robots-config
  namespace: ros2-multi-robot
data:
  robots.yaml: |
    - name: tb1
      x_pose: 0.0
      y_pose: 0.0
      z_pose: 0.01
      enabled: true
      domain_id: 1
    - name: tb2
      x_pose: 2.0
      y_pose: 0.0
      z_pose: 0.01
      enabled: true
      domain_id: 2
```

### Dockerfile Definitions

**Image 1: `ros2-tb3-nav2` (shared Nav2 + TurtleBot3 base)**

```dockerfile
FROM osrf/ros:humble-desktop

RUN apt-get update && apt-get install -y \
    ros-humble-turtlebot3 \
    ros-humble-turtlebot3-simulations \
    ros-humble-nav2-bringup \
    ros-humble-nav2-simple-commander \
    python3-pyyaml \
  && rm -rf /var/lib/apt/lists/*

ENV TURTLEBOT3_MODEL=burger

COPY launch/ /opt/ros2_ws/src/multi_robot_launch/launch/
COPY config/ /opt/ros2_ws/src/multi_robot_launch/config/

RUN cd /opt/ros2_ws \
  && . /opt/ros/humble/setup.sh \
  && colcon build --symlink-install

COPY entrypoint-nav2.sh /entrypoint.sh
ENTRYPOINT ["/entrypoint.sh"]
```

**Image 2: `gazebo-headless` (Gazebo world + robot spawner)**

```dockerfile
FROM ros2-tb3-nav2

RUN apt-get update && apt-get install -y \
    xvfb \
    ros-humble-gazebo-ros-pkgs \
  && rm -rf /var/lib/apt/lists/*

COPY entrypoint-gazebo.sh /entrypoint.sh
ENTRYPOINT ["/entrypoint.sh"]
# entrypoint-gazebo.sh: starts Xvfb on :99, then gzserver + spawn_entity per robot
```

**Image 3: `zenoh-bridge-ros2dds` sidecar**

```dockerfile
# Use the upstream pre-built image directly
FROM eclipse/zenoh-bridge-ros2dds:latest
# Configuration supplied entirely via environment variables at runtime
```

### Helm Chart Structure

```
helm/multi-robot-openshift/
├── Chart.yaml
├── values.yaml
└── templates/
    ├── configmap-robots.yaml
    ├── deployment-zenoh-router.yaml
    ├── service-zenoh-router.yaml
    ├── deployment-gazebo.yaml
    ├── deployment-nav2.yaml          ← range over .Values.robots
    ├── deployment-foxglove.yaml
    ├── service-foxglove.yaml
    └── route-foxglove.yaml
```

**`values.yaml`** — mirrors the `cloned_multi_tb3` YAML list format:

```yaml
robots:
  - name: tb1
    pose: {x: 0.0, y: 0.0, z: 0.01}
    domainId: 1
  - name: tb2
    pose: {x: 2.0, y: 0.0, z: 0.01}
    domainId: 2

zenohRouter:
  image: eclipse/zenoh-router:latest
  port: 7447

gazebo:
  image: your-registry/gazebo-headless:humble
  world: turtlebot3_world

nav2:
  image: your-registry/ros2-tb3-nav2:humble
  bridgeImage: eclipse/zenoh-bridge-ros2dds:latest

foxglove:
  image: ghcr.io/foxglove/bridge:latest
  port: 8765
  routeHost: foxglove.apps.your-cluster.example.com
```

**`templates/deployment-nav2.yaml`** — one Deployment per robot via `range`:

```yaml
{{- range .Values.robots }}
---
apiVersion: apps/v1
kind: Deployment
metadata:
  name: {{ .name }}-nav2
  namespace: ros2-multi-robot
spec:
  replicas: 1
  selector:
    matchLabels:
      app: ros2-nav2
      robot: {{ .name }}
  template:
    metadata:
      labels:
        app: ros2-nav2
        robot: {{ .name }}
    spec:
      containers:
      - name: nav2
        image: {{ $.Values.nav2.image }}
        env:
        - name: ROS_LOCALHOST_ONLY
          value: "1"
        - name: ROS_DOMAIN_ID
          value: "{{ .domainId }}"
        - name: ROBOT_NAMESPACE
          value: {{ .name }}
        command:
        - ros2
        - launch
        - multi_robot_launch
        - tb3_nav2.launch.py
        - namespace:={{ .name }}
        - use_sim_time:=true
        - x_pose:={{ .pose.x }}
        - y_pose:={{ .pose.y }}
        volumeMounts:
        - name: robots-config
          mountPath: /config

      - name: zenoh-bridge
        image: {{ $.Values.nav2.bridgeImage }}
        env:
        - name: ROS_LOCALHOST_ONLY
          value: "1"
        - name: ROS_DOMAIN_ID
          value: "{{ .domainId }}"
        - name: ZENOH_CONFIG_OVERRIDE
          value: 'mode="client";connect/endpoints=["tcp/zenoh-router:7447"]'
        - name: ZENOH_BRIDGE_NAMESPACE
          value: /{{ .name }}

      volumes:
      - name: robots-config
        configMap:
          name: robots-config
{{- end }}
```

### Zenoh Router Deployment

```yaml
apiVersion: apps/v1
kind: Deployment
metadata:
  name: zenoh-router
  namespace: ros2-multi-robot
spec:
  replicas: 1
  selector:
    matchLabels:
      app: zenoh-router
  template:
    metadata:
      labels:
        app: zenoh-router
    spec:
      containers:
      - name: zenoh-router
        image: eclipse/zenoh-router:latest
        ports:
        - containerPort: 7447
          protocol: TCP
---
apiVersion: v1
kind: Service
metadata:
  name: zenoh-router
  namespace: ros2-multi-robot
spec:
  selector:
    app: zenoh-router
  ports:
  - port: 7447
    targetPort: 7447
    protocol: TCP
  type: ClusterIP
```

### Foxglove Bridge Route (OpenShift)

```yaml
apiVersion: route.openshift.io/v1
kind: Route
metadata:
  name: foxglove-bridge
  namespace: ros2-multi-robot
spec:
  host: foxglove.apps.your-cluster.example.com
  to:
    kind: Service
    name: foxglove-bridge
  port:
    targetPort: 8765
  tls:
    termination: edge
```

---

## Mapping to `lokeshrangineni/ros2-openshift-demo` distributed-zenoh Pattern

| distributed-zenoh element | Multi-robot extension in this proposal |
|---|---|
| Single Zenoh router Pod + ClusterIP Service | Same — shared discovery backbone for all N robot pods |
| Single `zenoh-bridge-ros2dds` sidecar container | Replicated N times, each with unique `ZENOH_BRIDGE_NAMESPACE=/tbN` |
| Single ROS2 node Pod | Replaced by N Nav2 Deployment pods, generated via Helm `range` over `values.robots` |
| `ROS_LOCALHOST_ONLY=1` env var | Same — hard requirement per pod to prevent DDS cross-pod looping |
| `ZENOH_CONFIG_OVERRIDE` pointing to router | Same — points to `zenoh-router` ClusterIP DNS name |
| No DDS cross-pod communication | Same — Gazebo and Nav2 pods communicate exclusively through Zenoh |
| Single robot manifest | Replaced by Helm template + `values.yaml` robots array mirroring `cloned_multi_tb3` format |

---

## Caveats & Open Questions

### Known Risks

1. **Gazebo headless in OpenShift** is the largest practical blocker. The Gazebo simulation Pod requires a virtual framebuffer (Xvfb) or a headless-capable Gazebo build. GPU passthrough and OpenGL support in OpenShift containers are not covered by any verified source and may prevent physics-accurate multi-robot simulation without a GPU-enabled node.

2. **OVN-Kubernetes multicast behavior** (OpenShift 4.12+ default CNI) was not confirmed by any verified source. Calico and Flannel are confirmed to block DDS multicast, but OVN-Kubernetes needs empirical testing in your target cluster before assuming Zenoh is required.

3. **`zenoh-bridge-ros2dds` ROS2 version compatibility:** Clearpath Robotics documents the bridge as compatible with ROS2 Jazzy and later. If running ROS2 Humble, verify the bridge release matrix before committing to this approach.

4. **Nav2 action traffic and cross-robot TF visualization:** Routing bidirectional Nav2 action traffic (action servers/clients, not just pub/sub) and displaying all N robot TF frames in a single Foxglove/RViz session through the bridge remains unverified. A known filtering bug (zenoh-plugin-ros2dds Issue #241) may affect which topics are actually routed — validate `allow`/`deny` filter configuration carefully.

### Open Questions

1. What specific Kubernetes manifests exist in `lokeshrangineni/ros2-openshift-demo/examples/distributed-zenoh`? Do they cover multi-robot (N bridge pods) or only single-robot bridging? This proposal assumes N-fold extension is viable but the actual manifests need inspection to confirm router Service structure and sidecar configuration.

2. Does OVN-Kubernetes block DDS multicast similarly to Calico/Flannel? This is the deployment-critical CNI for the target OpenShift environment.

3. What is the realistic physics simulation rate (Hz) for N TurtleBot3 robots on CPU-only OpenShift nodes without GPU passthrough?

4. Can a single Foxglove Bridge instance subscribe to all `/tbN/*` namespaced topics across N robots via Zenoh without additional relay nodes?

---

## Sources

| Source | Type | Key contribution |
|---|---|---|
| [ROBOTIS eManual — TurtleBot3 Basic Examples](https://emanual.robotis.com/docs/en/platform/turtlebot3/basic_examples/) | Primary | Namespace launch args, TF frame uniqueness guidance |
| [ROBOTIS-GIT/turtlebot3 robot.launch.py](https://github.com/ROBOTIS-GIT/turtlebot3/blob/ros2/turtlebot3_bringup/launch/robot.launch.py) | Primary | `PushRosNamespace` implementation |
| [Nav2 multi-robot bringup README](https://github.com/ros-navigation/navigation2/blob/main/nav2_bringup/README.md) | Primary | `cloned_multi_tb3` vs `unique_multi_tb3` pattern documentation |
| [cloned_multi_tb3_simulation_launch.py](https://github.com/ros-navigation/navigation2/blob/main/nav2_bringup/launch/cloned_multi_tb3_simulation_launch.py) | Primary | Scalable N-robot YAML list launch pattern |
| [eclipse-zenoh/zenoh-plugin-ros2dds](https://github.com/eclipse-zenoh/zenoh-plugin-ros2dds) | Primary | Bridge namespace prefix, DDS isolation requirement |
| [ros2/rmw_zenoh](https://github.com/ros2/rmw_zenoh) | Primary | rmw_zenoh/bridge incompatibility, router TCP config |
| [arshadlab/tb3_multi_robot](https://github.com/arshadlab/tb3_multi_robot) | Secondary | robots.yaml ConfigMap pattern, two-launch-file separation |
| [fujitatomoya/ros_k8s](https://github.com/fujitatomoya/ros_k8s) | Secondary | Fast-DDS Discovery Server on K8s, pod-per-node topology |
| [PMC — ROS2 on K3s paper](https://pmc.ncbi.nlm.nih.gov/articles/PMC12390455/) | Primary (peer-reviewed) | Validated pod-per-node pattern, Zenoh vs CycloneDDS benchmarks |
| [Ubuntu — ROS2 with Kubernetes](https://ubuntu.com/blog/exploring-ros-2-with-kubernetes) | Blog | DDS/RTPS NAT breakage, CNI multicast blocking |
| [Clearpath Robotics — Zenoh docs](https://docs.clearpathrobotics.com/docs/ros/networking/ros2_networking/zenoh/) | Secondary | Router TCP 7447 config, Jazzy+ compatibility note |
| [geometry2 PR #390, Issue #433](https://github.com/ros2/geometry2) | Primary | `/tf` absolute path hardcoding, remapping workaround |
| [Nav2 Issue #5449](https://github.com/ros-navigation/navigation2/issues/5449) | Forum | `/tb1/tf` topic pattern, community consensus on namespace vs tf_prefix |
