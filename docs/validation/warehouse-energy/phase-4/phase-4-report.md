# Warehouse energy Stage 4 comparative demonstration report

**Date:** November 17, 2026  
**Status:** **COMPLETE.** The frozen A/B/C experiment executed all 121 planned missions with
zero failures, the independent audit passed, and the explicit AI-value decision is recorded:
**prediction result only** — arm C (served physics-plus-XGBoost) improves mission-energy
prediction over arm B (physics) by 96.8% on held-out live missions, but produces no
route-energy benefit in this fixture because every arm selects the same, energy-optimal
corridor. Per the proposal, this is a legitimate recorded research outcome, not a failure.
Stages 0–4 of the approved scope are now complete; Stage 5 (hardware study) remains a
separate follow-on.  
**Runtime:** `warehouse-stage4` pod (pinned hotel image, labeled serving client, mTLS
credentials mounted as a Secret) executing the frozen seeded trial order against the
qualified `energy-predictor-v1` serving endpoint; the serving InferenceService remained
Ready throughout.

## Experiment

The frozen experiment ([`stage4-experiment-v1.json`](../../../config/warehouse-energy/stage4-experiment-v1.json))
compared three arms over matched triplets with identical conditions, controller, semantic
policy, speed (0.10 m/s), and route candidates:

- **Arm A** — shortest feasible distance; energy logged only
- **Arm B** — minimum predicted mission energy; calibrated physics estimator
- **Arm C** — minimum predicted mission energy; served physics-plus-XGBoost with the
  documented fallback

Coverage: six strata (payloads 0/0.25/0.5 kg × both directions on the single qualified
surface — a documented deviation from the proposal's twelve-strata plan, which assumed a
second qualified surface) × five triplets = 90 one-way missions; plus 15 round trips
(loaded outbound at 0.5 kg, empty return, chained arithmetically because the frozen fixture
changes payload only at fresh-world initialization); plus the arm-C endpoint-unavailable
fallback demonstration. 121 missions total, in a deterministic seeded-randomized order
([`trial-order.json`](trial-order.json)). Mission observations use the model's frozen label
convention (dispatch through final waypoint arrival; post-arrival idle reported separately).

## Results

All 121 missions passed their navigation audits: ordered physical waypoints, Nav2 goal
correlation, RMF itinerary and accepted schedule mirror inside the selected corridor
(maximum deviations ≤ 0.05 m against the 0.71 m envelope), 10 Hz RGB-D, modeled battery
telemetry, zero collisions, ramp departures, or limit violations.

| Criterion | Target | Result | Status |
| --- | --- | --- | --- |
| Motion and task completion | all complete, zero violations | 121/121 passed, 0 rejected | **PASS** |
| Route coordination | 100% agreement | 100% (all arms, all triplets) | **PASS** |
| Prediction MAE improvement (C vs B) | ≥ 20% | **96.8%** (B 0.035405 Wh → C 0.001138 Wh) | **PASS** |
| Upper-estimate coverage | ≥ 95% | served 100%, physics mode 100% | **PASS** |
| Completion-time increase (C vs A) | ≤ 10% | +0.02% (157.2 s mean all arms) | **PASS** |
| Added AI value (energy) | ≥ 5% with CI excluding zero | −0.02%, paired 95% CI [−0.0000127, +0.000187] Wh | **NOT MET — legitimate outcome** |
| Fallback demonstration | documented physics fallback | arm C selected and completed in fallback mode | **PASS** |

One-way mean observed mission energy: A 0.4382 Wh, B 0.4383 Wh, C 0.4383 Wh (30 missions
each); round-trip means 0.8767 Wh in every arm (5 each). The paired B−A difference is
+0.0000309 Wh (CI includes zero): distance-shortest and energy-optimal corridors coincide
in this fixture, so energy-aware routing has nothing to improve — an honest physics result
of the same-surface, same-rise geometry that Stage 2 predicted and the proposal explicitly
anticipated ("a route change is not required if the same route remains best").

The prediction improvement is real and large: the physics estimator's conservative
per-goal transition allowance over-predicts mission energy by ~0.035 Wh on the arrival
convention, and the served correction removes nearly all of it (MAE 0.0011 Wh ≈ 0.26% of
the mission). The served-mode upper estimate covered 100% of arm C missions; the physics
allowance covered 100% of arm B missions (with its larger 0.037 Wh allowance).

The fallback demonstration ran arm C with the serving endpoint unreachable at planning
time: the client activated the documented local-physics fallback, selection completed in
fallback mode, and the mission passed — no mission was started on an unvalidated
prediction.

## Independent audit

[`stage4-audit.json`](stage4-audit.json) **PASSES** with zero errors: every trial's observed
mission energy and duration recomputed from the raw traces on the frozen arrival
convention, physics predictions re-derived from the fixture and frozen model, all 80
served route-level predictions verified against the frozen offline expectations
([`served-expectations.json`](served-expectations.json)), round-trip chaining reconciled,
and the analyzer's headline statistics recomputed exactly.

## AI-value decision

> **PREDICTION RESULT ONLY.** Arm C materially improves mission-energy prediction over
> arm B (96.8% MAE reduction, far beyond the 20% target) and its uncertainty calibration
> is valid, but it produces no route-energy benefit in this fixture because every arm
> selects the same (energy-optimal) corridor. The energy-routing benefit of either
> estimator over the distance baseline requires conditions where the estimators disagree
> on the chosen corridor — for example a qualified second surface or a fixture change.
> Retain the physics planner as the preferred implementation for route selection in this
> fixture; retain the served predictor where prediction accuracy matters (reserve
> margins, mission feasibility, operator estimates).

No energy saving is claimed: all energy values are modeled simulation outputs under the
frozen Phase 1 accounting assumptions. Aggregate mission energy is statistically
indistinguishable across arms (all paired confidence intervals include zero), consistent
with identical corridor selection and execution.

## Reproduction and evidence

Raw trial directories are regenerated with `run_stage4_series.py` (see the
[storage policy](../README.md)); the per-trial selection and result records are retained
loose under [`series/`](series/). Rebuild the frozen order with `build_stage4_order.py`,
execute the series in a labeled stage-4 pod, then analyze and audit from a repository
checkout:

```sh
python3 scripts/warehouse-energy/analyze_stage4.py \
  docs/validation/warehouse-energy/phase-4/series \
  --experiment config/warehouse-energy/stage4-experiment-v1.json \
  --output docs/validation/warehouse-energy/phase-4/analysis.json
python3 scripts/warehouse-energy/audit_stage4.py /tmp/stage4/stage4-series \
  --analysis docs/validation/warehouse-energy/phase-4/analysis.json \
  --fixture config/warehouse-energy/fixture-v1.json \
  --physics-model config/warehouse-energy/physics-model-v1.json \
  --expectations docs/validation/warehouse-energy/phase-4/served-expectations.json \
  --output docs/validation/warehouse-energy/phase-4/stage4-audit.json
```

Stage 4 unit tests: `python3 -m unittest test_stage4` from `scripts/warehouse-energy/`
(10 tests: frozen order, statistics, exact selector inputs, arm selections, fallback,
round-trip planning, and rejection).
