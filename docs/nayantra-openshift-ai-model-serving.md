# Nayantra integration with OpenShift AI Model Serving

Review date: 2026-10-12. Status: feasible integration design; live model-serving compatibility not yet validated.

**Nayantra can use a locally hosted model served by OpenShift AI through an OpenAI-compatible inference endpoint.** Replace the external model connection, not the hotel robotics stack. An adapted Nayantra agent would continue to use restricted tools over Fleet Copilot, with the existing gateway, Open-RMF, Free Fleet, and Nav2 responsible for authorized robot execution.

Here, local means hosted in our OpenShift environment, potentially on premises. It does not mean inference runs onboard the robot. The benefit is control over model hosting and versions, with the option to keep inference traffic inside the managed environment. Lower latency, lower cost, and equivalent model quality are evaluation questions, not guaranteed outcomes.

## Compatibility basis and scope

Red Hat documents an OpenAI-compatible vLLM runtime with `/v1/models` and `/v1/chat/completions` endpoints. Token-protected deployments require an authorization token. The model endpoint and supported runtime must be taken from the actual deployment. [OpenShift AI inference documentation][rhoai-inference].

The reviewed Nayantra development revision, `8c04b25bf599dbd40f7cede60392bc8f206c44cc`, uses `AsyncOpenAI` in `_OpenAIProvider`. It sends Chat Completions requests with tool definitions and `tool_choice="auto"`, then returns tool results to the model on subsequent turns. The SDK supports a custom `base_url` or the process environment variable `OPENAI_BASE_URL`. [Nayantra provider][n-agent], [official OpenAI SDK documentation][sdk].

This supports a configuration-led connection to OpenShift AI, but does not establish compatibility with every model or runtime. A successful ordinary chat response is insufficient: the selected model must produce usable structured tool calls and handle their results across multiple turns.

The September Nayantra development branch also contains its own fleet-control core, explicitly separate from Open-RMF. This proposal reuses its **agent pattern**, not that replacement orchestrator. Its REST tool protocol is also separate from the model inference API: adopting local model serving neither requires nor fixes standards-compliant MCP transport. [Branch and use-case assessment](nayantra-examples-and-demo-use-cases.md).

## Component responsibilities

| Component | Responsibility | Boundary to preserve |
|---|---|---|
| OpenShift AI model-serving deployment | Host the selected model and answer inference requests | Does not execute robot tools or own mission state |
| Adapted Nayantra agent | Conversation, bounded tool-use loop, interpretation, grounded answers | Can invoke only the approved application tools |
| Restricted hotel tool adapter | Expose catalog, preview, and scoped mission observations | Enforce schema, identity, and capability checks server-side |
| Fleet Copilot gateway | Immutable previews, confirmed dispatch, idempotency, RMF correlation, mission evidence | Remains the execution system of record |
| RMF, Free Fleet, and Nav2 | Task allocation, infrastructure coordination, navigation, and robot execution | No direct LLM velocity, navigation-goal, or lift-control path |

The agent sends conversation and tool schemas to the model endpoint, receives a proposed tool call, invokes the allowed application tool, and returns its result to the model. OpenShift AI supplies inference; the application still implements and authorizes the tools.

## Nayantra endpoint configuration

The following is an illustrative **container environment fragment**, not a deployment manifest ready to apply. Replace the endpoint, served-model name, and Secret reference with values from the actual deployment.

```yaml
env:
  - name: LLM_PROVIDER
    value: openai
  - name: OPENAI_BASE_URL
    value: https://<model-inference-host>/v1
  - name: OPENAI_MODEL
    value: <served-model-name>
  - name: OPENAI_API_KEY
    valueFrom:
      secretKeyRef:
        name: fleet-model-access
        key: token
```

`openai` selects the client/API format, not OpenAI's cloud service. `OPENAI_API_KEY` holds the configured model endpoint's bearer token, not necessarily an OpenAI-issued key. Store only the token value, without the `Bearer ` prefix. Keep the endpoint explicit so an omitted setting cannot silently use the SDK's public-cloud default.

The base URL is the API root, normally ending in `/v1` for a direct vLLM endpoint, **not** the full `/v1/chat/completions` URL. Preserve any deployment-specific path prefix. `OPENAI_MODEL` must match the served model identifier, not merely a model-family label or a guessed Kubernetes resource name.

Set `OPENAI_BASE_URL` in the actual process/container environment. The reviewed [Nayantra settings class][n-config] does not declare that field and ignores extra settings. Adding it only to a file consumed by Pydantic settings does not ensure that it becomes visible to the SDK. An alternative implementation is to add an explicit base-URL setting and pass it to the client constructor.

Before deployment, also make timeout and output-token limits explicit, verify certificate trust, and define token refresh or application restart behavior for expiring credentials. Pin the client dependency version with the validated model/runtime combination.

## Model and runtime requirements

Select self-hostable model weights with a license appropriate to the demo. Nayantra's hosted Claude/GPT model defaults are not weights that can simply be copied into OpenShift AI. No RMF-specific fine-tuning is required to start; model selection should be driven by performance on the restricted hotel tools and prompts.

For Nayantra's automatic tool selection, vLLM configuration typically includes:

```text
--enable-auto-tool-choice
--tool-call-parser=<parser-compatible-with-the-model>
```

Use a compatible chat template that represents tool definitions, assistant tool calls, and tool-result messages. Supply `--chat-template=<path>` when the model's packaged template is insufficient. Parser names and template requirements vary with the model and runtime release; verify against the version shipped in the installed OpenShift AI environment. [vLLM tool-calling documentation][vllm-tools].

The acceptance check must inspect structured `tool_calls`, valid JSON arguments, tool-call identifiers, and successful consumption of tool results on the next turn. Raw text that merely looks like a function call is not sufficient. Keep gateway validation even if the runtime constrains output syntax: syntactically valid arguments can still request an unsupported destination or operation.

Size the serving deployment for model weights, context/KV-cache needs, output length, and expected concurrent requests. No particular model, GPU quantity, or memory requirement is selected here because the available accelerators and installed runtime have not been established. The HTTP agent and tool adapter do not themselves require a GPU when inference is offloaded to the model-serving workload.

## The existing copilot can migrate independently

Nayantra is optional for local inference. Our current [Fleet Copilot provider](../apps/fleet-copilot/copilot/providers.py) already has an endpoint override, but uses a different output contract:

| Setting or contract | Adapted Nayantra | Existing Fleet Copilot |
|---|---|---|
| Provider selector | `LLM_PROVIDER=openai` | `FLEET_COPILOT_PROVIDER=openai` |
| Endpoint | `OPENAI_BASE_URL` | `OPENAI_BASE_URL` |
| Model identifier | `OPENAI_MODEL` | `FLEET_COPILOT_MODEL` |
| Credential | `OPENAI_API_KEY` | `OPENAI_API_KEY` |
| Required model behavior | Function/tool calling and tool-result feedback | Strict JSON-schema output for a closed mission-intent object |

Our provider sends `response_format.type=json_schema` with `strict=true`; validate that exact request against the selected runtime. Passing Nayantra tool-calling tests does not establish that the same deployment accepts our structured-output request, or vice versa. The current copilot request timeout is 15 seconds, so cold-start and generation latency must fit that budget or motivate an explicit, tested application change.

If the immediate objective is simply to demonstrate locally served mission interpretation, migrating the existing copilot first is the smaller change. Add Nayantra's tool-feedback pattern when conversational catalog discovery, error recovery, or follow-up mission questions are part of the demonstration.

## Security and operational controls

Use an authenticated endpoint reachable from the agent namespace, preferably over the intended private network path. Trust the cluster's relevant certificate authorities rather than disabling TLS verification. Limit network access so the agent can reach the model endpoint and restricted tool adapter, without acquiring direct RMF or robot-command access.

Keep inference credentials separate from tool-server credentials and operator identity. A model-serving token permits inference; it does not authorize a robot mission. Retain explicit operator approval, stable idempotency keys, and the existing terminal-state checks.

For a private-inference claim, disable unapproved external-model fallback, inspect telemetry/log destinations, and verify network egress. On-cluster inference alone does not prove that every prompt or log remains local. Disconnected operation additionally needs a plan for model artifacts, container images, dependencies, and credentials.

Keep the inference path outside real-time navigation. A model outage must block new interpretation or produce an explicit unavailable result; it must not interrupt an already accepted RMF mission or trigger a duplicate dispatch. Avoid automatic provider switching during a pending mutating operation. Switching model endpoints must not replay already-authorized tools.

## Staged validation

1. **Inventory and pin.** Establish OpenShift AI version, serving runtime/image, accelerator capacity, model revision/license, parser/template, served name, endpoint, and authentication method.
2. **Verify inference contracts.** Test basic chat, then the precise tool-calling or JSON-schema contract. Confirm multi-turn tool-result handling, invalid argument behavior, bounded output, TLS, and authentication failure reporting.
3. **Start read-only.** Enable catalog and mission-evidence queries. Bind requests to the correct mission and episode, report stale observations, and require evidence for progress claims. Do not invent a delay cause or ETA.
4. **Enable previews.** Exercise supported requests, misspellings, ambiguous destinations, unsupported delivery requests, and unknown floors. A preview must not dispatch a robot.
5. **Validate confirmed execution.** Use the existing gateway for the approved hotel patrol. Recheck same-key replay, uncertain submission handling, correlated terminal completion, and continued execution during model failure.
6. **Compare and decide.** Run the same held-out prompts against local and external baselines. Record correct intent/tool selection, invalid-call rate, clarification quality, unsupported-request rejection, end-to-end response latency, and serving resource use. Record physical completion separately from agent success.

A sensible first milestone is **local inference plus read-only mission questions**, followed by validated previews and confirmed dispatch. Keep rollback explicit: switch the application configuration back only through an approved change, without resetting missions or replacing the robotics stack. If external inference is prohibited, rollback means the prior approved local deployment or disabling the conversational feature—not silent cloud fallback.

## Review decisions and remaining validation

The endpoint and client compatibility are supported by documentation and source inspection. The Nayantra tests described in the [examples review](nayantra-examples-and-demo-use-cases.md) used simulated robots and scripted model responses; they did not validate an OpenShift AI endpoint.

Before implementation, select the model/runtime/hardware combination and decide whether the first target is the current structured-intent copilot or the richer Nayantra-style tool loop. No live model deployment, cluster configuration change, or robotics implementation change is included in these findings.

Related work: [Nayantra integration assessment](nayantra-integration-assessment.md), [examples and demo use cases](nayantra-examples-and-demo-use-cases.md), and [Fleet Copilot design and gated implementation](fleet-copilot-design-and-implementation-proposal.md).

[rhoai-inference]: https://docs.redhat.com/en/documentation/red_hat_openshift_ai_self-managed/3.5/html/deploying_models/making_inference_requests_to_deployed_models
[vllm-tools]: https://docs.vllm.ai/en/stable/features/tool_calling/
[sdk]: https://developers.openai.com/api/reference/python
[n-agent]: https://github.com/shashankbr27/nayantra/blob/8c04b25bf599dbd40f7cede60392bc8f206c44cc/nayantra/agent/agent.py
[n-config]: https://github.com/shashankbr27/nayantra/blob/8c04b25bf599dbd40f7cede60392bc8f206c44cc/nayantra/config.py
