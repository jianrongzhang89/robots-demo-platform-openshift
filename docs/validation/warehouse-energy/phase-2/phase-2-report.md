# Warehouse energy Stage 2 implementation report

**Date:** November 17, 2026  
**Status:** **COMPLETE / PASS.** The Stage 2 physics-routing gate passed: frozen calibrated
physics parameters, repeatable routes with valid itinerary/path correlation in every trial,
and a working pre-dispatch reserve/deadline gate including an explicit rejection scenario.
Stage 3A (simulation dataset) may proceed.  
**Runtime:** Isolated `warehouse-energy/warehouse-qualification` pod using the pinned hotel
runtime image, ROS domain 85, and the `warehouse_navigation_trial` Gazebo partition; no bridge
to the hotel demo. Calibration was reproduced byte-identically inside the same pod.

## Completed

### Calibrated physics estimator

The planning-time physics estimator follows the approved force balance
`F = m*a + m*g*sin(theta) + Crr*m*g*cos(theta)` with traction power `max(F*v, 0)/eta`, no
regeneration credit, and a constant auxiliary load. It predicts mission Wh from planning
inputs only: segment geometry, planned speed/acceleration caps, stop-to-stop profiles,
waypoint heading changes, and a declared per-goal transition allowance (13.5 s, derived from
the accepted Phase 1 mission windows; rotation at the Nav2 `rotate_to_heading` rate).

Parameters were fitted on the 36 dedicated Phase 0 fresh-world ramp trials (two routes × two
directions × three payloads × three resets), with observed Wh recomputed from the raw actuator
traces under the frozen Phase 1 telemetry accounting model. The frozen result is
[`config/warehouse-energy/physics-model-v1.json`](../../../../config/warehouse-energy/physics-model-v1.json):

| Parameter | Frozen value |
| --- | --- |
| Rolling resistance coefficient | 0.00038 |
| Drive efficiency | 0.435045 |
| Auxiliary power | 10.004126 W |

Calibration accuracy: RMSE **0.000276 Wh**, maximum absolute error **0.000741 Wh** across all
36 runs. Traction is only 0–0.75% of modeled energy, so rolling resistance and drive
efficiency are jointly weakly identified; the report records this valley explicitly and
documents the telemetry-consistent alternative (efficiency fixed at the Phase 1 constant 0.6,
rolling resistance 0.00526, which reproduces the declared simulator wheel joint friction).
Re-running the calibration inside the pinned pod reproduced the frozen model byte-identically
(SHA-256 `608330117e6470cd0fb7f97f43f20c8cca37d6723460b6f423e36651d6f4636d`). See the
[calibration report](calibration/calibration-report.json).

### Route selector and feasibility gates

The selector runs at planning time, before any world or process starts. It evaluates both
frozen fixture routes, predicts mission energy and duration with the frozen physics model,
and enforces the frozen one-way deadline (900 s) and the battery-reserve requirement
(predicted SOC after the mission plus the minimum-energy charger access over routes available
at planning time ≥ 0.20). Arm A picks the shortest feasible distance; arm B picks the minimum
predicted-energy feasible route with the frozen tie-break (0.01 Wh, then shorter duration,
then route id). Replanning hysteresis (5%) is implemented and unit-tested but not exercised
by this single-dispatch series.

At payload 0.5 kg and initial SOC 0.8 the selector predicts route A at 0.4752 Wh / 170.0 s
and route B at 1.3923 Wh / 499.9 s, with 0.5683 Wh charger access via the A descent. Both
arms therefore select route A: with identical surfaces and the same 0.2 m rise, the longer
route B costs more auxiliary time and more rolling work. This is the honest physics result
the proposal anticipated for the initial same-surface fixture; no world tuning was applied to
manufacture a route divergence.

### Live trial series

Eight trials ran in the pinned pod on November 17, 2026 (high payload 0.5 kg, 320×240
non-semantic RGB-D, same ordered RMF compose dispatch and Nav2 corridor execution as Phase
0/1). Every motion trial passed the underlying navigation audit (ordered physical waypoints,
Nav2 goal correlation, RMF itinerary and accepted schedule mirror inside the selected
corridor, RGB-D transport, modeled battery telemetry).

| Trial | Arm | Selected route | Observed Wh | Predicted Wh | Error | Observed duration | Final SOC |
| --- | --- | --- | ---: | ---: | ---: | ---: | ---: |
| armA-r1 | A | A | 0.4795 | 0.4752 | +0.9% | 171.4 s | 0.7763 |
| armA-r2 | A | A | 0.4812 | 0.4752 | +1.2% | 172.0 s | 0.7762 |
| armA-r3 | A | A | 0.4817 | 0.4752 | +1.4% | 172.2 s | 0.7762 |
| armB-r1 | B | A | 0.4799 | 0.4752 | +1.0% | 171.6 s | 0.7763 |
| armB-r2 | B | A | 0.4840 | 0.4752 | +1.8% | 173.1 s | 0.7761 |
| armB-r3 | B | A | 0.4610 | 0.4752 | −3.1% | 164.8 s | 0.7771 |
| armB-excluded-A-r1 | B (route A excluded) | B | 1.4105 | 1.3923 | +1.3% | 506.2 s | 0.7376 |
| rejected-low-soc | B | — | — | — | — | — | — |

Across the seven motion trials: prediction MAE **0.0090 Wh**, RMSE **0.0102 Wh**, maximum
absolute error **0.0183 Wh** (−3.1% to +1.8%); observed durations 164.8–506.2 s, all within
the 900 s deadline; observed final SOC 0.7376–0.7771, all above the 0.20 reserve. Maximum
plan centerline deviation 0.050 m, itinerary and accepted-mirror deviation 0.014 m, all far
inside the 0.71 m corridor envelope; every trial's physical ordered waypoint sequence matched
its dispatched path.

The exclusion scenario (`armB-excluded-A-r1`) removed route A at planning time; the selector
chose route B, and RMF/Nav2 executed that corridor end to end with the same correlation
checks passing. The rejection scenario (`rejected-low-soc`, initial SOC 0.22) was refused
before any world or process started with the explicit reason "predicted final SOC 0.1765
below reserve 0.2 after mission plus charger access" (the minimum feasible allowance at that
SOC is 0.48 Wh against a predicted 1.044 Wh mission-plus-access demand); no task was
dispatched and no motion occurred.

The independent series audit
([`series/stage2-audit.json`](series/stage2-audit.json)) re-derived every selection from the
frozen fixture and model, recomputed every mission window from the raw actuator, pose, and
adapter traces, and passed with zero errors.

## Stage 2 gate status

| Gate | Status | Evidence |
| --- | --- | --- |
| Frozen calibrated physics parameters | PASS — fitted on 36 dedicated Phase 0 calibration runs, RMSE 0.000276 Wh, pod-reproduced byte-identically | `config/warehouse-energy/physics-model-v1.json`, [`calibration/`](calibration/calibration-report.json) |
| Route selector with reserve/deadline checks | PASS — deterministic planning-time selection, charger access included, tie-break and hysteresis unit-tested | `route-selection.json` in each trial; `test_stage2.py` |
| Repeatable routes | PASS — three repeats per arm, one stable route per arm | `series/armA-r*/`, `series/armB-r*/` |
| Itinerary/path correlation | PASS in all seven motion trials | `result.json` per trial; `series/stage2-audit.json` |
| Selector-driven corridor switch | PASS — route-A exclusion selected and executed route B | `series/armB-excluded-A-r1/` |
| Pre-dispatch rejection with explicit reason | PASS — low-SOC mission refused without motion | `series/rejected-low-soc/` |
| Physics prediction accuracy | PASS for Stage 2 purposes — MAE 0.0090 Wh (≤2% of mission energy); no Stage 2 threshold was frozen for it | `series/stage2-audit.json` |
| Route divergence between arms | NOT PRESENT at this fixture — both arms correctly select route A; a physics result, not a gate failure | `route-selection.json` |
| Energy saving claim | NOT MADE | Modeled energy only |

## Assumptions and limits

All energy values remain outputs of the frozen Phase 1 modeled-telemetry assumptions (0.6
drive efficiency, 10 W auxiliary, 24 Wh battery, no regeneration) and the Stage 2 planning
model calibrated against them; none is a physical battery measurement. The telemetry model
and the planning physics model are deliberately separate artifacts: the frozen telemetry
constants define the observed label, and the fitted planning parameters (including the
efficiency that absorbs rolling-resistance model-form error) minimize prediction error
against that label. The per-goal transition allowance is a declared planning constant, not a
fitted parameter; its residual error is Stage 3B residual-learning material. Both arms
selecting route A is the correct physics outcome for the current same-surface fixture;
route divergence requires a qualified surface or fixture change, which remains future work.
No learned model, model serving, or energy-saving claim is part of this stage.

## Reproduction and evidence

Regenerate the Phase 0 ramp matrix with `run_matrix.py` (see the [storage policy](../README.md)) and run
`scripts/warehouse-energy/calibrate_physics.py` (standard library only) to reproduce the
frozen model. Re-run any trial with `scripts/warehouse-energy/run_stage2_trial.py` inside the
pinned pod (see `scripts/warehouse-energy/README.md`). Audit the retained series locally:

```sh
python3 scripts/warehouse-energy/audit_stage2.py \
  docs/validation/warehouse-energy/phase-2/series \
  --fixture config/warehouse-energy/fixture-v1.json \
  --physics-model config/warehouse-energy/physics-model-v1.json
```

Stage 2 unit tests: `python3 -m unittest test_stage2` from
`scripts/warehouse-energy/` (13 tests: force model, profiles, calibration recovery, selector
decisions, hysteresis, rejection gate).
