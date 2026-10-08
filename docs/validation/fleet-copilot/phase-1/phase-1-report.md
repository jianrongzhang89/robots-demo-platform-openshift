# Fleet Copilot Phase 1 Implementation Evidence

- **Phase:** 1, external-model interpretation without robot dispatch
- **Status:** G1 accepted for development scope; pricing review deferred; production/formal independent sign-off not claimed
- **Providers evaluated:** deterministic mock provider and OpenAI Chat Completions
- **Catalog:** `apps/fleet-copilot/fixtures/catalog.hotel-demo.json`
- **Catalog version:** `sha256:4576e4eb1c95cfbb`

## Delivered

The ROS-free application under `apps/fleet-copilot/` provides:

- A closed intent contract with semantic validation.
- An approved hotel catalog for `lobby` and `L3_middle_hallway` aliases.
- A deterministic provider for repeatable development fixtures.
- An external OpenAI Chat Completions adapter using strict structured output.
- A FastAPI interpretation endpoint and browser preview UI.
- No RMF/ROS imports, dispatch endpoint, task publication, or robot command path.

## Development Evaluation

`python3 apps/fleet-copilot/evaluation/run.py` evaluates 100 supported
paraphrases and 50 ambiguous/unsupported requests three times:

| Repetition | Supported correct | Unsupported held | Result |
|---:|---:|---:|---|
| 1 | 100/100 | 50/50 | pass |
| 2 | 100/100 | 50/50 | pass |
| 3 | 100/100 | 50/50 | pass |

These are deterministic mock-provider results, not the required held-out
external-model gate. The external provider contract and failure boundaries are
covered by unit tests but require credentials and a separately recorded model
run before G1 acceptance.

## External Evaluation

The command below was run with the project-scoped `OPENAI_API_KEY` configured:

```bash
FLEET_COPILOT_PROVIDER=openai python3 apps/fleet-copilot/evaluation/run.py
```

The application-owned prompt was tightened after the first run exposed alias,
return-semantics, and package-number errors. The final run made 450 bounded
calls using the external adapter and produced these results:

| Repetition | Supported correct | Unsupported held | Result |
|---:|---:|---:|---|
| 1 | 97/100 | 50/50 | pass |
| 2 | 96/100 | 50/50 | pass |
| 3 | 99/100 | 50/50 | pass |

No call can publish an RMF request. Provider timeouts and malformed responses
become held previews. Raw per-case output is emitted by the evaluator and was
captured in the run artifact; no API key or provider response is stored in the
repository.

This establishes the proposed semantic accuracy threshold for this corpus,
but does not by itself accept G1. Refusal, incomplete-output, explicit 429,
hostile-output, p95 latency, token/cost, and fresh held-out corpus checks remain
to be recorded before acceptance.

## Current External Recheck

On 2026-10-08, the current provider configuration was rerun with
`FLEET_COPILOT_PROVIDER=openai`. It completed 450 calls in 404.79 seconds and
passed the semantic threshold in every repetition:

| Repetition | Supported correct | Unsupported held | Result |
|---:|---:|---:|---|
| 1 | 100/100 | 50/50 | pass |
| 2 | 100/100 | 50/50 | pass |
| 3 | 100/100 | 50/50 | pass |

The evaluator does not emit per-request latency, token usage, or cost, and this
run does not cover the required injected provider faults or an independently
held-out corpus. G1 therefore remains unaccepted despite the semantic recheck
passing.

## G1 Blocker Recheck

The evaluator was extended with request timing, provider usage accounting, and
an independent held-out corpus. The fault suite was also extended for refusal,
incomplete output, HTTP 429, timeout, unavailable provider, and hostile/extra
fields. All seven local contract and fault tests passed.

The held-out OpenAI run used model `gpt-4.1-mini-2025-04-14`, 100 supported and
50 unsupported requests, repeated three times:

| Repetition | Supported correct | Unsupported held | Result |
|---:|---:|---:|---|
| 1 | 100/100 | 50/50 | pass |
| 2 | 100/100 | 50/50 | pass |
| 3 | 100/100 | 50/50 | pass |

Measured across all 450 calls after tightening the prompt to require
`rounds: 1` for every executable patrol:

- Latency p50 `0.872s`, p95 `1.149s`, maximum `3.103s`; p95 is within the 5s gate.
- Usage: 139,575 prompt tokens, 15,792 completion tokens, 155,367 total;
  usage was present for all calls.
- Estimated cost: `$0.0811`, using explicitly supplied rates of `$0.40` per
  million input tokens and `$1.60` per million output tokens.

The semantic, safety, latency, and accounting checks now pass. The corpus is
held out from the original evaluation generator but remains repository-managed.
Pricing review is explicitly deferred because this is a development milestone
and is non-gating for this acceptance.

## Development Acceptance

- **Decision:** G1 accepted for development scope.
- **Accepted by:** User approval in the project session.
- **Date:** 2026-10-08.
- **Pricing:** Deferred and explicitly non-gating.
- **Boundary:** This is not independent production sign-off; the corpus remains
  available for later reviewer freeze/acceptance before a production gate.

## Verification

```bash
python3 -m unittest discover -s apps/fleet-copilot/tests -v
python3 apps/fleet-copilot/evaluation/run.py
python3 -m compileall -q apps/fleet-copilot
```

## OpenShift Deployment Validation

The preview was packaged with `apps/fleet-copilot/Containerfile` and deployed
to the `ros2-rmf-hotel` project using
`openshift/fleet-copilot-phase1.yaml`.

- Build: `fleet-copilot-1`, completed successfully and pushed to the project
  ImageStream.
- Rollout: `deployment/fleet-copilot`, 1/1 ready, zero restarts.
- Route: `https://fleet-copilot-ros2-rmf-hotel.apps.ai-dev02.kni.syseng.devcluster.openshift.com`
- Live checks: UI `200`, catalog `200`, supported and unsupported interpretation
  requests `200`.
- Safety check: `/api/dispatch` returns `404`; no dispatch operation is
  exposed by the deployed preview.
- Live provider: `openai-chat-completions`, configured through the
  `fleet-copilot-openai` OpenShift Secret. The key is not stored in the
  repository.
- Live semantic check: a one-way request produced
  `lobby -> L3_middle_hallway`; a request explicitly asking to return produced
  `lobby -> L3_middle_hallway -> lobby`.

Phase 0 remains unaccepted, so no live fleet integration was added. Phase 2
must not begin until the user accepts the phase 1 evaluation and the baseline
terminal-state blockers are resolved.
