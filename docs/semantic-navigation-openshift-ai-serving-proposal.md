# Semantic navigation with OpenShift AI Model Serving

Date: October 13, 2026. Status: deferred implementation proposal; all migration gates are pending.

## Purpose and scope

Move qualified SAM3 inference to an on-premises OpenShift AI service after the [semantic navigation implementation plan](semantic-navigation-implementation-plan.md) passes phases 0–6. Preserve the camera pipeline, robot-side policy, semantic layer, NavFn, RPP, and stop behavior. Hosting the same pretrained model elsewhere does not itself require fine-tuning; recognition and runtime behavior still require revalidation.

The initial semantic-navigation work must provide a ROS-independent model runner, a versioned inference contract, and backend conformance tests. This later proposal adds the model server, remote client, serving resources, and deployment verification. It is not a prerequisite for demonstrating SAM3 semantic navigation.

## Feasibility and deployment choice

OpenShift AI's KServe-based model-serving platform uses `ServingRuntime` and `InferenceService` resources. A custom runtime is the proposed route for packaging the qualified SAM3 vision pipeline; this is an architectural assessment, not a claim of a built-in SAM3 runtime. [Red Hat serving architecture](https://docs.redhat.com/en/documentation/red_hat_openshift_ai_self-managed/3.5/html/configuring_your_model-serving_platform/configuring-your-model-serving-platform_rhoai-admin).

Register a custom container that loads the authorized model and exposes image-and-prompt inference. Red Hat documents custom runtimes, but states that user-created runtimes are outside its support coverage and must be maintained by their owners. Plan for our own model-server testing, dependency updates, and license compliance. Verify registration privileges and the installed OpenShift AI version before selecting resource fields or deployment settings. [Red Hat custom-runtime guidance](https://docs.redhat.com/en/documentation/red_hat_openshift_ai_self-managed/3.5/html/configuring_your_model-serving_platform/configuring-model-servers_rhoai-admin).

Keep the qualified accelerator stack: do not assume the AMD ROCm/MIGraphX integration can run in a CUDA image. Prefer the exact image-inference implementation and checkpoint accepted in the initial demo. If deployment requires different precision, exports, preprocessing, or hardware, treat those as explicit changes and repeat the affected recognition tests. [SAM3 installation and inference API](https://github.com/facebookresearch/sam3), [AMD integration setup](https://github.com/open-navigation/opennav_amd_semantic_navigation/blob/5e82f4a458f9e97ddd92e2cf10feb2c3552295d3/opennav_sam3_setup/README.md).

## Integration boundary

The robot-side ROS adapter sends selected RGB images and the approved prompt to the remote backend. The backend serializes the shared contract to the chosen server protocol and translates responses back. The service returns segmentation masks, optional documented scores, and actual model/version metadata. The ROS adapter retains the original image header and matching depth cloud, validates results, assigns class IDs, and publishes the unchanged `semantic/*` interfaces.

Use the contract in the main plan as the source of truth, including request identity, stream epoch, policy generation, original image coordinates, bounded queues, deadlines, and typed failures. The server must not subscribe to robot TF, set navigation costs, issue velocity commands, or authorize task resume. Do not route this pipeline through a chat-model endpoint; the required payloads and outputs are vision-inference data.

Initially serve independent images, carrying the prompt in each request. A fixed category in the demo does not justify mutable server-global prompt state that could leak across clients. Defer video tracking: it would require per-robot sessions, session-aware replica routing, expiration, and restart/reset behavior. If the accepted local backend uses tracking, first qualify a stateless alternative or explicitly extend the server contract; ordinary load balancing is not sufficient for stateful tracking.

## Operational requirements

- Keep at least one loaded, warmed replica available during semantic tasks. Configure this for the selected serving mode; do not rely on scale-to-zero cold starts meeting navigation deadlines. Readiness requires loaded weights and a successful warm-up inference, not just an open HTTP port.
- Pin server image, weights, preprocessing/decoder versions, and configuration. Store authorized weights in controlled persistent or object storage and avoid request-time downloads. Allocate and measure compatible GPU resources instead of assuming a memory size.
- Use an authenticated, TLS-protected endpoint and narrow network access. Keep credentials in secret references rather than source files or ordinary logs. Bound payload sizes; avoid retaining camera images by default. Test authorization failure and credential rotation.
- Measure encoding, upload, queueing, inference, decoding, and adapter-to-costmap latency. Track request drops, timeouts, readiness, and last valid capture. Use the adapter's monotonic clock for end-to-end deadlines; server timings are supplementary.
- Keep depth/cloud buffering bounded on the robot side. Discard responses after deadline or loss of the matching capture. Do not retry obsolete images or automatically switch models/backends while a semantic task is moving.
- Stop semantic tasks on stale or unavailable inference according to the existing watchdog. An on-premises cluster removes dependence on a public inference service, but does not remove network delay or outages between sensors and serving pods.

## Migration and verification gates

Apply the main plan's `PASS`, `FAIL`, or `HOLD` reporting and reviewer sign-off rules. Store evidence under a separate `docs/validation/semantic-navigation/openshift-ai/` tree, with large artifacts linked by checksum. Complete each gate before starting the next.

| Gate | Work and verification | Pass condition |
|---|---|---|
| S0 Confirm deployment target | Record installed OpenShift AI/KServe versions, permissions, accelerator/runtime compatibility, storage, serving mode, network path, and resource quota. Render proposed resources without changing the accepted demo | A reviewed deployment design fits the actual cluster; the accepted local backend remains runnable. Hold if access, GPU capacity, or runtime compatibility is unresolved |
| S1 Package and qualify the server | Reuse the qualified model runner in a custom server; deploy an isolated endpoint. Test warm/cached startup, schema validation, authentication, readiness, and the shared backend conformance suite. Replay the frozen phase 2 evaluation images | Meet phase 2 recognition thresholds and predeclared local-versus-served mask agreement tolerances. Report all discrepancies, actual model hashes, and resource use; do not require or assume bitwise equivalence across changed hardware |
| S2 Connect without navigation influence | Add the remote backend configuration and client, leaving semantic costs disabled. Repeat phase 3 under intended quotas and concurrent load; inject delay, loss, overload, unauthorized access, server restart, duplicate responses, and stale results | Pass all conformance checks and phase 3 gates, including ≥5 fresh masks/s, p95 capture-to-result ≤250 ms, valid cloud pairing, bounded memory, and rejection of late or mismatched results |
| S3 Revalidate navigation | Repeat phase 4 projection/clearing, phase 5 stopping, and phase 6 paired semantic-on/off trials with the remote backend. Include loss of the service during navigation | Pass all original gates, including p95 capture-to-costmap ≤300 ms, the 500 ms stale trigger, command zero within 100 ms of that trigger, and the paired navigation benefit. Do not relax thresholds just to accept remote serving |
| S4 Accept operations and rollback | Verify the warm-replica setting, metrics, restart behavior, credential rotation, controlled version update, and rollback to the accepted local backend | Faults remain visible and stop semantic tasks. Demonstrate operator-authorized recovery and rollback without stale masks, mixed versions, or automatic motion resume |

S1 agreement tolerances must be frozen before comparison and include mask geometry and false-positive/negative changes, not just matching class names. A server that passes HTTP checks but misses the navigation timing gates remains unsuitable for live semantic navigation.

For rollback, stop motion first, invalidate in-flight requests and the observation epoch, clear semantic buffers/maps using the verified procedure, select the accepted local backend, and wait for fresh qualified results. Resume only with explicit operator authorization. Geometry-only operation, if chosen, must be labeled degraded rather than counted as semantic success.

## Later extensions and decision

Multi-robot serving requires an additional concurrency gate proving per-robot identity isolation, fair admission, and per-robot timing under the intended fleet load. Tracking and dynamic prompts require their own session/policy transition tests. Any RMF or multi-floor demonstration must also repeat the applicable phase 8 task and floor-transition checks with remote inference.

Approve the compatibility boundary in the initial semantic-navigation implementation now. Schedule this serving proposal separately after the local SAM3 demonstration passes, preserving its model, interfaces, and acceptance criteria as the migration baseline.
