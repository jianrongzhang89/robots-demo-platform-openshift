# Multi-Floor Robot Transit Demo

This directory contains demo scripts for autonomous multi-floor robot transit using Open-RMF and elevator coordination.

## Demos Available

### 1. Single-Pod Demo (ros2-rmf-hotel)
**File:** `demo_l1_to_l3_auto.py`  
**Namespace:** `ros2-rmf-hotel`  
**Architecture:** Single-pod deployment  
**Robot:** tinyBot_1  

### 2. Zenoh-Federated Demo (ros2-rmf-hotel-federated)
**File:** `demo_federated_tinybot.py`  
**Namespace:** `ros2-rmf-hotel-federated`  
**Architecture:** Multi-pod with Zenoh router  
**Robot:** tinyBot_1  

## Prerequisites

- OpenShift cluster access
- Running hotel demo deployment in target namespace
- `oc` CLI configured and logged in
- Robot battery > 50% (restart pod if needed)

## Running the Single-Pod Demo

### Step 1: Check Pod Status

```bash
# Get the hotel-sim pod name
POD=$(oc get pods -l app=hotel-sim -n ros2-rmf-hotel --field-selector=status.phase=Running -o jsonpath='{.items[0].metadata.name}')
echo "Pod: $POD"
```

### Step 2: Check Robot Status

```bash
oc exec $POD -c hotel -n ros2-rmf-hotel -- bash -c "
export HOME=/tmp
source /opt/ros/jazzy/setup.bash
source /opt/rmf_demos_ws/install/setup.bash

ros2 topic echo /fleet_states --once 2>&1 | grep -A 20 'tinyBot_1'
"
```

**Important:** If battery is 0%, restart the pod:
```bash
oc delete pod $POD -n ros2-rmf-hotel
# Wait 3-4 minutes for new pod to start
```

### Step 3: Copy Demo Script to Pod

```bash
POD=$(oc get pods -l app=hotel-sim -n ros2-rmf-hotel --field-selector=status.phase=Running -o jsonpath='{.items[0].metadata.name}')

oc cp demo_l1_to_l3_auto.py $POD:/tmp/ -c hotel -n ros2-rmf-hotel
```

### Step 4: Run Demo

```bash
oc exec $POD -c hotel -n ros2-rmf-hotel -- bash -c "
export HOME=/tmp
export ROS_LOG_DIR=/tmp/ros_logs
source /opt/ros/jazzy/setup.bash
source /opt/rmf_demos_ws/install/setup.bash

python3 /tmp/demo_l1_to_l3_auto.py
"
```

### Step 5: Watch in Browser (Optional)

Open the noVNC visualization:
```
https://hotel-novnc-ros2-rmf-hotel.apps.ai-dev02.kni.syseng.devcluster.openshift.com
```

## Running the Federated Demo

### Step 1: Check Pod Status

```bash
# Get the gazebo-sim pod name
POD=$(oc get pods -l app=gazebo-sim -n ros2-rmf-hotel-federated --field-selector=status.phase=Running -o jsonpath='{.items[0].metadata.name}')
echo "Pod: $POD"
```

### Step 2: Check Robot Status

```bash
oc exec $POD -c gazebo -n ros2-rmf-hotel-federated -- bash -c "
export HOME=/tmp
source /opt/ros/jazzy/setup.bash

ros2 topic echo /fleet_states --once 2>&1 | grep -A 20 'tinyBot_1'
"
```

**Important:** If battery is 0%, restart the pod:
```bash
oc delete pod $POD -n ros2-rmf-hotel-federated
# Wait 3-4 minutes for new pod to start
```

### Step 3: Copy Demo Script to Pod

```bash
POD=$(oc get pods -l app=gazebo-sim -n ros2-rmf-hotel-federated --field-selector=status.phase=Running -o jsonpath='{.items[0].metadata.name}')

oc cp demo_federated_tinybot.py $POD:/tmp/ -c gazebo -n ros2-rmf-hotel-federated
```

### Step 4: Run Demo

```bash
oc exec $POD -c gazebo -n ros2-rmf-hotel-federated -- bash -c "
export HOME=/tmp
source /opt/ros/jazzy/setup.bash

python3 /tmp/demo_federated_tinybot.py
"
```

### Step 5: Watch in Browser (Optional)

Open the noVNC visualization:
```
https://ros2-multi-robot-novnc-ros2-rmf-hotel-federated.apps.ai-dev02.kni.syseng.devcluster.openshift.com
```

## Expected Results

### Successful Demo Output

```
======================================================================
🎬 DEMO STARTED: L1 → L3 MULTI-FLOOR TRANSIT
======================================================================
Task ID: L1_TO_L3_RECORDING_...
Robot: tinyBot_1
Route: L1 → L3 (via Elevator)

📹 RECORDING IN PROGRESS...
----------------------------------------------------------------------
[15s] Floor: L1, Position: (22.7, -30.4)
[30s] Floor: L1, Position: (17.5, -31.3)
...
[110s] 🛗 FLOOR CHANGE: L1 → L3
[110s] ✅ ARRIVED ON L3!
       Position: (16.98, -24.21)
       Battery: 96.0%

✅ DEMO COMPLETE - TOTAL TIME: 110 seconds
======================================================================
```

### Performance Metrics

- **Transit Time:** 102-116 seconds (average: ~110s)
- **Battery Usage:** 2-5% per transit
- **Success Rate:** 80%+ (verified over multiple tests)
- **Route:** L1 → L3 (2-floor ascent via Lift1)

## Troubleshooting

### Robot Won't Move

**Symptom:** Robot stays on same floor, no movement

**Causes:**
1. **Battery at 0%** - Restart pod to reset to 100%
2. **Stuck task** - Previous task still queued
3. **Fleet adapter crashed** - Check pod logs

**Solutions:**
```bash
# Check battery
oc exec $POD -c <container> -n <namespace> -- bash -c "
source /opt/ros/jazzy/setup.bash
ros2 topic echo /fleet_states --once | grep battery_percent
"

# If 0%, restart pod
oc delete pod $POD -n <namespace>
```

### Task Accepted but No Movement

**Symptom:** Task shows "queued" but robot doesn't move

**Solution:** Wait longer (timeout may need to be extended) or restart pod

### Floor Change Timeout

**Symptom:** Robot moves but doesn't reach L3 in 180 seconds

**Solution:** Extend timeout in demo script (already has 60s extension built-in)

## Demo Variations

### L3 → L1 Descent Demo

Modify the demo script to go from L3 to L1:

```python
# Change target place
"places": ["L1_door2"]  # Instead of L3_room1
```

### Different Floors

- **L1 → L2:** Change `"places": ["L2_room1"]`
- **L2 → L3:** Change `"places": ["L3_room1"]`
- **L3 → L1:** Change `"places": ["L1_door2"]`

## Architecture Comparison

| Aspect | Single-Pod | Federated |
|--------|-----------|-----------|
| Namespace | ros2-rmf-hotel | ros2-rmf-hotel-federated |
| Pods | 1 (hotel-sim) | Multiple (gazebo-sim, rmf-core, etc.) |
| Communication | ROS2 DDS (local) | Zenoh Router (cross-pod) |
| Container | `hotel` | `gazebo` |
| Complexity | Simple | Advanced |
| Use Case | Demo/Testing | Production/Scale |

## Related Documentation

- [Multi-Floor Transit Test Results](../../docs/multi-floor-transit-test-results.md)
- [Multi-Floor Transit Implementation](../../docs/MULTI-FLOOR-TRANSIT-COMPLETE.md)
- [Nav2 Integration Guide](../../docs/nav2-integration-guide.md)

## Acknowledgments

- Open-RMF (Robot Middleware Framework)
- ROS2 Jazzy
- Gazebo Harmonic
- Zenoh (for federated demo)

---

**Last Updated:** 2026-08-26  
**Status:** ✅ Tested and Working  
**Success Rate:** 80%+ over multiple test runs
