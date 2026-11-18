# Warehouse energy Phase 1 amended-B semantic repeatability series

**Date:** November 17, 2026 (00:28–01:11 UTC)
**Status:** PASS — three audited repeats for both B-up and B-down against the
amended B-route semantic fixture, with zero planner blocks. Combined with the
A-direction repeats of the original series
([`sam3-repeatability/`](../sam3-repeatability/README.md)), the full
three-repeat matrix for all four route/direction combinations passes; see the
merged `semantic-repeatability-audit.json` in that directory.

## Fixture amendment

The original series established that the B-route red-mat center
`[7.0, 6.3]` m reproducibly blocked Nav2's global planner on the B-up ramp
climb (three genuine planner blocks in eight attempts): the 0.60 m mat left a
0.75 m free strip in the 1.5 m corridor — the same marginal geometry that was
fixed for route A on November 16 by moving the A-route mat from `[4.5, 0.3]`
to `[4.5, 0.5]` m. The amendment moves the B-route red mat from
`[7.0, 6.3]` to `[7.0, 6.5]` m (`scripts/warehouse-energy/build_navigation.py`,
both the world generation and the recorded design), widening the free strip
from 0.75 m to 0.95 m. Controller, planner, behavior-tree, costmap, camera,
prompt, policy, and endpoint configuration are unchanged; the A-route semantic
fixture is untouched, so the A-direction repeats of the original series remain
valid. The original series' B-direction trials are retained as historical
evidence for the old mat position.

## Result

Every audited trial passed both independent audits (`audit_phase1.py` and
`audit_semantic_trial.py`). Cross-run results for the amended B trials:

| Route/direction | Audited passes | Modeled Wh range | Min mask precision | Max plan deviation | Max corridor deviation |
| --- | ---: | ---: | ---: | ---: | ---: |
| B-up | 3/3 | 1.518–1.544 | 97.5% | 0.276 m | 0.172 m |
| B-down | 3/3 | 1.513–1.528 | 99.3% | 0.319 m | 0.204 m |

The maximum plan-centerline deviation on B-up dropped from 0.425 m at the old
mat position to 0.276 m at the amended position, and the B-up planner-block
failure mode did not occur in any of the six amended-B route attempts. All
values remain inside the 0.70 m plan envelope and 0.40 m physical guard.
Modeled Wh values remain outputs of the explicitly assumed energy model, not
measurements.

## Runtime

Same isolated `warehouse-phase1-sam3` pod configuration and pinned endpoint
as the original series (rebuilt pod, telemetry plugin recompiled to the
bit-identical SHA-256 `6d48f4f9…01cca`). The serving credentials rotated on
November 16 remained valid. Three development attempts are preserved under
`failed-attempts/`: all were transient Nav2 global-costmap update timeouts
far from the red mat, the same infrastructure flake documented in the
original series; none was a planner block or an end-of-trial 429 status race.

## Reproduction

Re-run the merged cross-run audit over both series directories:

```sh
python3 scripts/warehouse-energy/audit_semantic_repeatability.py \
  docs/validation/warehouse-energy/phase-1/sam3-repeatability \
  docs/validation/warehouse-energy/phase-1/sam3-repeatability-b-amended
```

The audit merges trials by name, with later directories overriding earlier
ones; each case records its `series_directory` so amended-fixture trials are
distinguishable from the originals.
