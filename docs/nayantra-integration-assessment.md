# Nayantra integration assessment for the hotel demo

Review date: 2026-10-12. Status: source review and isolated tests; integration proposed, not deployed.

Reviewed Nayantra revision: [`8c0c0dcc7bb28f201f4630456d409e6757e54218`](https://github.com/shashankbr27/nayantra/tree/8c0c0dcc7bb28f201f4630456d409e6757e54218), dated 2026-06-18. Local platform baseline: `56c6668e9e5babdab7e831edf7f40d36a9a0d9db`.

**Branch scope update:** the subsequent [examples and use-case review](nayantra-examples-and-demo-use-cases.md) also examines September's `dev` and `feat/stub-gazebo` branches. Development adds a real tool-feedback loop, validated schemas, and approval workflows, addressing several main-branch findings below. It also introduces a Nayantra-native fleet orchestrator explicitly separate from Open-RMF. Do not generalize this main-revision audit to those branches; consult the follow-up for current reuse opportunities and reproduced scenario tests.

## 1. Recommendation

**Use Nayantra as a source of agent/tool integration ideas, or as an optional adapted agent above Fleet Copilot. Do not replace our mission gateway, RMF core, Free Fleet adapter, Nav2 stack, or simulator with its complete stack.**

Its useful contributions are a declarative tool registry, three model-provider paths, tool-call traces, and a planner abstraction. However, its current implementation has important protocol, execution, and security gaps. Connecting its default tools directly to `rmf-core-api:8000` would bypass safeguards we already have and would not reliably reproduce its warehouse examples in our multi-floor hotel.

For the smallest useful demonstration, add catalog and mission-observation tools, then let the agent propose a hotel patrol. Keep physical dispatch behind the existing explicit operator confirmation. This would demonstrate grounded tool use and auditable fleet operations; it would **not** introduce a learned Nav2 controller or a new robot-navigation model.

A further practical conclusion: if our only objective is another natural-language lobby/L3 patrol, Nayantra is unnecessary. Our existing copilot already implements that flow. Adoption becomes worthwhile when the demonstration specifically needs broader tool use, provider comparison, or interoperability with external agent clients.

For locally hosted inference, see [Nayantra integration with OpenShift AI Model Serving](nayantra-openshift-ai-model-serving.md). It documents endpoint configuration, tool-calling requirements, the independent migration path for our existing copilot, and live-validation gates.

## 2. What Nayantra actually provides

| Component | Finding at the reviewed revision | Relevance here |
|---|---|---|
| Agent | Python LLM tool calling with Anthropic, OpenAI, and Gemini paths; plan, execute, summarize | Reusable application-layer pattern |
| Tool server | FastAPI `GET /tools`, `POST /run`, and `GET /sse`; 28 registered tools | Requires custom integration; see MCP qualification below |
| RMF HTTP client | Async calls to fleet, task, door, lift, and other endpoints; optional bearer token | Useful API reference, not proof of wire compatibility with our RMF version |
| Planner | Dependency validation and parallel execution groups | Useful abstraction; provider-generated calls do not populate dependencies |
| History/UI | SQLite history of agent results; v2 adds dashboard and WebSocket routes | Tool trace is useful; agent success is not physical mission completion |
| Nav2 bridge | Separate RMF-like REST server controlling a Nav2 action client, or a kinematic stub | Not a substitute for our RMF scheduling and multi-floor integration |
| Simulator/network integrations | Isaac Sim and Zenoh modules and setup instructions | Not required for an HTTP-only agent extension to our Gazebo demo |

Primary implementation sources: [agent][n-agent], [tools][n-tools], [server][n-server], [client][n-client], [planner][n-planner], [history][n-history], [bridge][n-bridge], [Nav2 adapter][n-adapter].

### Models

The reviewed [configuration][n-config] contains `claude-sonnet-4-6`, `gpt-4o`, and `gemini-3.5-flash`. These are repository configuration strings, not independently verified current model availability or recommendations. The agent uses general-purpose model APIs for tool selection and summaries. No Nayantra-specific trained checkpoint, fine-tuned RMF model, or learned Nav2 policy was identified in this source review.

The agent/tool containers do not themselves require a GPU when inference is remote. A locally served model has its own compute requirements. If OpenShift AI serving is the desired next demonstration, evaluate endpoint compatibility, tool-calling behavior, structured output, and latency independently; Nayantra does not establish that compatibility. Our current [provider implementation](../apps/fleet-copilot/copilot/providers.py) already exposes an `OPENAI_BASE_URL` override, so Nayantra is not a prerequisite for testing a compatible model endpoint.

### Available demonstrations and their evidentiary limits

- The [quick start][n-readme] supplies a laptop/stub workflow and a Docker Compose stack. That is a useful software demonstration, not evidence of actual robot execution.
- The author's [May 2026 announcement](https://discourse.openrobotics.org/t/nayantra-natural-language-fleet-control-via-llm-open-rmf-mcp/54876) describes an early release, with end-to-end stub operation and maturing real-robot/Isaac Sim integration.
- An Open Robotics [July 2, 2026 SIG recording](https://vimeo.com/1208218644) is available. Its description presents natural-language package pickup/drop-off, an Isaac Sim warehouse, Nav2, and RViz. The recording's description was reviewed; the physical pipeline and claimed use of full RMF were not independently reproduced here.
- The source includes a separate `rmf_bridge` that emulates an RMF-like API and directly drives Nav2. Its presence means a working Nayantra/robot example must be examined to determine whether it uses genuine RMF task allocation and traffic/infrastructure coordination or this alternate bridge.

This review found useful public implementation and demonstration material, but did not establish a production customer deployment or a validated multi-floor hotel integration.

## 3. Correction to our earlier assessment: live dispatch already exists

The earlier research document relied on an outdated statement in the Fleet Copilot README. The current code and later validation records establish a more capable baseline:

- [The API](../apps/fleet-copilot/copilot/api.py) creates versioned/expiring previews, requires an idempotency key for mission creation, binds RMF task IDs, supports reconciliation on replay, synchronizes task state, and requests cancellation.
- [The bridge](../apps/fleet-copilot/copilot/bridge.py) submits `patrol` requests to `/tasks/dispatch_task`, checks the RMF business-level `success` flag, and extracts `state.booking.id`. It attaches mission/site/episode labels and has a conservative terminal-success predicate.
- [The store](../apps/fleet-copilot/copilot/store.py) persists mission identity, preview scope, dispatch attempts, idempotency keys, and events.
- [G2 evidence](validation/fleet-copilot/phase-2/g2-report.md) records repeated terminal completions and later fault/reconciliation checks. [G3 evidence](validation/fleet-copilot/phase-3/phase-3-report.md) records five independently reset model-driven patrols, same-key replay, unsupported requests being held, and continued robot execution after model disablement.
- [G4 evidence](validation/fleet-copilot/phase-4/phase-4-report.md) documents deterministic evidence-based explanations, but does not claim full G4 acceptance.

These are source capabilities and recorded development results, **not a fresh assertion that today's cluster is healthy**. Production acceptance remains deferred. In particular, the gateway's request-supplied `actor_id` is not authenticated identity, and its current development API must not be described as production-secure.

The integration objective should therefore be **extend and compare the existing copilot**, not complete a supposedly missing dispatch path.

## 4. Source-level findings that prevent drop-in adoption

### 4.1 The advertised MCP server is a custom REST tool interface

The reviewed server exposes REST tool discovery/execution and an SSE tool-result stream. It does not implement the MCP initialization handshake or JSON-RPC `tools/list` and `tools/call` methods. Its registered routes and agent HTTP calls confirm this distinction. Merely using SSE does not make an endpoint MCP-compatible. [Server][n-server], [agent][n-agent].

The official MCP specifications define [initialization and capability negotiation](https://modelcontextprotocol.io/specification/2025-11-25/basic/lifecycle) and [tool discovery/calls](https://modelcontextprotocol.io/specification/2025-11-25/server/tools). A generic MCP client should not be expected to connect directly to Nayantra's reviewed `/sse` endpoint.

**Integration consequence:** either explicitly retain a custom REST tool protocol for a Nayantra-only experiment, or implement a genuine MCP facade over our gateway and adapt the agent/client accordingly. Do not advertise standards interoperability before a conformant client test.

### 4.2 Successful HTTP is conflated with successful execution

`_execute_step()` marks a tool successful whenever `_call_mcp()` returns without an exception. It does not reject a nested RMF `success: false` response. `execute_plan()` then computes mission success from these step results. Even a genuinely accepted dispatch does not establish that the robot has finished. The fallback summary can say the mission completed successfully on this basis. [Agent][n-agent].

An isolated probe returned an HTTP-success-shaped tool result containing an RMF rejection; the step was marked `success`. Keep submission, allocation, execution, cancellation, and freshness distinct, as our gateway already does. Agent history and SSE traces must not become the source of truth for physical completion.

### 4.3 Real RMF task IDs are not propagated correctly

The agent recursively extracts specific key names such as `task_id`, but not `booking.id`. Its comment says it handles this nested example; the implementation does not. A probe using our bridge's expected dispatch response shape produced an empty context. Consequently, later task-state or cancellation calls cannot reliably inherit the actual RMF task ID. [Agent][n-agent], [our bridge](../apps/fleet-copilot/copilot/bridge.py).

Use explicit schema-aware normalization. Keep Nayantra's agent-run ID, our mission ID, the RMF task ID, and the simulation episode ID separate; do not copy arbitrary recursive IDs into a shared context.

### 4.4 The planner is not a complete observe-and-replan agent loop

The planner supports dependencies, but all three provider conversion paths create `ToolCall` objects without setting `depends_on`. Independent calls are executed concurrently. In a mocked model response containing `list_robots` followed by `move_robot`, both calls entered the same execution group. The model does not receive the robot-list result before deciding the move parameters in this flow. [Agent][n-agent], [planner][n-planner].

There is one initial planning request and a later summarization request, not a repeated tool-observation/planning loop. Even a manually supplied dependency only waits for the preceding HTTP call, not for physical arrival.

For our first integration, use a bounded catalog-read → validated-preview workflow and deterministic execution. If richer agent behavior is later required, add a capped tool-feedback loop, explicit dependencies, and resource-aware serialization of mutations. Let RMF execute the full patrol as one task instead of asking an LLM to issue each navigation leg.

### 4.5 Defaults and wire contracts differ from our hotel baseline

Nayantra's `move_robot` emits `navigate_to_waypoint`; its alternate bridge implements that category. Our proven path is a `patrol` over `lobby`, `L3_middle_hallway`, and `lobby`. Do not assume the hotel RMF fleet supports arbitrary navigation, delivery, loop, or charging categories just because Nayantra lists them. Its cancel tool also omits the `type` discriminator included by our bridge. Nayantra inserts an earliest-start value of zero; our bridge deliberately omits request timestamps to let RMF use its active simulation clock. [Tools][n-tools], [alternate bridge][n-bridge], [our bridge](../apps/fleet-copilot/copilot/bridge.py).

The tool schemas do not consistently express required fields, execution lacks per-tool parameter validation, and the system prompt names several tools differently from the registry. Validate a narrow hotel-specific schema server-side; do not depend on the prompt for capability enforcement.

`DEBUG_MODE` defaults to true and causes the RMF client to return simulated data. Compose points the server to `rmf-stub`. A successful demo can therefore make no RMF request at all. The ROS adapter also falls back to stub operation on missing ROS imports. Live mode must fail closed and visibly identify its backend. [Configuration][n-config], [Compose][n-compose], [client][n-client], [adapter][n-adapter].

### 4.6 Retry, authorization, and persistence need adaptation

- Both the agent's tool POST and the RMF client's POST retry transport errors without a stable dispatch idempotency key. A lost response after acceptance can create duplicate side effects. Route dispatch through the existing gateway and preserve its key and uncertain-submission handling. [Agent][n-agent], [client][n-client].
- The tool server has optional JWT checks, but the agent's tool-discovery/execution requests attach no bearer token. The agent API checks for a configured secret at startup but its execution routes do not enforce authentication. Enabling `USE_AUTH` alone is not an end-to-end security solution. [Server][n-server], [agent][n-agent], [API][n-api].
- The registry includes door/lift control, robot decommissioning, and fire-alarm reset. Exclude these capabilities from discovery **and execution** for this demo. RMF must retain infrastructure ownership. Task cancellation is not an emergency stop.
- SQLite agent history is real persistence, but it stores agent-run outcomes; it is not equivalent to our durable pre-dispatch intent, task reconciliation, and mission projection. Preserve our gateway as the execution system of record. [History][n-history].

## 5. Recommended integration architecture

```text
Operator / existing Fleet Copilot UI
       |
       v
Optional adapted Nayantra agent -- model endpoint
       |
       v
Restricted hotel tools (custom REST, or a genuine MCP facade)
       | catalog, preview, mission observations
       v
Existing Fleet Copilot gateway <--- explicit Dispatch from trusted UI
       | validated patrol, stable idempotency key, mission/RMF correlation
       v
rmf-core-api:8000 -> RMF / Free Fleet -> existing Zenoh path -> Nav2
                          |                                  |
                          +-- lifts / doors                  +-- Gazebo robot
```

This is an application-layer addition. Keep `hotel-sim`, `robot-nav-robot-1`, `rmf-core`, and the existing network bridge arrangement unchanged. The [current deployment manifest](../openshift/fleet-copilot-phase1.yaml) already connects Fleet Copilot to `http://rmf-core-api:8000`; no new ROS topic bridge is needed for language/tool traffic.

### Proposed tool-to-API mapping

These tool names are proposals, not existing Nayantra plugins. Paths below are existing Fleet Copilot endpoints.

| Proposed interface | Existing API | Policy |
|---|---|---|
| `list_destinations` | `GET /api/v1/sites/hotel-demo/destinations` | Read-only; return exact canonical names and catalog version |
| `preview_patrol` | `POST /api/v1/mission-previews` | Validate places, rounds, catalog version, and actor/site scope; no robot effect |
| Trusted UI Dispatch, **not a model tool initially** | `POST /api/v1/missions` | Explicit approval of immutable preview; stable `Idempotency-Key` |
| `get_mission` | `GET /api/v1/missions/{mission_id}` | Scope to authorized mission and episode; report freshness |
| Backend refresh | `POST /api/v1/missions/{mission_id}/sync` | Deterministic RMF observation/projection; never dispatch |
| `explain_mission` | `GET /api/v1/missions/{mission_id}/evidence` and `/explanation` | Preserve deterministic evidence and uncertainty |
| Trusted cancellation action | `POST /api/v1/missions/{mission_id}/cancellation` | Confirm target; show requested versus observed canceled state |

Our current UI polls `/sync`; merely subscribing to the SSE mission stream does not itself refresh RMF state. If the agent must monitor without an open browser, add a deterministic background sync worker or make the observation adapter refresh before reading. Do not pay for repeated model calls just to poll task state. [API](../apps/fleet-copilot/copilot/api.py), [UI](../apps/fleet-copilot/ui/app.js).

Fleet/robot listing is not currently a dedicated gateway endpoint. Add a read-only, schema-normalizing gateway adapter if the demonstration needs it, rather than handing the agent unrestricted RMF access. The first version can operate entirely from the approved destination catalog and mission observations.

### Concrete hotel interaction

1. Operator: “Take the robot from the lobby to the third-floor middle hallway and return.”
2. The agent reads the catalog and proposes `places=["lobby", "L3_middle_hallway", "lobby"]`, `rounds=1`.
3. The adapter creates a preview using the returned catalog version. Identity comes from the trusted application session, not model-provided text. Our existing store allows 2–8 places, exactly one round, and a two-minute preview lifetime.
4. The UI shows the route and asks for explicit Dispatch. The trusted application submits the preview ID and a stable idempotency key.
5. The gateway records mission and RMF task identities. RMF owns route execution and Lift2 coordination; the agent does not manually call the lift or issue Nav2 goals.
6. Deterministic sync/evidence updates show allocation, progress, freshness, and terminal outcome. “Accepted,” “waiting,” and “completed” remain distinct.
7. Requests to deliver a package, visit an invented floor, reset a fire alarm, or use an unknown destination are rejected or clarified. A warehouse example does not expand the hotel's supported capabilities.

The approved names come from the [hotel catalog](../apps/fleet-copilot/fixtures/catalog.hotel-demo.json); mission constraints come from the [store](../apps/fleet-copilot/copilot/store.py).

## 6. Integration options and decision

| Option | Benefit | Cost/risk | Assessment |
|---|---|---|---|
| Point unmodified Nayantra at RMF | Quick exploratory HTTP connectivity | Protocol/payload mismatches; bypassed preview/idempotency; misleading success | Do not use for the main demo |
| Adapt Nayantra's agent to restricted gateway tools | Provider comparison and visible tool use while retaining execution controls | Must repair tool loop, auth, schemas, IDs, and outcome reporting | Appropriate if demonstrating Nayantra itself matters |
| Add a genuine MCP facade to our existing copilot | Reusable standards-facing interface; preserves current application | New small service plus protocol/auth tests; not full Nayantra adoption | Preferred if MCP interoperability is the objective |
| Replace our fleet/simulator stack with Nayantra's bridge/Isaac setup | Reproduces its separate warehouse scenario | Loses the established hotel/infrastructure baseline; much broader project | Keep as an independent experiment only |

Do not install Nayantra's direct Nav2 adapter beside our fleet adapter for the same robot: it would introduce another goal-commanding owner. No learned planner/controller or costmap plugin is needed for the recommended integration.

## 7. OpenShift packaging and rollout plan

### Stage A — offline contract tests

Pin the reviewed upstream commit and dependency versions. Define the narrow hotel tools and test them with RMF-shaped fixtures, including `state.booking.id`, `success: false`, stale previews, duplicate requests, unavailable telemetry, and unknown destinations. Include an explicit backend-mode indicator. Keep the original copilot operational.

### Stage B — cluster read-only comparison

Deploy the optional agent and tool adapter as separate application workloads, connected to the existing gateway Service. Initially expose only catalog and scoped observation capabilities. Compare answers against the gateway's recorded state. Use an authenticated application edge; do not expose the raw tool server or RMF API through a public route.

For a real backend, explicitly disable debug/stub operation. Remove fallback tool catalogs that could re-enable disallowed actions during discovery failure. Restrict both advertised tools and server-side handlers. Use NetworkPolicy so the agent reaches only the adapter and selected model endpoint, and the adapter reaches the gateway; the agent should not reach RMF, ROS command endpoints, or infrastructure controls directly.

### Stage C — preview and confirmed dispatch

Add preview creation and retain trusted UI dispatch. Bind authenticated actor/site identity at the application boundary, enforce it server-side, and do not let the model manufacture a confirmation field. For any new facade, make this authorization boundary explicit: the existing development gateway is not sufficient as an internet-facing identity boundary by itself.

Keep one writer/replica while relying on the existing SQLite deployment model; do not casually scale replicas sharing a local database. Mount writable history storage separately if retaining Nayantra history. Build for OpenShift's arbitrary non-root UID, keep secrets out of image layers, and add readiness checks that distinguish model, gateway, and RMF reachability.

The upstream [agent Dockerfile][n-docker] manually installs dependencies and omits `google-genai` despite the source's Gemini support; it launches API v1, whereas the dashboard is added by [API v2][n-v2]. Package the chosen entry point and dependencies deliberately instead of assuming the upstream Compose stack supplies the intended UI/provider combination. No GPU request is needed for these application services when using remote inference.

### Stage D — bounded agent expansion

Only after the simple patrol passes, consider a real MCP transport, model-provider A/B tests, or multi-step read/clarify/preview flows. Record interpretation correctness, inappropriate-tool rejection, preview latency, duplicate-dispatch rate, and independently evidenced robot completion. Do not use the agent's `mission.success` metric as a robotics success measure.

Rollback is an application-level action: disable the optional agent/tool route and continue using the existing copilot. Do not restart or replace the underlying navigation/fleet stack merely to roll back this feature.

## 8. Required acceptance evidence

| Check | Pass condition |
|---|---|
| Grounding | Canonical destinations come from the catalog; unknown floor/delivery/charging requests create no RMF task |
| Human approval | A preview alone does not dispatch; only an authorized explicit confirmation can create a mission |
| Idempotency | Repeated confirmation and lost-response replay create one physical task; uncertain outcomes are reconciled, not blindly resubmitted |
| Business failure | HTTP 200 with RMF rejection is reported as rejected, not mission success |
| Correlation | Agent run, gateway mission, RMF task, and episode identifiers remain distinct and traceable |
| Completion | Repeated lobby → L3 → lobby runs meet the existing terminal predicate; API acceptance is insufficient |
| Model outage | An active RMF mission continues without the agent; model failure cannot trigger extra commands |
| Observation | Backend outage/stale telemetry yields explicit unknown/stale state, not invented progress or ETA |
| Ownership | No new direct Nav2, lift, door, fire-alarm, or velocity-command path exists |
| Authorization | Unauthorized clients cannot preview/dispatch/read others' missions or bypass the restricted tool set |
| Protocol claim | If labeled MCP, an independent compliant client initializes, lists tools, and calls them successfully |
| Mode integrity | Stub/simulation responses cannot be presented as live RMF evidence; missing dependencies fail closed |

These are proposed integration gates, not results of a live Nayantra deployment.

## 9. Verification performed in this review

The upstream repository was cloned into a temporary directory, its source inspected, and its test dependencies installed in an isolated virtual environment. No local application implementation was changed; no cluster deployment, live model request, or robot command was performed.

On macOS with CPython 3.14.5 and dependencies resolved on the review date:

- Upstream suite under the local America/New_York timezone: **184 passed, 1 failed**. `test_create_token_expiry_set` compares a JWT expiry with `datetime.utcnow().timestamp()`, which interprets a naive datetime using local-time rules.
- The same suite with `TZ=UTC`: **185 passed**, with 10 warnings. This isolates the timezone-sensitive assertion; it does not establish production auth correctness.
- The suite's fixtures force debug-friendly settings; passing it is not evidence of real RMF, simulator, model, or physical-robot compatibility.

Reproduction command from the pinned checkout:

```sh
TZ=UTC uv run --extra test pytest tests -q -o addopts=''
```

Additional isolated probes instantiated the agent without provider initialization and replaced network/model calls with mocks. They observed:

```json
{
  "http_200_business_rejection_step_status": "success",
  "booking_id_extracted_context": {},
  "model_generated_step_dependencies": [null, null],
  "execution_groups": [[0, 1]],
  "server_routes": ["/openapi.json", "/docs", "/docs/oauth2-redirect", "/redoc", "/health", "/tools", "/run", "/sse"],
  "registered_tools": 28
}
```

The first probe supplied `{"result":{"success":false,"error":"rejected"}}` to `_execute_step`; the second supplied `{"result":{"success":true,"state":{"booking":{"id":"patrol.dispatch-42"}}}}` to `_extract_ids`. The third mocked a provider response selecting `list_robots` and `move_robot`, then inspected the generated dependencies and planner groups. These are focused implementation checks, not benchmarks or end-to-end robot tests.

## 10. Review decision requested

Choose the objective before implementing: **Nayantra comparison**, **standards-compliant MCP access**, or **a different AI navigation capability**. For the first, adapt only the agent above the gateway; for the second, a small genuine MCP facade over the existing copilot is the more direct investment. For AI that changes robot perception or motion, Nayantra is not the relevant component—use the separately researched Nav2 perception/controller integrations.

[n-readme]: https://github.com/shashankbr27/nayantra/blob/8c0c0dcc7bb28f201f4630456d409e6757e54218/README.md
[n-agent]: https://github.com/shashankbr27/nayantra/blob/8c0c0dcc7bb28f201f4630456d409e6757e54218/nayantra/agent/agent.py
[n-tools]: https://github.com/shashankbr27/nayantra/blob/8c0c0dcc7bb28f201f4630456d409e6757e54218/nayantra/mcp/tools.py
[n-server]: https://github.com/shashankbr27/nayantra/blob/8c0c0dcc7bb28f201f4630456d409e6757e54218/nayantra/mcp/server.py
[n-client]: https://github.com/shashankbr27/nayantra/blob/8c0c0dcc7bb28f201f4630456d409e6757e54218/nayantra/rmf_client/client.py
[n-planner]: https://github.com/shashankbr27/nayantra/blob/8c0c0dcc7bb28f201f4630456d409e6757e54218/nayantra/agent/planner.py
[n-history]: https://github.com/shashankbr27/nayantra/blob/8c0c0dcc7bb28f201f4630456d409e6757e54218/nayantra/agent/history.py
[n-config]: https://github.com/shashankbr27/nayantra/blob/8c0c0dcc7bb28f201f4630456d409e6757e54218/nayantra/config.py
[n-bridge]: https://github.com/shashankbr27/nayantra/blob/8c0c0dcc7bb28f201f4630456d409e6757e54218/nayantra/rmf_bridge/server.py
[n-adapter]: https://github.com/shashankbr27/nayantra/blob/8c0c0dcc7bb28f201f4630456d409e6757e54218/nayantra/ros2_adapter/fleet_adapter.py
[n-compose]: https://github.com/shashankbr27/nayantra/blob/8c0c0dcc7bb28f201f4630456d409e6757e54218/docker/docker-compose.yml
[n-docker]: https://github.com/shashankbr27/nayantra/blob/8c0c0dcc7bb28f201f4630456d409e6757e54218/docker/Dockerfile.agent
[n-api]: https://github.com/shashankbr27/nayantra/blob/8c0c0dcc7bb28f201f4630456d409e6757e54218/nayantra/agent/api.py
[n-v2]: https://github.com/shashankbr27/nayantra/blob/8c0c0dcc7bb28f201f4630456d409e6757e54218/nayantra/agent/api_v2.py
