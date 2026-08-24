# RMF Hotel World - Federated Multi-Pod Demo

## Overview

This demo showcases a **fully federated multi-pod architecture** for Open-RMF hotel world simulation on OpenShift, demonstrating:

- **Zenoh-based DDS federation** for cross-pod ROS2 communication
- **Clock synchronization** across distributed pods using monotonic relay
- **Multi-level hotel building** with lifts, doors, and autonomous robots
- **Continuous patrol** of 4 robots managed by Open-RMF fleet adapters

## Architecture

The demo runs across **7 pods** in separate containers:

```
┌─────────────────────────────────────────────────────────────┐
│                     Zenoh Router                            │
│              (Federation Hub - Eclipse Zenoh 1.5.0)         │
└─────────────────────────────────────────────────────────────┘
                              │
         ┌────────────────────┼────────────────────┐
         │                    │                    │
┌────────▼─────────┐  ┌───────▼──────────┐  ┌────▼──────────┐
│   Gazebo Pod     │  │    RMF Pod       │  │  Robot Pods   │
│                  │  │                  │  │  (x4 Nav2)    │
│ • Hotel world    │  │ • Fleet mgmt     │  │               │
│ • 4 slotcar      │  │ • Task dispatch  │  │ • robot_1     │
│   robots         │  │ • Clock relay    │  │ • robot_2     │
│ • Lifts/doors    │  │ • Traffic sched  │  │ • robot_3     │
│ • RMF adapters   │  │                  │  │ • robot_4     │
│                  │  │                  │  │               │
│ Domain: 0        │  │ Domain: 55       │  │ Domain: 0     │
└──────────────────┘  └──────────────────┘  └───────────────┘
```

### Pod Breakdown

1. **Gazebo Pod (`gazebo-sim`)**
   - Image: `quay.io/jianrzha/ros2-rmf-hotel:latest`
   - Runs hotel.world with multi-level building
   - 4 slotcar robots (deliveryBot, tinyBot, 2x cleanerBotA)
   - RMF fleet adapters for robot control
   - noVNC visualization on port 6080
   - ROS domain: 0

2. **RMF Core Pod (`rmf-core`)**
   - Image: `quay.io/jianrzha/ros2-rmf:latest`
   - Fleet management and task dispatch
   - Monotonic clock relay (filters backward jumps)
   - Traffic scheduling coordinator
   - ROS domain: 55

3. **Nav2 Robot Pods (4x `robot-nav-robot-{1,2,3,4}`)**
   - Image: `quay.io/jianrzha/ros2-hotel-demo:latest`
   - TurtleBot3 Waffle with Nav2 stack
   - AMCL localization
   - Zenoh bridge sidecars:
     - `zenoh-bridge`: DDS-Zenoh communication
     - `zenoh-clock-bridge`: Clock synchronization
     - `zenoh-cmdvel-keepalive`: Velocity command relay
   - ROS domain: 0

4. **Zenoh Router Pod (`zenoh-router`)**
   - Image: `eclipse/zenoh:1.5.0`
   - Central hub for cross-pod federation
   - Bridges domain 0 ↔ domain 55

## Deployment

### Prerequisites

- OpenShift cluster access
- Namespace: `ros2-rmf-hotel-federated`
- Images built and pushed to quay.io

### Deploy

```bash
# Deploy the federated hotel demo
helm upgrade --install multi-robot-demo helm/multi-robot-demo \
  --namespace ros2-rmf-hotel-federated \
  --create-namespace \
  -f helm/multi-robot-demo/values.yaml \
  -f helm/multi-robot-demo/values-hotel-federated.yaml \
  --set namespace=ros2-rmf-hotel-federated

# Verify all pods are running
oc get pods -n ros2-rmf-hotel-federated

# Expected output (all Running):
# NAME                                 READY   STATUS
# gazebo-sim-xxxxx                     2/2     Running
# rmf-core-xxxxx                       1/1     Running
# robot-nav-robot-1-xxxxx              4/4     Running
# robot-nav-robot-2-xxxxx              4/4     Running
# robot-nav-robot-3-xxxxx              4/4     Running
# robot-nav-robot-4-xxxxx              4/4     Running
# zenoh-router-xxxxx                   1/1     Running
```

### Access the Demo

**noVNC Visualization:**
```
https://ros2-multi-robot-novnc-ros2-rmf-hotel-federated.apps.ai-dev02.kni.syseng.devcluster.openshift.com
```

You'll see:
- Multi-level hotel building (3 levels)
- 4 slotcar robots patrolling the lobby (L1)
- Gazebo Harmonic GUI with 3D visualization

## Continuous Patrol

The demo automatically runs a continuous patrol script for all 4 hotel robots.

### How It Works

The `hotel_patrol_loop.py` script runs in the Gazebo pod and:

1. Sends navigation commands to fleet manager HTTP APIs
2. Each robot patrols a dedicated zone (no collisions)
3. Alternates between 2 waypoints per robot
4. Runs indefinitely in background

### Robot Zones

| Robot          | Zone        | Waypoints                              |
|----------------|-------------|----------------------------------------|
| deliveryBot_1  | West        | (14.87,-28.77) ↔ (13.57,-21.79)       |
| tinyBot_1      | Center-East | (22.0,-26.5) ↔ (22.0,-30.0)           |
| cleanerBotA_1  | South-West  | (15.0,-30.5) ↔ (15.0,-35.0)           |
| cleanerBotA_2  | South       | (22.0,-33.5) ↔ (22.0,-37.0)           |

### Verify Patrol Status

```bash
# Check patrol log
GAZEBO_POD=$(oc get pod -n ros2-rmf-hotel-federated -l app=gazebo-sim --no-headers | awk '{print $1}')
oc exec -n ros2-rmf-hotel-federated $GAZEBO_POD -c gazebo -- tail -30 /tmp/patrol.log

# Expected output:
# Cycle 1: del(14,-23) | tin(22,-30) | cle(15,-35) | cle(22,-37)
#   [deliveryBot_1] -> (14.87,-28.77) ✓
#   [tinyBot_1] -> (22.0,-26.5) ✓
#   [cleanerBotA_1] -> (15.0,-30.5) ✓
#   [cleanerBotA_2] -> (22.0,-33.5) ✓
```

## Clock Synchronization Fix

### Problem

In federated multi-pod ROS2 deployments, simulation clock drift causes:
- `TF_OLD_DATA` errors in Nav2 collision monitor
- Robots ignore outdated sensor data (13-34 seconds old)
- Navigation failures due to rejected transforms

### Solution

**Monotonic Clock Relay** in RMF pod filters backward timestamp jumps:

```python
# entrypoints/monotonic_clock_relay.py
# Zenoh half: subscribe to 'clock', filter backward jumps
def zenoh_subscriber(robot_name: str):
    last_ns = 0
    def on_clock(sample):
        nonlocal last_ns
        ns = sec * 1_000_000_000 + nsec
        if ns < last_ns:
            return  # Drop backward jump (Gazebo restart)
        last_ns = ns
        sys.stdout.write(f"{sec} {nsec}\n")
```

**Clock Bridge Sidecars** in robot pods relay filtered clock:
- `zenoh-clock-bridge`: Subscribes to `clock_relay/clock_bridge` via Zenoh
- Publishes to local `/clock_bridge` topic
- `nav2_relay.py` filters again and publishes to `/clock`

### Verification

```bash
# Check for TF_OLD_DATA errors (should be 0)
ROBOT_POD=$(oc get pod -n ros2-rmf-hotel-federated --no-headers | grep robot-nav-robot-1 | grep Running | awk '{print $1}')
oc logs -n ros2-rmf-hotel-federated $ROBOT_POD -c nav2 --tail=100 | grep TF_OLD_DATA | wc -l

# Expected: 0 (no errors)
```

## Configuration Files

### Main Values File

`helm/multi-robot-demo/values-hotel-federated.yaml`:

```yaml
namespace: ros2-rmf-hotel-federated

# Hotel demo disabled - using federated architecture
hotel:
  enabled: false

# Gazebo uses hotel-specific image
hotelImage:
  repository: quay.io/jianrzha/ros2-rmf-hotel
  tag: latest

# Nav2 robots use standard image
image:
  repository: quay.io/jianrzha/ros2-hotel-demo
  tag: latest

# 4 TurtleBot3 robots (separate Nav2 pods)
robots:
  - name: robot_1
    color: "1,0,0"
    initialPose: {xPos: 10.0, yPos: -25.0, yaw: 0.0}
  - name: robot_2
    color: "0,1,0"
    initialPose: {xPos: 15.0, yPos: -30.0, yaw: 1.57}
  - name: robot_3
    color: "0,0,1"
    initialPose: {xPos: 20.0, yPos: -25.0, yaw: 3.14}
  - name: robot_4
    color: "1,1,0"
    initialPose: {xPos: 15.0, yPos: -35.0, yaw: -1.57}

# Gazebo settings
gazebo:
  world: hotel  # Hotel world with multi-level building

# Nav2 settings
nav2:
  localizationMode: amcl
  localizationMap: /usr/lib64/ros-jazzy/share/nav2_bringup/maps/tb3_sandbox.yaml
```

### Templates

- `deployment-hotel-gazebo.yaml`: Gazebo pod with hotel world
- `deployment-nav2.yaml`: Nav2 robot pods with Zenoh sidecars
- `deployment-rmf.yaml`: RMF core with clock relay
- `configmap-zenoh.yaml`: Zenoh bridge configuration

## Technical Stack

- **ROS2**: Jazzy
- **Gazebo**: Harmonic
- **Nav2**: AMCL localization, DWB controller, collision monitor
- **Open-RMF**: Fleet management, traffic scheduling, task dispatch
- **Zenoh**: 1.5.0 (DDS federation via eclipse/zenoh-bridge-ros2dds)
- **Platform**: OpenShift 4.x

## Troubleshooting

### Robots Not Moving

1. **Check patrol script is running:**
   ```bash
   oc exec -n ros2-rmf-hotel-federated $GAZEBO_POD -c gazebo -- \
     ps aux | grep hotel_patrol_loop
   ```

2. **Restart patrol if needed:**
   ```bash
   oc exec -n ros2-rmf-hotel-federated $GAZEBO_POD -c gazebo -- \
     bash -c "nohup python3 /scripts/hotel_patrol_loop.py > /tmp/patrol.log 2>&1 &"
   ```

3. **Check fleet adapters:**
   ```bash
   oc logs -n ros2-rmf-hotel-federated $GAZEBO_POD -c gazebo | \
     grep fleet_adapter | tail -20
   ```

### Clock Sync Issues

1. **Check RMF clock relay:**
   ```bash
   oc logs -n ros2-rmf-hotel-federated rmf-core-xxxxx | grep clock
   ```

2. **Check for TF errors:**
   ```bash
   oc logs -n ros2-rmf-hotel-federated $ROBOT_POD -c nav2 | \
     grep TF_OLD_DATA
   ```

### noVNC Black Screen

1. **Check Gazebo GUI is running:**
   ```bash
   oc exec -n ros2-rmf-hotel-federated $GAZEBO_POD -c gazebo -- \
     ps aux | grep "gz sim gui"
   ```

2. **Check X server:**
   ```bash
   oc exec -n ros2-rmf-hotel-federated $GAZEBO_POD -c gazebo -- \
     ps aux | grep Xorg
   ```

3. **Restart pod if needed:**
   ```bash
   oc delete pod -n ros2-rmf-hotel-federated $GAZEBO_POD
   ```

## Key Differences from Single-Pod Hotel Demo

| Aspect              | Single-Pod                | Federated Multi-Pod           |
|---------------------|---------------------------|-------------------------------|
| **Architecture**    | All-in-one container      | 7 separate pods               |
| **Communication**   | Localhost DDS             | Zenoh federation              |
| **Robots**          | Slotcars only             | Slotcars + TurtleBot3 option  |
| **Domains**         | Single domain (0)         | Domain 0 + 55                 |
| **Clock Sync**      | Not needed                | Monotonic relay required      |
| **Scalability**     | Limited                   | Highly scalable               |
| **Resource Isolation** | None                   | Per-pod resource limits       |

## Development Notes

### Branch

`rmf-ros2-hotel-world-demon`

### Key Commits

- `9eafbe4`: Use different images for Gazebo vs Nav2 robots
- `8fd3326`: Use ros2-hotel-demo for robot pods
- `593ea62`: Use values.yaml image for hotel Gazebo deployment
- `721c6a0`: Use correct image for federated hotel demo
- `64ad9f1`: Revert to full federation with TurtleBot3 robots

### Building Images

```bash
# Build hotel image
make build-push-hotel

# This creates:
# quay.io/jianrzha/ros2-rmf-hotel:latest
```

## Future Enhancements

- [ ] Add multi-level navigation (L1 ↔ L2 ↔ L3)
- [ ] Enable lift and door operations
- [ ] Integrate TurtleBot3 Nav2 pods with hotel world visualization
- [ ] Add RMF web dashboard UI
- [ ] Implement delivery tasks with item pickup/dropoff
- [ ] Add charging station behavior
- [ ] Create custom navigation graphs for hotel layout

## References

- [Open-RMF Documentation](https://osrf.github.io/ros2multirobotbook/)
- [Zenoh Documentation](https://zenoh.io/docs/)
- [Nav2 Documentation](https://navigation.ros.org/)
- [Gazebo Harmonic](https://gazebosim.org/docs/harmonic)
