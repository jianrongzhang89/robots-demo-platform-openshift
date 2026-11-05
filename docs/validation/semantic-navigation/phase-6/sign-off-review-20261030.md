# Phase 6 evidence review and sign-off — October 30, 2026

**Status: SIGNED OFF October 30, 2026 (user).** The reviewer accepted the
result and all five decision items below; the acceptance record is
`phase6-acceptance.json` in this directory. Phase 6 is CLOSED.

## The result under review

**Series-23** (`docs/validation/semantic-navigation/phase-6/series-23-20261029/`,
commit `69d19e09`) — the first complete Phase 6 series, all 58 trials green:

| Gate criterion | Result |
|---|---|
| Nominal pairs | 20/20 per arm, `goal_succeeded` every trial |
| Hull-exposure reduction (≥90%) | **100%** — on-arm aggregate 0.000 m vs off-arm 28.084 m (1.403 m/trial baseline) |
| Collisions | 0 across all 58 trials |
| Negative pairs | target-absent 3/3 pairs, target-removal 3/3 pairs, perception-failure 3/3 pairs with the Phase 5 fault-stop criteria met |
| Infrastructure | 5 liveness deaths, all recovered by the fresh-fixture-pod retry ladder; 0 topology recycles |

The semantic objective demonstrated: the lethal-254 on-arm detoured around
the staged mat completely in every nominal trial (zero samples inside the
ground-truth rectangle; the exposure gate's conservative circumscribed-hull
measure is 0.000 m), while the off-arm baseline crossed it every trial.

## The final candidate (every change individually user-approved)

- **Image chain**: base `125cbd5a` → console `15b900f6` → phase6 + controller
  overlay `348fc584` (nav2_controller patch at `f4108e5`, endpoint-capture
  goal evaluation, 0.20 m tolerance unchanged; sensors-override v4 chain
  unchanged, `.so` hashes verified in-image).
- **Controller**: RPP `lookahead_dist` 0.5 / `min_lookahead_dist` 0.25,
  `inflation_radius` 0.45, `use_rotate_to_heading` disabled (documented
  deadlock). Commits `0a6cf844`, `39a07bef`.
- **Localization**: AMCL particles 2000–8000, alphas 0.1. Commit `dbbbf73f`.
- **Fixture code (ConfigMap-shipped)**: capture-time TF witness, pose-delta
  stationary predicate (`affca80e`), extended liveness ladder (`5fc4735b`),
  completion-divergence record in every trial (`1331c955`).

## Items requiring explicit reviewer decisions

1. **Belief-frame arrival semantics.** The goal checker fires on the
   AMCL-localized pose. Every recorded arrival carries its belief/truth
   divergence (the October 28 fork decision made this visible by design):
   - off-arm: 0.445–0.889 m (mean 0.626); physical goal distance mean 0.587 m
   - on-arm: 0.356–1.161 m (mean 0.804); physical goal distance mean 0.783 m
   - no multi-metre divergences occurred in the passing series (the 2.3–2.7 m
     class appeared only in the root-caused failed trials, series-18/22)

   **Decision**: is a completion whose physical endpoint is ~0.4–1.2 m from
   the goal acceptable for the Phase 6 crossing-task semantics, given the
   divergence is recorded per-trial? (The evaluator's exposure metrics are
   physical-truth and unaffected.)

2. **The intrinsic AMCL y-ambiguity.** std_y grows to ~0.95 m through the
   detour in every trial — a property of the scene's scan ambiguity, not a
   defect the particle/alpha revision removes (it removed the mode-collapse
   failures: 20/20 on-trials clean after 2 consecutive series-killing
   failures). **Decision**: accept as a documented limitation?

3. **The gz-transport capture-trace delivery race.** Intermittent
   per-fixture-session (~10–30%) failure of one topic's gz delivery while
   all others flow; fail-closed at the pre-arm readiness gate; worked around
   by the retry ladder. Root mechanism unresolved (probe pair retained,
   `dataplane-probe-off-1/2`). **Decision**: accept the workaround with the
   root cause open, or require the root-cause investigation first?

4. **Standing waivers and private-fixture deviations** (carried from
   Phase 5 / earlier Phase 6 approvals): the Phase 2 recognition waiver;
   the capture-time TF witness sidecar; the UDP companion path; the
   sensors-system override; the grace/heartbeat-acceleration authority
   mechanics; the render warmup; the liveness retry ladder (infrastructure
   deaths only, never check failures); the stationary pose-delta
   corroboration (native arm gate unchanged).

5. **The lethal-254 framing.** The passing on-arm is the implementation
   plan's exclusion experiment (target_cost 254), demonstrating the semantic
   objective's ceiling — "a model-only restriction is not a production
   safety boundary." The production candidate remains the qualified soft
   cost 200.

## Evidence index

- Complete attempt history (every failure retained and root-caused):
  `docs/validation/semantic-navigation/phase-6/pilot-1-20261026/README.md`
- Series results: `series-1-20261028` … `series-23-20261029` (each with
  per-trial evidence under `trial-runs/`)
- The passing series: `series-23-20261029/series-result.json` (gate
  evaluation, per-arm completion divergence, per-trial records)
- Phase 5 acceptance (entry gate): `phase5-acceptance.json`
- The session fork that shaped this result: `HANDOFF-20261028.md`

## On acceptance

If the reviewer accepts the items above, the acceptance record is written
as `phase6-acceptance.json` (mirroring `phase5-acceptance.json`: passed,
accepted gates, sign-off date/commit/reviewer, evidence links) and Phase 6
closes.

**ACCEPTED October 30, 2026** — the reviewer signed off on the document as
drafted: the series-23 result and all five decision items (belief-frame
arrival semantics with the per-trial divergence record, the intrinsic AMCL
y-ambiguity, the gz capture-trace race workaround with its root cause open,
the standing waivers and private-fixture deviations, and the lethal-254
exclusion framing). See `phase6-acceptance.json`.
