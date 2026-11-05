# OpenShift AI served navigation presentation — November 4, 2026

**Demo PASS; cleanup PASS.** One semantic-on navigation run completed after the
user opened the new noVNC viewer and said “go.” No G4 campaign was resumed and G5
remains HOLD for its separate operations/presenter acceptance requirements.

The CPU ROS adapter used the accepted digest-pinned OpenShift AI/KServe SAM3
endpoint over authenticated TLS. The accepted G4 lethal-254 exclusion profile
marked 255 cells in the global semantic costmap, all within the staged target
rectangle. The local costmap retains the accepted non-semantic configuration.
The model, native guard, motion limits and capture/command thresholds are unchanged.
A CPU-only, view-only Gazebo GUI and an explicit operator-start hold are optional
presentation additions, so this run is not a new configuration qualification.

## Observed result

- Nav2 returned `goal_succeeded`; the original fixture evaluator passed.
- Physical path length: 4.876 m. Red-mat hull exposure: 0.0 m.
- Minimum estimated hull clearance: 0.137 m, using the accepted 0.246 m
  circumscribed radius. The contact audit found no unexpected contacts.
- Robot stopped and the task graph reached terminal state.
- SAM3 capture-age p95: 252.936 ms against the unchanged 500 ms limit;
  valid observation rate: 7.099/s. Pre-motion capture-stream RTF: 0.532.
- Arrival is based on localization belief: belief-to-goal distance 0.117 m,
  **ground-truth-to-goal distance 0.727 m**, and belief/truth divergence 0.775 m.
  Preserve the existing G4 completion-semantics caveat; this is not proof of
  physical arrival within the 0.20 m tolerance.
- A `native_capture_stale` latch at 100.995 ms processing age occurred during
  post-goal diagnostics, after the moving command-capture check and terminal /
  contact window passed. It remains visible in the raw summary and clock events.
  This run is not represented as clean timing through every teardown diagnostic.

See `demo-summary.json`, `trial/runtime/summary.json`, raw native/command/contact
traces, `operator-release.json`, `viewer-before-navigation.png` and
`viewer-navigation.png`. The local operator-hold/native-clock tests passed (18),
and the in-pod regression/native suites passed before starting this fixture.

## Retained presentation setup failure

`../navigation-demo-on-1` remains FAIL. Its first operator hold was followed by an
extra synchronous costmap inspection after native-clock binding. A capture was
processed at 104.293 ms and correctly latched the existing 100 ms freshness guard.
There were 23,507 native samples, all disarmed, with zero received command packets
and zero applied commands; no navigation task was requested. Cleanup passed.

For attempt 2, the viewing hold moved ahead of the original costmap/planning and
clock-binding sequence. Fresh readiness and render warmup then ran normally.
No bound clock was reset and no safety limit changed. The user was informed of
the setup correction and notified again before the fresh attempt started, using
their existing “go” authorization. Both attempts retain distinct tokens, epochs,
pods, source hashes and evidence; the failed attempt was not relabeled as PASS.

The wrapper removed the private fixture, G4 adapter/router and temporary noVNC
Service/Route, then restored the rendering reservation. The accepted local SAM3,
original local-demo noVNC deployment and accepted serving runtime are preserved.
