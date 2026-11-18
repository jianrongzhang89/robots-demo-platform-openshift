# Warehouse energy Stage 3A dataset report

**Date:** November 17, 2026  
**Status:** **COMPLETE / PASS.** The Stage 3A dataset gate passed: 96 instrumented sweep
runs (72 scripted traversals + 24 forced-corridor RMF/Nav2 missions), all trials passing
their physical and navigation audits, zero rejected runs, consistent segmentation into 312
labeled segment rows, frozen complete-run partitions with reserved generalization
combinations, and an independent data-quality audit that recomputes every label from the
raw traces. Stage 3B (offline training) may proceed.  
**Runtime:** Isolated `warehouse-energy/warehouse-qualification` pod using the pinned hotel
runtime image; scripted trials on the default Gazebo partition at real-time factor 10,
navigation missions on the `warehouse_navigation_trial` partition and ROS domain 85. No
bridge to the hotel demo.

## Sweep design and execution

The frozen sweep design ([`stage3-dataset-design-v1.json`](../../../../config/warehouse-energy/stage3-dataset-design-v1.json))
covers both ramps and directions, all three qualified payloads, planned speeds at or below
the qualified 0.10 m/s cap, and two stop profiles, in two run classes:

| Class | Conditions | Runs | Runner |
| --- | --- | ---: | --- |
| Scripted traversals | route {A,B} × direction {up,down} × payload {0,0.25,0.5} kg × speed {0.06,0.08,0.10} m/s × stop profile {none, mid-ramp stop + 3 s hold} | 72 | `stage3_trial.py` |
| Navigation missions | route {A,B} × direction {up,down} × payload {0,0.25,0.5} kg × speed {0.08,0.10} m/s | 24 | `run_stage3_nav.py` |

Scripted traversals replicate the Phase 0 physical checks (corridor, attitude, support,
clearance, overspeed, effort limits) with exactly known planned profiles, giving dense
control over stop/dwell conditions. Navigation missions force the swept corridor through
the same ordered RMF compose dispatch and Nav2 execution used in Stages 0–2, so the dataset
covers both ramps rather than only the preferred route. All 96 trials passed; the sweep ran
13:47–15:51 UTC on November 17, 2026 (about 2 h 4 m wall). The pinned fixture is
deterministic (Phase 0 finding), so repeat variation comes from real-time-factor wall-clock
jitter rather than seeds; this is recorded in the design.

## Dataset construction and labels

Each run is segmented consistently — ramp boundaries (start pad, ramp, end pad) for
scripted traversals, directed graph edges between consecutive waypoint crossings for
navigation missions — yielding 312 segment rows (216 scripted, 96 navigation, 96 ramp
segments). Every row pairs planning-time features (geometry, grade profile, ascent and
descent, heading change, planned speed, in-segment stops and dwell, total mass) with the
observed modeled Wh from the observation-only plugin trace under the frozen Phase 1
accounting model, the frozen Stage 2 physics estimate, and the residual. The dataset
artifacts are [`dataset/segments.jsonl`](dataset/segments.jsonl),
[`dataset/runs.jsonl`](dataset/runs.jsonl), and
[`dataset/dataset-manifest.json`](dataset/dataset-manifest.json); the raw runs are retained
as `stage3-raw-v1.tar.gz` (SHA-256
`32e5eafaf53e72017b62a055930442b035b0df72a359a56331a4c2815ba02d35`, 176 MB; extraction
plus audit re-verified after archiving).

Residual structure (observed minus frozen physics, per segment):

| Class | Segments | Mean residual | MAE | Range |
| --- | ---: | ---: | ---: | --- |
| Scripted | 216 | −0.0000 Wh | 0.0002 Wh | −0.0006 … +0.0007 Wh |
| Navigation | 96 | −0.0080 Wh | 0.0084 Wh | −0.0184 … +0.0012 Wh |

Scripted traversals reconcile with the frozen physics almost exactly, as expected for
controlled profiles on a deterministic fixture. Navigation residuals are systematically
negative and about forty times larger: the actual inter-goal transitions are faster than
the declared 13.5 s planning allowance. This is precisely the structured, learnable
correction the Stage 3B residual predictor is intended to capture, and it is consistent
across both directions (up −0.0079, down −0.0082 Wh mean).

## Partitions

Partitions follow the frozen complete-run rules; no run is split across partitions:

| Partition | Runs | Segments | Rule |
| --- | ---: | ---: | --- |
| residual_train | 42 | 138 | deterministic hash split |
| development | 14 | 44 | deterministic hash split |
| uncertainty_calibration | 13 | 43 | deterministic hash split |
| final_test | 27 | 87 | reserved combinations only |

The final-test partition holds out complete condition combinations for generalization
testing: every scripted run at payload 0.25 kg (24 runs, testing payload interpolation
against training payloads 0 and 0.5 kg) and every navigation route-B uphill run at
0.08 m/s (3 runs, testing an unseen navigation condition combination). The independent
audit verifies these combinations appear in no other partition.

## Stage 3A gate status

| Gate | Status | Evidence |
| --- | --- | --- |
| Instrumented traversal sweeps across the qualified envelope | PASS — 96/96 trials passed, both ramps and directions, three payloads, three speeds, two stop profiles | `raw-sweep.out`; raw archive regenerated per the [storage policy](README.md) |
| Traceable simulated Wh labels | PASS — every label recomputed from raw actuator traces under the frozen accounting model | `dataset/stage3-audit.json` |
| Consistent segmentation | PASS — 312 segment rows; synthetic perfect-observation tests reconcile to zero residual in both directions | `test_stage3.py` |
| Complete-run split manifest | PASS — four partitions, no run split, reserved combinations isolated | `dataset/dataset-manifest.json` |
| Data quality report | PASS — independent audit: labels, physics estimates, residual arithmetic, partition integrity, rejected-run handling | `dataset/stage3-audit.json` |
| Failed-run handling | PASS — zero failed runs in the accepted sweep; the pre-fix infrastructure failure is preserved and excluded | [`failed-attempts/`](failed-attempts/README.md) |

## Assumptions and limits

All labels remain modeled simulated energy under the frozen Phase 1 assumptions, not
physical battery measurements. One qualified surface exists on both ramps, so surface
variation is not part of this dataset. The dataset is a pilot sized for Stage 3B
development; the 180-run A/B/C evaluation pilot is Stage 4 work and is not part of this
budget. Dataset labels use the dispatch-to-final-waypoint-arrival window for navigation
runs, which excludes the post-arrival idle that the Stage 2 mission-window convention
included; the difference is documented in the manifest's label definition. No learned
model has been trained; no prediction-improvement or energy-saving claim is made.

## Reproduction and evidence

Regenerate the raw sweep with `stage3-sweep.sh` (see the [storage policy](../README.md)),
then rebuild and audit the dataset from a repository checkout (standard library only):

```sh
python3 scripts/warehouse-energy/build_stage3_dataset.py \
  --raw /tmp/stage3/stage3-raw-v1 \
  --fixture config/warehouse-energy/fixture-v1.json \
  --physics-model config/warehouse-energy/physics-model-v1.json \
  --design config/warehouse-energy/stage3-dataset-design-v1.json \
  --output /tmp/stage3-dataset
python3 scripts/warehouse-energy/audit_stage3_dataset.py /tmp/stage3-dataset \
  --raw /tmp/stage3/stage3-raw-v1 \
  --fixture config/warehouse-energy/fixture-v1.json \
  --physics-model config/warehouse-energy/physics-model-v1.json \
  --design config/warehouse-energy/stage3-dataset-design-v1.json
```

Stage 3A unit tests: `python3 -m unittest test_stage3` from `scripts/warehouse-energy/`
(9 tests: partitions, profile variants, synthetic perfect-observation reconciliation in
both directions, Phase 2 navigation-evidence rebuild, and manifest/rejection handling).
