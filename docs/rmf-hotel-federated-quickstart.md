# RMF Hotel Federated Demo - Quick Start

## TL;DR

```bash
# Deploy
helm upgrade --install multi-robot-demo helm/multi-robot-demo \
  --namespace ros2-rmf-hotel-federated \
  --create-namespace \
  -f helm/multi-robot-demo/values.yaml \
  -f helm/multi-robot-demo/values-hotel-federated.yaml

# Wait for pods (takes ~2 minutes)
oc get pods -n ros2-rmf-hotel-federated -w

# View in browser
https://ros2-multi-robot-novnc-ros2-rmf-hotel-federated.apps.ai-dev02.kni.syseng.devcluster.openshift.com
```

## What You'll See

- **Multi-level hotel building** (3 floors with lifts and doors)
- **4 autonomous robots** continuously patrolling:
  - `deliveryBot_1` (red/orange delivery robot)
  - `tinyBot_1` (small blue robot)
  - `cleanerBotA_1` (green cleaning robot)
  - `cleanerBotA_2` (green cleaning robot)

## Architecture at a Glance

```
7 Pods Total:
├─ 1x Gazebo (hotel world + 4 slotcar robots)
├─ 1x RMF (fleet management + clock relay)
├─ 4x Nav2 (TurtleBot3 robots - separate pods)
└─ 1x Zenoh Router (federation hub)
```

## Verify It's Working

```bash
# Check all pods running (should see 7 Running)
oc get pods -n ros2-rmf-hotel-federated

# Check patrol is active
GAZEBO_POD=$(oc get pod -n ros2-rmf-hotel-federated -l app=gazebo-sim --no-headers | awk '{print $1}')
oc exec -n ros2-rmf-hotel-federated $GAZEBO_POD -c gazebo -- tail -20 /tmp/patrol.log

# You should see:
# Cycle X: del(...) | tin(...) | cle(...) | cle(...)
#   [deliveryBot_1] -> (...) ✓
#   [tinyBot_1] -> (...) ✓
#   ...
```

## Camera Controls in noVNC

- **Left mouse**: Rotate camera
- **Middle mouse**: Pan view
- **Right mouse**: Zoom in/out
- **Home key**: Reset camera

## Common Issues

### Can't see robots?

1. Refresh browser page
2. Adjust camera - robots are in the lobby (Level 1)
3. Wait 30 seconds and watch for movement

### Patrol stopped?

```bash
# Restart patrol
oc exec -n ros2-rmf-hotel-federated $GAZEBO_POD -c gazebo -- \
  bash -c "nohup python3 /scripts/hotel_patrol_loop.py > /tmp/patrol.log 2>&1 &"
```

### Black screen in noVNC?

Wait 2-3 minutes for Gazebo GUI to fully load. The hotel world is large and takes time to render.

## Clean Up

```bash
# Delete deployment
helm uninstall multi-robot-demo -n ros2-rmf-hotel-federated

# Delete namespace
oc delete namespace ros2-rmf-hotel-federated
```

## Learn More

See [rmf-hotel-federated-demo.md](./rmf-hotel-federated-demo.md) for full documentation.
