# Fleet Copilot Phase 3 Implementation Evidence

- **Phase:** 3, end-to-end external fleet copilot flow
- **Status:** G3 accepted for development scope; production and browser review deferred
- **Provider:** OpenAI Chat Completions
- **Deployment:** `fleet-copilot-16`

## Delivered

- `POST /api/v1/turns` connects external interpretation to immutable Phase 2
  previews without dispatching.
- Supported previews receive a server-side `preview_id` and expiry.
- Unsupported, ambiguous, and provider-error turns remain held and do not
  create a mission preview or RMF task.
- Browser UI now renders a deterministic Dispatch action only for a valid
  preview.
- Dispatch uses a generated idempotency key and Phase 2 mission API.
- Mission identity, RMF task ID, submission, execution, and revision are
  rendered in the UI.
- UI polls the deterministic sync endpoint for live mission state.
- SSE mission stream endpoint emits revisioned mission events.
- Model errors remain explicit preview failures; they cannot reach dispatch.

## Live Verification

- UI route served Phase 3 markup successfully.
- Supported OpenAI turn returned `propose_patrol`, `dispatchable=true`, and a
  `preview_id`.
- Unsupported OpenAI turn returned `dispatchable=false` with no `preview_id`.
- Explicit dispatch created RMF task `patrol.dispatch-3`.
- Repeating the same Dispatch request returned the same mission and RMF task
  identity.
- The dispatched mission completed with RMF terminal evidence and gateway
  `execution=completed`.
- Five independently reset OpenAI-driven patrols completed with distinct
  mission identities and terminal RMF evidence.
- Ten unsupported live turns were held without previews or mission creation.
- Cross-site destination and preview requests returned `404`.
- Repeated Dispatch requests, pod restart replay, and two SSE reads returned
  the existing mission/event state without a second dispatch.
- External-model disablement during an active mission returned an explicit
  `unavailable` held turn while the active RMF mission continued to
  `execution=completed`.
- Mission stream emitted a revisioned `event: mission` SSE record.
- Local regression suite: `15/15` passed.

## G3 Boundary

## Development Sign-Off

- **Decision:** G3 accepted for development scope.
- **Accepted by:** User approval in the project session.
- **Production acceptance:** Deferred.
- **Browser automation review:** Deferred.
- **Boundary:** This is a development sign-off, not production acceptance.
