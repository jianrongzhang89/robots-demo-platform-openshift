# Nayantra examples and useful extensions for the hotel demo

Research date: 2026-10-12.

Nayantra has concrete author demos and executable scenario tests, but the public material located does not establish an independent production deployment. Its most useful contributions to our hotel demo are conversational operations, recovery from invalid requests, and visible task/approval traces. A delivery workflow offers a stronger business story, but needs additional application and robot-task semantics.

The September development branch is materially different from the older main branch: it contains a Nayantra-native fleet orchestrator, not an Open-RMF deployment. Borrow its agent and operator-interface patterns while retaining our existing gateway, RMF, Free Fleet, and Nav2 execution path.

These application patterns can use a model hosted in our cluster. The [OpenShift AI Model Serving follow-up](nayantra-openshift-ai-model-serving.md) covers the inference connection, configuration differences between Nayantra and the existing copilot, and the required validation before enabling robot dispatch.

## Branches change the assessment

| Source | Revision inspected | What it contains |
|---|---|---|
| `main` | `8c0c0dcc7bb28f201f4630456d409e6757e54218`, June 18 | Earlier agent, custom REST tool interface, RMF client, and a single-robot RMF-like bridge |
| `dev` | `8c04b25bf599dbd40f7cede60392bc8f206c44cc`, September 29 | New core, operator UI, validated tools, provider-independent tool-feedback loop, task traces, allocation explanations, and approval workflows |
| `feat/stub-gazebo` | `effcd4c163abd7321236281026dc5065dd96c1f5`, September 29 | New-core variant with a Gazebo warehouse backend and documented kinematic stub mode |

The [development README][dev-readme] explicitly identifies its core as separate from Open-RMF. It also says the new Nav2 adapter has not yet been exercised against a live Nav2 stack and that multi-robot Isaac Sim is not wired up. The [Gazebo branch documentation][gazebo-doc] says its assets are consistency-tested but have not been run against live Gazebo and Nav2.

Our [earlier integration assessment](nayantra-integration-assessment.md) remains an audit of the pinned **main** revision. Several of its agent criticisms are addressed in `dev`: a bounded tool-feedback loop replaces single-shot planning, Pydantic validates tool arguments, and structured tool errors are fed back to the model. These changes make `dev` a better source for reusable agent patterns. They do not make its core a drop-in RMF extension. Its [tool server][dev-server] still explicitly uses custom REST rather than the MCP JSON-RPC wire protocol.

## Concrete examples and what they establish

### Public warehouse demonstration

Open Robotics hosted a Nayantra presentation at the July 2, 2026 Interoperability SIG. The [announcement][sig] and [recording description][video] describe a natural-language pickup/drop-off request, an Isaac Sim warehouse robot, Nav2, and RViz. This is the clearest public presentation to review for the intended end-user experience.

The implementation contains distinct execution paths: [`nav_cli.py`][nav-cli] maps requests to Nav2 goals directly, whereas [`drive_cli.py`][drive-cli] controls a kinematic Isaac demo through HTTP. Neither path, by itself, demonstrates Open-RMF allocation or traffic coordination. The recording description does not resolve which backend was used for every demonstrated segment; the entire recording was not independently analyzed here.

**Useful idea:** a named service request that becomes an ordered workflow, with the robot and command trace visible together. **Do not infer:** production parcel handling, multi-floor delivery, or full RMF interoperability from that presentation alone.

### Reproducible navigation and delivery smoke scenario

The main branch's [`runtime/smoke_bridge.py`][smoke] exercises real bridge code in its explicitly labeled kinematic simulator:

1. Read the building's named waypoints.
2. Dispatch navigation to `zone_c` and poll for completion.
3. Reject the unknown destination `narnia` with HTTP 400.
4. Dispatch delivery from `zone_c` to `elevator_lobby` and poll for completion.

This script passed during this review with `ROS2_ENABLED=false`. Its delivery implementation navigates to pickup, waits two seconds, navigates to drop-off, then waits two seconds. There is no verified parcel manipulation or handoff sensor in this example. An `elevator_lobby` waypoint does not establish elevator integration. [Bridge implementation][main-bridge].

**Useful idea:** explicit task stages, known-place validation, and completion checks. **Evidence level:** reproduced software simulation, with no LLM, ROS, Nav2, Gazebo, or genuine RMF in this test.

### Batch delivery with capability-based allocation

The development branch's [`test_agent_loop.py`][agent-tests] supplies a scripted model response for a request to move three packages from receiving to storage. The agent creates three tasks, the core assigns three different robots, and each task retains the originating command and agent mission ID.

A separate [`test_delivery_is_allocated_by_capability`][core-tests] checks that the chosen robot can carry a payload, rejects a UAV candidate without that capability, resolves receiving/storage areas to concrete destinations, and waits for simulated completion. The [allocator][allocator] evaluates capabilities, reachability, battery, queue, and cost; these decisions are deterministic code, not a learned scheduling model.

**Useful idea:** show both the chosen robot and the reason for its eligibility. **Evidence level:** executable in-process tests, using a scripted LLM and kinematic robot fixtures—not a demonstrated heterogeneous physical fleet. Our current single-robot hotel cannot show meaningful robot-choice comparisons yet.

### Error correction through tool feedback

The development agent tests first submit a misspelled receiving-bay destination, receive an error with a suggested valid place, then submit a corrected request. Other tests reject an unsupported task type and verify that tool results are returned to the provider. [Tests][agent-tests], [agent implementation][dev-agent].

**Useful idea:** allow the assistant to recover from a malformed request using the authoritative catalog, rather than ending at the first parsing error. For our demo, ambiguous corrections must still ask the operator and produce a new preview before dispatch.

**Evidence level:** the test scripts both model responses. It proves the feedback plumbing works, not that a real model reliably chooses the right correction. Real-provider evaluation remains necessary.

### Operator approval and operational explanations

The development branch contains task-status tools with wait reasons, allocation explanations, origin information, and recent events. Its operator UI includes task and robot inspection views. Tests cover pending approval for broad stop requests, refusal of confirmation from the tool-client path, restricted destinations, and task pause/resume/cancel. [Tools][dev-tools], [API tests][core-tests].

**Useful idea:** pair natural-language requests with explicit task state and a visible human decision point. However, the core distinguishes client type using an `X-Nayantra-Client` header; that is not authenticated identity. Reuse the interaction pattern, not an assumption that it supplies production authorization. [API source][dev-api].

A physical emergency stop must remain available independently of the model and must not wait for conversational approval. The proposed hotel extension uses ordinary task confirmation/cancellation, not Nayantra's stop-all example as a safety-system design.

### Gazebo warehouse and multi-robot traffic scenarios

The Gazebo branch defines two namespaced ground robots, per-robot Nav2 instances, and a generated warehouse world. It derives physical obstacles and the planning map from shared configuration. The development traffic tests exercise intersections, opposing traffic in narrow corridors, restricted zones, idle blockers, and replanning. [Gazebo architecture][gazebo-doc], [traffic tests][traffic-tests].

**Useful idea:** use repeatable conflict scenarios and consistent map assets for regression testing. **Evidence level:** the traffic cases are software tests; the Gazebo integration is explicitly not live-validated. Its ground-truth odometry and static map transform should not replace our AMCL and multi-floor map handling.

## Independent adoption search

Searches covered Nayantra with robot, demo, deployment, warehouse, hotel, and Isaac terms; Open Robotics posts; GitHub repositories including forks; public branches; and linked project listings.

The [public fork list][fork-api] returned `Scaler2026/nayantra`. The [comparison with upstream main][fork-compare] showed zero commits ahead and eight behind. That fork does not provide evidence of a separate downstream implementation. Public repository searches also returned unrelated projects sharing the name; these were excluded.

Community catalog mentions and reposts link back to the original project. They are discovery references, not deployment reports. In particular, [`nullbyte91/nvidia-isaac-mcp`](https://github.com/nullbyte91/nvidia-isaac-mcp) is a separate Isaac scene-control project, not an established Nayantra derivative, despite a misleading fleet-control description in a third-party list.

**Conclusion:** there are useful author examples and testable implementations, but no independently documented Nayantra customer deployment was verified in this search. That is a limit of the public evidence, not proof that private deployments do not exist.

## Use cases that would benefit our demo

These are proposed adaptations, not existing Nayantra deployments in our environment. Priority reflects incremental value over our current hotel copilot.

| Priority | Use case | Benefit beyond the current patrol | Required work |
|---|---|---|---|
| 1 | Conversational mission diagnosis | Answer follow-up questions from live mission evidence instead of requiring the audience to interpret a status card | Read-only tools, mission/session binding, freshness checks, bounded tool-feedback loop |
| 2 | Grounded clarification and request correction | Demonstrate catalog discovery, useful clarification, and recovery without guessing or dispatching early | Error-to-model feedback, disambiguation policy, preview regeneration, real-model evaluations |
| 3 | Hotel service request with handoff confirmation | Turn robot movement into a recognizable business workflow with a request, delivery stages, and closure | New workflow state, pickup/drop-off acknowledgements, task composition, cancellation/recovery rules |
| 4 | Searchable request-to-task trace | Let operators ask what happened to a request and distinguish request acceptance from delivery completion | Correlate business request, agent turn, preview, mission, RMF task, and handoff events |
| Later | Explainable multi-robot assignment | Show why a capable available robot was selected and why another was not | Second robot/fleet, supported capability data, and actual RMF allocation evidence |
| Engineering support | Offline scenario rehearsal | Repeat invalid requests, model errors, stale telemetry, and duplicates without restarting the full simulation | Gateway-shaped fixtures and tests; explicitly separate replay/stub data from live evidence |

### First extension to build

Add an operations conversation over the existing patrol and evidence API:

- “What destinations are available?” → read the approved hotel catalog.
- “Send it to the third-floor hallway and return.” → create a preview; do not dispatch until confirmed.
- “Why has it stopped?” → synchronize the bound mission and read its evidence.
- “Has it finished?” → report the correlated RMF terminal result, or explicitly say completion is not established.

Our [UI](../apps/fleet-copilot/ui/app.js) already shows deterministic evidence. The new value is conversational follow-up grounded in the right mission—not another generic model-generated explanation. A lift-wait observation may support “an active lift event is pending,” but not “the elevator is crowded” unless another trusted source supplies that fact. Unknown cause, stale telemetry, and missing ETA must remain explicit. [Evidence classifier](../apps/fleet-copilot/copilot/evidence.py).

Success criteria: correct mission binding, evidence references for operational claims, no invented cause/ETA, no new dispatch from a status question, and continued mission execution when the model is unavailable.

### Stronger customer-facing extension

Use a request such as “Take the guest supplies from the lobby to the third-floor handoff point and return.” Initially associate the handoff point with the existing approved hallway waypoint; do not invent a room destination or claim package sensing.

A useful workflow is:

```text
Service request → operator approval → pickup acknowledgement
→ outbound RMF mission → arrival evidence → recipient acknowledgement
→ return RMF mission → service request closed
```

This requires more than renaming the existing round-trip patrol. The robot must remain at the destination until the handoff is acknowledged, with timeout and cancellation behavior defined. Model-generated text must not count as a pickup or recipient acknowledgement. A simple first implementation could compose separately tracked outbound and return navigation missions around application-level human confirmations; actual RMF delivery actions are a later option if the fleet supports them.

Our current model contract explicitly rejects delivery requests. This extension therefore needs deliberate changes to the intent schema, validator, gateway workflow, and tests. Preserve that rejection until those changes are implemented. Nayantra's two-second dwell is not sufficient evidence that a package was transferred. [Current provider contract](../apps/fleet-copilot/copilot/providers.py), [mission API](../apps/fleet-copilot/copilot/api.py).

Success criteria: a traceable service request, exactly one task per intended leg despite retries, no return before valid handoff acknowledgement, and separate navigation-complete and service-complete states. These are proposed benefits and gates, not measured improvements.

### What to leave out

Do not add a second traffic scheduler, a second direct Nav2 goal source, or model-driven lift commands. Avoid presenting kinematic UAV/quadruped/humanoid fixtures as real heterogeneous hardware. Do not use robot registration or an unvalidated Gazebo port as the centerpiece when our existing hotel already executes multi-floor missions.

For multi-robot allocation, retain RMF as the decision-maker. Borrow Nayantra's explanatory presentation only when our stack exposes the supporting candidate/bid data; otherwise report the selected fleet and unavailable rationale honestly.

## Verification and next step

At the pinned main revision, the kinematic navigation/delivery smoke script passed with ROS disabled. At the pinned development revision, the following selected suites passed: **34 tests in 44.22 seconds**, using CPython 3.14.5 and UTC:

```sh
TZ=UTC uv run --extra test pytest tests/test_agent_loop.py tests/core/test_core_api.py tests/core/test_core_traffic.py -q -o addopts=''
```

These tests cover real application code with local simulated robot state and scripted model responses. No live model, ROS/Gazebo deployment, Open-RMF cluster, or physical robot was exercised. The new Nav2 adapter and Gazebo branch remain subject to the upstream live-validation limitations.

**Recommended next step:** implement the read-only mission conversation and grounded clarification on our existing copilot, using the development agent's tool-feedback pattern. Then add the service-request and handoff workflow if the goal is a richer business demonstration. This gives us visible, testable benefits without replacing the proven hotel robotics path.

[dev-readme]: https://github.com/shashankbr27/nayantra/blob/8c04b25bf599dbd40f7cede60392bc8f206c44cc/README.md
[dev-agent]: https://github.com/shashankbr27/nayantra/blob/8c04b25bf599dbd40f7cede60392bc8f206c44cc/nayantra/agent/agent.py
[dev-tools]: https://github.com/shashankbr27/nayantra/blob/8c04b25bf599dbd40f7cede60392bc8f206c44cc/nayantra/mcp/tools.py
[dev-server]: https://github.com/shashankbr27/nayantra/blob/8c04b25bf599dbd40f7cede60392bc8f206c44cc/nayantra/mcp/server.py
[dev-api]: https://github.com/shashankbr27/nayantra/blob/8c04b25bf599dbd40f7cede60392bc8f206c44cc/nayantra/core/api.py
[allocator]: https://github.com/shashankbr27/nayantra/blob/8c04b25bf599dbd40f7cede60392bc8f206c44cc/nayantra/core/allocation.py
[agent-tests]: https://github.com/shashankbr27/nayantra/blob/8c04b25bf599dbd40f7cede60392bc8f206c44cc/tests/test_agent_loop.py
[core-tests]: https://github.com/shashankbr27/nayantra/blob/8c04b25bf599dbd40f7cede60392bc8f206c44cc/tests/core/test_core_api.py
[traffic-tests]: https://github.com/shashankbr27/nayantra/blob/8c04b25bf599dbd40f7cede60392bc8f206c44cc/tests/core/test_core_traffic.py
[gazebo-doc]: https://github.com/shashankbr27/nayantra/blob/effcd4c163abd7321236281026dc5065dd96c1f5/docs/gazebo_architecture.md
[nav-cli]: https://github.com/shashankbr27/nayantra/blob/8c04b25bf599dbd40f7cede60392bc8f206c44cc/scripts/nav_cli.py
[drive-cli]: https://github.com/shashankbr27/nayantra/blob/8c04b25bf599dbd40f7cede60392bc8f206c44cc/scripts/drive_cli.py
[smoke]: https://github.com/shashankbr27/nayantra/blob/8c0c0dcc7bb28f201f4630456d409e6757e54218/runtime/smoke_bridge.py
[main-bridge]: https://github.com/shashankbr27/nayantra/blob/8c0c0dcc7bb28f201f4630456d409e6757e54218/nayantra/rmf_bridge/server.py
[sig]: https://discourse.openrobotics.org/t/interop-sig-02-july-2026-natural-language-control-of-open-rmf-fleets-via-the-model-context-protocol-mcp/55687
[video]: https://vimeo.com/1208218644
[fork-api]: https://api.github.com/repos/shashankbr27/nayantra/forks?per_page=100
[fork-compare]: https://api.github.com/repos/shashankbr27/nayantra/compare/main...Scaler2026:main
