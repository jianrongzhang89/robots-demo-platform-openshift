# G2 Verification Attempt: Actual RMF/ROS

- **Date:** 2026-10-08
- **Cluster/project:** `ros2-rmf-hotel`
- **Gateway build:** `fleet-copilot-13` with simulation-clock, startup, and
  mission-scoped event fixes
- **Result:** Three-patrol terminal gate passes; full G2 matrix remains open

## Actual Bridge Evidence

The Phase 2 gateway was connected to the live RMF Web API through the
`rmf-core-api` Service:

- `POST /tasks/dispatch_task` accepted the gateway payload.
- RMF returned task ID `patrol.dispatch-1`.
- The task carried the persisted labels for mission, episode, and site.
- RMF logs showed a bid from `hotel_nav2`, assignment to `robot_1`, and an
  awarded task.
- Repeating the same Phase 2 submission with the same idempotency key returned
  the existing mission and did not publish a second RMF request.
- The same-key replay still returned the existing mission after the preview's
  two-minute expiry; the gateway checks the durable idempotency record before
  preview freshness.

## Failed Terminal Verification

Mission `58b0b568-16fd-4e16-bab3-1a9a967cc6e0` submitted:

```text
lobby -> L3_middle_hallway -> lobby
```

The RMF Web state after award reported `status=queued`, `phases=null`,
`completed=null`, and `pending=null`. No correlated terminal completion could
be established. The RMF log stopped after:

```text
Dispatcher Bidding Result: task [patrol.dispatch-1] is awarded
TaskAssignments updated for robots in fleet [hotel_nav2]
```

No corresponding Nav2 relay command/result was observed in the validation
window. The task was canceled through the RMF Web API after the failed attempt.

The gateway sync path was corrected to handle nullable RMF `dispatch` fields
without converting uncertainty into a 500 response. It now retains the mission
as queued/uncertain until a valid state or terminal evidence arrives.

## Remediation Verification

The bridge originally sent wall-clock epoch timestamps in
`unix_millis_request_time` and `unix_millis_earliest_start_time`. RMF accepted
the request but left it queued because the hotel simulator clock was only a few
hundred seconds. The bridge now omits both optional fields and lets RMF derive
them from its active simulation clock.

After a full documented RMF/Nav2 reset, mission
`8f79ab9a-090a-4308-9e95-7863656e307a` dispatched RMF task `patrol.dispatch-2`
through the Phase 2 API. RMF/Nav2 completed the lobby -> L3 hallway -> lobby
patrol, and the gateway sync recorded:

```text
completed=[1,2,3], pending=[], valid finish timestamp
execution=completed
```

This proves the timestamp/startup fix for one clean run. Three independently
reset successful runs were then completed:

| Run | RMF task | Gateway result | Terminal evidence |
|---:|---|---|---|
| 1 | `patrol.dispatch-2` | `execution=completed` | phases 1-3 complete, pending empty, valid finish |
| 2 | `patrol.dispatch-0` | `execution=completed` | phases 1-3 complete, pending empty, valid finish |
| 3 | `patrol.dispatch-0` | `execution=completed` | phases 1-3 complete, pending empty, valid finish |

The repeated RMF task ID is scoped by a new episode/generation and the gateway
now scopes source-event deduplication by application mission ID.

## G2 Decision

The development G2 checks pass: actual publish/response correlation,
command/result flow, three terminal patrols, idempotency, restart recovery,
foreign-event rejection, lost-response reconciliation, and source-age/
projection measurements are all evidenced below.

## Development Sign-Off

- **Decision:** G2 passed for development scope.
- **Accepted by:** User approval in the project session.
- **Review status:** Recovery-boundary and fault-assumption review postponed.
- **Boundary:** This is a development sign-off, not production safety approval.

## Emulator Matrix

The deterministic campaign in `apps/fleet-copilot/evaluation/g2.py` completed:

- 100 operations with 10 concurrent same-key retries each.
- 100/100 same-key retries returned one mission identity.
- Gateway restart replay returned all 100 persisted mission identities.
- 100/100 changed-payload retries returned conflicts.
- Mission rows: 100; dispatch attempts: 100; publish markers: 100.
- Duplicate publications: 0.

The four bridge crash points are covered by the deterministic boundary harness
in `apps/fleet-copilot/evaluation/g2_faults.py`:

- Same mission identity survived restart in all four scenarios.
- No scenario republished the RMF operation.
- The response-before-projection scenario reconciled by binding the existing
  RMF task ID after restart.

This is a deterministic store/bridge-boundary harness; the live worker crash
and lost-response checks are recorded below.

## Live Safety Recheck

- A live Fleet Copilot pod was force-restarted after a completed RMF mission;
  replaying the same idempotency key returned the existing mission and task ID
  with no new RMF publication.
- A live foreign event carrying another mission ID was rejected with HTTP `409`.
- A live RMF sync projection completed in `94 ms`.

The remaining formal boundary is review of the recovery limits; the live crash,
foreign-event, source-age, and projection-latency checks are recorded below.

## Live In-Flight Restart

Mission `7bc56fc9-96bb-4cb2-9e38-dc86f672c871` was dispatched to RMF task
`patrol.dispatch-1`. The Fleet Copilot pod was force-terminated while the RMF
task was active. After the replacement pod mounted the same PVC:

- Same-key replay returned the original mission and RMF task ID.
- No second RMF publication occurred.
- Sync preserved the task through queued state and projected
  `execution=completed` after RMF terminal evidence arrived.

This validates live in-flight application restart recovery.

## Live Lost-Response Fault

The controlled `FLEET_COPILOT_CRASH_AFTER_RMF_RESPONSE` seam was enabled for one
mission. The gateway exited after RMF accepted task `patrol.dispatch-2` and
before mission projection returned to the client; the route observed a `502`.
After the pod restarted with the fault disabled:

- Same-key replay reconciled the RMF task by its persisted mission label.
- No second RMF task was published.
- The patrol reached `execution=completed` with terminal RMF evidence.
- A follow-up sync projection measured `99 ms`.

This closes the live lost-response/restart scenario. A 100-request sync sample
measured p50 `81.71 ms`, p95 `99.64 ms`, and max `157.42 ms`.

## Source Age

The live RMF ROS domain was sampled for 100 fleet observations, comparing each
robot location timestamp with `/clock`:

- p50 source age: `490 ms`
- p95 source age: `960 ms`
- maximum source age: `990 ms`
- budget: `5,000 ms`

The source-age check passed.
