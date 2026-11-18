# Warehouse energy Phase 0 report

Date: 2026-11-16. **Status: COMPLETE / PASS for the frozen simulation fixture.**

The hotel baseline, 36-trial ramp/payload matrix and four live RMF/Nav2 route
trials passed, including independent replay audits. The fixture and numerical
evaluation targets are frozen for Stage 1. This is not energy-model, warehouse
perception, hardware or production qualification.

The approved work is the warehouse proposal's Stage 0 (baseline and design
freeze). Existing hotel profiles remain unchanged. New files are confined to
`config/warehouse-energy`, `scripts/warehouse-energy` and this evidence directory.

## Results

| Work item | Result | Evidence |
| --- | --- | --- |
| Pin actual deployed hotel environment | Captured Helm revision 45, image digests, mounted sources, generated world/URDF/graph, fleet configuration, package versions and asset hashes | [baseline snapshot](baseline-20261116/inventory.json), [checksums](baseline-20261116/sha256.json) |
| Compare live configuration with repository | All 15 corresponding mounted sources match apart from terminal newlines | [comparison](config-drift.json) |
| No-motion served-SAM3/Nav2 preflight | PASS; 9 lethal mat samples, 575 path poses, 0.5188 m minimum planned hull clearance | [preflight](live-preflight.json) |
| Fresh monitored hotel round trip | PASS, including independent physical audit; L1 → L3 → L1, final position 0.025 m from spawn | [result](live-baseline-result.json), [audit](live-baseline-audit.json), [summary](live-baseline-summary.json) |
| Installed RMF route spike | PASS for ordered waypoint sequences, routes A/B × uphill/downhill; no motion or dispatch | [spike](rmf-route-spike.json) |
| Bounded robot and ramp/payload envelope | 36/36 independently reset trials and separate raw-data audit PASS | [ramp audit](qualification-20261116/ramp-audit.json), [summary](qualification-20261116/ramp-summary.json) |
| Fixture design | v1 records the qualified simulation envelope and unchanged energy targets | [fixture v1](fixture-specification-v1.md), [machine-readable fixture](../../../../config/warehouse-energy/fixture-v1.json) |
| Live warehouse route integration | 4/4 route/direction trials PASS; 20/20 Nav2 goals succeeded; accepted schedules and physical paths agree | [independent route audit](qualification-20261116/navigation-audit.json), [series](qualification-20261116/navigation-series-result.json), [raw evidence regenerated per the storage policy](../README.md) |
| Early energy sensitivity | Short route A wins 162/162 uncalibrated cases; no learned-value claim | [calculations](sensitivity.json) |
| Local checks | 15 warehouse checks pass; 20 existing Phase 8 regressions passed in the baseline work | [warehouse test log](qualification-20261116/local-tests.log) |
| Hotel preservation | All 17 captured mounted configuration entries unchanged | [preservation check](qualification-20261116/hotel-preservation-check.json) |

## Findings that affect implementation

The new patrol `patrol.dispatch-34239631f4` finished idle on L1. The independent
audit measured 0.648 m minimum physical mat clearance, 0.0101 m maximum cabin
support gap, and 0.716 m maximum fleet/physical position disagreement against
the inherited 0.750 m limit. That last metric has little margin and should be
tightened in the lower-speed warehouse fixture. There were 23 moving semantic
plans after returning to L1. The terminal SAM3 status was not Ready, although
the trial and audit passed under the inherited fixed-scene semantic-memory
policy. This is a passing navigation reproduction, not a healthy-serving SLA.

The November 11 accepted baseline used Helm revision 26 and ended at the named
lobby waypoint. The current source audit expects the newer `phase8_spawn`
endpoint. Replaying the old evidence through current code therefore fails only
the final endpoint test: 4.537 m from spawn, versus the original audit's 0.049 m
from lobby. Preserve the [failed replay](historical-audit-current-code.json) and
the [original accepted audit](../../semantic-navigation/phase-8/multilevel-recovery-fix-20261111/audit.json).
Do not overwrite either result or represent that replay as a fresh validation.

The live revision 45 hotel image is
`phase8-multilevel-fix@sha256:46042806035753067de14010aff4eb5d2c63e929f7c5a93e1c139311ee06c99e`.
Its installed packages include RMF fleet adapter 2.7.2, Nav2 1.3.13 and Gazebo
Sim CLI 8.15.0. Contrary to the proposal's compatibility uncertainty, `nav2-route`
is installed. Retain ordered RMF activities for the initial route implementation;
the package inventory does not prove Route Server integration.

SAM3 serving intermittently reported HTTP 429, disconnected connections and
capture expiry at inspection, and its client was not Ready at snapshot time.
The no-motion trial subsequently passed using live served results. Neither that
pass nor the hotel round trip constitutes serving availability qualification.
The snapshot records the actual server/client image IDs and status without
exporting credentials.

The inherited physical robot is a custom 1.653 kg SDF model. Its URDF/RMF
parameters are not equivalent to physical mass or geometry, and its drive was
effectively unbounded. The isolated warehouse generator now replaces that drive
with force-mode wheel controllers capped at ±0.080 Nm, corrects separation to
the SDF's 0.288 m, and adds physical payload mass/inertia. The 0/0.25/0.50 kg
matrix passed on the 0.20 m-rise ramps. The proposal's 1 m rise remains
unqualified. An energy result still requires independent electrical
instrumentation and calibration.

The first full-warehouse B-up run exposed an upper-deck box overlapping the
rising ramp, creating a collision lip. The robot stalled under bounded effort;
Nav2 reported failure to make progress and the task was cancelled. The corrected
deck ends at the ramp boundary. All four route/direction cases were repeated and
passed in the corrected world. [Development attempts](qualification-20261116/development-attempts.md)
remain separate from final qualification counts, including an earlier invalid
all-zero actuator trace caused by sampling after physics cleared force commands.

## Stage 0 exit evidence

1. **Closed:** bounded drive and ramp/payload qualification, including slope
   braking/hold/restart, full-pose support, chassis clearance and raw torque audit.
2. **Closed:** corrected-world four-case RMF/Nav2 route series and independent
   replay audit of accepted schedule, goal and physical records. All 20 goals
   succeeded; maximum final position error was 0.0563 m and maximum physical
   centerline deviation was 0.0580 m. Native joint velocities confirmed stopped
   wheels at every completion.
3. **Ownership resolved:** Codex owns implementation and simulation validation;
   fixture v1 is reviewed against the protocol, raw audit and automated checks.
   No separate human sign-off is claimed. Hardware access is unknown and outside
   the approved simulation scope.

The proposal lists detailed ramp traversal under Stage 1 while also requiring
capability and itinerary agreement during Stage 0. The minimal isolated world
and bounded-drive work supplies that Stage 0 evidence. Warehouse perception,
electrical energy telemetry, calibrated parameters and reserve accounting remain
Stage 1/2 work. No training, energy serving or comparative evaluation has started.

| Final case | RMF task | Nav2 goals | Result |
| --- | --- | --- | --- |
| A uphill, 0.50 kg | `compose.dispatch-56f2510a55` | 5 succeeded | PASS |
| A downhill, 0.50 kg | `compose.dispatch-4869ac638d` | 5 succeeded | PASS |
| B uphill, 0.50 kg | `compose.dispatch-97db25e9cb` | 5 succeeded | PASS |
| B downhill, 0.50 kg | `compose.dispatch-dc7f709d75` | 5 succeeded | PASS |

The route graph includes both ramps throughout. The selected corridor is
enforced through ordered RMF activities and a matching static Nav2 map. Each
trial captures both `/rmf_traffic/itinerary_set` and schedule-server
`/rmf_traffic/query_update_1` data, with real goal UUIDs and full physical pose.
The simulation currently has known empty corridors and fixed admission SOC;
warehouse SAM3 and battery-reserve claims are explicitly excluded.

## Reproduction

From the repository root, capture into a new directory (the tool refuses to
overwrite an existing snapshot):

```sh
python3 scripts/warehouse-energy/capture_baseline.py --output /tmp/warehouse-baseline-new
python3 scripts/warehouse-energy/design_check.py config/warehouse-energy/fixture-v0.json --output /tmp/warehouse-sensitivity.json
python3 -m unittest discover -s scripts/warehouse-energy -p 'test_*.py' -v
python3 -m unittest discover -s scripts/semantic-navigation -p 'test_phase8_*.py' -v
```

Run `rmf_route_spike.py` with `fixture-v0.json` inside the pinned hotel image,
after sourcing `/opt/ros/jazzy/setup.bash`. It only constructs an in-memory graph
and planner; it does not publish ROS commands or mutate the running graph.

The live preflight command used the explicit Running pod, avoiding a stale Error
pod that `oc logs deploy/...` sometimes selected:

```sh
oc exec -n semantic-navigation phase8-multilevel-hotel-85c7bd7b79-rlz5j -c hotel-nav2-rmf -- bash -lc 'source /opt/ros/jazzy/setup.bash; source /opt/rmf_demos_ws/install/setup.bash; python3 /opt/ros2-demo/scripts/phase8_multilevel_trial.py --preflight-only --output /tmp/warehouse-phase0-preflight.json'
```

The monitored patrol uses the same executable with `--dispatch --timeout 2400
--output /tmp/warehouse-phase0-baseline.json`. It dispatches a real simulated RMF
task with the inherited independent physical monitor and cancellation checks.
Reproduce from a fresh initialized hotel fixture, with the robot idle at L1
spawn, no active task and current serving identity. Inspect the captured config,
images and hashes before rerunning; do not assume any future live release matches.

Replay the final result with `python3 demo/phase8_multilevel_audit.py <result>`.
The retained generated world references assets in the digest-pinned image;
image retention and the referenced TLS Secret are required for restoration.

For the warehouse, follow the [qualification tools](../../../../scripts/warehouse-energy/README.md).
Regenerate the navigation series with `run_navigation_matrix.py` (see the [storage policy](../README.md)) and run:

```sh
python3 scripts/warehouse-energy/audit_routes.py /tmp/warehouse-audit/navigation-series-v2 \
  --output /tmp/warehouse-audit/navigation-audit.json
```

All trial process groups are stopped after the series. The isolated
`warehouse-energy/warehouse-qualification` pod is retained idle for subsequent
work; no trial continues in the background. Phase 1 starts with warehouse sensor
integration and independently validated electrical-energy telemetry, using this
qualified motion fixture and preserving the accepted hotel baseline.
