# Phase 4 projection and semantic map lifecycle

- **Status: PASS — user review approved on October 16, 2026. Phase 5 authorized.**
- **Authorization:** user requested “Move on to phase 4” on October 16, 2026,
  after approving the Phase 3 review. This authorizes isolated costmap testing,
  not Phase 5 motion or canonical hotel configuration changes. Subsequently, the
  user said “Review approved. Please move on to phase 5.” This separately
  authorizes isolated Phase 5 work, not canonical hotel changes or Phase 6.
- **Recognition:** the Phase 2 development-label/held-out-scoring demo waiver
  remains unchanged. Runtime projection is not recognition qualification.

## Candidate and scope

The repository-local `demo_semantic_costmap::SemanticLayer` is a new, deliberately
narrow Nav2 plugin for the existing fixed `avoid-target/v1` policy. It is not a
ported or qualified version of the upstream plugin. Source is in
[apps/semantic-costmap](../../../../apps/semantic-costmap/).

The [previous upstream audit](../../../nav2-ai-demo-implementation-proposal.md#source-audit-issues-to-resolve)
identified possible raster/temporal-buffer clearing problems at upstream commit
`cf85d3e499af4d389f2aac31e6c8409b424fa417`. Also, that plugin expects
`vision_msgs/LabelInfo`, whereas the executed Phase 3 contract uses versioned
JSON in `std_msgs/String`. The candidate avoids importing confidence accumulation
and arbitrary ontology features not needed by this demo. This is an implementation
choice, not evidence that upstream lifecycle defects have been reproduced.

Selected behavior:

- IDs 0/2 only, fixed generation 1; cost 200 for `avoid_target`.
- Exact mask/cloud/timing joins, strict layout/frame validation, finite depth,
  capture-time TF, height/range filtering, and maximum 640×480 input.
- Maximum merge preserves lethal geometry **and unknown space**. ID 0 adds no
  assertion; an empty detection does not certify a previously marked area free.
- One-second observation lifetime, expiring from capture in either ROS or wall
  time; 500 ms maximum admission age; conservative 2 ms wall-clock allowance.
- At most eight partial pairs and 65,536 observed world cells; full bounded
  raster rebuilding on every update, including the area of disappeared cells.
- Clear, resize, deactivation/reactivation and observed clock rollback invalidate
  the observation epoch. Only later wall captures may rebuild it. A changing
  producer epoch also invalidates old observations after freshness validation.
- Whole-layer `reset()` is supported. Spatial partial-clear operations are
  deliberately excluded (`isClearable() == false`); a raster-only clear would
  not invalidate pending work. The later navigation profile must use a full
  epoch-clearing reset, not rely on partial clear or an enabled toggle.
- Input settings are startup-only; runtime prompt/policy changes remain deferred.

Phase 3 timing receives additive `mask_sha256` and `cloud_sha256` fields. Repeated
ROS timestamps after reset otherwise cannot distinguish delayed old DDS payloads
from new results with the same header. The layer requires hashes; the unchanged
Phase 3 image therefore fails closed rather than silently bypassing this check.
Model weights, prompt, inference backend and navigation policy are unchanged.

## Verification sequence

1. Build and run deterministic tests against real Jazzy `LayeredCostmap` instances
   and verify pluginlib loading. Synthetic observations are integration fixtures,
   not model detections.
2. Only after those tests pass, run the payload-bound SAM3 candidate with isolated
   global-sized and rolling local-sized costmaps. Their fixed robot-base frame
   intentionally excludes localization and moving-robot qualification (Phase 5).
3. Measure capture-to-costmap p95 ≤300 ms, actual update periods, stale-state
   clearing, pairing/admission behavior, and resources. Repeat relevant runtime
   faults because both the consumer and output metadata changed.
4. Store exact source/image pins and raw results. Request reviewer sign-off only
   after all mandatory checks pass; do not infer a pass from implementation.

Build configurations: [layer](../../../../helm/semantic-navigation/phase4-build.yaml)
and [SAM3 binding](../../../../helm/semantic-navigation/phase4-binding-build.yaml).
The [profile renderer](../../../../scripts/semantic-navigation/render_phase4_profile.py)
reuses the pinned Phase 3 simulator/compressor and explicit consumer DDS profile,
but assigns separate Phase 4 resource names, Gazebo partition and ROS domains
81/82. It accepts digest-pinned images only. There is no planner, controller,
RMF dispatch or command publisher in the costmap observer, and camera bridges
do not route velocity commands.

## Results

### Deterministic and runtime builds

- **23/23 deterministic tests pass** against real Jazzy `LayeredCostmap` instances,
  including pluginlib loading: [build 4 log](build-4-passed.log).
- SAM3 payload-binding build passes **27 core and two ROS callback tests**:
  [runtime build log](sam3-binding-build-1.log).
- Build 1 failed on test-harness Jazzy API usage, corrected before execution:
  [log](build-1-failed.log). Build 2 was cancelled as superseded.
- Build 3 passed 19/20 tests, with a faulty missing-TF fixture: `Buffer.clear()`
  retained the static transform. The corrected fixture installs a genuinely
  empty TF buffer; it passes in build 4. This was not an observed failure of the
  layer to reject missing TF. [Failure retained](build-3-test-failure.log).
- The deployed source and library hashes were read back from the running image:
  [installed pins](installed-source-pins-20261016.txt). Nav2 costmap package is
  `1.3.13-1noble.20260903.024922`, ROS Jazzy.

| Artifact | Qualified candidate pin |
|---|---|
| Costmap image, build 4 | `semantic-costmap@sha256:447c6ee36d2eff0707a69133881c4131e0033dab5c38099750844173d416c92f` |
| SAM3 payload binding, build 1 | `sam3-runtime@sha256:478ec01a7a47fbb0c862fbbef495c71b4a512ff59ed8d6ed5b7234422cc35686` |
| Installed plugin library | `sha256:3e0ab378c2ea85918c7529e973d4395b1dce6cff037d4e8dee4f759f58dc6a51` |
| Source revision | Repository-local uncommitted candidate; exact file hashes above, not an upstream plugin commit |

Images reside in the internal `semantic-navigation` registry namespace. The
[rendered manifest](../../../../helm/semantic-navigation/phase4-isolated-costmaps.yaml)
pins both images plus the unchanged Phase 3 simulator and compressor. Server-side
dry run passed before deployment. The maps are 12×12 m fixed and 4×4 m rolling,
both 0.05 m/cell, using the stationary `base_footprint` frame and a 33 ms wall
timer. They contain no planner, controller or inflation layer. The live maps
start as known free space; geometry/unknown merging is tested by deterministic
fixtures, not by claiming the free-grid observer contains the hotel static map.

### Live pilot and lifecycle

The [60-second pilot](pilot-60s-20261016/summary.json) applied 398 distinct results
to each map at 6.62/s. Capture-to-costmap p95 was **251.81 ms global / 252.34 ms
local**; maximum 267.75 / 268.24 ms. There were no rejected results, queue
evictions, not-current updates or epoch changes during the measured window.
Partial-pair occupancy peaked at one. The global/local rasters contained 270/142
marked cells, respectively. Full update records are retained in the linked
directory; these counts are not a recognition score or navigation benefit.

The [live lifecycle run](live-lifecycle-20261016/result.json) passed:

- Explicit clear: both raster and observation state emptied; a late pre-clear
  result was rejected, and subsequent captures rebuilt the maps.
- Deactivate/reactivate: rasters, observed cells and pending pairs remained
  empty for 71 observed updates during the quiescence check; fresh captures
  rebuilt both maps after activation.
- Paused simulation: wall-time expiry emptied both maps **1,031.26 ms** after
  the last capture, below **1,069.10 ms** (T=1,000 ms plus two observed worst
  update periods of 34.552 ms). Both stayed empty while paused and recovered
  after the private world resumed.
- Clock reset: rollback immediately produced an empty raster/buffer epoch, then
  fresh post-reset captures repopulated both maps. The deterministic suite also
  covers repeated ROS stamps with mismatched old payloads, out-of-order input,
  rolling-window eviction and target removal/expiry.

The live reset test invoked the private Gazebo world only. Restoration ran even
on the failure path. The runner compares capture times with **cluster-side**
action timestamps, not the workstation clock. The layer latency measurements
are also cluster-side; [chrony snapshots](clock-before-20261016.json) support the
2 ms cross-node allowance. These snapshots are not continuous clock guarantees.

### Full-grid evidence

The additional [snapshot test](grid-evidence-build-2.log) linked against the
**already-built candidate library**, without rebuilding or replacing the live
plugin. Its [six complete master/semantic rasters and buffer snapshots](grid-snapshots-20261016.json)
cover before marking, marked, reset, delayed pre-reset result, fresh capture and
expiry. They preserve static cost 254 and unknown 255 while semantic cost 200
appears, clears, and does not return from the delayed old observation. Inputs
and clocks are deterministic test fixtures, not AI results or performance data.
The first evidence-only build had a CMake packaging error, corrected by making
the harness a standalone test project: [retained log](grid-evidence-build-1-failed.log).
This did not change the qualified runtime image.

### Ten-minute sustained qualification

The [600.37-second observation run](soak-600s-20261016/summary.json) retained
18,183 update records and 3,957 distinct applied results per map. This includes
the result current at window entry; the in-window acceptance counter increased
by 3,956. No reset or deliberate fault was injected during this measurement.

| Measurement | Global-sized map | Rolling local-sized map |
|---|---:|---:|
| Distinct applied results / measured rate | 3,957 / 6.59 Hz | 3,957 / 6.59 Hz |
| Capture-to-costmap p95 | 252.16 ms | 252.84 ms |
| Capture-to-costmap maximum | 279.48 ms | 280.08 ms |
| Rejections / queue evictions during run | 0 / 0 | 0 / 0 |
| Not-current updates / epoch changes | 0 / 0 | 0 / 0 |
| Maximum partial pairs / observed cells | 1 / 270 | 1 / 142 |
| Costmap update work p95 | 0.622 ms | 0.069 ms |

The common wall update period was 33.275 ms p95 and 40.452 ms maximum. The
capture-to-costmap numbers include the declared 2 ms cross-node allowance and
end after actual master-cost merging, not at inference publication. An
interleaved-callback regression prevents a newly arrived result from receiving
an application timestamp for a raster that was prepared before its arrival.

The [delivery audit](delivery-20261016/summary.json) correlates the publisher's
preserved valid-result records with the actual applied capture stamps over
38.4–638.4 simulation seconds in the stable epoch. **All 3,957 published outputs
appeared in each map (100%)**, without missing, unexpected or duplicate stamps.
This is published-mask/cloud-to-costmap yield, **not** raw-camera-to-model yield;
bounded inference admission continues to skip camera frames intentionally.
Compressed raw publisher records are stored alongside the audit summary, and
full costmap-update records are stored alongside the soak summary, with hashes.

[Resource sampling](resources-600s-20261016.json) collected 27 observations:
the costmap process RSS ranged from 39.23 to 45.45 MiB and ended at 41.94 MiB;
SAM3 process RSS grew by 0.75 MiB (2,003.87 to 2,004.62 MiB). Allocated GPU memory
remained 5,855 MiB. No runaway growth was observed. Kubernetes working-set
metrics also include the `ros2` launcher and diagnostic CLI daemon; they should
not be confused with the layer process RSS. All private containers had zero
restarts at the [final deployed-profile readout](deployed-profile-20261016.json).

The [Gazebo RTF record](rtf-600s-20261016.json) contains 5,664 samples over a
separate overlapping 600-second read-only observation: mean 0.99215, minimum
0.57431, maximum 1.99510. The latency gates use capture wall time, not scaled
simulation time. [After-run clock checks](clock-after-20261016.json), like the
before-run checks, showed normal synchronization and support the 2 ms allowance.

## Disposition and boundaries

The Phase 4 technical gates pass for the pinned, stationary, isolated profile.
The user approved this review and requested Phase 5 on October 16, 2026.
This remains a projection and
costmap-lifecycle qualification, not a claim of recognition accuracy, successful
avoidance, collision safety, or moving-robot localization correctness.

The layer is fixed-policy and restart-configured. Spatial partial clearing and
runtime ontology/parameter changes are not qualified. Phase 5 must integrate a
whole-epoch reset with the real costmap lifecycle and validate the shared
geometric, inflation, stop/watchdog and command-routing profile before motion.
The full hotel map and additional layers require their own runtime checks; the
small observer grids do not qualify arbitrary costmap sizes or update rates.
No OpenShift AI endpoint was deployed; adapter-side hashes leave the separate
backend-serving proposal compatible but unqualified.

**Cleanup verified:** the three private Phase 4 pods, router Service and
diagnostic ConfigMap were removed after retrieving the evidence. The pinned
manifest recreates them; candidate images, build records and the Bound 10 GiB
checkpoint PVC are retained. All three canonical semantic namespace deployments
remained available at 1/1. [Cleanup readout](cleanup-20261016.txt).
No canonical navigation configuration, host sysctl or robot-command route was
changed. Changes remain local/uncommitted; no commit or push was requested.
