# Hotel + Nav2 Deployment Guide

**Status:** Ready for deployment  
**Target:** ros2-rmf-hotel namespace  
**Date:** 2026-09-04

---

## Prerequisites Check

Before deploying, verify:

- [ ] OpenShift CLI (`oc`) installed and authenticated
- [ ] Access to ros2-rmf-hotel namespace
- [ ] BuildConfig `hotel-image-build` exists
- [ ] Quay.io push access configured

**Check authentication:**
```bash
oc whoami
oc project ros2-rmf-hotel 2>/dev/null || oc new-project ros2-rmf-hotel
```

---

## Step 1: Build New Hotel Image

The hotel image needs rebuilding to include:
- TurtleBot3 spawn script
- Updated entrypoint with spawn logic

### Start Build

```bash
cd /Users/zhangj/devt/src/robots-demo-platform-openshift

# Start build from current directory
oc start-build hotel-image-build --from-dir=. -n ros2-rmf-hotel --follow
```

**Expected duration:** ~20-25 minutes

**What to watch for:**
- Stage A: rmf_ros2 workspace build (~10 min)
- Stage B: rmf_demos workspace build (~8 min)
- Patch scripts execution
- Final image push to quay.io

**Success indicator:**
```
Push successful
```

### Verify Build

```bash
# Check build status
oc get builds -n ros2-rmf-hotel | grep hotel-image-build

# Get image reference
oc get build hotel-image-build-<N> -n ros2-rmf-hotel -o jsonpath='{.status.outputDockerImageReference}'
```

**Expected:** `quay.io/jianrzha/ros2-rmf-hotel:latest`

---

## Step 2: Deploy Hybrid Architecture

### Pre-Deployment Check

Verify configuration files are in place:

```bash
# Check nav graph
ls -la helm/multi-robot-demo/files/nav_graph.yaml

# Check fleet config
ls -la helm/multi-robot-demo/files/fleet_config.yaml

# Check map files
ls -la maps/hotel_L*.{pgm,yaml}

# Check values file
ls -la helm/multi-robot-demo/values-hotel-nav2.yaml
```

### Deploy

```bash
# From repository root
helm upgrade --install multi-robot-demo ./helm/multi-robot-demo \
  -f helm/multi-robot-demo/values.yaml \
  -f helm/multi-robot-demo/values-hotel-nav2.yaml \
  -n ros2-rmf-hotel \
  --create-namespace \
  --wait \
  --timeout 10m
```

**Expected output:**
```
Release "multi-robot-demo" has been upgraded. Happy Helming!
```

### Verify Deployment

```bash
# Check all pods
oc get pods -n ros2-rmf-hotel

# Expected pods:
# hotel-sim-<hash>         (1/1 or 2/2 if Zenoh sidecar)
# zenoh-router-<hash>      (1/1)
# robot-nav-robot-1-<hash> (2/2)
# rmf-core-<hash>          (2/2)
```

**Wait for all pods to be Running:**
```bash
watch oc get pods -n ros2-rmf-hotel
```

---

## Step 3: Verify Infrastructure

### 3.1 Check Hotel Pod

```bash
HOTEL_POD=$(oc get pod -n ros2-rmf-hotel -l app=hotel-sim -o jsonpath='{.items[0].metadata.name}')
echo "Hotel pod: $HOTEL_POD"

# Check logs
oc logs -n ros2-rmf-hotel $HOTEL_POD -c hotel --tail=50
```

**Look for:**
```
[hotel-pod] Launching Open-RMF hotel demo
[hotel-pod] TurtleBot3 spawning enabled
[spawn-tb3] Spawning robot_1 at (10.0, 30.0, yaw=0.0)
[spawn-tb3] ✓ robot_1 spawn complete
```

**If Zenoh bridge sidecar exists:**
```bash
oc logs -n ros2-rmf-hotel $HOTEL_POD -c zenoh-bridge-gazebo --tail=20
```

### 3.2 Check Zenoh Router

```bash
ZENOH_POD=$(oc get pod -n ros2-rmf-hotel -l app=zenoh-router -o jsonpath='{.items[0].metadata.name}')
echo "Zenoh router pod: $ZENOH_POD"

oc logs -n ros2-rmf-hotel $ZENOH_POD --tail=20
```

**Look for:**
```
Zenoh router listening on tcp/0.0.0.0:7447
```

### 3.3 Check Nav2 Pod

```bash
NAV2_POD=$(oc get pod -n ros2-rmf-hotel -l app=robot-nav-robot-1 -o jsonpath='{.items[0].metadata.name}')
echo "Nav2 pod: $NAV2_POD"

# Check nav2 container
oc logs -n ros2-rmf-hotel $NAV2_POD -c nav2 --tail=50
```

**Look for:**
```
[tinybot_nav2_launch] TinyBot Nav2 Launch Configuration
Multi-level navigation ENABLED
  Initial level: L1
  Available levels: ['L1', 'L2', 'L3']
Configured map_server_L1: active
Configured map_server_L2: inactive
Configured map_server_L3: inactive
```

### 3.4 Check RMF Core Pod

```bash
RMF_POD=$(oc get pod -n ros2-rmf-hotel -l app=rmf-core -o jsonpath='{.items[0].metadata.name}')
echo "RMF core pod: $RMF_POD"

oc logs -n ros2-rmf-hotel $RMF_POD -c rmf-core --tail=50
```

**Look for:**
```
[free_fleet_adapter] Starting fleet adapter for turtlebot3
[free_fleet_adapter] Multi-level navigation enabled for [robot_1]
```

---

## Step 4: Verify TurtleBot3 Spawn

### Access noVNC

```bash
# Get route
oc get route -n ros2-rmf-hotel hotel-novnc -o jsonpath='{.spec.host}'
```

Open in browser: `https://<route-host>`

**Visual verification:**
- [ ] Hotel world visible
- [ ] TurtleBot3 robot visible (blue/black robot)
- [ ] Robot at approximately (10, 30) - lobby west area
- [ ] LiDAR sensor visible on robot
- [ ] NO slotcar robots (DeliveryRobot, TinyRobot, CleanerBot)

**Alternative CLI verification:**
```bash
# Check Gazebo models
oc exec -n ros2-rmf-hotel $HOTEL_POD -c hotel -- \
  bash -c "source /opt/ros/jazzy/setup.bash && gz model -l -w hotel"
```

**Expected output should include:**
```
robot_1
```

---

## Step 5: Test Nav2 Localization

### Check AMCL

```bash
# Monitor AMCL pose
oc exec -n ros2-rmf-hotel $NAV2_POD -c nav2 -- \
  bash -c "source /opt/ros/jazzy/setup.bash && \
           ros2 topic echo /robot_1/amcl_pose --once"
```

**Expected:**
- Position near (10.0, 30.0)
- Valid covariance (not all zeros)

### Check TF Tree

```bash
oc exec -n ros2-rmf-hotel $NAV2_POD -c nav2 -- \
  bash -c "source /opt/ros/jazzy/setup.bash && \
           ros2 run tf2_ros tf2_echo map robot_1/base_footprint"
```

**Expected:**
```
Translation: [10.xxx, 30.xxx, 0.xxx]
Rotation: ...
```

### Check Map Server

```bash
# Verify map_server_L1 is active
oc exec -n ros2-rmf-hotel $NAV2_POD -c nav2 -- \
  bash -c "source /opt/ros/jazzy/setup.bash && \
           ros2 lifecycle get /robot_1/map_server_L1"
```

**Expected:** `active [3]`

```bash
# Verify L2, L3 are inactive
oc exec -n ros2-rmf-hotel $NAV2_POD -c nav2 -- \
  bash -c "source /opt/ros/jazzy/setup.bash && \
           ros2 lifecycle get /robot_1/map_server_L2"
```

**Expected:** `inactive [2]`

---

## Step 6: Test Free Fleet Registration

### Check Fleet States

```bash
oc exec -n ros2-rmf-hotel $RMF_POD -c rmf-core -- \
  bash -c "source /opt/ros/jazzy/setup.bash && \
           source /opt/rmf_ros2_ws/install/setup.bash && \
           ros2 topic echo /fleet_states --once"
```

**Expected:**
```yaml
name: turtlebot3
robots:
  - name: robot_1
    location:
      level_name: L1
      x: ~10.0
      y: ~30.0
```

### Check Task Dispatcher

```bash
oc exec -n ros2-rmf-hotel $RMF_POD -c rmf-core -- \
  bash -c "source /opt/ros/jazzy/setup.bash && \
           source /opt/rmf_ros2_ws/install/setup.bash && \
           ros2 topic list | grep dispatch"
```

**Expected:**
```
/dispatch_states
/task_summaries
```

---

## Step 7: Test Single-Level Navigation

### Submit Simple Patrol Task

```bash
oc exec -n ros2-rmf-hotel $RMF_POD -c rmf-core -- \
  bash -c "source /opt/ros/jazzy/setup.bash && \
           source /opt/rmf_ros2_ws/install/setup.bash && \
           ros2 run rmf_demos_tasks dispatch_patrol \
             -F turtlebot3 -R robot_1 \
             -p lobby_west lobby_east -n 1 \
             --use_sim_time"
```

**Expected output:**
```
Dispatcher connected
Submitted task: ...
Task ID: ...
```

### Monitor Task Execution

```bash
# Watch dispatch states
oc exec -n ros2-rmf-hotel $RMF_POD -c rmf-core -- \
  bash -c "source /opt/ros/jazzy/setup.bash && \
           source /opt/rmf_ros2_ws/install/setup.bash && \
           ros2 topic echo /dispatch_states"
```

**Look for:**
- Task state: assigned
- Fleet: turtlebot3
- Robot: robot_1

### Monitor Robot Movement

In noVNC, watch the robot:
- [ ] Robot starts moving
- [ ] Path appears in RViz (if visible)
- [ ] Robot navigates from lobby_west to lobby_east
- [ ] Task completes

---

## Step 8: Test Multi-Level Navigation

### Submit Cross-Level Task

```bash
oc exec -n ros2-rmf-hotel $RMF_POD -c rmf-core -- \
  bash -c "source /opt/ros/jazzy/setup.bash && \
           source /opt/rmf_ros2_ws/install/setup.bash && \
           ros2 run rmf_demos_tasks dispatch_patrol \
             -F turtlebot3 -R robot_1 \
             -p lobby_center L2_center -n 1 \
             --use_sim_time"
```

### Monitor Map Switching

```bash
# Watch Free Fleet adapter logs
oc logs -n ros2-rmf-hotel $RMF_POD -c rmf-core -f | grep -E "Cross-level|switch|transition"
```

**Look for:**
```
Cross-level navigation: L1 → L2
Will use Lift1 for level transition
Starting level transition: L1 → L2 via Lift1
Step 1/8: Waiting for Lift1 arrival at L1...
[STUB] Waiting for Lift1 arrival at L1
Step 2/8: Waiting for Lift1 doors to open...
...
Step 6/8: Switching map to L2...
Switching map: L1 → L2
Successfully switched to map [L2]
Step 7/8: Reinitializing AMCL at lift exit...
Reinitialized AMCL at (57.50, 27.50, 180.0°) on map [L2]
...
Level transition complete: L1 → L2
```

### Verify Map Switch

```bash
# Check current map server states
oc exec -n ros2-rmf-hotel $NAV2_POD -c nav2 -- \
  bash -c "source /opt/ros/jazzy/setup.bash && \
           ros2 lifecycle get /robot_1/map_server_L1"
```

**Expected:** `inactive [2]` (was active)

```bash
oc exec -n ros2-rmf-hotel $NAV2_POD -c nav2 -- \
  bash -c "source /opt/ros/jazzy/setup.bash && \
           ros2 lifecycle get /robot_1/map_server_L2"
```

**Expected:** `active [3]` (was inactive)

---

## Troubleshooting

### Issue: Hotel pod not starting

**Check:**
```bash
oc describe pod -n ros2-rmf-hotel $HOTEL_POD
oc logs -n ros2-rmf-hotel $HOTEL_POD -c hotel
```

**Common causes:**
- Image not available
- Resource limits too low
- Volume mounts missing

### Issue: TurtleBot3 not spawning

**Check:**
```bash
oc logs -n ros2-rmf-hotel $HOTEL_POD -c hotel | grep -A 10 "TurtleBot3"
```

**Verify:**
- SPAWN_TURTLEBOT3=true in pod env
- Spawn script copied to image
- Gazebo world name is "hotel"

**Manual spawn test:**
```bash
oc exec -n ros2-rmf-hotel $HOTEL_POD -c hotel -- \
  python3 /opt/ros2-demo/scripts/spawn_turtlebot3_hotel.py \
    --name robot_1 --x 10.0 --y 30.0 --yaw 0.0
```

### Issue: Nav2 not starting

**Check:**
```bash
oc logs -n ros2-rmf-hotel $NAV2_POD -c nav2
```

**Common causes:**
- Map files missing
- ENABLE_MULTILEVEL not set
- AMCL localization failure

### Issue: Free Fleet not registering robot

**Check:**
```bash
oc logs -n ros2-rmf-hotel $RMF_POD -c rmf-core | grep robot_1
```

**Verify:**
- Zenoh connections established
- Fleet config has robot_1 definition
- Nav graph loaded correctly

### Issue: Map switching not working

**Check adapter logs:**
```bash
oc logs -n ros2-rmf-hotel $RMF_POD -c rmf-core -f
```

**Verify:**
- level_maps populated in adapter
- Lifecycle service clients created
- Map files exist for all levels

---

## Success Criteria

### Minimum Success (Single-Level)

- [ ] All pods running (4 total)
- [ ] TurtleBot3 visible in hotel world
- [ ] AMCL localization working
- [ ] Robot registered to Free Fleet
- [ ] Single-level navigation completes

### Full Success (Multi-Level)

- [ ] Cross-level task accepted
- [ ] Map switching executes (L1 → L2)
- [ ] Lifecycle transitions successful
- [ ] AMCL reinitializes on new map
- [ ] Robot completes navigation on L2

---

## Rollback

If deployment fails:

```bash
# Revert to original hotel demo
helm upgrade --install multi-robot-demo ./helm/multi-robot-demo \
  -f helm/multi-robot-demo/values.yaml \
  -f helm/multi-robot-demo/values-hotel.yaml \
  -n ros2-rmf-hotel
```

Or delete and redeploy:

```bash
helm uninstall multi-robot-demo -n ros2-rmf-hotel
# Wait for cleanup
# Redeploy from scratch
```

---

## Next Steps After Success

1. **Add lift integration** - Replace stub methods with real rmf_lift_msgs
2. **Test with multiple robots** - Expand to 2+ robots
3. **Performance tuning** - Adjust timeouts, thresholds
4. **Documentation** - Record test results, known issues

---

**Last Updated:** 2026-09-04  
**Status:** Ready for deployment
