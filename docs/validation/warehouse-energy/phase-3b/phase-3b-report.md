# Warehouse energy Stage 3B training report

**Date:** November 17, 2026  
**Status:** **COMPLETE / PASS.** The Stage 3B offline-training gate passed: a reproducible CPU
training job in the pinned pod produced the first deployable residual model as one versioned
frozen release; the independent audit reloaded the artifacts through a separate inference
path, recomputed every held-out metric, and verified a byte-identical retrain. On the
held-out final-test partition (27 missions), physics-plus-XGBoost reduces mission-energy MAE
by **77.4%** versus the frozen physics baseline, against 29.1% for the linear-residual
comparison. Stage 3C (serving qualification) may proceed.  
**Runtime:** Isolated `warehouse-energy/warehouse-qualification` pod (Python 3.12.3,
numpy 1.26.4, scipy 1.11.4, vendored xgboost 2.1.4 with its nccl dependency; single thread,
seed 17).

## Training and selection

The target is the Stage 3A residual: `observed_segment_Wh − physics_segment_Wh` under the
frozen Stage 2 physics model. Inputs are the 14 declared planning-time features only
(geometry, grade profile, ascent and descent, turn magnitude, planned speed, in-segment
stops and dwell, total mass, the physics baseline estimate and planned duration, and the
run-class indicator). Hyperparameters were selected on the **development partition only**,
by mission-energy MAE, over a bounded grid (depth 2–4, 40–160 trees, learning rate 0.05 or
0.1, minimum child weight 1 or 5):

| Model | Selected configuration | Development mission MAE |
| --- | --- | ---: |
| XGBoost residual | depth 4, 40 trees, learning rate 0.1, min child weight 1 | 0.000465 Wh |
| Ridge linear residual | λ = 0.001 on standardized features | 0.001641 Wh |

## Frozen release

[`config/warehouse-energy/energy-model-release-v1/`](../../../config/warehouse-energy/energy-model-release-v1/)
packages the XGBoost artifact, the linear comparison model, the feature schema, the selected
hyperparameters and seed, dependency versions, dataset digest, the physical-bounds rule
(reject to physics fallback when the combined estimate is negative or the correction exceeds
the physics estimate), and the uncertainty calibration as one versioned release. The frozen
portion is hash-recorded (SHA-256
`288b38674dab867a61be51e2d7cd888a2c77c8d18aded70268cc13e8940f286b`) **before** the held-out
test partition is read; the test is opened exactly once, after freezing. Mission-level
uncertainty allowances were calibrated on the separate uncertainty-calibration partition
(13 missions): 0.004713 Wh for the learned mode and 0.037041 Wh for the physics fallback,
each the empirical 95th percentile of mission absolute error, with the 13-mission
finite-sample caveat recorded in the release.

## Held-out evaluation (opened once, after freezing)

The final-test partition holds out complete condition combinations — every scripted run at
payload 0.25 kg (24 missions) and every navigation route-B uphill run at 0.08 m/s
(3 missions), 27 missions and 87 segments in total:

| Mode | Mission MAE | Segment MAE | Max mission error | Bounds rejections |
| --- | ---: | ---: | ---: | ---: |
| Physics only (arm B baseline) | 0.003011 Wh | 0.001163 Wh | 0.027595 Wh | — |
| Physics + linear residual | 0.002133 Wh | 0.001353 Wh | 0.013277 Wh | 0 |
| Physics + XGBoost residual | 0.000680 Wh | 0.000718 Wh | 0.007325 Wh | 0 |

Mission-energy MAE improvement over physics-only: **77.4%** for XGBoost and 29.1% for the
linear comparison. (The Stage 4 acceptance target of at least 20% lower held-out
mission-energy MAE for arm C than arm B is a comparative-experiment criterion; this value is
the offline preview on the Stage 3A held-out partitions, not the Stage 4 result.) The
combined estimate never violated the physical-bounds rule on the held-out partition.
Upper-estimate coverage on the held-out missions: learned mode 26/27 (96.3%, the one miss is
within the small-sample caveat of a 13-mission calibration), physics fallback 27/27 (100%,
with its larger 0.037 Wh allowance).

The learned correction is dominated by the navigation goal-transition structure identified
in Stage 3A (systematic −0.008 Wh per navigation segment against the declared 13.5 s
per-goal planning allowance); the held-out navigation combination (route B uphill at
0.08 m/s) is where the improvement concentrates, while the held-out scripted payload-0.25
missions reconcile with physics near exactly, as expected for controlled profiles.

## Independent audit

[`stage3b-audit.json`](stage3b-audit.json) **PASSES** with zero errors: the frozen hash and
artifact digests verify, no test-derived value appears inside the frozen portion, the
XGBoost booster and linear model are reloaded from their artifacts through an inference
path independent of the training wrappers, all held-out metrics and coverage figures
recompute exactly, the frozen allowances reconcile with the calibration partition, and a
full retraining run reproduces the model artifact byte-identically.

## Assumptions and limits

The model is simulation-trained for the frozen warehouse fixture, robot, payloads, and
single qualified surface; it is not valid across robots, battery systems, or physical
facilities. Labels remain modeled energy under the frozen Phase 1 accounting assumptions,
not physical battery measurements. The uncertainty calibration uses 13 missions, so the
nominal 95% upper estimate carries a finite-sample caveat; Stage 4's frozen evaluation will
report coverage with its own sample counts. No route-choice or energy-saving claim is made
by this stage.

## Reproduction and evidence

Inside the pinned pod (xgboost 2.1.4 vendored at `/work/vendor`, wheel SHA-256
`8df6da72963969ab2bf49a520c3e147b1e15cbeddd3aa0e3e039b3532c739339` with nccl 2.27.7,
`de5ba5562f08029a19cb1cd659404b18411ed0d6c90ac5f52f30bf99ad5809aa`):

```sh
cd /work && PYTHONPATH=/work/vendor LD_LIBRARY_PATH=/work/vendor/nvidia/nccl/lib \
  python3 scripts/warehouse-energy/train_stage3b.py \
  --dataset /work/docs/validation/warehouse-energy/phase-3a/dataset \
  --output /work/stage3b-release --seed 17
PYTHONPATH=/work/vendor LD_LIBRARY_PATH=/work/vendor/nvidia/nccl/lib \
  python3 scripts/warehouse-energy/audit_stage3b.py /work/stage3b-release \
  --dataset /work/docs/validation/warehouse-energy/phase-3a/dataset --retrain
```

Stage 3B unit tests: `python3 -m unittest test_stage3b` from `scripts/warehouse-energy/`
(9 tests; the XGBoost determinism smoke test runs where xgboost is available and skips
elsewhere).
