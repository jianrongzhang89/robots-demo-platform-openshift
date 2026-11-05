# Session handover — G5 safety and operations

G4 remains accepted. G5 is **HOLD**, not accepted. Read `report.md`,
`gate-result.json` and `operator-runbook.md` revision 3 before continuing.
Do not resume the paused G4 paired-series campaign.

## Completed evidence

- Registry model 3/version 4/artifact 2 registered and read back exactly; repeated
  registration is idempotent. Three stopped replay update/rollback cycles passed.
- CA/server/client rotation passed, retired/missing credentials rejected, monitor
  principal cannot infer, dependency isolation passed with reachable controls.
- Actual serving-pod loss during verified motion: `pod-loss-5/result.json` and
  `attribution.json` PASS. Applied zero 1.266446 ms after the native freshness
  trigger; stationary 885.254230 ms; no automatic resume over 482 native samples.
- Wrong response version during verified motion: `wrong-version-1/result.json`
  PASS on its first attempt. Applied zero 0.912384 ms after the trigger;
  stationary 848.010457 ms; no automatic resume over 476 native samples.
- Original 500 ms freshness / 100 ms applied-zero thresholds and native evaluator
  unchanged. These are observation-only semantic safety fixtures, not a new G4
  navigation campaign or qualification of the metrics candidate for motion.
- Perses dashboard `redhat-ods-monitoring/semantic-g5-serving` has 21 panels.
  Six serving data sources and live navigation capture/result, drops, RTF and
  supervisor series verified through authenticated Thanos queries. Passive
  navigation exporter has no ROS connection, token, GPU or egress access.
- Stationary costmap telemetry: `costmap-telemetry-3/correlation.json` PASS, all
  254 results matched in both maps (100% coverage, no capture/stream mismatch).
  Attempt 1 lacked CPU capacity; attempt 2 lacked the required socket buffer.
  Attempt 3 uses the already tuned rendering worker for CPU-only consumers;
  images, requests and DDS settings are unchanged. This is not G3 requalification.
- Expired sources: `navigation-unavailable-verification.json` PASS, all four
  availability indicators zero and all state/latency series absent.
- Capture-stream RTF across fault/recovery: 0.6736 pod loss, 0.6786 wrong version.
  These windows are not the three ten-minute G3 runs. See `rtf-audit.json`.
- 14 focused operations/telemetry/attribution/preflight tests pass, in addition to
  the retained 22 server and 42 shared-perception regression tests.

## Current runtime and constraints

- Accepted serving digest `f9bcc273…` remains active. Candidate `af5cb732…` is
  stopped-replay qualified only; its histogram panels are absent on the baseline.
- Current platform is OpenShift AI 3.5.2 / OCP 4.21.16. Historical records retain
  their original versions. Re-audit timing for a changed moving configuration.
- `sam3-g0-issuer` holds the G5 CA. Server/replay leaves expire November 11 around
  14:14 UTC; monitor expiry is recorded separately. Use this issuer for any future
  fault proxy, and reissue the monitor certificate after another CA rotation.
- Monitor URI `spiffe://semantic-model-serving/sa/g5-monitor` maps to `[]`
  inference permissions; ingress is limited to user-workload Prometheus.
- The retained exporter intentionally reports sources unavailable after sampling
  ends. Its ten-second dashboard TTL does not change the safety threshold.

Final restoration: `preflight-safety-final.json` PASS and
`cleanup-safety-final.json` confirms no temporary G3/G4/native fixture or proxy
resources remain. Rendering reservation/local SAM3 are Ready, hotel-sim is zero,
and the accepted serving image remains Ready. Monitoring/exporter resources are
intentional deliverables. No sampler or fault trial remains active.

## Attempt history and continuation rules

Never overwrite attempt directories. `pod-loss-1` found a stale fixture ConfigMap;
attempt 2 used deletion grace too long for the verified-motion window; attempt 3
was a documented zero-packet, never-armed setup timeout; attempt 4's extra CLI reads
delayed deletion until normal stopping. All remain unsuccessful. Attempt 5 removes
the injection-path delay and proves deletion preceded the safety stop in the
fixture clock. Do not compare host and fixture wall timestamps directly.

`g5_prearm.py` only permits explicitly complete zero-packet/disarmed setup evidence
with no results/events and no failed existing check; missing evidence rejects.
The original G4 classifier is unchanged. No armed failure was relabeled or retried
under the same protocol. `dependency-isolation-1.json` and the initial navigation
collection/check are also retained unsuccessful/exploratory evidence.

The browser tool returned **No browser is available** (`dashboard-browser-check.json`).
API checks do not prove visual usability or evidence-link navigation. A new presenter
must execute the full revision-3 protocol, including explicit recovery/resume, then
record identity, date, commands and evidence. Presenter identity and user acceptance
remain unset. Do not promote G5 from this implementation session alone.

## Subsequent user-viewed navigation demo

`navigation-demo-on-2/report.md` records a completed served semantic-on presentation
after explicit user “go”: original fixture PASS, no unexpected contacts, zero
red-mat hull exposure, and successful cleanup. Physical arrival was 0.727 m from
the requested goal despite Nav2 success; retain the G4 localization caveat.
Attempt 1 remains a failed, never-armed presentation setup. The optional
`--operator-demo` viewer/hold extension is not a new gate qualification.
See `preflight-after-navigation-demo.json` for the latest restored state.

## Navigation rerun 3 and presentation corrections

`navigation-demo-on-3/report.md`: fixture PASS and cleanup PASS; zero mat hull
exposure, no unexpected contacts, capture-age p95 250.267 ms, no clock fault.
Physical goal offset remains 0.812 m despite Nav2 success. Final restored-state
check: `preflight-after-navigation-demo-3.json`.
The user identified the smaller fixture mat and choppy viewer; follow-up restores
the standalone 1.2 × 1.95 m mat for operator presentations only and investigates
viewer rendering. G5 remains HOLD.

### Presentation fixes, run 4 (live)

`navigation-demo-on-4/SESSION-HANDOVER.md` owns the active held presentation.
Historical D2 mat restored to 1.2 × 1.95 m for operator demos only. Viewer
changed from OGRE2/one CPU (~1.25 FPS) to OGRE/three CPUs (~21 FPS), with smaller
viewport and no anti-aliasing. Original GPU sensor renderer is unchanged.
Navigation validation is pending the user's viewing-ready release. See the
run's `presentation-fix-report.md` and `viewer-diagnosis/`.

### Viewer availability correction — run 5

Run 4 closed before navigation when the resource sampler hit its original
20,000-sample cap (~400 seconds); cleanup passed and removed the viewer route.
User could not open noVNC for that reason. `resource_probe.py` now accepts a
bounded sample capacity; operator presentations request 65,000 samples to cover
the 1,300-second pod lifetime. Default qualification capacity stays 20,000.
A test crosses the old limit and verifies capacity metadata. Run 5 starts with
the persisted wide-mat/faster-viewer fixes and requires a fresh viewing-ready
release. See `navigation-demo-on-5/SESSION-HANDOVER.md` for active state.

### Run 5 closed: wider-mat navigation unresolved

`navigation-demo-on-5/report.md`: navigation FAIL, cleanup PASS. Viewer median
20.97 FPS and restored 1.2 × 1.95 m geometry verified. Native first fault
packet_invalid caused native_session_lost; 103.292 ms native_capture_stale came
later. Conservative hull exposure 0.331 m / minimum clearance −0.055 m means
this is not acceptable mat avoidance despite no physical contacts. The robot
stopped; serving timing passed. No automatic rerun. See
`preflight-after-navigation-demo-5.json` for restoration verification. G5 HOLD.

Final restoration preflight PASS: `preflight-after-navigation-demo-5-settled.json`. Initial post-cleanup check caught a terminating router and remains HOLD evidence. Native zero applied 4.322 ms after packet-invalid trigger.

### Recording rerun 6 — held ready

User requested another run for recording. Active wrapper session 73979;
`navigation-demo-on-6/SESSION-HANDOVER.md` owns state. HTTPS/WebSocket/RFB verified,
viewer ~21 FPS, robot held disarmed with zero commands. Await fresh user “go”.
Run 5's navigation failures remain unresolved; this is an explicitly requested
rerun with unchanged wider-mat presentation settings, not new qualification.

### Recording rerun 6: early stop confirmed

`navigation-demo-on-6/report.md`: navigation FAIL after fresh user release.
Native first fault lease_expired → native_session_lost; zero applied in 1.992 ms.
No clock fault; serving timing passed. Physical goal distance 2.265 m, viewer
median20.86 FPS; conservative hull exposure0.121 m / clearance−0.006 m.
User noticed early stop and was informed of the command-renewal timing failure.
No automatic retry. Check run6 result/preflight for cleanup state. G5 HOLD.

Run6 cleanup/restoration verified: settled preflight PASS (`preflight-after-navigation-demo-6-settled.json` in S5). Initial check observed the terminating router and remains retained as HOLD. G5 acceptance status remains HOLD.

## Root-cause investigation after run 6

See `lease-renewal-investigation/report.md` and reproducible analysis/replays.
Run5 confirmed deterministic same-source grace-reset defect: repeated checked
command withdraws 25 ms grace, emits 1.08445 ms lease that native receiver must
reject against its 2 ms allowance; actual Python and C++ guard reproduced it.
Run6 renewal sent only 1.079 ms before previous native expiry after 11.807 ms
guard-stage interval; receive/acceptance lost the deadline. No per-packet native
receive/lock timings exist, so exact scheduler-vs-mutex split is unproven.
Viewer load is a plausible contributor, not an isolated causal result. All
armed fixture intervals have zero quota throttling; serving timing passed.
No control-policy code changed or new navigation launched in investigation.
Corrective directions and validation requirements are in the report. G5 HOLD.

## Lease renewal correction implemented; run 7 closed

See `lease-renewal-fix/report.md`: 237 safety tests PASS; 4 regressions fail on
old code and pass with fix. Preserve same-source granted grace, apply proven
grace before forwarding, fail closed on inadmissible short lease, prioritize
full guard ahead of observers and retain fine timing evidence. Safety constants
unchanged. Run 7 received explicit user release and ended on a distinct
`native_capture_stale` fault; see `navigation-demo-on-7/report.md`. Cleanup and
settled G5 preflight passed. The G5 presentation goal is now moved to
`(19.2, -32.4)`, a free landing point beyond the mat's far x edge near the
observed stop; general Phase 6 defaults are unchanged. Navigation completion,
the capture-processing backlog correction, and wider-mat clearance remain
unproven. G5 HOLD.

## Run 8: adjusted-goal presentation

`navigation-demo-on-8/report.md`: user released the fresh token after checking
noVNC. The fixture and cleanup passed; Nav2 returned `goal_succeeded` at the
adjusted far-side goal. No unexpected contacts; minimum physical hull clearance
was 0.152 m. Native applied zero followed completion in 2.73 ms, with confirmed
stationary in 531 ms. The physical pose at Nav2's goal-success timestamp was
0.735 m from the requested goal, so this does not establish physical arrival
within tolerance. The active-motion command mapping had no clock fault; a
`native_capture_stale` event occurred only in the idle tail after the completed
stationary/contact window. G5 remains HOLD. Post-run G5 preflight PASS:
`preflight-after-navigation-demo-on-8.json`.

## Run 10: stopped short and ingress timing correction

`navigation-demo-on-10/report.md`: navigation FAIL, cleanup PASS. The robot
stopped 1.427 m from the adjusted far-side goal with `command_expired`. A raw
capture initially lacked its native clock bracket; its next join attempt came
21.6 ms after receipt and exceeded the existing 20 ms join bound. The matching
checked command then had no raw ledger source; a subsequent valid renewal was
handled 2.8 ms beyond the gate grace deadline. No clock fault or unexpected
contact occurred, and native zero was applied within 0.687 ms of watchdog
trigger. Post-run settled preflight passed. `HotelGuardAdapter.command()` now
drains the bounded joiner immediately after validated raw/checked ingress,
while retaining the observer-tick drain and all existing capture/freshness
limits. `git diff --check` passed; tests and a follow-up live run have not been
performed. G5 remains HOLD pending a new explicitly released run.

## Recording demo reruns 11 and 12

Run 11 stopped before navigation because the newly added immediate drain called
`timings` on the installed adapter test double. See
`navigation-demo-on-11/report.md`. The ingress callback now skips the immediate
drain for joiner stubs without a `drain()` method; run 12's installed adapter
regression suite passed all 10 tests.

Run 12 reached the operator hold with a viewable noVNC route, was released by
the user, and then stopped under native status reason
`native_lease_margin_exhausted`. Captured pose `(18.657, -33.401)` was 1.139 m
from goal `(19.2, -32.4)`. The failed fixture pod ended before its full runtime
summary/trace could be retrieved, so packet-level root-cause attribution is
incomplete. Cleanup restored the rendering reservation and removed the route;
settled G5 preflight PASS is retained as
`preflight-after-navigation-demo-on-12.json`. See
`navigation-demo-on-12/report.md`. The ingress correction is not validated as
a fix for this distinct watchdog stop. G5 remains HOLD.

## Recording demo rerun 13

`navigation-demo-on-13/report.md`: noVNC readiness and disarmed hold were
verified before the user's release. The robot moved, then the guard revoked
with `command_expired`; the native status later showed `lease_expired`. Final
settled pose was 1.116 m from the goal. Native zero was applied 1.910 ms after
the trigger; there was no clock fault and the contact audit was clear. The
ingress drain correction was active, but the same command-expiry stop remains
unresolved. Full runtime trace and join diagnostics are retained in the run
directory. Cleanup and settled preflight passed. G5 remains HOLD.

## Navigation completion fix — verified runs 20 and 21

User requested root-cause correction and verification after run 13. See
`navigation-completion-fix/report.md`, `investigation.json` and
`verification.json`. The callback pump now services commands and the guard
between observer callbacks, and ordinary navigation no longer scans the
growing Wait-event history. Run 17 proved navigation completion but exposed
a 1.425 m AMCL-to-physical mismatch against wheel odometry's 0.021 m error.
The opt-in presentation restores the historical fixed spawn map origin with
wheel odometry; AMCL no longer broadcasts map TF in this mode. The goal is
directly opposite spawn across the mat at `(19.4008, -31.594)`, with position-only
completion. The wrapper additionally requires physical arrival within 0.20 m
and a stationary disarmed endpoint beyond the far mat edge.

Runs 20 and 21 both passed with `goal_succeeded`, stopping 0.086598 m and
0.086892 m from the physical goal. Cleanup passed for both. 238 safety unit
tests, 11 installed adapter checks, and 5 physical endpoint checks passed.
All intermediate attempts remain retained, including failed corrections.
The final restoration check is `preflight-after-navigation-completion-fix.json`.
Native capture-stale events occurred only after completion in the idle tail;
active-motion mapping passed. Conservative hull clearance was about 0.0467 m,
below the historical 0.10 m target, so broader G5 acceptance remains HOLD.
The requested demo goal-arrival failure is corrected and verified; no demo
or noVNC route remains active after cleanup.

## User-viewed rerun 22

The user checked noVNC and explicitly released run 22. Navigation and physical
endpoint checks passed: `goal_succeeded`, stationary 0.086919 m from the goal
on the opposite side of the mat. No unexpected contacts or active-motion
clock fault. Cleanup passed; restoration is recorded in
`preflight-after-navigation-demo-on-22.json`. See `navigation-demo-on-22/report.md`.
No demo/noVNC resources remain active. Broader G5 acceptance remains HOLD.

## User-viewed rerun 23

The user released run 23 after noVNC was ready and the fixture was confirmed
disarmed. Navigation completed with `goal_succeeded`; independent physical
endpoint acceptance passed at `(19.33727, -31.53497)`, 0.08672 m from the
far-side goal, stationary and clear of the mat edge. Cleanup removed the
fixture and noVNC route and restored the rendering reservation. The immediate
post-run preflight saw G4 pods during teardown and reported HOLD; after
teardown settled, `preflight-after-navigation-demo-on-23-settled.json` passed.
G5 overall remains HOLD on broader acceptance criteria. See
`navigation-demo-on-23/report.md` and its retained `trial/` evidence.

## User-viewed rerun 24

The noVNC route was HTTP 200 and the user released run 24 from its fresh,
verified disarmed hold. Navigation completed with `goal_succeeded`; physical
endpoint acceptance passed at `(19.33718, -31.53489)`, 0.08684 m from the
far-side goal, stationary and clear of the mat edge. Cleanup removed the
fixture and noVNC route and restored the rendering reservation. The first
settled preflight observed the G4 router pod terminating; after it disappeared,
`preflight-after-navigation-demo-on-24-final.json` passed. G5 overall remains
HOLD pending broader acceptance criteria. See
`navigation-demo-on-24/report.md` and its retained `trial/` evidence.
