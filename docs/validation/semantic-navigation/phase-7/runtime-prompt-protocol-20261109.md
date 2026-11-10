# Phase 7 runtime prompt protocol review — November 10, 2026

## Result

**Current demo-scoped result: DEMO PASS; reviewed and signed off November 10,
2026.** The production-focused HOLD criteria in this evidence register are
superseded by the accepted demo scope and current sign-off record in
[`phase7-demo-signoff-20261110.md`](phase7-demo-signoff-20261110.md). This file
retains the detailed validation history. Demo evidence does not qualify
production deployment, new-object recognition, or physical-robot use.

## Review readiness — November 10, 2026 (local)

The demo-scoped review disposition is defined by
[`phase7-demo-signoff-20261110.md`](phase7-demo-signoff-20261110.md). The
earlier broad production/generalization gates remain documented below as future
work, not requirements for the current demo sign-off. Keep accepted Phase 6
workloads unchanged during every demo run.

| Gate | Result | Evidence / remaining work |
| --- | --- | --- |
| Permit, authorization, API, and transition-control behavior | PASS in fixtures | Runtime, adapter-permit, and control tests; candidate digest below |
| Native watchdog stop behavior | PASS in isolated Gazebo fixture | Disarmed clamp, producer-loss stop, explicit stop, paused-simulation stop, and late-success/session-reuse rejection |
| mTLS transition through the real operator runtime process | PASS in fixture topology | Both Nav2 cancel services invoked; rejected cancel left generation 1; accepted update reached generation 2 and fresh readiness; then 20 alternating mTLS changes reached generations 3–22 |
| Runtime restart during an in-flight transition | PASS in fixture topology | Runtime terminated while generation 2 was pending; adapter completed readiness; restarted API recovered generation 2 as `changed: false` before the 20-cycle sequence |
| Secret-mounted operator credentials | PASS in fixture topology | Candidate loaded the signing key, operator map, TLS server/client identity, and client CA from a read-only Secret mount; temporary fixture Secret deleted after the Job passed. Production identities and lifecycle remain unqualified. See [managed credential fixture](../security/phase7-managed-credentials-20261110/README.md). |
| Live operator policy + Nav2 cancellation | PASS in the combined simulator topology | Candidate #66 passed twice with the ROS endpoint startup gate. In the latest run, both domain probes received all five streams, the adapter paired 48 triplets and emitted 29 fresh results, `red mat` returned HTTP 200 with `changed:false`, `blue crate` returned HTTP 400, and a real Nav2 goal reached `STATUS_CANCELED`. All 415 native samples stayed disarmed with zero applied commands; maximum physical speed was 0.0010035701 m/s. All 19 containers exited 0. See [startup-gate pass](attempts/live-ros-stream-startup-gate-20261110/README.md) and [repeat](attempts/live-ros-stream-startup-gate-repeat-20261110/README.md). |
| Loopback-only listener hardening retest | PASS in corrected integrated topology | The #64 attempt failed closed before API readiness. Candidate #66 confirms the operator API is reachable only through loopback in two complete startup-gated runs. The mTLS red-mat no-op and unapproved blue-crate rejection passed before the actual Nav2 cancellation test. See the [first pass](attempts/live-ros-stream-startup-gate-20261110/README.md) and [repeat](attempts/live-ros-stream-startup-gate-repeat-20261110/README.md), and retain the [failed startup evidence](attempts/live-operator-loopback-scope-startup-timeout-20261110/README.md). |
| Per-domain ROS stream diagnosis | PASS after endpoint startup gate | Candidate #65 probes isolated missing depth delivery. Reliable route blocking alone passed once but failed on the exact repeat. Candidate #66 now waits for the expected source camera publisher nodes and adapter subscriber nodes before starting both camera bridges. Two consecutive complete live runs delivered all five streams in both ROS domains and passed the combined operator, Nav2 cancellation, and native no-motion workflow. See the [first startup-gate pass](attempts/live-ros-stream-startup-gate-20261110/README.md) and [repeat](attempts/live-ros-stream-startup-gate-repeat-20261110/README.md), with the earlier [failed probe](attempts/live-ros-stream-probe-20261110/README.md) retained.
| Scoped NetworkPolicy for isolated live topology | PASS | The policy denies inbound traffic and limits egress to OpenShift DNS and the pinned model predictor. The first attempt exposed the service-to-pod DNS port translation; the corrected policy passed a DNS/mTLS probe and the full 19-container live workflow. See [candidate #68 repeat under policy](attempts/live-network-policy-candidate-68-repeat-20261110/README.md) and retain the [failed attempt](attempts/live-network-policy-candidate-68-20261110/README.md).
| Old-generation adapter and costmap barriers | PASS in isolated adapter/costmap fixtures | Delayed old response, stream-epoch retirement, generation flush, and plugin preflight; not production sensor/model traffic |
| Phase 7 demo topology and safety use cases | DEMO PASS | Candidate #68 passed live `red mat` inference, idempotent mTLS request, unapproved prompt rejection, actual Nav2 cancellation, watchdog no-motion, and scoped NetworkPolicy. The separate mTLS fixture passed signed prompt changes, restart recovery, and freshness barriers. Phase 6/shared Phase 5 snapshots were unchanged. See the [demo sign-off record](phase7-demo-signoff-20261110.md) and [policy-qualified run](attempts/live-network-policy-candidate-68-repeat-20261110/README.md). |
| Additional-object recognition | OUT OF SCOPE for demo | The pinned identity remains `red mat`. `blue crate` rejection is an authorization check only; it does not claim recognition quality. Blind review and held-out evaluation remain future work if the category is later needed. |
| Production managed credentials and deployment | OUT OF SCOPE for demo | The isolated demo uses a short-lived validation Secret and a single-pod simulator topology. Production identity lifecycle, multi-pod policy, service availability, and deployment operations are not claimed. |

**Latest startup-gated live topology, November 10:** runtime candidate #66 (`sha256:bdcc039a9a0279fccecdcfad9231cdeaa3facc0ccf5f36fc06912b949cd91148`) passed all 25 in-image Phase 7 tests. The adapter candidate (`sha256:d5b22eae66497af2bd3230d43767f862d6b0923d73ffb8f54a865e21c9258c28`) paired 60 triplets and emitted 36 fresh results in the first startup-gated run; the exact repeat paired 48 and emitted 29. Both ROS domains received all five required streams in both runs. Each mTLS operator check confirmed the loopback-only listener, the active `red mat` prompt returned HTTP 200 with `changed:false`, and unapproved `blue crate` returned HTTP 400 without transition effects. A real Nav2 goal was accepted and canceled with `STATUS_CANCELED` in both runs. All 402 then 415 native samples remained disarmed with zero applied commands; maximum measured speeds were 0.0010043501 and 0.0010035701 m/s. All 19 containers exited zero in both runs, and Phase 6 pod snapshots matched. See the [first startup-gate pass](attempts/live-ros-stream-startup-gate-20261110/README.md) and [repeat](attempts/live-ros-stream-startup-gate-repeat-20261110/README.md).

**Latest policy-qualified live run, November 10:** runtime candidate #68
(`sha256:b344a05fe7f3b8d31246c9af50d3436a03389704640e474fcfda2e091ed06f1b`;
26 in-image tests passed) completed the same 19-container workflow with the
scoped ingress-deny/egress-allow NetworkPolicy active. Both ROS domains
received all five streams; the adapter paired 97 triplets and emitted 67 fresh
results from the pinned red-mat service. The loopback-only mTLS API returned
HTTP 200/`changed:false` for `red mat` and rejected `blue crate` with HTTP 400.
Nav2 accepted a goal after four submissions; both cancel services acknowledged
and Nav2 returned `STATUS_CANCELED`. All 410 native samples remained disarmed
with zero applied commands; maximum measured speed was 0.0010071496 m/s. All
containers exited zero, and normalized Phase 6/shared Phase 5 router snapshots
were identical before and after. See the [complete evidence bundle](attempts/live-network-policy-candidate-68-repeat-20261110/README.md).

**Earlier combined-topology evidence (#62):** Candidate #62 (`sha256:81df532f19a65e8de4b8c895918d8bc64702e7ace1d0667f47197efe6fbcbdb5`) passed all 24 in-image Phase 7 tests. Adapter candidate `sha256:d5b22eae66497af2bd3230d43767f862d6b0923d73ffb8f54a865e21c9258c28` passed 46 unit and 17 ROS integration tests. The integrated pod produced 49 paired RGB-D-CameraInfo triplets and 31 fresh authenticated model results. An mTLS-authenticated `red mat` no-op returned HTTP 200 with `changed:false`; unapproved `blue crate` returned HTTP 400 without stop, cancellation, or prompt update. Nav2 accepted a goal after four submissions; the cancel proxy acknowledged the active goal and Nav2 returned `STATUS_CANCELED`. All 411 native samples remained disarmed with zero applied commands; max physical speed was 0.0010036451 m/s. All 15 containers exited zero. See [candidate #62 evidence](live-operator-idempotent-rejection-nav2-cancel-pass-20261110/README.md). Earlier #60 and #54 live passes remain linked below.

**Live fail-closed operator check, November 10:** two startup-gated runs confirmed that an authenticated idempotent request for the active `red mat` prompt returns `changed:false` without advancing generation, before unapproved `blue crate` is rejected. This still does not qualify a successful approved live prompt transition/restart/stale-result workflow; only the red-mat model identity is approved and served in this topology.

A later retry exposed a concrete QoS incompatibility: the camera compressor paired RGB/depth, but the adapter received no complete triplets because CameraInfo and capture traces were offered BEST_EFFORT while adapter subscriptions requested RELIABLE. The adapter now requests BEST_EFFORT for CameraInfo and both trace topics, with a regression test. The corrected candidate passed two consecutive integrated startup runs. Longer-duration behavior and the complete live transition workflow remain open. See [diagnostic evidence](attempts/live-metadata-best-effort-qos-failure-20261110/README.md) and [corrected live pass](live-operator-idempotent-rejection-nav2-cancel-pass-20261110/README.md).

**Historical broad-scope disposition:** superseded by the demo-scoped record.

## Demo environment state and future work

The serving identity approves only `red mat`, as required for the live demo. The
narrowly selected policy for the single-pod simulator topology is deployed from
[`phase7-live-network-policy.yaml`](../../../../helm/semantic-navigation/phase7-live-network-policy.yaml). The initial DNS-policy failure and later over-narrow variant remain retained beside the successful candidate #68 bundle. The current policy matches the passing configuration. No Phase 7 demo pod or fixture Secret is active; the runbook creates temporary resources and removes them after evidence capture. The policy selector does not match the accepted Phase 6 pods.

The blue-crate label review, development expansion, held-out evaluation, and
production deployment controls remain documented as future work. They are not
requirements for the current demo-scoped Phase 7 decision. Use the
[demo sign-off record](phase7-demo-signoff-20261110.md) for current acceptance
criteria and reviewer disposition.

## Additional-object capture pilot — November 9, 2026

An isolated Phase 7 simulator capture pod now produces synchronized compressed
RGB/depth frames for the blue-crate fixture. The pilot has four positive views
and two negatives across three simulator episodes. One negative is target out
of view; the other has the crate model omitted while the red mat remains
visible. Five views follow odometry-feedback motions or a fresh scene start;
each capture was taken after odometry confirmed the robot stopped. All
RGB/depth and CameraInfo skews are 0 ms; odometry skew is 20–80 ms.
Geometry/depth masks for all four visible crate views align in visual checks;
both negative masks are empty. Gazebo entity metadata confirmed the crate was
absent in the crate-omitted scene. The six-row Phase 2 validator passes with
`--min-heldout-per-class 0`, recording four development positives, two
development negatives, and no held-out rows.

These samples are synthetic and pending human label review. The visible crate
is shown over the existing red mat under one default lighting/background
condition. They do not measure the pinned SAM3 model's recognition quality or
satisfy the episode-separated held-out requirement. The full pilot packet is at
[`phase7-bluecrate-pilot`](../phase-2/phase7-bluecrate-pilot/README.md).
The six labels now have a blind human-review packet and a primary-review
template with two independently selected checks; all decisions remain pending.
See the [label packet](../phase-2/phase7-bluecrate-pilot/label-review-packet.md)
and [contact sheet](../phase-2/phase7-bluecrate-pilot/label-review-contact-sheet.jpg).
The missing development views are scheduled in a separate
[34-frame development expansion](../phase-2/phase7-bluecrate-development-plan-20261109.md)
to reach 20 positives and 20 negatives across episodes after the current labels
are reviewed.
I also preregistered a five-episode, 100-view held-out coverage matrix before
any blue-crate SAM3 scoring; prompt, threshold, and visibility configuration
remain unfrozen, so capture must wait for development review/configuration.
See the [held-out matrix plan](../phase-2/phase7-bluecrate-heldout-plan-20261109.md).
The initial positive used capture image
`sha256:f29be73f58587cc8f0c1b89055ac9a272df34a2a637e470b04623899ff22799b`;
the four motion-follow-up frames used
`sha256:f377c071277f5739b947344ffdaa73155c6b3953ef8dde130151a0585a063004`;
the crate-absent negative used
`sha256:27c5d36420cdb4b89a229e15787796013ad53343898be13828f8b668bebf0e1e`.

## Credential hygiene follow-up — November 10, 2026

The exposed G5 replay CA/server/client credentials were rotated through the
stopped-replay workflow. The baseline serving image and deployment identity
were preserved; the replacement predictor returned Ready. The retired client
and a request without a client certificate were both rejected. The temporary
rotation client was removed after verification. The evidence is in
[`g5-credential-rotation-20261110`](../security/g5-credential-rotation-20261110/README.md).
This rotation does not provision production Phase 7 operator identities or
permit signing key, so the production managed-credential gate remains HOLD.

## Coverage

The adapter ROS integration suite exercised 20 sequential transitions between
`red mat` and `blue crate` using a deterministic mock inference server. Each
transition incremented the policy generation, flushed old work, required a
fresh result for the new generation, and published matching prompt metadata.
An unapproved `yellow cone` request was rejected without changing generation.
The suite also exercised a delayed old response during a prompt transition and
rejected a permit signed for a prior stream epoch. Adapter transitions now
require a five-second HMAC permit scoped to prompt, next generation, and current
stream epoch; the old caller-supplied boolean attestations are removed.

The permit issuer checks the configured operator credential and the native
safety clock's 250 ms stationary window, current measured velocity, disarmed
state, and zero applied command. The permit authority and transition-control
core cover permit issuance through `NativeClock`, stop/apply/fresh-result
ordering, bad credentials, failed stops, and loss of stationarity. An mTLS
HTTPS operator API was added: client certificates are mandatory, a certificate
CN must map unambiguously to an operator credential, and invalid requests do
not reach the controller. A runtime bridge now binds this API to the native
Gazebo status/stop interface, Nav2 cancel services, and the adapter's atomic
ROS parameter service. It requires a private `phase5-watchdog-phase7-*` Gazebo partition,
loopback Gazebo transport, matching fresh native status, and a ready adapter;
it never arms motion or resumes Nav2. The bridge has been built and tested, but
has not yet run against a complete Phase 7 runtime topology. No signing key is
provisioned in the cluster; the adapter reports transitions disabled without
its key file.

An isolated OpenShift integration fixture exercised the candidate operator
runtime as a separate process against the real Gazebo watchdog status and stop
service, fixture ROS adapter services/topics, and fixture Nav2 cancel services.
The mTLS request invoked both `CancelGoal` endpoints. A rejected cancel ACK
failed closed and left the adapter at generation 1. A successful retry applied
a signed permit atomically, advanced to generation 2, and waited for matching
fresh adapter readiness. The runtime process was terminated while that
generation was pending; after the adapter became ready, a restarted runtime
recovered the committed prompt with `changed: false`, without another stop or
parameter update. The same runtime then completed 20 alternating prompt
changes through mTLS (generations 3–22), each with two cancel acknowledgements,
one permit-authorized atomic apply, fresh matching readiness, and a stationary
native proof. Across the interrupted transition and the 20-cycle run, the
fixture recorded 21 applies and zero native motion or resume. The adapter and
Nav2 endpoints remain fixtures, so this does not qualify the production
ROS/Nav2/adapter deployment.

The costmap suite exercised generation changes, rejection of old results,
stream-epoch changes, process-restart epoch retirement, and plugin loading. Its
isolated observer preflight ran for eight seconds with no observation input;
the semantic layers remained clear and it shut down cleanly.

## Test results

- Adapter image build: 46 Python tests passed; 16 ROS tests passed.
- Native-clock permit authority tests: 2 passed.
- Operator transition-control tests: 3 passed locally.
- Operator mTLS API tests: 3 passed locally.
- Operator runtime bridge tests: 5 passed locally.
- Deployed operator-control validation Job: 8 tests passed.
- Deployed operator-runtime validation Job: 14 tests passed on the rebuilt
  runtime candidate.
- Deployed native watchdog preflight: startup disarmed, raw-command clamp,
  producer-loss stop, explicit stop, paused-simulation stop, and late-success
  rejection passed in an isolated Gazebo fixture.
- Deployed mTLS/native operator integration fixture: passed on the rebuilt
  runtime candidate; verified rejected-cancel fail-closed behavior, both Nav2
  cancellation ACKs, generation 2, runtime restart recovery (`changed: false`),
  20 alternating changes through generations 3–22, and `motion_resumed: false`.
- Integration result record: `passed=true`, `rejected_cancel_fail_closed=true`,
  `restart_during_transition_recovered=true`; the interrupted request returned
  a non-success response before recovery,
  `retry_changed=false`, 20/20 alternating transitions returned `changed=true`,
  `apply_count=21`,
  `native_stationary_at_apply_count=21`, and 44 cancel-service callbacks across
  the rejected attempt, successful retry, and 20 alternating changes.
- Deployed Secret-mounted operator integration Job: passed on runtime image
  `semantic-safety@sha256:1c4175d7d3b8a59f685387fa3aff64ac1d20965b6d0a7df34ac704cd267fe080`;
  loaded all credentials from a read-only Kubernetes Secret mount and repeated
  the native/mTLS 20-cycle and restart checks. The temporary fixture Secret was
  deleted after completion. An initial run emitted a nonfatal ROS teardown
  warning; verifier executor shutdown was tightened and the rerun completed
  without that warning. Evidence:
  [`phase7-managed-credentials-20261110`](../security/phase7-managed-credentials-20261110/README.md).
- Deployed Zenoh ROS bridge integration Job: passed across separate Nav2,
  adapter, and operator domains with the packaged cancellation-proxy sidecar on
  runtime image
  `semantic-safety@sha256:d153b717d2d6656d0b656c1c0080012213e8d85e3aca463c1f44df56b2683a77`.
  All six containers exited zero. Both fixture actions had active goals; the
  proxy received two `return_code: 0` acknowledgements, both goal results
  reached status 5, the fixture prompt applied atomically, and three adapter
  status messages arrived. Logs:
  [`ros-service-bridge-packaged-proxy-pass-20261110`](ros-service-bridge-packaged-proxy-pass-20261110/).
- Deployed adapter validation Job: 16 ROS tests passed on the permit-based
  candidate.
- Costmap image build: 26 C++ tests passed (27 result records, zero failures).
- Costmap observer validation Job: completed successfully after its eight-second
  run.
- Model-server candidate build: 22 tests passed.

## Candidate image identities

- Adapter: `sha256:3088ac06ceaef5b49b12b9c2b64f33b7bc1c080d4f7a5d6a48436abc8b8c7640`
- Model server: `sha256:8d91ec5d457eb94dcd07ad1387b08efc4b61e660dfaa38c46ff44a71047b6c5c`
- Costmap: `sha256:167d2f41bb985f8b7dd96a73cb4f4930a8e95954565370a11e81159246fabbc3`
- Operator control: `sha256:eaee8b0e684a6b242a85a1ef604c37a25ce3f06110f28b8e0367678b534702a9`
- Operator runtime: `sha256:d153b717d2d6656d0b656c1c0080012213e8d85e3aca463c1f44df56b2683a77` (build #44; 17 tests passed)
- Operator runtime for actual Nav2 cancellation subgate: `sha256:47c8424498ca3bd15975fa29d8912d0373d8d3de5476fd742f1e58071fce90d6` (build #51; 17 tests passed; 11/11 live topology containers exited zero)

These images were built as Phase 7 candidates. Validation Jobs ran the adapter
and costmap candidates in isolated ROS domains; the operator-control Job ran
the safety API and control tests, and the runtime Job ran all 14 safety API,
control, authority, and runtime bridge tests. The latest runtime image build
(#44) ran 17 tests. Separate runtime Jobs exercised the native watchdog,
ROS-backed mTLS transition fixture, Secret-mounted credential path, and
packaged cancellation-proxy bridge path. The accepted model-serving and Phase 6
navigation workloads were left on their existing images.

## Live-topology preflight

A read-only probe of the running `semantic-phase6-simulator` pod found only
`/robot_1/cmd_vel` and `/robot_1/odom` among the relevant Gazebo topics, and no
`/phase5/drive/status` topic or `/phase5/drive/stop` service. The deployed
Phase 6 adapter and Nav2 also run in separate ROS domains (82 and 87), while
the simulator runs in its own Gazebo partition. The active simulator therefore
does not provide the independent native stop/status interface required by the
permit issuer. This confirms that the mTLS API cannot safely be connected to
the active Phase 6 stack as it stands.

The isolated fixture runs the operator runtime in a subprocess and covers 20
alternating mTLS changes plus restart during a pending prompt transition. A
separate Phase 7 simulator topology has since passed actual Nav2 active-goal
cancellation and native no-motion with the watchdog in the command path. The
remaining topology gate is to add the candidate adapter and model service with
managed mTLS and permit-key credentials, then repeat the transition, restart,
delayed-old-result, and no-motion checks against those deployed components.
The Phase 6 simulator lacks the independent native stop/status interface and
remains unchanged.

## Limits and remaining gates

The `blue crate` prompt exists only in the test fixture identity. Six
synthetic development samples with geometry/depth annotations now exist, but
their labels await human review and the pinned serving manifest still allows
only `red mat`. The mock responses do not measure SAM3 recognition quality, so
`blue crate` remains unqualified and unavailable to deployment. No live authenticated operator endpoint or key provisioning is
connected to the adapter, so runtime transitions remain disabled in the
candidate configuration. The separate actual-Nav2 simulator run now qualifies
active-goal cancellation and native no-motion, but the fixture restart test
still does not qualify restart behavior with the deployed adapter/model service
or exercise actual Nav2 motion and resume.
Each additional category must pass Phase 2 and the applicable Phases 3–6 gates
before inclusion in a pinned serving identity.
