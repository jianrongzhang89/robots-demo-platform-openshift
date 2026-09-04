# RMF lift_lanes Root Cause Analysis

## Executive Summary

**Root Cause Identified:** RMF's lift_lanes architecture requires actual elevation differences between levels. Our 2.5D approach (all levels at elevation 0.0) is fundamentally incompatible with RMF's lift traversal calculations.

**Error Message:** "insufficient battery capacity" is **misleading** — it's RMF's generic fallback when no valid path exists.

**Actual Issue:** TaskPlanner rejects paths through lift_lanes when elevation delta is zero, treating them as invalid lift operations.

---

## Investigation Summary

### What We Tested

1. **Flattened single-level with global indices**
   ```yaml
   levels:
     L1:
       vertices: [... 25 total ...]  # indices 0-24
   lift_lanes:
     - [8, 15, {lift_name: Lift1}]
   ```
   **Result:** ❌ Failed - both vertices on same level (elevation 0.0)

2. **True multi-level with dictionary format**
   ```yaml
   levels:
     L1:
       elevation: 0.0
       vertices: [... 9 vertices ...]
     L2:
       elevation: 0.0
       vertices: [... 9 vertices ...]
   lift_lanes:
     - {from: [L1, 8], to: [L2, 6], lift_name: Lift1}
   ```
   **Result:** ❌ Failed - elevation delta = 0.0

3. **Added lift definitions to nav_graph.yaml**
   ```yaml
   lifts:
     Lift1:
       reference_floor_name: L1
       x: 52.5
       y: 27.5
   ```
   **Result:** ❌ Failed - Free Fleet parser crashed with "invalid node; first invalid key: 'position'"

### Error Observed

```
[ERROR] [turtlebot3_fleet_adapter]: [TaskPlanner] Failed to compute assignments 
        for task_id [...] due to insufficient battery capacity to accommodate 
        one or more requests by any of the robots in this fleet.
```

**Battery Settings Tested:**
- 240 Ah (original) → Failed
- 10,000 Ah → Failed  
- 1,000,000 Ah → Failed
- With `account_for_battery_drain: False` → Still failed

**Conclusion:** Battery capacity is NOT the issue.

---

## Root Cause: Elevation Requirements

### From RMF Documentation

**Traffic Editor Documentation:**
> "When waypoints are connected across levels via lifts, the rmf_fleet_adapter will request for the lift to arrive at the appropriate floor. The displacement between the cabin's current elevation and that of the destination floor is computed."

**Simulation Documentation:**
> "The lift plugin configuration includes floor elevations, specified as `<floor name="L1" elevation="0.0">` and `<floor name="L2" elevation="10.0">`."

### RMF Demos Hotel World (Working Example)

**File:** `rmf_demos/rmf_demos_maps/maps/hotel/hotel.building.yaml`

```yaml
levels:
  L1:
    elevation: 0      # Ground floor
    drawing:
      filename: L1.png
  L2:
    elevation: 8      # 8 meters above ground
    drawing:
      filename: L2.png
  L3:
    elevation: 16     # 16 meters above ground
    drawing:
      filename: L3.png

lifts:
  Lift1:
    reference_floor_name: L1
    x: 355
    y: 340
    yaw: 0
    width: 3.5
    depth: 2.5
    lowest_floor: L1
    highest_floor: L3
    level_doors:
      L1: [lift1_L1_door]
      L2: [lift1_L2_door]
      L3: [lift1_L3_door]
```

**Navigation Graph Generation:**
```bash
ros2 run building_map_tools building_map_generator nav hotel.building.yaml output_nav_graphs/
```

The nav graph is **auto-generated** from the building file, not manually created.

---

## How RMF TaskPlanner Processes lift_lanes

### Path Cost Calculation

When evaluating a multi-level task:

1. **Within-level cost:** Euclidean distance using waypoint coordinates
2. **Lift traversal cost:** Calculated from elevation difference
3. **Total path cost:** Sum of all segments
4. **Battery check:** Total cost vs. available battery capacity

### The 2.5D Problem

**Our configuration:**
```yaml
L1: elevation: 0.0
L2: elevation: 0.0
L3: elevation: 0.0
```

**TaskPlanner calculation:**
```
elevation_delta = L2.elevation - L1.elevation = 0.0 - 0.0 = 0 meters
lift_traversal_cost = f(elevation_delta) = f(0) = UNDEFINED/INFINITE
```

**Result:** Path marked as **invalid** (not a traversable lift operation)

**Fallback error:** "insufficient battery capacity" (generic message when no path found)

---

## Why Both Formats Failed

### Format 1: Flattened Global Indices

```yaml
levels:
  L1:
    vertices:
      - [52.5, 27.5, {name: lift1_cabin_L1}]  # index 8
      - [57.5, 27.5, {name: lift1_cabin_L2}]  # index 15
lift_lanes:
  - [8, 15, {lift_name: Lift1}]
```

**Issue:** Both vertices are in the same level "L1" at elevation 0.0. RMF sees this as a horizontal connection, not a lift lane requiring vertical travel.

### Format 2: Multi-Level Dictionary

```yaml
levels:
  L1:
    elevation: 0.0
    vertices:
      - [52.5, 27.5, {name: lift1_cabin_L1}]  # index 8
  L2:
    elevation: 0.0
    vertices:
      - [57.5, 27.5, {name: lift1_cabin_L2}]  # index 6
lift_lanes:
  - {from: [L1, 8], to: [L2, 6], lift_name: Lift1}
```

**Issue:** Even with separate levels, both have `elevation: 0.0`. Elevation delta = 0 → invalid lift operation.

---

## Prerequisites for Working lift_lanes

Based on rmf_demos analysis and RMF documentation:

### Required Components

| Component | Purpose | Status in Our Setup |
|-----------|---------|---------------------|
| **Distinct elevations** | Enable lift cost calculation | ❌ All at 0.0 |
| **Lift definitions in building.yaml** | Specify lift properties | ❌ In nav_graph (wrong place) |
| **Generated nav graph** | Auto-connect lift cabins | ❌ Manually created |
| **Separate level definitions** | Enable cross-level routing | ✅ Have L1/L2/L3 |
| **lift_cabin waypoints** | Mark lift entry/exit points | ✅ Have them |
| **Lift supervisor node** | Coordinate lift state | ⚠️ Placeholder only |
| **Map switching logic** | Change Nav2 map per level | ❌ Not implemented |

### Architecture Mismatch

**RMF's Design (3D):**
- True vertical building structure
- Each level has its own 2D map file
- Robots switch maps when entering/exiting lifts
- Lift moves vertically between floors

**Our Implementation (2.5D):**
- Single horizontal map with 3 zones
- All "levels" visible simultaneously at Z=0
- No map switching (single map for all zones)
- Lifts would be horizontal transitions

---

## Evidence from Code Search

### TaskPlanner Class

**Source:** [`rmf_task::TaskPlanner`](https://docs.ros.org/en/ros2_packages/humble/api/rmf_task/generated/classrmf__task_1_1TaskPlanner.html)

**Error trigger:** When planner cannot find a valid path within constraints

**Generic error message:** "Failed to compute assignments due to insufficient battery capacity"

**Why it's misleading:** Used for ANY path-finding failure, not just battery issues

### Lift Elevation Calculation

**File:** `rmf_traffic_editor/building_map_tools/building_map/level.py`

**Function:** Computes displacement between cabin elevation and destination floor

**Critical assumption:** Levels have different elevations

**Breaks when:** `elevation_A == elevation_B` → displacement = 0 → invalid

---

## Comparison: Our Config vs. Working Examples

### rmf_demos Hotel (Working)

```yaml
# hotel.building.yaml
levels:
  L1:
    elevation: 0
    vertices: [...]
  L2:
    elevation: 8      # 8m vertical difference
    vertices: [...]
  L3:
    elevation: 16     # 16m vertical difference
    vertices: [...]

lifts:
  Lift1:
    reference_floor_name: L1
    lowest_floor: L1
    highest_floor: L3
    level_doors:
      L1: [door]
      L2: [door]
      L3: [door]
```

**Generated nav graph:**
- Separate vertex lists per level
- lift_lanes auto-generated based on `lift_cabin` properties
- No manual lift_lanes specification needed

### Our Config (Failing)

```yaml
# nav_graph.yaml
levels:
  L1:
    elevation: 0.0
  L2:
    elevation: 0.0    # ❌ Same as L1
  L3:
    elevation: 0.0    # ❌ Same as L1

lifts: {}              # ❌ Empty

lift_lanes:            # ⚠️ Manually specified
  - {from: [L1, 8], to: [L2, 6]}
```

**Key differences:**
- Manual nav graph (not generated)
- No lift definitions
- Zero elevation differences
- No building.yaml file

---

## Why Free Fleet Parser Rejected Lift Definitions

**Error when adding lifts to nav_graph.yaml:**
```
RuntimeError: invalid node; first invalid key: "position"
```

**Root cause:** Free Fleet's `FleetConfiguration.from_config_files()` expects a navigation graph format, NOT a building definition format.

**Proper structure:**
- Lift definitions → `building.yaml`
- Navigation graph → generated from building file
- Fleet config → `fleet_config.yaml`

**Our mistake:** Tried to add building-level lift definitions directly to nav_graph.yaml

---

## Solution Path: True Multi-Level Implementation

### Requirements for Option 1

1. **Set distinct elevations:**
   ```yaml
   levels:
     L1:
       elevation: 0.0    # Ground level
     L2:
       elevation: 4.0    # 4 meters up
     L3:
       elevation: 8.0    # 8 meters up
   ```

2. **Create building.yaml with lift definitions:**
   ```yaml
   lifts:
     Lift1:
       reference_floor_name: L1
       lowest_floor: L1
       highest_floor: L3
       level_doors:
         L1: [lift1_door]
         L2: [lift1_door]
         L3: [lift1_door]
   ```

3. **Generate nav graph from building file:**
   ```bash
   building_map_generator nav hotel.building.yaml output_dir/
   ```

4. **Implement map switching in fleet adapter:**
   - Detect when robot enters lift cabin
   - Switch Nav2's active map to destination level
   - Resume navigation on new map after lift travel

5. **Run lift supervisor nodes:**
   - Coordinate lift state machine
   - Process lift requests from fleet adapters
   - Publish lift status to /lift_states

### Challenges

**Nav2 Integration:**
- Nav2 operates on 2D maps, one at a time
- Current Free Fleet doesn't support map switching
- Need custom logic to change maps during lift transitions

**State Coordination:**
- Fleet adapter must wait for lift arrival
- Robot enters cabin, waits for lift travel
- Exits on new level with new map loaded

**Complexity:**
- Significantly more complex than 2.5D approach
- Requires lift state management
- Potential for state machine deadlocks

---

## Alternative: Single-Level Demo

**Current working state:**
- Single level (L1 only)
- 4-robot patrol working perfectly
- No lift_lanes, no multi-level navigation

**Limitation:** Cannot demonstrate multi-level requirements

---

## Conclusion

The 2.5D multi-level architecture is fundamentally incompatible with RMF's lift_lanes design. RMF assumes:

1. True 3D building structure with vertical elevation differences
2. Lift definitions in building files (not nav graphs)
3. Auto-generated navigation graphs
4. Map switching capability when traversing levels
5. Active lift supervisor nodes coordinating operations

To demonstrate multi-level navigation with RMF, we must:
- Abandon the 2.5D approach
- Implement true elevations (even if physically horizontal in Gazebo)
- Add map switching logic to the fleet adapter
- Run actual lift supervisor infrastructure

The "insufficient battery capacity" error will persist regardless of battery settings until elevation differences are implemented or lift_lanes are abandoned entirely.

---

## References

- [Traffic Editor - Programming Multiple Robots with ROS 2](https://osrf.github.io/ros2multirobotbook/traffic-editor.html)
- [Simulation - Programming Multiple Robots with ROS 2](https://osrf.github.io/ros2multirobotbook/simulation.html)
- [Fleet Adapter Tutorial](https://osrf.github.io/ros2multirobotbook/integration_fleets_adapter_tutorial.html)
- [Tasks in RMF](https://osrf.github.io/ros2multirobotbook/task.html)
- [RMF FAQ](https://osrf.github.io/ros2multirobotbook/rmf-core_faq.html)
- [GitHub - open-rmf/rmf_demos](https://github.com/open-rmf/rmf_demos)
- [GitHub - open-rmf/rmf_traffic_editor](https://github.com/open-rmf/rmf_traffic_editor)
- [TaskPlanner API Documentation](https://docs.ros.org/en/ros2_packages/humble/api/rmf_task/generated/classrmf__task_1_1TaskPlanner.html)

---

**Date:** 2026-09-04  
**Branch:** rmf-hotel-world-demo  
**Investigation Method:** Agent-based code search + documentation review  
**Agent Tokens Used:** 63,956  
**Research Duration:** 225 seconds
