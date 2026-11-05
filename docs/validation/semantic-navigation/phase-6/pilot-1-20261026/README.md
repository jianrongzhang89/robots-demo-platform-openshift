# Phase 6 pilot 1 — semantic-on stationary smoke (October 26–27, 2026)

Scope: Step 1 of the user-approved Phase 6 execution plan (October 26,
2026): semantic-on guarded profile + stationary wiring/clearing smoke on the
frozen guarded GPU profile, before any pilot pairs. The private SAM3
topology for this pilot is managed by `phase6_topology.py` (demo pod
`semantic-phase6-sam3` saved/deleted, restored on teardown) in
`sam3-topology/`. No goal is dispatched in any smoke attempt; the native
guard stays disarmed. These are smoke diagnostics, not Phase 6 trials.

Frozen profile: console image chain `semantic-safety-console-phase6`
(Phase 5 console build 26 `f854b838…` base + the Phase 4-qualified
`demo_semantic_costmap` plugin as an overlay), pinned node
`ip-10-0-44-146.ec2.internal`, GPU rendering, 2 ms physics, 12 m virtual
lidar, 200 Hz odometry, rear casters, console-only server, contact audit;
SAM3 `478ec01a…` on `ip-10-0-18-251.ec2.internal`, prompt `red mat`;
crossing goal (19.402, −31.594), mat ground truth
x∈[16.9514, 17.8514], y∈[−31.919, −31.269].

## Pilot pair 1 (Step 2) — CLOSED (user-accepted October 28, 2026)

The pilot pair is closed with its findings accepted as the pilot's
result; the mid-route renewal race is recorded as the series-entry work
item. The pilot demonstrated:

1. **The off arm passes completely** (`pair-1-off-tfwitness-3`: all 32
   checks, `goal_succeeded`, 4.03 m, baseline hull exposure **1.415 m**
   over 1720 in-rectangle samples — the scene is interpretable).
2. **The on arm's semantic objective is achieved at lethal cost 254**
   (`pair-1-on-lethal254`: hull exposure **0.000 m** — a 100% reduction
   against the ≥90% series gate — zero samples inside the mat, and the
   circumscribed hull cleared the mat by ~5 cm). At the qualified soft
   cost 200 the contrast is nil (`pair-1-on-globalonly`: 1.448 m, the
   planner only nudging its plan ~0.4 m) — the implementation plan's
   anticipated fork, resolved by its defined exclusion experiment.
3. **The mechanical chain works end-to-end in both arms** — after the
   GC fix, the drain-before-tick reorder, the user-approved capture-time
   TF witness (the fixture's own `/tf` reader saturates to ~430 ms at
   mat-close; the witness renews at ~1.4 ms), the user-approved
   global-only semantic layer (the local map's semantic subscription
   loaded the controller's process past its 100 ms command authority),
   and the stationary smoke re-passed under the global-only candidate
   (`smoke-globalonly`, all 24 checks).
4. **The mid-route renewal race — CLOSED (October 28, 2026, later the same
   day):** the one-shot admission-scheduling grace (user-approved;
   `COMMAND_GRACE_NS` = 25 ms, once per source, only when the ledger holds a
   newer validated source) plus the rotation provenance fix (the ledger's
   source record accepts pre-monitor magnitudes; the applied bounds are
   unchanged at resolve/gate/lease) closed it end-to-end:
   `pair-1-on-lethal254-grace3` **passes all 33 checks with `goal_succeeded`
   and 0.000 m exposure** — the grace saved 2 mid-route races in that run
   and 4 in its predecessor. A topology creation race (the SAM3 pod's zenoh
   bridge dialing before the router listens — half-alive control plane, dead
   data plane) was also root-caused and fixed in `phase6_topology.py`.
   Requalification scope recorded with the grace: command-expiry fault bands
   may shift by at most 25 ms in modes where the smoother keeps publishing;
   the controller-silence class is unchanged.

Recognition caveats carried forward: the registration contract
degrades on the shifted (detour) views (pooled 0.688 vs 1.0 from the
baseline lane; sub-cell edge bleed, no cost cell outside the rectangle
— `pair-1-on-bleedmap`), under the standing Phase 2 recognition
waiver. The lethal-cost arm is the plan's exclusion experiment, not a
production boundary ("a model-only restriction is not a production
safety boundary").

## Attempt history (every failure retained, no motion in any attempt)

| Attempt | Image | Outcome | Root cause |
|---|---|---|---|
| 1 (`smoke-attempt-1-validation-order`) | `4b91594f…` | fixture died at validation, before Gazebo startup | fixture code bug introduced this session: the Phase 6 arm validation referenced the geometry env vars before they are parsed (UnboundLocalError); fixed in the same commit series, check moved next to the SAM3 geometry gate |
| 2 (`smoke-attempt-2`) | `4b91594f…` | plan request aborted: NavFn error 207 "Costmap timed out waiting for update"; `phase6_semantic_wiring` PASSED (both costmaps subscribed all four semantic streams; both `semantic_layer_raw` topics present) | the semantic layer's `isCurrent()` only turns true once a fresh observation is ACCEPTED (within its 500 ms window) and that gates the costmap currency NavFn waits on; at plan time every observation was still being rejected, so the costmap was never current. Fixture now gates the plan request on accepted soft costs + a sustained result streak |
| 3 (`smoke-attempt-3`) | `4b91594f…` | 60 s honest timeout of the new plan gate; every semantic observation rejected `stale_or_wrong_identity` (~7/s — payloads complete; ages healthy 190–380 ms) | aggregate reason not diagnosable from logs; the layer's rejection reasons were split (same conditions, same order, no policy change) |
| 4 (`smoke-attempt-4`) | `575154a8…` | every observation rejected `labels_invalid`, `labels_valid=0`, wall_age 190–381 ms, sim_age 132–286 ms | the label_info transient-local latch is not reaching the costmap nodes' layer subscription. A separate read-only diagnostic pod (fresh 85-bridge + transient-local `ros2 topic echo` on domain 85) PROVED the latch crosses the bridge with this exact config (`phase6-label-diag`, deleted after the check), so the mechanism works in a quiet pod; the costmap-side reception path differs. `receiveLabels` instrumented (arrival bytes + failing sub-check) to disambiguate |
| 5 (`smoke-attempt-5`) | `1dd9e055…` | plan gate honest 60 s timeout again; the `receiveLabels` instrumentation logged NOTHING in either costmap — the label_info callback never fired, so the latch never arrives at the costmap nodes at all (arrival, not validation). Run lasted ~47 s sim | the same bridge config delivers the latch to a transient-local subscriber in a quiet diagnostic pod (`phase6-label-diag`, PROBE_EXIT=0, correct JSON). Late-vs-early subscriber timing test in progress |

| 6 (`smoke-attempt-6`) | `1dd9e055…` | wiring check timed out on the relay status — but the retained costmap logs prove the FIX CHAIN WORKS: `label_info received bytes=164 valid=1` and observations ACCEPTED (`accepted=215 rejected=4`, healthy ages) | two fixture bugs masked the working chain: (a) the relay mounted the shared volume at `/tmp/phase6-sam3-shared` while the fixture mounts (and reads) `/tmp/phase5-sam3-shared`, so its status was invisible; (b) the mat mover's hardcoded `z=0.2` lifted the 0.012 m slab past the layer's map-frame height filter (`max_height 0.15`) — every accepted observation projected `projected_cells=0`. Both fixed (mover takes an explicit model z; the fault post keeps 0.2) |
| 7 (`smoke-attempt-7`) | `1dd9e055…` | wiring check PASSED including the relay status (received=1, published=1); BOTH costmaps carry live semantic cells (global 253 / local 156 marked, `master_unknown=0`, matching the demo D1 counts); plan gate still timed out and swallowed its reason | the costs-gate predicate records no diagnostics — instrumented (last pull summary + worker streak retained on timeout) for attempt 8 |
| 8 (`smoke-attempt-8`) | `1dd9e055…` | gate diagnostics added; pull fails with `'str' object is not callable` | the action-endpoint inventory loop `for service, types in ...` shadowed main's `service()` helper with a string — every call after that block (including the grid pull) raised TypeError; the lifecycle `activate()` calls run before the loop, which is why they always worked. Renamed the loop variable |
| 9 (`smoke-attempt-9`) | `1dd9e055…` | traceback captured, confirming the shadowing at the `service(...)` call site | same root cause, fixed |
| 10 (`smoke-attempt-10`) | `1dd9e055…` | **PASS — all 24 checks** | — |

## Stationary smoke result (attempt 10, October 27, 2026)

The Phase 6 semantic-on stationary wiring/clearing smoke passes on the
frozen guarded GPU profile with the console-phase6 image `1dd9e055…`
(base build 26 + the semantic plugin overlay + label diagnostics):

- `phase6_semantic_wiring` PASS — both costmaps subscribe all four semantic
  streams; both per-layer publishers present; label relay delivered the
  transient-local latch (received=1, published=1).
- `phase6_semantic_costs_at_target` PASS — 253 global soft-cost cells, ALL
  inside the ground-truth mat rectangle (+0.15 m margin, zero outside),
  156 local cells, only free/soft/unknown values on the layer grids.
- `phase6_stationary_smoke` PASS — the staged mat was removed through the
  pre-warmed mover (correct model z) and the stale semantic cells cleared
  in **1084 ms**, within the Phase 4 expiry bound of **1766 ms**
  (observation lifetime 1.0 s + 2 update periods + measured p95 capture
  age 216 ms + publish period + margin).
- `phase6_smoke_registration` PASS — 67 stationary pre-removal results,
  379,102 projected points, **100% inside the mat rectangle**.
- `sam3_observation_timing` PASS — 6.90 results/s (≥5), p95 capture age
  216 ms (≤500).
- Disarmed throughout: `native_never_armed_and_robot_stationary` PASS, no
  clock fault, settled support geometry PASS.

This closes Step 1 (semantic-on guarded profile + stationary smoke). The
smoke is diagnostic evidence, not a Phase 6 trial; the paired moving
pilots follow.

## Pilot pair 1 (Step 2)

### The GC breakthrough and the corrected mat-close /tf blocker

**The deterministic x≈16.5 failure was Python's cyclic garbage collector.**
The joiner per-row diagnostics plus the stage timings proved it directly
(pair-1-off-joindiag-2): a single 53.4 ms observer-stage pause — a gen-2
collection over the evidence/message heap — ended 6 ms after the
`command_expired` trip, while the in-window checked renewal sat unprocessed
in the joiner and expired in its 20 ms window through the same pause.
Allocation-driven collection timing explains the determinism. With the GC
disabled (and the earlier drain-before-tick reorder), **the robot crossed
the historical x≈16.5 barrier for the first time and drove ONTO the mat**
(pair-1-off-gcfix: x=17.174, pump pauses ≤10.9 ms, the admission chain
clean deep into the crossing).

**Remaining blocker — CORRECTED ROOT CAUSE (October 28, 2026): the mat-close
`/tf` delivery delay into the fixture, NOT a scan-delivery outage.** The
gcfix evidence was re-analyzed end to end and the earlier scan-outage
narrative is wrong on both of its legs:

- **The scans never stopped.** All 215 scans (stamps 0.2→21.6) arrived
  contiguously at the fixture with a 26–45 ms capture-clock receipt lag —
  through the failure and after it. The "~600 ms outage" was end-of-run
  truncation: the last scan is stamp 21.6 and physics then ran to sim 22.2
  while the trial tore down (the parameter bridge exits before Gazebo).
  The "AMCL kept receiving (a map→odom edge for 21.80 exists)" observation
  was AMCL's `transform_tolerance: 0.2` stamp offset on that same last scan
  21.6 — AMCL saw no scan the fixture missed. The post-failure tf trace
  rows (stamps 20.6–21.6, qualified after the stop) had been mistaken for
  pre-failure renewals because the trigger's steady→wall anchor was
  computed from the final native status, which was published 1.65 s after
  its physics capture during the teardown stall.
- **What actually starved:** the fixture TF buffer's odom→base stamps fell
  90–110 ms of simulation time behind the scan stamps as the robot closed
  on the mat (per-scan lookup retry attempts grew 3→37 across stamps
  18.5→20.5). The scan period is 100 ms of sim time, so once the deficit
  crossed it, every capture-time map→lidar_frame lookup was superseded by
  the next scan before the bracketing odom→base edge arrived (stamps
  20.3–20.5: 32/33/37 attempts, never resolved). The last qualified
  renewal was scan 20.2; the 500 ms tf lease expired ~500 ms later →
  `tf_stale` at wall 563.828 with the robot on the mat (x=17.174). After
  the goal cancel dropped Nav2 to idle, the deficit recovered (attempts
  34→1 over stamps 20.6→21.3).
- **Exonerated by the same evidence:** the frame bridge (its status
  reports odom receipts 0.8–9.4 ms fresh and stamps 1.6–10.6 ms behind
  real time through the failure window; the 726 ms worst lag was early
  startup `clock_stale`), the fixture's own `/robot_1/odom` DDS receipt
  (3.1 ms), the fixture pump (round period p50 5.9 ms / max 23.8 ms, no
  stage over 10.9 ms), the cgroup (zero throttled periods), and `/clock`
  (the joiner diagnostics show now.ros == native sim throughout).
- **The delay is confined to `/tf` delivery into the fixture.** The
  map→odom edges ride the same topic and the same reader: their receipt
  lag behind the scan-linked issuance grew from ~0–6 ms (sim <18) to
  p50 96 ms / max 184 ms (sim 20–22) while AMCL stayed at 4.2% CPU — the
  reader-side delay, not AMCL processing, grew at mat-close.
- **Load correlation:** the SAM3 selected-pixel count grew from ~4k to
  ~67k average (max 94,908) as the mat filled the camera view — the
  mat-close semantic payload growth is the Phase 6 novelty (the Phase 5
  observation series never drove onto the mat). At the failure the
  fixture process ran at ~94% CPU (its busy pump) and the console server
  at ~120%; the pod total stayed under its 8-CPU limit.

The reliable-QoS scan/odom subscription attempt and revert
(pair-1-off-scanreliable) remains factual history — the sensor bridge's
publishers are best-effort, so a reliable subscriber does not match — but
its premise (lost scans) is now disproven; a gz→DDS scan forwarder would
not have addressed this failure.

**Next step (instrumented off-arm diagnostic, `--phase6-tf-probe`):**
localize the `/tf` delay's exact drop point — (a) per-message odom→base
arrival rows recorded in the fixture (`tf-edges.json`), (b) the frame
bridge's TF producer trace (`FRAME_DIAG` rows in `frames.log`, row cap
raised to cover the failure window), and (c) a read-only `/tf` prober
sidecar (`phase6_tf_prober.py`, own CPU quota) as a disinterested third
reader on the safety domain. Prober prompt + fixture late ⇒ delay is
specific to the fixture process (its reader/executor scheduling under the
~94% busy pump); prober lagging identically ⇒ writer-side or
loopback-level. The prober is diagnostic-only and changes no gate or
threshold.

**RESULT (pair-1-off-tfprobe, October 28, 2026): the drop point is the
fixture process itself.** The failure reproduced identically (`tf_stale`,
terminal 5, robot on the mat, every other check passing) and the three-way
probe split the chain definitively, per odom stamp against the native
capture clock:

- **Frame bridge (writer):** odom receipts 0.2–1.7 ms after capture,
  `sendTransform` complete ~0.5 ms later — prompt and cheap throughout,
  including the failure window. Writer-side exonerated.
- **Prober sidecar (third reader, own process and quota, same pod, same
  domain, same QoS shape):** 0.7–3.6 ms throughout. Loopback and Cyclone
  delivery exonerated.
- **The fixture's `/tf` arrival:** p50 5 ms at −13 s, 10 ms at −6 s
  (mat entering view), then 25 → 53 → 115 → 153 → **179 ms (max 208) at
  the trigger**, recovering to 7.5 ms by +1.5 s after the goal cancel.
  The curve tracks the fixture process's own CPU (88% early → 95% at the
  failure → 32% post-stop) while its pump round period stayed p50 5.9 ms
  — the pump did not slow down; the process saturated. The 57 stamps
  missing at the fixture were all at +1.6…+2.1 s (teardown), not part of
  the failure. The fixture's `/robot_1/odom` receipts and the odom lease
  stayed healthy, and `/clock` tracked native sim throughout (joiner
  diagnostics) — `/tf` starves first because its effective tolerance is
  the ~100 ms sim scan window (the capture-time lookup must resolve
  before the next scan supersedes it), far tighter than the 500 ms
  leases.

**Mechanism (established):** the mat-close SAM3 load (selected pixels
~4k → ~67k average) grows the fixture process's work until its single
GIL/Cyclone domain nears saturation; its `/tf` reader delivery develops a
nonlinear queue (the classic knee just below 100% utilization) while an
identical idle process receives the same messages in ~1.4 ms. This is a
private-fixture evidence-path capacity limit, not a robot-chain defect:
Nav2's own TF consumers run in separate processes and the transport is
prompt. The guard stopped the robot fail-closed on its own evidence
pipeline's saturation, exactly as designed.

**Open micro-mechanism question (does not change the remedy decision):**
whether the queue forms in the fixture's Cyclone receive thread (lock
contention with the pump's ~2600 waitset rebuilds/s across ~15 readers,
growing as more action/service entities go live) or in the rclpy
executor's GIL arbitration with the UDP-status, gz contact-audit and
graph-audit threads. The exact split can be measured later; both point to
the same remedy families: reduce the fixture process's per-message work,
or move the supervisor's TF evidence consumption to its own process
(mirroring the qualified UDP companion path and observation-worker
patterns). Any change to the supervisor's evidence path requires user
approval and an explicit fail-closed contract (witness loss ⇒ `tf_stale`,
never optimistic authority).

**Remedy approved by the user (October 28, 2026): the capture-time TF
witness sidecar.** A small own-quota process
(`apps/semantic-safety/phase6_tf_witness.py`, runner flag
`--phase6-tf-witness`, required for Phase 6 arm trials) subscribes the
same `/robot_1/scan_fixed` and `/tf`/`/tf_static` streams, keeps its own
tf2 buffer, and resolves `map → sensor` at each scan's capture stamp with
the fixture lookup's exact semantics (capture-time, no latest-TF, no
extrapolation). It writes only a small sequenced status record through
the shared emptyDir; the fixture polls it in the guard stage BEFORE
`adapter.tick()` (the drain-before-tick rule) and renews the tf lease
through the unchanged `evidence()` path — same native clock bound, same
monotonicity, same 500 ms capture-age freshness. Fail-closed contract: a
stale (>500 ms heartbeat), missing or regressing record renews nothing;
witness loss starves the lease exactly as before and can never create
optimistic authority or resume motion. The fixture's own lookup remains
active (union of two fail-closed sources; the saturated one simply stops
contributing). The witness must be live and have qualified at least one
capture stamp before the guarded request is admitted. This mirrors the
qualified UDP companion path precedent (a private-profile deviation to be
recorded at sign-off, like the watchdog UDP companion path).

A second, post-failure defect remains retained for separate investigation:
the console server SEGFAULTED (-11) inside the Server destructor after
`destructor_begin` during teardown under the mat-close load state (gcfix
run, one occurrence; the Phase 5 serialized-stop fix is in place and its
markers all appeared before the crash).

| Post-reorder attempts | Result |
|---|---|
| pair-1-off-fix | still command_expired at x=16.430 — the reorder alone insufficient; the checked copy's fate needed the joiner diagnostics |
| pair-1-off-joindiag | killed by the frozen 280 s in-pod budget mid-run (the trial runs longer than the 1 m-goal era allowed) — budget raised to 600/700/660 s |
| pair-1-off-joindiag-2 | the diagnostics land: a 53.4 ms observer-stage GC pause at the trip; checked renewal expired unprocessed in the joiner's 20 ms window |
| pair-1-off-gcfix | **GC disabled: past x≈16.5 onto the mat (x=17.174)**; new failure `tf_stale` from the mat-close /tf delivery delay into the fixture (corrected root cause below — NOT a scan outage); console server segfault (-11) at teardown |
| pair-1-off-scanreliable | reliable scan/odom QoS: no publisher match, zero scans — reverted (its premise, lost scans, was later disproven by the gcfix re-analysis) |
| pair-1-off-tfprobe | **failure reproduced with the three-way /tf probe**: frame bridge publishes at 0.2–1.7 ms, the prober sidecar receives at 0.7–3.6 ms, the FIXTURE's /tf arrival lags 5 ms → 179 ms (max 208) as its own CPU reaches 95%, recovering to 7 ms after the stop — the delay is internal to the fixture process; same `tf_stale` at the mat, only the goal check failed |
| pair-1-off-tfwitness | first run of the user-approved TF witness: fixture crashed during pre-arm discovery — the witness qualifies capture stamps as soon as AMCL is live, before the native clock binds, and the poll lacked `adapter.tick()`'s clock-bound precondition; died before arming, no motion; poll guarded |
| pair-1-off-tfwitness-2 | **the witness WORKED — the tf lease survived the mat-close starvation** (no `tf_stale` for 1.2 s of sim past the fixture's own last renewal at sim 20.0; the witness qualified 218 stamps through the end) — but the trial was killed by the frozen 20 s navigation-terminal window from the 1 m-goal era at 2.0 m displacement, the robot on the mat (x=17.426) and still moving at 0.15 m/s; `navigation_trial_timeout`, only the goal check failed. Two fixture bugs found: the poll's success detection (`evidence()` has no return value — renewals were applied but invisible to the counter) and the 20 s window (now 90 s for Phase 6 arms) |
| pair-1-off-tfwitness-3 | **PASS — all 32 checks, terminal 4 (`goal_succeeded`)**: the first complete off-arm crossing. 4.03 m displacement, 1720 physical samples inside the mat rectangle (nonzero baseline exposure), contact window clear, and the witness carried the tf lease with 301 applied renewals (of 302 records, zero stale) through the mat-close window where the fixture's own reader starves. The pilot pair's off arm is complete |
| pair-1-on-tfwitness | first on-arm run: **`command_expired` at 0.081 m, 1.3 s into motion** — the witness worked (21 applied renewals, no `tf_stale`), the SAM3 stream stayed healthy (~7/s, capture ages 170–215 ms), no physics stall, no process CPU saturation, registry/task graph clean, audit delivery prompt. The controller's output stamps gapped ~106 ms of sim (~150 ms wall) at motion start (its own "loop rate 29.4 Hz" warning; stamps 9.650→9.756), so no fresh command source existed inside the 100 ms authority window and the chain correctly failed closed. The local costmap — the controller's own process, carrying the semantic layer (the on-arm novelty) — updated at only ~400 ms cadence (vs 200 ms nominal), indicating per-update semantic-layer costs of that order. The exact blocking point inside the controller cycle (semantic-layer update vs TF/costmap-currency wait) needs one instrumented on-arm run |
| pair-1-on-tfdiag | instrumented on-arm (image `b122c2a3…`, per-observation digest/TF/projection timings + updateBounds lock-wait logs): **the semantic layer is exonerated** — every observation costs 3.7–5.4 ms (digest 2.5–3.3, TF 0.02–0.06, projection 1.1–2.1) and no updateBounds exceeded 15 ms. The failure reproduced identically (`command_expired`, 0.833 m, one ~165 ms controller cycle, loop rate 11.6 Hz). **Root cause pinned:** the semantic observation delivery to the CONTROLLER's reader lagged ~150–200 ms while the PLANNER's global costmap received the same stamps promptly (e.g. stamps 14.2/14.3/14.4 at walls .407/.457/.594 at the planner vs .596/.601/.606 in a burst at the controller) — a per-process reader saturation of the controller_server under the on-arm load. The reliable depth-8 subscription history delivered the backlog in order, so the newest observation queued behind stale ones already past the layer's 500 ms isCurrent window; the local costmap went non-current; the controller's costmap-currency wait blocked its cycle past the 100 ms command authority. Remedy: the observation streams (mask/points/timing) move to best-effort keep-last(3) — drops the OLDEST under backlog, bounding the newest observation's staleness by the stall itself; a dropped triple component fails the digest join and is rejected exactly like any invalid observation (fail-closed, unchanged thresholds) |
| pair-1-on-qosfix | **best-effort REVERTED — wrong remedy**: the multi-megabyte observation clouds require reliable transport; without fragment retransmits the delivery collapsed (>90% loss in the quiescent pre-motion phase — 4 observations in the controller log vs ~70 expected), the costs gate found zero semantic cells and the trial stopped before motion. The re-analysis also refined the tfdiag finding: the PLANNER received stamp 14.4 late too (.594), so the SAM3 stream itself had a ~140 ms cadence gap, and the controller's reader added ~150–190 ms on top; the layer's 500 ms isCurrent window runs from the observation's CAPTURE wall, so the nominal ~200 ms end-to-end latency leaves only ~300 ms of slack — a stream gap plus a reader excursion trips it. The chain's fail-closed stop is correct behavior; the structural question is whether the on-arm's semantic freshness contract can be met under load with the full-resolution cloud into the controller's process |
| pair-1-on-globalonly | **the on-arm navigation WORKS — goal succeeded (terminal 4, 3.94 m, all checks green except registration)** with the user-approved global-only semantic layer (image `4486307d…`): the controller's process carries no semantic subscription, the command chain held through the full crossing, and the witness carried the tf lease (302 renewals, zero stale). **But the pilot pair shows NO route contrast at soft cost 200**: the on-arm's hull exposure is 1.448 m vs the off-arm's 1.415 m — the planner responded to the semantic costs (the initial plan's midpoint shifted ~0.4 m north, hugging the mat's edge) but the penalty does not buy a full detour on this scene geometry. The `sam3_registration_under_motion` contract also degraded on the shifted views (pooled 0.688 vs the off-arm's 1.0 on the same mat): the north-hugging lane's grazing camera views bleed the mask onto non-mat areas — recognition behavior outside the crossing-route envelope the Phase 5 series validated (the standing Phase 2 recognition waiver applies). The plan anticipated exactly this fork: "Start with an explicitly selected soft cost of 200 for the target. Evaluate lethal cost 254 as a separate exclusion experiment." |
| pair-1-on-bleedmap | **the bleed map is clean — no cost cell ever fell outside the mat rectangle** (19 one-second snapshots through the trial: every cost-200 cell inside, `outside=0` throughout, ~253 cells). The registration check's 31% "outside points" are sub-cell edge bleed absorbed by the layer's +0.15 m cell margin — NOT a second red area — so the lethal-cost-254 exclusion experiment is viable from the bleed perspective. **The trial's `native_session_lost` failure was the poll's own artifact, root-caused and corrected:** materializing the ~585k-cell service response in the pump's guard stage costs a measured 33–42 ms of pure-Python pump block per 1 Hz poll (the stage-timings slow list shows the 1 Hz signature); one such block landed on the lease-issuance path while the command source neared its 100 ms deadline — the coordinator's lease cadence gapped 46 ms, the watchdog's lease (capped by the aging source deadline) expired, and every apparent "delivery excursion" in the run (the fixture's /tf and scan spikes, the missing command audits, the watchdog's 47 ms lease-packet gap) was that pump block. The frame bridge's odom receipts stayed ≤11 ms throughout — the source never stalled. The poll is now opt-in (`--phase6-costcells`) with the warning recorded; the on-arm's post-global-only failure rate without the poll is 0 of 1 (globalonly passed) |
| pair-1-on-globalonly-2 | clean on-arm rerun (no poll; pump clean — guard max 8.7 ms, zero slow events): **`command_expired` at 2.415 m, ON the mat** — the known mid-route stamp-lag race class at its design margin. The last source (stamp 25.004, wall 146.5721) carried renewals whose remaining authority shrank to 17–23 ms; its fixed 100 ms expiry (146.6701) fired 2 ms before the next source's checked admission would have landed (~146.672: smoother output +83 ms of the source's life — the conservative bound leads publication — plus the monitor's 10 ms, 4 ms delivery, 6 ms drain). The controller never stalled (its stamps stopped only at the cancel; the footprint publications continued; no rate warnings), the witness worked (186 renewals), the planner's layer ran 3 ms/observation with zero cells at the mat-on views (the mat is under the robot, no longer visible — expected). The on-arm at mat-close is a coin flip on single-digit milliseconds of ordinary chain latency; the pass (globalonly) and this failure differ by a few ms of jitter, not by any defect |
| pair-1-on-lethal254 | **the lethal-cost exclusion experiment achieves the pilot pair's semantic objective: hull exposure 0.000 m vs the off-arm baseline's 1.415 m (100% reduction; the series gate needs ≥90%), zero samples inside the mat rectangle, and the circumscribed hull cleared the mat by ~5 cm** (closest centerline approach 0.299 m vs the 0.246 m hull radius) — the planner detoured around the mat completely at target_cost 254, where the soft cost 200 only nudged the plan. The trial still failed its goal check on the SAME mid-route renewal race, at 4.035 m (~90% of the longer detour route, sim 45.16): the last source's fixed 100 ms expiry fired ~1–3 ms before the next source's checked admission — identical shape to pair-1-on-globalonly-2, now away from the mat (the race is route-independent). Across the three post-global-only on-arm runs the race tripped 2 of 3 (pass at full route, trips at 60% and 90% of route) — a per-cycle probability of roughly 0.1–0.3% that makes any 20-pair series infeasible until addressed. The race is the single remaining mechanical blocker; the semantic result stands on its own |
| smoke-globalonly | **PASS — all 24 checks** under the global-only candidate (image `4486307d…`): wiring (global costmap subscribes all four streams, layer publisher present, local costmap geometry-only), costs at target (253 global cells, all inside, zero local cells), mat removal clearing 1078.5 ms within the 1761 ms Phase 4 bound, registration 100% (66 results). The candidate change is validated end-to-end in the stationary mode; the record replaces the both-maps-era smoke attempt 10 for the global-only era |
| pair-1-on-lethal254-grace1 | topology data-plane failure, root-caused and fixed: the r2 topology's SAM3 pod was created in the same instant as the router, and its zenoh bridge's initial dial preceded the router's listening socket (retry: None — the known never-re-dials lesson): the control plane half-lived (routes formed from declarations) but NO data flowed — SAM3 warm and "awaiting live RGB-D frame" forever, zero observations at the costmaps, the witness never qualifying a scan, the costs gate timing out before arming. The topology tool now waits for the router's available replicas before creating the pod; recycling just the pod (dialing the live router) restored the data plane |
| pair-1-on-lethal254-grace2 | **the grace works — 4 mid-route races saved** (4 `command_deadline_grace` events, the topology data plane flowing, the witness at 386 renewals, the detour run to the goal approach at 4.315 m) — then tripped on a newly discovered liveness defect at the goal approach: RPP's rotation commands for the detour's larger heading correction reach wz −0.549..−0.652 rad/s (the Phase 5 rotation endgame ran at ~0.02), the ledger rejected those raws on the applied magnitude bound (`abs(wz) ≤ 0.5`), and the monitor's valid limited outputs (wz ramping to −0.08) were left sourceless — `command_expired` with no newer source for the grace. Fixed in the provenance path only: the ledger's source record now requires structural validity (`velocity_finite`); the authority path (resolve, gate.command, the native lease) keeps the full magnitude bounds on the APPLIED velocity |
| pair-1-on-lethal254-grace3 | **PASS — all 33 checks, `goal_succeeded`: the first complete on-arm pass.** Hull exposure **0.000 m** (100% reduction vs the baseline's 1.415 m), zero samples inside the mat, registration **99.99%** pooled over 54 moving results (the earlier 0.688 was lane-specific, not a deterministic detour property), the witness carried 378 renewals, and the grace saved 2 more mid-route races. With the grace, the rotation provenance fix, and the topology race fix, the series-entry blocker is closed end-to-end: the on-arm lethal-254 trial completes the full detour route with every check green |
| pair-1-on-lethal254-grace4 | **PASS — the second consecutive complete on-arm pass** (all 33 checks, `goal_succeeded`, registration 99.99%, the grace saving 3 more mid-route races, the witness at 349 renewals, 4.16 m detour route) — recorded from the partial-copy evidence: the runner's main `oc cp` truncated with an unexpected EOF racing the fixture's teardown, so the runner reported failure while the fixture's own summary and the finally's complete partial copy prove the pass (the copy now retries once). Two consecutive on-arm lethal-254 passes with the grace active (5+4+3 saves across the three grace-era runs) close the series-entry blocker with repeatability evidence |
| negative-absent-on-pilot | first run of the target-absent negative case: died at startup — the fixture wrote the observation worker's ground truth by unconditionally parsing the (absent) mat from the world. Fixed: `mat:null` for the absent case, the worker degrades to empty results without projection, and the registration check inverts (no moving result may carry a ≥50-selected-pixel mask with no target staged) |
| negative-absent-on-pilot-2 | **PASS — all 33 checks, `goal_succeeded`**: no staged mat, zero observed target-cost cells (the recognition diagnostic), the inverted registration contract green, the plan gated on the observation streak with the layer current from accepted empty detections. The target-absent negative case is validated |
| negative-removal-on-pilot | first run: the removal mechanics worked (the mover fired at 1.003 m, the route completed to the goal at x=19.404) but the endgame tripped `native_session_lost` — the packet issued just before the grace window carried only 27.8 ms of remaining life and the new-source packet landed at the watchdog 2 ms past the old expiry (the regular ≥20 ms heartbeat cadence). Fixed: the grace now clears `last_send`, forcing the same tick's heartbeat to transmit the bridge packet with the extended deadline |
| negative-removal-on-pilot-2 | second run: the bridge packet fix in, but the endgame tripped `native_capture_stale` — the watchdog's own publication loop stalled 104–105 ms on the console server's shared gz transport mutex under the endgame camera load, and the UDP sendto was sequenced AFTER the gz publish in the same worker iteration: the companion path was not actually independent of the mutex it exists to bypass, and the status JSON carried a physical capture older than the 100 ms bound. Fixed in the native watchdog: the UDP sendto now goes FIRST (the gz paths unchanged and active) — console base build 27 (`6d863ee…`) + the phase6 overlay rebuild (`ea8f535…`) |
| negative-removal-on-pilot-3 | **PASS — all 34 checks, `goal_succeeded`** on the UDP-first image chain: the mover fired at 1.004 m of verified displacement, the route completed (4.28 m), the grace saved 3 mid-route races, and the endgame held. The target-removal negative case is validated; the new base chain is validated end-to-end on the full guarded profile |
| negative-perception-on-pilot | **PASS — all 35 checks**: the armed-semantic supervisor on the phase6 on-arm (lethal-254, witness), the camera-path-loss fault injected after verified semantic-armed motion, the fail-closed stop with the mode-qualified `camera_stale` reason at 459.8 ms injection-to-trigger (the 500 ms freshness band), the Phase 5 stop criteria met, and the observed late success did not resume motion. The perception-failure negative case is validated — all three negative cases are now pilot-proven on the UDP-first chain |
| controller-block-threadprobe-1 | never scheduled: the pinned GPU node `ip-10-0-44-146` was occupied by another project's deployment (`e5-mistral` in `agent-mesh-ci-project-1`, holding the node's only GPU allocation); the fixture pod stayed `Pending` to the runner's 660 s timeout. Pure external node contention — no trial ran, no fixture code executed |
| controller-block-threadprobe-2 | **the goal-approach endgame failure ROOT-CAUSED (see the section below)**: a ~103 ms console-server physics stall at the goal-approach boundary froze `/clock` domain-wide; the controller kept cycling at 40 Hz republishing the same frozen sim stamp; the ledger correctly rejected the duplicates and the chain expired fail-closed (robot 1.213 m from the goal). Run with the read-only thread probe plus the opt-in controller snapshot, on `ip-10-0-55-116` — an exact g5.2xlarge/A10G hardware match — as a user-approved DIAGNOSTIC-ONLY placement (the pinned node was GPU-blocked; this run is not motion-qualified evidence) |
| sensors-override-smoke-1 | the fail-closed `console_sensors_system_override_loaded` gate worked as designed: the SYSTEM sensors plugin loaded, not the override — gz-sim's SystemLoader appends `GZ_SIM_SYSTEM_PLUGIN_PATH` entries AFTER its own install dir, so a bare plugin filename always resolves to the system library (the env var adds plugins; it cannot shadow them). Trial stopped before arming |
| sensors-override-smoke-2 | **PASS — all 25 checks**: the override provably loaded (absolute-path world rewrite — `SystemPaths::FindSharedLibrary` short-circuits an existing absolute path); wiring, costs at the mat, mat removal clearing, registration, timing, disarmed throughout |
| sensors-override-pair-off-1 | **PASS — all 33 checks, `goal_succeeded`** (override v1): the armed window's physics cadence clean (max gap < 30 ms; every long gap pre-arm) — the render/physics coupling fix works for the off arm |
| sensors-override-pair-on-1 | override v1, on-arm lethal: ONE 106 ms physics stall at the goal-approach turn (sim 50.200, frozen stamps, camera frame at 50.2 never captured) — the SECOND coupling wait (`updateTimeCv`, the ECM-sync) remained |
| sensors-override-pair-on-2 | override v2 (the ECM-sync wait removed): ONE 103.4 ms stall — the wait was gone but both it and the skip check lived inside `std::unique_lock(renderUtilMutex)`, which the render thread holds for the ENTIRE `renderUtil.Update()` (the scene/geometry application): the mutex ACQUISITION itself blocked |
| sensors-override-pair-on-3 | override v3 (`try_to_lock` on the ECM-sync mutex): ONE 90 ms stall — the same acquisition-class bug on the SECOND mutex: `RunOnce` holds `renderMutex` around the ENTIRE `sensorManager.RunOnce()` (render + publish), and the busy check acquired it before reading the flag |
| sensors-override-stallprobe-1 | override v3 + the wchan/syscall thread instrumentation: the physics thread futex-waits on the HEAP `renderMutex` (0x55cdcf5f82b4) while the render thread burns a full core — the final blocking site named. (The trial's other failures are the documented gdb-freeze artifacts) |
| sensors-override-pair-on-4 | **override v4 (lock-free busy check): the physics stall class is DEAD** — armed cadence clean (max 16.4 ms) straight through the pathological frame, `/clock` and native status never froze. But the trial still expired on a NEW variant of the same root: the pathological render itself (~190 ms of render-thread CPU at the on-arm's goal-approach viewpoint — the camera's first exposure of scene content not seen on the detour route) now travels through the SENSOR path: the gpu_lidar renders in the same manager iteration (scan late ~450 ms) → AMCL's map→odom edge late → the controller's cycle blocks ~76 ms in a TF wait (its own log: loop rate 16.13 Hz, all threads futex-idle) → the 100 ms command authority expires. The OFF arm's route never triggers the spike (zero motion-phase camera gaps) |
| sensors-override-warmup-on-1 | **PASS — all 35 checks, `goal_succeeded`, hull exposure 0.000 m** with the pre-arm render warmup (four goal-area cameras subscribed only while disarmed): ZERO camera capture gaps through the whole run (not even the startup ones), armed physics max gap 18.7 ms, warmup check green (all four cameras rendered 5 frames each). **The endgame failure class is closed at its root** |
| sensors-override-warmup-off-1 | **PASS — all 34 checks, `goal_succeeded`, baseline hull exposure 1.415 m** (matching the pilot baseline exactly), warmup active in both arms — the paired set on the final configuration |

## The endgame failure closed: the Sensors-system override plus the pre-arm render warmup (October 28, 2026)

The goal-approach failure that blocked the Phase 6 series is closed at its
root, in two user-approved private-fixture remedies on the same precedent
as the capture-trace override and the UDP companion path:

**1. The Sensors-system override** (image chain base `125cbd5a` → console
`15b900f6` → phase6 `a788757d`, override `.so`
`2918a1a9…`, loaded by absolute-path world rewrite): gz-sim 8.15.0's
Sensors system couples the physics thread to the render thread at THREE
points, each of which blocked physics for a pathological frame's full
duration (~90–120 ms observed at the goal-approach viewpoint):

| Coupling point | Upstream behavior | Override |
|---|---|---|
| ECM-sync (`updateTimeCv`) | waits until the render thread's `renderUtil.Update()` consumes the pending ECM update | `try_to_lock(renderUtilMutex)`; skip the cycle's `UpdateFromECM` when held or unconsumed |
| busy check (`renderCv`) | waits until the in-flight render iteration completes | lock-free read of the `std::atomic` flags; skip arming when a render is in flight |
| arming (`renderMutex`) | (reached only when idle) | unchanged — the render thread then holds the mutex only microseconds |

The fix ladder (each version removing exactly one mechanism, each run
retained): v1 removed the arming cv-wait (one 106 ms stall remained — the
ECM-sync wait); v2 removed the ECM-sync wait (one 103 ms stall — the
`renderUtilMutex` acquisition); v3 try-locked that mutex (one 90 ms stall —
the `renderMutex` acquisition around `sensorManager.RunOnce`, named by the
wchan/syscall probe: the physics thread futex-waiting on the heap
`renderMutex` while the render thread burned a full core); v4 made the busy
check lock-free — **the armed physics cadence stayed clean (max 16.4 ms)
straight through the pathological frame**. Two loader findings en route:
`GZ_SIM_SYSTEM_PLUGIN_PATH` cannot shadow the system plugin (the env
entries are appended after gz-sim's own install dir — the override loads by
absolute path instead), and every trial gates on the
`console_sensors_system_override_loaded` marker so a shadowing or
non-rebuild failure cannot pass silently.

**2. The pre-arm render warmup** (fixture-side, `dce79730`): the
pathological frame itself — the camera's first exposure, at the on-arm's
goal-approach orbit, of scene content not seen on the detour route —
costs ~190 ms of render-thread CPU and its blast radius then travels
through the sensor path (the gpu_lidar renders in the same manager
iteration: scan late ~450 ms → AMCL's map→odom edge late → the controller
blocks ~76 ms in a TF wait → the 100 ms command authority expires). Four
static collision-less rgbd cameras at the goal facing N/E/S/W (1.8 rad FOV
— full coverage of the orbit's sweep) are staged in BOTH arms; the gz
Sensors system never renders sensors without subscribers, so they cost
nothing during the armed trial; the fixture subscribes each sequentially
during the DISARMED startup (≥5 frames, then unsubscribes), forcing the
lazy scene content to load. The `phase6_render_warmup` check fails closed
if any camera produced no frames.

**Result** (`sensors-override-warmup-on-1`, the on-arm lethal-254 trial):
all 35 checks, `goal_succeeded`, hull exposure **0.000 m**, ZERO camera
capture gaps through the entire run, armed physics max gap 18.7 ms. The
off arm on the identical configuration: all 34 checks, `goal_succeeded`,
baseline exposure **1.415 m** — the pilot pair's contrast (100% reduction
against the ≥90% series gate) reproduces on the fixed chain. The
requalification set is closed by the stationary smoke on the same
configuration.

## Series 15–18 (October 28, 2026, evening): the endgame race ladder closed; the remaining blocker is pre-existing goal-approach localization

Four series attempts on the remediated chain, each stopped on first
failure, each root-caused (all retained):

- **series-15** (trial 000-on): the goal-centered warmup missed content
  visible from the orbit circle through parallax/occlusion — extended to
  twelve cameras (four goal-centered + eight on the orbit circle facing
  outward); validated by `sensors-override-warmup-on-2` (35/35, zero
  motion-phase camera gaps).
- **series-16** (13 consecutive passes, then 006-on): the RPP
  goal-approach orbit non-convergence (~30 s of circling, timeout) plus
  the corner-cutting exposure finding (RPP's 0.6 m lookahead cutting the
  mat's northeast corner inside the 0.35 m inflation clearance — hull
  exposure 0.000–0.710 m/trial, aggregate 82% vs the 90% gate). Remedy
  (user-approved): the candidate revision `lookahead_dist` 0.6→0.4,
  `min_lookahead_dist` 0.3→0.25, `inflation_radius` 0.35→0.45, both
  arms equally; `use_rotate_to_heading` stays disabled (its zero-linear
  velocity deadlocks against the goal checker's stale-stamp target —
  October 23 GPU trial 2). Requalified: off 34/34 (baseline 1.423 m),
  on 35/35 (0.000 m, clearance 0.257 m).
- **series-17** (three passes, then 001-on): a 3 ms endgame race — the
  20 ms heartbeat cadence lets the watchdog's lease floor sit one
  cadence below the gate's deadline while a source ages out, so the
  grace's forced packet landed past the watchdog's expiry. Remedy
  (user-approved): the heartbeat accelerates to 5 ms inside the final
  40 ms of authority (no new authority — packets stay capped by the
  source deadline). Validated under load: `heartbeat-accel-on-1` passed
  with NINE grace saves in one trial.
- **series-18** (three passes, then 001-on): **the authority path finally
  held — twenty-six grace saves in the failed trial alone — and the stop
  exposed the pre-existing limitation**: the goal-approach completion is
  an AMCL-belief-frame arrival. Every accepted `goal_succeeded` trial
  (including the pilot's grace3/4) physically ends 0.5–1.4 m from the
  goal; in this trial the belief/truth divergence reached 2.7 m (AMCL's
  y-covariance growing through the approach — scan-matching ambiguity)
  and the goal checker never fired: the robot's belief sat 0.11 m from
  the goal with the carrot at the path end while the physical robot
  wandered 2.6 m away until the timeout.

**The next session's decision**: the leading remedy is qualifying the
endpoint-capture controller overlay (evaluates the fixed map goal at the
robot pose's capture timestamp — built and piloted October 19, never
series-qualified) as part of the candidate; the yaw/orbit component may
additionally need goal-checker or AMCL parameter review. Note that a
belief-frame completion with multi-metre physical error is a degraded
result for qualification honesty — the evaluator's exposure metrics
(physical) remain valid, but the completion semantics deserve explicit
review at sign-off.

## The endpoint-capture candidate (October 28, 2026, night): fork (a) taken, with arrival divergence recorded

The user approved the recommended fork: qualify the endpoint-capture
controller overlay into the candidate **and** record the belief/truth
divergence at arrival in every trial record, so a multi-metre-diverged
"arrival" is visible rather than silently accepted. AMCL parameter review
(the y-ambiguity root cause) is held in reserve pending series data.

**The candidate revision** (commit `1331c955`): both arms, all cases, run
the October 19 endpoint-capture overlay — the goal checker evaluates the
fixed map goal at the robot pose's capture timestamp instead of the path's
original stamp (the documented stale-stamp mismatch class), without
relaxing the 0.20 m arrival tolerance; no sensor or command stamp is
changed. The overlay rebuilt `--no-cache` on the current phase6 chain
(`Containerfile.controller` FROM re-pinned to `a788757d`): candidate
digest `348fc584…`, in-image verification controller_server
`ecc29dd0…` / libcontroller_server_core.so `cdf6ad1c…`, with the
inherited binaries unchanged (sensors override `2918a1a9`, watchdog
`0a0126d5`). Every trial fail-closes on `opt_in_controller_overlay_loaded`
(runner flag `--controller-endpoint-capture`, now unconditionally in
`phase6_trial.py`).

**The divergence metric** (`completion_divergence` in `phase6_trial.py`;
fixture-side, no image rebuild): control-geometry.json map poses (the
AMCL belief) matched to trace.jsonl physical rows by simulation stamp,
measured at the arrival instant — the controller's own
"Reached the goal!" wall stamp mapped through the trace — plus the final
row. Descriptive only, never a gate: the series result carries a per-arm
`completion_divergence` summary, and whether a multi-metre-diverged
arrival is acceptable stays with the user at sign-off. Validated against
the retained series-18 evidence first (001-on: divergence 2.697 m, belief
0.115 m from the goal at timeout — the handoff's numbers exactly).

**Requalification on the final configuration** (all three retained):

| Attempt | Result |
|---|---|
| endpoint-capture-smoke-1 | **PASS — all 27 checks** (the stationary smoke plus the new `opt_in_controller_overlay_loaded` gate): wiring, costs at the mat, mat removal clearing, registration, render warmup, disarmed throughout — the overlay chain validated in the stationary mode |
| endpoint-capture-off-1 | **PASS — all 35 checks, `goal_succeeded`**, baseline hull exposure **1.381 m** over a 4.13 m route; divergence at arrival 1.392 m, the physical robot 1.381 m from the goal (the high end of the known 0.5–1.4 m belief-frame arrival class — now visible per-trial instead of implicit) |
| endpoint-capture-on-1 | **PASS — all 36 checks, `goal_succeeded`**, hull exposure **0.000 m** (100% reduction vs the baseline), min centerline clearance 0.302 m (clears the 0.246 m hull); divergence at arrival 1.276 m, the physical robot 0.878 m from the goal |

The pilot pair's semantic contrast and completion both hold on the
endpoint-capture candidate. Series-19 follows on this configuration.

## Series-19 (October 28, 2026, night): 11 consecutive passes, then the post-goal stationary-confirmation false negative

Series-19 ran the endpoint-capture candidate: eleven consecutive passes
(000 through 005-off, including two topology-liveness recycles on 000-off
and 003-off — the wrapper's accepted mechanic, both attempts retained),
then stopped on **005-on** — not on the goal, not on the chain, but on a
new physics-evidence class:

**Root cause (series-19 trial 005-on):** the goal fired mid-orbit (the
overlay working as designed — belief/truth divergence at arrival just
0.495 m, stop applied in 2.07 ms, displacement 0.34 mm), and the
post-goal stationary confirmation could never fire. The physics-reported
`WorldAngularVelocity` NORM decayed through quiet (0.00156 at sim
77.334), then **rebounded and converged to exactly 0.18547 rad/s,
permanently frozen** — while the pose had been bit-static since 77.25
(2900+ identical samples), the wheels static, the floor contacts resting
(depth ~1e-8 m), and the physics cadence healthy throughout. A resting
body with a frozen nonzero velocity report: the stationary predicate
(`angular_speed < 0.02` for 250 ms) false-negatives forever, and
`native_stationary_after_task` timed out at its 10 s bound. All twelve
other series-19 trials decayed cleanly to 0.0000-0.00001 terminal
angular. The class triggers when the goal fires with residual rotation
(~0.18 rad/s at the stop) — more frequent now that the overlay reliably
converts mid-orbit goal approaches into completions instead of timeouts.

**Remedy (user-approved, fixture-side ConfigMap — no image rebuild):**
`NativeClock`'s quiet window now SURVIVES a velocity-norm rebound while
the pose provably has not moved since the window opened (≤1 mm and
≤0.005 rad from the window-opening pose, linear speed still < 0.01 m/s
— a live, unjammed signal in the observed artifact). The window still
OPENS only on the velocity criterion. Safety argument: the pose is the
primary physical state (the velocity norm is a derived solver quantity,
now proven capable of a permanent false value); the pose-delta bounds
accept no more motion than the velocity criterion itself (≤4 mm/s,
≤0.02 rad/s average); and the ARMING authority path is untouched — the
native watchdog's C++ arm gate independently requires its own
velocity-norm stationary proof (`lease_guard.hpp` rejects on
`!stationary`; a rejected arm fails closed through the first-command
timeout). Validated by replaying the entire retained 005-on trace
through the fixed clock: the window opens at the trough and stationary
holds through the whole post-goal tail. Seven new unit tests including
the 005-on replay, the rotating-pose reset, the linear-signal reset, and
the fail-closed no-window-without-velocity-quiet case.

**Also recorded (pre-existing, not an overlay regression):** the on-arm
RPP corner-cut exposure recurs stochastically — series-17 000-on 0.389 m,
series-18 000-on 0.589 m, series-19 000-on 0.565 m and 001-on 0.311 m
(roughly half the on-trials, 0.3-0.6 m each) — putting the aggregate
exposure reduction near 87-90% against the 90% series gate. The user
elected to watch it in the series data rather than pre-emptively revise
the candidate again.

**Requalification on the pose-delta predicate** (all retained;
`posequiet-off-1` is the router data-plane liveness death after the smoke
consumed the topology's session life — infrastructure, not a trial
result; the topology was recycled through the wrapper's accepted mechanic
and the pair re-run):

| Attempt | Result |
|---|---|
| posequiet-smoke-1 | **PASS — all 27 checks** on the fixed predicate |
| posequiet-off-2 | **PASS — all 35 checks, `goal_succeeded`**, arrival divergence 0.922 m (physical 0.967 m from the goal) |
| posequiet-on-1 | **PASS — all 36 checks, `goal_succeeded`**, arrival divergence 1.162 m (physical 1.000 m from the goal); hull exposure 0.578 m / clearance 0.15 m — the corner-cut class appearing at its observed rate, watched in the series aggregate per the user's decision |

Series-20 follows on this configuration.

## Series-20 (October 28–29, 2026, overnight): 16 consecutive passes, then the capture-trace delivery race

Series-20 ran the endpoint-capture candidate with the pose-delta
predicate: **sixteen consecutive passes** (000 through 007 both arms),
then trial 008-off stopped on an infrastructure class the one-recycle
mechanic could not cure — root-caused through two instrumented probe
trials (both retained, `dataplane-probe-off-1/2`):

**Root cause (established by live probing inside the SAM3 pod):** the
gz-transport delivery of `/robot_1/camera/capture_trace` — the
render-time trace published by the patched `SemanticCaptureTrace` inside
the console server — intermittently fails to reach the camera bridge,
while EVERY other topic flows through the same processes and links
(probe counts over 10 s in the SAM3 pod: /clock 3744, camera_info 75,
both compressed images 75, compression_trace 75, **capture_trace 0**).
The ROS-side route (domain 88) and the zenoh relay were identical
between the failed and passed probes; the patched library was loaded
and `SEMANTIC_CAPTURE_TRACE` set in both. The class is a
**per-fixture-session gz-transport matchmaking race** (roughly 10-30%
of sessions on the current chain), fails CLOSED at the pre-arm SAM3
readiness gate (no motion, no evidence contamination), and a **fresh
fixture pod on the SAME topology recovers it** — probe-2 passed
immediately after probe-1 failed, on the same SAM3 pod and router. The
wrapper's topology recycle was the wrong remedy for this class (the
router was never at fault), and when the post-recycle retry also lost
the race the series died. The per-topic selectivity (the same bridge
process carries camera_info but not capture_trace) is recorded as the
open root-cause question for the gz-transport matchmaking mechanism.

**Remedy (user-approved, October 29): the wrapper's liveness ladder.**
On the liveness signature, the trial retries with a fresh fixture pod
on the SAME topology (up to twice) before falling back to one topology
recycle with a final retry. Every attempt is retained under `-liveness-N`
suffixes and counted in the record (`infrastructure_retries`,
`infrastructure_recycles`). Fail-closed semantics unchanged: a trial
whose CHECKS fail is never retried — the stop-on-first-failure
discipline only tolerates infrastructure deaths.

Also recorded: series-20's on-arm corner-cut exposures before the stop
(000-on 0.565 m had already appeared in series-19; the aggregate at the
stop was 0.752 reduction over 8 on-trials — small-sample variance, the
20-pair data decides).

## The lookahead-0.5 candidate (October 29, 2026): the corner tradeoff rebalanced

Series-21 stopped on trial 000-on (after a correctly-retried liveness
death) when the mat-NE descent-turn overshoot (0.3 m south of the path,
growing monotonically to 2 m) entered a pure-pursuit circling limit
cycle around the goal until the 90 s window expired — the catastrophic
face of the same corner that produces the benign corner-cut exposure
class (~half the on-trials, 0.3-0.6 m). The series-16 tightening to 0.4
recovered the cut but narrowed the off-path recovery envelope; at the
observed ~1/14 on-trial rate the series is statistically infeasible
without a fix.

**The revision (user-approved, commit `39a07bef`):** `lookahead_dist`
0.4→0.5 — between the cutting 0.6 (82% aggregate reduction) and the
overshooting 0.4 — with `min_lookahead_dist` 0.25 and `inflation_radius`
0.45 unchanged, both arms equally; `use_rotate_to_heading` stays
disabled (the documented deadlock). Renderer and all three checked-in
candidate yamls updated together.

**Requalification (all retained):**

| Attempt | Result |
|---|---|
| lookahead05-smoke-1 | **PASS — all 27 checks** |
| lookahead05-off-1 | **PASS — all 35 checks, `goal_succeeded`**, baseline exposure 1.433 m; arrival divergence 0.939 m |
| lookahead05-on-1 | **PASS — all 36 checks, `goal_succeeded`**, hull exposure **0.000 m**, min clearance 0.335 m, **max path deviation 0.623 m** (vs 2.09 m into the limit cycle at 0.4, and 0.9 m recovered cuts) — the corner negotiated with margin on both faces; arrival divergence 0.655 m |

Series-22 follows on this configuration.

## Series-22 and the AMCL review (October 29, 2026): the y-ambiguity is intrinsic

Series-22 stopped on its first on-trial with the identical
descent-corner failure shape at lookahead 0.5 (deviation 0.24 → 2.24 m
into the limit cycle) — with a decisive addition: at the end **the
belief sat 0.1 m from the goal** (inside the 0.20 m xy tolerance, the
endpoint-capture overlay active) while the physical robot circled
2.24 m away, divergence 2.34 m, and the checker still did not fire
(the orbiting heading vs the yaw tolerance). AMCL's std_y grew
0.10 → 0.92 m through the detour — the handoff's y-ambiguity confirmed
as the root layer. The lookahead knob was tried at 0.4 and 0.5 with the
same stochastic failure (~13%/trial across series-19→22; the series is
infeasible without addressing the root).

**The AMCL revision (user-approved, commit `dbbbf73f`):** particle
budget 500-2000 → 2000-8000 and odometry-noise alphas 0.2 → 0.1 — the
cloud represents the ambiguous axis without mode collapse and
propagation anchors to the near-ideal 200 Hz odometry. Both arms
equally; all three candidate yamls regenerated.

**Requalification (all retained) and the honest readout:**

| Attempt | Result |
|---|---|
| amcl05-smoke-1 | **PASS — all 27 checks** |
| amcl05-off-1 | **PASS — all 35 checks, `goal_succeeded`**; std_y max 0.69 on the through-route |
| amcl05-on-1 | **PASS — all 36 checks, `goal_succeeded`**, exposure 0.000 m, clearance 0.431 m, max path deviation 0.938 m (recovered), arrival divergence 0.871 m — **but std_y max 0.948, essentially unchanged from 0.92 pre-fix** |

The primary readout did NOT move: the y-covariance growth is intrinsic
to the scene's scan ambiguity (the likelihood itself is y-ambiguous;
the cloud honestly reflects it). What the revision may still buy is
reduced mode collapse — this draw's divergence (0.87 m) and recovered
deviation are consistent with that but one trial cannot distinguish.
The series remains the measurement; the ~13%/trial risk may persist,
and if the limit-cycle class recurs the remaining options are the
goal-checker yaw question (with the divergence record front and center)
or the sign-off discussion of the corner's three layers.

## Series-23 (October 29–30, 2026): **PASS — the first complete Phase 6 series**

All 58 trials passed, the series gate green with no problems:

- **20/20 nominal pairs** (40 trials, both arms, `goal_succeeded` every
  trial), zero limit-cycle occurrences in 20 on-trials (the class that
  killed series-21/22 at ~13%/trial), zero corner-cut exposures (the
  on-arm aggregate exposure **0.000 m** vs the off-arm baseline
  **28.084 m** — a 100% reduction against the ≥90% gate).
- **All 9 negative-pair trials**: target-absent 6/6, target-removal
  6/6, perception-failure 6/6 with the fault-stop criteria met in every
  trial (the fail-closed stop validated under the final candidate).
- **Zero collisions**; 5 infrastructure-liveness deaths, all recovered
  by the fresh-fixture-pod retry ladder with zero topology recycles.
- **Completion semantics (the sign-off item)**: belief/truth divergence
  at arrival — off-arm max 0.889 m, on-arm max 1.161 m (mean 0.70 m
  across the series; no multi-metre divergences). Every trial's
  divergence is recorded in its record and in the series result's
  per-arm `completion_divergence` summary, as the October 28 fork
  decision required: visible, not silently accepted.

The final candidate: image `348fc584` (endpoint-capture controller
overlay + the sensors-override chain), lookahead 0.5 / min 0.25 /
inflation 0.45, AMCL 2000-8000 particles / alphas 0.1, pose-delta
stationary predicate, extended liveness ladder. The remaining open
items for sign-off: the belief-frame arrival semantics (divergence
0.36–1.16 m at arrival), the intrinsic AMCL y-ambiguity (std_y ~0.95,
mode-collapse-free in this series), the gz-transport capture-trace
delivery race (worked around by the retry ladder, root mechanism still
open), and the standing recognition waiver.








## The goal-approach endgame failure root-caused (October 28, 2026, `controller-block-threadprobe-2`)

The "controller's goal-approach block" that stopped the terminal-hold
validation run is **a recurring ~100–120 ms console-server physics stall at
the goal-approach boundary**. Three instances are now pinned from retained
native traces, all with the same signature (`dt_wall ≈ 103–120 ms`,
`dt_sim = 2.0 ms` — exactly one physics step, i.e. the stall is inside a
single iteration): series-14 trial 003-on (~120 ms, the stall-gap variant
the terminal hold covers), `terminal-hold-validation-on` (114.6 ms), and
`controller-block-threadprobe-2` (103.4 ms).

The mechanism, proven end to end in threadprobe-2's evidence:

1. **The console server's physics thread stalls** ~103 ms inside one
   iteration (normal cadence 6 ms wall / 4 ms sim). The thread probe shows
   the physics/main thread (steady ~80% CPU) blocked through the window
   while a normally-light render/sensor-path thread (~11% CPU) **burst to
   ~full core (~200 ms of CPU)** — a pathological RGB-D frame. The camera
   frame at the stall instant (sim 45.600) **never captured** (the
   observation record's capture-stamp sequence jumps 45.5 → 45.7).
2. **`/clock` freezes domain-wide** for the stall's duration (the clock
   derives from sim time): the fixture's own `ros`, the controller's
   stamps, AMCL and the costmaps all freeze at the same sim value. The
   native status stream gaps identically (the watchdog fills its UDP slot
   from the physics thread).
3. **The controller never stops cycling.** Its wall-timer cycle keeps
   firing at exactly 40 Hz (25 ms `source_timestamp` spacing) and
   republishes the SAME frozen sim stamp — the earlier "silent controller
   stop" narrative (and the smoother-ramp attribution for the repeated
   terminal-stamp raws in the validation run) is corrected by this
   evidence: those repeated raws are the controller's frozen-stamp
   republishes.
4. **The chain correctly fails closed.** The ledger's stamp-monotonic
   contract rejects the duplicate stamps; no NEWER sim stamp can exist
   while the clock is frozen, so both the admission-scheduling grace and
   the terminal-deceleration hold (which each structurally require a
   newer validated source) cannot fire; the previous source's fixed
   100 ms lifetime expires mid-stall → `command_expired`. Bridging a
   frozen clock would be optimistic authority and is rejected.

The stall reproduced on `ip-10-0-55-116` — an exact hardware match
(g5.2xlarge / A10G / driver 580.95.05) at ~3% CPU load versus the
qualified node's ~30% — so it is intrinsic to the console server's
render/physics coupling at the goal-approach viewpoint, not node
contention. All three stalls sit at the goal-approach boundary (after the
detour, at the approach view), consistent with a viewpoint-dependent
one-time render cost (new scene content). The rate on the current chain
is **3 stalls in the last 10 goal approaches** (series-14's 7 passes +
003-on, the validation run, threadprobe-2) — the Phase 6 series gate is
infeasible until the stall is addressed.

Instrumentation notes: the in-act gdb stacks were denied
(`Permission denied` — ptrace is blocked by the current pod security
context; the earlier in-act stacks ran under a different one), but the
snapshot retained per-thread wchan/syscall (the controller's threads all
in `futex_wait_queue`, alive and switching through the block — the
controller process was healthy throughout). The trial's own
`native_capture_stale`/`native_stationary_after_task` failures are the
documented gdb-fork artifacts; the thread probe runs in a separate
process and its timeline is clean.

**Off-arm trials (attempts 1–6, all retained)** — 25/26 checks PASS each;
the single failure is `guarded_real_hotel_one_meter_goal`: terminal 5,
`command_expired`, deterministically at **x≈16.5** (0.44 m before the mat,
~8 s of motion at 0.15 m/s). Attempts 1–2 present as a "silent controller
stop"; attempts 3–6 (with instrumentation) reveal the unified mechanism:

**Root cause (narrowed)**: the fixture's native-status UDP ingest ages past
the 100 ms `native_capture_stale` bound (attempts 3–6 latch
`native_capture_stale`; attempts 1–2 are the 20–100 ms variant that breaks
the 20 ms capture-bracket joins without latching). The chain then fails
correctly: joins fail → checked-command admissions stop → the ledger
expires the 100 ms source lifetime → `command_expired`. Attempt 6's in-act
capture proves the controller was STILL PUBLISHING 4 ms before the trip —
the controller, TF, scan, costmaps, native physics and the 88-chain are
all healthy through the failure (worker p95 age 212 ms); the console
process publishes native status on time (dense capture walls, no motion
gaps); every pump stage is fast (max one 54 ms ingress event). The delay
is confined to the UDP delivery / fixture receive-thread path under the
phase-6 pod's load. The phase-6 pod differs from the 10/10 passing Phase 5
observation-series pods by the 85-semantic-bridge sidecar (a second
26 MB/s zenoh reception into the pod, republished on domain 85) and the
label relay.

**Retained instrumentation**: `controller-block-snapshot.json` captures
post-failure /proc thread states and bounded gdb stacks (synchronously at
the fixture's stop detection since attempt 6); the earlier attempts'
snapshots fired post-cancel and show the normal idle state — retained as
negative evidence that no thread leaks or crashes accompany the failure.

**Corrected root-cause record (UDP-timing diagnostic, `pair-1-off-udptiming`)**

The instrumented receive thread exonerates every earlier theory; the
final, best-evidenced mechanism of the off-arm `command_expired`:

- The **controller ran perfectly** the whole trial: raw commands at
  0.150 m/s with steadily advancing stamps until the coordinator's cancel,
  which it processed within ~50 ms (the final zero raw is the cancel's
  `publishZeroVelocity`; the smoother's deceleration ramp after the trip
  reuses that terminal stamp — the known Wait-transition pattern).
- The **physics, native UDP path (both directions), pump stages, TF, scan,
  costmap and contact streams were all healthy** through the failure:
  receive-thread recvfrom p50 5.11 ms / max 102 ms, appends max 0.37 ms,
  steady 19–20 receipts per 100 ms, physical captures advancing every
  bucket, scans at normal cadence. The `native_capture_stale` latches and
  1.6 s "UDP freezes" in earlier attempts were instrumentation artifacts
  (gdb fork) or post-failure consequences (the physics stopping ~2.3 s
  after the trip, sequence 8275 frozen).
- The failure itself: the last admitted checked command carried stamp
  14.954 (admitted at −0.096 s); the checked commands at the final stamps
  14.970–15.010 were **not admitted** during the ~50 ms before the source
  deadline expired — a transient admission gap in the fixture's
  joiner/ledger plumbing (the ledger's source binding racing the
  capture-bracket timing for the final stamps), the same structural class
  as the known Wait-transition stamp-lag races, now appearing mid-route at
  the crossing goal's speed and ~0.65 RTF. The chain then failed closed
  correctly.

**Next instrumentation (not yet run)**: per-row joiner/ledger diagnostics
(the resolve outcome and bracket timing for each checked row at the final
stamps) to pin the exact admission-gap mechanism.

| Attempt | Result |
|---|---|
| 1 | command_expired at x=16.554; presented as silent controller stop (full speed, no log); clock clean |
| 2 | same, x=16.513 — deterministic |
| 3 | same + post-cancel stack snapshots (too late; cancel processed 3.6 s late proving the multi-second block) |
| 4 | same; in-act watchdog failed to fire (coordinator state gate bug) |
| 5 | same; watchdog still silent (thread never fired; replaced) |
| 6 | same + in-act synchronous capture: controller publishing 4 ms before trip; `native_capture_stale` latched — the admission chain, not the controller, expired |
| no85bridge | same failure without the 85-bridge — **the bridge is exonerated** |
| threadprobe | clean clock; controller worker thread (tid 452) exits AT the cancel; console physics 83% CPU, no starvation |
| udptiming | receive thread fully healthy; controller ran perfectly; **the failure is a ~50 ms checked-admission gap at the final stamps** |

**85-bridge isolation diagnostic (`pair-1-off-no85bridge-diag`)** — the
failure reproduces IDENTICALLY without the 85-semantic-bridge and relay
sidecars (`command_expired` at x=16.544, same profile otherwise): **the
85-bridge is exonerated**; the pod then matches the passing Phase 5
observation-series sidecar set, leaving the 4 m crossing goal itself as
the principal remaining delta.

**Instrumentation artifact identified and gated**: the
`native_capture_stale` latch in attempts 3–6 and the diagnostic is caused
by my own in-act gdb snapshot — the `subprocess` fork at the trip freezes
the fixture's UDP status receive thread ~1.66 s (the queued backlog then
drains in milliseconds; worst capture→receipt age 1663 ms exactly at the
trip), latching the clock and failing the stationary check. The snapshots
are now opt-in (`--phase6-controller-snapshot`) with the warning recorded.
**The pristine failure signature is attempts 1–2** (no snapshot code,
clean clock): the controller's raw output genuinely stops at x≈16.5 at
full speed with no log, the smoother's input-timeout ramp ages out, and
the ledger correctly expires. The controller stack itself was never
captured mid-block (the post-cancel stacks show normal idle; the in-act
capture's own side effects mask the timing evidence).

**Next investigation step (not yet run)**: a clean reconfirmation
(exact attempt-1 configuration, snapshots off) plus non-invasive
instrumentation of the controller process — the `--gz-thread-probe`
schedstat sampler extended to `controller_serv` runs in the separate
resource-probe process (no fixture GIL impact), and/or a nav2 controller
logging overlay. The remaining suspects for the silent stop are confined
to the controller process itself under the longer 4 m route.

## Root cause confirmed (read-only diagnostics `phase6-label-diag*`, deleted after each)

The label_info transient-local latch fails only when **both fixture-pod
bridges (88 and 85) connect to the private router simultaneously**:

| Diagnostic pod | Bridges | Subscriber timing | Latch |
|---|---|---|---|
| diag (single 85-bridge, exact fixture config) | 85 only | T+10 s | delivered (exit 0, correct JSON) |
| diag (single 85-bridge) | 85 only | T+75 s | delivered (exit 0) — late subscribers are served |
| diag2 (85 + 88 starting together, as the fixture pod) | 85 + 88 | T+10 s and T+75 s | **both time out (exit 124)** |
| diag3 (88 first, 85 delayed 30 s) | 85 + 88 staggered | T+60 s | **times out (exit 124)** |
| diag4 (85 + 88 together, probes on BOTH domains) | 85 + 88 | T+30 s | **both delivered (exit 0)** |

The bridge itself, the router, the SAM3-side cache and the DDS
transient-local handshake are all healthy in isolation. With a single
bridge the latch is reliable (the Phase 5 series shape: 30+ trials); with
two bridges subscribing the same transient-local key the delivery is
**nondeterministic** (diag2/diag3 fail, diag4 succeeds, all five smoke
attempts failed). Nondeterministic latch fan-out is unacceptable for
qualification, so the fix makes the 85 path deterministic: label_info is
exclusive to the 88-bridge and the `sam3-label-relay` sidecar republishes
the identical transient-local message on domain 85 for the costmap layers
(the relay's delivery is plain DDS, proven by the single-bridge
diagnostics).

## Findings so far (all before any motion)

1. **Wiring works**: both costmaps subscribe mask/points/timing/label_info on
   the safety domain through the runner's domain-85 semantic bridge sidecar
   (own CPU quota), and nav2's per-layer publishers exist in both maps.
2. **The semantic layer is the costmap-currency gate**: Nav2 cannot plan
   until the layer accepts a fresh observation. This is fail-closed by
   design and the fixture now respects it; it also means Phase 6 on-arm
   trials genuinely cannot plan without live accepted semantics.
3. **Stream ages are healthy** at the costmap (wall 190–381 ms, sim
   132–286 ms vs the 500 ms bound) — the domain-85 cloud delivery is not
   the rejection cause.
4. **The label_info latch is the sole blocker**: the layer's
   `receiveLabels` callback never fires in the fixture pod (instrumented,
   attempt 5), while the identical bridge config serves the latch to a
   transient-local subscriber in a quiet pod. The 88-chain delivers labels
   to the observation worker in every Phase 5 series trial, so the failure
   is specific to the 85-bridge/costmap path in the busy fixture pod.
5. RTF ~0.7 during the loaded Nav2 window (no cgroup throttling, no
   process saturated) — watch in moving pilots; the Phase 5 baseline was
   ~1.0.
6. odom→base TF gaps of 731/625 ms occurred during the Nav2 node-launch
   CPU spike (before arming in these disarmed smokes) — the known
   series-2-trial-2 load class on domain 85; the guarded readiness gates
   would catch it before arming in moving trials.
