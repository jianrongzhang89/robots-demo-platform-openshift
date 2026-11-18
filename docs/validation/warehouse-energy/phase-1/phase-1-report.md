# Warehouse energy Phase 1 implementation report

**Date:** November 16–17, 2026  
**Status:** **COMPLETE / PASS — accepted with reviewer sign-off on November 17, 2026.** All four 320×240 route/direction sensing and bounded SAM3 semantic runs passed, and the November 16–17 semantic repeatability series passed three audited repeats for every route/direction after the B-route red-mat amendment (mat moved from `[7.0, 6.3]` to `[7.0, 6.5]` m to eliminate a reproducible B-up planner block at the old position). 640×480 throughput and other objects remain open; physical electrical calibration remains out of scope. Stage 2 may proceed.  
**Runtime:** Isolated `warehouse-energy/warehouse-qualification` and `semantic-navigation/warehouse-phase1-sam3` pods using pinned images; no bridge to the hotel demo.

## Completed

The bounded warehouse fixture supports 640×480 and smaller RGB-D camera sizes at 10 Hz. Gazebo color, depth, and camera calibration streams bridge into ROS. A separate full-pose optical-frame transform is published from the Gazebo pose stream at capture-time simulation stamps, preserving robot pitch and roll without changing Nav2's planar `base_footprint` transform. The four-route 640×480 series delivered approximately 3–4.5 RGB frames/s and 2.7–3.2 depth frames/s, below the configured rate. Four integrated 320×240 runs, covering both routes and directions, passed transport, RMF/Nav2, capture-time TF, and energy audits at 10.0 Hz RGB and depth with maximum frame gaps of 0.1 s. Capture-time TF deltas were at most 0.018 s. The present Phase 1 sensing configuration is therefore 320×240 at 10 Hz. 640×480 throughput remains below target.

The observation-only Gazebo plugin now produces an electrical-demand trace alongside the original torque/speed trace. It computes positive wheel mechanical power from simulated joint effort and angular velocity, divides by the assumed drive efficiency, adds auxiliary power, integrates Wh in simulation time, and derives SOC from a design battery capacity. The warehouse adapter reports this changing SOC to RMF fleet state. The independent audit recalculates Wh and SOC from the raw actuator trace and checks each trace row's units and arithmetic.

Four full RMF/Nav2 route trials passed with high payload (0.50 kg), RGB-D streams, and modeled battery telemetry:

| Route | Direction | RMF task | Modeled Wh | Final modeled SOC | RGB / depth frames | Approx. RGB / depth Hz |
| --- | --- | --- | ---: | ---: | ---: | ---: |
| A | Up | `compose.dispatch-78e2a91b9d` | 0.540 | 77.75% | 857 / 612 | 4.5 / 3.2 |
| A | Down | `compose.dispatch-a3c69c663c` | 0.563 | 77.66% | 628 / 537 | 3.1 / 2.7 |
| B | Up | `compose.dispatch-64b78ed954` | 1.474 | 73.86% | 1,905 / 1,594 | 3.6 / 3.0 |
| B | Down | `compose.dispatch-3ac8ab46f6` | 1.487 | 73.81% | 1,828 / 1,518 | 3.4 / 2.9 |

All four raw energy traces passed independent arithmetic reconciliation. All four tasks followed their dispatched waypoints and selected corridors, and all RGB-D messages had nonempty payloads, expected dimensions, and the optical frame ID. These Wh and SOC values are outputs of the explicitly assumed model, not measured battery performance or an energy-saving comparison.

The four 320×240 route/direction runs passed independent arithmetic and sensing audits:

| Route | Direction | RGB / depth frames | RGB / depth Hz | Max capture-TF delta | Modeled Wh | Final modeled SOC |
| --- | --- | ---: | ---: | ---: | ---: | ---: |
| A | Up | 1,745 / 1,746 | 10.0 / 10.0 | 0.002 s | 0.530 | 77.79% |
| A | Down | 1,841 / 1,841 | 10.0 / 10.0 | 0.010 s | 0.568 | 77.63% |
| B | Up | 5,169 / 5,170 | 10.0 / 10.0 | 0.018 s | 1.503 | 73.74% |
| B | Down | 5,175 / 5,175 | 10.0 / 10.0 | 0.000 s | 1.501 | 73.75% |

These Wh and SOC outputs use the same explicit model assumptions and do not represent measured electrical performance.

The semantic gate passed on all four route/direction combinations at 320×240 using the pinned `sam3-mat-v1` HTTP endpoint, frozen `red mat` prompt, and `avoid-target/v1` policy. The red mat and neutral distractor were visual-only. For route A, the red mat is centered at `[4.5, 0.5]` m; for route B it is centered at `[7.0, 6.3]` m. Each run retained up to 24 paired RGB/mask captures. The minimum mask precision against visible red pixels was 97.6%, and minimum red-pixel coverage was 99.3% across the four audits.

The global semantic costmap accepted observations and projected lethal cost 254 cells. Nav2 completed every route goal and RMF task while detouring around the target. Across the four runs, maximum plan centerline deviation was 0.465 m and maximum physical corridor deviation was 0.324 m, within the existing 0.70 m plan envelope and 0.40 m physical guard. Independent audits confirm controller, planner, behavior-tree, and local-costmap settings match the non-semantic baseline. This qualifies one run per route/direction for the frozen fixture and policy; it does not establish repeated-run robustness, behavior on other objects, or 640×480 semantics.

The semantic capture trace records ROS receipt time from the Gazebo camera bridge because Gazebo does not expose exposure wall-clock timestamps. It supports simulated stream ordering/freshness checks, not a hardware exposure-to-inference latency claim. Each semantic run also passed the modeled energy/SOC audit; its route-specific assumed Wh/SOC values are in `semantic-warehouse-series-audit.json` and are not physical measurements or an energy comparison.

## Semantic repeatability series

A repeated-run series (three repeats per route/direction at 320×240, frozen
fixture/prompt/policy, same pinned pod and endpoint configuration) ran on
November 16–17, 2026. The first series passed three audited repeats each for
A-up, A-down, and B-down, but the B-up r3 slot hit three genuine
mat-corridor planner blocks at the B-route red-mat position `[7.0, 6.3]` m —
the same marginal 0.75 m free-strip geometry previously fixed for route A.
The B-route mat was moved to `[7.0, 6.5]` m (widening the free strip to
0.95 m, prompt/policy/controller settings unchanged), and both B directions
then passed three audited repeats with zero planner blocks. The merged
cross-run audit passes for all twelve trials. Cross-run modeled Wh varied by
at most 0.035 Wh within a route/direction; minimum mask precision across the
series was 96.7%; maximum plan centerline deviation was 0.465 m and maximum
physical corridor deviation was 0.316 m, inside the existing envelopes.
Full evidence, preserved failed attempts, and infrastructure observations are
in [`sam3-repeatability/`](sam3-repeatability/README.md) (original series and
merged audit) and
[`sam3-repeatability-b-amended/`](sam3-repeatability-b-amended/README.md)
(amended-fixture B repeats).

## Assumptions and limits

The trace uses a 60% drive efficiency, 10 W auxiliary load, 24 Wh battery, and 80% initial SOC. These were selected from fixture sensitivity values and are not measured or calibrated robot properties. Negative wheel mechanical power receives no regeneration credit. Wheel joint effort is simulated actuator command evidence, not battery voltage/current telemetry. The metric is modeled energy at the simulated robot battery boundary.

RGB-D transport and capture-time camera TF are verified at 320×240 on all four route/direction combinations. SAM3 label and costmap behavior passed one bounded run in each combination and three audited repeats in every route/direction (A directions from the original series; B directions against the amended red-mat position `[7.0, 6.5]` m after the original `[7.0, 6.3]` m position reproducibly blocked the B-up planner). Other objects and 640×480 throughput remain open. The energy model is not calibrated against battery-terminal measurements. No route-energy advantage or physical battery-saving claim has been made.

## Phase 1 gate status

| Gate | Status | Evidence |
| --- | --- | --- |
| RGB-D transport on both ramps and directions | PASS at 320×240, 10.0 Hz in all four cases; 640×480 rate below target | The four `camera-320x240-*/result.json` files and independent audits |
| Capture-time 3D camera TF | PASS in all four 320×240 cases | Each route's `phase1-audit.json`; maximum nearest RGB/depth TF delta 0.018 s |
| Wheel-power, Wh, and SOC accounting | PASS in all four 320×240 cases and the earlier four-case 640×480 series | Independent arithmetic audits, with no arithmetic or timestamp errors |
| RMF battery-state propagation | PASS for all four route/direction cases at both resolutions | Adapter battery-state events and changing final SOC |
| Warehouse SAM3 semantic labels and Nav2 exclusion behavior | PASS, bounded one run per route/direction at 320×240, plus three audited repeats in every route/direction | Four current `sam3-attempts/phase1-semantic-320-*/` results and semantic audits; merged `sam3-repeatability/semantic-repeatability-audit.json` over both series directories |
| Repeated-run stability (semantic) | PASS — three audited repeats per route/direction after the B-route mat amendment | `sam3-repeatability/` and `sam3-repeatability-b-amended/` series with fifteen preserved development attempts |
| Physical electrical calibration | OUT OF SCOPE | Requires hardware battery-terminal voltage/current measurements |

## Reproduction and evidence

Regenerate the telemetry series with `run_navigation.py` and audit it with this
checkout's `scripts/warehouse-energy/audit_phase1_series.py` (see the
[storage policy](../README.md)). The retained loose evidence includes the trial designs,
raw wheel and energy traces, physical pose records, RGB-D summaries, RMF schedules, Nav2
plans and goal events, and audit results; the raw archive was removed to save storage.

The model constants and explicit non-calibration statement are in `config/warehouse-energy/phase1-telemetry-v1.json`. Implementation details and the isolated pod workflow are in `scripts/warehouse-energy/README.md`.

The four current SAM3 route/direction runs and independent audits are retained under `sam3-attempts/`. Re-run any semantic gate locally with:

```sh
python3 scripts/warehouse-energy/audit_semantic_trial.py \
  docs/validation/warehouse-energy/phase-1/sam3-attempts/phase1-semantic-320-A-up-12 \
  --baseline-nav2 docs/validation/warehouse-energy/phase-1/camera-320x240-A-up/nav2.yaml \
  --output docs/validation/warehouse-energy/phase-1/sam3-attempts/phase1-semantic-320-A-up-12/semantic-warehouse-audit.json
```
