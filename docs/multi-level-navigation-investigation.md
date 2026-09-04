# Multi-Level Navigation Investigation

## Problem Statement

Multi-level patrol tasks (e.g., `lobby_center` → `L2_center` → `L3_center`) are rejected by RMF's TaskPlanner with "insufficient battery capacity" error, despite:
- Battery capacity set to 1,000,000 Ah (vs default 240 Ah)
- `account_for_battery_drain: False` enabled
- Single-level tasks working correctly on same graph

## Investigation Timeline

### Test 1: Original Hierarchical Structure
**Nav Graph Format:**
```yaml
levels:
  L1:
    vertices: [...]
  L2:
    vertices: [...]
  L3:
    vertices: [...]

lift_lanes:
  - [lift1_cabin_L1, lift1_cabin_L2, {...}]  # Using waypoint NAMES
```

**Result:** ❌ Failed  
**Error:** "insufficient battery capacity"  
**Root Cause:** RMF requires lift_lanes to use vertex indices, not names

### Test 2: Flattened 2.5D Structure with Global Indices
**Nav Graph Format:**
```yaml
levels:
  L1:
    vertices:
      - [..., {name: lobby_east}]     # 0
      - [..., {name: lobby_west}]     # 1
      # ... all 25 vertices in single level
      - [..., {name: lift1_cabin_L1}]  # 8
      - [..., {name: lift1_cabin_L2}]  # 15
      - [..., {name: lift2_cabin_L2}]  # 17
      - [..., {name: lift2_cabin_L3}]  # 24

lift_lanes:
  - [8, 15, {lift_name: Lift1}]   # Using global INDICES
  - [17, 24, {lift_name: Lift2}]
```

**Result:** ❌ Still Failed  
**Error:** "insufficient battery capacity"  
**Verification:** 
- Vertex indices confirmed correct (0-24)
- lift_lanes using global indices as specified
- Single-level tasks work: `lobby_center` → `lift1_cabin_L1` ✅ ASSIGNED

## Key Findings

### What Works ✅
1. **Single-level navigation** - Tasks within one logical "floor" work perfectly
2. **Graph structure** - Flattened nav graph is valid and loads correctly
3. **Waypoint naming** - All 25 waypoints recognized by RMF
4. **Fleet adapter integration** - Robots register, bids submitted
5. **Task dispatch system** - Single-level tasks assigned and executed

### What Fails ❌
1. **Multi-level paths** - Any task requiring lift_lanes traversal rejected
2. **Two-level paths** - Even simple `L1` → `L2` fails (not just L1→L2→L3)
3. **Battery calculation** - Error persists with 1M Ah capacity

## Hypothesis: RMF TaskPlanner Limitation

The TaskPlanner likely:

**Option A: Requires True Multi-Level Structure**
- Expects separate levels with different elevations
- lift_lanes with dictionary format: `{from: [L1, idx], to: [L2, idx]}`
- Calculates vertical traversal costs based on elevation deltas

**Option B: Doesn't Support 2.5D Lift Lanes**
- 2.5D (all at Z=0) may not be compatible with lift_lanes concept
- lift_lanes might be designed only for true 3D multi-floor buildings
- Flattened structure with lift_lanes may be undefined behavior

**Option C: Missing Lift Definitions**
- Nav graph has `lifts: {}` (empty)
- TaskPlanner may need lift definitions to calculate traversal costs
- Even with correct lift_lanes, missing lift specs cause rejection

## Evidence

### Battery Error is Misleading
```bash
# Test with 1,000,000 Ah capacity
[ERROR] [TaskPlanner] Failed to compute assignments for task_id [...] 
        due to insufficient battery capacity

# Same error with account_for_battery_drain: False
```

**Analysis:** The "battery" error is likely a fallback message when TaskPlanner cannot find ANY valid path. When path planning fails for structural reasons (e.g., untraversable lift_lanes), RMF reports it as a battery issue.

### Path Cost Calculation Theory
If RMF calculates path cost as Euclidean distance:
- `lobby_center` (20, 25) → `L2_center` (78, 25) = 58 meters straight-line
- Actual lane-based path: lobby_center → lift_approach (7m) → cabin (4.5m) + lift_lane (unknown cost) + cabin → lift_approach (4.5m) → L2_center (16m) ≈ 32m + lift_cost

If lift_lanes have undefined/infinite cost → path rejected as infeasible → battery error.

## Architecture Constraints

### Free Fleet + EasyFullControl
We're using:
- **Free Fleet**: Python wrapper around RMF's C++ fleet adapter
- **EasyFullControl**: C++ API for fleet management
- **Nav2**: Robot navigation (single-level only)

**Limitation:** Nav2 operates on single 2D map. Multi-level navigation requires:
1. RMF coordinating high-level path (L1 → Lift → L2)
2. Triggering map switches at level transitions
3. Nav2 navigating within each level's local map

Current implementation may not support map switching during task execution.

## Test Results Summary

| Task | Start | End | Levels | lift_lanes | Battery | Result |
|------|-------|-----|--------|------------|---------|--------|
| Patrol | lobby_east | lobby_west | 1 | No | 1M Ah | ✅ ASSIGNED |
| Patrol | lobby_center | lift1_cabin_L1 | 1 | No | 1M Ah | ✅ ASSIGNED |
| Patrol | lobby_center | L2_center | 2 | Yes (1) | 1M Ah | ❌ REJECTED |
| Patrol | lobby_center | L2_center, L3_center | 3 | Yes (2) | 1M Ah | ❌ REJECTED |

**Conclusion:** lift_lanes traversal is the blocker, not battery capacity.

## Next Steps - Options

### Option 1: Revert to True Multi-Level Structure
- Use separate levels (L1, L2, L3) with elevations (0m, 4m, 8m)
- Use dictionary lift_lanes: `{from: [L1, 6], to: [L2, 3]}`
- Implement map switching logic in fleet adapter
- **Risk:** May require custom Nav2 integration beyond Free Fleet's scope

### Option 2: Implement Simulated Lifts
- Create physical "lift zones" in the 2D map at (52.5, 27.5) and (112.5, 27.5)
- Use regular lanes (not lift_lanes) to connect zones
- Sacrifice RMF lift coordination features
- **Benefit:** Works within current 2.5D architecture

### Option 3: Add Lift Definitions to Nav Graph
```yaml
lifts:
  Lift1:
    ref_floor: L1
    levels: [L1]  # All on same level
    # Minimal definition for 2.5D
```
- Test if TaskPlanner needs lift specs to cost lift_lanes
- **Effort:** Low, quick test

### Option 4: Research RMF Demos Examples
- Find working multi-level nav graph from rmf_demos
- Compare lift_lanes format and level structure
- Identify what we're missing
- **Status:** rmf_demos package not fully installed in container

## Files Modified (Commit 0da2240)

```
config/rmf/hotel_nav_graph_multilevel_2d.yaml     - Flattened structure, global indices
helm/multi-robot-demo/files/nav_graph.yaml        - Deployed nav graph
helm/multi-robot-demo/files/fleet_config.yaml     - Single L1 map, 1M Ah battery
config/free_fleet/tinybot_fleet_config_multilevel.yaml - Config source
```

## References

- [RMF Core](https://github.com/open-rmf/rmf_core) - Traffic management and task planning
- [Free Fleet](https://github.com/open-rmf/free_fleet) - Nav2 integration layer
- [RMF Demos](https://github.com/open-rmf/rmf_demos) - Example multi-level buildings (hotel, office)
- Memory: [[demo_requirements]] - Hard requirements mandate multi-level with lifts
- Memory: [[rmf_hotel_world_plan]] - Original multi-level plan notes

## Test Results

### Option 3: Add Lift Definitions ❌ FAILED

**Attempted:** 2026-09-04 11:25 UTC

Added lift definitions to nav_graph.yaml:
```yaml
lifts:
  Lift1:
    reference_floor_name: L1
    x: 52.5
    y: 27.5
    yaw: 0.0
    width: 2.7
    depth: 2.7
```

**Result:** Fleet adapter crashed on startup
```
RuntimeError: invalid node; first invalid key: "position"
[ros2run]: Process exited with failure 1
```

**Root Cause:** Free Fleet's `FleetConfiguration.from_config_files()` cannot parse lift definitions in nav_graph.yaml. Lift definitions belong in building.yaml (separate file), not the navigation graph.

**Conclusion:** Option 3 is not viable. nav_graph.yaml must have `lifts: {}`.

## Status

**Current State:** Infrastructure ready, nav graph restructured correctly with global indices, but multi-level path planning fails.

**Option 3 Result:** ❌ Incompatible with Free Fleet parser  
**Next Step:** Implement Option 1 (true multi-level structure with elevations)

**Date:** 2026-09-04  
**Branch:** rmf-hotel-world-demo  
**Commit:** 0da2240
