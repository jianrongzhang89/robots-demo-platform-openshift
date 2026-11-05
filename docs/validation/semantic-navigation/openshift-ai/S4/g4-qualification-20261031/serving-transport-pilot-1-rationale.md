# Serving-transport pilot 1: lease-evidence latency fix

November 1, 2026. Candidate change and rationale for the isolated
serving-unavailable pilot run by `scripts/semantic-navigation/run_g4_serving_pilot.py`
into `serving-transport-pilot-1/`.

## What changed

Two fixture-side source files, both delivered to the fixture pod through the
per-trial `semantic-phase5-native` ConfigMap (the pinned fixture image digest
`sha256:348fc584e70b07c6f73f9e428623240da5fc4c81ead630f0cb051c18de2d4371` and
every binary it carries are unchanged):

- `apps/semantic-safety/sam3_observer_worker.py`
  (attempt-3 sha256 `460aef432d6613367855e233d8acab7016068734f31492dd2c0f1266a7215b22`
  → `f1b7a11c8ceddb2b4d9b17bc5b6717133d7eb998389a0d00d20c1c2a8a42bd22`):
  in served topology only, `on_timing` writes its status file immediately
  when a renewed semantic lease lands, instead of waiting for the pump loop's
  10 ms write cadence. The loop's cadenced writes are unchanged.
- `apps/semantic-safety/verify_hotel_stack.py`
  (attempt-3 sha256 `b2006fe1ff66e83d071af088646cb759e8aea10ebdeef916b180c182fa4e3c5a`
  → `170ec957ddffdb9e5f8d1fc7062fda522636c77b94a63c04809ccd9291ff5e9e`):
  the supervisor's `semantic_lease_poll` read throttle drops from 20 ms to
  5 ms.

## Why

The attempt-3 trial-10 armed failure (`semantic_stale` before
`motion_verified`, 503 never injected) was a lost lease-renewal race, not an
inference outage and not a host-polling miss; see the attempt-3 diagnosis in
[../../report.md](../../report.md). The renewal chain for the semantic lease
runs capture → adapter result (~190 ms typical, 268 ms under the observed
load transient) → observer-worker receipt (+30–40 ms) → worker status-file
write (10 ms cadence) → supervisor poll (20 ms granularity) → `gate.observe`,
against the unchanged 500 ms capture-age authority measured from the capture
wall. The measured observer-side margin was median ≈ 84–86 ms with p10 ≈
50–68 ms in passing and failing trials alike; the final ~15–30 ms of plumbing
comes out of that. Trial 10 lost by milliseconds: the renewing result was
worker-received 16.4 ms before the previous capture's deadline, and the
write+poll hop did not reach the gate in time.

The change removes ~15–25 ms from exactly that final hop. It touches no
acceptance criterion: the 500 ms freshness trigger, the 100 ms zero-command
deadline, fault semantics, stop reasons, watchdog binaries, thresholds,
model/server identity, geometry and calibration are all unchanged. The
evidence content is identical — the same lease records reach the same gate
through the same `observe` contract, only sooner.

## Pilot 3 addendum: deadline-aware fast poll (November 1, later)

Qualification-4 (`qualification-4/`) validated the transport fix — six serving
trials passed, including a complete serving-unavailable trial with real 503
wire proof — but trial-07 (auth-r2) lost a thinner instance of the same race:
the renewal reached the worker +4.5 ms before its capture-age deadline, and
the supervisor's 5 ms poll phase (bounded below by the ~3–6 ms `pump()`
period driven by `until()`'s 3 ms sleep) missed the window by ~0.2–0.8 ms.
The compression came from an acceleration-window backend spike (169 ms vs
138 median, model-server side) plus a zenoh delivery spike (60 ms vs ~35),
both in pinned components; the fixture container was at ~3.4 of 8 cores.

The follow-up is scheduling-only and lives in `verify_hotel_stack.py`
(sha256 `bad0d24fe0d1f6ebe9768d65c40732e6845ca304ede5e9b9e1a408dab27eed8c`):
`semantic_lease_urgent()` is true only while the newest armed semantic lease
is within 40 ms of its capture-age deadline — which normal renewals (landing
50–80 ms early) never trigger — and while urgent, `semantic_lease_poll`'s
throttle drops to 1 ms and `until()` sleeps 0.5 ms instead of 3 ms, so a
last-instant renewal reaches the gate within ~2 ms of the worker's write
instead of ~4–6 ms. The 500 ms freshness contract, the 100 ms zero-command
deadline, stop reasons and every threshold are unchanged, and the extra pump
load occurs only during the rare, brief windows where a renewal is already
late. The late-success dwell loop's 3 ms cadence is deliberately untouched:
it is disarmed (urgency cannot fire) and its cadence is load-bearing against
a documented ingest-lag false latch.

## Qualification-5 addendum: hardened restore path (November 1, latest)

Qualification-5 (`qualification-5/`) stopped on trial-02 (wrong_version). The
fault itself behaved correctly — injection at `motion_verified`, a real
tampered-identity 200 on the wire, qualified `semantic_stale` stop 1.923 s
later, zero command within 0.31 ms — and trial-01 (auth) passed, so both
lease-transport fixes are holding. The failure was the post-restore
late-success check: the runner's restore for wrong_version deletes and
recreates only the adapter pod, and the fixture-side zenoh bridge
intermittently failed to re-bind its Zenoh→ROS routes for the semantic
topics to the new participant. Retained proof: the worker's camera lease
kept advancing to trial end (forward path fine), the recreated adapter
emitted 572 valid results with a live 20 Hz status publisher, yet the
worker's `semantic` and `inference_heartbeat` leases froze at the old pod's
last values — no semantic topic ever re-crossed. The identical restore
passed in qualifications 3 (twice) and 4, so the re-bind is a race, the
zenoh-bridge 1.5.0 issue-368 class on participant churn. The trial also
exposed an evidence bug: `run_g4_faults` collected the adapter pod's bridge
log under `sam3-zenoh-bridge.log`, overwriting the fixture bridge's log of
the same name collected by `run_phase5_native`.

The hardening (harness-only; no gate, deadline, fault semantic or threshold
touched):

- `g4_topology.recycle(fault_proxy)`: the recycle now takes the proxy flag so
  a recycled topology keeps the loopback injector in the serving path.
- `run_g4_faults.py`: the wrong_version/process_loss/transport_loss restore
  now recycles pod **and router** — both bridges rebuild their routes from
  clean router state instead of relying on incremental participant-churn
  re-binding — and `wait_semantic_flow()` proves end-to-end recovery (the
  fixture supervisor's semantic lease sequence advancing past the
  pre-restore baseline) before the restore is considered complete; a
  missing flow is recorded in the injection log and the trial then fails
  through its own late-success check. The adapter pod's logs are collected
  as `adapter-*.log` so the fixture bridge's log is retained.
- `semantic_fault_probe.py`: the served-mode late-success wait extends from
  120 s to 240 s to cover the router-recycling repair time. This is
  observation patience for the late-success proof, not a safety deadline —
  a longer window only gives a spurious resume more time to show.

A wrong_version pilot (`serving-transport-pilot-4/`) gates this before
qualification-6, exercising exactly the recycle-and-verify restore path.

**Pilot-4 result and correction.** The pilot failed and proved the
router-recycle approach strictly worse: with the router replaced, the
fixture bridge reconnected and exchanged announcements with the new adapter
bridge (mutual discovery 23:15:38) but created **zero** routes afterward —
its routes manager does not rebuild after a zenoh session drop — so both
directions were dead (the replacement adapter emitted no results; the
worker's semantic and heartbeat leases froze at the old pod's last values).
The retained bridge logs (the collision fix made both sides visible for the
first time) also clarify the original intermittent failure: it is an
announcement/retirement ordering race. The restore now force-kills the old
pod, waits out the retirement propagation (zenoh liveliness lease 10 s;
20 s settle), and only then creates the replacement — making
retirement-first deterministic — followed by the same
`wait_semantic_flow()` end-to-end proof. Pilot 5
(`serving-transport-pilot-5/`) gates the ordered restore.

## Qualification-7 addendum: 30 simulation-Hz camera candidate (November 2)

With the adapter node freed (user-approved scale-down of the leftover
Phase-3-era `semantic-hotel-sim`, recorded in `qualification-7-setup.json`),
qualification-7 passed 11 of 12 serving-fault trials — including both
wrong_version ordered restores and both serving repeats — with 275
healthy-window renewals at minimum margin 79.3 ms and median 112 ms.
The single failure (trial-12, hang-r2) was an isolated ~100 ms coincident
jitter event inside the pinned adapter/model path during the first second
of armed motion: model upstream +30 ms, adapter body-write stall +12 ms,
internal queueing +50 ms compounding, leaving the renewal 3.9 ms past its
capture-age deadline. Node and GPU were idle throughout.

The user-approved candidate change raises the G4 camera cadence from 15 to
30 simulation-Hz (the same sanctioned lever as the earlier 10→15 Hz fix):
a fresher capture is available whenever the serial inference pipeline
frees, adding ~24 ms of capture-age margin to every armed renewal. The two
zenoh bridges' CPU limits rise from 500m to 1 (requests 200m) because frame
traffic doubles, and `run_g4_suite.py`'s plan record now states
`camera_update_hz: 30`. No freshness deadline, zero-command deadline, fault
semantic, watchdog, threshold, identity, geometry or calibration changes;
the fixture image digest is unchanged (the cadence is a fixture-source
ConfigMap value). Pilot 6 (`serving-transport-pilot-6/`) validates the
margin shift and that the compressor and bridges keep up, before
qualification-8.




## Pilot protocol

One isolated serving-unavailable trial through the unchanged qualification
runner (`run_g4_faults.py --modes serving --repetitions 1`), so the trial
code path, pre-arm ladder, wire proof requirements (a real injected 503 on
the loopback proxy) and evidence retention are exactly those of
qualification. The pilot provisions a fresh short-lived (72 h) self-signed
localhost certificate/secret `semantic-g4-proxy-tls` — key material is never
retained or printed; only subject/issuer/validity/fingerprint metadata is
recorded in `events.json` — and removes it in a `finally` that also removes
the G4 topology and restores the A10G rendering reservation from the saved
manifest. A read-only serving sampler runs with its own stop file and is
always stopped. If this pilot passes, the next step is a fresh full
qualification in a new output directory; if it fails, it is retained and
diagnosed before anything else runs.
