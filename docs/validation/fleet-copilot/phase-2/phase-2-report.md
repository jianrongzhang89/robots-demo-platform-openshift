# Fleet Copilot Phase 2 Implementation Evidence

- **Phase:** 2, deterministic mission gateway and lifecycle projection
- **Status:** G2 accepted for development scope; recovery-boundary review deferred
- **Database:** SQLite on the `fleet-copilot-data` PVC
- **Bridge boundary:** live RMF Web dispatch and task-state sync, plus a
  deterministic emulator event path for local recovery tests

## Delivered

- Immutable catalog-checked mission previews with two-minute expiry.
- Typed mission submission using required `Idempotency-Key` headers.
- Durable mission records containing episode and RMF generation identifiers.
- Publish-attempt marker and stable request UUID persisted before the bridge
  boundary.
- Live RMF Web bridge for patrol dispatch, task ID binding, state sync, and
  cancellation requests.
- Lifecycle event ingestion and projection for queued, selected, dispatched,
  failed-to-assign, completed, and cancellation states.
- Duplicate source-event suppression and protection against late terminal-state
  regression.
- Episode reset that marks nonterminal missions `generation_changed` while
  preserving terminal history.
- Health, readiness, catalog, mission, event, cancellation, and reset APIs.

## Local Verification

```text
12 tests passed
```

The tests cover concurrent same-key retries, ten sequential retries, changed
payload conflicts, one publication marker per mission, terminal-state ordering,
duplicate events, and generation reset behavior.

## OpenShift Verification

- Build: `fleet-copilot-13`, completed successfully.
- Deployment: `fleet-copilot`, 1/1 ready after the PVC/SCC rollout fix.
- Persistent volume: `fleet-copilot-data`, 1Gi, `Bound`.
- Live health/readiness: passed.
- Live idempotency retry: same mission and request UUID returned.
- Live changed-payload retry: HTTP `409` returned.
- Live lifecycle: queued -> selected -> dispatched -> completed projected
  correctly with six persisted events.
- Live restart: completed mission remained available after pod restart.
- Live episode reset: new episode and RMF generation created.
- Live duplicate/out-of-order events: duplicate source ID was ignored and a
  late queued event did not regress an underway mission.
- Live RMF idempotency replay after preview expiry: existing mission and RMF
  task ID were returned without a second publication.
- Live RMF patrol after the simulation-clock fix: task `patrol.dispatch-2`
  completed with the conservative terminal predicate and projected as
  `execution=completed`.
- Three independent reset patrols now have terminal-success evidence after the
  RMF startup/localization hardening.

## Boundary and G2 Gaps

This implementation does not claim the G2 gate. The live bridge now publishes
to RMF Web and binds actual RMF task IDs, but it does not yet reconcile lost RMF
responses, prove three physical patrols, or provide a real single-owner ROS
publisher. The actual-RMF verification attempt is recorded separately in
`g2-report.md`.
