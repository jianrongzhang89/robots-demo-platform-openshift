# G5 operations protocol — revision 3

This is the full-gate rehearsal protocol. Stopped replay, pod-loss/wrong-version safety and passive telemetry results
are recorded in `report.md`; G5 remains HOLD. A new presenter must execute the final script and retain their name, date,
commands and evidence. The implementation author cannot substitute for that run.

## Scope and entry

Use a declared **stopped maintenance window**, one GPU serving replica, and the
full pinned identity in `registry-metadata.json`. No warm rollout claim. Preserve
the accepted local SAM3 deployment, rendering reservation, G4 tuning, original
freshness/stop thresholds and recognition waiver. Keep `semantic-hotel-sim` at 0.
Do not resume the paused G4 paired-series campaign as part of G5.

From the repository root, collect a fresh snapshot (use a new output filename):

```sh
python3 scripts/semantic-navigation/preflight_g5.py --output docs/validation/semantic-navigation/openshift-ai/S5/preflight-ATTEMPT.json
```

Require preflight PASS, then verify authenticated metadata and frozen replay parity
using the S1 replay/contract tooling. Preflight health and image checks alone do
not verify the loaded identity. Record the complete deployment identity, resources,
TLS leaf fingerprints/expiry, client principal policy, endpoint, candidate and
rollback image digests, rendered manifests, source hashes and evaluation-set hash.
Never store private keys, tokens, raw Secrets or normal camera images in evidence.

Before disruptive operations: cancel navigation, observe applied zero commands
and stationary state, disarm, invalidate outstanding work/epochs, and establish
the stopped state from runtime evidence. An idle pod or absence of G4 pods is not
proof of stopped motion. Snapshot resources needed for rollback securely. Do not
scale shared platform operators or dashboards to test dependency loss.

## Implementation prerequisites before rehearsal

1. Register `registry-metadata.json` through the installed model registry's API;
   resolve its actual service, schema and authorization first. This file is a
   local metadata specification, not an API request body. Retain returned model,
   version and artifact IDs plus readback. Include the immutable checkpoint hash,
   runtime identity, prompt policy, evaluation limitations and evidence links.
   Promotion is metadata and grants no motion authority.
2. Provide a dashboard showing the measurements below, current identity and gate
   evidence links. Use authenticated collection on port 8443; the health port is
   not a metrics bypass. Give monitoring its own explicit least-privilege identity
   and narrowly scoped network access. Never broaden inference access to make
   scraping work. Show stale/unavailable data explicitly.
3. Produce a digest-pinned update candidate, with full identity distinct from the
   rollback identity, and qualify it before serving navigation. A pod restart or
   metadata-label edit does not count as a model/runtime update. Runtime changes
   require the applicable contract/parity/timing qualification and RTF audit;
   moving-navigation claims require requalification of the changed candidate.
4. Implement a bounded lifecycle driver/evaluator with separate attempt directories
   and restoration in failure paths. Freeze timeouts and candidate before the
   first run. Do not automatically retry failed lifecycle assertions.

| Dashboard requirement | Implemented source / presentation notes |
| --- | --- |
| Request rate and success/error counts | `semantic_requests_total{status=...}`; rate requires successive samples |
| Inference latency and queue delay | Candidate bounded histograms; absent on accepted baseline. No queue: immediate busy rejection; candidate queue capacity is zero |
| Worker readiness/busy state | `semantic_worker_ready`, `semantic_worker_busy` |
| GPU utilization and memory | Live accelerator utilization/memory series verified through Thanos |
| Complete model/runtime identity | Authenticated metadata endpoint and pinned-identity comparison |
| Capture-to-result/costmap ages, drops, last valid capture | Passive source-stamped adapter/costmap collector, exact request/capture correlation, ten-second dashboard expiry |
| Watchdog state, stop reason, applied command | Armed/stop reason panels; native applied-command traces linked from the safety evidence |
| Simulation RTF and wall capture age | Capture-stream sim/wall ratio and wall capture age; never substitute sim age for wall freshness |
| Evaluation and evidence links | Registry metadata and G0–G5 gate records; G5 visibly HOLD until qualified |

## Demonstration sequence and required evidence

Retain every attempt, including failure and cleanup. Each result needs wall UTC
and monotonic event times where applicable, command, exit code, resource UID and
identity. Keep request IDs in bounded traces, not metric labels.

| Step | Action | Pass evidence |
| --- | --- | --- |
| Baseline | Show deployment, GPU, registry identity, accepted off/on evidence and live metrics | Registry readback matches complete pinned identity; evidence links resolve; old navigation evidence is labeled with its original run |
| Authorization | Exercise actual internal TLS endpoint with no certificate, untrusted certificate and trusted but unbound principal | TLS/auth rejection; no successful inference or semantic publication; authorized request still succeeds |
| Rotation | In stopped window issue replacement server/client leaves, record expiry/fingerprints, update mounts and restart affected processes | New connection succeeds with verified hostname/chain; retired credential is rejected; full loaded identity/parity unchanged; no automatic resume |
| Update/rollback cycles 1–3 | Follow the cycle below three times | Three independent complete cycles, each returning to the exact pinned identity |
| Pod loss | In qualified fixture delete only the named serving pod after recording UID; observe fail-closed behavior and replacement | Existing freshness/zero-command bounds pass; new UID, checksum/warm readiness, exact identity and parity; no automatic motion resume |
| Dependency loss | Isolate only the test workload's access to registry/dashboard while retaining inference access; verify those paths actually fail | Already-loaded serving continues successful inference with the same identity; control and motion authority unaffected; restore scoped isolation |
| Egress denial | Attempt direct-IP external inference egress from the actual serving network context, paired with reachable control evidence | Network denial (not DNS failure alone), deny policy inventory, successful internal inference and no external inference dependency |
| Presenter recovery | Show restored identity, fresh evidence, empty pending work and cleared buffers/maps; explicitly resume | Resume is a distinct recorded operator action; normal operation only after all safety prerequisites |

TLS and client policy are read at server startup. Updating a mounted Secret alone
does not prove rotation. A replacement client leaf with the same URI SAN under
the same still-trusted CA also does not revoke the previous leaf: plan a unique
replacement principal plus policy removal, or a controlled CA trust transition,
and prove rejection of the retired credential after restart. Read-only preflight
reported the original leaf expiring November 7. The completed G5 rotation replaced
it: the current server expires **2026-11-11 14:14:48 UTC**. Recheck replay-client,
monitor and issuer expiries before scheduling the window. Reissue the monitor
credential after any later CA rotation (`provision_g5_monitor.py`).

For each update/rollback cycle:

1. Record stopped/disarmed state and invalidate old epochs/pending requests.
2. Deploy the qualified candidate under the stopped-window procedure; wait for
   checksum validation, warm-up and authenticated metadata. Pin the intended
   full identity explicitly for the new run; never auto-adopt a returned identity.
3. Verify candidate parity and deliver delayed old-version/pre-reset results to
   the guard. Require zero accepted mismatches and no publication from stale work.
4. Stop/disarm again, restore the saved digest-pinned runtime/configuration and
   original adapter identity, and verify exact metadata equality and replay parity.
5. Demonstrate fresh valid results without automatic resume. Retain guard
   acceptance/rejection and applied-command traces across both transitions.
6. Record explicit resume only after pending work and buffers/maps are cleared and
   fresh valid observations meet the original safety prerequisites.

## Failure, restoration and exit

Stop the attempt on any unexpected identity, accepted mixed-version result,
automatic resume, unauthorized success, threshold failure or missing evidence.
Retain the failed attempt; do not relabel it or relax thresholds. Keep motion
stopped, restore the pinned runtime/configuration and valid credentials, verify
identity/parity, remove only G5-owned test resources/policies, and confirm the
reservation, local SAM3 and hotel-sim replica count. Report restoration failures
explicitly; successful cleanup does not turn a failed test into PASS.

Set technical G5 PASS only after all rows and three cycles pass, metrics/evidence
are visible, and the new presenter has completed the script. Record technical
review separately from user acceptance. G6 remains a separate fleet gate.

## Reproducing the stopped replay tooling

The session removed its temporary replay pod. Before using the operations scripts
again, create the isolated client and stage only the frozen evaluation files and
three required source files (commands run from the repository root):

```sh
oc create -f docs/validation/semantic-navigation/openshift-ai/S5/replay-client.json
oc wait -n semantic-navigation pod/sam3-g5-client --for=condition=Ready --timeout=180s
oc exec -n semantic-navigation sam3-g5-client -- mkdir -p /tmp/g5/scripts/semantic-navigation /tmp/g5/apps/semantic-model-server /tmp/g5/apps/semantic-perception
oc cp scripts/semantic-navigation/replay_serving_parity.py semantic-navigation/sam3-g5-client:/tmp/g5/scripts/semantic-navigation/replay_serving_parity.py
oc cp apps/semantic-model-server/artifact.py semantic-navigation/sam3-g5-client:/tmp/g5/apps/semantic-model-server/artifact.py
oc cp apps/semantic-perception/inference_contract.py semantic-navigation/sam3-g5-client:/tmp/g5/apps/semantic-perception/inference_contract.py
oc cp docs/validation/semantic-navigation/openshift-ai/S1/g1-qualification-20261031/frozen semantic-navigation/sam3-g5-client:/tmp/frozen
```

`run_g5_replay_cycles.py --candidate-image IMAGE_AT_DIGEST --output-dir NEW_PATH`
creates the two identity files, executes three stopped replay cycles and restores
the original runtime/strategy. It does not establish a robot's stopped state or
replace the integrated safety steps above. Do not use it while other inference
clients or a motion fixture are active. It refuses additional labeled clients.

`rotate_g5_credentials.py --output-dir NEW_PATH` rotates issuer/server/replay
credentials and restarts the model to reload them; `provision_g5_monitor.py
--output-dir NEW_PATH` reissues the monitor under that issuer, reloads its read-only
policy, verifies inference denial, and applies monitoring. Both require the isolated
client. Recheck replay parity after these operations and retain every report.
`verify_g5_monitoring.py --output NEW_FILE` checks actual Thanos data and dashboard
configuration. `check_g5_dependency_isolation.py --output NEW_FILE` checks the
serving pod's denied connections against reachable controls. Pair it with passing
replay immediately before/after. Remove the temporary replay pod when finished.

## Reproducing the integrated safety and telemetry checks

Use a fresh directory for every attempt. Keep the accepted serving runtime pinned;
these commands do not qualify the metrics candidate for navigation. Before starting,
ensure the rendering reservation is Ready and no G3/G4/native fixture is active.

```sh
python3 scripts/semantic-navigation/run_g5_pod_loss.py --output-dir NEW_POD_LOSS_DIR --reservation docs/validation/semantic-navigation/openshift-ai/S4/g4-qualification-20261031/rendering-reservation-saved.json
python3 scripts/semantic-navigation/evaluate_g5_pod_loss.py --run-dir NEW_POD_LOSS_DIR
python3 scripts/semantic-navigation/run_g4_serving_pilot.py --mode wrong_version --output-dir NEW_VERSION_DIR --reservation docs/validation/semantic-navigation/openshift-ai/S4/g4-qualification-20261031/rendering-reservation-saved.json
```

Require both the original fixture result and pod-deletion attribution PASS. Do not
add CLI reads between verified motion and deletion: the motion window is short.
The attribution evaluator deliberately avoids assuming host and fixture wall clocks
are synchronized. Native trigger-to-applied-zero and confirmed-stationary timings
are separate measurements. Failed armed attempts stay failed; no automatic retries.
`g5_prearm.py` only classifies explicit zero-packet/disarmed setup timeouts; it never
relabels a safety failure or changes the G4 retry policy.

For live dashboard measurements, run the bounded passive collector alongside a
fixture and verify through Thanos before the fixture exits:

```sh
python3 scripts/semantic-navigation/collect_g5_navigation.py --output NEW_SAMPLES.jsonl --seconds 900
python3 scripts/semantic-navigation/verify_g5_navigation.py --output NEW_LIVE_CHECK.json
```

The semantic-armed fault fixture intentionally has no semantic costmap subscriber.
Use `run_g5_costmap_telemetry.py --output-dir NEW_COSTMAP_DIR` for a separate,
stationary 40-second capture / 60-second costmap demonstration. If the historical
CPU node lacks capacity, declare `--inference-node WORKER` and retain the changed
placement. Require the existing 4 MiB DDS socket-buffer prerequisite. The already
tuned rendering worker can host CPU-only consumers with the simulator's narrow
toleration when capacity permits; do not lower resource requests or call this a G3 requalification. The
wrapper verifies live metrics, correlates applied IDs/capture times against results,
removes its test resources and restores the rendering reservation. Capture/costmap
correlation must meet the unchanged 95% coverage bound for both maps.

After stopping the collector/fixture, wait for source expiry and require:

```sh
python3 scripts/semantic-navigation/verify_g5_navigation.py --unavailable --output NEW_UNAVAILABLE_CHECK.json
python3 scripts/semantic-navigation/preflight_g5.py --output NEW_FINAL_PREFLIGHT.json
```

These scripts are focused operations tools. The recorded safety demonstrations
and API checks do not substitute for the new presenter running the complete
protocol, checking the dashboard and evidence links visually, and explicitly
recovering/resuming. Script PASS is not G5 PASS.

## Interactive navigation presentation

Use `scripts/semantic-navigation/run_g5_navigation_demo.py --output-dir <new-dir>`.
This optional presentation stages the standalone D2 mat (1.2 × 1.95 m), while
ordinary qualification trials retain the original smaller mat. It is not a new
qualification. The view-only CPU viewer uses OGRE, a 960 × 600 viewport, no
anti-aliasing, and 1 CPU requested / 3 CPU limit. Sensor GPU rendering remains
OGRE2. See `navigation-demo-on-4/presentation-fix-report.md` for the diagnosed
1-FPS regression and measured correction. The per-run token hold requires a
fresh operator release and expires after 600 seconds. Never reset a bound
clock or relax motion/freshness limits to proceed. Viewer FPS and CPU records
are collected with the fixture evidence.
