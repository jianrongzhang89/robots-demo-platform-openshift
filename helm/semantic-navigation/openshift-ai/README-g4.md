# G4 served navigation

G3 is user-approved. G4 uses the existing Phase 5 guarded fixture and Phase 6 paired evaluator with the pinned HTTP adapter. See the [G4 record](../../../docs/validation/semantic-navigation/openshift-ai/S4/report.md).

`g4_topology.py up --output-dir <new-directory>` creates a separate private router and CPU adapter. It checks the loaded deployment identity and status freshness using the adapter's clock. Initialization does not grant ROS readiness or motion permission. The fixture still requires real fresh results before arming. The accepted local SAM3 pod is retained.

Apply `g4-navigation-tuned.yaml` for the A10G worker's 8 MiB receive-buffer ceiling; the G3 adapter worker retains its existing scoped TuneD profile. Both G4 consumers request 4 MiB DDS buffers. Preserve the rendering reservation's live manifest before handing its GPU to the private fixture.

G4 raises only the RGB-D cadence to 15 simulation-Hz to retain wall-clock freshness in the full guarded world; physics remains at 2 ms. The served heartbeat uses the adapter publication time and last validated capture stamp, avoiding a future timestamp from another ROS domain.

The fixture entry is `run_phase5_native.py --sam3-observation --served-topology` with the accepted guarded GPU placement, contact audit and geometry flags. The served observation worker drains both ROS executors without blocking on an idle domain. It publishes the small lease/status file at 10 ms cadence and the larger diagnostic history at 100 ms cadence. Capture timestamps, hash matching, projection and all freshness/stop thresholds are unchanged. Historical local-mode fixtures keep their existing scheduling.

`run_g4_phase5.py` repeats moving observation, recovery or native stop gates. `run_g4_faults.py` repeats the original semantic faults and six serving faults. Each trial starts with fresh private topology. Armed and injected-fault failures stop immediately. Setup uses the accepted bounded pre-arm liveness ladder only when the retained coordinator history proves no arming attempt occurred. Every setup attempt and log is preserved.

Serving fault trials require the separate loopback TLS certificate Secret `semantic-g4-proxy-tls`. The injector trusts the existing client CA and forwards healthy requests over verified mutual TLS to the pinned real model. Authorization sends an unauthorized robot identity and requires an actual upstream 403; overload sends two competing requests and requires an actual upstream 429. Serving-unavailable 503, closed connection, response hang and changed deployment version are explicit injected conditions. Wrong identity remains latched until adapter restart; the recovered result must not restart motion.

`run_g4_suite.py --output-dir <new-directory> --reservation <saved-restore-json>` requires signed-off G1–G3, runs the original Phase 5 repetitions, two repeats of each added fault, then 20 nominal pairs plus three pairs of each negative case. It retains the lethal-254 exclusion framing and belief/truth measurements. The paired series keeps the previously accepted bounded pre-arm infrastructure retry policy. No failed motion trial is retried. The suite restores the rendering reservation and removes private G4 topology and injector credentials on exit. PASS remains pending user acceptance.
