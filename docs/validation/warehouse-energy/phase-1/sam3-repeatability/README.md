# Warehouse energy Phase 1 semantic repeatability series

**Date:** November 16–17, 2026 (22:15–23:55 UTC)
**Status:** PARTIAL — eleven audited passing trials. A-up, A-down, and B-down
each passed three repeats; B-up passed two of three. The B-up r3 slot could not
produce a third audited pass because the B-route red-mat position `[7.0, 6.3]` m
reproducibly blocks Nav2's global planner on the ramp climb; the series was
stopped with user approval after six attempts at that slot.
**Runtime:** The isolated `warehouse-phase1-sam3` pod (pinned images, ROS
domain 188, GZ partition `warehouse_semantic_phase1`), the pinned
`sam3-mat-v1` mTLS endpoint, frozen `red mat` prompt and `avoid-target/v1`
policy, 320×240 at 10 Hz, high payload (0.50 kg), RTF 3 — the same qualified
configuration as the four accepted single runs reported in the
[phase 1 report](../phase-1-report.md). The telemetry plugin was recompiled in
the pod to a bit-identical SHA-256 (`6d48f4f9…01cca`) matching the accepted
series. The serving credentials were rotated before the series
([rotation record](../../semantic-navigation/security/g5-credential-rotation-20261116/));
no other cluster state was changed.

## Result

Every audited trial passed both independent audits (`audit_phase1.py` and
`audit_semantic_trial.py` against the non-semantic A-up baseline), including
RGB-D transport at 10.0 Hz, capture-time TF, energy/SOC reconciliation, RMF
task completion, all Nav2 goal terminals, semantic mask precision/coverage,
and the lethal-cost detour envelopes. The cross-run summary
(`semantic-repeatability-audit.json`, produced by
`scripts/warehouse-energy/audit_semantic_repeatability.py`) reports:

| Route/direction | Audited passes | Modeled Wh range | Min mask precision | Max plan deviation | Max corridor deviation |
| --- | ---: | ---: | ---: | ---: | ---: |
| A-up | 3/3 | 0.594–0.629 | 96.7% | 0.272 m | 0.201 m |
| A-down | 3/3 | 0.593–0.610 | 99.7% | 0.323 m | 0.202 m |
| B-up | 2/3 | 1.541–1.554 | 99.0% | 0.425 m | 0.312 m |
| B-down | 3/3 | 1.532–1.537 | 99.5% | 0.465 m | 0.316 m |

All values remain inside the existing 0.70 m plan envelope and 0.40 m physical
guard. Modeled Wh varies by at most 0.035 Wh within a route/direction. These
remain outputs of the explicitly assumed energy model, not measurements.

## B-up repeatability finding

The B-up r3 slot accumulated six preserved attempts
(see `development-attempts.md`): three genuine mat-corridor planner blocks at
the same ramp position (planner start ≈ (5.5, 5.9), goal `b_top`, `Failed to
create a plan from potential when a legal potential was found`), two
end-of-trial inference HTTP 429 status races, and one costmap-update timeout.
Three genuine planner blocks in eight total B-up route attempts establish that
the B-route red-mat position `[7.0, 6.3]` m — unchanged from the accepted
single-run series — leaves a free strip that Nav2 cannot reliably traverse.
This reproduces, on route B, the failure mode that was fixed for A by moving
the A-route mat from `[4.5, 0.3]` m to `[4.5, 0.5]` m. **The B-up
repeatability gate remains open** until the B-route mat is repositioned and
the B-up repeats are re-run against the amended fixture.

## Infrastructure observations (not gate evidence)

- The pinned model server admits one inference at a time and immediately
  rejects concurrent arrivals with HTTP 429 (`apps/semantic-model-server/server.py`).
  With the qualified 10 Hz request rate, the adapter's instantaneous status at
  trial end has a substantial chance of recording a rejected request even
  though valid results flowed throughout the run; the independent semantic
  audit checks that final status snapshot and therefore fails such runs. Four
  otherwise-complete trials were excluded for this reason alone.
- Five trials were excluded for transient Nav2 global-costmap update timeouts
  (`Costmap timed out waiting for update`) under RTF 3, concentrated on route B.
- Each trial leaves unreaped zombie process entries in the pod (the container's
  PID 1 does not reap); zombies are inert and were ruled out as a failure cause.

## Reproduction

Each `semantic-320-<route>-<direction>-r<N>` directory is a complete trial
record (design, world, logs, traces, audits). Failed attempts are preserved
under `failed-attempts/` and are excluded from the series. Re-run the
cross-run audit with:

```sh
python3 scripts/warehouse-energy/audit_semantic_repeatability.py \
  docs/validation/warehouse-energy/phase-1/sam3-repeatability
```

Re-run any single trial's independent audits with `audit_phase1.py` and
`audit_semantic_trial.py` as documented in
`scripts/warehouse-energy/README.md`.
