# building_map_generator Attempt (Option A)

## Objective

Try using RMF's `building_map_generator` tool to auto-generate navigation graphs from building.yaml, following the rmf_demos approach.

## Background

Research showed that rmf_demos hotel world uses:
- `building_map_generator nav hotel.building.yaml output_dir/`
- Auto-generates lift_lanes from `lift_cabin` waypoint properties
- Eliminates manual lift_lanes specification

## Attempt

### Step 1: Check Tool Availability

```bash
$ ros2 pkg executables rmf_building_map_tools
rmf_building_map_tools building_map_generator  ✓
```

**Result:** Tool is available in the container

### Step 2: Generate Nav Graph

```bash
$ ros2 run rmf_building_map_tools building_map_generator nav \
    /opt/hotel_config/hotel.building.yaml /tmp/generated_nav/
```

**Output:**
```
building name: hotel
coordinate system: reference_image
parsing level L1
parsing level L2
parsing level L3
calculating levels relative to L1
WARNING! No measurements defined. Scale is indetermined.
         Nav graph generated in pixel units, not meters!
```

**Result:** ❌ **No files generated**

### Step 3: Root Cause Analysis

**Problem:** `building_map_generator` requires building files created with **traffic_editor** GUI, which includes:

1. **Drawing images** for each level
   ```yaml
   levels:
     L1:
       elevation: 0
       drawing:
         filename: L1.png  # Required!
   ```

2. **Fiducials** for coordinate alignment
   ```
   calculating level L2 offset and scale...
     0 common fiducials:  # None found
   ```

3. **Image-based vertex placement**
   - Vertices placed on PNG/SVG drawings
   - Coordinates in pixel units
   - Converted to meters via measurements

**Our building.yaml:**
```yaml
levels:
  L1:
    elevation: 0.0
    # No drawing! ❌
```

**Conclusion:** We're using a **programmatic approach** (direct coordinate specification), not a **GUI-based approach** (traffic_editor + building_map_generator).

## Why Option A Is Not Viable

### rmf_demos Workflow

```
Traffic Editor (GUI)
    ↓ Create building with drawings
hotel.building.yaml (with drawing references)
    ↓ building_map_generator nav
hotel_nav_graph.yaml (auto-generated)
    ↓ Use in simulation
Working multi-level navigation
```

### Our Workflow

```
Manual creation
    ↓ Direct coordinate specification
hotel.building.yaml (NO drawings)
    ↓ building_map_generator nav
ERROR: No measurements defined ❌
```

### Fundamental Mismatch

| Requirement | rmf_demos | Our Approach |
|-------------|-----------|--------------|
| **Building file source** | Traffic Editor GUI | Manual YAML |
| **Level drawings** | PNG/SVG images | None (pure coordinates) |
| **Vertex placement** | GUI on images | Direct X,Y coordinates |
| **Coordinate system** | Image pixels → meters | Meters (Gazebo world) |
| **Nav graph generation** | Auto-generated | Manually created |
| **Fiducials** | Placed in GUI | None |

## Alternative Approaches Considered

### 1. Create Dummy Drawing Files

**Idea:** Generate blank PNG images for each level

**Problem:** 
- Vertices would be in pixel coordinates relative to image
- No measurements → scale indeterminate  
- Coordinate transform to our Gazebo world unclear

### 2. Use traffic_editor Directly

**Idea:** Install traffic_editor and create building graphically

**Problem:**
- Requires GUI environment (container is headless)
- Would duplicate our existing coordinate-based layout
- Adds dependency on GUI tools

### 3. Reverse-Engineer Generated Format

**Idea:** Find rmf_demos generated nav graph and copy format

**Problem:**
- Already tried multiple nav graph formats (all failed)
- Issue isn't format - it's Free Fleet's lack of map-switching

## Current Status

**What We Have:**
- ✅ Elevations: L1=0m, L2=4m, L3=8m
- ✅ Proper multi-level nav graph structure
- ✅ lift_cabin waypoint properties
- ✅ Dictionary-format lift_lanes
- ✅ Unique dock names per level

**What's Still Missing:**
- ❌ Map switching logic in Free Fleet
- ❌ Level transition coordination
- ❌ Actual lift supervisor integration

**Evidence:**
- Single-level tasks: ✅ Working (`lobby_east` → `lobby_west` assigned)
- Multi-level tasks: ❌ Failing (`lobby_center` → `L2_center` rejected)
- Error: "insufficient battery capacity" (misleading - actually path rejection)

## Real Blocker: Free Fleet Limitations

### Free Fleet Architecture

```python
class Nav2RobotAdapter:
    def __init__(self, robot_name, robot_config, ...):
        self.map_frame = robot_config_yaml['map_frame']  # Single map
        # No level-switching logic!
```

**Key Missing Functionality:**

1. **Map switching**: When robot enters lift cabin, switch Nav2's active map
2. **Level tracking**: Monitor robot's current level
3. **Coordinate transform updates**: Adjust transforms when changing levels
4. **Lift state coordination**: Wait for lift travel before resuming navigation

### What rmf_demos Has

**Full fleet adapter with map switching** (C++ implementation):
```cpp
// Pseudocode
if (robot_at_lift_cabin && target_on_different_level) {
    wait_for_lift_arrival();
    enter_lift();
    switch_nav2_map(target_level);  // Critical!
    wait_for_lift_travel();
    exit_lift();
    resume_navigation();
}
```

**Free Fleet** (Python wrapper around C++ EasyFullControl):
- Thin layer over RMF's C++ API
- Designed for single-level fleets
- No multi-level/map-switching support

## Conclusion

**Option A (building_map_generator) is NOT viable** because:

1. Requires traffic_editor-created building files with drawings
2. We use programmatic coordinate-based approach
3. Even if we generated nav graphs correctly, **Free Fleet still lacks map-switching**

**The real issue** is not nav graph format, but architectural:
- Free Fleet was designed for single-level navigation
- Multi-level requires map-switching capability
- This needs custom fleet adapter development

## Recommendations

### Option B: Implement Map Switching in Free Fleet

**Effort:** High (weeks of development)

**Changes needed:**
1. Modify `Nav2RobotAdapter` to track current level
2. Add map-switching logic on lift transitions
3. Coordinate with RMF lift state machine
4. Update coordinate transforms per level

**Feasibility:** Technically possible, but significant work

### Option C: Document Limitation

**Effort:** Low (documentation only)

**Acknowledge:**
- Single-level multi-robot coordination works ✅
- Multi-level requires architecture changes beyond scope
- Current demo meets most requirements except multi-floor

**Status:** This is the pragmatic choice given timeline

## Files

**Building file used:**
- `/opt/hotel_config/hotel.building.yaml` (no drawings)

**Generated output:**
- None (generation failed due to missing drawings/measurements)

**Current nav graph:**
- `/opt/ros2-demo/rmf/nav_graph.yaml` (manually created, with elevations)

---

**Date:** 2026-09-04  
**Attempt Duration:** 30 minutes  
**Tool Used:** `ros2 run rmf_building_map_tools building_map_generator nav`  
**Result:** Not viable for coordinate-based approach
