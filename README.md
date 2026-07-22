# Multi-Robot ROS2 Demo on OpenShift

A Helm-deployed multi-robot simulation demonstrating how to run independent
[ROS2](https://docs.ros.org/en/jazzy/) navigation stacks on
[OpenShift](https://www.redhat.com/en/technologies/cloud-computing/openshift),
with [Gazebo Harmonic](https://gazebosim.org/) physics,
[zenoh-bridge-ros2dds](https://github.com/eclipse-zenoh/zenoh-plugin-ros2dds)
sidecars for cross-pod DDS bridging, and a dedicated
[Zenoh router](https://zenoh.io/) pod as the central communication hub.

Two [TurtleBot3 Waffle](https://emanual.robotis.com/docs/en/platform/turtlebot3/overview/)
robots — **blue** and **red** — run in isolated OpenShift pods, each with its
own Nav2 autonomy stack (AMCL + planner + controller), and are independently
controllable in real time. All four pods (Gazebo simulation, two Nav2 stacks,
and the Zenoh router) connect through a single stable `zenoh-router` ClusterIP
Service, so any pod can restart without disrupting the others.

---

## Architecture

```
┌─────────────────────────── OpenShift namespace: ros2-multi-robot ──────────────────────────────┐
│                                                                                                 │
│  ┌──────────────────────────────────┐                                                          │
│  │  Pod: zenoh-router               │  ← dedicated Zenoh hub; lifecycle independent of         │
│  │  (eclipse/zenoh:latest)          │    Gazebo and Nav2                                       │
│  │  mode: router, TCP :7447         │                                                          │
│  └──────────────┬───────────────────┘                                                          │
│      ClusterIP Service: zenoh-router:7447                                                       │
│           ▲              ▲                      ▲                                               │
│           │ (client)     │ (client)             │ (client)                                      │
│  ┌────────┴─────────┐  ┌─┴──────────────────┐  ┌┴───────────────────┐                        │
│  │ Pod: gazebo-sim  │  │ Pod: robot-nav-     │  │ Pod: robot-nav-    │                        │
│  │                  │  │      robot-1        │  │      robot-2       │                        │
│  │ container: gazebo│  │                     │  │                    │                        │
│  │ • Gazebo Harmonic│  │ container: nav2     │  │ container: nav2    │                        │
│  │ • Spawns robot_1 │  │ namespace=robot_1   │  │ namespace=robot_2  │                        │
│  │   (blue,-2,-0.5) │  │ • AMCL              │  │ • AMCL             │                        │
│  │ • Spawns robot_2 │  │ • planner_server    │  │ • planner_server   │                        │
│  │   (red, 2, 0.5)  │  │ • controller_server │  │ • controller_server│                        │
│  │ • ros_gz_bridge  │  │ • bt_navigator      │  │ • bt_navigator     │                        │
│  │ • noVNC  (:6080) │  │ • map_server        │  │ • map_server       │                        │
│  │ • web    (:8080) │  │                     │  │                    │                        │
│  │                  │  │ /robot_1/scan       │  │ /robot_2/scan      │                        │
│  │ sidecar:         │  │ /robot_1/odom       │  │ /robot_2/odom      │                        │
│  │ zenoh-bridge     │  │ /robot_1/cmd_vel    │  │ /robot_2/cmd_vel   │                        │
│  │ (client)         │  │ /robot_1/tf         │  │ /robot_2/tf        │                        │
│  └──────────────────┘  │                     │  │                    │                        │
│                        │ sidecar:            │  │ sidecar:           │                        │
│                        │ zenoh-bridge        │  │ zenoh-bridge       │                        │
│                        │ (client)            │  │ (client)           │                        │
│                        └─────────────────────┘  └────────────────────┘                        │
└─────────────────────────────────────────────────────────────────────────────────────────────────┘
```

### Key design decisions

| Concern | Choice | Reason |
|---|---|---|
| Cross-pod DDS | `zenoh-bridge-ros2dds` sidecar | DDS multicast is blocked by OVN-Kubernetes CNI; Zenoh bridges over TCP |
| Zenoh topology | Dedicated `zenoh-router` pod; all bridges = clients | Router lifecycle is independent of Gazebo and Nav2 — Gazebo restarts don't disconnect Nav2 pods |
| Robot isolation | ROS2 namespaces (`/robot_1/`, `/robot_2/`) | Topics, TF, and actions are fully isolated per robot without zenoh namespace prefix |
| Navigation map | Predefined `tb3_sandbox` map (AMCL) | Avoids SLAM instability; robots localize instantly at spawn |
| Deployment | Helm chart (`helm/multi-robot-demo/`) | `values.yaml` `robots:` list drives N-robot scaling; one Deployment template per robot via `range` |
| Robot colours | Per-robot diffuse in SDF xacro | `entrypoint-gazebo.sh` patches `gz_waffle.sdf.xacro` at spawn time from the `ROBOTS` env var |

---

## Repository structure

```
.
├── Containerfile                         # Single image: Fedora 43 + ROS Jazzy + Gazebo Harmonic + noVNC
├── Makefile                              # build / push / deploy / reset / demo targets
├── entrypoints/
│   ├── entrypoint-gazebo.sh              # Gazebo pod: spawns N colour-coded robots
│   └── entrypoint-nav2.sh               # Nav2 pod: namespaced Nav2 + AMCL initialisation
├── config/
│   ├── worlds/tb3_sandbox.sdf.xacro      # Gazebo world (turtlebot3_world + plugins)
│   └── www/index.html                    # Web landing page served in the Gazebo pod
├── demo/
│   └── meet_demo.py                      # Autonomous meet demo (Nav2 Simple Commander)
└── helm/
    └── multi-robot-demo/
        ├── Chart.yaml
        ├── values.yaml                   # Robot list, images, resources, route hosts
        ├── files/
        │   ├── zenoh-router.json5        # Zenoh config: standalone router
        │   ├── gazebo-bridge.json5       # Zenoh config: client mode → zenoh-router
        │   └── nav2-bridge.json5         # Zenoh config: client mode → zenoh-router
        └── templates/
            ├── configmap-zenoh.yaml
            ├── deployment-zenoh-router.yaml  # Dedicated Zenoh router pod + ClusterIP Service
            ├── deployment-gazebo.yaml        # Single Gazebo pod
            ├── deployment-nav2.yaml          # {{- range .Values.robots }} → one pod per robot
            ├── serviceaccount.yaml
            └── services-routes.yaml          # noVNC/web Services + OpenShift Routes
```

---

## Prerequisites

| Tool | Version |
|---|---|
| `podman` | ≥ 4.x (macOS: `/opt/podman/bin/podman`) |
| `helm` | ≥ 3.13 |
| `oc` | ≥ 4.10 |
| OpenShift cluster | ≥ 4.10 (tested on 4.10) |
| quay.io push access | to `quay.io/jianrzha/ros2-demo` |

---

## Quickstart

### 1. Log in

```bash
# OpenShift cluster
oc login --token=<token> --server=https://api.<cluster>:6443

# Container registry
/opt/podman/bin/podman login quay.io
```

### 2. Build and push the container image

```bash
make build-push
```

This builds a single image (`quay.io/jianrzha/ros2-demo:latest`) used by both
the Gazebo pod and the Nav2 pods (different entrypoints, same image).

> **First build:** ~10–15 min (Fedora 43 + ROS Jazzy COPR packages).  
> **Subsequent builds:** ~2 min (only the final `COPY entrypoints/` layer changes).

### 3. Deploy to OpenShift

```bash
make deploy
```

This runs `helm upgrade --install` into the `ros2-multi-robot` namespace and
creates:

| Resource | Count |
|---|---|
| Deployment (`zenoh-router`) | 1 |
| Deployment (`gazebo-sim`) | 1 |
| Deployment (`robot-nav-robot-1`, `robot-nav-robot-2`) | 1 per robot |
| ClusterIP Services (zenoh-router, noVNC, web) | 3 |
| OpenShift Routes (noVNC, web) | 2 |
| ConfigMap (`zenoh-bridge-config`) | 1 |
| ServiceAccount (`ros2-demo`) | 1 |

### 4. Check status

```bash
make status    # oc get pods -n ros2-multi-robot -o wide
make routes    # print noVNC and web route URLs
```

Wait ~2 min for all pods to reach `2/2 Running` (Gazebo and Nav2 pods) and
`1/1 Running` (zenoh-router). The Gazebo pod readiness probe has a 60 s
initial delay (Gazebo server startup).

### 5. Open the simulation

Navigate to the **noVNC route** printed by `make routes`:

```
https://ros2-multi-robot-novnc-ros2-multi-robot.apps.<cluster>
```

You should see two TurtleBot3 robots — blue (`robot_1`) and red (`robot_2`) —
in the Gazebo GUI.

---

## Moving the robots manually

All commands use `oc exec` into the Nav2 pod. The `export HOME=/tmp/ros-home`
prefix is required because ROS logging needs a writable directory.

```bash
# Move blue robot (robot_1) forward
POD1=$(oc get pod -n ros2-multi-robot -l app=robot-nav-robot-1 \
        -o jsonpath='{.items[0].metadata.name}')
oc exec -n ros2-multi-robot "$POD1" -c nav2 -- bash -c \
  'export HOME=/tmp/ros-home; source /usr/lib64/ros-jazzy/setup.bash
   ros2 topic pub /robot_1/cmd_vel geometry_msgs/msg/Twist \
     "{linear: {x: 0.3}}" --times 20 --rate 10'

# Move red robot (robot_2) backward
POD2=$(oc get pod -n ros2-multi-robot -l app=robot-nav-robot-2 \
        -o jsonpath='{.items[0].metadata.name}')
oc exec -n ros2-multi-robot "$POD2" -c nav2 -- bash -c \
  'export HOME=/tmp/ros-home; source /usr/lib64/ros-jazzy/setup.bash
   ros2 topic pub /robot_2/cmd_vel geometry_msgs/msg/Twist \
     "{linear: {x: -0.3}}" --times 20 --rate 10'

# Spin in place
#   angular.z > 0  → counter-clockwise
#   angular.z < 0  → clockwise
```

---

## Autonomous Meet Demo

`demo/meet_demo.py` uses the **Nav2 Simple Commander API** to autonomously
navigate both robots to swap starting positions — crossing paths in the middle
of the world.

```
robot_1 (blue)  (-2, -0.5)  ─────────────────────► (2, 0.5)
                                       ✕
robot_2 (red)   ( 2,  0.5)  ◄───────────────────── (-2, -0.5)
```

### Run

```bash
make reset   # teleport both robots back to spawn positions
make demo    # copy script + run autonomous navigation
```

Or step by step:

```bash
# 1. Reset robot positions
make reset

# 2. Copy the demo script into the Nav2 pod
NAV1=$(oc get pod -n ros2-multi-robot -l app=robot-nav-robot-1 \
        -o jsonpath='{.items[0].metadata.name}')
oc cp demo/meet_demo.py ros2-multi-robot/${NAV1}:/tmp/meet_demo.py -c nav2

# 3. Run the demo
oc exec -n ros2-multi-robot "$NAV1" -c nav2 -- bash -c \
  'export HOME=/tmp/ros-home; source /usr/lib64/ros-jazzy/setup.bash
   python3 /tmp/meet_demo.py'
```

### Expected output

```
============================================================
 Meet Demo — robots swap positions (cross paths)
   robot_1 (blue): (-2, -0.5) → (2,  0.5)
   robot_2 (red):  ( 2,  0.5) → (-2, -0.5)
============================================================
[robot_1/blue] Waiting for Nav2 to become active...
[robot_2/red]  Waiting for Nav2 to become active...
[robot_1/blue] Nav2 active. Setting initial pose (-2.0, -0.5)...
[robot_2/red]  Nav2 active. Setting initial pose (2.0, 0.5)...
[robot_1/blue] Navigating to (2.0, 0.5) ...
[robot_2/red]  Navigating to (-2.0, -0.5) ...
[robot_1/blue]   3.21 m remaining
[robot_2/red]    3.18 m remaining
...
[robot_1/blue] Navigation SUCCEEDED ✓
[robot_2/red]  Navigation SUCCEEDED ✓

============================================================
 Results
============================================================
  robot_1 (blue): SUCCEEDED ✓
  robot_2 (red):  SUCCEEDED ✓
```

---

## Configuration

### Add a third robot

Edit `helm/multi-robot-demo/values.yaml`:

```yaml
robots:
  - name: robot_1
    color: "0,0,1"      # blue
    initialPose: { xPos: -2.0, yPos: -0.5, yaw: 0.0 }
  - name: robot_2
    color: "1,0,0"      # red
    initialPose: { xPos: 2.0, yPos: 0.5, yaw: 3.14159 }
  - name: robot_3
    color: "0,0.8,0"    # green
    initialPose: { xPos: 0.0, yPos: -2.0, yaw: 1.5708 }
```

Then redeploy:

```bash
make deploy
```

One new `robot-nav-robot-3` Deployment is created automatically and its
zenoh-bridge sidecar connects to the shared `zenoh-router` pod as a new
client. No template changes required.

### Change robot colours

Colours are RGB values in the 0–1 range passed via the `color:` field.
Examples: `"1,0.5,0"` (orange), `"0.5,0,0.5"` (purple), `"1,1,0"` (yellow).

### Use a GPU node for Gazebo

```bash
helm upgrade multi-robot-demo helm/multi-robot-demo \
  --namespace ros2-multi-robot \
  --reuse-values \
  --set gazebo.gpu=true
```

With `gpu: true` the Gazebo deployment adds:
- `nvidia.com/gpu: 1` resource request/limit
- `nvidia.com/gpu: NoSchedule` toleration
- `NVIDIA_VISIBLE_DEVICES=all` and `NVIDIA_DRIVER_CAPABILITIES=all` env vars

The entrypoint detects `nvidia-smi` at runtime and switches from llvmpipe
software rendering to full GPU rendering automatically.

### Adjust resource requests

```bash
helm upgrade multi-robot-demo helm/multi-robot-demo \
  --namespace ros2-multi-robot \
  --reuse-values \
  --set gazebo.resources.requests.cpu=2 \
  --set nav2.resources.requests.memory=1Gi
```

---

## Makefile reference

```
make help          Show all targets

Build
  make build       Build the container image with podman
  make push        Push to quay.io/jianrzha/ros2-demo:latest
  make build-push  Build and push in one step

Deploy
  make deploy      helm upgrade --install into ros2-multi-robot namespace
  make undeploy    helm uninstall + delete namespace
  make restart     Rolling restart of all pods
  make set-image   Upgrade with a new tag: make set-image TAG=v1.2

Demo
  make reset       Teleport both robots to spawn positions via gz service
  make demo        Reset + copy meet_demo.py + run autonomous navigation

Helm
  make template    Render templates to stdout (for review)
  make lint        Lint the Helm chart
  make package     Package chart into dist/

Utilities
  make status      oc get pods
  make routes      Print route URLs
```

> **Namespace override:** if your shell has a `NAMESPACE` env var set, use
> `ROS_DEMO_NS=<ns>` instead:
> ```bash
> make reset ROS_DEMO_NS=ros2-multi-robot
> make demo  ROS_DEMO_NS=ros2-multi-robot
> ```

---

## How it works — Zenoh bridge topology

```
Within each pod: standard ROS2 DDS (localhost, shared memory)
Between pods:    Zenoh TCP transport via zenoh-bridge-ros2dds sidecars

                     ┌──────────────────┐
                     │   zenoh-router   │  eclipse/zenoh:latest
                     │   mode: router   │  ClusterIP :7447
                     └────────┬─────────┘
             ┌────────────────┼─────────────────┐
             │ (client)       │ (client)         │ (client)
    ┌────────┴───────┐  ┌─────┴──────────┐  ┌───┴────────────┐
    │  gazebo-sim    │  │ robot-nav-      │  │ robot-nav-     │
    │  zenoh-bridge  │  │ robot-1        │  │ robot-2        │
    │                │  │ zenoh-bridge   │  │ zenoh-bridge   │
    │ /robot_1/*     │  │                │  │                │
    │ /robot_2/*     │  │ /robot_1/*     │  │ /robot_2/*     │
    │ (local DDS)    │  │ (local DDS)    │  │ (local DDS)    │
    └────────────────┘  └────────────────┘  └────────────────┘
```

- **DDS stays local:** each pod uses `ROS_DOMAIN_ID=0` with no cross-pod multicast
- **Zenoh carries everything:** all `/robot_N/scan`, `/robot_N/odom`,
  `/robot_N/cmd_vel`, `/robot_N/tf`, `/clock` topics are bridged transparently
- **No node changes:** ROS2 nodes publish/subscribe via DDS as usual; the bridge
  handles cross-pod routing invisibly
- **Independent router:** the `zenoh-router` pod lifecycle is decoupled from
  Gazebo and Nav2 — restarting the Gazebo pod does not disconnect Nav2 bridges
- **Client reconnection:** all bridge configs set `exit_on_failure: false` with
  exponential-backoff retry (1 s → 16 s), so any pod survives router restarts

---

## Based on

- [lokeshrangineni/ros2-openshift-demo](https://github.com/lokeshrangineni/ros2-openshift-demo/tree/main/examples/distributed-zenoh) — single-robot distributed-zenoh reference
- [eclipse-zenoh/zenoh-plugin-ros2dds](https://github.com/eclipse-zenoh/zenoh-plugin-ros2dds) — Zenoh bridge
- [ros-navigation/navigation2](https://github.com/ros-navigation/navigation2) — Nav2 + Simple Commander API
- [ROBOTIS TurtleBot3](https://emanual.robotis.com/docs/en/platform/turtlebot3/) — robot model and simulation
