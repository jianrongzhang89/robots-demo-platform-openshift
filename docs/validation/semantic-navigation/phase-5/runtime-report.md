# Phase 5 shared navigation and stop qualification

Updated: October 26, 2026. **PHASE 5 ACCEPTED — evidence review approved by
the user on October 26, 2026; Phase 6 unlocked.**

All four Phase 5 moving gates pass on the identical frozen guarded GPU
profile. The
[armed semantic fault matrix](#armed-semantic-fault-matrix-the-supervisor-stops-on-perception-loss-while-costs-stay-excluded)
closed the fourth and final gate: the semantic-task supervisor
armed with camera/semantic/inference-heartbeat leases at the unchanged 500 ms
capture-age freshness while semantic costs stayed excluded from navigation,
and five fault classes (camera path loss, TF loss, hung inference, process
loss, transport loss) each stopped the chain fail-closed with a mode-qualified
first reason, native zero within 0.3–2.6 ms of the freshness trigger, an
**observed** late success that did not resume motion — **10/10 matrix
trials** (`semantic-fault-matrix-13-20261026`) on the identical frozen GPU
profile. With the
[recovery repeatability](#fourth-series-attempt-1010--recovery-repeatability-subgate-passed),
[moving fault-stop](#moving-fault-stop-probe-five-fault-classes-on-the-qualified-guarded-fixture)
and
[moving SAM3 observation](#moving-sam3-observation-registration-under-motion-and-load-on-the-guarded-fixture)
gates, **all four Phase 5 moving gates now pass**; twelve retained matrix
series document the infrastructure findings fixed along the way (a zenoh
client session never re-dials a lost router; the perception topology recovers
from backend loss by pod recreation, not in-place process restart alone).
Phase 5 acceptance now awaits the evidence review.

Earlier: the
[Wait-transition stamp-lag diagnosis](#wait-transition-stamp-lag-diagnosis-the-smoothers-terminal-ramp-not-clock)
refuted the `/clock` hypothesis from retained evidence — the 70–90 ms lag is
the velocity smoother's terminal deceleration ramp reusing BackUp's terminal
zero-command stamp — and the user-approved renewal/confirmation split removed
the native-status round trip from the hold's critical authority path. A fresh
GPU pilot passed all 31 checks with a 20.08 ms renewal margin (versus 0.78 ms
in the failed trial), and the
[fourth ten-trial GPU series](#fourth-series-attempt-1010--recovery-repeatability-subgate-passed)
completed **10/10 trials**, closing the recovery-repeatability subgate — the
first of the four Phase 5 moving gates. The
[moving fault-stop probe and frozen matrix](#moving-fault-stop-probe-five-fault-classes-on-the-qualified-guarded-fixture)
then closed the second: five fault classes (collision-monitor STOP state,
supervisor scan-evidence cutoff, controller stall, native transport loss,
and a physically spawned obstacle detected by the real monitor) each stopped
the chain fail-closed with a mode-qualified first reason and 1.7–2.3 mm
sampled stopping distances, **10/10 matrix trials** on the identical frozen
GPU profile. The
[moving SAM3 observation series](#moving-sam3-observation-registration-under-motion-and-load-on-the-guarded-fixture)
closed the third: observation-only SAM3 running beside the guarded chain
under a UDP companion path for the watchdog's status and leases (the
perception camera's gz-transport load had delayed the status publication
itself by p95 ~575 ms, which the 20 ms capture-bracket joins cannot
absorb), the ten-trial series passing **10/10 with 100% capture-time
registration over ~850k projected points per trial**, p95 capture age
~190 ms and ~7 results/s. Earlier the same day, the first
authorized [isolated-node recovery pilot](#october-23-isolated-node-recovery-pilot-fail-closed-stop-at-the-wait-transition)
failed its guarded recovery subgates on a newly characterized Wait-transition
race in the fixture; the safety chain stopped the robot fail-closed. The
[user-approved wait-hold fix](#wait-hold-timing-fix-same-day-user-approved)
then passed a fresh pilot, and the
[ten-trial recovery series](#ten-trial-recovery-series-stopped-on-trial-1-by-a-simulator-stall)
stopped on trial 1 from a 158 ms in-pod physics stall during FollowPath. The
[thread-probe diagnostic](#gazebo-thread-probe-diagnostic-physics-stalls-are-in-process-rendering-saturation)
then identified the mechanism: continuous in-process software rendering
(llvmpipe, ~3 cores) saturating the console Gazebo server, with the fatal
stalls being CPU-bound bursts on the simulation-iteration thread — not node
contention, transport, or scheduler starvation. The user-selected
[GPU-rendering remedy](#gpu-rendering-trials-stalls-eliminated-full-pass-on-the-third-trial)
then eliminated every motion-phase stall and passed all 31 recovery checks
on the third trial after an Xvfb-library conflict and a wait-interval
contract issue were fixed. The
[GPU series](#gpu-series-trial-2-exposed-a-goal-endgame-race-series-stopped-per-the-no-retry-rule)
passed trial 1 and stopped on trial 2's goal-endgame deadlock, which was
[proven and fixed](#goal-endgame-deadlock-proven-and-fixed-four-validation-trials-pass)
(four subsequent validation trials all pass, including a +13.5 cm
localization drift). The
[private TF-loss subgate passed](#october-19-tf-loss-subgate-pass-in-the-private-geometry-only-fixture)
with the normal 500 ms input freshness and 100 ms command freshness thresholds.
The [armed semantic fault matrix](#armed-semantic-fault-matrix-the-supervisor-stops-on-perception-loss-while-costs-stay-excluded)
passed 10/10 on October 26, closing the last moving gate; the overall Phase 5
gate remains on HOLD only for the evidence review.

The user approved the Phase 4 review and requested Phase 5. This authorizes
isolated baseline navigation/safety testing, not Phase 6 semantic steering or
canonical hotel changes. Phase 2 recognition review/scoring remains deferred
under the existing demo waiver; nothing here qualifies recognition accuracy.

## October 23 isolated-node recovery pilot: fail-closed stop at the Wait transition

The user reserved a non-GPU moving window and selected a light-loaded worker.
The runner's placement guard verified `ip-10-0-15-146` Ready and GPU-free
before creating resources (after [aligning the guard](#guard-alignment-below)
with the committed series-runner contract). The pinned console candidate was
rebuilt from the unchanged committed sources as build
`semantic-safety-console-phase5-14`
(`semantic-safety@sha256:0eb68793d47d1a23fc6e7beaeb1aacd65c902ccbb9b50cba2c1ed3305dac708b`)
because the October 19–20 Build objects had been TTL-pruned; no source changed
since the October 22 preflight. The trial retained the full guarded profile:
hotel-guarded suite, BackUp/Wait/FollowPath recovery probe, contact audit,
console-only server, rear casters, 2 ms physics, 12 m lidar, 200 Hz odometry.

The pilot is retained at
[recovery-pilot-isolated-1-20261023](recovery-pilot-isolated-1-20261023/).
All 31 pre-integration checks passed (169 unit tests, frame bridge, hotel
adapter, native lease). The fixture localized, planned the 0.50 m goal, and
**BackUp completed with 211 bounded reverse commands at −0.05 m/s**. The trial
then stopped fail-closed during the Wait interval with terminal status 5
(`native_session_lost`) and failed the guarded recovery subgates. The pod was
otherwise healthy: dense 4–6 ms physics samples, only 6 throttled cgroup
periods across the run, and an 8–22 ms coordinator lease cadence with no pump
stall. **The isolated reservation eliminated node contention as a factor.**

Root cause (measured, not inferred): during Wait no new checked commands can
be admitted — the command chain's stamps stop advancing, so zero commands
resolve against the aging capture bound and are rejected as
`source_rejected_or_expired`. Command authority is then sustained only by the
coordinator's zero-wait hold, which requires the owned Wait child plus the
native watchdog armed and applying zero; it first fired **66.7 ms after the
Wait action started**. Meanwhile the regular 20 ms lease tick had already
emitted lease 216 carrying only **10.87 ms** of remaining command authority
(bound to the last admitted command's 100 ms lifetime). The watchdog's 2 ms
lease margin put its expiry 0.2 ms before the refreshed hold lease arrived;
the watchdog correctly stopped `lease_expired`, applied zero within 1.55 ms,
and cleared the session. Total displacement was 0.103 m (the bounded BackUp
reverse motion); no forward motion was ever applied.

This race is latent in the fixture, not new: the October 19 diagnostic-1 run
that completed Wait shows the same 69.5 ms hold delay and also emitted three
short leases (minimum 12.51 ms) — a ~1.6 ms difference in remaining authority
decided survival. The Wait transition therefore has a randomized few-ms
margin between command-deadline exhaustion and wait-hold refresh. A pilot pass
under this margin would not justify the frozen ten-trial series, which stops
on first failure; the series remains unstarted per the existing rule. No
capture-age, command-lifetime, lease, or stop threshold was changed, and no
guard was weakened. Candidate remedies (earlier wait-hold evaluation on the
pump path, with the same owned-child and armed-zero proofs) require fixture
changes, full local test reruns, and a fresh passing pilot before any series.

**Wait-hold timing fix (same day, user-approved):** the hold's measured delay
decomposed into 57 ms of velocity-smoother deceleration to the first
admissible zero command plus ~9 ms waiting for the native status to confirm
`applied_vx ≈ 0`. That confirmation is redundant — the hold only ever
forwards the gate's zero velocity (checked as a precondition), and the
watchdog revalidates every lease and remains fail-closed — so the applied-
value terms were removed from the coordinator's `zero_wait_hold` native-status
precondition. Session match, armed, and not-pending remain required, as do
all owned-task and gate-zero proofs. The hold now renews in the same observer
pass as the zero-command admission, converting the measured −0.2 ms race
margin into ~9 ms. A regression test covers the lagging-applied-value case
and the still-blocking session/disarm/pending cases; 170 safety tests and 33
launcher/series tests pass. The evidence chain above is unchanged; a fresh
pilot with this fixture follows below.

### Second isolated-node pilot with the fixed fixture: PASS

The console candidate was rebuilt with the fix as build
`semantic-safety-console-phase5-15`
(`semantic-safety@sha256:db3cd6ea1c79b95ce99631a18800dfbbbba44b7375202e5bc758b809fcb1b27e`)
and rerun on the same pinned Ready GPU-free worker with the identical guarded
profile. The pilot is retained at
[recovery-pilot-isolated-2-20261023](recovery-pilot-isolated-2-20261023/):
**all 31 checks passed** and the recovery probe reached `goal_succeeded`.
BackUp completed with bounded reverse commands, the Wait interval held zero
with 180 native zero samples (maximum applied velocity 0.0, maximum sample
gap 5.5 ms), and FollowPath completed the 0.50 m goal with independent native
displacement of 0.302 m (≥ 0.20 m required) at the qualified 0.15 m/s cap.
The guard applied zero within 2.96 ms of completion and the robot settled
0.8 mm from its final pose.

The fix behaved as designed: the first zero-wait hold fired 54.3 ms after
the Wait action started (as soon as the decelerating command chain admitted
its first zero — motion is never converted to zero by design), 370 holds
sustained the interval, and the minimum lease remaining authority was
18.59 ms versus 10.87 ms in the failed pilot. This is a private-fixture
pilot pass under the frozen guarded profile; it is not the ten-trial
recovery-repeatability qualification, which remains unstarted and requires
the fixed series runner on the same pinned non-GPU worker.

### Ten-trial recovery series: stopped on trial 1 by a simulator stall

The user authorized the frozen ten-trial series on the same reserved worker
and pinned image. The series is retained at
[recovery-series-isolated-1-20261023](recovery-series-isolated-1-20261023/);
it stopped on the first trial per the no-retry rule.

**Trial 1** completed BackUp and — confirming the Wait fix under series
conditions — the full Wait interval held zero with 180 native samples and no
pre-zero anomalies. During the subsequent FollowPath leg the trial stopped
fail-closed with `command_expired`: the physics sample stream showed a
**158.3 ms stall** at simulation time 15.1 s, which froze the command capture
sources, collapsed the final lease to 4.58 ms of remaining authority, and
expired it. The watchdog's zero application was itself delayed to 79.6 ms
because the physics thread was inside the stall; the robot stopped with 1.7
mm post-stop displacement and 0.131 m total (below the 0.20 m independent
motion minimum, so the task failed). No clock rollback occurred and the
cgroup recorded no new throttling (7 periods, 566 ms total across the run).

This is the known simulator-stall class, not node contention and not the
Wait race: the pod was using ~6 of its 8-CPU limit at the stall with the
node at 3–4% overall, and all coordinator pump stages stayed fast (maximum
18.7 ms). Both isolated-node moving runs show the same deterministic early
stalls (~35–45 ms at sim 2.2, ~103–105 ms at sim 5.8) which both survived;
the passing pilot's FollowPath stall was only 33 ms while trial 1's was
158 ms. With the 100 ms command-freshness contract, any stall beyond 100 ms
during active motion fails a trial by design (correct fail-closed behavior),
so the series cannot reliably pass while such stalls occur sporadically.
Per the frozen rule the series was not retried; a retry-until-pass pattern
would be dishonest. **Recovery repeatability remains HOLD; the Wait-transition
fix stands verified; the remaining blocker is the in-pod physics-stall
issue**, for which Gazebo-side source-publish timestamps were not yet
captured and thread-level scheduling contention inside the single-pod
fixture (Gazebo physics plus the full Nav2 stack) is the credible mechanism.

### Gazebo thread-probe diagnostic: physics stalls are in-process rendering saturation

The user selected read-only instrumentation. A new opt-in `--gz-thread-probe`
runner flag (commit `e2435e2`) extends the resource probe to sample every
thread of the console Gazebo and Collision Monitor processes — schedstat
(on-CPU vs run-queue wait), utime/stime, state, and context-switch counters —
at 20 ms. The instrumented trial is retained at
[recovery-threadprobe-1-20261023](recovery-threadprobe-1-20261023/); it
reproduced the fatal class (a 169.8 ms physics stall at sim 15.4 s during
FollowPath, `command_expired`, correct fail-closed stop) with full thread
data through the stall.

**Findings.** Across the fatal 181 ms stall window the console process main
(simulation-iteration) thread consumed **162.7 ms of on-CPU time with 0.3 ms
run-queue wait** — the physics iteration was neither scheduler-starved nor
IO-blocked; it was executing CPU-bound work. Four `llvmpipe` threads (Mesa
software OpenGL; the node has no GPU) each consumed ~22–24 ms in that window.
The deterministic early stall at sim 5.8 s shows the complementary signature:
llvmpipe-dominated (286.7 ms across the four render threads) with the main
thread at only 18.2 ms. Critically, **normal non-stall windows show the same
saturation continuously**: during ordinary FollowPath and Wait segments the
main thread runs ~80% CPU and llvmpipe ~75% per thread (~3 cores of
rendering), so the pod sits near its 8-CPU limit the entire trial. The fatal
stalls are the tail of an always-saturated software-rendering pipeline — the
RGB-D camera (10 Hz, 640×480, installed for stack realism) rendered through
llvmpipe on a non-GPU node is the dominant consumer, and its synchronous
bursts occasionally block the simulation iteration beyond the 100 ms
command-freshness budget.

This closes the October 20 evidence gap: the stall is neither Gazebo
publication delay, nor transport, nor node contention, nor scheduler
starvation — it is in-process CPU saturation dominated by software rendering.
The safety chain behaved correctly in every instrumented failure. Candidate
remedies, all requiring an explicit profile decision because the camera is
part of the frozen hotel stack: run the fixture on a GPU node (hardware
rendering; currently restricted by the non-GPU placement policy), remove or
throttle the RGB-D camera for the Phase 5 recovery profile (it exists for
stack realism; Phase 5 does not run SAM3, but Phase 6 requires the camera in
both arms), or reduce the rendering cost (resolution/engine configuration).
Recovery repeatability remains **HOLD** pending that decision.

### GPU-rendering trials: stalls eliminated; full pass on the third trial

Following the thread-probe diagnosis, the user selected the GPU-node remedy.
Feasibility was verified stepwise on a free A10G worker: the GPU operator
injects the full driver stack when `NVIDIA_DRIVER_CAPABILITIES=all`
(`libEGL_nvidia` and the graphics libraries are mounted; they are absent with
the default compute-only capabilities), gz-sim 8 exposes
`ServerConfig::SetHeadlessRendering`, and every GPU node has exactly one free
GPU. The fixture gained an opt-in `--gpu-rendering` mode (commit `8396f49`):
pinned node, one `nvidia.com/gpu`, EGL headless rendering in the console
server, g5/g6e tolerations, and no forced software GL — the non-GPU profile
is unchanged.

[Trial 1](recovery-gpu-render-1-20261023/) aborted when **Xvfb segfaulted in
`InitExtensions`**: the pod-wide NVIDIA graphics libraries interpose its GLX
extension initialization. EGL headless needs no X server, so the GPU profile
no longer launches Xvfb (commit `63bdf13`).
[Trial 2](recovery-gpu-render-2-20261023/) then **eliminated every
motion-phase physics stall** (only the deterministic startup gaps and the
pre-arm ~104 ms sim-5.7 event remained) and passed 30 of 31 checks: the sole
failure was the wait-interval zero contract, because the earlier hold-timing
fix let the hold fire while the native still applied the −0.010 deceleration
step, starting the measured interval one pre-zero sample early.
[Trial 3](recovery-gpu-render-3-20261023/), after commit `227dbad`, **passed
all 31 checks to `goal_succeeded`**: the wait hold now requires the native
applied value inside the ≤0.005 settling tail and is evaluated on the pump's
native-ingest path (~650 Hz), closing both the original 0.2 ms deadline race
and the interval-start race. Wait normalization took 2.5 ms with zero
pre-zero samples, independent native displacement was 0.285 m at the 0.15 m/s
cap, and the guard applied zero within 3.8 ms of completion.

The instrumented trials retain thread evidence: no llvmpipe threads exist
under GPU rendering. These are diagnostic-profile runs (`--gz-thread-probe`);
a clean un-instrumented pilot and series follow the same path. The frozen
recovery series on the GPU node remains the gate for recovery repeatability.

### GPU series: trial 2 exposed a goal-endgame race; series stopped per the no-retry rule

The frozen ten-trial series ran on the GPU node with the clean profile.
[Trial 1](recovery-series-gpu-1-20261023/trial-01/) **passed all checks**.
[Trial 2](recovery-series-gpu-1-20261023/trial-02/) completed BackUp and Wait,
then FollowPath drove the goal distance but ended in an approximately
five-second pure-rotation endgame (RPP correcting a final heading error at
~0.02 rad/s with zero linear velocity) during which the command
stamp-to-capture-bound offset grew from the usual ~31 ms to ~45 ms. When the
controller reached the goal and stopped publishing, the BT's FollowPath
terminal status arrived **112.6 ms after the last capture bound** — versus
6.8/11.1 ms in the two passing GPU runs — exceeding the ~98 ms command
authority by 14.6 ms. The gate correctly tripped `command_expired`, the
watchdog applied zero within 1.97 ms, and the coordinator's cancel converted
the pending success into terminal status 5. The safety chain again behaved
fail-closed; no physics stall occurred.

This is the third timing race found in the recovery probe's action-endgame
paths (Wait handoff, wait-interval start, now goal conclusion), each pitting
Nav2's action-state propagation latency against the 100 ms command-freshness
contract. The first two were fixture-scheduling defects with clean fixes; this
one couples the controller's rotation-endgame stamp lag with BT conclusion
latency and needs diagnosis of why the passing runs concluded in ~10 ms while
trial 2 took ~64 ms after the last command. Per the frozen rule the series
was stopped and not retried. **Recovery repeatability remains HOLD.**

### Goal-endgame deadlock: proven and fixed; four validation trials pass

The goal-endgame diagnosis closed with the fixture's own control-geometry:
the goal checker transforms the path end into the local costmap's odom frame
at the path's **planning stamp**, so AMCL drift holds that target fixed
while RPP's current-frame carrot tracks the corrected estimate. Trial 2
parked at 0.185 m (current) vs 0.203 m (stale) — a 1.9 cm drift separating
the two 0.2 m tolerance targets — with RPP's rotate-to-goal-heading
commanding zero linear velocity permanently between them (five seconds of
micro-rotation, the checker never firing, the wz values matching RPP's
deceleration-clamped rotate formula exactly). The passing trials had won
only by approach-creep momentum through the stale target — a coin flip on
the drift. The earlier TF-block hypothesis was refined: TF-edge lateness
(119–132 ms scan-transform waits) occurs in **every** trial including
passes, and the controller's cycle cadence is otherwise a rock-steady
25 ms.

The fix (commit `5136c3e`): `use_rotate_to_heading=false` in the recovery
profile — the straight 0.5 m probe goal needs no in-place rotation, and
without it the approach creep carries the robot through the checker's
stale target with the 0.35 rad yaw tolerance covering the residual approach
yaw. Four validation trials on the GPU node then **passed all checks**
(`recovery-gpu-deadlockfix-1..4`): FollowPath 3.8–4.2 s, zero rotation
phases, terminals 6.9–11.3 ms after the last capture bound, and final
stale-vs-current drift of +13.5/−0.2/−3.5/−0.3 cm — including a +13.5 cm
drift far exceeding the deadlocking 1.9 cm, carried through cleanly. A
read-only `map→odom` TF edge recorder was also added (commit `d7c7fc8`,
`tf-edges.json`) confirming the AMCL edge cadence (100 ms sim-time, 121–135
ms wall at ~0.8× real time) in the same trials.

### Intermediate hypothesis: controller TF wait (superseded)

The controller server in nav2 1.3.13 has exactly one class of silent
mid-goal block: synchronous TF lookups (`getRobotPose` and RPP's transforms,
`transform_tolerance` 0.2 s) that wait on a timed condition for a transform
edge. Trial 2's evidence fits no other path: the controller published at a
steady 25 ms cadence and then stopped **without** goal-reached, cancellation,
or error logging while the action stayed EXECUTING — a blocked loop — and the
coordinator's cancel was processed 74 ms later. The local costmap kept
updating through the window (10 Hz footprint updates, no gap), and sensor
deliveries stayed steady, excluding the costmap-currency wait. A
current-time `map→odom` lookup waits for the next AMCL edge, which is
published per scan; the endgame ran at ~0.8× real time (scan arrivals
120–135 ms apart), and the guard's scan-TF audit records a 7-attempt/23 ms
transform failure beginning 120 ms after the controller stopped — direct
evidence that TF edges were late in exactly that window. This is the same
late-exact-time-TF mechanism the corrected October 20 trace established for
the Collision Monitor, now on the controller's path, occurring without any
physics stall.

Remedies follow the October 20 prescription: confirm with TF-producer
instrumentation on the armed profile (the existing TF probes currently run
only in the disarmed Collision Monitor diagnostic profile and would need a
guarded extension), and reduce TF-edge latency exposure. Never substitute
latest/stale TF. The safety chain's fail-closed behavior is correct and
unchanged. **Recovery repeatability remains HOLD.**

### Wait-transition stamp-lag diagnosis: the smoother's terminal ramp, not `/clock`

The third series' evidence pointed at a `/clock`-to-physics offset degrading
during the BackUp→Wait transition. Reconstructing the exact command timeline
from all six retained Wait-transition trials (gpu-3 trials 1–2, gpu-2 trial 3,
deadlockfix-4, pilot-isolated-1, gpu-render-2) refutes that hypothesis and
localizes the lag deterministically:

- **Raw behavior-server commands never degrade.** Their stamp-to-publish lag
  stays at 0.4–7 ms through every trial including the transition (one 15 ms
  outlier in gpu-2), so the sensor bridge's `/clock` publication and its
  receipt by the command chain are not the source.
- **The 70–90 ms lag is the velocity smoother's terminal deceleration ramp
  reusing one stamp.** BackUp's completion publishes a terminal zero command
  stamped at the completion sim time; the smoother then ramps −0.050 → 0 m/s
  at the qualified `max_decel` 0.8 m/s² in exactly **7 × 10 ms steps**, and
  with `stamp_smoothed_velocity_with_smoothing_time: false` every ramp step
  carries that terminal command's stamp. Each step therefore consumes 10 ms
  of the terminal command's fixed 98 ms authority: the first ramp step lands
  at 23–32 ms of lag, the last admissible settling-tail step (−0.002 m/s) at
  76–84 ms, and the zero step at 85–94 ms — admitted in the passing trials,
  expired on arrival in gpu-3 trial 2. The structure is identical in passing
  and failing trials; it is not probabilistic simulator or clock behavior.
- **What actually decided pass/fail** is the wait-hold's native-status
  confirmation round trip (lease delivery 0.6–4 ms, native applies, status
  publication, ingest — together ~7–8 ms) racing the ~10–19 ms of authority
  remaining on the settling-tail command. Passing trials won with 6–13 ms of
  margin; gpu-3 trial 2 had **0.78 ms** and lost to delivery jitter.

**Fix (user-approved, same day): authority renewal split from interval
confirmation.** The coordinator gained `renew_wait_zero()`, which renews
zero-only Wait authority as soon as the command chain admits its
settling-tail command (|v| ≤ 0.005 m/s) during an owned Wait. It keeps every
precondition of the confirmed hold except the native applied-value terms:
session match, armed, not pending, owned task, and the gate's settling tail
all remain, and a command beyond the tail can never be converted to zero.
The zero lease can only stop the robot sooner; the native watchdog
revalidates every lease and stays fail-closed, and session disarm or loss
still stops immediately. This mirrors the reasoning of the earlier
user-approved hold fix: the applied-value confirmation is redundant on the
authority critical path. `zero_wait_hold()` keeps its exact semantics — it
fires only once the native applied value is inside the ≤0.005 tail and
remains the measured Wait-interval anchor, so the gpu-render-2
interval-start race stays closed by construction. Renewals record a separate
`wait_zero_renewal` event; confirmed holds remain the only interval anchors.

Local verification passes **173 safety tests** — three new: renewal precedes
native confirmation while the confirmed hold stays blocked on a lagging
−0.010 applied value; renewal is blocked outside the settling tail so real
motion is never zeroed; and the interval metric excludes pre-confirmation
deceleration samples because it anchors at the confirmed hold — plus 96
Phase 5 runner/series tests, Python compilation and `git diff --check`.

**Fresh pilot: PASS with the race margin restored.**
[recovery-waitrenew-pilot-1-20261023](recovery-waitrenew-pilot-1-20261023/)
ran the identical frozen guarded GPU profile (build 21 image
`e1bc5f2b…`, pinned node `ip-10-0-44-146`, 2 ms physics, 12 m lidar,
200 Hz odometry, rear casters, console-only server, contact audit) with only
the ConfigMap-mounted Python fixture changed. All **31 checks passed** to
`goal_succeeded`. The first renewal fired at settling-tail admission and its
zero lease carried **20.08 ms of margin** over the decaying −0.002 lease —
versus 0.78 ms in the failed gpu-3 trial 2 — with the first confirmed hold
5.07 ms behind it. The Wait interval held zero over 218 native samples with
zero pre-zero samples, 2.2 ms normalization latency, and 573 confirmed holds
at a 7.26 ms maximum gap. The guard applied zero 6.97 ms after completion
with 0.97 mm sampled settling displacement and 0.2998 m independent native
displacement at the 0.15 m/s cap. This is a private-fixture pilot pass under
the frozen guarded profile; the frozen ten-trial recovery series follows.

### Fourth series attempt: 10/10 — recovery repeatability subgate PASSED

The frozen ten-trial series
[recovery-series-gpu-4-20261023](recovery-series-gpu-4-20261023/) ran the
identical guarded profile — build 21 image `e1bc5f2b…`, pinned GPU node
`ip-10-0-44-146`, 2 ms physics, 12 m virtual lidar, 200 Hz odometry, rear
casters, console-only server, contact audit — with the renewal fix frozen
into the series source hashes and no retries or runtime-input changes:
**10 planned, 10 attempted, 10 successful**, every trial passing all 31
checks to `goal_succeeded`.

| Measurement | Ten-trial result |
|---|---|
| Goal/contact/stop/recovery checks | 10/10 trials, 31/31 checks each |
| Renewal margin over the decaying settling-tail lease | 15.30–28.26 ms (failed gpu-3 trial 2: 0.78 ms) |
| Pre-confirmation renewals per trial | 2–3 |
| Wait-interval native zero samples | 215–223 per trial, **zero pre-zero samples in all ten** |
| Confirmed holds per Wait interval | 568–588, maximum gap ≤ 7.3 ms class |
| Normal-completion revoke → applied zero | 2.80–5.47 ms |
| Independent native displacement (0.20 m required) | 0.2875–0.3011 m at the 0.15 m/s cap |
| Clock faults / capture stalls | None |

Every trial's private pod/ConfigMap cleanup succeeded and the final
private-resource check is empty; the canonical hotel/camera deployments and
the Phase 6D demo pods remained running and unchanged throughout.

**Recovery repeatability: PASS** for the private geometry-only fixture
(fresh-world BackUp 0.10 m / Wait 1 s / FollowPath to a 0.50 m target under
the guarded command chain, GPU-rendering placement). This closes the first
of the four Phase 5 moving gates. **Overall Phase 5 remains HOLD** pending
moving fault-stop coverage, moving SAM3 registration/load qualification, and
the armed semantic fault matrix; Phase 6 remains HOLD pending Phase 5.

### Moving fault-stop probe: five fault classes on the qualified guarded fixture

The second Phase 5 moving gate injects one fault class at a time into the
identical frozen guarded GPU profile (build 21 image `e1bc5f2b…`, pinned
node `ip-10-0-44-146`, 2 ms physics, 12 m lidar, 200 Hz odometry, rear
casters, console-only server, contact audit) after a shared pre-injection
predicate proves an armed session with independently verified physical
motion (>0.02 m/s applied and physical, a fresh forwarded checked command,
≤100 ms capture age). Every watchdog, lease and freshness threshold is
unchanged; each trial requires a mode-qualified first stop reason, native
stop metrics, terminal cancellation, physical stationarity and no automatic
resume after the fault is restored.

| Mode | Injection | Qualified first reason |
|---|---|---|
| `collision_state` | CollisionMonitorState STOP message on the observed topic, cleared after the stop | `collision_monitor_stop` |
| `scan_loss` | supervisor-only scan-evidence cutoff (Nav2 keeps the real stream) | `scan_stale`/`tf_stale` in the ≥300 ms input-freshness band |
| `command_stall` | SIGSTOP of the controller server | `command_expired` |
| `transport_loss` | SIGSTOP of the native link worker | `native_session_lost`/`native_queue_unavailable` (watchdog lease expiry) |
| `obstacle_spawn` | a physical post moved mid-trill into the corridor | `collision_monitor_stop` with a real monitor STOP state and no contact |

**Obstacle-mode debugging history (three failed pilots, all retained, every
stop correct fail-closed):** the first pilot blocked the fixture pump with a
synchronous subprocess call for the ~305 ms Gazebo create-service round trip
and stopped `command_expired` with zero applied in 2 ms. The second launched
the spawn asynchronously but entity *creation* itself parses SDF and builds
scene geometry inside `PreUpdate`, stalling physics 190.5 ms — beyond the
100 ms command-freshness contract. The third pre-placed the post at a
map-verified staging pose 2.5 m off the corridor and moved it with the
blocking `set_pose` service (which only sets a `WorldPoseCmd` component);
the move was stall-free, but the subprocess's gz-transport connection
handshake stalled the simulation server 104 ms through the shared NodeShared
mutex — the same native-7 lesson. The final design follows the NativeLink
pattern: a persistent worker starts with the fixture while the robot is
disarmed, establishes and warms the `set_pose` connection with a no-op move
to the staging pose, and serves the injection move through files, so the
armed trial never creates a transport connection. The post sits inside the
Collision Monitor stop envelope (|y| ≤ 0.315 m) but outside the padded hull
(|y| > 0.165 m) and RPP's footprint collision check, with ~0.045 m drift
margin on each boundary, so real lidar returns must trip the monitor's STOP
while no footprint contact is possible.

**Scan-loss contract correction:** cutting supervisor scan evidence freezes
the scan lease and the scan-derived capture-time tf lease at the same
capture bound; both expire ~500 ms later and the first-named reason is an
iteration artifact (`tf_stale` in the failed pilot, `scan_stale` after). The
mode now accepts either reason and requires the stop to land ≥300 ms after
injection, proving the 500 ms input-freshness deadline — not the 100 ms
command deadline — produced the stop.

**Passing pilots** (`faultstop-pilot4-obstacle_spawn`, `faultstop-pilot5-collision_state`,
`faultstop-pilot6-{scan_loss,command_stall,transport_loss}`, all 31 checks each):

| Pilot | First reason | Injection → trigger | Trigger → applied zero | Sampled stopping distance |
|---|---|---:|---:|---:|
| obstacle_spawn | `collision_monitor_stop` (1 real monitor STOP state) | 3420.8 ms (approach) | 2.77 ms | 1.24 mm |
| collision_state | `collision_monitor_stop` | 51.2 ms | 2.20 ms | 2.3 mm |
| scan_loss | `scan_stale` | 422.9 ms | 0.81 ms | 1.7 mm |
| command_stall | `command_expired` | 73.6 ms | 0.39 ms | 1.7 mm |
| transport_loss | `native_session_lost` | 56.6 ms | 0.06 ms (native watchdog) | 1.7 mm |

No clock fault, no unexpected contact, and no automatic resume occurred in
any passing pilot; every fault was restored in a `finally` block. Local
verification passes 181 safety tests and 101 launcher/series tests,
including the fault-matrix acceptance function and the qualified-profile
placement guard.

**Frozen fault-stop matrix: 10/10 — moving fault-stop subgate PASSED.**
The frozen matrix [faultstop-matrix-2-20261023](faultstop-matrix-2-20261023/)
ran the identical profile with the probe frozen into the series source
hashes, no retries and no runtime-input changes: **10 planned, 10 attempted,
10 successful** (each fault class twice, rep-major order). An earlier
[matrix-1](faultstop-matrix-1-20261023/) attempt is retained as
tooling-interrupted: its single trial passed on the cluster, but the
matrix's own acceptance function demanded a check name the fault probe had
renamed (`baseline_native_stop_metrics` vs `fault_stop_native_stop_metrics`);
the corrected function accepts that trial.

| Trial | Mode | First reason | Injection → trigger | Trigger → applied zero | Sampled stopping distance |
|---|---|---|---:|---:|---:|
| 1 / 6 | collision_state | `collision_monitor_stop` | 45.6 / 50.8 ms | 4.74 / 2.81 ms | 2.0 / 2.3 mm |
| 2 / 7 | scan_loss | `tf_stale` / `scan_stale` | 391.5 / 361.6 ms | 0.83 / 2.10 ms | 1.7 / 2.0 mm |
| 3 / 8 | command_stall | `command_expired` | 72.9 / 82.6 ms | 0.92 / 0.29 ms | 2.0 / 2.0 mm |
| 4 / 9 | transport_loss | `native_session_lost` | 66.0 / 58.3 ms | 1.89 / 2.14 ms | 2.0 / 2.0 mm |
| 5 / 10 | obstacle_spawn | `collision_monitor_stop` | 3475 / 3512 ms (approach) | 1.86 / 3.63 ms | 2.0 / 1.7 mm |

Every trial passed all runtime checks (mode-qualified first reason in the
correct latency band, stop metrics, cancellation, stationarity, contact
window, no resume); no clock fault occurred; all ten private
pod/ConfigMap cleanups succeeded and the final private-resource check is
empty. The canonical deployments and Phase 6D demo pods remained unchanged.

**Moving fault-stop: PASS** for the private guarded fixture at ≤0.15 m/s
under the frozen GPU profile, covering collision intervention (both the
monitor state path and a real detected obstacle), supervisor input loss,
command producer stall and native transport loss. This closes the second
of the four Phase 5 moving gates. **Overall Phase 5 remains HOLD** pending
moving SAM3 registration/load qualification and the armed semantic fault
matrix; Phase 6 remains HOLD pending Phase 5.

### Moving SAM3 observation: registration under motion and load on the guarded fixture

The third Phase 5 moving gate runs the separately qualified SAM3 runtime
(image `478ec…`, prompt `red mat`) observation-only alongside the guarded
baseline on the identical frozen GPU profile — semantic costs excluded from
navigation, no semantic layer in any costmap. The fixture world already
contains the staged red mat, the distractor tile, the RGB-D camera and the
verified capture-time `map → camera_color_optical_frame` TF.

**Wiring.** Console build 23 (`1df223bc…`) gains the Phase 3 capture-trace
override: the pinned gz-sensors commit's patched `RgbdCameraSensor` is
recompiled against the image's exact installed gz-sensors 8.2.2 ABI (the
apt-installed dev package is deliberately NOT upgraded, which would have
silently changed the qualified runtime) and preferred via `LD_LIBRARY_PATH`
when `SEMANTIC_CAPTURE_TRACE=1`, so render-time capture traces are published
on the private Gazebo partition. The fixture pod gains two sidecars
mirroring the proven Phase 6D D1 wiring — the trace-instrumented camera
compressor (`semantic-hotel-sim@c3ba94b…`, gz input) and a scoped Zenoh
bridge exporting only the compressed camera streams, calibration, traces
and clock — plus a private router and a private SAM3 pod on the qualified
L40S placement. The checkpoint PVC is ReadWriteOnce node-locked to the demo
SAM3's node, so the series runner saves and deletes the parked demo pod,
runs the private topology for the whole series, and restores it in a
`finally` with retained evidence.

**Debugging history (five failed pilots, all retained, every stop correct
fail-closed):** (1) the Zenoh locator syntax — zenoh locators are
`tcp/host:port`, not `tcp://host:port`; (2) the runner's evidence commands
needed the fixture container named once sidecars existed; (3) a module
shadowing crash; (4) SAM3 received no frames until `camera_info` was
remapped from its gz name to the qualified contract's
`/robot_1/camera/color/camera_info`; (5) — the substantive one — the trial
stopped `command_expired` at 0.07 m with the command chain publishing
normally and no CPU throttling: the multi-megabyte semantic clouds
deserialized on the pump's observer executor hold the interpreter lock for
~10–15 ms and can expire the 20 ms raw-command capture-bracket joins. All
semantic processing moved to a separate worker process that owns the
subscriptions, hash-matches each timing record to its mask and cloud,
projects through its own TF buffer, and reports only through small files.
A sixth fix retries payload matching across out-of-order delivery (the
small timing records overtake their clouds through the cross-node
transport).

**Passing pilot** (`sam3-observation-pilot-10-20261026`, all 31 checks):
the guarded one-metre goal succeeded with SAM3 running — displacement
0.797 m, no clock fault, every command/contact/cancellation check green,
revoke-to-applied-zero 7.6 ms — answering the load question directly.
Registration under motion: **57 moving results, 833,659 capture-time
projected points, 100% inside the ground-truth mat rectangle** (minimum
per-result fraction 1.0, 0.10 m tolerance). Observation timing: p95
capture age 178.9 ms (500 ms admission bound), 7.21 results/s (≥5
required). Isolation: only the observation worker subscribes any semantic
topic; no costmap subscription exists. Local verification passes 187
safety tests and 105 launcher/series tests.

**The load finding and the UDP companion path.** The pilot passed, but
the first frozen series stopped on trial 2 and the following attempts
failed at 30–70% of trials on one mechanism, each retained and root-caused:
the perception camera's image publications (12 MB/s) hold the console
server's shared gz-transport mutex long enough to delay the watchdog's
status **publication itself** — measured p95 ~575 ms after physics while
the fixture's receive path is 0.5 ms median — which the 20 ms
capture-bracket joins cannot absorb; lease delivery and the arm/stop
service round trips showed the same exposure, and the observer's
best-effort `/clock` copy stalled `now.ros` past the join window under
the same load. Intermediate corrections — a single gz image subscriber,
DDS-domain isolation for every camera/semantic stream, the graph audit
moved off the command path per the October 19 prescription (bounded
fail-closed 500 ms freshness), a reliable `/clock`, and the guarded
future-stamp check consulting the authoritative native physics sim
instead of a transport-delayed `/clock` copy — each removed one failure
mode. The decisive fix (user-approved, C++): the watchdog gained a **UDP
companion path** — status leaves through a non-blocking loopback
`sendto` that no transport mutex can block, and leases, arm and stop
arrive through a dedicated UDP listener thread feeding the same guard
with unchanged proofs (arm acceptance is proven by the status stream's
session; stops are backstopped by the independent lease expiry; the
qualified gz paths all remain active). Rebuilding the image chain
(base → contacts → controller → console build 26, `f854b83…`) also fixed
the resulting teardown: `shutdown(SHUT_RDWR)` now wakes the listener
thread that `close()` alone left sleeping (teardown had raced every
bounded window: 5.9/16.7/31.6 s across pilots, all exiting 0 with a
complete lifecycle). Sixteen series attempts and eleven pilots are
retained in full; every intermediate stop was correct fail-closed
behavior.

**Frozen observation series: 10/10 — moving SAM3 subgate PASSED.**
[sam3-observation-series-20-20261026](sam3-observation-series-20-20261026/)
ran the identical frozen profile with observation-only SAM3 for all ten
trials, no retries and no runtime-input changes: **10 planned, 10
attempted, 10 successful**, every trial passing all 31 checks.

| Measurement | Ten-trial result |
|---|---|
| Registration (moving results per trial) | 52–61 |
| Capture-time projected points per trial | 788,509–944,960 |
| Pooled in-rectangle fraction | **1.000 in all ten trials** |
| p95 capture age | 187.2–195.2 ms (500 ms bound) |
| Results per second | 6.63–7.26 (≥5 required) |
| Guarded goal | 10/10 `goal_succeeded`, displacement 0.796–0.799 m |
| Clock faults / unexpected contacts | None |
| Cleanups | All ten trial pods/ConfigMaps removed; private topology torn down; the parked demo SAM3 pod restored on its L40S placement and Running |

**Moving SAM3 registration/load: PASS** for the private guarded fixture.
This closes the third of the four Phase 5 moving gates. **Overall Phase 5
remains HOLD** pending the armed semantic fault matrix; Phase 6 remains
HOLD pending Phase 5.

### Armed semantic fault matrix: the supervisor stops on perception loss while costs stay excluded

The fourth and final Phase 5 moving gate arms the semantic-task supervisor:
`SafetyGate(require_semantics=True)` adds three leases to the unchanged 500 ms
capture-age freshness contract — **camera** (fed from the render-time capture
traces, the authoritative camera heartbeat), **semantic** (the SAM3 timing
records, freshness measured by capture age) and **inference_heartbeat** (the
runtime's 20 Hz status, its ros field from the isolated domain-88 clock). The
observation worker sidecar reports all three through its status file and the
fixture's guard stage feeds them to the gate; arming requires every lease
present, and any expiry while armed stops the chain fail-closed. Semantic
costs remain excluded from navigation — no semantic layer in any costmap.

**Fault modes.** Five classes, each injected only after independently
verified semantic-armed motion (armed, ≥0.3 m displacement, a fresh semantic
result while moving — stronger than the fault-stop predicate, so the pre-fault
observation window is meaningful):

| Mode | Injection | Repair (late-success path) |
|---|---|---|
| `camera_path_loss` | fixture SIGSTOPs the camera bridge (capture traces, calibration and the domain-88 clock stop) | SIGCONT; the camera lease advances again |
| `tf_loss` | fixture pauses AMCL | SIGCONT; capture-time `map → camera` TF resolves again |
| `hung_inference` | runner SIGSTOPs the inference process (a bash-wrapper child — signals to a PID-namespace init are dropped, even SIGSTOP) | SIGCONT; the heartbeat advances |
| `process_loss` | runner SIGKILLs the inference process; `restartPolicy Always` restarts the container | automatic; the restarted process's heartbeat |
| `transport_loss` | runner force-deletes the SAM3 pod (the backend's whole connectivity vanishes instantly; the router and fixture-side session survive) | the runner recreates the pod; results resume through the live router |

Every trial requires a mode-qualified first stop reason, native applied zero
within 100 ms of the 500 ms freshness trigger, the late success to be
**observed** (a fresh perception response or restored capture-time TF, not
merely assumed) and no motion resume over the post-restore dwell. Readiness
gates order SAM3 readiness (300 s, covering a process-loss model reload)
before `adapter.ready`, and armed-semantic trials may only arm from a
sustained five-second fresh-result streak — the SAM3 stream has a
reproducible burst phase clustered before arming, and arming on a momentary
fresh receipt during those bursts starves the lease within seconds.

**Result: `semantic-fault-matrix-13-20261026`, 10/10 trials pass** (five
modes × two repetitions, frozen hashes, no retries).

| Trial | Mode | First reason | Injection → trigger | Trigger → zero | Late-success key |
|---|---|---|---|---|---|
| 1, 6 | camera_path_loss | `semantic_stale` / `camera_stale` | 367 / 388 ms | 1.4 / 1.0 ms | camera |
| 2, 7 | tf_loss | `command_expired` | 231 / 224 ms | 0.8 / 2.6 ms | capture-time TF |
| 3, 8 | hung_inference | `semantic_stale` | 1963 / 994 ms | 1.7 / 0.8 ms | inference_heartbeat |
| 4, 9 | process_loss | `semantic_stale` | 1473 / 1423 ms | 2.0 / 0.3 ms | inference_heartbeat |
| 5, 10 | transport_loss | `semantic_stale` | 1394 / 1023 ms | 1.3 / 0.5 ms | semantic |

TF loss stops through the qualified geometry path (`command_expired`); every
perception-side fault stops through the semantic leases; zero follows the
freshness trigger in 0.3–2.6 ms everywhere, far inside the 100 ms limit; and
in all ten trials the late success arrived and motion did not resume
(hundreds of disarmed native samples per dwell). The throughput contract is
evaluated over the settled pre-fault window (the leading warmup bursts are
excluded — gaps past the 500 ms lease cannot occur during armed motion
without stopping the supervisor): 6.9 results/s, p95 capture age ~218 ms.

**Retained engineering evidence.** Twelve series were run to this pass and
every failure is retained under `phase-5/semantic-fault-*` with root causes
fixed in commits `55188ac…e284fa5`: the in-pod suite wrapper's frozen 280 s
fixture budget cannot contain a 300 s post-restart readiness window; the
auto-restarted inference process is not a sufficient readiness signal (its
status publishes before the model loads); a **zenoh client session never
re-dials a lost router** (matrices 8–9, with `connect.timeout_ms -1` and a
verified router rollout — the reason transport_loss deletes the pod rather
than the router); a wrapper-run bridge never delivered camera data to the
process while announcements, routes and the reverse data direction all
worked (matrix 10 — the wrapper is reverted); and the late-success dwell
must pump at full cadence because the native clock fails closed at a 100 ms
processing-time capture age (matrix 12 latched at 104.5 ms on a capture that
was 52 ms old at callback). Operationally relevant for Phase 6: the
perception topology recovers from backend loss by pod recreation, not by
in-place process restart alone.

**Armed semantic fault matrix: PASS.** This closes the fourth and final
Phase 5 moving gate. **All four moving gates pass on the identical frozen
guarded GPU profile.**

### Phase 5 evidence review and sign-off (October 26, 2026)

The user reviewed the four passing gates and accepted the Phase 5 evidence,
authorizing closure of the Phase 5 acceptance gate and unlocking Phase 6.
The acceptance carries these recorded caveats:

1. **Footprint geometry**: the qualified profile uses the corrected support
   geometry with rear casters and the padded hull; the measured discrepancy
   and correction are retained above.
2. **Private-profile deviations**: the watchdog's UDP companion path, the
   domain isolation (85/86/88), the matrix runner's pod recycles and the
   transport-loss pod-deletion design are private-fixture mechanics, not
   canonical deployment changes; nothing here changes the canonical hotel.
3. **Operational findings for Phase 6**: a zenoh client session never
   re-dials a lost router — perception-backend loss is repaired by pod
   recreation, not in-place process restart alone; the SAM3 result stream
   has a reproducible pre-arming burst phase, so arming requires a
   sustained fresh-result streak.
4. **Single-floor scope**; the **Phase 2 recognition waiver** stands —
   nothing in Phase 5 qualifies recognition accuracy.
5. Twelve failed matrix series are retained as evidence; every failure was
   root-caused and fixed, with no retries anywhere in the passing series.

**Phase 5: ACCEPTED.** Phase 6 semantic steering may proceed under its own
gates; the Phase 6D demo track remains separately scoped.

### Third series attempt: the Wait-transition authority race resurfaces narrowed

The fresh ten-trial series (`recovery-series-gpu-3`) passed trial 1 and
stopped on trial 2 — the same Wait-handoff authority race as the first
isolated-node pilot, resurfacing in a narrower form that the earlier fix
did not close. Anatomy: the decel tail's last admitted command (−0.002
m/s) carried a capture bound **88 ms into its 100 ms source lifetime**
(the Wait-transition stamp lag, measured at 70–84 ms on the decel tail in
passing and failing trials alike), leaving its lease only 10.5 ms of
authority. The wait-hold fast path fired correctly — 7 ms after the
native applied the settling tail, versus 9 ms on the slower observer path
that lost the first pilot by 0.2 ms — and issued fresh 80 ms leases, but
the refresh needed to arrive within 0.8–2.8 ms of the watchdog's
margin-adjusted expiry and lost by 1–4 ms of native-link delivery
latency. The watchdog correctly stopped `lease_expired`; the coordinator
recorded `native_session_lost`; the robot applied zero immediately.

The three Wait-transition failures (first pilot, GPU-2's interval
contract, this trial) are manifestations of one structure: the Nav2
command pipeline's stamp lag (31 ms typical, 70–90 ms during the Wait
transition) compresses the final settling command's authority to
~10–20 ms, and every coordinator confirmation path (native-status
round-trip ~7 ms plus delivery 0.6–4 ms) must fit inside the remainder.
Coordinator-side latencies have been narrowed twice; the exposure cannot
be eliminated while the stamp lag persists. The next investigation
target is the lag's source — the /clock-to-physics offset degrading
during the Wait transition, in the sensor bridge's clock publication or
its receipt by the smoother/Collision Monitor chain. *(Superseded: the
[stamp-lag diagnosis above](#wait-transition-stamp-lag-diagnosis-the-smoothers-terminal-ramp-not-clock)
refuted the /clock hypothesis from this same retained evidence — the lag
is the smoother's terminal decel ramp reusing the terminal command's
stamp — and the renewal/confirmation split removed the confirmation
round trip from the critical path.)* An earlier attempt
(`recovery-series-gpu-2`, 3/3 passing trials) was aborted by a local
tooling timeout mid-trial-4 and is retained as infrastructure-interrupted,
not a trial failure. **Recovery repeatability remains HOLD.**

### Guard alignment

`run_phase5_native.py --require-non-gpu-node` previously required
`--moving-timing-trace`, contradicting the committed series runner that
propagates the flag to all ten recovery trials. The guard now requires a
pinned node for any trial and still refuses `--allow-g5-node`; the fail-closed
Ready/GPU-free check before resource creation is unchanged. This widens
enforcement to more trials. Launcher tests were updated and all 31 pass.


## October 22 non-actuating preflight: PASS; motion gates unchanged

The post-commit, pinned Phase 5 preflight completed successfully in the
`semantic-navigation` project using
`semantic-costmap@sha256:447c6ee36d2eff0707a69133881c4131e0033dab5c38099750844173d416c92f`.
It ran 169 semantic-safety unit tests, the static geometry audit, the native
Collision Monitor/smoother fixture, and the owned-action lifecycle fixture.
All passed; the image contained the expected Jazzy Nav2 Collision Monitor,
controller, and velocity-smoother packages. The temporary Pod and ConfigMap
were deleted successfully. Evidence is in
[`preflight-20261022`](preflight-20261022/).

This is a non-actuating software/profile preflight only. The geometry audit
again reports that a 0.22 m canonical circular radius does not enclose the
0.23154 m corner radius of the pinned chassis bounds; the Phase 5 candidate
uses the explicit padded rectangular footprint, but moving clearance remains
unqualified. The test uses synthetic inputs, not a moving hotel robot. It does
not close recovery-enabled task repeatability, physical fault-stop coverage,
moving SAM3/load qualification, or the armed semantic fault matrix. **Overall
Phase 5 remains HOLD.**

### Moving-trace placement review: held before launch

A follow-up placement check found the Phase 6D candidate still running in its
isolated project. The simulator is on `ip-10-0-38-113`, Nav2 on
`ip-10-0-39-214`, and SAM3 on `ip-10-0-18-251`; the simulator node's sampled
CPU use was about 11.9 cores. The prior Phase 5 timing fixture ran on
`ip-10-0-53-174`, which also hosts a persistent hotel simulator and showed
about 12.9 cores at the latest metrics sample. Reusing either placement would
confound the intended CPU-isolation comparison.

The lowest-current-CPU candidate observed was a G5-tainted node, but the Phase 5
runner deliberately permits that taint only for pinned, **disarmed** timing
diagnostics. A guarded moving trace is rejected by that policy. Other low-sample
CPU workers are either running Nav2/camera or RMF workloads, host the persistent
hotel simulator, or are heavily allocated to shared services. I did not weaken
the G5 policy or launch the moving fixture. This is a placement/coordination
hold, not a new navigation result. To continue the controlled moving test,
reserve a non-GPU worker and low-load window, or review a narrowly scoped
moving-fixture placement exception with explicit resource limits and GPU
workload coordination; do not bypass the current launcher guard.

### October 22 non-GPU window follow-up: postponed

After the user selected the non-GPU route, a read-only cluster check sampled
candidate workers five times over one minute. The least-loaded worker was
`ip-10-0-15-146` (`m6i.4xlarge`, no GPU resource or taint), at 3–6% observed CPU
and 44% memory. It is not reserved: `oc describe node` showed 74 non-terminated
pods, CPU requests of 12.384/15.5 allocatable cores (79%), and CPU limits at
176%. The guarded fixture requests 2 CPUs and can use up to 8, so placing it
there could contend with shared workloads. Other low-CPU candidates were also
committed; `ip-10-0-22-57` hosts active RMF workloads, while
`ip-10-0-53-182` hosts the semantic camera probe and hotel-test Nav2.

The user chose to postpone the moving trace rather than run it on shared
capacity. No Phase 5 Pod or ConfigMap was created, and no worker or deployment
was changed. The native runner has an opt-in `--require-non-gpu-node` preflight
for a future pinned moving trial; it rejects a non-Ready or GPU-capable target
before creating test resources. The fixed recovery-series runner now requires
both `--node-name` and `--require-non-gpu-node`, propagating them to all ten
trials so each is pinned to and rechecks the same non-GPU worker. These checks
enforce placement only; they do not reserve CPU capacity or qualify navigation.
**Phase 5 remains HOLD.**

## October 17 implementation: real hotel coordinator connected

### Callback scheduling correction (latest follow-up)

The fixed-series-1 failure below led to an isolated callback-scheduling change,
not a deadline increase. The C++ command observer, native actuator/watchdog,
source provenance checks, 20 ms capture join, 100 ms source lifetime, 80 ms
maximum native lease, receiver uncertainty and 500 ms sensor/TF limit are unchanged.

The Python fixture now keeps command ingress, sensor/TF observation and task
results on separate persistent single-thread executors, polled on **one thread**.
[The bounded pump](../../../../apps/semantic-safety/priority_pump.py) services
four command polls and four observer polls per round, ingests native captures
between observer callbacks, then services task results and the guard before
diagnostic joins. A nonblocking executor poll is not guaranteed to execute a
callback, including at the end of a previous ready-set iteration. There is no
background adapter thread, unbounded queue drain, latest-command substitution or
receipt-time renewal. Audit subscription depth remains 100; raw and checked
provenance is retained. Already-qualified scan transforms are not queried again
to renew evidence. New scans still require the exact capture-time transform.

Audit rows additionally record the audit String's DDS source/receive metadata,
separately from the original Twist timestamps. These are hop diagnostics, not
capture authority or proof of network-only delay. Per-scan TF diagnostics retain
availability, qualification, first lookup error and buffer-head stamps; latest
TF is inspected only for diagnosis, never substituted for capture-time TF.

Intermediate outcomes (all retained, not counted as baseline successes):

- [Hotel 46](hotel-contact-46-20261017/runtime/summary.json) stopped **before
  arming** because installed rclpy supplies message metadata as a dictionary.
  The callback was corrected and a regression test added.
- [Hotel 47](hotel-contact-47-20261017/runtime/summary.json), four ingress polls
  but one observer poll per round: command observer-to-callback latency improved
  to **0.486/3.215/4.372 ms** median/p95/max (134 checked observations), compared
  with 5.73/22.14/44.53 ms in failed series 1. However, the task stopped on
  **TF freshness**, so this was not a navigation pass.
- [Hotel 48](hotel-contact-48-20261017/runtime/guard-tf.json) added TF diagnostics
  and duplicate-lookup suppression. It reproduced TF expiry: at scan capture
  10.6 s the observer's odometry transform head was only 10.428 s; successive
  latest-scan candidates were replaced before their exact transforms caught up.
  This establishes observer-side TF lag, not loss of the frame publisher.
- [Hotel 49](hotel-contact-49-20261017/runtime/summary.json) used persistent
  executors and four observer polls but only one ingress poll. TF caught up,
  but command delivery again backed up: **8.032/29.759/39.771 ms** median/p95/max
  and admission age up to **82.554 ms**. Native lease expiry stopped the run;
  observed native trigger-to-applied-zero was **0.612 ms**. Contact checks passed.
  This motivated bounded batches for **both** ingress and observer executors.
- [Hotel 50](hotel-contact-50-20261017/runtime/summary.json), four polls for each
  executor with the persistent executors: **20/20 checks passed**. The robot
  completed the one-metre target (0.797 m physical displacement), with no unexpected
  contact over 141 samples / 3,200 covered steps. Command observer-to-callback
  latency was **0.820/3.612/8.043 ms** median/p95/max across 623 checked commands;
  admitted capture age was **35.137/47.811/56.355 ms**. Normal-completion revocation
  reached applied zero in **2.238 ms**, with 0.938 mm sampled displacement to
  confirmed quiet after 501 ms including dwell. This qualifies a pilot, not
  repeatability or the fault matrix.

The revised source passes **124 local safety tests and ten profile/tree tests**.
Installed adapter checks additionally cover unchanged capture stamps, no repeated
TF renewal, and no latest-TF fallback. These deterministic tests do not constitute
moving baseline acceptance. The passing pilot is followed by a new frozen
ten-trial series, not an unrecorded repeat of series 1. **Phase 5 remains HOLD.**

#### Fixed series 2: 10/10 baseline repeatability subgate passed

[Frozen plan](baseline-series-2-20261017/plan.json) and
[series result](baseline-series-2-20261017/summary.json): **10 planned, 10 attempted,
10 successful**, in order, with no retry or runtime-input changes. Every trial
passed all **20 integration checks**, including goal success, terminal descendants,
native stop metrics and exact-allowlist contact coverage. This supersedes the
older unresolved baseline-repeatability status below; failed series 1 is retained.

The image remains build 4, with private rear casters, 2 ms physics, 12 m virtual
lidar, 200 Hz native odometry, 10 Hz lidar updates, 40 Hz controller and 100 Hz
smoother. Python runtime inputs are pinned by the series source hashes; native
watchdog and observer binaries were not rebuilt for this scheduling correction.

| Measurement | Ten-trial result |
|---|---|
| Goal/contact/stop checks | 10/10 trials, 20/20 checks each |
| C++ observation → Python callback | 0.943 / 3.673 / 8.103 ms median/p95/max; 7,103 checked observations |
| Conservative capture bound → admission | 33.979 / 47.108 / 57.555 ms median/p95/max; 7,098 admitted checked observations |
| Normal goal revocation → applied zero | 2.579–5.963 ms |
| Revocation → confirmed physical quiet | 254.6–550.6 ms, including 250 ms quiet dwell |
| Sampled translational distance from the pre-revocation sample to confirmed quiet | 0–0.936 mm |
| Actual start-to-end physical displacement | 0.748–0.799 m for the one-metre **target** |
| Unexpected contact pairs | None in any covered baseline window |

These are successful **localized Nav2 goals**, not proof of exactly one metre
of physical travel or a ground-truth endpoint-accuracy qualification. The existing
0.2 m goal tolerance was unchanged. Trials 3 and 8 had shorter physical displacement
and no measurable translation after revocation; zero sampled translation is **not**+a claim of zero braking distance. Normal completion often decelerates before the
parent result, so these results cannot replace stopping tests triggered during motion.
Percentiles above pool commands across all trials; they are observations, not
hard real-time latency guarantees.

All ten runs passed 124 pure safety tests, six installed frame tests, nine
installed adapter tests and fifteen native lease tests before their moving fixture.
All ten cleanup records confirm removal of their private pod/ConfigMap, with
evidence retained. The final private-resource check is empty; canonical hotel,
camera and Zenoh deployments remain 1/1 and unchanged. No commit/push was performed.

**Remaining Phase 5 work:** recovery/Wait/backup routing and cancellation
qualification, physical fault-triggered stopping coverage, moving SAM3 registration
and compute-load validation, and the armed semantic-input/remote-style fault matrix
with semantic costs still excluded. Passing this straight, no-recovery baseline
subgate does **not** authorize Phase 6 or mark the overall Phase 5 gate passed.

### Support-geometry correction and range investigation (follow-up)

The following supersedes the unresolved settling diagnosis below; Phase 5 remains
HOLD until the moving qualifications pass. Canonical assets/deployments are unchanged.

- [Hotel 38](hotel-contact-38-20261017/runtime/contacts.json), original robot:
  the added world-pose/contact-point diagnostics confirm backward tipping. At the
  final sample pitch was **−2.8795°**; contact points were on both rear chassis
  corners at floor z≈0, with upward normals. This is physical support contact,
  not a collision-name misclassification. The pre-arm gate failed as intended.
- [Hotel 39](hotel-contact-39-20261017/runtime/summary.json), rear casters but
  original 10 ms step: **failed**. All six components existed, but the caster/floor
  pairs never appeared; chassis contact persisted. This failed candidate is retained.
- [Positive control 3](contact-positive-3-20261017/runtime/summary.json): the
  same caster geometry at 1 ms on the small plane fixture registered both caster
  contact pairs and the deliberately introduced chassis/obstacle pair. The drive
  stayed disarmed. This separated a hotel contact-resolution problem from an
  absent caster component or an entirely unsupported ball joint.
- [Hotel 40](hotel-contact-40-20261017/runtime/summary.json), casters plus 1 ms:
  contact evidence shows both wheels and both casters supporting the robot with
  **no chassis contact recorded**, pitch ≈−0.00290°, and base height ≈10.006 mm.
  The overall run still **failed** its sensor precondition: the level 3.5 m lidar
  had 360 positive-infinity readings, not NaNs. The nearest occupied cell in the
  installed map is approximately **8.48 m** from the starting pose, so a finite
  wall return within 3.5 m cannot be assumed. No moving task was permitted.
- [Hotel 41](hotel-contact-41-20261017/runtime/summary.json), casters, 1 ms and
  a private **12 m virtual lidar**: **16/16 disarmed integration checks passed**.
  There were 277 finite beams out of 360, complete six-collision monitoring, only
  allowlisted wheel/caster support contacts, unchanged sensor extrinsics, successful
  planning and real Nav2 command-chain checks without actuator permission.

[Private geometry correction](../../../../apps/semantic-safety/support_geometry.py)
adds two 5 mm-radius balls at x=−0.140 m, y=±0.064 m, z=−0.005 m, with ball joints,
1 g mass each and nonzero friction. All original collisions, inertias, wheel
geometry/friction and sensor mounts remain; the support spheres fit inside the
existing hull. The URDF adds fixed sphere-centre transforms for rendering; actual
ball-joint dynamics are SDF-only. This follows the rear-ball-support arrangement
in the [upstream Waffle model](https://github.com/ROBOTIS-GIT/turtlebot3_simulations/blob/main/turtlebot3_gazebo/models/turtlebot3_waffle/model.sdf),
with locations adapted to this demo's smaller chassis—not a hardware-accurate
replacement model. No chassis contact or arbitrary floor contact is exempted.

The controlled 10 ms versus 1 ms hotel comparison establishes that timestep
resolution matters for this small support geometry. Startup tunnelling is a
plausible mechanism, but the exact solver failure was not established. The fix
uses finer simulation resolution rather than disabling collision/friction or
changing native command deadlines. Its moving runtime cost still needs qualification.
The 12 m range matches the existing Nav2 candidate's configured maximum, but it
**changes the virtual sensor specification**; it is not a physical TurtleBot lidar
capability claim. The finite-return readiness check was not removed. Run 33's
unretained rejected payload remains unexplained; these findings do not retroactively
convert earlier integration trials into qualified baseline evidence.

Observer build 4 is pinned to
`sha256:700eb9424e301d571c80c31d31c97e9945f783afdc840f501ddb222440ec623e`.
It adds body/collision poses, contact points, normals and depths; actuator code is
unchanged. The geometry, timestep and virtual range remain explicit opt-in runner
arguments (`--rear-casters --physics-step .001 --lidar-range 12`). The baseline
series records these choices alongside frozen source hashes. Local checks pass
**121 safety tests and ten profile/tree tests** after the range-contract and
odometry-rate follow-ups below. Disarmed contact evidence alone does not pass Phase 5.

#### Guarded moving pilot and latency follow-up

| Run | Outcome |
|---|---|
| [42](hotel-contact-42-20261017/runtime/summary.json) | Failed before arm: adapter still expected the original 3.5 m sensor. The explicit selected range now configures the validator; a mismatched 3.5/12 m payload is rejected in either direction. No freshness or malformed-scan guard was relaxed. |
| [43](hotel-contact-43-20261017/runtime/summary.json) | At 1 ms physics, contact checks passed but command expiry stopped the trial soon after arming. Simulation was roughly half real time; checked-command latency consumed the source deadline. |
| [44](hotel-contact-44-20261017/runtime/summary.json) | At 2 ms physics, support and moving contact windows passed, with 0.784 m physical displacement, but native lease expiry stopped the goal. The run remains failed. |
| [45](hotel-contact-45-20261017/runtime/summary.json) | At 2 ms, with native odometry increased from 50 to 200 Hz, **20/20 checks passed**: successful goal, terminal descendants, contact window and native stop metrics. |

Run 44 isolates an actual **lease expiry**, not a physics-heartbeat failure.
The final new lease was enqueued only 0.294 ms before native expiry, insufficient
transport margin; it did not resurrect the expired session. Native expiry reached
wheel zero in **0.173 ms**. A separate offline calculation anchored to that native
trigger gives 0.965 mm sampled displacement to confirmed physical quiet, confirmed
after 573 ms including the 250 ms quiet dwell. This is one observed expiry, not a
completed fault matrix. Its original normal-completion metric remains failed:
native zero preceded coordinator revocation, so that metric could not locate a
new zero application after the later coordinator trigger. The trace is preserved,
not rewritten to pass.

The [pinned collision-monitor source](https://github.com/ros-navigation/navigation2/blob/1.3.13/nav2_collision_monitor/src/source.cpp)
requests a transform at current time when base-shift correction is enabled.
Increasing native odometry publication supplies those transforms more frequently;
the bridge still preserves capture stamps, and base-shift correction remains on.
This is a targeted latency mitigation, not proof that TF waiting is the sole
cause of every scheduling delay. Observed admitted checked-command age
(capture-bound to admission) improved from **45.26/60.41/69.94 ms** median/p95/max
in run 44 to **35.93/48.40/55.43 ms** in run 45. The native command lease,
source deadline, receiver uncertainty and sensor-freshness limits are unchanged.

Run 45 completed the one-metre **target** with 0.795 m actual displacement,
consistent with the goal tolerance; maximum applied forward command was 0.15 m/s.
Normal-completion revoke-to-wheel-zero was **0.672 ms**, and physical quiet was
confirmed after 356 ms including dwell. Contact coverage contained 138 samples
and 3,185 physics steps with no unexpected pair. Chassis/lidar contacts are still
excluded from allowed support. The final-image
[positive control 4](contact-positive-4-20261017/runtime/summary.json) also passed
with the six-collision robot, detecting the deliberately introduced obstacle.

The qualified **pilot candidate**, not a full Phase 5 pass, is:
`--rear-casters --physics-step .002 --lidar-range 12 --odom-frequency 200` with
the build-4 digest above, guarded 10 Hz lidar and unchanged 40/100 Hz controller/
smoother rates. The ten-trial runner freezes these inputs and stops on first
failure; its results are separate from the diagnostic pilots. Both later semantic
and baseline arms must use identical qualified geometry/sensor parameters.

#### Fixed series 1: failed on trial 1; repeatability still blocked

[Frozen plan](baseline-series-1-20261017/plan.json) and
[series result](baseline-series-1-20261017/summary.json): **10 planned, 1 attempted,
0 successful; the other 9 were not attempted.** The runner stopped on the first
failure without retries or changing inputs. The diagnostic pilot's success is not
counted as a series success.

[Trial 1](baseline-series-1-20261017/trial-01/runtime/summary.json) again passed
the support and moving contact checks, with no unexpected pairs over the covered
window (136 samples / 3,100 physics steps), but native lease expiry canceled the
goal after approximately 0.778 m physical displacement. The native trace reports
**2.172 ms** from expiry to wheel-zero application; parent/descendants terminated.
The trial and its normal-completion metric remain failed.

The [command trace](baseline-series-1-20261017/trial-01/runtime/guard-commands.json)
localizes an additional late-stage delay. Checked-command publication to the C++
observer was **0.082/0.160/0.826 ms** median/p95/max; C++ observation to Python
adapter callback was **5.73/22.14/44.53 ms**. The last checked command was already
observed around 44.1 ms before its adapter callback. The newest lease was then
enqueued after the previous lease's receiver-adjusted deadline, and could not
revive the stopped session. Admitted command age reached 84.85 ms.

Thus, higher odometry frequency improved the pilot but did **not** establish
repeatability. The demonstrated unresolved boundary is the C++ audit-observer →
Python adapter path, including audit publication/DDS buffering and executor
dispatch; these timestamps do not isolate which subcomponent accounts for all
44.5 ms. Next: instrument audit-publish completion and middleware receive time,
separate control ingress from high-rate clock/sensor/diagnostic callbacks, and
requalify bounded/latest-only delivery without dropping provenance checks,
restamping commands, extending deadlines or permitting automatic restart.
Then rerun the pilot and a new explicitly recorded fixed series. Do not repeat
the same series until a lucky pass or treat the native fail-safe stop as task success.

The [final fixture cleanup](baseline-series-1-20261017/trial-01/cleanup.json)
confirms deletion of its private pod and ConfigMap. Canonical hotel, camera and
Zenoh deployments remain 1/1 and unchanged. Build artifacts/evidence were retained;
no source commit or push was performed. **Phase 5 remains HOLD**: repeatable
baseline, recovery qualification, moving SAM3 registration and the semantic fault
matrix are still outstanding.

### Contact instrumentation follow-up: baseline blocked before arm

Implemented a read-only native [contact observer](../../../../apps/semantic-safety/native/contact_audit.cpp),
[contact assessment](../../../../apps/semantic-safety/contact_evidence.py),
[physical stop metrics](../../../../apps/semantic-safety/baseline_metrics.py), and
a [fixed ten-trial runner](../../../../scripts/semantic-navigation/run_phase5_baseline.py).
The series freezes runtime inputs, uses fresh private worlds, requires successful
goals plus contact/stop evidence, and stops at the first failure without automatic
retries. **The ten-trial series has not been started.**

The observer requests contact data for all four robot collision components and
counts each collision pair on every unpaused physics step. Cumulative counts are
published outside the physics thread, so a brief contact is not erased between
messages. Assessment requires a bracketed observation window, unchanged monitored
components, monotonic counters and no simulation/source-wall sample gaps over
200 ms. This is an evidence-coverage limit, **not** a relaxation of the native
80 ms command lease or existing stop/freshness limits. Contact assessment is
offline evidence with a disarmed pre-arm check, not a new certified protective
controller. The existing collision monitor and actuator watchdog remain in place.

The observer-only image is pinned to
`sha256:2af9a55872adcb1aa52db55b36a65b3aa67f5c8a5c817dcd94e22900faeda9dc`
in the namespace's `semantic-safety` repository. It derives from build 10;
[installed hashes](hotel-contact-36-20261017/installed-pins.txt) confirm that the
drive watchdog, smoother and command observer executables are unchanged.

| Evidence | Outcome |
|---|---|
| [Positive control 1](contact-positive-1-20261017/test.log) | Failed before qualification because Gazebo's default log path was unwritable. The fixture now uses the existing writable `/tmp` record path. Retained as failed evidence. |
| [Positive control 2](contact-positive-2-20261017/runtime/summary.json) | Passed: deliberately introduced base/obstacle contact detected with all four components present and drive disarmed/applied zero. Physical displacement caused by contact is not ruled out; this is not a stationary or navigation qualification. |
| [Disarmed hotel 36](hotel-contact-36-20261017/runtime/summary.json) | Instrumentation/integration checks passed, but retained contacts exposed persistent chassis/floor contact. Its historical overall PASS does not qualify collision-free navigation. |
| [Guarded hotel 37](hotel-contact-37-20261017/runtime/summary.json) | New support-geometry gate failed before Nav2 startup/arm on `sim_world::hotel_L1::floor_3::collision` ↔ `sim_world::robot_1::base_link::base_collision`. All 2,808 native records remained disarmed with zero applied commands. |

The exact support whitelist permits only the two wheel collisions against this
specific floor collision; it excludes chassis, lidar, other floors, walls and
objects. It was not widened after the failure. Hotel 37 recorded chassis/floor
contact in 1,156 of 1,170 observed physics steps, not a one-off startup event.
The retained [robot world](hotel-contact-37-20261017/runtime/assets/hotel.world)
has no caster: chassis-box bottom is at model z=0, while wheel bottoms are nominally
z=-0.010 m. The [floor mesh](hotel-contact-37-20261017/runtime/hotel-floor-3.obj)
has 58 vertices spanning z=-0.1 to 0; the corresponding model collision is the
floor mesh, separate from wall meshes. **Confirmed blocker:** the current model
has persistent chassis/floor contact. Missing support geometry and settling/pitch
are plausible causes, but contact counts alone do not establish the full dynamics
or identify the contact point/depth. No claim is made that this explains scan
rejection in hotel 33.

Next: retain contact position/normal/depth and full model roll/pitch during a
disarmed settling probe; correct/validate support geometry in the private test
asset, requalify the observer's monitored collision inventory and frame/footprint
assumptions, then run the guarded pilot before freezing the ten-trial series.
Do not remove chassis collision, disable friction/contact, or exempt all floor
contacts merely to pass. Any qualified geometry must subsequently be identical
in baseline and semantic arms; canonical assets remain unchanged for now.

The stop-metric implementation requires applied-zero within 100 ms of revocation,
physical sample gaps ≤50 ms, and 250 ms sustained physical quiet. Offline evaluation
of the previously retained hotel 35 trace passes: 6.16 ms revoke-to-applied-zero,
257.75 ms to confirmed quiet, and 0.789 m total displacement. This normal-completion
check is not a moving fault-stop measurement and adds no contact qualification to
hotel 35. The newly wired moving contact/stop checks have not yet run end-to-end,
because hotel 37 correctly stopped at the geometry precondition.

Local tests now pass **115 safety tests and ten profile/tree tests**; hotel 37
executed 114 safety tests, six frame callbacks, six adapter callbacks and 15 native
tests before the intentional fail-closed runtime gate. The later local change adds
source-wall contact-coverage validation and malformed-evidence rejection.
[Cleanup](hotel-contact-37-20261017/cleanup.json) confirms removal of the private
pod and ConfigMap. Canonical hotel/camera/Zenoh deployments remain 1/1; no canonical
deployment was modified. No commit or push was performed. **Phase 5 remains HOLD**;
recovery qualification, moving SAM3 registration and the armed fault matrix remain
outstanding in addition to the blocked baseline series.

### Earlier coordinator implementation and evidence

Implemented the revised RCA corrections in the isolated fixture, not in the
canonical hotel deployment:

- [Coordinator](../../../../apps/semantic-safety/guarded_coordinator.py): cold
  start uses independently captured native applied-zero and 250 ms physical
  stationary evidence, fresh inputs, idle tasks and a new command-session barrier.
  It no longer waits for an unsolicited idle Nav2 zero command. Preparation stays
  zero-only and bounded to five seconds. Registry checks now precede dispatch,
  command admission and lease enqueue. Collision-monitor STOP latches revocation;
  clearing the monitor does not resume. Accepted checked commands enqueue leases
  immediately; the watchdog tick remains, with unchanged source/80 ms lease caps.
- [Hotel adapter](../../../../apps/semantic-safety/hotel_guard_adapter.py): real
  clock/scan/odometry evidence and scan-capture TF, conservative native capture
  mapping, pre-admission publisher GUID/frame validation and bounded joins are
  connected to the native actuator. Native callbacks are drained between ROS
  callbacks, preventing an already received clock bracket from waiting behind
  an entire callback batch. Transport/client discovery precedes capture binding.
- [Registry](../../../../apps/semantic-safety/hotel_task_registry.py): checks the
  exact ten private action endpoints, allowed client roles, frozen client graph
  and publisher identities. Legitimate planner/follower child UUIDs differ from
  the owned parent. Cancel-all sweeps cover every private server after synchronous
  permission revocation; cancellation ACK alone never clears an active goal.
  Missing terminal evidence or graph changes inhibit rearm. This is a lifecycle
  fence for a freshly launched, controlled graph—not authenticated caller/parent
  lineage. Status messages are event-driven, not heartbeats. SROS2 is not made
  mandatory for this loopback/private simulation test; exposed deployments need
  a separate security/ownership design.
- [Explicit baseline tree](../../../../apps/semantic-safety/phase5-baseline.xml)
  contains only planning and following. Recovery servers remain inventoried but
  cannot be activated by this tree; unexpected recovery activity revokes permission.
  Recovery qualification is **not** claimed. Candidate controller/behavior/smoother
  rates are now 40/40/100 Hz; guarded tests use 10 Hz lidar. Goal tolerances remain
  unchanged. RPP `stateful: false` lets positional arrival be reconsidered after
  localization corrections. The BT cancel wait is 2,000 ms, independent of—and
  subsequent to—the immediate drive-permission revoke.

### Executed evidence and limitations

| Run | Result |
|---|---|
| [29](hotel-29-20261017/runtime/summary.json) | Failed closed before arm: capture-clock binding preceded transport/client startup. Discovery was moved before binding; no moving deadline was extended. |
| [30](hotel-30-20261017/runtime/summary.json) | Drove approximately 0.77 m, then native lease expiry latched. Parent and child actions canceled. Raw captures lost their bounded join while native samples waited behind ROS callbacks. |
| [31](hotel-31-20261017/runtime/summary.json) | Callback interleaving sustained the guarded path for 20 seconds without a lease/freshness trip, but goal completion timed out in near-goal rotate-only behavior. Not a baseline pass. |
| [32](hotel-32-20261017/runtime/summary.json) | **16/16 integration checks passed**, including successful Nav2 goal, terminal child actions and native stationary confirmation. |
| [33](hotel-33-20261017/runtime/summary.json) | Scan payload rejection latched a stop; parent/children canceled. The exact rejected scan was not retained in this attempt, so its payload-level cause is not established. It remains a failed trial. |
| [34](hotel-34-20261017/runtime/summary.json) | **16/16 integration checks passed** with the stricter endpoint/client allowlist and installed adapter callback tests. Rejected-scan diagnostics are now retained. |
| [35](hotel-35-20261017/runtime/summary.json) | **16/16 integration checks passed** on the final implementation, including the no-return scan contract and invalid-input readiness block. No rejected scan or registry fault occurred. |

Run 32's one-meter **target** completed in 10.07 seconds; measured physical
displacement was 0.790 m, consistent with goal-checker tolerance plus localization
error, not a claim of one meter of travel. Maximum applied forward command was
0.15 m/s. Goal-completion revocation reached native wheel zero in **1.84 ms**.
This is a normal completion observation, not the fault-matrix stopping bound.
No contact-based collision-free qualification is inferred from these traces.

The RPP change addresses its independent, latched positional-arrival state;
the default can remain rotate-only after the estimated position changes.
Run 31 versus 32 supports this diagnosis, but is not an exhaustive localization
proof. [Pinned RPP implementation](https://github.com/ros-navigation/navigation2/blob/1.3.13/nav2_regulated_pure_pursuit_controller/src/regulated_pure_pursuit_controller.cpp).
The cancellation wait comes from the pinned BT implementation, not a change to
command freshness. [Pinned BT action server](https://github.com/ros-navigation/navigation2/blob/1.3.13/nav2_behavior_tree/include/nav2_behavior_tree/bt_action_server_impl.hpp).

Sensor validation now distinguishes complete scans containing positive infinity
(valid no-return readings) from NaN errors and negative-infinity too-close
readings, which remain fail-closed. Freshness, frame and geometry checks still
apply. This corrects a validator contract independently; it does **not** establish
that run 33 was an all-infinity scan. [ROS REP-117](https://github.com/ros-infrastructure/rep/blob/master/rep-0117.rst).

Local checks: **106 safety tests and 10 profile/tree tests**. Runs 34–35 additionally
executed **six frame callbacks, six hotel-adapter callbacks and 15 native lease
tests**. Every run retains source hashes, effective parameters, traces and cleanup.
The existing pinned build-10 native binaries are unchanged; Python/XML are mounted
read-only with hashes. All earlier sections below retain historical evidence.

[Combined regression 14](combined-14-20261017/runtime/summary.json) passed all
**11 checks**, including six fault cases with the updated immediate sender.
Injected collision-state STOP reached native wheel zero **1.90 ms** after
coordinator revocation (**2.50 ms** after message injection), stayed stopped after
the clear-state message, and required terminal task completion before rearm.
Suspending both supervisor processing paths reached zero in **58.72 ms**;
killing the transport worker reached zero in **57.13 ms**. These use private
physics with controlled command/sensor evidence and a fake action backend—not
a physical obstacle test in the hotel. The preceding
[regression 13](combined-13-20261017/runtime/summary.json) remains failed:
its old stall injection disabled only periodic tick delivery, leaving the new
immediate callback path running. The fixture now suspends ingress and periodic
processing while independently observing native expiry; no production stop
deadline was changed to pass the test.

**Still required:** repeated/contact-instrumented 10/10 baseline goals, diagnosis
of any repeated scan rejection, enabled recovery/Wait/backup-speed qualification,
physical fault-stop measurements, moving SAM3 projection and the armed semantic
fault matrix. Neither these three goal completions nor isolated callback tests
constitute full Phase 5 acceptance. Semantic costs remain excluded. The final
[hotel cleanup](hotel-35-20261017/cleanup.json) and
[fault-regression cleanup](combined-14-20261017/cleanup.json) confirm the private
pod/ConfigMap were removed. The canonical hotel, camera and Zenoh deployments
remain 1/1 available and were not modified. No commit or push was performed.

## Completed: non-actuating preflight

- Added a [shared single-floor candidate](../../../../helm/semantic-navigation/phase5-nav2-candidate.yaml)
  and [reproducible renderer](../../../../scripts/semantic-navigation/render_phase5_params.py).
  Both maps use the same explicit rectangular hull plus 1 cm padding, enabled
  geometric/inflation layers, and **no semantic plugin**. Initial forward speed
  is 0.15 m/s, reverse limit 0.10 m/s, and yaw limit 0.5 rad/s. Inflation radius
  is 0.35 m. These are candidate settings, not a stopping-distance qualification.
- The native collision monitor has an enabled stop polygon and enabled
  footprint-approach checking. Its output is `phase5/collision_checked`, **not
  the simulator command topic**. Docking parameters are excluded. AMCL is selected
  as the sole future `map -> odom` authority; the existing fixed-offset TF helper
  must not run alongside it.
- Implemented [ROS-independent guard and receiver state machines](../../../../apps/semantic-safety/safety_core.py).
  They start disarmed, require explicit rearm, retain the first stop reason, reject
  stale/replayed/old-session commands, and cannot resume on a late successful
  inference result. Source capture deadlines are checked *before* callbacks can
  refresh inputs. Reset barriers include the 2 ms clock allowance.
- **30 deterministic state-machine tests pass**, including three additional
  recovery/barrier tests after the first preflight. **Six local profile tests
  pass**, including footprint coverage of the pinned SDF collision geometry and
  equality of checked-in configuration to renderer output.
- Ran the **real installed Jazzy collision-monitor executable** in a separate
  cluster pod using ROS domain 85, loopback-only DDS and no Zenoh/Gazebo bridge.
  Synthetic scans, transforms, footprint and commands verified nominal command
  passage, obstacle intervention, scan timeout, and absence of actuator topics.
  This fixture does not run SAM3, RPP, a simulator, or a physical robot.

The [first cluster preflight](preflight-1-20261016/test.log) passed 27 core tests
and all five native fixture checks. First observed zero after synthetic obstacle
injection was **42.88 ms**, measured with one process's monotonic clock. The
[raw trace](preflight-1-20261016/collision-monitor.json) includes commands,
monitor states and the ROS topic inventory. This is **not** the Phase 5
capture-fault-to-final-actuator latency or physical braking measurement.

The [second preflight](preflight-2-20261016/test.log) passed 29 core tests and
repeated the native fixture (42.80 ms). A subsequent regression test reproduced
a recovery defect: repeatedly rejected pre-fault captures moved the reset
barrier forward, potentially preventing rearm indefinitely with ordinary
inference delay. While already disarmed, these replies are now discarded
without moving the barrier. This does not authorize motion or automatic rearm.
The test failed before the correction and passes afterward.

The final third preflight includes all 30 core tests and the native fixture:
[test log](preflight-3-20261016/test.log),
[native trace](preflight-3-20261016/collision-monitor.json),
[source hashes](preflight-3-20261016/source-hashes.json),
[actual pod specification/status](preflight-3-20261016/pod.json).

Test image: the approved Phase 4 image
`semantic-costmap@sha256:447c6ee36d2eff0707a69133881c4131e0033dab5c38099750844173d416c92f`
in the internal `semantic-navigation` namespace. The executable package is
`ros-jazzy-nav2-collision-monitor 1.3.13-1noble.20260903.031125`.
Source is mounted read-only with hashes; no image tag was changed.

The native monitor resumes when its obstacle clears. That behavior was tested
explicitly and is why a separate latched supervisor is required. Its output
publication also depends on incoming commands, and zero publication eventually
ceases after `stop_pub_timeout`; it is not an independent actuator watchdog.
[Nav2 1.3.13 implementation](https://raw.githubusercontent.com/ros-navigation/navigation2/1.3.13/nav2_collision_monitor/src/collision_monitor_node.cpp).

## Isolated frame and actuator implementation

Implemented [asset preparation](../../../../apps/semantic-safety/prepare_assets.py)
that generates separate corrected world/URDF files; it does not modify the
canonical assets. The base joint is co-located with the SDF base links, lidar
x is −0.032 m, and a separate `lidar_frame` accounts for the additional 0.01 m
sensor offset. Four asset tests reject unknown geometry and duplicate patches.
The [sensor-only frame bridge](../../../../apps/semantic-safety/frame_bridge.py)
preserves source stamps, publishes no map transform or commands, and rejects
duplicates, stale inputs and clock rollback. Six installed-ROS callback tests
pass. These are not yet moving camera-to-map registration tests.

The actual installed map, world and URDF are retained with hashes. The runtime
L1 map is 693 × 845 at 0.05 m/pixel with origin `[0, -42.25, 0]`.
The initial pose `[15.402, -31.594, 0]` and sampled straight segments to x=16.402
and x=18.402 have known-free padded-footprint coverage in the static map.
This identifies candidate baseline locations, not successful Nav2 goals.
See the [map audit](native-5-20261016/runtime/assets/map-audit.json).

Added a [native Gazebo actuator guard](../../../../apps/semantic-safety/native/watchdog.cpp)
with bounded, session-specific 80 ms command leases and a fail-latched stop.
Explicit arming first reserves a session with **zero motion authority**; only a
fresh valid packet enables motion. The two-second nonmoving handshake does not
extend any moving-command lifetime. Cancelled/expired sessions cannot be reused.
The guard checks expiry on the physics thread and writes both wheel commands
after DiffDrive, so loss of a transport-delivered zero cannot preserve stale
wheel authority. Fifteen native lease tests pass in the candidate image.

The physics fixture uses the original robot on a private flat world, no Nav2,
camera, SAM3, RMF, GPU or Zenoh, with loopback transport and its own Gazebo
partition. It tests the actuator foundation only. The full hotel navigation
graph remains disconnected from this path.

### Failed iterations retained, not counted as passes

- [Native 1](native-1-20261016/test.log): simulator startup failed on the default
  unwritable logging directory; the fixture now supplies an explicit writable
  `--record-path` without changing the process home directory.
- Native [2](native-2-20261016/test.log), [3](native-3-20261016/test.log) and
  [4](native-4-20261016/test.log): startup/clamp checks passed, but first-command
  handshaking failed. Added a nonmoving pending state and discarded expired
  pre-arm traffic without renewing its deadline. Transport publication was
  moved outside the control-state mutex so it cannot block physics expiry.
- Native [5](native-5-20261016/test.log) and
  [6](native-6-20261016/test.log): actual motion began, but a publisher stall
  caused a fail-safe lease expiry **before** intended fault injection. Native 6
  instrumentation measured a roughly 97 ms `publish()` call. Native 5's
  reported latency assertion was not a valid injected-fault measurement.
  The fixture now rejects premature stops and the native plugin records the
  first zero wheel write for each trigger, separately from telemetry sampling.
- [Native 7](native-7-20261016/test.log): a blocking world-control service request
  timed out before motion. The Python binding does not release the GIL around
  `RequestRaw`; the harness now uses a persistent subscription-free service
  process and keeps status callbacks in the observer process.
  [Binding source](https://raw.githubusercontent.com/gazebosim/gz-transport/gz-transport13/python/src/transport/_gz_transport_pybind11.cc).

Gazebo transport's service-connection implementation sleeps for 100 ms while
holding its shared mutex; publication also accesses that mutex. This is a
source-supported explanation for the observed startup stalls, not a stack-trace
proof of the precise blocked call. Establishing connections and warming the
stream while stopped passed the first complete fixture; the 80 ms moving lease
is unchanged. A new connection or later transport stall must still stop motion,
not silently extend its authority.
[Gazebo transport source](https://raw.githubusercontent.com/gazebosim/gz-transport/gz-transport13/src/NodeShared.cc).

### Passed: repeated native actuator fixture (limited subgate)

The final candidate passed twice with identical mounted source hashes:
[native 8 summary](native-8-20261016/runtime/summary.json) and
[native 10 summary](native-10-20261016/runtime/summary.json).
Each run passed **34 Python tests, six installed-ROS frame callback tests,
15 native lease tests and eight live physics checks**. The separate six local
Nav2 profile tests also pass. The live checks cover disarmed startup, raw
DiffDrive bypass rejection, producer death, explicit cancellation, simulator
pause, and late-command/session-reuse rejection after each stop.

| Injected fault at 0.1 m/s | Fault request/death → first wheel zero, runs 8 / 10 | Native stop trigger → first wheel zero, runs 8 / 10 |
|---|---|---|
| Command producer killed | 62.724 / 61.621 ms | 0.607 / 0.488 ms after lease expiry |
| Explicit stop | 1.210 / 0.936 ms | 0.880 / 0.633 ms |
| Simulator pause | 2.197 / 1.682 ms | 0 / 0 ms: stop and zero in the same physics update |

Both runs confirmed about 0.1 m/s immediately before fault injection, following
approximately 0.5 s of observed motion. The source-to-expiry lease remains
80 ms maximum, shortened by the 2 ms clock allowance. No automatic resume
occurred after pause/resume or fresh-looking late packets. These same-pod
measurements use a shared host clock; they do not qualify cross-node clock skew.

Independent Gazebo body pose/velocity—not wheel odometry—gave bracketed
post-command-stop travel of **1.08–1.18 mm** for producer death and
**0.777–0.778 mm** for explicit cancellation, with approximately 4.9–5.0 ms
sample brackets. These values start at the last nonzero-command sample, not
the fault injection; they exclude most travel during the remaining command
lease. They are measurements of this flat-world simulation at 0.1 m/s, **not
real-robot braking limits or a safety-envelope certification**. The pause case
does not qualify braking because physics is frozen. Moving real-time factor
was 0.981–1.0002; neither pod recorded CPU throttling.

Candidate image:
`semantic-safety@sha256:48fd677170651c34371c344e908db60140ff5275287e90b5a7b14fd9b7d0f098`.
Only the isolated `semantic-safety:phase5` build output was updated. Build 6
contains the native library; read-only mounted Python fixture/bridge source is
separately pinned in each run. The retained
[build log](native-10-20261016/build.log),
[installed library/source hashes](native-10-20261016/installed-pins.txt),
[mounted source hashes](native-10-20261016/source-hashes.json),
[raw trace](native-10-20261016/runtime/trace.jsonl),
[pod specification](native-10-20261016/pod.json) and
[CPU counters](native-10-20261016/cpu-cgroup.txt) support reproduction.
Installed Gazebo is `libgz-sim8 8.15.0-1~noble`, transport is
`libgz-transport13 13.6.0-1~noble`. Build 4 was cancelled as superseded before
qualification. Attempt 9 refused to replace the still-terminating run-8 pod;
it executed no tests and changed no cluster resources.

**Overall Phase 5 remains HOLD.** This qualifies the small native actuator
fixture only: no full Nav2 task, controller comparison, hotel obstacle/contact
test, semantic observation under motion, or end-to-end 500 ms perception-fault
to actuator-stop test has yet passed.

## Passed: stamped command chain and owned-task ROS cancellation

Further work on October 16 added the
[owned-task state machine](../../../../apps/semantic-safety/task_session.py),
[ROS action adapter](../../../../apps/semantic-safety/nav_task_client.py), and
[source-command ledger](../../../../apps/semantic-safety/command_ledger.py).
The isolated profile now enables `TwistStamped` on the controller, behaviors,
velocity smoother and collision monitor, with
`stamp_smoothed_velocity_with_smoothing_time: false`. The canonical profile is
unchanged. This supersedes the earlier preflight's explicit unstamped contract.

The action adapter uses actual ROS `NavigateToPose` requests, UUID-bound goal
handles, asynchronous cancel requests and terminal result futures. Its revoke
hook runs synchronously **before** requesting cancellation. A cancel ACK does
not mean the goal has terminated: new requests remain blocked while the result
is outstanding, including after timeout or a rejected cancellation. Late goal
acceptance is cancelled without allowing commands. A successful backend result
after a fault retains the fault and outcome `stopped`, not `succeeded`. Old
session callback errors cannot change the current task.

This adapter manages **its own action only**. It does not arm `SafetyGate`,
prove that other Nav2 actions are idle, validate physical stationary state,
connect to the native guard, or publish actuator commands. It requires an
explicit backend name and a synchronous permission-revocation hook. Its
`may_command` result is a necessary task condition, never sufficient authority
to move. The integrating coordinator still needs the other guards below.

The ledger binds each checked output to an observed raw command's original
source ROS stamp, validated source wall stamp, session and fixed deadline.
Repeated smoothed outputs cannot renew that deadline; unbound stamps, prior
sessions, expired sources and out-of-range velocities are rejected. **Receipt
time is not an acceptable source wall stamp.** The wall-clock fixture can use
the original ROS stamp directly, but production simulation needs a qualified
simulation-to-wall capture mapping. The subsequent combined fixture below now
tests that mapping; application to the actual Nav2 hotel clock remains outstanding.

An important installed-runtime edge case was reproduced: when the velocity
smoother times out, it can generate newly stamped deceleration output from the
old command, even with smoothing-time restamping disabled. A stamped topic alone
therefore does not preserve command authority. The ledger rejects those
unbound outputs, including nonzero deceleration messages; source expiry must
revoke permission independently. The source code corroborates the observed
timeout behavior.
[Nav2 1.3.13 smoother](https://raw.githubusercontent.com/ros-navigation/navigation2/1.3.13/nav2_velocity_smoother/src/velocity_smoother.cpp).
The monitor copies input headers into its output, as verified in the fixture.
[Nav2 1.3.13 monitor](https://raw.githubusercontent.com/ros-navigation/navigation2/1.3.13/nav2_collision_monitor/src/collision_monitor_node.cpp).

Cluster evidence:

- [Preflight 4](preflight-4-20261016/test.log): 49 pure Python tests, six ROS
  owned-action checks and eight actual smoother/monitor checks passed.
- [Preflight 5](preflight-5-20261016/test.log): added and passed a seventh action
  check for late backend success after a fault.
- [Final preflight 6](preflight-6-20261016/test.log): **49 pure Python tests,
  eight ROS owned-action checks and eight installed smoother/monitor checks
  passed**. Seven local profile tests also pass. The last action regression
  checks prior-session callback errors against a new active request.

The final [action trace](preflight-6-20261016/owned-action.json) uses a controlled
fake navigation backend over real ROS action transport, not the actual BT
navigator or controller. The [command-chain trace](preflight-6-20261016/collision-monitor.json)
runs the installed native smoother and collision monitor against synthetic
scans, TF and commands. It checks normal stamp preservation, timeout restamping,
obstacle intervention, stale scans, delayed command reception and absence of
actuator topics. First observed ROS zero after obstacle injection was
**20.55–20.69 ms** in runs 4–6; this is not final-actuator latency or braking.
The native monitor's automatic resumption after clearing an obstacle remains
an explicit reason to keep the separate fail-latched supervisor.

All three runs used the pinned Phase 4 image, not a new deployment image:
`semantic-costmap@sha256:447c6ee36d2eff0707a69133881c4131e0033dab5c38099750844173d416c92f`.
The installed smoother is `ros-jazzy-nav2-velocity-smoother
1.3.13-1noble.20260903.025045` and the monitor is
`ros-jazzy-nav2-collision-monitor 1.3.13-1noble.20260903.031125`.
Final [source hashes](preflight-6-20261016/source-hashes.json),
[pod specification](preflight-6-20261016/pod.json), and
[cleanup](preflight-6-20261016/cleanup.json) are retained. No simulator, Gazebo
bridge, SAM3, RMF or motion authority was present in these new tests.

## Passed: combined supervisor-to-wheel fixture

The [combined coordinator](../../../../apps/semantic-safety/guarded_coordinator.py)
now connects the command ledger, `SafetyGate`, ROS owned-task client and native
wheel guard in a private flat-world fixture. This is a further integration
subgate, **not full hotel navigation or Phase 5 acceptance**. The fixture uses
real ROS action transport and real Gazebo physics; its navigation backend,
raw/checked commands and scan/TF evidence are deliberately controlled test inputs.
It does not run RPP, the real Nav2 behavior tree, SAM3 or scene perception.

Implemented and tested:

- [Native capture clock](../../../../apps/semantic-safety/native_clock.py):
  a per-instance native epoch, physics sequence and original wall/steady/simulation
  timestamps. Restart, rollback, pause and malformed/stale captures fail closed.
  Mapping uses the **strictly preceding** native physics sample as an earlier
  wall-time bound, with a bracketing gap of at most 30 ms. It does not interpolate
  a fresh timestamp or substitute receipt time. This is conservative dating,
  not a claim of exact wall capture time or cross-node clock qualification.
- Live native stationary checks: valid speed <0.005 m/s and angular speed
  <0.02 rad/s, zero applied command, disarmed native state, at least 250 ms
  continuous quiet captures, and capture age <100 ms. Fresh matching neutral
  raw/checked commands and an idle task registry are also required before arming.
  The fixture registry covers its **one owned fake action server only**; it
  is not proof of global Nav2 idleness. Unexpected task ownership revokes permission.
- Native arm acknowledgement **and** matching native session status must both
  arrive before dispatching the task. Late acknowledgements after cancellation
  cannot dispatch a goal. A bounded five-second preparation interval grants
  **zero motion only until the first valid command**; input freshness still
  applies. The first real command restores the ordinary 100 ms source lifetime.
  Native packets remain limited to 80 ms, shortened to remaining input/command
  authority. No recurring zero message can renew a previous moving command.
- [Dedicated transport process](../../../../apps/semantic-safety/native_link.py):
  bounded queues, asynchronous-to-the-coordinator service calls and exact packet
  forwarding. The worker never caches/republishes a command or resets a deadline.
  Service setup finishes while disarmed, before readiness/epoch qualification.
- Explicit task cancellation on stop, no successor while the terminal result
  is outstanding, and no automatic rearm on fresh inputs or terminal completion.

[Combined 1](combined-1-20261016/test.log) failed safely before task dispatch:
the first service connection produced a capture-age gap. Its failed evidence
is retained. Warming the connection before qualification corrected the ordering;
[combined 2](combined-2-20261016/runtime/summary.json) passed the initial eight
checks. Expanded runs [3](combined-3-20261016/runtime/summary.json) and
[4](combined-4-20261016/runtime/summary.json) passed **all ten live checks twice
with identical mounted source hashes**, including zero-only preparation and
an independently stalled supervisor output loop. Each final run also passed
**69 pure Python tests, six ROS frame callback tests and 15 native lease tests**.
The seven local Nav2 profile tests remain passing.

Measured at approximately 0.1 m/s, final runs 3 / 4:

| Fault injection | Injection → first applied wheel zero | Sampled travel from injection to stopped |
|---|---|---|
| Explicit cancel | 0.612 / 1.237 ms | 1.18 / 1.08 mm |
| Stop refreshing synthetic scan evidence | 490.805 / 489.315 ms | 49.88 / 49.88 mm |
| Fresh checked outputs without matching raw sources | 81.460 / 70.004 ms | 8.88 / 7.78 mm |
| Stall supervisor lease output | 61.053 / 48.894 ms | 6.88 / 5.78 mm |
| Kill transport worker process | 50.831 / 53.675 ms | 6.38 / 6.28 mm |

Scan loss is measured from cessation of evidence updates, **not** from the
500 ms freshness boundary. The robot continues for the remaining valid evidence
lifetime, explaining about 5 cm of simulated travel. For source/scan expiry,
the native guard stopped about 1.2 ms **before** the supervisor's recorded
deadline because of the downstream clock allowance. Negative signed
`trigger_to_applied_zero_ms` values mean native preemption, not negative physical
latency. All measured trigger-to-zero bounds meet the 100 ms fixture criterion.
The output-stall case inhibits the supervisor's transmission loop; it is not
a kill test of the entire ROS supervisor process. The transport process really
is killed. Travel is independently measured from Gazebo body poses and includes
the last pre-injection sample (up to about 6 ms of sampling uncertainty); these
remain simulated measurements, not certified real-robot stopping distances.

The final two runs mapped 312 command captures each without assigning a wall
time later than publication. Maximum conservative capture age was 16.57 / 25.85 ms.
In the last 450 ms before each injection, native simulation/wall progression was
0.99985–1.00007× real time across the two runs; neither pod recorded CPU throttling.
The mapping is now exercised with the native simulation clock; actual Nav2
clock delivery and camera/TF capture registration still require hotel tests.

Updated isolated image (build 7):
`semantic-safety@sha256:218b63994d5f063fa0b59e8f478619b9de5d93cabe75b9ae30aa091ca4cef967`.
The native change adds capture epoch/sequence/pause metadata; wheel authority
and 80 ms lease enforcement remain in the physics thread. Read-only mounted
Python code is pinned separately. Evidence includes the
[build log](combined-4-20261016/build.log),
[source hashes](combined-4-20261016/source-hashes.json),
[installed pins](combined-4-20261016/installed-pins.txt),
[coordinator events](combined-4-20261016/runtime/coordinator-events.json),
[task events](combined-4-20261016/runtime/task-events.json),
[full native trace](combined-4-20261016/runtime/trace.jsonl),
[capture bounds](combined-4-20261016/runtime/command-captures.json), and
[cleanup](combined-4-20261016/cleanup.json). Candidate build records/images are
retained; each test pod and its ConfigMap are removed. Canonical deployments,
semantic costs and OpenShift AI serving remain unchanged.

The same updated image also passed the original standalone native physics
regression in [native 11](native-11-20261016/runtime/summary.json): all eight
live checks passed, including raw DiffDrive bypass rejection, actual producer
death, explicit stop, pause/resume and old-session rejection. Producer death
reached applied wheel zero in 63.89 ms; explicit stop in 1.08 ms.

## Actual hotel/Nav2 integration: disarmed diagnostics, gate still HOLD

The new [hotel fixture](../../../../apps/semantic-safety/verify_hotel_stack.py)
launches the installed hotel world, corrected robot/lidar frames, the existing
RGB-D camera/target installer, actual odometry/scan/clock bridges, AMCL, map server,
RPP controller, planner, behavior server, path smoother, velocity smoother,
collision monitor and BT navigator. It uses the actual installed L1 map. There
is **no lease publisher, native arm request, command bridge, RMF dispatcher,
semantic layer or SAM3 inference process**. The short real NavigateToPose request
exercises the command chain while the native wheel guard remains disarmed, then
requires terminal cancellation. It is not a completed baseline navigation trial.

### Fixed: costmaps subscribed to nonexistent lidar topics

[Hotel 6](hotel-6-20261016/runtime/controller_server.log) aborted navigation with
`Costmap timed out waiting for update`, although the sensor bridge was healthy.
[Hotel 7's resolved subscriptions](hotel-7-20261016/runtime/sensor-graph.json)
proved that relative `scan_fixed` resolved to
`/robot_1/local_costmap/scan_fixed` and `/robot_1/global_costmap/scan_fixed`.
Neither had a publisher. The renderer and checked-in **candidate only** now use
`/robot_1/scan_fixed` explicitly for both maps. An added profile test prevents
regression; the canonical navigation configuration is unchanged.

[Hotel 8](hotel-8-20261016/runtime/summary.json) passed **9/11** checks; after
rendering-capacity adjustment, [hotel 9](hotel-9-20261016/runtime/summary.json)
passed **10/11**, with publisher binding still failing. Both validated real
RGB-D/lidar/odometry inputs, corrected static sensor extrinsics, nine active
lifecycle nodes, corrected costmap subscriptions, command publisher topology,
a 39-pose one-meter plan, nonzero checked commands and terminal navigation
cancellation, capture-time camera/lidar-to-map transforms, and no native arming
or meaningful robot displacement. This is **stationary** capture registration,
not moving projection, recognition accuracy, or collision-avoidance acceptance.

### Timing and transport findings

- Hotel 1 failed on an unwritable default Gazebo log path. The runner now uses
  the explicit writable record path already used by the native fixtures.
- Hotel 2 received only three raw ROS RGB frames and no depth frames, despite
  continuing scans/odometry. Camera observation now subscribes directly through
  Gazebo Transport, following the Phase 3 native-input architecture; the full
  compressed transport/inference pipeline is **not** exercised here. Hotel 3
  also demonstrated that receiving scans is not sufficient scene readiness:
  the fixture waits for actual finite lidar returns before localization.
- Hotel 8, with two software-rendering threads, ran at approximately **0.627
  real-time factor** during the command trial. Native physical capture age
  reached **102.04 ms** while the task was active, correctly latching the
  unchanged 100 ms freshness check. Increasing only the CPU ceiling from four
  to eight cores had removed cgroup throttling but had not solved the delay.
- Hotel 9 used four software-rendering threads with the same eight-core ceiling
  (two-core request, no GPU). Its short command trial ran at **0.9998 RTF**;
  peak native capture age during the task was **13.55 ms**, with no clock latch.
  This short diagnostic improvement is not a sustained-load qualification.
- Independent ROS command and native status deliveries can arrive out of order.
  The [bounded capture joiner](../../../../apps/semantic-safety/capture_joiner.py)
  waits at most **20 ms**, with a bounded queue, for a native clock bracket or
  matching original raw command. It never replaces a capture timestamp or
  renews the original 100 ms command lifetime. Five tests cover ordering,
  missing brackets, expiry, queue limits and session changes. It is currently
  used only by the disarmed observer, not the motion-authorizing coordinator.

[Hotel 10](hotel-10-20261016/runtime/summary.json) exercised that joiner with
**81 Python tests, six installed-ROS frame tests and 15 native tests passing**.
Its hotel smoke checks remain **10/11**, with publisher binding failed. The
three-second command window ran at approximately **1.0001 RTF**, with peak native
capture age **11.50 ms** and no latched clock fault. Of 157 checked observations,
137 were timestamp-eligible after the bounded join. This does **not** mean they
were authorized: the publisher-identity check still rejects the stream.

### Fresh-command continuity: promising disarmed timing result, not qualified

A positive capture-mapping smoke check is insufficient for a moving task.
The reproducible [offline continuity audit](hotel-10-20261016/command-authority-analysis.json),
generated by [this analyzer](../../../../apps/semantic-safety/analyze_hotel_commands.py),
found **14 gaps of 13.35–42.75 ms** between eligible checked-command authority
intervals. Hotel 11–19 isolated timing experiments showed both scan/controller
cadence and downstream capture-to-publication delay mattered. Raising the
controller target to 30 Hz, with the private lidar at 10 Hz and smoother at
100 Hz, produced the first no-gap result in [hotel 20](hotel-20-20261017/command-authority-analysis.json).
The longer [hotel 21](hotel-21-20261017/command-authority-analysis.json) repeated
that result over 20 seconds: **1,979/1,979** checked messages were eligible and
the optimistic analysis found **zero gaps** using the unchanged 100 ms lifetime
minus 2 ms uncertainty. In hotel 21, checked capture-to-publication delay was
**38.9 ms median, 52.5 ms p95, and 131.6 ms maximum**; late rows are rejected by
the existing capture/source checks. These runs were stationary and disarmed.
The analyzer omits supervisor/lease scheduling and window edges; this is a
promising scheduling candidate, not a pass or approval to adopt these rates for
motion.

Follow-up tests used the patched smoother overlay and added an actual unexpected
writer/restart probe. [Hotel 25](hotel-25-20261017/command-authority-analysis.json)
at 30 Hz had one **2.77 ms** authority gap, so that setting is not considered
continuous. [Hotel 26](hotel-26-20261017/command-authority-analysis.json) and
[hotel 27](hotel-27-20261017/command-authority-analysis.json) repeated the same
20-second disarmed trial at 40 Hz controller / 10 Hz scan / 100 Hz smoother.
Both had zero optimistic gaps: respectively **1,797/1,797** and **1,997/1,997**
eligible checked observations. Admitted capture-to-checked delays were 39.6 ms
median / 52.9 ms p95 / 82.5 ms max in run 26, and 34.1 ms / 47.1 ms / 97.4 ms
in run 27. Raw controller intervals were approximately 25 ms (p95 25.13 ms,
maximum 26.13 ms in run 27); neither controller log contained a missed-loop
warning. The authority analyzer remains optimistic (no lease scheduling or
window-edge proof), and these stationary tests are not 10/10 moving baseline
trials. Treat 40 Hz only as the leading isolated candidate, not a qualified or
checked-in operating profile.

[Hotel 28](hotel-28-20261017/runtime/summary.json) repeated the disarmed 20-second
40/10/100 Hz observation after adding a persisted action-server inventory. All
14 live checks passed, including real sensor/AMCL/Nav2 graph checks, 2,014
positive checked commands, terminal cancellation, publisher-GUID binding,
capture-time sensor transforms, and confirmation that the native guard stayed
disarmed and the robot stationary. The offline authority audit found 1,996
eligible checked messages and zero optimistic gaps; it still omits coordinator
and lease scheduling and does not qualify motion. The test suite, frame bridge,
and native lease tests all returned zero; the temporary test pod was removed.

The actual active hotel/Nav2 graph exposes ten action servers:
`navigate_to_pose`, `navigate_through_poses`, `follow_path`, `backup`, `spin`,
`drive_on_heading`, `wait`, `compute_path_to_pose`, `compute_path_through_poses`,
and `smooth_path`. This closes the action-endpoint *discovery* gap for this
candidate launch. It does not prove runtime ownership, reject goals from other
clients, cancel every active action on a fault, or revoke motion authority when
an endpoint changes. The complete service/type inventory is retained in
[action-endpoint-inventory.json](hotel-28-20261017/runtime/action-endpoint-inventory.json).
Direct `/cmd_vel`/Zenoh, relay-heartbeat and capture-motion paths remain excluded;
the audited fixture has no command bridge or lease publisher and never arms.

Nav2's controller loop waits for a current costmap before computing commands
([1.3.13 source](https://github.com/ros-navigation/navigation2/blob/1.3.13/nav2_controller/src/controller_server.cpp));
the hotel scan cadence was a plausible contributor to earlier stalls, but not
proven to be the sole cause. Future qualification must retain raw-to-checked
age distributions, missed-loop logs, and end-to-end guard deadlines. Never
restore apparent continuity by re-stamping an old source command.

### Per-message publisher identity: observer binding subgate passes

The installed Python callback metadata does not expose publisher GID (failed
attempts [4](hotel-4-20261016/test.log) and [5](hotel-5-20261016/test.log)). A new
[read-only C++ observer](../../../../apps/semantic-safety/native/command_observer.cpp)
retains middleware metadata without publishing velocity or leases. This exposed
a deeper mismatch: installed `rmw_cyclonedds_cpp` **2.2.4** puts the DDS
publication **handle** into message-info `publisher_gid`, while graph discovery
reports a GUID. The identifiers cannot be compared directly. The exact version's
[source implementation](https://github.com/ros2/rmw_cyclonedds/blob/2.2.4/rmw_cyclonedds_cpp/src/rmw_node.cpp#L3050-L3064)
and upstream [issue 377](https://github.com/ros2/rmw_cyclonedds/issues/377) support
the observed mismatch. The isolated C++ observer now resolves each sample's
publication handle through Cyclone DDS's built-in DCPSPublication reader to the
endpoint GUID and compares every message against the discovered topic/publisher
graph. [Hotel 20](hotel-20-20261017/runtime/summary.json) and [hotel 21](hotel-21-20261017/runtime/summary.json)
pass the independent `per_message_publisher_binding` check. No name-only,
arrival-order or receipt-time fallback is used. Hotels 24–27 additionally
created an unexpected writer on the disconnected checked-command topic, observed
its exact GUID, and confirmed the expected-publisher graph rejected it. The
publisher was destroyed and restarted; the new endpoint received a distinct GUID
and was also resolved and rejected. Deterministic tests cover stale-GUID rejection
after restart. This closes the observer-binding subgate for the isolated pinned
Cyclone implementation; it does not yet provide continuous runtime endpoint
revocation or full controller/recovery task ownership, idle/neutral readiness,
or task-wide publisher monitoring.

Candidate build 9 adds the read-only GUID resolver without changing native
watchdog source:
`image-registry.openshift-image-registry.svc:5000/semantic-navigation/semantic-safety@sha256:356c3648b60cf0490c0967de0a5849115c8ecd7d14ceb834eface57b437a3a99`.
Candidate build 10 adds the isolated Nav2 smoother overlay described below:
`image-registry.openshift-image-registry.svc:5000/semantic-navigation/semantic-safety@sha256:e697c4558af2415d4d59cbdf14d985683351668a8839e0ec399b918cfc3054cd`.
Each run retains mounted-source hashes, image/build records, installed binary
hashes, actual command metadata, sensor/command graphs, native physical traces,
logs and cleanup results. Failed subgates keep the runner unsuccessful even
when independent disarmed checks pass.

The updated image also passed [native regression 12](native-12-20261016/runtime/summary.json):
all eight live physics checks, 81 Python tests, six ROS frame checks and 15
native tests passed. Producer death reached applied wheel zero in **73.01 ms**,
explicit stop in **0.59 ms**, and pause in **2.31 ms**. The final test pod and
ConfigMap were removed and verified absent; the three pre-existing semantic
demo deployments remain 1/1 available and unchanged. Build/image records and
all local evidence remain retained. No repository commit or push was performed.

## Audit findings and required corrections

### Timeout-frame defect fixed in an isolated candidate; not a production qualification

Hotels 20 and 21 exposed a defect in the smoother's cancellation/timeout
deceleration tail: after velocity timeout, non-zero deceleration values were
published with an empty `header.frame_id`. The pinned Nav2 1.3.13
[velocity-smoother source](https://github.com/ros-navigation/navigation2/blob/1.3.13/nav2_velocity_smoother/src/velocity_smoother.cpp)
explains the exact cause. It copies the stored input frame to the outgoing
message, but once `velocity_timeout` expires it replaces its stored command
with a default-constructed `TwistStamped` and assigns a new timestamp. Later
timer iterations consequently propagate an empty frame. That regenerated stamp
must not be treated as source authority; the existing source-command ledger
correctly rejects that interpretation.

The isolated patch [nav2_velocity_smoother-frame-preserve.patch](../../../../apps/semantic-safety/nav2_velocity_smoother-frame-preserve.patch)
preserves the prior frame when replacing the stored twist with zero. Candidate
build 10 compiled the overlay from Nav2 1.3.13 commit
`f4108e5b1c2bce804a1aa0c7be6673a8eb4a1501`; the harness explicitly launched
`/opt/nav2-smoother-overlay/lib/nav2_velocity_smoother/velocity_smoother` (binary
SHA-256 `3fdce59b6aed016628a89e36762a58bf18351959f6dfe16614262dcc8a72de09`).
Hotels 25–27 explicitly launched the overlay executable and passed frame/axes
validation; hotel 26 and 27 also observed the
timeout deceleration tail with zero empty-frame smoother messages. The existing
ledger unit test that prevents smoothing from renewing a source deadline passed
in each run. Hotel 23 is retained as a failed experiment: when the publisher
probe ran after navigation, the added discovery work caused the independent
native clock monitor to latch `native_capture_stale`. Moving identity stress
before clock binding fixed the test order; hotel 24–27 then completed without a
clock fault. The patch is validated only in this stationary, disarmed candidate;
the canonical Nav2 image/configuration remains unchanged.

| Finding | Evidence | Phase 5 disposition |
|---|---|---|
| A 0.22 m circular footprint does not cover the rear chassis corners | Pinned SDF bounds x = −0.172…0.108 m, y = ±0.155 m; rear-corner radius 0.23154 m | Explicit hull + 0.01 m padding implemented in candidate; moving clearance still unqualified |
| Canonical global obstacle/inflation layers and approach polygon are disabled | `config/nav2/hotel_nav2_params.yaml` | Enabled only in separate candidate; no multi-floor/lift qualification claimed |
| Relative lidar topic resolves below each costmap namespace | Hotel 7 resolved DDS subscription graph | Both candidate maps now explicitly subscribe to `/robot_1/scan_fixed`; verified in the actual hotel graph |
| Cyclone message-info identifier differs from discovery GUID | Actual C++ callback metadata, pinned rmw source, and hotels 24–27 live writer/restart probes | Isolated per-message binding and unexpected-writer rejection pass; continuous endpoint revocation/task-wide ownership remain unqualified |
| Nav2 smoother timeout erased `TwistStamped.header.frame_id` | Nav2 1.3.13 timeout path and hotel 20–21 command traces | Patched 1.3.13 overlay passes stationary cancellation/frame checks in hotels 24–27; canonical stack remains unchanged, moving qualification pending |
| Existing TF helper re-stamps stored odometry with current time and also publishes a fixed `map -> odom` | `scripts/odom_tf_authority.py` | Do not reuse it; preserve actual odometry capture stamps and monitor receipt/deadline independently; use AMCL alone for map transform |
| URDF and simulator frame geometry differ | URDF base joint z = 0.10 m versus co-located SDF base links; URDF lidar x = −0.064 m versus SDF −0.032 m, with another 0.01 m lidar sensor offset | Correct isolated TF/scan-frame mapping and revalidate camera-to-map projection before motion; do not silently reuse Phase 4 stationary projections as moving-world evidence |
| Repository map and installed simulator map differ | Repository L1 origin y = −30.0 m; installed hotel map origin y = −42.25 m | Pin and validate the actual runtime map/start/goal together; do not substitute the repository PGM/YAML without validation |
| Several existing paths can publish commands directly | `entrypoint-nav2.sh` forwards `/cmd_vel` directly to a robot Zenoh key; `nav2_relay.py` publishes zero heartbeats; capture motion script publishes robot command directly | None may run in the Phase 5 moving graph; inspect actual publisher endpoints before arming |
| Default Gazebo drive command retention is not an independent stop guarantee | Pinned SDF exposes direct DiffDrive topic without a watchdog configuration | Add/qualify an actuator-side watchdog before any baseline motion; killing the ROS receiver must not retain the last nonzero command |

The [geometry audit](preflight-3-20261016/geometry.json) retains the installed
world/URDF hashes, robot SDF, collision bounds and DiffDrive configuration. The
[audit code](../../../../apps/semantic-safety/audit_geometry.py) rejects unsupported
collision geometry rather than guessing a hull. The geometry audit is static;
pose/TF consistency under motion remains a separate check. The source camera
installer places the camera relative to `base_link`, so the 10 cm base-joint
disagreement affects camera extrinsics as well as the lidar frame chain.

The examined upstream Gazebo 8 DiffDrive implementation retains `targetVel`
between callbacks and uses it in subsequent velocity updates. This supports
requiring explicit downstream timeout protection; it is not a substitute for
testing the exact installed binary under process/transport failure.
[Gazebo DiffDrive source](https://raw.githubusercontent.com/gazebosim/gz-sim/gz-sim8/src/systems/diff_drive/DiffDrive.cc).

## Command routing and stop contract to integrate

```text
RPP / all enabled recovery behaviors
  -> cmd_vel_nav -> velocity smoother -> cmd_vel_smoothed
  -> collision monitor -> phase5/collision_checked
  -> latched task supervisor -> short-lived session-bound command lease
  -> simulator-side receiver -> actuator-side watchdog -> private DiffDrive
```

Only the final qualified actuator path may publish to the private drive topic.
No RMF adapter, docking, teleoperation, direct capture-motion publisher or command
keepalive is in scope. Audit actual DDS **and Gazebo** endpoints, not just launch
remappings. Loss of any intermediate process must fail closed downstream.

The core's initial constants are 500 ms source/heartbeat freshness, 100 ms
upstream command lifetime, and 80 ms receiver lease with a proposed 20 ms steady
timer. Leases are shortened to the remaining upstream authority; republishing
cannot restart source or command lifetimes. Expiry also checks wall time and
ROS capture age. Pause/clock loss therefore cannot freeze the safety deadline.
The 80 + 20 ms budget is a design bound under timely scheduling, **not a measured
runtime guarantee**. Cluster clock synchronization must again justify the 2 ms
allowance before moving tests.

The combined coordinator establishes native applied-zero/stationary and task
readiness checks. `SafetyGate` itself still trusts those assertions; the real
hotel adapter now supplies measured sensor and closed-graph lifecycle evidence
for the no-recovery integration subgate. Idle Nav2 neutral publications are not
required; the fresh native-zero proof and new-session barrier replace them.
Cancel acknowledgements are not substituted for terminal results.
It must validate payload hashes, policy/generation, capture
identity and TF before submitting semantic evidence. Never translate a generic
`ready: true` or a new receipt timestamp into a fresh capture.

Every collision stop, stale input, cancel, epoch change and backend failure must
cancel the active task and revoke its command session. Clearing the fault only
restores readiness; an explicit operator/coordinator rearm after verified stop
and task cancellation creates a new session. Geometry-only and semantic-observed
runs use separate startup policies; a semantic fault must not silently switch
the running task to geometry-only mode.

## Remaining subgates, in execution order

1. **Hotel integration repeatability and recoveries:** the actual real-sensor
   adapter and private no-recovery navigation route are now connected, with
   three successful integration trials above. Retain and classify rejected scan
   payloads if run 33's stop recurs. Extend the explicit baseline tree only
   after qualifying recovery output frequency, bounded backup speed and a
   zero-only Wait policy; do not extend moving command lifetimes to accommodate
   the default 10 Hz behavior loop or unsolicited idle-zero dependency.
   The registry's controlled-client-graph assumptions do not prove caller/child
   lineage for arbitrary external dispatchers. Qualification of all enabled
   velocity paths, fault-time graph changes, and sensor loss is still required.
2. **Geometry-only baseline:** prove collision intervention, cancel, restart and
   command expiry at ≤0.15 m/s; measure final drive command and independently
   measured Gazebo physical displacement until stationary. Run **10/10** baseline
   goals without collisions, recording trajectories, contacts and controller timing.
3. **Observation-only SAM3:** keep semantic layers out of navigation; verify
   corrected capture-time projection under motion, registration and compute/network
   overhead. Do not re-label Phase 4's stationary base-frame checks as this test.
4. **Armed-supervisor fault matrix:** camera loss, TF loss, stale mask, hung
   inference, process/transport loss and clock anomalies; simulated backend
   timeout/overload/disconnect and late success. For every fault retain trigger,
   final zero-command timestamp, physical stopping distance and explicit reason.
   Require zero ≤100 ms after the 500 ms freshness trigger and no automatic resume.
5. **Evidence review:** all criteria above must pass before Phase 5 acceptance.
   No Phase 6 A/B navigation until the next review gate.

## Reproduction and cleanup

```sh
python3 -m unittest discover -s apps/semantic-safety -p 'test_*.py' -v
python3 -m unittest discover -s scripts/semantic-navigation -p 'test_phase5_params.py' -v
python3 scripts/semantic-navigation/run_phase5_preflight.py \
  --oc /Users/zhangj/bin/oc --output-dir /path/to/new-preflight-evidence
python3 scripts/semantic-navigation/run_phase5_native.py \
  --oc /Users/zhangj/bin/oc \
  --image image-registry.openshift-image-registry.svc:5000/semantic-navigation/semantic-safety@sha256:218b63994d5f063fa0b59e8f478619b9de5d93cabe75b9ae30aa091ca4cef967 \
  --output-dir /path/to/new-native-evidence
python3 scripts/semantic-navigation/run_phase5_native.py \
  --oc /Users/zhangj/bin/oc --suite combined \
  --image image-registry.openshift-image-registry.svc:5000/semantic-navigation/semantic-safety@sha256:218b63994d5f063fa0b59e8f478619b9de5d93cabe75b9ae30aa091ca4cef967 \
  --output-dir /path/to/new-combined-evidence
python3 scripts/semantic-navigation/run_phase5_native.py \
  --oc /Users/zhangj/bin/oc --suite hotel \
  --image image-registry.openshift-image-registry.svc:5000/semantic-navigation/semantic-safety@sha256:e697c4558af2415d4d59cbdf14d985683351668a8839e0ec399b918cfc3054cd \
  --controller-frequency 40 --scan-update-rate 10 \
  --smoother-frequency 100 --nav-seconds 20 \
  --output-dir /path/to/new-hotel-evidence
python3 scripts/semantic-navigation/run_phase5_native.py \
  --oc /Users/zhangj/bin/oc --suite hotel-guarded \
  --image image-registry.openshift-image-registry.svc:5000/semantic-navigation/semantic-safety@sha256:e697c4558af2415d4d59cbdf14d985683351668a8839e0ec399b918cfc3054cd \
  --output-dir /path/to/new-guarded-hotel-evidence
```

Hotels 26 and 27 passed all 13 disarmed smoke checks with the isolated patched
smoother, including zero empty-frame outputs and the unexpected-writer/restart
probe. The overall Phase 5 gate remains HOLD: these are stationary diagnostics,
and their optimistic source-authority analysis does not replace moving baseline,
physical stopping, or fault-matrix qualification. The hotel runner uses a
seven-minute pod deadline (other native fixtures retain five minutes).

The runner refuses to replace existing named resources, has a five-minute pod
deadline, retains source hashes/logs/manifests, and removes only its own
`semantic-phase5-preflight` pod and ConfigMap. See
[first cleanup](preflight-1-20261016/cleanup.json) and
[second cleanup](preflight-2-20261016/cleanup.json), plus the
[final cleanup](preflight-3-20261016/cleanup.json).
The native runner likewise refuses replacement and removes only its own
`semantic-phase5-native` pod and ConfigMap; successful runs retain their
[run-8 cleanup](native-8-20261016/cleanup.json) and
[run-10 cleanup](native-10-20261016/cleanup.json). The runner now waits for deletion
before returning to avoid racing a still-terminating predecessor. Candidate
BuildConfig/ImageStream and build records are retained for reproduction.
The historical collision-monitor preflight connected no motion path. Subsequent
native fixtures actuated only their own isolated flat-world robot. No canonical
deployment/configuration was modified and no OpenShift AI endpoint was deployed.
Repository changes are uncommitted; no commit or push was requested this turn.

## October 18 recovery/Wait probe: bounded Wait handoff verified; full task still fails

The first isolated BackUp→Wait probe exposed that Nav2 publishes no continuing
velocity samples during its BT `Wait` action. The native receiver correctly
expired the last checked command. A narrowly scoped recovery profile was added:
it admits only the actual `BackUp` and `Wait` BT children; `Wait` must remain
owned by the active parent task; the last requested and independently applied
motion must be within 0.005 m/s; then the coordinator normalizes it to exact
zero and renews only zero leases. Sensor freshness, source stamps, and the
independent native watchdog remain enforced. A Wait-time zero source sample
cannot shorten that hold deadline. During the transition, only the measured
reverse deceleration tail (no faster than 0.055 m/s, no lateral/yaw command,
maximum 300 ms, before the first zero hold) is admitted. Larger motion or any
nonzero command after the zero hold latches a stop.

The zero-hold subgate is independently supported by
[hotel-recovery-10](hotel-recovery-10-20261017/runtime/guard-events.json) and
its [native trace](hotel-recovery-10-20261017/runtime/trace.jsonl), then
repeated in [hotel-recovery-13](hotel-recovery-13-20261017/runtime/summary.json).
In recovery-10, BackUp and Wait both reached `SUCCEEDED`; Wait lasted 1,127.61
ms. The first authorized zero hold began 75.82 ms after Wait activation; 332
holds followed with a maximum gap of 7.40 ms. Across the 205 independent native
status samples from first hold through the final 50 ms of Wait, applied
translation and yaw were exactly zero. Recovery-13 independently recorded 196
such applied-state samples at zero, 349 holds, and a 9.58 ms maximum gap.
Reverse checked commands remained bounded at −0.05 m/s. Recovery-7 also
completed BackUp and Wait, with 347 holds and 10.23 ms maximum gap.

This verifies the guarded recovery/Wait handoff subgate, not repeatable
end-to-end recovery-enabled navigation. The 0.25 m probe (recovery-8) returned
success but did not satisfy the independent >0.2 m motion check because the
goal fell within arrival tolerance. The 0.5 m probe (recovery-10) met all other
runtime checks and returned terminal success. The following run
(recovery-13) actually used a **0.35 m target**, as recorded in its runtime
summary; it was not an identical repeat. It expired its native command lease
before terminal success and failed the motion threshold. The 0.75 m/1.0 m attempts also failed downstream
of Wait. Thus recovery-enabled task completion and meaningful-motion
repeatability remain unqualified. Earlier retained probes document the
debugging history: recovery-1 had no hold; recovery-2 revealed zero commands
could overwrite the hold deadline; recovery-3 rejected the smoother's bounded
reverse tail; recovery-4/5 narrowed the handoff timing; recovery-6 verified the
zero transition but exposed that subsequent zero inputs could reintroduce the
old deadline. The independent applied-state check now begins at first hold,
after the bounded deceleration handoff, rather than incorrectly requiring
Nav2 checked commands during its silent Wait interval.

Local verification after the final change: 130 safety tests, 10 runner
parameter tests, and `git diff --check` passed. All evidence remains in the
private runner output. No canonical deployment was changed. **Overall Phase 5
remains HOLD** pending repeatable recovery-enabled navigation completion,
physical fault-triggered stopping coverage, moving SAM3 registration/load
testing, and the armed semantic fault matrix. Semantic costs remain excluded
from motion.

## October 18 TF-loss fault-injection investigation: not yet qualified

Historical status, superseded by the October 19 qualification below. A subsequent
trace audit corrected the high-rate diagnosis: trial 5 never injected TF loss.
It stopped on command expiry first; the capture-clock fault occurred about
3.9 seconds later. Both navigation actions canceled and all cancellation
endpoints acknowledged. The combined terminal/stationary predicate timed out
because the latched clock fault prevented stationary verification.

An isolated `hotel-guarded` probe was added to pause only the fixture AMCL
process after a checked command and independent physical motion, then observe
guard revocation, native applied zero, task cancellation, and descendant
quiescence. The first two attempts stopped safely but do not establish that
loss of TF caused the stop: the coordinator latched `command_expired` in the
first trial (about 119 ms after injection); a second exploratory run shortened
the TF freshness window immediately on pause and reported `tf_stale`, but did
not require a post-injection failed capture-time transform lookup. Its applied
zero arrived 5.9 ms after the latched trigger, but that run is not accepted as
TF-fault attribution.

The stricter version now requires a post-injection failed `map→lidar` lookup
before its test-only 50 ms TF freshness window can take effect (the production
default remains 500 ms). At the default 10 Hz scan cadence, command expiry can
win before a new failed lookup is processed. Raising the diagnostic scan rate
to 30 Hz caused a native capture-clock fault and failed descendant-quiescence
verification, so that run is also not a pass. The runner cleaned its private
pod and ConfigMap in each case. See [exploratory trial 2](hotel-tf-loss-2-20261017/runtime/summary.json),
[strict trial 3](hotel-tf-loss-3-20261017/runtime/summary.json), and
[high-rate trial 5](hotel-tf-loss-5-20261017/runtime/summary.json).

The code now supports per-input freshness overrides and tests that a private
TF window leaves all other leases and the 500 ms default unchanged. Local
verification passes 132 safety tests, 10 Phase 5 parameter tests, Python
compilation, and `git diff --check`. The next useful step is to make the
fault injection deterministic without weakening the normal command watchdog,
then require all of: a post-injection failed transform, `tf_stale` as the
first latched reason, native applied zero, and terminal cancellation. **The
TF-loss fault subgate remains unpassed; overall Phase 5 remains HOLD.**

## October 19 TF-loss subgate PASS in the private geometry-only fixture

Two complementary live tests now pass with identical runtime source hashes and
the existing digest-pinned candidate image. Input/TF freshness stays at 500 ms,
command freshness at 100 ms, and the maximum native lease at 80 ms. The temporary
50 ms TF override and its runtime configuration path were removed. Both tests
use the usual 10 Hz lidar and require a current active task, fresh admitted
command, armed native receiver, and independently measured motion before injection.

| Test and retained summary | First coordinator reason | Earliest verified trigger to native applied zero | Trigger to confirmed physical stationarity |
|---|---|---:|---:|
| [Supervisor TF delivery loss](tf-supervisor-2-20261019/runtime/summary.json) | `tf_stale` | 2.293 ms | 813.754 ms |
| [AMCL publisher outage](tf-amcl-2-20261019/runtime/summary.json) | `command_expired` | 3.185 ms | 814.620 ms |

The supervisor test selectively drops dynamic `map→odom` updates only from a
dedicated supervisor TF buffer. Nav2 and the observer continue receiving the
full TF stream. It recorded five dropped updates and a failed lookup for a
new capture beyond the frozen map edge while odometry remained current; the
full buffer could resolve that exact capture. The coordinator latched `tf_stale`
532.295 ms after injection. This elapsed time includes cached transforms that
were still usable after injection: the 500 ms limit applies to the last
qualified capture, not to the injection timestamp. The first failed lookup
occurred 251.050 ms after injection.

The AMCL test pauses only its privately launched AMCL process. It preserves the
first protective stop reason and continues observing while AMCL is paused,
even when command expiry stops motion first. In the final run the coordinator
stopped at 120.202 ms after injection; a failed capture-time lookup proved the
frozen `map→odom` edge at 224.604 ms, with live odometry. AMCL is resumed in a
local `finally` block, including on timeout or assertion failure. Exceptions
revoke motion permission before restoring TF delivery.

Both runs verified terminal cancellation, acknowledgements from all ten action
endpoints, physical stationarity, and restored capture-time TF. Cancellation and
stationary verification are now separate checks. After restoration, 114 and 117
native status samples respectively confirmed zero applied velocity and no
renewed authority. Sampled horizontal travel from the earliest stop trigger to
confirmed stationarity was approximately 1.598 mm in each simulation. This is
sampled simulator evidence, not a hardware braking-distance specification.

The stop metric also needed correction. In
[the first new AMCL attempt](tf-amcl-1-20261019/runtime/summary.json), all behavioral
checks passed but the old metric returned `missing_stop_samples`: the native
watchdog had applied zero 0.185 ms **before** the coordinator deadline. Its
independent uncertainty allowance can make it trigger first. The corrected
metric accepts this only with post-injection native trigger evidence and a
recent armed status belonging to the same session; it rejects old stops,
different sessions, and any later motion or authority. It reports both the
earliest-trigger latency and the signed coordinator-relative latency. The
original failed summary remains retained; the final AMCL run is a fresh pass.
The [initial supervisor run](tf-supervisor-1-20261019/runtime/summary.json) also
passed before this metric correction.

Both final runs used the same 50 ConfigMap source hashes and image
`semantic-safety@sha256:700eb9424e301d571c80c31d31c97e9945f783afdc840f501ddb222440ec623e`.
Each installed suite passed 135 safety tests, six frame tests, ten ROS adapter
tests (including real TF-buffer separation/restoration), and 15 native lease
tests before the live trial. Local parameter tests, compilation, and whitespace
checks also pass. The missing-input reason assertion accidentally displaced by
the earlier override tests was restored to its original test.

Reproduce either mode with a new output directory:

```sh
python3 scripts/semantic-navigation/run_phase5_native.py \
  --suite hotel-guarded --tf-loss-probe --tf-loss-mode supervisor \
  --image image-registry.openshift-image-registry.svc:5000/semantic-navigation/semantic-safety@sha256:700eb9424e301d571c80c31d31c97e9945f783afdc840f501ddb222440ec623e \
  --output-dir /path/to/new-supervisor-evidence
```

Use `--tf-loss-mode amcl` and another new output directory for the publisher
outage. The runner retains manifests, source hashes, fault events, TF diagnostics,
command/physical traces and cleanup records. Both final evidence copies and
private pod/ConfigMap cleanups succeeded. No canonical deployment was modified.

**TF-loss subgate: PASS for the private geometry-only fixture. Overall Phase 5:
HOLD.** This closes the TF attribution/measurement blocker. Recovery-enabled
task repeatability, moving SAM3 registration/load verification, and the remaining
camera/inference/semantic faults still require qualification before Phase 6.

## October 19 recovery investigation: endpoint-time mismatch confirmed

Recovery repeatability remains **HOLD**. Three new private diagnostic runs retain
the 40/40/100 Hz command chain, 100 ms upstream freshness, 80 ms maximum native
lease, contact audit, rear support casters, 2 ms physics step, 12 m virtual lidar,
and 200 Hz odometry. No safety deadline or arrival tolerance was relaxed.

The historical comparison was not controlled: recovery-10 used a 0.50 m
goal, but recovery-13's summary records 0.35 m. The earlier description of it as
a repeat has been corrected. At 0.35 m, the 0.20 m arrival tolerance also makes
the independent >0.20 m displacement requirement unreliable. Subsequent probes
now explicitly use 0.50 m. This is a revised diagnostic scenario, not a
retroactive pass for either historical run.

The new evidence separates three mechanisms:

1. [Diagnostic 1](recovery-diagnostic-1-20261019/runtime/summary.json) stopped
   during FollowPath, after BackUp and Wait completed. Independent native
   captures show a **159.286 ms physics gap** at simulation time 14.0 s.
   The clock fault was already present at the native publisher, not introduced
   by Python receipt time: capture age was 103.893 ms when published, 104.228 ms
   when received. Checked commands stopped advancing; the command lease expired.
   The clock correctly remained latched. CPU throttling occurred during the
   whole fixture, but the aggregate counters do not establish that it caused
   this specific pause.
2. [Diagnostic 2](recovery-diagnostic-2-20261019/runtime/stage-timings.json)
   measured a **60.619 ms synchronous graph audit** inside a 62.778 ms guard
   call. The graph audit crossed the command deadline while preventing ingress
   processing. This explains this supervisor-side command expiry; it is not a
   Wait-handoff gap. Separately, after stop, 1,612 distinct physics samples over
   approximately 7.9 simulated seconds had identical x/y/yaw but an unchanged
   reported angular speed of 0.031819 rad/s. The stationarity check therefore
   failed. The pinned Gazebo implementation updates link velocity components
   through its changed-link frame-data path, consistent with stale component
   values when a pose stops changing; this remains a source-supported diagnosis,
   not proof that every post-stop velocity disagreement has that cause.
   [Gazebo 8.15.0 physics source](https://github.com/gazebosim/gz-sim/blob/gz-sim8_8.15.0/src/systems/physics/Physics.cc).
3. [Diagnostic 3](recovery-diagnostic-3-20261019/runtime/control-geometry.json)
   confirms the **near-goal rotate-only mismatch**. Its path endpoint was
   stamped at 13.026 s. At a robot capture of 21.642 s, transforming that fixed
   map endpoint using the original timestamp yielded **0.216730 m**, while
   using the robot capture yielded **0.193417 m**, matching RPP's carrot.
   Both yaw errors were within the 0.35 rad tolerance. Thus RPP stopped forward
   translation inside its 0.20 m threshold while the goal checker still saw a
   position outside that threshold. The pinned controller retains the endpoint
   timestamp; RPP transforms its plan for the current robot pose.
   [Nav2 controller 1.3.13](https://github.com/ros-navigation/navigation2/blob/1.3.13/nav2_controller/src/controller_server.cpp),
   [RPP 1.3.13](https://github.com/ros-navigation/navigation2/blob/1.3.13/nav2_regulated_pure_pursuit_controller/src/regulated_pure_pursuit_controller.cpp).

The targeted candidate copies the fixed map endpoint and assigns **the robot
pose's capture stamp** before the goal-check transform. It does not substitute
latest TF for captured sensor evidence or rewrite any velocity, scan, camera,
or semantic timestamp. The original controller remains the default executable;
the private overlay requires `--controller-endpoint-capture`. Its build starts
from the existing digest-pinned contact image and patches Nav2 commit
`f4108e5b1c2bce804a1aa0c7be6673a8eb4a1501` with zero patch fuzz. This is scoped
to the fixture's fixed map goal, not a general moving-frame target solution.

Additional harness changes retain bounded per-stage timing records and planner
endpoint/TF comparisons. A stationary timeout remains a failed check, but no
longer suppresses subsequent independent evidence. It does not clear faults,
grant readiness, or rearm. Diagnostic 3 consequently retained its terminal
failure and a separate `missing_stop_samples` metric failure when native zero
preceded the coordinator deadline; no diagnostic failure was reclassified.

`run_phase5_baseline.py --recovery-probe` now provides a separate frozen ten-trial
recovery series: fresh worlds, fixed target, required recovery/contact/stop
checks, no retries, stop on first failure. It is not interchangeable with the
one-meter no-recovery baseline. Do not start qualification until the candidate
pilot passes. Graph-audit scheduling, simulator stalls, and independently
qualified physical stationarity remain separate issues even if goal completion
is corrected.

All three diagnostic evidence copies and private pod/ConfigMap cleanups
succeeded. Local checks pass: 139 safety tests and 15 parameter/series tests.
The instrumented diagnostic live suites passed 137 safety tests, six frame callbacks, ten ROS adapter
tests, and 15 native lease tests. Candidate build/runtime results follow below;
these diagnostics alone do not close recovery repeatability or Phase 5.

The early-native-stop metric handling has subsequently been extended to ordinary
trials when an explicit `arm_requested` event identifies the revoked session.
It still requires a recent armed native sample for that same session, rejects
pre-arm stops, and rejects subsequent motion/authority. It does not require
inventing a fault-injection timestamp. Offline diagnostic-3 analysis then reports
native zero **1.133 ms after its native trigger**, 0.867 ms before the coordinator
deadline, with confirmed stationarity after 254.090 ms. Its original failed
summary remains unchanged and navigation still failed; this is a metric
correction, not a recovery pass.

### Controller candidate build and first live pilot

Build `semantic-safety-controller-phase5-2` completed and produced
`semantic-safety@sha256:cb041cae2c90bf4ecbd0c97d86352a4a8d1e18cf9b97cff3ca0a982f6d2e623b`.
The first build failed strict patch application because a blank context line
was missing; that was corrected against the exact commit and a local zero-fuzz
dry run passed before rebuild. The controller overlay compiled successfully;
upstream controller C++ unit tests were not enabled in this build. The existing
native watchdog binary was not changed.

[Pilot 1](recovery-controller-pilot-1-20261019/runtime/summary.json) verified the
[actual overlay executable and loaded controller library](recovery-controller-pilot-1-20261019/runtime/controller-runtime.json).
BackUp and Wait completed, but a **156.58 ms physics-capture gap** at simulation
time 14.8 s stopped FollowPath before it reached the goal region. Unlike the
graph-audit failure, there was no >10 ms measured supervisor stage near this
stop. Capture age already exceeded 100 ms at the native publisher, and
`native_capture_stale` latched. This run therefore **does not yet verify the
controller correction's end-to-end effect**.

The native watchdog applied zero 84.592 ms after its own trigger. The stopping
metric correctly failed its sample-coverage requirement: the pretrigger sample
was 65.909 ms old, beyond the 50 ms limit. Displacement was 0.154915 m, below the
required >0.20 m. Parent/descendants canceled and native commands stayed zero;
no fault was cleared or task restarted. The latched clock correctly prevented
readiness/stationarity acceptance even though the independent trace later
contained quiet physical samples. The failed pilot is retained, not retried as
qualification. **The ten-trial recovery series has not started.**

The pilot passed 139 Python safety tests, six frame tests, ten installed ROS
adapter tests, and 15 native lease tests before navigation. Evidence copying
and cleanup completed successfully. Local parameter/series tests total 15.
No canonical deployment/configuration was changed; the candidate BuildConfig,
image and build records remain available. Repository work is uncommitted.

Next work should isolate the physics pause with time-aligned per-interval
resource/render/logging measurements; aggregate CPU throttling counters alone
are insufficient. Move synchronous graph inspection out of the command
processing path only with a bounded, fail-closed audit-freshness contract and
process-loss/graph-change tests. Independently qualify post-stop velocity
measurement against the native pose stream rather than declaring cached
angular velocity zero. Then rerun a candidate pilot and, only after it passes,
the frozen recovery series. TF-loss's previously qualified scope remains
unchanged; overall Phase 5 stays **HOLD**.

### October 19 simulator-pause isolation and Wait measurement correction

A separate read-only process now records cgroup counters every 20 ms and process
counters every 100 ms, with original steady timestamps and explicit read errors.
It buffers observations and writes them at shutdown, outside the moving trial.
The offline resource analysis brackets physical-capture gaps rather than using
whole-run CPU totals. Process scheduler counters cover the process leader, not
every rendering/physics thread. Pressure files are unavailable in this container;
missing pressure data must not be interpreted as zero host contention.

- [Resource diagnostic 1](recovery-resources-1-20261019/runtime/summary.json):
  a **179.848 ms** physical-capture gap at simulation time 15.2 s. Its
  [resource bracket](recovery-resources-1-20261019/resource-analysis.json) has
  approximately 20 ms sampling intervals, **zero additional CPU throttles**,
  zero additional throttled microseconds, and no memory-limit/OOM events.
  Gazebo's disk-write burst before the gap motivates a recorder isolation test,
  but does not establish causation. Native zero took **109.711 ms**, exceeding
  the unchanged 100 ms deadline; pretrigger coverage also failed (68.781 ms).
- [First recording-disabled attempt](recovery-no-record-1-20261019/runtime/summary.json):
  removing the CLI recording arguments caused Gazebo to exit before sensors or
  arming. The retained stack recursively enters `FileLogger::Init` while creating
  the default console-log directory. This is a startup/log-path failure, **not a
  moving trial** and not evidence for or against recorder-induced pauses.
- [Sparse-recording diagnostic](recovery-sparse-record-1-20261019/runtime/summary.json):
  `--record-period 3600` still produced **12,588 changed-state messages over
  25.176 simulation seconds**, roughly 58 MiB on disk, effectively every 2 ms
  physics step. The **156.739 ms** capture gap at 14.9 s again had no additional
  CPU-quota throttling in its [aligned bracket](recovery-sparse-record-1-20261019/resource-analysis.json).
  Native zero took 89.625 ms, but pretrigger coverage failed at 62.084 ms and
  displacement was only 0.147838 m. This experiment did not isolate recording.

The pinned Gazebo log system records one-time component changes even when the
period has not elapsed. The CLI also enables recording when a record path is
provided, while its non-recording branch initializes the default console path.
The subsequent diagnostic therefore uses the server API to disable world recording
explicitly while initializing a writable console path; it does not change HOME,
sensor rates, physics, watchdogs, or the controller.
[Gazebo LogRecord source](https://github.com/gazebosim/gz-sim/blob/gz-sim8_8.15.0/src/systems/log/LogRecord.cc),
[CLI server setup](https://github.com/gazebosim/gz-sim/blob/gz-sim8_8.15.0/src/gz.cc),
[default log path](https://github.com/gazebosim/gz-sim/blob/gz-sim8_8.15.0/src/ServerConfig.cc).

The Wait metric now distinguishes Python enqueue time from actual native zero
application. In resource diagnostic 1, one native sample still reflected the
already-permitted -0.002 m/s settling tail; zero was applied about 6.046 ms after
normalization was enqueued. The corrected metric allows only that bounded
initial tail (at most 0.005, zero within 100 ms), requires continuing native
authority and sample coverage, and rejects **any** nonzero command after native
zero. It does not relax the actuator guard or authorize motion during Wait.
Sparse-recording diagnostic 1 passed this check: 185 native zero samples,
2.234 ms normalization-to-application latency, maximum sample gap 5.314 ms.
Original failed summaries remain unchanged.

Recording experiments are explicitly marked `diagnostic_only` and rejected by
the fixed-series acceptance function even if their navigation checks pass.
The three runs above retained their evidence and removed their private pod and
ConfigMap. TF-loss qualification is unchanged; recovery repeatability and
overall Phase 5 remain **HOLD**. Local tests currently pass: 147 safety tests and
20 parameter/series/resource-analysis/launcher tests.

#### Recording-disabled API diagnostic and recording-enabled control

The private API launcher explicitly initializes the console log and selects
`ServerConfig::SetUseLogRecord(false)` or `true`. It compiles against the
digest-pinned image's installed Gazebo libraries before simulation starts;
source hashes, build logs, executable SHA-256, command/physical/contact traces,
and resource samples are retained. It cannot be selected by the qualification
series and both modes set `diagnostic_only=true`.

| API-server experiment | Task outcome | Physics-capture evidence during task | Native zero / stop evidence |
| --- | --- | --- | --- |
| [Recording disabled](recovery-no-record-api-1-20261019/runtime/summary.json) | All checks passed; BackUp → Wait → FollowPath succeeded | Largest observed gap **16.515 ms**; no capture-clock fault | Zero **3.095 ms** after completion/revocation; confirmed stationary **477.063 ms**; contact check passed |
| [Recording enabled control](recovery-record-api-control-1-20261019/runtime/summary.json) | Canceled after command expiry | **203.784 ms** pause at simulation time 16 s; `native_capture_stale` | Zero **116.139 ms** after native trigger, beyond 100 ms; pretrigger gap **86.013 ms** and contact coverage also failed |

The successful run moved 0.282577 m, exceeding the required 0.20 m, and retained
only a roughly 46 KiB server console log, with no `state.tlog`. The control
produced a roughly 60 MiB state recording. Its
[resource window](recovery-record-api-control-1-20261019/resource-analysis.json)
again reports zero incremental CPU-quota throttling. No measured supervisor
stage exceeded 10 ms near its pause. Both runs used the same controller image,
world and robot hashes, rates, physics timestep, and safety limits. Generated
Nav2 parameter files differ in their per-pod ConfigMap mount path. The control
adds a runtime on/off switch to the launcher; these are semantically matched
API configurations, not an identical-binary randomized experiment.

**Assessment:** full-world recording is now strongly implicated in this private
fixture's long capture pauses. Disabling it removed the pause in one successful
moving diagnostic; enabling it through the same server API reproduced the
failure. The exact blocking operation inside Gazebo/transport/storage has not
been profiled, and one successful run does not establish repeatability or rule
out the separately observed graph-audit stall. This is also the first successful
end-to-end diagnostic with the endpoint-time controller correction, not yet a
qualified controller rollout or a counterfactual unpatched-controller test.

**Implementation direction:** separate console logging from optional world
recording for the private moving fixture. Preserve the independent native
command/pose/contact/stop evidence, manifests, source hashes and resource
measurements; run full-world recording as a separate diagnostic when needed.
The existing recorder-enabled fixture remains the default, and canonical
deployments are untouched. Before adopting a qualification candidate, freeze
the console-only launcher and evidence contract, verify its fail-closed
startup/shutdown and recording state, pass a fresh pilot, then start the fixed
ten-trial recovery series without retries. Keep the 100 ms command/stop and
500 ms sensor/TF thresholds unchanged. Graph-audit blocking and post-stop
velocity consistency still need independent treatment if they recur; moving
SAM3 and the semantic fault matrix remain outstanding.

Both API runs passed 147 safety Python tests, six frame tests, ten ROS adapter
tests and 15 native lease tests before navigation. Both evidence copies and
private pod/ConfigMap cleanups succeeded. No fixed recovery series has started;
TF-loss remains passed in its documented scope and overall Phase 5 is **HOLD**.

### Console-only qualification candidate

The new opt-in `--console-only-server` path uses an installed
`/opt/semantic-safety/bin/phase5_console_server`, built on the exact controller
candidate image. Unlike the exploratory API launcher, it has no recorder switch
and is compiled into a digest-pinned image rather than at trial startup. The
native watchdog, controller overlay, geometric profile, sensor rates and timing
limits are unchanged. Default and canonical launch paths are unchanged.

The first candidate build failed because `WorldCount()` is not a Gazebo 8 server
API. The corrected implementation checks world-index validity with the pinned
`EntityCount()` API; this build failure is not a moving-trial failure.
[Pinned Gazebo Server API](https://github.com/gazebosim/gz-sim/blob/gz-sim8_8.15.0/include/gz/sim/Server.hh).

Before arming, every console-only trial must pass actual-binary preflight tests
for private domain/transport/partition restrictions, a missing world, invalid or
existing console paths, preservation of an existing file, valid startup, bounded
SIGINT shutdown, and absence of world recordings. The smoke world uses its own
Gazebo partition. The moving world's SDF must contain exactly one world and no
explicit recording/playback plugin. Sensor readiness is still required.

The verifier then checks the live `/proc` executable, installed source hashes,
loaded libraries and recording files before allowing arming. It retains binary
identity and maps, checks bounded shutdown, and checks again for `.tlog` artifacts
after shutdown. These checks supplement rather than replace the independent
command, capture, contact and physical-stop metrics. No automatic restart is
introduced. A diagnostic flag cannot be combined with the candidate flag.

The fixed-series runner freezes the launcher source/build input as well as the
existing runtime inputs, passes the explicit candidate flag to each trial, and
requires all five console-server checks plus `world_recording=false`. Diagnostic
runs remain ineligible. A fresh candidate pilot must pass before starting the
fixed ten-trial series; a failed trial stops that series without a retry.

Local verification passes 150 safety tests and 22 parameter/runner/series tests.
Candidate build, pilot and series results are recorded below when available;
implementation alone does not change the Phase 5 HOLD status.

#### Pinned candidate pilot: startup passed, moving gate failed

Build `semantic-safety-console-phase5-2` completed with digest
`sha256:06fb9ce1d46313556260b7c0c8459f8afacaee5e00234c0b522c11f339a5629b`.
The [fresh qualification pilot](recovery-console-pilot-1-20261019/runtime/summary.json)
verified all ten launcher preflight checks, the installed executable and source
hashes, and absence of a loaded recorder or `.tlog` artifacts. It did **not**
complete recovery: command expiry canceled BackUp before Wait or FollowPath.
There was no capture-clock fault. Contact, cancellation and physical-stationarity
checks passed; native zero was applied **3.070 ms** after the earliest native
trigger and stationarity was confirmed after **316.387 ms**. Displacement was
only 0.019345 m. The ten-trial series was therefore **not started**.

The full [command audit](recovery-console-pilot-1-20261019/runtime/commands.json),
which continues after revocation, isolates a **63.083 ms Collision Monitor
output gap**. Its last old-stamp output was published at wall time
`1792417143424692174 ns`; the next output was published at
`1792417143487774729 ns`, about **4.344 ms after** the prior command's final
native lease deadline. Newer smoothed inputs were already being published. The
next output's original capture age at publication was about 82.749 ms; it was
not intrinsically expired, but arrived too late to preserve continuous authority.
It must not rearm a revoked session. The audit-hop delay was small; the
supervisor's measured callbacks and graph audit never exceeded 10 ms in this run.

The [resource analysis](recovery-console-pilot-1-20261019/resource-analysis.json)
shows a concurrent **48.625 ms** physical-capture gap, with no added CPU-quota
throttling. This is smaller than the recording-enabled diagnostic pauses, but
still consumes command-chain headroom. The failed pilot ran on worker
`ip-10-0-53-174.ec2.internal`; the successful recorder-disabled diagnostic and its
recording-enabled control both ran on `ip-10-0-53-182.ec2.internal`. Both workers
are `m6i.4xlarge`. A later `oc adm top nodes` snapshot showed 91% versus 18% CPU
usage; that snapshot is **not time-aligned with the pilot** and cannot establish
host contention as its root cause. Zero cgroup throttling does not rule out host
scheduling delays. The pod requests two CPUs while allowing up to eight.

Collision Monitor obtains source data and transforms before publishing its
output; with base-shift correction enabled, it transforms the sensor capture
into the current base frame. TF waiting and scheduling are therefore concrete
next instrumentation targets, **not confirmed internal causes** of the observed
output gap. Do not disable base-shift correction, substitute latest TF, renew
source timestamps, or increase the 100 ms deadline to obtain a pass.
[Collision Monitor 1.3.13](https://github.com/ros-navigation/navigation2/blob/1.3.13/nav2_collision_monitor/src/collision_monitor_node.cpp),
[source transform path](https://github.com/ros-navigation/navigation2/blob/1.3.13/nav2_collision_monitor/src/source.cpp).

#### Independent shutdown defects and corrections

The same pilot failed the new shutdown gate with exit `-11` and an XIO error.
The old fixture signaled all process groups before waiting for any, allowing
Xvfb to exit while Gazebo/Ogre still used the display. Teardown now waits for
Gazebo and the other application processes before signaling the display and
resource sampler. Forced termination remains a failed qualification check.

The [first disarmed shutdown validation](console-shutdown-disarmed-1-20261019/runtime/summary.json)
proved the corrected order in its
[shutdown events](console-shutdown-disarmed-1-20261019/runtime/process-shutdown.json),
and no longer logged XIO, but **still failed** with exit `-6`. Its log shows
`rclcpp` processing SIGINT followed by an invalid-context guard-condition
exception during Gazebo teardown. Thus display ordering was a real defect but
not the only one. The minimal preflight world has no hotel ROS plugins and did
not expose this second problem.

For the console candidate, teardown now requests `stop: true` through the private
Gazebo `/server_control` service after revoking task authority. This requests
Gazebo shutdown without simultaneously signaling its plugins' ROS context.
Qualification requires a positive service reply, normal exit code zero, no
forced kill, and display teardown only after Gazebo exits. Rejected/timed-out
service requests fall back to signals for cleanup but **cannot pass** the gate.
This changes test teardown only, not the motion stop path or its timing limits.
[Gazebo stop message](https://github.com/gazebosim/gz-msgs/blob/gz-msgs10/proto/gz/msgs/server_control.proto),
[server implementation](https://github.com/gazebosim/gz-sim/blob/gz-sim8_8.15.0/src/ServerPrivate.cc).

Current local checks pass: **157 safety tests and 22 runner/series tests**. The
pilot and first disarmed run both retained their evidence and cleaned up their
private pod and ConfigMap. No failure was retried as a qualifying series trial.
The moving command-chain latency issue remains open independently of shutdown.

The [second disarmed validation](console-shutdown-disarmed-2-20261019/runtime/summary.json)
received the positive stop-service reply and logged the renderer thread stopping,
without the earlier XIO or invalid-context exception. However, Gazebo did not
exit within five seconds and was forcibly terminated (`-9`). Its
[shutdown evidence](console-shutdown-disarmed-2-20261019/runtime/process-shutdown.json)
therefore correctly fails the gate despite the positive acknowledgement. All
other disarmed checks passed. This is **not** a clean-shutdown pass, nor evidence
that the remaining hang is definitely a ROS-plugin deadlock. The blocking stack
and lifecycle stage still need to be captured before another teardown change.
Evidence copy and private pod/ConfigMap cleanup succeeded for this run too.

**Current next steps:** isolate the shutdown wait with lifecycle-stage markers
and thread-stack evidence while disarmed; instrument Collision Monitor callback
and TF-wait durations alongside native capture and node scheduling evidence;
freeze any resulting candidate changes, then require a fresh successful moving
pilot before starting the no-retry series. Do not substitute extra shutdown
time, source restamping, broader TF tolerance, or a longer command deadline for
these investigations. The fixed recovery series remains unstarted; TF-loss's
existing pass is unchanged and overall Phase 5 remains **HOLD**.

#### October 19 follow-up: instrumented shutdown candidate and scheduling capacity

Build `semantic-safety-console-phase5-3` completed with digest
`sha256:e956a58dbd4f70dfc2e8e28c2526ea72eb91084dc48f363d0be3ebf7a0ba88eb`.
The launcher now logs construction, return from `Run`, and entry/exit of the
server destructor. After a five-second shutdown failure, the verifier retains
per-thread `/proc` wait information and attempts a bounded, unprivileged GDB
backtrace. Debugger attachment happens **only after the gate has already failed**;
it may pause threads, so it is never used during a moving measurement. The
post-failure diagnostic has a separate three-second limit and cannot turn a
timeout into a pass. Permission errors and partial debugger output are retained.
No pod capability, seccomp exception, or ptrace permission was added.

This instruments a specific hypothesis, not a confirmed root cause:
Gazebo's service stop thread and destruction path both call `Stop`, and sensor
teardown joins a rendering thread. A stack is needed to distinguish overlapping
teardown from another wait. See the pinned
[server shutdown paths](https://github.com/gazebosim/gz-sim/blob/gz-sim8_8.15.0/src/ServerPrivate.cc)
and [sensor teardown](https://github.com/gazebosim/gz-sim/blob/gz-sim8_8.15.0/src/systems/sensors/Sensors.cc).

Local checks pass: **161 safety tests and 22 runner/series tests**. Added tests
verify that snapshots run only after failure, snapshot errors cannot suppress
forced cleanup, and unavailable/partial debugger output remains evidence.
The disarmed invocation `console-shutdown-disarmed-3-20261019` initially could
not schedule: at 13:56 UTC the scheduler reported **8 nodes with insufficient
CPU and 16 with untolerated taints**. The two previously used workers had
14.479 and 14.106 CPUs already requested, respectively, leaving insufficient
room for this fixture's unchanged two-CPU request. A completed build does not
reserve those CPUs for the subsequent test. Do not lower the fixture request,
add tolerations, or interrupt another workload to obtain a test result without
an explicit resource/availability decision. This is a capacity limitation, not
new runtime evidence about shutdown.

Capacity subsequently became available on `ip-10-0-44-171.ec2.internal`:
attempt 3 was scheduled at 13:59:32 UTC, between the last Pending observation
and operator cancellation. It was interrupted without complete runtime
evidence and is **ABORTED**, not a pass or a measured shutdown failure; see
its [attempt record](console-shutdown-disarmed-3-20261019/attempt-status.json).
Its private pod and ConfigMap were removed successfully. Attempt 4 uses the
same image, source and resources for a fresh disarmed diagnostic. No running
demo workload was scaled down, and no recovery-series trial was started.

The retained failed moving pilot also narrows the latency investigation. In
[resource samples](recovery-console-pilot-1-20261019/runtime/resource-samples.json),
the observations at steady timestamps `12472590839412251` and
`12472591045801188` bracket the 63.083 ms Collision Monitor output gap. Across
that approximately **206.389 ms** interval, Collision Monitor PID 262's main
thread accumulated **4.451 ms CPU execution and 8.132 ms run-queue wait**;
Gazebo PID 109's main thread accumulated **86.896 ms execution and 67.696 ms
run-queue wait**. These are cumulative per-thread counters, not whole-process
CPU totals or exact per-callback durations. Collision Monitor's main-thread
run-queue wait alone therefore cannot explain the complete output gap. This
does not rule out delayed TF producers/listeners, callback blocking, or upstream
scheduling; it does not prove a particular TF wait. The source uses its main
thread to spin the node and a separate TF listener thread.
[Collision Monitor entry point](https://github.com/ros-navigation/navigation2/blob/1.3.13/nav2_collision_monitor/src/collision_monitor_main.cpp),
[TF listener setup](https://github.com/ros-navigation/navigation2/blob/1.3.13/nav2_collision_monitor/src/collision_monitor_node.cpp),
[scheduler counter definitions](https://docs.kernel.org/scheduler/sched-stats.html#proc-pid-schedstat).

#### Shutdown blocking stack captured; serialized-stop correction

The [fourth disarmed run](console-shutdown-disarmed-4-20261019/runtime/summary.json)
completed on the newly available worker with unchanged resources. All checks
except bounded shutdown passed. The launcher printed `run_returned result=0`
and `destructor_begin`, but not `destructor_end`. After the failed five-second
wait, unprivileged GDB captured the main thread in this path:

```text
main → gz::sim::Server::~Server → SensorsPrivate::Stop → std::thread::join
```

The [full thread evidence](console-shutdown-disarmed-4-20261019/runtime/process-shutdown.json)
shows the renderer thread is no longer present, and the Gazebo console log
records its exit. The loaded-library map identifies the actual sensor and
server libraries as version **8.15.0**. This confirms the blocking site is
sensor teardown during server destruction, not the hotel ROS plugin's spin
callback or a still-rendering camera. The source's independently initiated stop
thread, repeated sensor-stop entry, and already-finished renderer support an
overlapping-join mechanism; the snapshot itself does not capture both callers
inside the join simultaneously. The run remained failed and was forcibly
cleaned up; evidence copy and private pod/ConfigMap cleanup succeeded.

The correction under test gives the private launcher an owned stop worker and
`/phase5/console_stop` endpoint. The callback only records the stop request;
the worker calls `Server::Stop`, and the main thread **joins that worker before
allowing Server destruction**. The simulation continues to use the existing
blocking `Run` path. During operation the extra worker sleeps on a condition
variable; it does not poll or alter physics, command deadlines, or lease state.
The native `/server_control` implementation is not patched, and the private
harness no longer uses it for this candidate.

The empty-world preflight now checks rejection of `stop:false`, a positive
stop acknowledgement, normal bounded exit, and ordered lifecycle markers.
The full hotel shutdown gate also requires `stop_end → stop_worker_joined →
destructor_begin → destructor_end`; acknowledgement alone remains insufficient.
Local checks pass **164 safety tests and 22 runner/series tests**. The new
serialized-stop build and a fresh disarmed validation must succeed before
calling this correction verified. The independent moving command-gap blocker
and overall Phase 5 HOLD remain unchanged.

#### Serialized shutdown verified in the disarmed hotel fixture

Build `semantic-safety-console-phase5-4` completed with candidate digest
`sha256:b0bcdf4700fd13fb5e9d35936f465a74b2edd8124dd30f840b687782e35b4f6c`.
The [fifth disarmed validation](console-shutdown-disarmed-5-20261019/runtime/summary.json)
**passed every check**, including all 11 actual-binary preflight cases, source
and executable identity, absence of world recording, and full-hotel shutdown.
Gazebo exited with code **0**, with **no forced termination**, and was reaped
**1.443 seconds after the positive stop acknowledgement**. Xvfb was signaled
only after Gazebo had been reaped. The actual hotel lifecycle order was:

```text
stop_begin → run_returned → stop_end → stop_worker_joined
           → destructor_begin → destructor_end
```

See the [shutdown events](console-shutdown-disarmed-5-20261019/runtime/process-shutdown.json)
and [launcher log](console-shutdown-disarmed-5-20261019/runtime/gazebo.log).
The before/after disarmed runs used the same worker, two-CPU request/eight-CPU
limit, robot geometry, sensor setup and five-second shutdown wait. Their
deliberate change was the serialized stop path and its corresponding evidence
checks. No safety deadline, TF tolerance, sensor timestamp, or motion authority
rule was relaxed. All artifacts were copied successfully; the private pod and
ConfigMap were removed. The canonical demo remained running throughout.

**Status:** the reproduced teardown blocker is resolved in this private,
disarmed fixture. This is not a moving-navigation pass or a repeatability
claim. Later disarmed timing probes localized the recurring ~20–30 ms callback
stall, but cannot qualify active output continuity. The historical 63.083 ms
moving-output gap still needs an instrumented moving trace to establish its
exact callback/TF/scheduling contributions. Require a fresh successful moving
pilot before starting the fixed ten-trial recovery series. The series remains
unstarted; the existing TF-loss subgate pass is unchanged; overall Phase 5
remains **HOLD**.

#### October 19: repeated disarmed Collision Monitor timing isolates a source-transform stall

The private console image `semantic-safety-console-phase5-7` (digest
`sha256:37401ad98bb5dd49ab41970d47ed0790d7f3ab29c6161bcdfde44b5076e26998`)
contains an opt-in overlay built from Nav2 commit
`f4108e5b1c2bce804a1aa0c7be6673a8eb4a1501`. It records only timing and return
status around the Collision Monitor input callback, source-data path, and
`Source::getTransform`; it does not change command processing or safety
decisions. To limit logging perturbation, callback-gap logs require at least
20 ms and callback/source/TF duration logs require at least 25 ms. The earlier
[exploratory run](cm-timing-disarmed-1-20261019/runtime/collision_monitor.log)
used denser thresholds and emitted 773 diagnostic lines, so it is retained for
exploration but excluded from the clean-run comparison. A subsequent attempt
failed the capture-freshness check before producing any CM timings and is also
not timing evidence.

Two identical repeats, [run 4](cm-timing-disarmed-4-20261019/runtime/summary.json)
and [run 5](cm-timing-disarmed-5-20261019/runtime/summary.json), passed all 22
runtime checks. Both used the disarmed, stationary hotel/Nav2 fixture, no world
recording, no GPU request, and the exact diagnostic executable and library
verified at runtime. The native receiver stayed disarmed; `clock_fault` was
null. Positive checked commands were observed (302 in run 4 and 299 in run 5),
but they were not authorized to move the robot. The private fixture was pinned
to an otherwise application-free GPU node only to obtain scheduler capacity;
its test-only toleration did not request or consume a GPU. The private pod and
ConfigMap were removed after each run.

Both runs contain the same aligned timing signature:

| Measurement | Run 4 | Run 5 |
|---|---:|---:|
| Scan TF lookup duration (`ok=1`) | 30.327 ms | 30.337 ms |
| Source `getData` duration | 30.415 ms | 30.405 ms |
| Full input callback duration | 30.659 ms | 30.688 ms |
| Gap until next callback start | 30.716 ms | 30.889 ms |
| Largest positive checked-command arrival gap | 31.105 ms | 30.889 ms |

The follow-up [run 6](cm-timing-disarmed-6-20261019/runtime/summary.json)
also passed all 22 runtime checks. It retained the same disarmed/stationary,
no-recording, no-GPU-request conditions and exact diagnostic executable/library
identity. The native receiver stayed disarmed; `clock_fault` was null; cleanup
removed the private pod and ConfigMap. Its two long successful TF lookups show
the same signature:

| Run 6 event | TF lookup | `getData` | Full callback | Next callback gap |
|---|---:|---:|---:|---:|
| Scan stamp 4.800 s → target 5.000 s | 30.304 ms | 30.464 ms | 30.682 ms | 30.862 ms |
| Scan stamp 5.000 s → target 5.200 s | 30.367 ms | 30.543 ms | 30.857 ms | 30.927 ms |

The largest positive checked-command arrival gap in run 6 was **31.714 ms**,
from wall times `1792431394948158576 ns` to `1792431394979873076 ns`; it aligns
with the second TF event (logged at `1792431394947439563 ns`). For those two
lookups, thread instrumentation measured:

| Event | Thread CPU | Scheduler runtime | Run-queue wait | Off-CPU/unattributed residual |
|---|---:|---:|---:|---:|
| Scan 4.800 s | 0.132 ms | 0.132 ms | 0.019 ms | 30.153 ms |
| Scan 5.000 s | 0.168 ms | 0.217 ms | 0 ms | 30.199 ms |

These are bracketed counter deltas, not stack-level wait attribution. They
nevertheless show that the ~30.3 ms elapsed lookup is overwhelmingly not CM
CPU work or run-queue contention: almost all of it elapsed while the CM thread
was not executing and was not queued for CPU. Both transforms succeeded.
The scheduler `slices=3` counter is a thread timeslice delta, **not** a count of
TF polling iterations.

In run 4, the TF lookup began at wall time `1792423682967778493 ns`; the
corresponding checked-command gap ran from `1792423682968823882 ns` to
`1792423682999928745 ns`. In run 5, the lookup began at
`1792423941461291757 ns`, and the largest command gap ran from
`1792423941461792236 ns` to `1792423941492680953 ns`. In each case, the TF
lookup, `getData`, and complete callback durations closely account for the
callback and checked-output gap. The lookup succeeded and processed 277 scan
points; this is not a failed-lookup/fallback case. Runtime parameters had
`base_shift_correction: true` and `transform_tolerance: 0.1` for Collision
Monitor.

**Per-edge follow-up:** build 9 added the opt-in 1 ms probe, but its first two
20-second trials emitted no TF event at the then-current 25 ms log threshold.
They therefore could not identify the late leg; one also had a transient
console-server destructor abort, while the second shut down cleanly. Both
retained the already-known settled-support-geometry failure. Build 10 lowered
the log threshold to 8 ms only when the explicit probe flag is set. These runs
are still diagnostic-only and may be perturbed slightly by the helper thread.
Build 10 is pinned at
`sha256:11c98c3c61e7b13f0635ce9ae5931b6b734c6a75d406c597a60fd4067275fdfb`.

The 50 Hz baseline [run](cm-timing-edge-probe-3-20261019/runtime/summary.json)
logged 778 successful (`ok=1`) lookup calls of at least 8 ms. The sampler found
the `odom ← lidar_frame` scan-time leg ready in a mean **0.105 ms** (range
0.047–1.098 ms). It detected the current-time `odom/base_footprint` leg becoming
available later in 717 of 778 calls: mean **9.793 ms** (range 3.320–15.338 ms);
in 703 calls it lagged the source leg by more than 5 ms. All 778 full advanced
lookups and end-of-call target checks succeeded. Durations cluster at the TF2
poll cadence: median **10.207 ms**, p90 **20.308 ms**, maximum **21.569 ms**.
The checked-output gap reached **33.570 ms**. The exact asset used
`odom_publish_frequency=50` Hz, a 20 ms interval
([run asset](cm-timing-edge-probe-3-20261019/runtime/assets/hotel.world)).

The controlled disarmed [200 Hz comparison](cm-timing-edge-probe-4-odom200-20261019/runtime/summary.json)
changed only that fixture rate. Its 466 logged calls (at least 8 ms) took
10.123–11.740 ms; their current-time base/odom leg became available after a
mean **2.053 ms**, and none took 12 ms or longer. No target transform was
missing at lookup completion. The largest positive checked-output gap fell
from **33.570 ms to 26.683 ms**. This is a single exploratory A/B, not a
qualification; both runs failed only the independent settled-support-geometry
subgate (`floor_3::collision` against `base_link::base_collision`). In both,
`native_never_armed_and_robot_stationary` passed, `clock_fault` was null, and
console shutdown/cleanup succeeded. The robot never had motion authority.

**Root-cause assessment (refined from the raw per-call data):** the recurring
10–20 ms synchronous stall has two linked causes. First, Collision Monitor
asks for the base transform at `curr_time`, while the Phase 5 fixture only
publishes `odom → base_footprint` TF when its odometry message arrives. The
fixture's [`frame_bridge.py` implementation](cm-timing-edge-probe-3-20261019/manifest.yaml#L383)
copies the odometry message's header stamp onto that TF, so the requested time
is commonly ahead of the newest transform in the buffer. The 50 Hz odometry
stream has a 20 ms sample interval; the 200 Hz
stream has a 5 ms interval. This is a timestamp/publication-phase gap, not
expensive transform math.

Second, the pinned TF2 0.36.22 advanced lookup uses a fixed
`std::this_thread::sleep_for(10ms)` after an unsuccessful availability check.
It does not wake as soon as the transform arrives. This is directly visible
in the correlation: at 50 Hz, 377 of the 717 sampled target transforms seen
by the helper became available 5–10 ms after lookup start, and all 377 lookups
finished in the ~10 ms class. Of 326 observed target arrivals after 10 ms,
301 incurred the second poll and finished in the ~20 ms class. At 200 Hz, all
466 sampled target transforms arrived after lookup start but within 5.479 ms
(mean 2.053 ms); nevertheless, every full lookup took 10.123–11.740 ms. The
first failed check therefore leaves the callback asleep for the rest of the
10 ms polling period even when the missing TF arrives quickly. This explains
why 200 Hz removes the observed 20 ms class but cannot remove the ~10 ms
latency floor.

The scan-time `odom ← lidar_frame` leg was already available within a mean
0.105 ms in the 50 Hz run. The measured CM thread CPU time was sub-millisecond
(median about 0.19 ms at 50 Hz and 0.18 ms at 200 Hz); run-queue wait was also
small. These measurements rule against CM compute and CPU starvation as the
dominant cause. The exact upstream path is pinned: [Nav2 Collision Monitor
source](https://github.com/ros-navigation/navigation2/blob/1.3.13/nav2_collision_monitor/src/source.cpp)
uses [Nav2's two-time transform
helper](https://github.com/ros-navigation/navigation2/blob/1.3.13/nav2_util/src/robot_utils.cpp#L824-L855),
and [TF2 0.36.22 polling implementation](https://github.com/ros2/geometry2/blob/0.36.22/tf2_ros/src/buffer.cpp#L1074-L1095)
sleeps 10 ms between unsuccessful checks. Installed packages were
`ros-jazzy-nav2-util 1.3.13-1noble.20260903.023450`,
`ros-jazzy-tf2 0.36.22-1noble.20260902.041654`, and
`ros-jazzy-tf2-ros 0.36.22-1noble.20260903.021700`.

**Remaining attribution limit:** this probe observes when the transform becomes
queryable in TF2, but does not separately timestamp Gazebo odometry publish,
ROS odometry receipt, and `frame_bridge.py` TF publication. Thus it identifies
the cadence/phase gap at the TF consumer and the TF2 polling quantization, but
cannot apportion the remaining few milliseconds among Gazebo scheduling,
`ros_gz_bridge`, and the frame-bridge callback. The earlier ~30.3 ms and
63.083 ms events were not reproduced: this probe's maximum lookup was 21.569
ms, so those larger outliers are not yet fully attributed.

**Recommendation:** retain 200 Hz odometry/TF as the first demo candidate—it
preserves transform and capture-time semantics, and the earlier guarded moving
[pilot 45](hotel-contact-45-20261017/runtime/summary.json) passed 20/20 checks
with improved admitted-command latency. Keep `base_shift_correction: true`,
the 100 ms command freshness and native lease limits, and exact timestamps; do
not use latest-TF fallback or increase `transform_tolerance`. The private 1 ms
TF2 polling candidate can reduce lookup delay, but the corrected-profile
comparison below found its benefit is load-sensitive and it adds substantial
polling/wakeup CPU. Keep it opt-in and private; it is not yet recommended as
the demo fix. Any separate moving pilot still requires explicit approval. If
maintaining a TF2 overlay is undesirable, a bounded asynchronous readiness
design remains an alternative, but it must preserve exact capture-time sensor
and current-time base transforms and fail closed. No timing result authorizes a
moving trial.

In this initial probe, the earlier **63.083 ms** pilot gap and separate ~30.3
ms lookup events from runs 4–6 were not reproduced (the 50 Hz maximum here was
21.569 ms). The measured current-time TF wait was a strong root cause for the
recurring smaller stalls and a plausible contributor to the larger gaps, but
did **not** fully explain those exact outliers. Subsequent corrected-profile
and producer traces reproduced and localized the ~20–30 ms class; an archived
moving-pilot scan/command correlation below narrows, but does not close, the
63.083 ms event. Phase 5 stays **HOLD**; the fixed ten-trial recovery series
remains unstarted.

Current local verification passes **166 safety tests and 28 Phase 5
runner/series tests**; Python compilation and `git diff --check` also pass.
No private diagnostic pod or ConfigMap remains.

### October 19 private TF2 1 ms polling candidate: initial timing probe (superseded by matched-profile tests below)

To test the diagnosed fixed-poll floor without changing canonical runtime
behavior, a private candidate rebuilt only the advanced/two-time
`tf2_ros::Buffer::canTransform` polling interval from 10 ms to 1 ms. It used
geometry2 0.36.22 at commit
`62335b1e1506785a283ba121f451bb962e9b6db3`; the single-time overload, exact
requested timestamps, timeout, and fail-closed behavior were unchanged. The
patch was applied at image build time and the runtime audit verified that
Collision Monitor loaded `/opt/tf2-poll-overlay/lib/libtf2_ros.so` from that
overlay, rather than the stock library. Candidate image:
`image-registry.openshift-image-registry.svc:5000/semantic-navigation/semantic-safety@sha256:5dbe033ff0ef03805e359d7ee688c52535d9b2ccba91c96ffe9000070a310a5b`.

The run was the same private hotel/Nav2 fixture at 200 Hz odometry, with the
robot disarmed and stationary, no world recording, and no motion authority.
It recorded 82 successful exact-time TF lookup diagnostics above the 1 ms log
threshold. Their duration was **1.154–5.803 ms** (median **2.737 ms**, p90
**4.424 ms**, mean **2.881 ms**); none reached 8 ms. Every logged lookup
succeeded, and the target edge was present at the end-of-call check in all 82.
The stock 200 Hz comparison logged 466 successful lookups above its 8 ms
threshold, all **10.123–11.740 ms** (median **10.188 ms**, p90 **10.236 ms**,
mean **10.214 ms**). The logging thresholds differ, so these are distributions
of threshold-selected long calls, not all-call latency percentiles. Even with
that caveat, the candidate eliminates the fixed ~10 ms class in the observed
sample; it does not establish tail latency under other loads or explain the
separate historical 30.3 ms and 63.083 ms callback/output-gap events.

Measured Collision Monitor thread CPU averaged **0.220 ms per logged lookup**
versus **0.182 ms** in the stock comparison; the candidate median scheduler
run-queue wait was 12.5 μs and p90 was 423 μs. The candidate log showed a
median of four scheduler slices per lookup versus two in stock, consistent
with more frequent polling/wakeups. The container cgroup reported zero CPU
throttling during this run. This is encouraging but not a sustained-load or
power-cost qualification; the custom overlay must remain opt-in until repeated
resource and tail-latency measurements are reviewed.

The overall hotel suite still returned failure solely at the known
`settled_support_geometry` check: the floor collision was reported against the
robot base collision. The independent `native_never_armed_and_robot_stationary`
check passed, `clock_fault` was null, and console shutdown and private-resource
cleanup succeeded. Thus the **TF polling timing sub-experiment succeeded**, but
the hotel suite and Phase 5 gate did not pass. No moving pilot or canonical
deployment was performed. See the retained [run summary](cm-timing-tf2-poll-1ms-odom200-20261019/runtime/summary.json),
[Collision Monitor trace](cm-timing-tf2-poll-1ms-odom200-20261019/runtime/collision_monitor.log),
[runtime library identity](cm-timing-tf2-poll-1ms-odom200-20261019/runtime/collision-monitor-runtime.json),
[CPU evidence](cm-timing-tf2-poll-1ms-odom200-20261019/cpu-cgroup.txt), and
[cleanup record](cm-timing-tf2-poll-1ms-odom200-20261019/cleanup.json).

### October 19 matched stock-vs-1 ms comparison under controlled CPU load (initial profile)

The follow-up comparison used an ABBA order (stock, patched, patched, stock),
the same 1,000 μs logging threshold for both builds, 200 Hz odometry, the same
hotel fixture/base image, and a bounded two-worker CPU load. Each run was
stationary and disarmed, with no world recording or motion authority. The load
helper measured 1.886–1.899 CPU cores in use for approximately 45–46 seconds;
the container reported no throttling (`nr_throttled=0`,
`throttled_usec=0`). Runtime audits confirmed the intended stock or overlay
`libtf2_ros.so` was actually loaded in every run. Exact-time lookups succeeded
and the target transform edge was present at the end of every logged lookup.

| Arm | Logged lookups ≥1 ms | Median | P90 | P95 | Maximum | Mean |
|---|---:|---:|---:|---:|---:|---:|
| Stock TF2 | 149 | 10.187 ms | 10.269 ms | 10.537 ms | 13.682 ms | 10.208 ms |
| 1 ms poll overlay | 163 | 2.253 ms | 4.388 ms | 4.693 ms | 6.604 ms | 2.407 ms |

In this matched sample the overlay reduced the median by **77.9%**, P90 by
**57.3%**, and mean by **76.4%**. This is direct evidence that the stock
10 ms polling floor dominates the measured lookup latency when the requested
current-time transform arrives shortly after lookup begins. These are still
only calls selected by a ≥1 ms logging threshold—not all-call latency
percentiles, end-to-end command latency, or a moving-navigation qualification.

The measured Collision Monitor thread CPU per logged lookup averaged 180.3 μs
on stock and 208.5 μs on the overlay (+28.2 μs). Median scheduler slices rose
from 2 to 3; pooled overlay run-queue P90 was 780 μs versus 195 μs for stock.
Thus the latency improvement is clear, but the overlay adds polling/wakeup
activity and its sustained power/resource cost is not yet qualified. The
`cmdVelInCallbackStamped` callback-gap probe emitted no ≥20 ms events in these
four runs; it does not measure the separate historical checked-output gap, so
the prior ~30.3 ms and 63.083 ms events remained unresolved at the time. Later
corrected-profile probes directly reproduced the ~30 ms class; the 63.083 ms
event is narrowed, but not closed, by the archived moving-pilot correlation
below.

All four hotel suites failed only `settled_support_geometry` (floor collision
`floor_3::collision` against `base_collision`); the independent
disarmed/stationary check passed, `clock_fault` was null, and cleanup succeeded.
These invocations omitted the already-qualified private support profile
(`--rear-casters --physics-step 0.002 --lidar-range 12`), so they are useful as
an exploratory timing result but are **not** a valid geometry-qualified
comparison for the demo profile. An earlier stock attempt without a verified
contention-helper shutdown record is retained as
[stock-1](cm-timing-matched-stock-1-odom200-2cpu-20261019/runtime/summary.json)
but excluded from the ABBA statistics. See the four included records:
[stock-2](cm-timing-matched-stock-2-odom200-2cpu-20261019/runtime/summary.json),
[overlay-1](cm-timing-matched-poll1ms-1-odom200-2cpu-20261019/runtime/summary.json),
[overlay-2](cm-timing-matched-poll1ms-2-odom200-2cpu-20261019/runtime/summary.json),
and [stock-3](cm-timing-matched-stock-3-odom200-2cpu-20261019/runtime/summary.json).

The private candidate tag is restored to patched image digest
`sha256:7c38c0e243856d7402247f18745a64eb9a7706d8d117c3ec7f9b54d1d2635e75`;
the temporary stock build argument was removed from the BuildConfig. No
diagnostic pod/ConfigMap remains, and no canonical deployment or moving pilot
was changed/run. The corrected-profile comparison below supersedes this
exploratory result for any recommendation about the demo's qualified geometry.

### October 19 corrected-geometry stock-vs-1 ms comparison

The earlier ABBA used the default four-collision robot and default physics and
lidar settings. The contact gate correctly rejected chassis-floor contact; the
previous 10/10 baseline series had already established a different private
profile with rear ball supports, 2 ms physics, 12 m virtual lidar, and 200 Hz
odometry. To resolve the mismatch, two additional ABBA comparisons were run
using that exact profile, the same 1,000 μs log threshold and 200 Hz odometry,
the same hotel image base and pinned node. Both sequences were stock,
overlay, overlay, stock. One used the bounded two-worker CPU load; the other
had no added worker load. All eight runs were console-only, stationary and
disarmed, with no world recording or motion authority. The intended TF2
library was verified in each arm.

| Added CPU workers | Arm | Logged lookups ≥1 ms | Median | P90 | P95 | Maximum | Mean |
|---|---|---:|---:|---:|---:|---:|---:|
| None | Stock TF2 | 557 | 10.178 ms | 10.278 ms | 10.466 ms | 30.412 ms | 10.539 ms |
| None | 1 ms poll overlay | 649 | 6.538 ms | 9.243 ms | 10.041 ms | 26.641 ms | 6.109 ms |
| Bounded two-worker load | Stock TF2 | 516 | 10.177 ms | 11.795 ms | 20.272 ms | 20.900 ms | 11.110 ms |
| Bounded two-worker load | 1 ms poll overlay | 594 | 8.910 ms | 11.976 ms | 12.941 ms | 19.585 ms | 9.197 ms |

Without added workers, the overlay reduced median latency **35.8%** and P90
**10.1%**. Under the two-worker load, median improved only **12.5%** and P90
was **1.5% worse** than stock. Thus the 1 ms polling change does reduce the
stock polling floor, but its practical benefit is load-sensitive and does not
close the long tail. The current-time `odom → base_footprint` edge was observed
after lookup began at a median of about **5.7 ms** in the no-added-load arms;
the capture-time sensor edge was available much earlier. This preserves the
root-cause finding: fresh base TF publication age is a substantial part of the
wait, while TF2's fixed poll adds avoidable delay when the transform arrives
mid-wait.

The overhead is material. Mean Collision Monitor thread CPU per logged lookup
rose from **156.2 to 268.5 μs** with no added workers (+71.9%), and from
**157.8 to 280.3 μs** with the worker load (+77.6%). Median scheduler slices
rose from 2 to 7 without added load and from 2 to 9 under load. Under load,
run-queue P90 grew from 92 to 1,024 μs. Cgroups reported zero throttling in
all eight runs; this does not rule out runnable-thread scheduling delay. The
corrected-profile no-added-load runs later reproduced 20–32 ms callback gaps
and correlated the ~30 ms class with current-time TF lookup. This still does
not establish the cause of the historical 63.083 ms checked-output gap.

All eight runs passed `settled_support_geometry` with the exact allowlist, the
native disarmed/stationary check, runtime-library identity and clean shutdown.
No chassis/floor contact was accepted or exempted. Each run returned success;
the private resources were removed. No-added-load evidence: [stock 1](cm-timing-geometry-stock-noload-1-odom200-20261019/runtime/summary.json),
[overlay 1](cm-timing-geometry-poll1ms-noload-1-odom200-20261019/runtime/summary.json),
[overlay 2](cm-timing-geometry-poll1ms-noload-2-odom200-20261019/runtime/summary.json),
[stock 2](cm-timing-geometry-stock-noload-2-odom200-20261019/runtime/summary.json).
Bounded-load evidence: [stock 1](cm-timing-geometry-stock-1-odom200-2cpu-20261019/runtime/summary.json),
[overlay 1](cm-timing-geometry-poll1ms-1-odom200-2cpu-20261019/runtime/summary.json),
[overlay 2](cm-timing-geometry-poll1ms-2-odom200-2cpu-20261019/runtime/summary.json),
[stock 2](cm-timing-geometry-stock-2-odom200-2cpu-20261019/runtime/summary.json).

**Disposition:** the support-geometry failure in the earlier timing report was
a test-profile omission, not a new model defect; the corrected profile passes
here and was already used by the fixed 10/10 baseline series. A launcher guard
now requires the qualified support profile for future Collision Monitor timing
diagnostics. Keep the TF2 overlay private and opt-in: the measured gain under
load is too small and its CPU/wakeup cost too high to recommend it as the demo
fix. Next work should isolate base-TF production/scheduling under representative
load or test an asynchronous exact-time readiness path that preserves timeout
and fail-closed semantics. Do not substitute latest TF or reuse stale data.
Phase 5 remains **HOLD** for its other open gates, not for support geometry;
these stationary measurements authorize neither the recovery series nor a
moving pilot.

### October 19 TF producer trace: 20–30 ms stall stages localized

To split transform-buffer waiting from the upstream odometry/bridge path, a
second opt-in trace recorded each accepted odometry callback's wall and
monotonic receipt time, latest observed simulation-clock age, and TF
publication duration. The instrumentation does not change the odometry stamp
or synthesize transforms. One stock and one overlay run used the corrected
geometry profile, no added worker load, 200 Hz configured odometry, and the
same 1,000 μs TF diagnostic threshold. Both were stationary/disarmed, passed
the support gate, and shut down cleanly. These are diagnostic repeats, not
moving-output qualification.

The frame bridge captured 1,234 stock and 1,243 overlay TF publications. In
both runs, odometry headers advanced in 6 ms simulation-time increments;
wall receipt intervals were about 8.45 ms median (P90 10.56 ms) on stock and
8.52 ms median (P90 10.61 ms) on the overlay. At frame-bridge callback time,
the latest observed `/clock` was only 0–2 ms ahead of the odometry stamp. The
bridge's `sendTransform` call took 0.296 ms median (P90 0.488 ms, maximum
2.693 ms) on stock and 0.298 ms median (P90 0.485 ms, maximum 3.037 ms) on
the overlay. This rules out a tens-of-milliseconds delay inside the Python
frame-bridge callback in these samples; it does not independently timestamp
Gazebo publication or TF-listener insertion.

| Traced arm | Logged TF lookups ≥1 ms | Median | P90 | P95 | Maximum | ≥20 ms CM callback-start gaps |
|---|---:|---:|---:|---:|---:|---:|
| Stock TF2 | 282 | 10.178 ms | 10.224 ms | 10.383 ms | 20.326 ms | 3 |
| 1 ms poll overlay | 324 | 6.599 ms | 9.869 ms | 10.081 ms | 12.375 ms | 0 |

The stock run's three ~20 ms lookups are particularly diagnostic. The scan-time
source edge appeared within 0.10–0.92 ms, while the current-time base edge
appeared after 10.99–11.43 ms. The first frame-bridge TF message whose stamp
bracketed the requested current time was sent 9.38–11.12 ms after lookup start;
its own send call took 0.34–0.39 ms. The full stock lookup nevertheless took
20.26–20.33 ms, leaving about 9 ms after the target edge became queryable.
That remaining wait matches the pinned TF2 10 ms polling interval. In the
overlay run, the maximum lookup was 12.375 ms and its sampled target edge was
available at 12.343 ms; it returned as soon as the transform became
queryable, with no second ~10 ms quantization.

This confirms the two-stage cause of the recurring ~20 ms stalls: the
current-time transform is ahead of the newest buffered odometry TF and takes
roughly one wall-time odometry interval to arrive; stock TF2 can then sleep
through that arrival until its next 10 ms poll. The direct Nav2 path is
`Scan::getData → Source::getTransform → process → publishVelocity`; see the
pinned [Scan source](https://github.com/ros-navigation/navigation2/blob/1.3.13/nav2_collision_monitor/src/scan.cpp),
[Source transform code](https://github.com/ros-navigation/navigation2/blob/1.3.13/nav2_collision_monitor/src/source.cpp),
and [Collision Monitor process path](https://github.com/ros-navigation/navigation2/blob/1.3.13/nav2_collision_monitor/src/collision_monitor_node.cpp).
The prior 30.412 ms lookup is consistent with the same mechanism plus a later
target-edge arrival: its edge probe reached the exact-time transform at 23.039
ms and the lookup returned at 30.412 ms; `getData`, full callback, and next
callback start took 31.328, 31.595, and 31.674 ms respectively. A patched
repeat likewise waited 26.613 ms for its target edge and returned at 26.641 ms.

**Limit:** these private timing fixtures keep the robot disarmed. They can
measure Collision Monitor callback gaps but cannot qualify active checked
velocity continuity: stationary zero output is intentionally suppressed after
`stop_pub_timeout`. The ~30 ms single-callback mechanism is now directly
reproduced. The archived moving-pilot correlation below ties the historical
63.083 ms checked-output gap to a delayed scan arrival and elevated Gazebo
main-thread run-queue wait over the enclosing sample window, but the sparse
resource samples and lack of in-pilot callback/TF probes do not establish
causality or partition the exact gap. A separately approved moving-output
trace is still required. No new moving pilot or canonical deployment was run.

### Archived moving-pilot correlation: 63.083 ms output gap narrowed, not closed

The retained failed moving pilot
([commands](recovery-console-pilot-1-20261019/runtime/commands.json),
[sensor timing](recovery-console-pilot-1-20261019/runtime/timing-events.json),
[resource samples](recovery-console-pilot-1-20261019/runtime/resource-samples.json))
allows one useful cross-stream correlation without rerunning the robot. The
checked-command source timestamps around the reported gap are
`1792417143424692174` and `1792417143487774729`, a **63.083 ms** interval. A
scan stamped 7.6 s simulation time arrived at
`1792417143468388695`, inside that interval: 43.697 ms after the preceding
checked command and 19.386 ms before the next. The adjacent scan receipts were
178.375 ms apart for a 100 ms simulation-stamp advance; the following pair
were 208.435 ms apart for another 100 ms advance. Thus the scan stream was
advancing at substantially less than wall-time real time during this segment,
and the next checked command followed the scan receipt by about 19.4 ms.

The 63.083 ms interval falls inside two resource snapshots 206.389 ms apart.
Across that broader window, Gazebo's main thread accumulated **86.896 ms CPU
execution and 67.696 ms run-queue wait**; Collision Monitor's main thread
accumulated **4.451 ms CPU and 8.132 ms run-queue wait**. The cgroup reported
no CPU-quota throttling. This makes upstream simulator scheduling/scan cadence
a credible contributor and argues against attributing the full gap to
Collision Monitor main-thread scheduling alone. It does not prove that the
67.696 ms Gazebo wait occurred inside the exact command gap: the scheduler
counters are cumulative over a window more than three times as long, and the
pilot had no per-scan TF-readiness or Collision Monitor callback-duration
probe. The 19.386 ms scan-to-next-command interval is consistent with the
separately reproduced current-time TF wait, but is not itself a transform-wait
measurement.

**Updated root-cause assessment:** the ~20–30 ms class is localized to waiting
for a future exact current-time base transform and, on stock TF2, its 10 ms
poll cadence. For the historical 63.083 ms event, existing evidence now points
to an upstream scan/simulator cadence disturbance with a possible additional
exact-time TF wait or scheduling delay; it cannot distinguish one compounded
stall from multiple delays. Do not ship the 1 ms TF2 overlay as a fix: its
corrected-profile benefit is load-sensitive and its CPU/wakeup cost is high.
Preserve exact-time transforms and fail-closed behavior. **At the time of this
archived pilot analysis**, the recommended next step was a moving trace with
scan receipt, exact-time transform readiness, Collision Monitor callback
entry/exit, checked-output publication, and scheduler evidence on a common
monotonic clock. The corrected October 20 trace below later captured these
signals and directly reproduced the late-exact-TF mechanism for a 53.150 ms
gap. It strongly explains the mechanism class behind the historical 63.083 ms
gap, but does not replay that exact event. The new trace also failed its guarded
recovery subgates, so Phase 5 remains **HOLD**.

### October 19 moving-timing attempt stopped by profile preflight; no motion

The first authorized one-shot attempt is retained at
[moving-timing-trace-1-20261019](moving-timing-trace-1-20261019/). The pinned
console candidate digest was
`sha256:7c38c0e243856d7402247f18745a64eb9a7706d8d117c3ec7f9b54d1d2635e75`.
Native unit tests, frame-bridge verification, adapter verification, and native
lease tests completed successfully, but `verify_hotel_stack.py` rejected the
profile before it generated assets or launched Gazebo/Nav2. Consequently there
is no moving trace, no scan/TF/Collision Monitor timing evidence, and no new
information about the 63.083 ms output gap.

**Cause:** the launcher serializes parsed float arguments with `str()`, so the
manifest correctly contains `PHASE5_LIDAR_RANGE=12.0` and
`PHASE5_ODOM_FREQUENCY=200.0`. The in-container guard incorrectly compared
those strings to `"12"` and `"200"` (the physics value `"0.002"` matched).
This was a representation-only mismatch, not a geometry/profile mismatch.
The runtime guard now compares parsed numeric values against the exact
qualified tuple `(0.002, 12.0, 200.0)` and has regression coverage for both
integer-looking float encodings and changed/missing values. The summary also
records `moving_timing_trace` explicitly and marks the run diagnostic-only.

The fixture pod and ConfigMap were both deleted successfully (return code 0);
the existing camera, simulator, and router deployments were not modified. The
attempt directory retains the manifest, build identity, test output, and
cleanup evidence. Local verification now passes 169 semantic-safety tests and
30 Phase 5 launcher tests, plus Python compilation and `git diff --check`.
This preflight failure did not count as a motion trial or a Phase 5 pass. It was
superseded by the corrected, separately approved October 20 trace below; the
preflight-only attempt itself remains retained as historical evidence.

### October 20 moving trace: 53 ms output gap directly tied to late exact-time TF

The corrected, one-shot guarded trace is retained at
[moving-timing-trace-2-20261020](moving-timing-trace-2-20261020/). It ran with
the pinned console candidate, stock TF2, no world recording, the fixed 2 ms /
12 m / 200 Hz geometry profile, and the explicit BackUp–Wait–FollowPath probe.
Its summary is diagnostic-only and failed the guarded recovery subgates; it is
not a Phase 5 pass.

**Directly reproduced timing chain:** among admitted moving `checked` outputs,
the largest gap was **53.150 ms**, from source wall timestamp
`1792503064164432849` to `1792503064217583330`. The Collision Monitor log
brackets that same interval with a **51.986 ms** exact-time TF lookup, a
**53.017 ms** full callback, and a **53.085 ms** next-callback gap. The lookup
was for scan stamp 8.3 s at target time 8.5 s. The scan/source transform was
ready after 0.563 ms, but the exact current-time `odom → base_footprint` target
edge did not become available until **44.993 ms** into the lookup. It returned
about 6.993 ms after that edge became ready, consistent with stock TF2's
polling cadence. Inside the lookup, the CM thread used 0.250 ms CPU and accrued
1.539 ms run-queue wait; the wait was not 52 ms of CM computation or runnable
CPU starvation.

The producer trace locates the missing edge upstream of `sendTransform`: the
frame bridge received odometry stamp 8.496 s at wall time
`1792503064152226548`, then stamp 8.502 s at
`1792503064207864480`—a **55.638 ms receipt gap for only 6 ms of simulation
time**. The latter TF send took 0.321 ms. A scan stamped 8.4 s arrived during
the CM callback, at wall time `1792503064203459491`. Thus the output gap is
directly explained by a late future odometry/TF sample, not by slow transform
broadcasting; the 10 ms TF2 poll contributes only the short tail after the
edge arrives. This reproduces the same mechanism class as the earlier
63.083 ms pilot gap, although it does not retroactively prove that individual
historical event had the identical sequence.

The guarded stop then behaved fail-closed. The last admitted checked command
used a conservative native capture bound of `1792503064131438109`; by its
source timestamp it was already **86.145 ms** old, leaving only **11.855 ms**
inside the 98 ms effective capture window. For the following scan at 8.5 s,
the capture bound was `1792503064147142438`, giving an effective deadline of
`1792503064245142438`. Its next checked output was processed at
`1792503064245156634`, **14.196 μs after that deadline**, and was rejected as
`source_rejected_or_expired`. Permission was revoked for `command_expired`;
the native watchdog applied zero within **1.936 ms** of the first trigger. The
robot displaced only 0.02993 m,
below the 0.20 m evidence minimum; BackUp was canceled and Wait was never
reached. The full summary also records a later `native_capture_stale` fault:
the physical sample was 98.371 ms old at publication and 100.569 ms old when
processed, just beyond the strict 100 ms limit. A separate later TF lookup
lasted 137.693 ms, with the target edge appearing at 136.555 ms. These later
events further show simulator/clock freshness trouble, but occur after the
command-expiry stop and are not the cause of the initial 53 ms gap.

**Root-cause assessment and remedy:** the immediate cause of the reproduced
gap is a synchronous Collision Monitor wait for a future exact-time TF edge;
the upstream symptom is delayed odometry arrival / slow simulation-time
progress. The producer probe begins at frame-bridge receipt, so it cannot
distinguish Gazebo publication delay from transport or bridge-delivery delay;
Gazebo-side source-publish timestamps were not captured. Faster TF2 polling
alone is not the remedy: it could save roughly 7 ms here but cannot remove the
44.993 ms until the target edge exists. During the gap, cgroup `nr_throttled`
and `throttled_usec` did not increase; the container limit was 8 CPUs and its
sampled use was below that limit. The probe was scheduled on
`ip-10-0-53-174`, the same node as the persistent hotel simulator. A post-run
node snapshot (not time-matched to the event) showed 91% CPU use, with that
simulator using 9.269 cores despite requesting 1 CPU. This makes node
contention / simulator load a credible contributor, not a proven exclusive
cause: node-level run-queue and Gazebo source-publish timestamps were not
captured for the event.

For the demo, first avoid co-locating two CPU-heavy Gazebo instances and give
the persistent simulator realistic CPU requests or dedicated placement; then
verify odometry receipt cadence and real-time factor under the intended load.
Keep the existing capture-age, command-lease, and stop thresholds unchanged.
If delayed exact-time TF remains after isolating simulation load, prototype a
nonblocking exact-time readiness path that stops safely on deadline; never
substitute latest/stale TF. The historic 63.083 ms event is now strongly
mechanistically explained, but its exact per-event attribution remains
retrospective rather than directly replayed. Phase 5 stays **HOLD** because this
motion trial expired and did not complete the recovery task.
