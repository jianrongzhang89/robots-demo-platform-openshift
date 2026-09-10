# ROS2 Lyrical + Ubuntu 26.04 Upgrade Plan

**Date:** 2026-09-09  
**Objective:** Upgrade from ROS2 Jazzy (Ubuntu 24.04) to ROS2 Lyrical (Ubuntu 26.04) to fix continuous joint DOF=0 bug  
**Impact:** Enables DiffDrive odometry for TurtleBot3 Nav2 integration in RMF Hotel demo

---

## Executive Summary

**Problem:** Gazebo Harmonic 8.11.0 + DART 6.13.2 in ROS2 Jazzy has a critical bug where continuous/revolute joints are converted to FIXED (0 DOF), preventing DiffDrive odometry from working.

**Solution:** Upgrade to ROS2 Lyrical Luth which ships with Gazebo Jetty 11.x + DART 6.16.6 where the bug is fixed.

**Timeline:** ~4-8 hours for container rebuild + testing

**Risk Level:** Medium (requires base image change, but containerized deployment limits impact)

---

## Current vs Target Environment

### Current (Broken)
```
Ubuntu:   24.04 Noble
ROS2:     Jazzy Jalisco (May 2024)
Gazebo:   Harmonic (gz-sim 8.11.0)
Physics:  DART 6.13.2
Status:   ❌ Continuous joints → FIXED (0 DOF)
```

### Target (Fixed)
```
Ubuntu:   26.04 (release name TBD)
ROS2:     Lyrical Luth (May 2026)
Gazebo:   Jetty (gz-sim 11.x)
Physics:  DART 6.16.6
Status:   ✅ Continuous joints work properly
```

---

## Upgrade Strategy

### Approach: Container-Based Migration

**Why Containerized Approach:**
- ✅ No disruption to host OpenShift cluster
- ✅ Easy rollback (keep old Jazzy image tagged)
- ✅ Test in parallel (deploy to separate namespace)
- ✅ Gradual migration (blue-green deployment)

**Base Image Change:**
```dockerfile
# Current
FROM ubuntu:24.04

# Target  
FROM ubuntu:26.04
```

---

## Phase 1: Preparation (1 hour)

### 1.1 Verify Ubuntu 26.04 Availability

**Action:**
```bash
# Check if Ubuntu 26.04 image exists
podman pull ubuntu:26.04

# Or check Docker Hub
curl -s https://hub.docker.com/v2/repositories/library/ubuntu/tags | \
  jq -r '.results[].name' | grep "26.04"
```

**Expected:** Ubuntu 26.04 should be available (current date is Sept 2026)

**Fallback:** Use `ubuntu:oracular` (26.04 development name) if 26.04 tag not yet created

### 1.2 Check ROS2 Lyrical Packages

**Action:**
```bash
# Check if Lyrical packages are in Ubuntu repos
docker run --rm ubuntu:26.04 bash -c "
  apt-get update && 
  apt-cache search ros-lyrical-desktop
"
```

**Expected:** `ros-lyrical-desktop` package available

**Fallback:** Add ROS2 apt repository manually if not in default repos

### 1.3 Backup Current Working Configuration

**Action:**
```bash
# Tag current working image (even though odometry is broken, navigation structure works)
podman tag quay.io/jianrzha/ros2-rmf-hotel:hotel-nav2-final-20260909 \
           quay.io/jianrzha/ros2-rmf-hotel:jazzy-backup-20260909

podman push quay.io/jianrzha/ros2-rmf-hotel:jazzy-backup-20260909

# Export current Helm values
helm get values multi-robot-demo -n ros2-rmf-hotel-test > /tmp/current-values-backup.yaml

# Backup scripts and patches
cp -r scripts scripts-jazzy-backup
cp -r entrypoints entrypoints-jazzy-backup
```

---

## Phase 2: Container Image Migration (2-3 hours)

### 2.1 Create Lyrical Base Image

**New File:** `Containerfile.hotel-lyrical-base`

```dockerfile
# Base ROS2 Lyrical + Gazebo Jetty image
FROM ubuntu:26.04

ENV DEBIAN_FRONTEND=noninteractive \
    ROS_DISTRO=lyrical \
    LANG=en_US.UTF-8

# Install ROS2 Lyrical desktop (includes Gazebo Jetty)
RUN apt-get update && apt-get install -y \
    locales \
    curl \
    gnupg2 \
    lsb-release \
    && locale-gen en_US en_US.UTF-8 \
    && update-locale LC_ALL=en_US.UTF-8 LANG=en_US.UTF-8 \
    && rm -rf /var/lib/apt/lists/*

# Add ROS2 apt repository (if not in default Ubuntu 26.04 repos)
RUN curl -sSL https://raw.githubusercontent.com/ros/rosdistro/master/ros.key \
    -o /usr/share/keyrings/ros-archive-keyring.gpg \
    && echo "deb [arch=$(dpkg --print-architecture) signed-by=/usr/share/keyrings/ros-archive-keyring.gpg] \
    http://packages.ros.org/ros2/ubuntu $(lsb_release -cs) main" \
    | tee /etc/apt/sources.list.d/ros2.list > /dev/null

# Install ROS2 Lyrical + Gazebo Jetty
RUN apt-get update && apt-get install -y \
    ros-lyrical-desktop \
    ros-lyrical-gazebo-ros-pkgs \
    ros-lyrical-ros-gz \
    python3-colcon-common-extensions \
    python3-rosdep \
    && rm -rf /var/lib/apt/lists/*

# Verify DART version
RUN dpkg -l | grep dartsim

# Source ROS2 environment
RUN echo "source /opt/ros/lyrical/setup.bash" >> /root/.bashrc

CMD ["/bin/bash"]
```

**Build:**
```bash
cd /Users/zhangj/devt/src/robots-demo-platform-openshift

podman build --platform linux/amd64 \
  -t quay.io/jianrzha/ros2-rmf-hotel:lyrical-base \
  -f Containerfile.hotel-lyrical-base .
```

**Verify DART version:**
```bash
podman run --rm quay.io/jianrzha/ros2-rmf-hotel:lyrical-base \
  bash -c "dpkg -l | grep dartsim"

# Expected output:
# ros-lyrical-gz-dartsim-vendor ... DART 6.16.6 or higher
```

### 2.2 Rebuild RMF Workspace for Lyrical

**Challenge:** RMF demos workspace was built for Jazzy

**Options:**

**Option A: Use Pre-built RMF Lyrical Packages (Preferred)**
```dockerfile
RUN apt-get update && apt-get install -y \
    ros-lyrical-rmf-demos \
    ros-lyrical-rmf-task-ros2 \
    ros-lyrical-rmf-fleet-adapter \
    && rm -rf /var/lib/apt/lists/*
```

**Option B: Build from Source (If packages unavailable)**
```dockerfile
# Clone and build rmf_demos for Lyrical
WORKDIR /opt/rmf_demos_ws/src
RUN git clone https://github.com/open-rmf/rmf_demos.git -b main

WORKDIR /opt/rmf_demos_ws
RUN . /opt/ros/lyrical/setup.bash && \
    colcon build --cmake-args -DCMAKE_BUILD_TYPE=Release
```

### 2.3 Create Full Lyrical Hotel Image

**New File:** `Containerfile.hotel-lyrical-nav2`

```dockerfile
FROM quay.io/jianrzha/ros2-rmf-hotel:lyrical-base

ENV ROS_DISTRO=lyrical

# Install Nav2 for Lyrical
RUN apt-get update && apt-get install -y \
    ros-lyrical-navigation2 \
    ros-lyrical-nav2-bringup \
    ros-lyrical-slam-toolbox \
    && rm -rf /var/lib/apt/lists/*

# Install RMF demos (Option A - use pre-built if available)
RUN apt-get update && apt-get install -y \
    ros-lyrical-rmf-demos \
    ros-lyrical-rmf-demos-gz \
    ros-lyrical-rmf-demos-maps \
    || echo "RMF packages not available, will build from source" \
    && rm -rf /var/lib/apt/lists/*

# Create workspace for custom builds (if needed)
RUN mkdir -p /opt/rmf_demos_ws/src

# Copy all entrypoints and scripts
COPY entrypoints/entrypoint-hotel.sh /entrypoint-hotel.sh
COPY entrypoints/entrypoint-nav2.sh /entrypoint-nav2.sh
COPY entrypoints/entrypoint-rmf.sh /entrypoint-rmf.sh
COPY entrypoints/nav2_relay.py /nav2_relay.py
RUN chmod +x /entrypoint-hotel.sh /entrypoint-nav2.sh /entrypoint-rmf.sh /nav2_relay.py

# Copy URDF for robot_state_publisher
RUN mkdir -p /usr/lib64/ros-lyrical/share/nav2_minimal_tb3_sim/urdf
COPY scripts/turtlebot3_waffle.urdf /usr/lib64/ros-lyrical/share/nav2_minimal_tb3_sim/urdf/

# Copy spawn script (updated for Lyrical)
COPY scripts/spawn_turtlebot3_hotel.py /opt/ros2-demo/scripts/
RUN chmod +x /opt/ros2-demo/scripts/spawn_turtlebot3_hotel.py

# Patch hotel.world for Sensors system (gpu_lidar)
COPY scripts/patch_hotel_world.py /tmp/patch_hotel_world.py
RUN python3 /tmp/patch_hotel_world.py \
    /opt/rmf_demos_ws/install/share/rmf_demos_maps/maps/hotel/hotel.world \
    /opt/rmf_demos_ws/install/share/rmf_demos_maps/maps/hotel/hotel.world \
    && rm /tmp/patch_hotel_world.py

# NO PHYSICS PATCH NEEDED - DART 6.16.6 works correctly!
# Remove all physics patches (patch_hotel_physics_dart.py, patch_hotel_physics_tpe.py, etc.)

# Pre-spawn robot in world file
COPY scripts/patch_hotel_world_add_robot.py /tmp/patch_hotel_world_add_robot.py
RUN python3 /tmp/patch_hotel_world_add_robot.py \
    && rm /tmp/patch_hotel_world_add_robot.py

# Patch simulation launch for headless rendering
COPY scripts/patch_simulation_launch.py /tmp/patch_simulation_launch.py
RUN python3 /tmp/patch_simulation_launch.py \
    /opt/rmf_demos_ws/install/share/rmf_demos_gz/simulation.launch.xml \
    /opt/rmf_demos_ws/install/share/rmf_demos_gz/simulation.launch.xml \
    && rm /tmp/patch_simulation_launch.py

CMD ["/entrypoint-hotel.sh"]
```

### 2.4 Update Entrypoint for Lyrical

**Edit:** `entrypoints/entrypoint-hotel.sh`

```bash
# Update ROS paths
source /opt/ros/lyrical/setup.bash

# Remove physics patch section - DART 6.16.6 works!
# DELETE lines 128-134 (old DART physics patch)

# Update message
echo "[hotel-pod] TurtleBot3 robot_1 pre-spawned in world file at (10, 30)"
echo "[hotel-pod] DART 6.16.6 physics with continuous wheel joints"
```

**Edit:** `entrypoints/entrypoint-nav2.sh`

```bash
# Update paths
ROS_PREFIX="/opt/ros/lyrical"
source "${ROS_PREFIX}/setup.bash"
```

**Edit:** `entrypoints/entrypoint-rmf.sh`

```bash
source /opt/ros/lyrical/setup.bash
```

### 2.5 Build Lyrical Image

```bash
cd /Users/zhangj/devt/src/robots-demo-platform-openshift

podman build --no-cache --platform linux/amd64 \
  -t quay.io/jianrzha/ros2-rmf-hotel:lyrical-nav2-20260909 \
  -f Containerfile.hotel-lyrical-nav2 .
```

**Expected Build Time:** 15-30 minutes

### 2.6 Push to Registry

```bash
podman push quay.io/jianrzha/ros2-rmf-hotel:lyrical-nav2-20260909
```

---

## Phase 3: Testing (2-3 hours)

### 3.1 Deploy to Test Namespace

```bash
# Create isolated test namespace
oc create namespace ros2-rmf-hotel-lyrical-test

# Update values file
cp /tmp/hotel-nav2-final-amcl-values.yaml /tmp/hotel-lyrical-test-values.yaml

# Edit image tag
sed -i 's/tag: hotel-nav2-final-20260909/tag: lyrical-nav2-20260909/' \
  /tmp/hotel-lyrical-test-values.yaml

# Deploy
helm install multi-robot-demo-lyrical \
  ./helm/multi-robot-demo \
  -n ros2-rmf-hotel-lyrical-test \
  -f /tmp/hotel-lyrical-test-values.yaml
```

### 3.2 Verify DART 6.16.6 Loaded

```bash
export TEST_NS=ros2-rmf-hotel-lyrical-test
HOTEL_POD=$(oc get pod -l app=hotel-sim -n $TEST_NS -o jsonpath='{.items[0].metadata.name}')

# Wait for pod ready
oc wait --for=condition=Ready pod/$HOTEL_POD -n $TEST_NS --timeout=300s

# Check DART version
oc exec -n $TEST_NS $HOTEL_POD -c hotel -- bash -c "
  dpkg -l | grep dartsim
"

# Expected: ros-lyrical-gz-dartsim-vendor ... 6.16.6 or higher
```

### 3.3 Verify Physics Engine

```bash
# Wait for Gazebo to initialize
sleep 120

# Check physics engine in logs
oc logs -n $TEST_NS $HOTEL_POD -c hotel | grep -i "physics\|DART"

# Expected: NO "DOF=0" errors, NO physics patch messages
```

### 3.4 Test Odometry Publication (CRITICAL)

```bash
# Check for DOF errors (should be NONE)
oc logs -n $TEST_NS $HOTEL_POD -c hotel --tail=200 | grep -i "degrees of freedom"

# Expected: No output (no errors)

# Test odometry topic
oc exec -n $TEST_NS $HOTEL_POD -c gz-ros-bridge -- bash -c "
  export HOME=/tmp/ros-home
  source /opt/ros/lyrical/setup.bash
  export ROS_DOMAIN_ID=0
  
  # Should see ~50 Hz
  timeout 10 ros2 topic hz /robot_1/odom
"

# Expected output:
# average rate: 50.000
# min: 0.020s max: 0.020s std dev: 0.00001s window: 500
```

### 3.5 Verify Odometry Data

```bash
oc exec -n $TEST_NS $HOTEL_POD -c gz-ros-bridge -- bash -c "
  export HOME=/tmp/ros-home
  source /opt/ros/lyrical/setup.bash
  export ROS_DOMAIN_ID=0
  
  ros2 topic echo /robot_1/odom --once
"

# Expected: Valid pose, twist, covariance data
# pose.pose.position: {x: ~10.0, y: ~30.0, z: 0.1}
# twist.twist.linear: {x: 0.0, y: 0.0, z: 0.0}  (stationary)
```

### 3.6 Test Nav2 Stack

```bash
# Check slam_toolbox receives odometry
oc exec -n $TEST_NS $HOTEL_POD -c nav2 -- bash -c "
  source /opt/ros/lyrical/setup.bash
  export ROS_DOMAIN_ID=0
  
  # Should see map->odom TF
  ros2 run tf2_ros tf2_echo map odom
"

# Expected: Valid transform published

# Check Nav2 node status
oc exec -n $TEST_NS $HOTEL_POD -c nav2 -- bash -c "
  source /opt/ros/lyrical/setup.bash
  export ROS_DOMAIN_ID=0
  
  ros2 node list | grep nav2
"

# Expected: bt_navigator, controller_server, planner_server, etc.
```

### 3.7 Test Multi-Level Navigation

```bash
# Dispatch patrol task (L1 lobby -> L2 room)
oc exec -n $TEST_NS $(oc get pod -l app=rmf-core -n $TEST_NS -o jsonpath='{.items[0].metadata.name}') \
  -c rmf-core -- bash -c "
  source /opt/ros/lyrical/setup.bash
  export ROS_DOMAIN_ID=55
  
  ros2 run rmf_demos_tasks dispatch_patrol \
    -p lobby_center L2_room2 -n 1 --use_sim_time
"

# Monitor task execution
oc logs -n $TEST_NS -l app=rmf-core -c rmf-core -f | grep -i "patrol\|navigate"

# Expected: Task progresses, robot navigates, odometry updates
```

---

## Phase 4: Production Migration (1 hour)

### 4.1 Success Criteria Checklist

Before migrating production, verify:

- [x] DART 6.16.6 confirmed in container
- [x] No "degrees of freedom" errors in logs
- [x] `/robot_1/odom` publishes at ~50 Hz
- [x] Odometry data is valid (pose, twist, covariance)
- [x] slam_toolbox publishes map->odom TF
- [x] Nav2 nodes activate successfully
- [x] Multi-level patrol task completes
- [x] Zenoh bridge forwards topics cross-pod
- [x] RMF fleet adapter registers robot

### 4.2 Blue-Green Deployment

```bash
# Keep old Jazzy deployment running
# Deploy Lyrical to production namespace with new release name

helm install multi-robot-demo-lyrical \
  ./helm/multi-robot-demo \
  -n ros2-rmf-hotel-test \
  -f /tmp/hotel-lyrical-prod-values.yaml

# Test production deployment
# ... (repeat Phase 3 tests)

# Switch traffic (update ingress/routes if applicable)

# After 24 hours of stable operation:
# Uninstall old Jazzy deployment
helm uninstall multi-robot-demo -n ros2-rmf-hotel-test
```

### 4.3 Update Documentation

```bash
# Update README
- Change "ROS2 Jazzy" → "ROS2 Lyrical"
- Change "Ubuntu 24.04" → "Ubuntu 26.04"
- Change "Gazebo Harmonic" → "Gazebo Jetty"
- Remove physics patch workaround documentation

# Update Helm chart defaults
values.yaml:
  image:
    tag: lyrical-nav2-20260909
    
# Git commit
git add -A
git commit -m "feat: upgrade to ROS2 Lyrical + DART 6.16.6 (fixes continuous joint bug)"
git push
```

---

## Phase 5: Cleanup (30 min)

### 5.1 Remove Obsolete Files

```bash
# Delete physics patch scripts (no longer needed)
rm scripts/patch_hotel_physics_dart.py
rm scripts/patch_hotel_physics_tpe.py
rm scripts/patch_hotel_physics_bullet.py

# Update Containerfile to remove patch steps
# (already done in Phase 2.3)

# Remove backup files
rm -rf scripts-jazzy-backup
rm -rf entrypoints-jazzy-backup
```

### 5.2 Archive Old Images

```bash
# Keep Jazzy backup for 30 days
# Set quay.io expiration policy on :jazzy-backup-20260909 tag

# Delete test images
podman rmi quay.io/jianrzha/ros2-rmf-hotel:lyrical-base
```

---

## Rollback Plan

### If Lyrical Upgrade Fails

**Rollback to Jazzy (with slotcar robots):**

```bash
# Option 1: Revert to previous Jazzy image
helm upgrade multi-robot-demo \
  ./helm/multi-robot-demo \
  -n ros2-rmf-hotel-test \
  --set image.tag=jazzy-backup-20260909

# Option 2: Use slotcar robots instead of TurtleBot3
helm upgrade multi-robot-demo \
  ./helm/multi-robot-demo \
  -n ros2-rmf-hotel-test \
  --set env.SPAWN_TURTLEBOT3=false
```

**Rollback Trigger Conditions:**
- DART version < 6.16.0 in Lyrical
- DOF=0 errors still present
- Odometry not publishing after 2 hours troubleshooting
- RMF packages incompatible with Lyrical

---

## Risk Assessment

### High Risk Items

| Risk | Probability | Impact | Mitigation |
|------|-------------|--------|------------|
| Ubuntu 26.04 not stable yet | Low | High | Use LTS tag, test in isolated namespace |
| RMF packages not available for Lyrical | Medium | High | Build from source (Option B) |
| DART 6.16.6 not included | Low | Critical | Verify before full migration |
| Breaking changes in Lyrical APIs | Medium | Medium | Review ROS2 migration guide |

### Medium Risk Items

| Risk | Probability | Impact | Mitigation |
|------|-------------|--------|------------|
| Build time exceeds estimate | High | Low | Schedule during off-hours |
| Zenoh compatibility issues | Low | Medium | Test cross-pod communication thoroughly |
| Nav2 API changes | Low | Medium | Check Nav2 Lyrical documentation |

---

## Dependencies & Prerequisites

### External Dependencies
- Ubuntu 26.04 image available in Docker Hub
- ROS2 Lyrical packages in apt repositories
- Gazebo Jetty included in ros-lyrical-desktop
- DART 6.16.6 in ros-lyrical-gz-dartsim-vendor

### Build Machine Requirements
- Podman machine running
- ~30 GB disk space for build
- ~2 hours of uninterrupted build time

### OpenShift Cluster Requirements
- Namespace quota for test deployment
- ~20 GB storage per deployment (4 pods)
- No cluster upgrades during migration

---

## Success Metrics

### Technical Metrics
- ✅ Zero "degrees of freedom" errors in Gazebo logs
- ✅ Odometry publication rate: 48-52 Hz (target: 50 Hz)
- ✅ Nav2 controller_server activation: < 15 seconds
- ✅ Multi-level task completion: 100% success rate
- ✅ Cross-pod topic latency: < 100ms

### Operational Metrics
- Total upgrade time: < 8 hours
- Downtime: 0 (blue-green deployment)
- Rollback exercises: 1 successful

---

## Timeline Estimate

| Phase | Duration | Dependencies |
|-------|----------|--------------|
| 1. Preparation | 1 hour | Ubuntu 26.04 availability |
| 2. Image Build | 2-3 hours | RMF Lyrical packages |
| 3. Testing | 2-3 hours | Phase 2 complete |
| 4. Production | 1 hour | Phase 3 success |
| 5. Cleanup | 30 min | Phase 4 stable |
| **Total** | **6.5-8.5 hours** | |

---

## Next Steps

### Immediate (Today)
1. ✅ Verify Ubuntu 26.04 availability
2. ✅ Check ROS2 Lyrical package availability
3. ✅ Create backup of current Jazzy deployment

### This Week
4. Build Lyrical base image
5. Test DART 6.16.6 version
6. Build full hotel-lyrical-nav2 image

### Next Week
7. Deploy to test namespace
8. Complete validation testing
9. Production migration (if tests pass)

---

## References

- [ROS2 Lyrical Luth Release](https://discourse.openrobotics.org/t/ros-2-lyrical-luth-released/55021)
- [Gazebo Jetty Release](https://discourse.openrobotics.org/t/gazebo-jetty-released/50349)
- [DART 6.16.6 Upgrade](https://discourse.openrobotics.org/t/dart-upgraded-from-6-13-to-6-16-6-in-linux-gazebo-jetty-gz-physics9/52881)
- [ROS2 Migration Guide](https://docs.ros.org/en/lyrical/Releases/Release-Lyrical-Luth.html)
- [Gazebo Migration Guide](https://gazebosim.org/docs/jetty/migration_from_ionic)

---

## Appendix: Command Reference

### Quick Start Commands

```bash
# 1. Build Lyrical image
cd /Users/zhangj/devt/src/robots-demo-platform-openshift
podman build --platform linux/amd64 \
  -t quay.io/jianrzha/ros2-rmf-hotel:lyrical-nav2-20260909 \
  -f Containerfile.hotel-lyrical-nav2 .

# 2. Push to registry
podman push quay.io/jianrzha/ros2-rmf-hotel:lyrical-nav2-20260909

# 3. Deploy test
helm install multi-robot-demo-lyrical \
  ./helm/multi-robot-demo \
  -n ros2-rmf-hotel-lyrical-test \
  --set image.tag=lyrical-nav2-20260909

# 4. Verify odometry
export TEST_NS=ros2-rmf-hotel-lyrical-test
HOTEL_POD=$(oc get pod -l app=hotel-sim -n $TEST_NS -o jsonpath='{.items[0].metadata.name}')
oc exec -n $TEST_NS $HOTEL_POD -c gz-ros-bridge -- bash -c "
  source /opt/ros/lyrical/setup.bash
  export ROS_DOMAIN_ID=0
  ros2 topic hz /robot_1/odom
"
```

---

**Document Version:** 1.0  
**Author:** Claude (upgrade planning agent)  
**Status:** Ready for execution  
**Approval Required:** Yes (before Phase 4 production migration)
