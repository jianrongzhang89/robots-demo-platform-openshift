# U1 Fleet Copilot: Detailed Design and Gated Implementation Proposal

- **Research date:** October 5, 2026
- **Status:** Proposed design; implementation and phase acceptance have not started.
- **Parent research:** [OpenShift AI for Robotics — U1](openshift-ai-robotics-research-and-use-cases.md#u1-natural-language-fleet-copilot)
- **Baseline:** Jazzy / Gazebo Harmonic / Nav2 / Open-RMF / Zenoh 1.5.0 federated hotel.
- **Delivery strategy:** External model first; migrate to site-local OpenShift AI inference after the application and evaluation contracts are proven.

**Jump to:** [Recommendation](#1-recommendation) · [Repository findings](#3-verified-integration-findings) · [Architecture](#4-application-architecture) · [Contracts](#5-contracts-and-request-flow) · [Recovery](#6-mission-lifecycle-idempotency-and-recovery) · [Telemetry](#7-telemetry-and-evidence-based-answers) · [Models](#8-external-model-first-local-inference-later) · [Implementation](#10-implementation-work-packages) · [Phase gates](#11-phased-delivery-and-acceptance-gates) · [References](#references)

## 1. Recommendation

Build **“Ask, dispatch, and explain”** around the demonstrated patrol:

> “Send the robot from the lobby to the third-floor middle hallway and bring it back.”

The application resolves this to `lobby → L3_middle_hallway → lobby`, displays the resolved mission, submits an ordinary RMF patrol, and answers progress questions from observed events.

Start with an external OpenAI API model, using **`gpt-4.1-mini-2025-04-14` as an evaluation candidate**, because its documented capabilities include Chat Completions, function calling, and structured outputs. It is a reproducible starting candidate, not a claim that it is the newest or best model. Select the actual model by the phase-1 evaluation. [R01]

Use an application-owned model adapter and JSON contracts so that subsequent local inference replaces the model endpoint, credentials, and model/runtime profile. The mission gateway, RMF bridge, state database, UI, and task lifecycle remain the application boundary.

The key design decisions are:

1. **Language creates an intent; application code creates an RMF request.** The model does not generate executable ROS commands or raw RMF JSON.
2. **Task submission and task execution are separately observable.** A queued RMF response is not robot assignment or task completion.
3. **Mission identity is persistent.** HTTP retries and UI reconnects return the same mission; a lost RMF response creates an uncertain submission that is reconciled rather than blindly retried.
4. **State wiring is explicit.** Detailed RMF task state/log updates use the Jazzy WebSocket message protocol; the bridge also consumes local ROS dispatch, robot, navigation, and lift observations.
5. **Every phase has a stop point.** Deliver its implementation, test results, and evidence; obtain explicit acceptance before implementing the next phase.

The external-first milestone demonstrates AI-assisted fleet operations hosted on OpenShift. The later local-serving milestone demonstrates the additional OpenShift AI value: private inference, model/runtime evaluation, versioned deployment, and controlled migration.

## 2. Product scope and operator experience

### 2.1 First supported interactions

| Interaction | Expected behavior |
|---|---|
| Request the known multi-floor return patrol | Resolve exact places, display route and rounds, dispatch once when the operator selects **Dispatch** |
| “What destinations can I use?” | Show the current approved catalog, floor names, and aliases |
| “Where is the robot?” | Show last observed floor/pose, its age, and current mission association |
| “Has it reached the hallway?” | Answer from completed task phases or correlated waypoint-arrival evidence |
| “Why is it waiting?” | Explain supported observations; identify missing/stale evidence when cause is unresolved |
| Unknown or ambiguous location | Ask a specific location question; create no executable mission |
| “Cancel that mission” | Resolve the mission explicitly, request supported cancellation, show pending/observed outcome |

Begin with one site, one RMF-managed robot, one patrol task type, English text, and a browser UI. A patrol visits waypoints; it does not prove physical pickup, payload carriage, or handover. The route specifies visits in order; it does not assert the robot is already at the first waypoint.

### 2.2 Example UI sequence

```text
Operator: Send the robot from the lobby to the third-floor middle hallway
          and bring it back.

Resolved mission:
  Hotel demo / patrol / one round
  Lobby (L1) → Middle hallway (L3) → Lobby (L1)
  Allocation: RMF fleet dispatch
  [Dispatch]

Submission: RMF queued patrol.dispatch-…; allocation pending.
Execution: Assigned to robot_1; heading toward Lift2.

Operator: Why is it waiting?
Answer: The active task event reports waiting for Lift2. Its latest observed
        doors are closed at L1. These observations are 1.2 seconds old.
        [event links]

Completion: RMF reports completed. Final lobby arrival is independently
            observed in this episode. [task and navigation evidence]
```

The mission card, state badges, task ID, and evidence links are rendered from application data, independent of generated prose. If the explanation model is unavailable, the timeline remains usable.

## 3. Verified integration findings

These findings are from repository inspection and upstream source retrieval, not a fresh cluster test. Moving Jazzy branches must be matched to the packages actually deployed at phase 0.

| Finding | Evidence | Design consequence |
|---|---|---|
| The CLI dispatches patrols through `/task_api_requests` and `/task_api_responses` | [Makefile](../Makefile), [local dispatcher](../demo/dispatch_multilevel_task.py), Jazzy `dispatch_patrol.py` [R06] | A long-lived ROS bridge can use the existing task boundary |
| Task API QoS is reliable, transient-local; upstream dispatcher depth is 10 | Local dispatcher and `Dispatcher.cpp` [R07] | Match actual QoS; include retained-request replay in restart testing |
| Initial `success=true` returns a `state` created before bidding completes | `Dispatcher.cpp` [R07] | Read `state.booking.id`; label the response **queued for allocation** |
| Dispatch “finished” entries include tasks handed to fleet adapters | `Dispatcher.cpp` [R07] | `/dispatch_states.finished` is not execution completion |
| Detailed phase, task-state, and task-log JSON is published through a WebSocket client | `TaskManager.cpp` [R08] | Do not invent a `/task_state` ROS topic or rely only on dispatch states |
| Request-ID deduplication is a bounded in-memory response cache | `Dispatcher.cpp` [R07] | Application persistence is required; cache survival cannot be assumed across restart |
| Default dispatcher task IDs use a process-local counter | `Dispatcher.cpp` [R07] | Qualify IDs with episode and RMF generation; validate unique-ID configuration |
| RMF Web HTTP dispatch generates a fresh ROS request UUID per call | `RmfService.call()` [R11] | Use the bridge for submission with application-owned identity; HTTP POST retries are not durable deduplication |
| Fleet-adapter cancellation and dispatcher cancellation have different ownership | `TaskManager.cpp`, `Dispatcher.cpp` [R07, R08] | Cancel bidding via dispatcher service; cancel adapter-owned tasks via task API |
| Empty Helm `serverUri` does not disable the current entrypoint's connection | [values](../helm/multi-robot-demo/values-hotel-nav2.yaml), [entrypoint](../entrypoints/entrypoint-rmf.sh) | `${SERVER_URI:-ws://localhost:8000/_internal}` replaces empty values with localhost; configure explicitly |
| Dispatcher startup currently supplies neither `server_uri` nor `use_sim_time` | Entrypoint | Configure dispatcher telemetry and validate consistent simulation-clock semantics |
| RMF HTTP Service/Routes template excludes hotel mode | [RMF services/routes](../helm/multi-robot-demo/templates/services-routes-rmf.yaml) | A container port does not establish cluster reachability; render the hotel overlay before integration |
| RMF Python/Zenoh code documents a process-separation workaround | Entrypoint clock relay | Keep the new ROS bridge free of an embedded Zenoh Python session |
| Canonical nav graph and building/fleet assets are injected from the hotel image | [RMF deployment](../helm/multi-robot-demo/templates/deployment-rmf-core.yaml) | Generate the destination catalog from the actual mounted assets, not a similarly named source file |
| Builds use moving ROS packages, Free Fleet default branch, and RMF Web Jazzy branch | [Containerfile.rmf](../Containerfile.rmf) | Record image digests, ROS package versions, upstream revisions, and installed adapter contents |

### 3.1 Details that should not be copied from the demonstration script

The local Python script is useful as a transport example, but its production replacement should:

- Generate UUIDs rather than second-resolution request IDs.
- Correlate every response to its request ID instead of accumulating all responses seen on the topic.
- Treat an absent clock as a readiness failure rather than proceeding after a wait expires.
- Construct patrol `description` as `{"places": [...], "rounds": 1}`, matching upstream `dispatch_patrol.py`.
- Avoid the script's `request.assignments` field: the inspected task-request schema has no documented robot-assignment field there. For fleet dispatch, use optional `fleet_name`; explicit robot targeting uses a different `robot_task_request` envelope. [R06, R12]

For U1, retain fleet dispatch and let RMF allocate. With the verified one-robot hotel fleet this should assign `robot_1`; prove that through observed assignment rather than promising it from the language response.

### 3.2 Exact deduplication limitation

The inspected dispatcher caches a response by `ApiRequest.request_id`; `_max_size` is 50. Its `> _max_size` eviction condition permits approximately 51 tracked entries. The useful guarantee is **small, process-local, bounded retention**, not an exact long-term replay window. It does not bind a duplicate request ID to a verified payload hash. [R07]

A transient-local publisher can also replay retained requests to a restarted subscriber. Persistent HTTP idempotency does not prevent this DDS behavior. Section 6 defines the initial supported recovery boundary and a separate extension for durable dispatcher recovery.

## 4. Application architecture

### 4.1 Logical components and initial deployment

```text
Browser / authenticated operator
             │ HTTPS, typed mission/status APIs, SSE timeline
             ▼
fleet-copilot application — separate OpenShift workload
  UI + conversation orchestration
  model adapter ───── external HTTPS model API initially
               └──── site-local OpenShift AI endpoint later
  destination catalog + mission gateway + evidence/state API
             │
             ▼
PostgreSQL — missions, dispatch attempts, events, evaluations
             ▲
             │ staged commands / durable observations
             │
rmf-bridge — sidecar in rmf-core pod, ROS domain 55
  command worker → ROS ApiRequest; ApiResponse correlation
  ROS collector ← dispatch states, clock, robot/nav/lift data
  WebSocket ingress ← dispatcher + fleet task/state/log updates
             │
             ▼
Existing RMF → Free Fleet → Zenoh → Nav2 → hotel-sim
```

Use **two application images**: a ROS-free copilot image and a Jazzy bridge image. Deploy PostgreSQL with persistent storage. Group gateway, catalog, conversation, and state API as modules in one FastAPI application initially; separate services when scaling or ownership requires it. No message broker or vector database is needed for this bounded workflow.

The bridge sidecar shares the RMF pod network and domain-55 DDS context. This avoids new cross-pod DDS discovery or broadening Zenoh task-command routing. It sources the actual Jazzy environment, uses `rmw_cyclonedds_cpp`, and validates discovery against the running RMF nodes.

### 4.2 Explicit task-state ingress

Recommended initial implementation: the bridge exposes a **private, Jazzy-compatible WebSocket receiver** at `ws://127.0.0.1:8100/_internal`. Both the dispatcher and fleet adapter point to it. It accepts validated `task_state_update`, `task_log_update`, `fleet_state_update`, and `fleet_log_update` envelopes and persists normalized evidence. This is new application code reusing an upstream message protocol, not an existing RMF feature in this repository. [R08, R09]

Configure:

- Fleet-adapter server URI explicitly to `ws://127.0.0.1:8100/_internal`.
- Dispatcher `server_uri` explicitly to the same URI.
- Dispatcher `use_sim_time:=true` for the simulation profile, after validating bidding and command-expiry behavior against the baseline.
- Dispatcher `use_unique_hex_string_with_task_id:=true` if available in installed packages; still retain generation-qualified identities.

The receiver starts before adapter registration. Its liveness checks its own event loop; readiness additionally reports database access, schema compatibility, ROS endpoints, and source availability. Buffering is bounded; a dropped event increments a gap counter and invalidates continuity claims.

The existing RMF Web server can remain an optional dashboard consumer via best-effort forwarding of the same envelopes. It is not the new command authority. If using RMF Web instead of the proposed receiver, its Jazzy routes include `GET /tasks/{task_id}/state`, `GET /tasks/{task_id}/log`, label-filtered task queries, and Socket.IO subscriptions. A polling response alone cannot establish telemetry freshness. [R09, R10]

### 4.3 Responsibility boundaries

| Layer | Owns |
|---|---|
| Model | Supported intent extraction, clarification, grounded explanation |
| Copilot orchestrator | Conversation context, bounded model calls, typed read tools |
| Mission gateway | Identity/site scope, semantic validation, catalog version, staged command, request/task mapping |
| Bridge | ROS schemas/QoS, correlated submission response, dispatch/cancel transport, telemetry ingestion |
| State/evidence modules | Event persistence, source age, state projection, causal evidence classification |
| Open-RMF | Bidding/allocation, task phases, schedules, building coordination |
| Nav2 / robot stack | Localization and navigation execution |
| OpenShift AI, later | Local model serving and model/runtime lifecycle |

## 5. Contracts and request flow

### 5.1 Versioned destination catalog

At episode startup, read the mounted RMF nav graph and building/fleet assets. Extract named vertices with floor IDs and fleet reachability, then apply a reviewed alias/visibility configuration. Publish the asset hashes as `catalog_version`.

Initially expose only the validated lobby/hallway demonstration destinations. Lift entry/cabin waypoints are routing infrastructure, not operator mission destinations. The catalog can grow after additional routes are validated.

```json
{
  "site_id": "hotel-demo",
  "catalog_version": "sha256:<mounted-assets-and-aliases>",
  "destinations": [
    {"id": "lobby", "floor_id": "L1", "display_name": "Lobby", "aliases": ["ground-floor lobby", "first-floor lobby"]},
    {"id": "L3_middle_hallway", "floor_id": "L3", "display_name": "Middle hallway", "aliases": ["third-floor middle hallway", "level 3 middle hallway"]}
  ]
}
```

Aliases do not encode a universal meaning of “first floor.” They are site-specific. “Upstairs,” “the hallway,” and “bring it back” require sufficient floor/origin/session context. If the current location is unknown, clarify the return destination; do not invent it from a stale pose.

### 5.2 Model-produced intent

Keep a flat, closed schema for provider portability. All fields are required; unused fields are `null` or empty arrays. Application validators enforce cross-field rules.

```json
{
  "schema_version": "intent.v1",
  "operation": "propose_patrol",
  "places": ["lobby", "L3_middle_hallway", "lobby"],
  "rounds": 1,
  "mission_ref": null,
  "clarification_question": null,
  "unresolved_terms": []
}
```

`operation` is an enum: `propose_patrol`, `list_destinations`, `get_robot_state`, `get_mission`, `explain_delay`, `propose_cancel`, `clarify`, `unsupported`.

For `propose_patrol`, require 2–8 ordered places, each in the current catalog, and initially exactly one round. Other operations must have empty `places` and `rounds=null`. `clarify` requires a question and must not stage a command. Validate strict integer/string types without coercing malformed arguments.

The application supplies site, actor, episode, current catalog, and conversation-selected mission. The model does not supply authorization, timestamps, idempotency keys, generation IDs, or credentials. A self-reported confidence value is unnecessary; semantic validation and held-out evaluation determine reliability.

### 5.3 Resolved mission envelope

After validation, the gateway creates the application mission record:

```json
{
  "schema_version": "mission.v1",
  "mission_id": "<server-generated-uuid>",
  "site_id": "hotel-demo",
  "episode_id": "hotel-run-042",
  "rmf_generation_id": "<rmf-startup-uuid>",
  "catalog_version": "sha256:<assets>",
  "task_type": "patrol",
  "places": ["lobby", "L3_middle_hallway", "lobby"],
  "rounds": 1,
  "allocation": "fleet_dispatch",
  "clock_context": "simulation",
  "actor_id": "<authenticated-operator>",
  "intent_trace_id": "<trace-uuid>"
}
```

The preview is immutable and expires after a proposed two minutes of wall time. On Dispatch, recheck actor scope, active episode/generation, catalog hash, patrol capability, source freshness, and single-mission admission. A map/episode change invalidates the preview. A second deliberate identical patrol uses a new mission identity; fuzzy text similarity is not the deduplication key.

### 5.4 Public application APIs and model tools

All URLs below are proposed application endpoints, not upstream RMF endpoints.

| API | Purpose and important semantics |
|---|---|
| `POST /api/v1/turns` | Persist turn identity; return clarification, validated preview, or evidence-backed answer |
| `GET /api/v1/sites/{site}/destinations` | Current catalog and version |
| `GET /api/v1/sites/{site}/robots/{robot}` | Last observation, source age, episode, mission relation |
| `POST /api/v1/mission-previews` | Deterministic validation and immutable preview; useful for CLI and tests |
| `POST /api/v1/missions` | Consume preview with `Idempotency-Key`; return `202` and a stable mission resource |
| `GET /api/v1/missions/{id}` | Submission, allocation, execution, cancellation, freshness, and RMF identifiers |
| `GET /api/v1/missions/{id}/events` | Ordered persisted evidence; bounded pagination |
| `GET /api/v1/missions/{id}/stream` | SSE updates with event IDs; reconnect via `Last-Event-ID` |
| `POST /api/v1/missions/{id}/cancellation` | Distinct idempotent cancellation operation, with current mission revision |
| `GET /api/v1/health` and `/api/v1/readiness` | Process health and dependency/source readiness |

Return `409` for key/payload conflict or stale preview revision; `422` for invalid destination/capability; `503` when admission dependencies are unavailable. `202` means the application accepted processing, not RMF accepted the task. A same-key replay returns the existing resource and current state.

Expose model tools for `list_destinations`, `get_robot_state`, `get_mission`, and `get_incident_evidence`. A `propose_patrol` tool can create a preview. **Dispatch and cancellation execution are deterministic UI/API transitions**, so repeated model calls cannot independently publish tasks. Do not expose SQL, arbitrary URLs, coordinates, shell, pod exec, or generic ROS publishing as fleet tools. [R14, R15]

### 5.5 Deterministic RMF translation

Create `ApiRequest.request_id` from the persisted dispatch attempt. Construct this JSON in bridge code:

```json
{
  "type": "dispatch_task_request",
  "request": {
    "unix_millis_request_time": 123450,
    "unix_millis_earliest_start_time": 123450,
    "category": "patrol",
    "description": {
      "places": ["lobby", "L3_middle_hallway", "lobby"],
      "rounds": 1
    },
    "requester": "fleet-copilot",
    "labels": ["mission_id=<uuid>", "episode_id=hotel-run-042", "site_id=hotel-demo"]
  }
}
```

The example times are simulation milliseconds, despite the upstream `unix_millis_*` names. For simulation, obtain them from the validated ROS clock; never substitute epoch wall time. A real-robot profile uses the site's validated wall-clock convention. Both application audit wall time and source clock context are stored separately.

Match responses on `request_id`, require the expected response type, validate the pinned response schema, and persist the raw response before updating projections. On success extract `state.booking.id`; on failure preserve structured errors. An unrelated, malformed, or duplicate response cannot advance another mission.

Upstream schema `$id` and `$ref` values may reference `main` even in Jazzy files. Vendor a complete schema set with checksums and resolve references locally; runtime validation must not fetch a moving schema over the network. [R12]

## 6. Mission lifecycle, idempotency, and recovery

### 6.1 Independent state axes

Store these axes rather than compressing every condition into one status:

```text
submission: prepared → pending → publish_attempted → rmf_queued
                                         ├────────→ rejected
                                         └────────→ submission_unknown

allocation: pending → selected → dispatched | failed_to_assign
execution:  unknown → queued → underway / blocked / delayed / error
                                      → completed / failed / canceled / killed
cancellation: none → requested → acknowledged → observed | unresolved
freshness: fresh | stale | source_gap | generation_changed
```

Retain upstream status values and the application mapping version. `blocked`, `delayed`, and `error` are not automatically terminal. `killed` is not completion. A selected winning bid is not proof that the robot began moving. A Nav2 leg result is not proof that all patrol phases completed.

The UI marks **completed** only from a correlated RMF terminal task state. Independently check final lobby arrival for the demonstration outcome; display a discrepancy if RMF completion and navigation evidence disagree. If the last terminal update was missed, retain the last known execution state with a gap marker, not inferred completion.

### 6.2 Durable records and ownership

| Record | Essential fields/constraints |
|---|---|
| `episodes` | Site, episode, simulator startup, active RMF generation, clock convention, catalog/assets hashes |
| `turns` / `previews` | Actor/site, client turn identity, schema/model/prompt versions, resolved preview hash, expiry |
| `missions` | Mission UUID, immutable payload hash, actor/site, episode, current revision and state axes |
| `idempotency_keys` | Unique `(site_id, actor_id, operation, key)` and canonical payload hash → resource ID |
| `dispatch_attempts` | Unique mission dispatch operation, stable request UUID, generation, committed publish marker, raw response/task ID |
| `events` | Event ID, source sequence when available, raw payload reference, clocks, scope, evidence quality |
| `state_snapshots` | Current projection, latest source observations, event cursor, reducer version |
| `evaluations` | Dataset/prompt/schema/model/runtime digests, test counts, failures, acceptance record |

Persist raw observations before projecting them. Join early task updates to an existing mission by its booking labels even if the submission response has not arrived. Deduplicate source log sequences within their source/task/phase scope; do not use a hash of an unchanged robot pose as proof that no heartbeat arrived. Preserve late observations in history, but do not let an earlier queue snapshot overwrite a known terminal state in the same generation. Where sources provide no trustworthy ordering/version, conflicting snapshots are an uncertainty condition rather than an invented total order. Monotonic receipt values are meaningful only within their source process/boot; after restart use persisted wall time and mark continuity until fresh observations arrive.

One bridge worker owns publication per site. Initial deployment uses one replica and a database-backed ownership session; bridge replacement is quiesced and fenced before another publisher starts. A Kubernetes replica count or lease alone does not fence an old process that can still reach ROS. Scale read/model endpoints independently of this publisher.

### 6.3 Publish-once recovery policy

1. In a transaction, validate and insert the immutable mission plus pending dispatch operation. HTTP retry reads this same record.
2. The bridge claims the operation and commits `publish_attempted` **before** the ROS publish call.
3. Publish once with the persisted UUID; a matching response binds the actual RMF task ID.
4. If the response is lost, the worker crashes, or publication is interrupted after the marker, enter `submission_unknown` after a proposed ten-second wall-time response deadline.
5. Reconcile using matching booking labels in observed task state, saved responses, and current dispatcher/fleet evidence. Exactly one label match can bind the task; multiple matches create an explicit conflict.
6. No match is not proof that RMF never received the request. Leave the mission unresolved and stop additional mission admission for this one-robot demo until it is reconciled or the episode is deliberately reset.

This deliberately favors duplicate avoidance over automatic eventual delivery. A crash between the committed marker and actual publish may leave a mission that was never dispatched. The database transaction and ROS publication are not atomic; an ordinary transactional outbox with unconditional replay would reintroduce duplicate-execution risk.

Keep a bounded, per-command transient-local writer; retire it after response or uncertainty deadline, and do not restore historical command writers on application restart. Continue ingesting late responses for known persisted UUIDs. Record publisher discovery and generation; test actual DDS teardown behavior.

### 6.4 Supported restart boundary and retained-message replay

The initial zero-duplicate target covers **UI/HTTP retries, repeated model calls, lost responses, and application/bridge recovery with the same stable RMF dispatcher**. It does not establish exactly-once execution through an arbitrary RMF crash. A dispatcher restarting while a transient-local writer still exists can receive a historical command after losing its cache. [R07]

For controlled RMF/simulator resets:

1. Close mission admission, drain or classify outstanding operations, and retire command writers.
2. Reset the baseline in its documented order; start a new episode and RMF generation.
3. Mark old nonterminal missions `generation_changed`/unresolved; preserve history.
4. Verify no old retained command is dispatched; reopen admission only after readiness.

Test abrupt dispatcher restarts as well. If automatic replay creates a second task, report the failed recovery case and block any claim of transparent RMF crash recovery. To support that guarantee, add a separately accepted RMF hardening work package: persistent request-ID/payload binding and a stable task identity with restart recovery of dispatch/assignment ownership. A wrapper response cache alone does not make the underlying assignment side effect atomic. Task execution recovery also requires fleet-adapter state restoration; the inspected checkpoint callback contains a backup TODO. [R08]

Task identity in the database is `(site, episode, rmf_generation, rmf_task_id)`, not the raw string alone. Idempotency tombstones are retained for the entire demo campaign, even if detailed event history is compacted.

### 6.5 Cancellation

Cancellation is a separate operation with its own identity and evidence:

- A preview or unclaimed pending operation can be canceled locally before publication.
- For dispatcher-owned bidding/selection, call Jazzy `cancel_task` service (`rmf_task_msgs/srv/CancelTask`). Query `get_dispatches` where needed. [R07, R13]
- For adapter-owned queued/running execution, publish `cancel_task_request` with the correlated task ID and application labels. [R08, R12]
- Recheck ownership during a handoff race. A negative dispatcher result does not prove an assigned task cannot be canceled. Use the current adapter-owned path when assignment is observed.
- A positive response means the cancellation request was accepted, not that the robot has stopped. Wait for terminal task/cancellation evidence.
- Unknown task/submission or an unobserved response remains unresolved. “Cancel” is not an emergency-stop control.

Validate queued, underway, lift-wait, already-completed, duplicate-cancel, and dispatch-handoff cases before enabling the cancellation UI.

## 7. Telemetry and evidence-based answers

### 7.1 Sources and correlation

| Source | Use | Correlation/freshness rule |
|---|---|---|
| Task-state/log WebSocket updates | Task phases, assignment, terminal state, active event/log detail | `booking.id`/`task_id`, booking labels, bridge connection generation |
| ROS topic `/dispatch_states` and service `get_dispatches` | Allocation and failed bids | Task ID within RMF generation; not mission completion |
| Fleet state | Robot floor/pose, current activity | Fleet + robot + task identity if provided; preserve observation provenance |
| `/robot_1/amcl_pose`, odometry and supported floor updates | Position and navigation evidence | Match configured frames and floor-map version; do not infer floor from 2D pose alone |
| `/robot_1/rmf_navigate_result` | Individual goal result | Goal UUID must be mapped to mission/task/phase at the adapter |
| `/lift_states` and lift requests | Lift floor/motion/doors and requested destination | Session/request identity plus active task waiting event; mere overlap is contextual evidence |
| ROS `/clock`, source heartbeat and bridge connection events | Simulation readiness, freshness and resets | Store simulator source time and monotonic receipt times separately |

The exact topic names, message types, QoS, floor publication, and bridge forwarding are phase-0/2 discoveries. Existing Zenoh regexes forward selected robot/nav/lift topics; they do not by themselves establish task-to-goal correlation. Add small structured event hooks at the adapter/relay boundary where needed, including mission/task/phase, goal UUID, waypoint, floor, and outcome.

### 7.2 Event envelope and freshness

Every event includes:

```text
event_id, event_type, source, source_instance_id, source_sequence_if_available
site_id, episode_id, rmf_generation_id, fleet_id, robot_id
mission_id_if_known, rmf_task_id_if_known, phase_id_if_known, goal_id_if_known
source_timestamp, source_clock_context, received_at_wall, received_at_monotonic
catalog_version, frame_id_if_relevant, raw_payload_reference
correlation_quality, source_gap, normalization_version
```

Proposed freshness budget: robot/lift observations and task update receipt age **≤5 seconds wall time** under normal load. Derive actual budgets from source publish periods during phase 0. Measure heartbeat/receipt age, source-clock progression, and source observation age separately. A live adapter may republish cached robot position, so a fresh fleet message does not automatically prove fresh sensor data.

An HTTP poll of cached state never resets the source freshness timestamp. SSE replay preserves original observation times. A simulation pause can leave a source timestamp stationary while the connection is alive; display **simulation paused**, not unexplained robot movement or a fresh sensor measurement.

Use wall/monotonic time for API timeouts and freshness. Use simulation time for simulation task timing and lift waits. Explicit reset creates a new episode; backwards source-clock motion triggers a generation/clock check but does not silently rewrite old timestamps. Existing clock relays filter some backwards jumps, so consume episode/reset identity rather than relying exclusively on filtered `/clock`.

### 7.3 Deterministic evidence before language explanation

Implement a small evidence classifier:

| Classification | Required evidence | What the copilot can say |
|---|---|---|
| Allocation pending/failed | Current dispatch state and errors | RMF is still allocating, or no fleet bid was accepted |
| Lift wait | Active task event explicitly waiting for named lift; fresh correlated lift state | Task is waiting for Lift2; report observed floor/doors/session |
| Navigation failure | Task-correlated goal failure and current task event | A navigation leg failed; RMF recovery or task outcome is still pending |
| Telemetry unavailable | Missing heartbeat/source-age threshold exceeded | Position/progress is stale; current delay cause cannot be established |
| Unresolved | Evidence absent, conflicting, or only temporally adjacent | State the observations and the unresolved cause |

Pass a bounded evidence packet to the model, containing factual fields, timestamps, allowed conclusions, and event IDs. Require an answer envelope with `summary`, `claims[{text,evidence_ids}]`, `uncertainties`, and `suggested_next_checks`. Validate IDs against the supplied packet and scope. Render decisive facts such as completion, coordinates, and observation age from the application projection.

Citation existence alone does not prove that prose is entailed by the evidence. Use deterministic templates for critical state facts, human-reviewed evaluation for causal wording, and a fallback evidence card when checks fail. Do not claim predicted ETA accuracy: initially display RMF estimates as RMF estimates, with freshness and clock convention.

## 8. External model first, local inference later

### 8.1 Provider-neutral model adapter

Use Chat Completions as the initial common API surface, with application-owned conversation history. Current vLLM also documents Responses support, but the proposal does not depend on its feature parity with a hosted provider. [R01, R04]

```python
class ModelClient:
    async def generate_intent(self, messages, catalog, schema) -> IntentResult: ...
    async def explain(self, question, evidence, schema) -> ExplanationResult: ...
    async def probe_capabilities(self) -> CapabilityProfile: ...
```

Normalized results include outcome (`ok`, `refused`, `incomplete`, `invalid`, `unavailable`), parsed payload, provider/model identity, finish reason, latency, token usage where available, and trace ID. Provider-specific exceptions never escape into mission-state logic.

Start with an application-directed flow: fetch the current catalog, request one structured intent, validate it, and execute only the required application operations. Optional model-selected **read-only** tools have a maximum of three tool iterations, serial execution, bounded result size, and an overall turn deadline. Enforce these bounds in the application even if provider parallel-tool settings differ.

External requests use `response_format.type=json_schema`, `strict=true`, a closed object schema, and all fields required with nullable unused fields. Local requests use the same schema when supported, or adapter-specific `structured_outputs` configuration. Do not send deprecated vLLM `guided_json` fields. Validate parsed output again at the application boundary. [R02, R05]

### 8.2 External integration profile

| Setting | Initial proposal |
|---|---|
| Provider/API | OpenAI / Chat Completions |
| Model candidate | `gpt-4.1-mini-2025-04-14` |
| Sampling | Temperature 0 where supported; evaluate repeated runs rather than assuming determinism |
| Request bounds | ≤8k input tokens, intent output ≤1k tokens, explanation ≤1.5k tokens |
| Timeout/retry | 15s overall turn budget; at most one bounded transient model retry inside that budget |
| Storage | Application-owned session history; `store=false` where supported |
| Credentials | Project-scoped API key in an OpenShift Secret, mounted only into copilot workload |
| Logging | Versioned trace metadata and redacted examples; no credential logging |

Send text plus the approved destination subset or selected event packet. Raw maps, bag recordings, full pod logs, and unrelated site history are unnecessary. Keep actor authentication and mission execution local to the application.

The provider documents that API content is not used for training by default, while abuse-monitoring logs normally have up to 30-day retention. `store=false` does not mean zero provider retention; Zero Data Retention has separate eligibility/approval and feature limitations. Use the simulated hotel data for the initial external phase and record the actual account settings. [R03]

At the retrieved GPT-4.1 mini prices of $0.40/M input and $1.60/M output tokens, a 2,000-input / 300-output call is approximately **$0.00128**, excluding retries and other calls. Treat this as a dated cost example, not a quote. Measure total model calls/tokens per successful mission and status answer. [R01]

### 8.3 Local inference candidate and sizing

Evaluate `ibm-granite/granite-3.1-8b-instruct` as a first local reference candidate: its model card documents Apache-2.0 licensing, function calling, extraction, and summarization, and stable vLLM documents the `granite` parser and use of its Hugging Face chat template. This is an integration reference, not a requirement to use an older model; newer supported candidates may compete on the same tests. [R15, R16]

For application-directed structured extraction, an automatic-tool parser may not be necessary. If optional automatic read tools are enabled, validate the exact model/tokenizer revision, chat-template digest, tool parser, vLLM build, and decoding backend as one deployment profile. Schema-valid arguments are not necessarily the right destinations. [R05, R15]

Planning estimate for a dense 8B model at BF16: approximately 16 GB decimal weight storage, plus KV cache, activations, runtime overhead, and concurrency. A supported **24 GB-class GPU** is a reasonable starting sizing candidate with an 8k context and low concurrency, not a proven capacity requirement. Quantization changes both capacity and quality and must be reevaluated. Keep inference and Gazebo resource placement separate so inference load does not distort the robot baseline.

### 8.4 OpenShift AI deployment path

1. Inventory actual OpenShift/OpenShift AI versions, installed serving components, accelerator/operator/driver versions, node architecture, storage, and quotas.
2. Select a supported model-serving runtime for that version; deploy a single model instance with immutable model artifact, tokenizer/template, runtime image digest, and decoding profile.
3. Store artifacts in supported S3/PVC/OCI locations; expose the authenticated inference endpoint to the copilot namespace.
4. Warm up the intent/explanation schemas and measure cold/warm latency at demo concurrency.
5. Run the same contract/evaluation suite against both providers. Store evaluation lineage; use MLflow/AI Pipelines when available and useful, while application gates enforce release eligibility.
6. Run local inference in shadow with recorded inputs and read-only state snapshots. Shadow has no command-worker credentials and cannot dispatch.
7. Promote by changing the model-adapter profile after phase-5 acceptance; retain prior profile and schema/prompt versions for rollback.

The October 2 support matrix lists KServe GA in OpenShift AI 3.5 on x86_64 and refers runtime compatibility to Red Hat AI Inference. The retrieved inference matrix maps 3.5 to vLLM 0.24.0; its detailed accelerator tables are labeled 3.4. Verify the actual selected 3.5 image/hardware combination rather than treating those tables as a universal guarantee. Upstream stable vLLM features still require a deployed-runtime capability probe. [R17, R18, R19]

Configuration switches include `MODEL_PROVIDER`, `MODEL_BASE_URL`, `MODEL_ID`, credential Secret reference, `MODEL_PROFILE_VERSION`, and schema/decoding capability profile. An endpoint switch does not automatically remove external egress or prove local-only operation; phase 6 tests that explicitly.

## 9. Deployment, operations, and resource plan

### 9.1 Topology and connectivity

- Keep robotics in `ros2-rmf-hotel`; deploy the bridge sidecar there.
- Deploy copilot and database in a proposed `robot-fleet-copilot` project; keep model serving in the selected OpenShift AI serving project.
- Public route: copilot UI/API only. Scope mission read/dispatch/cancel to authenticated site roles.
- Internal connections: copilot ↔ PostgreSQL, bridge ↔ PostgreSQL, copilot → model endpoint. Bridge telemetry ingress is pod-local. Optional RMF Web forwarding is pod-local.
- Model tools inherit server-side actor/site scope. Client-supplied site IDs are checked against that identity.
- The current RMF Web container includes a demo admin-authentication patch and upstream `_internal` is unauthenticated. Keep those interfaces internal; the copilot's public identity/permissions are implemented separately. [R09]

Proposed initial application resource requests, to be measured: copilot `250m` CPU / `512Mi`, bridge `250m` / `512Mi`, PostgreSQL `250m` / `512Mi` plus a `5Gi` PVC. Begin with one active patrol and five concurrent read/chat users. ROS/vendor dependencies and event volume may require adjustments. No GPU is required in the external-model phase.

### 9.2 Observability and continuity

Track mission/turn/dispatch trace IDs across components. Metrics should include:

- Intent validity and semantic accuracy, clarification rate, model latency/tokens/errors.
- Pending/unknown submissions, actual RMF task creations, payload conflicts, response correlation errors.
- Time to RMF queue, assignment, execution, and terminal evidence.
- Telemetry age by source, missing sequences, reconnects, dropped events, projection lag.
- Citation correctness and unsupported-claim counts from evaluation.
- End-to-end route success and baseline-relative robot duration, separate from interpretation errors.

Model outage leaves submitted missions under RMF/Nav2 control and the deterministic timeline available. Database outage closes new mission admission; it does not cancel current motion. Bounded telemetry buffering reports gaps rather than claiming complete recovery. A bridge outage can miss a terminal event; reconnection alone does not prove that the terminal evidence was recovered.

Retention proposal: 30 days of detailed demo events and evaluations, with mission identities, payload hashes, dispatch attempts, and idempotency tombstones retained throughout the demo campaign. Archive accepted phase evidence before cleanup. Retention policy is application configuration, not implicit provider behavior.

## 10. Implementation work packages

Paths in this table are **proposed additions/changes**, not files already delivered by this proposal.

| Work package | Proposed repository locations | Deliverable |
|---|---|---|
| Shared contracts | `apps/fleet-copilot/contracts/`, `apps/fleet-copilot/schemas/rmf-jazzy/` | Intent/mission/evidence schemas and locally resolved RMF schema bundle |
| Copilot application | `apps/fleet-copilot/copilot/` | FastAPI modules: conversation, providers, catalog, missions, evidence, SSE, identity |
| Bridge | `apps/fleet-copilot/bridge/` | ROS request worker/collector, WebSocket ingress, correlation and ownership |
| Persistence | `apps/fleet-copilot/migrations/` | Database schema, uniqueness constraints, reducers, recovery queries |
| UI | `apps/fleet-copilot/ui/` | Chat, preview/Dispatch, task card, live timeline, evidence and freshness |
| Build | `Containerfile.copilot`, `Containerfile.rmf-bridge` | Pinned ROS-free and ROS-aware images |
| Independent app chart | `helm/fleet-copilot/` | Copilot, PostgreSQL, route, Secrets references, network permissions |
| Robotics overlay | `helm/multi-robot-demo/values-hotel-copilot.yaml` plus RMF template changes | Opt-in bridge, catalog asset mounts, explicit dispatcher/adapter settings |
| Startup wiring | `entrypoints/entrypoint-rmf.sh` | Explicit startup/readiness/generation and clock/URI configuration |
| Correlation hooks | Installed fleet adapter and `entrypoints/nav2_relay.py` | Structured task/phase/goal and floor events; verify actual installed adapter path first |
| Evaluation | `evaluation/fleet-copilot/` | Datasets, provider matrix, RMF emulator, fault scripts, machine-readable reports |
| Operator commands | `Makefile` | Proposed `copilot-evaluate`, `copilot-deploy`, `copilot-smoke`, `copilot-gate` targets |
| Local serving | `deploy/fleet-copilot-model/` | Version-specific runtime/model profile and promotion/rollback configuration |
| Accepted evidence | `docs/validation/fleet-copilot/phase-N/` | Summary and immutable artifact manifest; large captures stored externally |

Use repository-native build/deployment patterns and a dependency lock for the Python applications. Unit tests focus on semantic validators, lifecycle reducers, and recovery boundaries; integration tests use recorded RMF messages and a controllable emulator; live simulation tests prove route and state correlation. Text/schema snapshots alone cannot prove robot outcomes.

## 11. Phased delivery and acceptance gates

**Execution rule:** Implement one phase at a time. At its end publish the test report, demonstrate the required behavior, and stop for acceptance. Tests passing makes the phase eligible for acceptance; it does not authorize proceeding. A failed requirement is fixed/retested or explicitly revised in the phase record before acceptance.

Each phase record contains `phase_id`, prerequisite acceptance reference, Git/image/schema/dataset digests, environment manifest, exact commands, pass/fail counts, failures, evidence locations, and the user's acceptance/hold decision. Decisions can be recorded in conversation and captured in the phase evidence index.

All thresholds below are **proposed demo acceptance targets**, not observed results. Lock them before the phase's held-out evaluation. Changes to model, prompt, catalog, schemas, clock handling, or RMF packages invalidate the affected downstream gate results.

### Phase 0 — Reproduce and inventory the baseline

**Deliver:** Environment/version report, active mounted catalog assets, message/QoS inventory, episode identity plan, and recorded baseline patrol outcomes.

Use the documented reset and dispatch commands, with the actual namespace variable used by the target:

```bash
make restart-hotel-nav2-federated HOTEL_NAV2_RMF_NS=ros2-rmf-hotel
make dispatch-hotel HOTEL_NAV2_RMF_NS=ros2-rmf-hotel HOTEL_WAYPOINTS="lobby L3_middle_hallway lobby" HOTEL_LOOPS=1
```

**Gate G0:**

- Three successful complete baseline runs, each independently reset; preserve RMF assignment/execution and final-lobby evidence.
- Inventory image digests, ROS/RMF package versions, actual adapter source, asset hashes, Zenoh config, clock domains, and available resources.
- Record source publish periods and baseline wall/simulation duration; derive the mission deadline before subsequent tests.
- Confirm existing state/log transport and source availability; document exact changes needed for the bridge.

**Stop:** Obtain baseline acceptance. A navigation failure is resolved here before attributing later failures to AI.

### Phase 1 — External-model interpretation without robot dispatch

**Deliver:** Provider adapter, catalog, intent schema/validator, preview UI, development fixtures, and external-model evaluation report. Tests use mocked fleet tools; no mission publication.

**Gate G1:**

- Freeze a held-out set of **100 supported paraphrases** spanning floor aliases, route order, return semantics, and one-round wording; score exact semantic tuple rather than JSON syntax.
- **≥95/100** correct intents; report by category and raw outputs. Run each case three times and meet the threshold in each run.
- Separate **50 ambiguous/unsupported requests**: every case clarifies or rejects with no executable preview. Include invented floors, room IDs, pickup/delivery, conflicting places, and stale “back here” context.
- Inject refusal, incomplete output, invalid JSON/arguments, 429, timeout, unavailable provider, and hostile tool-result text. Every case has a bounded, explicit result and zero staged dispatches.
- Normal-load interpretation p95 **≤5s**, timeout bounded by the **15s** turn budget, token usage and cost recorded.

**Stop:** Accept model/prompt/schema and preview behavior before RMF integration.

### Phase 2 — Deterministic mission gateway, bridge, and lifecycle

**Deliver:** Database, mission APIs, bridge command/telemetry paths, generation/episode handling, and deterministic UI/timeline. Dispatch through the typed API, without the model.

**Gate G2:**

- Three independently reset API-driven hotel patrols complete within the phase-0 mission deadline; each is linked to one actual RMF task and terminal evidence.
- **100 emulator operations**, each with 10 same-key retries including concurrent calls and gateway restart: one mission identity and at most one bridge publication per operation. Changed payload with same key always conflicts.
- Fault-inject bridge crashes before marker, after marker/before publish, after publish/before response, and after response/before projection. No automatic republish of ambiguous operations; persisted identity survives.
- Live lost-response case reconciles by mission booking labels where evidence exists; no-evidence case remains unknown. No-bid case is shown as failed allocation after initial queued response.
- Foreign/late/duplicate responses and out-of-order state snapshots never complete the wrong mission; history and projections survive application restart.
- Controlled simulator/RMF reset creates a new episode/generation and no historical task replay. Abrupt dispatcher restart is separately tested and classified under section 6.4; transparent crash recovery requires the additional hardening gate.
- Validate canceled-before-publish, queued, running, lift-wait, completed, duplicate, and handoff cancellation semantics; acknowledgment is distinct from observed termination.
- Normal-load source age **≤5s** and projection/UI delay p95 **≤2s** from bridge receipt.

**Stop:** Accept the deterministic control and stated recovery boundary. Do not proceed if the task-state stream cannot substantiate completion.

### Phase 3 — End-to-end external fleet copilot

**Deliver:** Connect phase-1 previews to phase-2 Dispatch/status APIs; complete the customer UI and external-model failure behavior.

**Gate G3:**

- Five independently reset supported natural-language patrols complete with matching preview, mission ID, RMF task ID, assignment, phase progress, and final-lobby outcome.
- Browser double-click, turn retry, model retry, and SSE reconnect create no second dispatch; reloaded UI shows the existing mission.
- Ten unsupported/ambiguous live requests create no RMF task; cross-site requests cannot read or mutate other site state.
- Disable external model access after a mission begins: it continues under RMF/Nav2; task card/timeline stays usable; new language turns report model unavailability.
- Rerun G1 and deterministic submission tests; report language errors separately from RMF/navigation failures.

**Stop:** Accept the external-first “ask and dispatch” milestone before diagnostic fault scenarios.

### Phase 4 — Grounded progress, delay, and recovery explanations

**Deliver:** Correlation hooks, evidence classifier, explanation envelope, evidence UI, and reproducible fault injection.

**Gate G4:**

- Freeze **40 evidence-question fixtures**, ten each for allocation, lift wait, navigation failure, and telemetry loss; ≥95% correct classification/answer and **100% valid scoped evidence IDs**.
- Zero false completion claims; every stale/missing-source fixture explicitly reports uncertainty. Human review checks whether cited evidence supports each causal claim.
- Demonstrate a lift delay and a separate telemetry outage, repeated twice each; answers distinguish actual wait from unavailable progress evidence.
- During delay tests, an active lift-wait task event is mandatory. A closed lift door alone is insufficient to pass the causal explanation gate.
- Simulated pause, backwards clock/reset, missed terminal event, unrelated navigation failure, and conflicting observations produce the defined gap/uncertainty behavior.
- Question-to-answer p95 **≤5s** at normal load; observation age is visible and source facts remain independently inspectable.

**Stop:** Accept the full external-model “ask, dispatch, and explain” demo and its evidence claims.

### Phase 5 — Local OpenShift AI candidate evaluation and shadow

**Deliver:** Supported runtime/model profile, hardware measurements, provider-contract report, local held-out evaluation, and shadow comparison. The external model remains active.

**Gate G5:**

- Inventory validates the selected product/runtime/hardware combination; model, tokenizer/template, image, parser, and decoding configuration are immutable.
- Local endpoint passes all intent/explanation/provider contract fixtures, including nulls, enums, completion/truncation, and capability differences.
- Same G1 thresholds and G4 grounding thresholds are met; local semantic accuracy is no more than **2 percentage points below** the accepted external result and never below 95%.
- Warm p95 **≤5s** at five concurrent turns; no OOM or unbounded queue during a **30-minute** load test. Record cold start/schema warm-up and GPU/RAM utilization.
- Shadow **100 recorded/replayed turns** with identical evidence snapshots; every discrepancy classified. Shadow produces **zero mission mutations** and has no dispatch credentials.
- Evaluation artifacts and promotion profile are saved; rollback to the accepted external profile is rehearsed without submitting a mission.

**Stop:** Accept the local candidate before changing the active provider.

### Phase 6 — Local cutover, local-only operation, and rollback

**Deliver:** Active local serving profile, external-key/egress configuration, final demo runbook, and comparative external/local results.

**Gate G6:**

- Change the adapter profile; no mission contract, gateway translation, or robot command-path changes are needed.
- Five independently reset local-model patrols complete with the same evidence requirements as G3.
- With model artifacts already available, block external provider egress/remove its key: local interpretation, status questions, and three patrol episodes still work. Observe no external model requests.
- Restart local serving during an active patrol: robot execution continues; UI/task facts remain available; language unavailable/recovery is explicit.
- Rehearse provider/profile rollback within a proposed **five minutes**; it does not create, cancel, or replay an existing mission. External rollback requires restoring connectivity/key configuration explicitly.
- Publish final gate report with external versus local accuracy, grounding, latency, resource use, cost, and route outcomes.

**Stop:** Accept the local OpenShift AI demonstration. Subsequent features use new scoped work packages and gates.

## 12. Test corpus, evidence, and customer demonstration

### 12.1 Evaluation design

Keep development prompts/fixtures separate from the held-out corpus. Group paraphrases by underlying wording/template to avoid near-duplicate leakage. Version both the corpus and catalog. On a failed gate, report the failures; after tuning, use a fresh held-out revision for the formal result rather than treating the previously inspected test set as unseen.

Capture expected intent, source state, exact ordered places/rounds, clarification expectation, actor/site scope, and evidence entitlement. Score language semantics separately from structural validity, application rejection, transport result, and navigation outcome.

Use a deterministic RMF emulator for cache eviction, races, reordered responses, worker crashes, and simulated generation changes. Live acceptance validates the actual domain/QoS, label propagation, transient replay, lift travel, terminal task publication, and navigation correlation. Five demo runs do not establish a production reliability percentage; they establish the visible acceptance scenario.

### 12.2 Customer script

1. Show the existing four robotics workloads and active model profile.
2. Enter the lobby-to-L3-and-return request; show resolved catalog destinations.
3. Select Dispatch; show queued versus assigned versus underway, with the real RMF ID.
4. Watch the robot take Lift2 and reach L3; inspect correlated phase/goal evidence.
5. In a separate controlled run, introduce a lift delay and ask why it is waiting.
6. Show the timestamped lift-wait evidence and contrast a telemetry-outage answer.
7. Ask for an unsupported floor; demonstrate a grounded clarification.
8. Show external/local evaluation results and the accepted local-serving profile.
9. Disable external egress; demonstrate site-local inference and another complete patrol.

Measure operator time to submit the correct mission and identify a delay against the CLI/dashboard baseline using matched scenarios. Report participant count, repeat runs, median/p95 and failures. This supports a customer-specific benefit claim; it does not borrow navigation success or cost savings from a model benchmark.

## 13. Next implementation step

**Begin phase 0 only:** capture the actual deployed environment and three baseline patrols, resolve the catalog/message/clock/state inventory, and present G0 evidence for acceptance. The immediate technical priorities are detailed terminal-state visibility, stable identity/recovery semantics, and exact installed adapter/schema compatibility.

## References

Sources were retrieved on October 5, 2026, including research carried forward from the parent investigation. Provider documentation, upstream stable pages, and Jazzy branches are moving sources; pin exact deployed versions at the implementation gates.

| ID | Source | Design evidence |
|---|---|---|
| R01 | [OpenAI GPT-4.1 mini](https://developers.openai.com/api/docs/models/gpt-4.1-mini) | Snapshot, Chat Completions, tools/structured outputs, dated token prices |
| R02 | [OpenAI structured outputs](https://developers.openai.com/api/docs/guides/structured-outputs) | JSON Schema output, strict schemas, refusal/incomplete handling |
| R03 | [OpenAI data controls](https://developers.openai.com/api/docs/guides/your-data) | Training defaults, abuse-monitoring retention, application storage and ZDR distinctions |
| R04 | [vLLM stable online serving](https://docs.vllm.ai/en/stable/serving/online_serving/) | API surfaces, template requirements, parameter compatibility |
| R05 | [vLLM stable structured outputs](https://docs.vllm.ai/en/stable/features/structured_outputs/) | JSON Schema support, decoding backends, deprecated `guided_*` fields |
| R06 | [Jazzy dispatch_patrol.py](https://github.com/open-rmf/rmf_demos/blob/jazzy/rmf_demos_tasks/rmf_demos_tasks/dispatch_patrol.py) | Exact patrol envelope, dispatch versus direct request, UUID/QoS/clock |
| R07 | [Jazzy Dispatcher.cpp](https://github.com/open-rmf/rmf_ros2/blob/jazzy/rmf_task_ros2/src/rmf_task_ros2/Dispatcher.cpp) | Initial queue acknowledgment, bounded cache, allocation/cancel semantics, ID generation |
| R08 | [Jazzy TaskManager.cpp](https://github.com/open-rmf/rmf_ros2/blob/jazzy/rmf_fleet_adapter/src/rmf_fleet_adapter/TaskManager.cpp) | Task-state/log WebSocket publication, terminal update, cancellation, checkpoint limits |
| R09 | [Jazzy RMF Web internal receiver](https://github.com/open-rmf/rmf-web/blob/jazzy/packages/api-server/api_server/routes/internal.py) | `_internal` update envelopes and state/log processing |
| R10 | [Jazzy RMF Web task routes](https://github.com/open-rmf/rmf-web/blob/jazzy/packages/api-server/api_server/routes/tasks/tasks.py) | State/log reads, label queries, subscriptions, HTTP task operations |
| R11 | [Jazzy RMF Web RmfService](https://github.com/open-rmf/rmf-web/blob/jazzy/packages/api-server/api_server/rmf_io/rmf_service.py) | Fresh UUID per call, timeout, duplicate/out-of-order response protocol |
| R12 | [Jazzy RMF API schema directory](https://github.com/open-rmf/rmf_api_msgs/tree/jazzy/rmf_api_msgs/schemas) | `task_request`, `task_state`, `dispatch_task_response`, `cancel_task_request` schemas |
| R13 | [Jazzy RMF task standard names](https://github.com/open-rmf/rmf_ros2/blob/jazzy/rmf_task_ros2/include/rmf_task_ros2/StandardNames.hpp) | `cancel_task`, `get_dispatches`, dispatch-state topic names |
| R14 | [OpenAI function calling](https://developers.openai.com/api/docs/guides/function-calling) | Application-executed tools and strict argument contracts |
| R15 | [vLLM stable tool calling](https://docs.vllm.ai/en/stable/features/tool_calling/) | Model/parser/template coupling, caller responsibilities, Granite examples |
| R16 | [Granite 3.1 8B Instruct model card](https://huggingface.co/ibm-granite/granite-3.1-8b-instruct) | Apache-2.0, model size, extraction/summarization/function-calling capabilities |
| R17 | [OpenShift AI 3.x supported configurations](https://access.redhat.com/articles/rhoai-supported-configs-3.x) | Product/architecture/serving support; October 2 matrix |
| R18 | [Red Hat AI Inference supported configurations](https://access.redhat.com/articles/rhaii-supported-configs) | Product/vLLM mapping, hardware/runtime and quantization distinctions |
| R19 | [Open Data Hub documentation source: model serving](https://github.com/opendatahub-io/opendatahub-documentation/blob/main/modules/about-model-serving.adoc) | Serving endpoints, KServe mechanism, artifact storage choices; upstream explanatory source |

### Repository evidence

- [README.md](../README.md) and [MULTI-LEVEL-NAVIGATION-DEMO.md](../MULTI-LEVEL-NAVIGATION-DEMO.md): supported hotel baseline and reset behavior.
- [Makefile](../Makefile): actual `dispatch-hotel` target and namespace/waypoint arguments.
- [demo/dispatch_multilevel_task.py](../demo/dispatch_multilevel_task.py): current ROS request/response example.
- [Containerfile.rmf](../Containerfile.rmf): dependencies, source builds and demo RMF Web patch.
- [entrypoints/entrypoint-rmf.sh](../entrypoints/entrypoint-rmf.sh): domain, clocks, server URI, dispatcher and adapter startup.
- [patches/fleet_adapter.py](../patches/fleet_adapter.py), [patches/nav2_robot_adapter.py](../patches/nav2_robot_adapter.py), [entrypoints/nav2_relay.py](../entrypoints/nav2_relay.py): configuration and navigation/lift integration; installed image contents still require verification.
- [Hotel values](../helm/multi-robot-demo/values-hotel-nav2.yaml), [RMF deployment](../helm/multi-robot-demo/templates/deployment-rmf-core.yaml), [RMF Service/Routes](../helm/multi-robot-demo/templates/services-routes-rmf.yaml), [Zenoh ConfigMap](../helm/multi-robot-demo/templates/configmap-zenoh.yaml): deployment conditions, actual assets, and selected topic routing.
