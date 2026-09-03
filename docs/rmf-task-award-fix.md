# RMF Task Award Fix - Using Official rmf_demos Configuration

## Problem

Tasks were submitted successfully and bids were received, but the RMF dispatcher never awarded tasks to robots. The bidding process would complete but tasks remained in "queued" state indefinitely with `is_assigned: false`.

## Investigation

Compared our implementation with the working `rmf-ros2-hotel-world-demon` branch:

1. **Demon branch uses official rmf_demos launch files** - `ros2 launch rmf_demos_gz hotel.launch.xml`
2. **Puppet controller proves task assignment works** - The controller monitors `/dispatch_states` and processes tasks when they reach status 2 (selected) or 3 (dispatched), proving the dispatcher IS awarding tasks on that branch
3. **Different parameter passing method** - The official launch files use ROS parameters, not command-line flags

## Root Cause

Our manual component launch was **missing critical ROS parameters** that control the dispatcher's bidding and task assignment behavior:

### What We Were Doing (WRONG)

```bash
# Command-line flag approach
ros2 run rmf_task_ros2 rmf_task_dispatcher -s "${SERVER_URI}" \
  --ros-args -p use_sim_time:=true --log-level rmf_task_ros2:=DEBUG
```

**Issues:**
- Using `-s` flag for server_uri
- Missing `bidding_time_window` parameter
- Missing `use_unique_hex_string_with_task_id` parameter
- Parameters not passed as ROS params

### What rmf_demos Does (CORRECT)

From `rmf_demos/launch/common.launch.xml` line 57-62:

```xml
<node pkg="rmf_task_ros2" exec="rmf_task_dispatcher" output="screen">
  <param name="use_sim_time" value="$(var use_sim_time)"/>
  <param name="bidding_time_window" value="$(var bidding_time_window)"/>
  <param name="use_unique_hex_string_with_task_id" value="$(var use_unique_hex_string_with_task_id)"/>
  <param name="server_uri" value="$(var server_uri)"/>
</node>
```

**Default values:**
- `bidding_time_window: 2.0` seconds
- `use_unique_hex_string_with_task_id: true`
- `server_uri: ""` (empty string for standalone mode)

## Solution

Updated `entrypoint-rmf-free-fleet-multi-level.sh` to use **ROS parameters** matching the official rmf_demos configuration:

### Dispatcher Fix

```bash
ros2 run rmf_task_ros2 rmf_task_dispatcher \
  --ros-args \
  -p use_sim_time:=true \
  -p bidding_time_window:=2.0 \
  -p use_unique_hex_string_with_task_id:=true \
  -p server_uri:="${SERVER_URI:-}" \
  --log-level rmf_task_ros2:=DEBUG
```

### Fleet Adapter Fix

Also added `server_uri` parameter to fleet adapter to match rmf_demos configuration:

```bash
ros2 run free_fleet_adapter fleet_adapter.py \
  -c /opt/free_fleet_config/tinybot_fleet_config.yaml \
  -n ${NAV_GRAPH} \
  -sim \
  -s "${SERVER_URI}" \
  --zenoh-config "${ZENOH_CONFIG}" \
  --ros-args -p use_sim_time:=true
```

## Key Insights

1. **ROS parameters vs command-line flags matter** - The dispatcher expects configuration via ROS parameters, not just command-line arguments
2. **Missing parameters break bidding logic** - Without `bidding_time_window` and `use_unique_hex_string_with_task_id`, the dispatcher may not complete the bidding process
3. **Official launch files are the source of truth** - Even when using custom architectures (Free Fleet instead of rmf_demos fleet adapters), the core RMF components (dispatcher, traffic schedule) need the same parameter configuration
4. **Puppet controller was a workaround for execution, not assignment** - The demon branch's puppet controller bypasses C++ EasyFullControl crashes during task **execution**, not during task **assignment**

## Expected Outcome

With this fix:
1. ✅ Dispatcher receives proper ROS parameters
2. ✅ Bidding window completes correctly (2.0 seconds)
3. ✅ Tasks get awarded to robots (`is_assigned: true`)
4. ✅ `dispatch_request` messages published
5. ✅ Robots receive task assignments and begin execution

## Testing

```bash
# Deploy updated configuration
make deploy-multilevel

# Wait for robots to register
kubectl logs -f deployment/rmf-core -n ros2-multi-robot-demo

# Submit patrol task
kubectl exec -it deployment/rmf-core -n ros2-multi-robot-demo -- bash
ros2 topic pub --once /task_api_requests rmf_task_msgs/msg/ApiRequest ...

# Monitor task state
ros2 topic echo /dispatch_states
# Should show: is_assigned: true (instead of false)
```

## Files Modified

1. **entrypoints/entrypoint-rmf-free-fleet-multi-level.sh**
   - Added `bidding_time_window:=2.0` parameter to dispatcher
   - Added `use_unique_hex_string_with_task_id:=true` parameter to dispatcher
   - Changed `server_uri` from `-s` flag to ROS parameter
   - Added `server_uri` parameter to fleet adapter

## References

- `rmf_demos/launch/common.launch.xml` - Official dispatcher configuration
- `rmf_demos_fleet_adapter/launch/fleet_adapter.launch.xml` - Official fleet adapter configuration
- `rmf-ros2-hotel-world-demon` branch - Working hotel demo proving task assignment works
- GitHub: [open-rmf/rmf_demos](https://github.com/open-rmf/rmf_demos) - Upstream source

## Alternative Approach Considered

We considered switching to use `hotel.launch.xml` directly, but this would require:
- Rebuilding containers on Ubuntu (current: Fedora)
- Building rmf_demos from source
- Losing Free Fleet integration
- Losing multi-pod Zenoh federation architecture

By extracting the correct parameters from rmf_demos and applying them to our Free Fleet setup, we get the best of both worlds: proven RMF configuration + custom multi-level Free Fleet architecture.
