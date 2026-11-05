# S3 live timing and projection qualification

October 31, 2026. **G3 PASS; user-approved on October 31, 2026.** G2 is PASS and user-approved. All three independent ten-minute runs passed, including the two moving-observation runs. There were 10,223 timed results in total.

The isolated topology uses the signed-off CPU adapter and G1 model images unchanged. A private headless Gazebo world supplies capture-origin RGB-D, calibration, odometry and TF on an A10G rendering node. A CPU adapter performs authenticated HTTPS inference on the existing L40S endpoint. Two diagnostic Nav2 costmaps consume the output with an odometry fixed frame. No planner, navigation controller or RMF connection consumes those costmaps. Controlled yaw sweeps exercise moving observations without semantic influence on motion.

The fixed G3 thresholds are ≥5 fresh valid results/s, p95 capture-to-result ≤250 ms, ≥95% mask/cloud pairing, zero accepted mismatches, p95 capture-to-costmap ≤300 ms, and zero unexplained healthy-run publication gaps above 500 ms. Qualification also requires p95 ≤250 ms through observer validation, rather than relying solely on publication timestamps. Every mask and cloud is checked against its result trace's SHA-256 binding. Raw tails, discarded work, memory samples and resource usage are retained.

The [qualification plan](g3-qualification-20261031/qualification-plan-final.json) and [rendered resources](g3-qualification-20261031/resources-final.json) specify the final configuration. The adapter requests 1 CPU/1 GiB and limits 2 CPU/2 GiB. The dual costmap observer requests 1 CPU/1 GiB and limits 3 CPU/3 GiB. A separately bounded 0.5 CPU background worker runs throughout measurement alongside the real sensor, compression, bridge, TF and costmap work. ROS domains 190/191 and the dedicated Zenoh router isolate the fixture. The existing accepted local SAM3 path remains deployed.

## Preflight findings and fixes

All attempts are retained in [g3-qualification-20261031](g3-qualification-20261031/).

| Pilot | Finding |
| --- | --- |
| 1 | 40 ms maximum queued-work wait produced 4.999 fresh results/s; rate failed. Publication p95 189 ms, costmap p95 about 253 ms. |
| 2 | Increasing queued-work wait to 60 ms produced 5.479/s and publication p95 233 ms. UDP loss still delayed the observer. The motion helper failed before publishing a command because its log directory was unwritable; that setup failure is retained. |
| 3 | Bounded yaw motion passed and stopped; rate 5.529/s and publication p95 232 ms. Observer delivery remained slow. |
| 4 | A 4 MiB requested DDS receive buffer eliminated pod UDP receive-buffer errors. Moving observations passed. Observer validation p95 was still 262 ms. |
| 5 | Equivalent vectorized cloud validation reduced its measured validation cost from 14.46 to 2.18 ms/frame. All pilot criteria passed: 5.795/s, publication p95 232 ms, validated-consumer p95 246 ms. |

Only admission waiting changed in the runtime configuration: one pending request, one queued bundle and the original 500 ms capture deadline remain enforced. No model, precision, prompt, threshold, inference wire contract or SAM3 shared source changed.

The worker's receive-buffer ceiling was 212,992 bytes. The scoped `semantic-g3-adapter` TuneD profile now inherits `openshift-node` and sets `net.core.rmem_max=8388608` only on `ip-10-0-53-174.ec2.internal`. The consumer DDS configuration requests exactly 4 MiB; its minimum makes startup fail if the required buffer is unavailable. This uses Cyclone DDS's documented receive-buffer setting. [Cyclone DDS configuration reference](https://cyclonedds.io/docs/cyclonedds/latest/config/config_file_reference.html#cyclonedds-domain-internal-socketreceivebuffersize)

The observer's optimized checks were compared against the original implementation for all 729 combinations of representative finite, NaN, infinity and range-boundary values, plus ten full-size randomized clouds. The same validation semantics and payload binding remain enforced. This optimization affects evidence collection, not the signed-off adapter image.

## Projection and failure checks

The installed costmap plugin was reused without rebuilding it. The new observer wrapper supplies an odometry fixed frame and the robot pose for its rolling window. Its image build passed all 23 projection/lifecycle tests, including capture-time rather than latest TF, exact grid placement, optical-frame rotation, missing TF, invalid depth, payload/epoch mismatches, bounded partial pairs, rolling-window eviction, clearing, and pause expiry.

Live clear, deactivate/reactivate, paused expiry and clock reset passed against the served model. Recovery required fresh captures after each barrier. The 12 actual ROS fault tests also passed with the 60 ms queue-wait limit and final DDS settings. The moving fixture passed its odometry freshness, translation/yaw bounds and verified-stop checks.

Clock checks on the rendering and adapter workers reported Normal synchronization. Their measured clock errors plus root-delay/dispersion bounds fit within the retained 2 ms cross-host allowance. The serving GPU's wall clock is not used to establish capture age.

## Qualification runs

All three independently restarted 600-second runs passed the same frozen criteria. Each used a fresh adapter/costmap pod and a reset private world. Runs 2 and 3 completed their yaw sweeps and verified stopped states.

| Run | Observation | Fresh results/s | Publication p95 | Validated consumer p95 | Worst costmap p95 |
| --- | --- | ---: | ---: | ---: | ---: |
| 1 | stationary | 5.648 | 231.152 ms | 244.869 ms | 259.848 ms |
| 2 | bounded yaw observation | 5.711 | 231.045 ms | 244.914 ms | 259.852 ms |
| 3 | bounded yaw observation | 5.678 | 230.860 ms | 244.285 ms | 259.758 ms |

Mask/cloud pairing was at least 99.9705%. All three runs had zero identity, ordering, capture-age or payload-binding errors, zero publication gaps above 500 ms, zero additional UDP receive-buffer errors and zero pod restarts. The maximum publication gap was 256.892 ms. Applied global/local costmap request IDs were independently correlated with the actual capture/result records, with no mismatched identities or capture timestamps. Collector-window boundary records are retained separately.

Adapter process RSS stayed below 103 MiB. Total adapter-container memory, including the measurement observer retaining its bounded ten-minute evidence, stayed below 160 MiB. Queues and costmap buffers remained within their configured bounds. Raw admission drops and latency tails are included in each [run summary](g3-qualification-20261031/run-summary.json); passing p95 does not mean every result was below the p95 limit.

The model remained on the same G1 image and pod throughout qualification. Serving/GPU samples, capture traces, costmap update streams, motion/stop evidence and per-run evaluations are retained. Initial monitor requests to the health-port `/metrics` returned 404; the corrected monitor used the authenticated TLS endpoint. Both monitor histories remain available.

After qualification the private world was paused, adapter readiness became false, and both costmaps cleared to zero cells. The three G3 pods, private router Service and ConfigMap were removed. The original rendering reservation was restored and is Ready; the accepted local SAM3 pod remains Ready; the G1 InferenceService and overall OpenShift AI DSC remain Ready. The G2 adapter remains Running and intentionally not Ready while idle. The scoped TuneD profile and pinned build artifacts are retained for the next stage.

Reproduction and rollback instructions are in [README-g3.md](../../../../../helm/semantic-navigation/openshift-ai/README-g3.md). Preserve the 60 ms work-wait setting, 4 MiB DDS receive buffer, scoped 8 MiB kernel ceiling and declared quotas when reproducing these results. The validated-consumer p95 has about 5 ms headroom to its limit; a different topology or resource profile needs fresh timing qualification.

G3 is ready for user sign-off. G4 remains the served-navigation experiment and moving failure/stop checks; no navigation gate is inferred from this result.

The recognition waiver remains unchanged. These checks qualify the declared isolated sensor and costmap workload; navigation avoidance, moving fault stops, production localization and fleet throughput remain G4–G6 work.
