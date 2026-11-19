# Energy-aware warehouse navigation: stakeholder summary

**Date:** November 18, 2026  
**Status:** Approved scope (Stages 0–4) **complete**. All gates passed with independent audits;
evidence committed and reproducible.  
**Companion proposal:** [warehouse-ramp-energy-navigation-proposal.md](warehouse-ramp-energy-navigation-proposal.md)
— the approved design, assumptions, and claim boundaries.

For field studies, public models, hardware telemetry, and proposed customer pilots, see [Energy-aware routing for mixed robot fleets](robot-energy-optimization-research.md).

---

## Executive summary

We set out to answer one question: *can a centrally served AI model make a warehouse robot's
energy decisions better than a well-calibrated physics model?* We built the complete pipeline
to answer it — simulation fixture, energy telemetry, calibrated physics planner, training
dataset, offline model training, OpenShift AI model serving, and a 121-mission comparative
experiment — and the answer is precise and honest:

> **The served model makes mission-energy predictions about 15× more accurate than the
> physics baseline (96.8% lower error), with 100% reliability of its uncertainty bounds and
> a safe fallback when the AI endpoint is unavailable. In this fixture it does not change
> which route the robot takes or how much energy it uses — both planners independently pick
> the same optimal corridor — so the demonstrated value is prediction precision and tighter
> battery-reserve decisions, not energy savings.**

No energy-saving claim is made anywhere in this work. All energy values are modeled
simulation outputs under frozen, documented assumptions. Physical battery savings would
require the separately scoped Stage 5 hardware study.

---

## What was built

An end-to-end, evidence-gated enhancement to the existing ROS 2 / OpenRMF / Nav2 / OpenShift
robotics platform:

| Layer | What exists now | Where |
| --- | --- | --- |
| **Warehouse fixture** | A surveyed two-ramp warehouse (short/steep and long/gentle corridors between the same endpoints), qualified robot and payload envelope, physical ramp trials | Stage 0–1 evidence |
| **Energy telemetry** | Observation-only battery accounting (wheel mechanical power → electrical Wh → state of charge) flowing into RMF fleet state | Stage 1 |
| **Calibrated physics planner** | A frozen, calibrated physics energy estimator plus a pre-dispatch route selector enforcing the mission deadline and the battery-reserve floor (including charger access) | Stage 2 |
| **Training dataset** | 96 instrumented runs / 312 labeled segments with frozen train/development/calibration/test partitions | Stage 3A |
| **Learned model** | A small XGBoost residual model (physics + learned correction), trained reproducibly on CPU, frozen as one versioned release | Stage 3B |
| **Model serving** | `energy-predictor-v1` on OpenShift AI: one warm CPU replica, mutual TLS, versioned artifacts, fail-closed client with physics fallback | Stage 3C, **deployed and Ready** |
| **Comparative experiment** | The frozen A/B/C evaluation (distance vs physics vs learned routing) with paired statistics and an explicit AI-value decision | Stage 4 |
| **Demonstration** | A scripted operator showcase with a self-contained HTML summary and a live browser view (noVNC) of the robot making its deliveries | Demo |

---

## The results

**The frozen A/B/C experiment — 121 missions, zero failures** (90 one-way across
payload/direction strata, 15 round trips, 1 fallback demonstration):

| Measure | Distance baseline (A) | Physics planner (B) | Served model (C) |
| --- | ---: | ---: | ---: |
| Mission-energy prediction error (MAE) | — (logged only) | 0.0354 Wh | **0.0011 Wh** |
| Prediction improvement vs physics | | | **96.8%** (target: 20%) |
| Uncertainty allowance for 95% coverage | | 0.0370 Wh | **0.0047 Wh** (8× tighter) |
| Empirical coverage of upper estimates | | 100% | 100% |
| Completion time vs baseline | — | +0.01% | +0.02% |
| Corridor/itinerary agreement | | 100% | 100% |
| Consumed energy (statistically identical across arms) | 0.4382 Wh | 0.4383 Wh | 0.4383 Wh |

**Serving quality (Stage 3C, 11/11 qualification checks passed):** served predictions match
offline inference to 1e-9 Wh on 96 replay segments; wrong-version, malformed, stale, and
out-of-envelope inputs are all rejected; an unreachable endpoint activates the documented
physics fallback (demonstrated live); p95 latency **69.5 ms** against the 250 ms target for
the maximum 32-segment batch.

**Reproducibility:** the training job re-runs byte-identically in the pinned environment; the
serving deployment's container identity is verified from the pod status; every stage's
evidence is independently audited and committed.

---

## What this means for stakeholders

### For operations and customers
- **Trustworthy energy forecasts.** Operators and fleets get "this delivery will consume
  ~0.44 Wh and end at 77.7% charge" estimates that land within half a percent — versus an
  8.4% conservative bias from the physics baseline.
- **Tighter battery-reserve decisions.** Mission acceptance near the reserve floor no longer
  needs an 8× safety margin on the estimate. The learned uncertainty is calibrated, so
  feasibility checks accept more missions *safely* — and reject the ones physics would
  wrongly accept.
- **Graceful degradation.** When the AI endpoint is unavailable, the robot does not stop and
  does not guess: it falls back to the conservative physics planner with its validated
  larger allowance. No mission ever starts on an unvalidated prediction. This was
  demonstrated live, twice.
- **Explainable choices.** Every route decision records why it was made: per-corridor
  estimates, uncertainty, reserve math, model identity and version — inspectable after the
  fact in each mission's selection record.

### For the platform organization
- **A reusable, production-grade pattern for serving robotics ML on OpenShift AI.** This is
  the second model deployed with the custom-serving pattern (after SAM3 semantic inference):
  digest-pinned images, mutual TLS, versioned model artifacts, offline/server parity gates,
  fault-injection qualification, network isolation, and health/latency metrics. The next
  model (any robotics regression/classification task) can follow the same audited rails.
- **Evidence discipline as a deliverable.** Nine gated stages, each with an independent
  audit, frozen configurations, preserved raw evidence, and reproduction instructions. The
  AI-value decision is stated explicitly rather than implied — including the negative result.

### For robotics and data science
- **A complete, reproducible MLOps loop for a physical-domain model:** simulation → labeled
  dataset with frozen complete-run partitions → CPU training with a hash-recorded
  freeze-before-test boundary → served deployment → live A/B/C evaluation → operator demo.
- **A qualified baseline that is hard to beat.** The calibrated physics model is itself a
  deliverable (0.0003 Wh calibration error on controlled runs), and the experiment design
  measures the learned model against it fairly, on matched triplets with paired confidence
  intervals.

---

## The honest boundaries of the claim

1. **No energy saving is claimed.** All arms consume statistically identical energy because
   every planner selects the same corridor — the shortest route is also the energy-optimal
   one in this fixture (both ramps rise the same 0.2 m; the longer ramp only adds time,
   rolling losses, and turns). This is a physics result, recorded as such, and was
   anticipated by the approved proposal.
2. **A routing benefit requires non-equivalent corridors** — for example a second qualified
   surface, or a fixture/payload condition that makes the steep ramp infeasible. The
   selectors, estimators, and evaluation machinery to demonstrate that switch are built and
   qualified; the fixture change is future work.
3. **Accuracy is in-distribution.** The 96.8% figure is on live missions within the
   qualified fixture conditions; on held-out condition combinations (unseen payload and
   route/speed combinations) the offline improvement was 77.4%. Both are simulation results.
4. **Modeled, not measured, energy.** The telemetry converts simulated wheel power to
   electrical Wh under frozen assumptions (60% drive efficiency, 10 W auxiliary, 24 Wh
   battery). Physical battery measurements require the Stage 5 hardware study, which was
   explicitly out of the approved scope.

---

## Investment and reuse

Everything is committed and re-runnable: the fixture generators, trial runners, audits,
training pipeline, serving deployment, experiment harness, and both presentation formats
(HTML summary and live noVNC). The demonstration can be re-staged on demand in ~25 minutes.
The serving endpoint remains deployed in `semantic-model-serving`; the warehouse simulation
and demo pods are reproducible from committed manifests and scripts.

**Evidence index** (all under `docs/validation/warehouse-energy/`):

| Stage | Report |
| --- | --- |
| 0 Baseline and design freeze | [`phase-0/phase-0-report.md`](validation/warehouse-energy/phase-0/phase-0-report.md) |
| 1 Ramp and telemetry qualification | [`phase-1/phase-1-report.md`](validation/warehouse-energy/phase-1/phase-1-report.md) |
| 2 Physics routing and calibration | [`phase-2/phase-2-report.md`](validation/warehouse-energy/phase-2/phase-2-report.md) |
| 3A Simulation dataset | [`phase-3a/phase-3a-report.md`](validation/warehouse-energy/phase-3a/phase-3a-report.md) |
| 3B Offline training | [`phase-3b/phase-3b-report.md`](validation/warehouse-energy/phase-3b/phase-3b-report.md) |
| 3C Serving qualification | [`phase-3c/phase-3c-report.md`](validation/warehouse-energy/phase-3c/phase-3c-report.md) |
| 4 Comparative demonstration | [`phase-4/phase-4-report.md`](validation/warehouse-energy/phase-4/phase-4-report.md) |
| Operator demonstration | [`demo/demo-summary.html`](validation/warehouse-energy/demo/demo-summary.html) (open in a browser) |

**Frozen configuration and artifacts:** `config/warehouse-energy/` (fixture, physics model,
dataset design, experiment design, and the versioned model release).

---

## Recommended next steps

1. **Stage 5 (hardware study)** — instrument a physical robot and qualified ramps; measure
   transfer error of the simulation-trained model; recalibrate or retrain before any
   physical energy-saving claim.
2. **Second surface / corridor divergence** — qualify a differentiated surface on one ramp
   to create the conditions where energy-aware routing changes the chosen corridor; the
   entire selection, evaluation, and demonstration stack is ready for it.
3. **Fleet extension** — multiple robots sharing the served predictor and reserve checks,
   building on the existing OpenRMF coordination.
