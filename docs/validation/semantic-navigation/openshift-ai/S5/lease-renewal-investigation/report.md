# Root-cause investigation: early navigation stops in presentation runs 5 and 6

The failures originate in the command-authority renewal path. The native guard
correctly stops when it receives an invalid lease or its existing lease expires.
The two runs have distinct immediate mechanisms; treating both as an OpenShift
AI inference failure, or as the later stale-clock latch, is incorrect.

## Recording run 6: renewal arrives too close to the existing native deadline

The coordinator computes authority from command-capture time, forwards checked
commands immediately, and periodically renews. The native receiver subtracts its
2 ms clock allowance and independently expires the *last accepted* lease. A new
packet with a later deadline cannot revive a session whose previous lease has
already expired.

For the final accepted sequence 4129, native expiry was
`1793809490285752449` wall ns. The following events are measured relative to that
boundary (negative means before expiry):

| Event | Relative time |
| --- | ---: |
| New checked command published | −25.489 ms |
| Its audit callback received by fixture | −17.282 ms |
| Slow guard stage begins (steady-clock comparison) | −12.559 ms |
| Renewal 4130 issuance timestamp sampled | −4.350 ms |
| UDP worker finishes sending renewal 4130 | **−1.079 ms** |
| Slow guard stage ends (steady-clock comparison) | −0.752 ms |
| Native lease expiry trigger | 0 |
| Native applies zero | +1.992 ms |

The guard stage took **11.807 ms wall time**. From checked callback to worker
send took **16.203 ms**. No lease enqueue was dropped. Sequence 4130 itself had
34.559 ms of declared validity; the problem was continuity with the previous
accepted lease, not its own expiry. Native status shows sequence 4129 remained
the last accepted sequence and then latched `lease_expired`.

The scheduling design leaves this narrow margin: `verify_hotel_stack.pump()`
runs command ingress, observers, task callbacks and native ingestion before
its guard stage. That stage polls TF/semantic records and calls
`HotelGuardAdapter.tick()`, which performs evidence checks and command-joiner
draining before `GuardedCoordinator.tick()` handles heartbeat/grace. Thus fresh
commands may exist while the independently running native receiver is still
living on an older accepted deadline. In this instance, source-age handling,
callback/drain delay and an 11.8 ms guard interval consumed almost all of the
renewal margin. A subsequent receive/acceptance delay of approximately 1.1 ms
was enough to lose the session.

**Precision limit:** the worker log timestamps after `sendto`, while native
status exposes only the most recent packet-receive time. There is no per-packet
socket receive / mutex-acquired / acceptance trace. The data therefore cannot
separate OS scheduling, socket-to-thread wakeup and native mutex waiting for
sequence 4130. It establishes late acceptance across the old lease deadline,
not a specific network or mutex defect. Main-thread scheduler evidence in the
surrounding 202.204 ms shows the fixture supervisor waiting 28.115 ms on the run
queue and the simulator main thread waiting 34.208 ms. These are interval totals,
not attribution of a particular millisecond to the receive thread.

## Run 5: repeated same-source admission withdraws grace and sends an invalid packet

This is a deterministic software defect, independently reproduced offline.
`SafetyGate.command()` accepts an equal source timestamp but resets
`command_grace_used` and recomputes the ungraced deadline on every admission.
`GuardedCoordinator.checked()` immediately sends the resulting packet.
`maybe_grace_command_deadline()` runs afterward during the coordinator tick.

Observed packets for the same captured source:

| Sequence | Declared window | Deadline behavior |
| --- | ---: | --- |
| 7695 | 33.040 ms | Existing 25 ms grace included |
| 7696 | **1.08445 ms** | Same-source re-admission removes ~25 ms grace |
| 7697 | 25.370 ms | Grace reapplied, deadline restored ~25 ms |

The native guard requires `expires_wall > received_wall + 2 ms`. Sequence 7696
cannot satisfy that even at its issuance instant. It therefore triggers
`packet_invalid`; the later corrected packet cannot revive the latched session.
The native stop precedes the separately recorded 103.292 ms stale-capture latch.
That clock latch is secondary, not the initiating cause.

The comments describe grace as once per source, and tests cover a *newer*
command resetting grace. They do not cover repeated checked copies of the same
source resetting it. Retained traces show exactly this 25 ms withdrawal and
restoration. Merely increasing inference speed or retrying the demonstration
cannot remove this defect.

## What changed with the presentation, and what is not proven

| Run | Result | Armed simulation/wall ratio | Fixture CPU cores during motion | Fixture CPU throttle | Semantic capture p95 |
| --- | --- | ---: | ---: | ---: | ---: |
| 2 | PASS | 0.496 | 3.348 | 0 | 252.936 ms |
| 3 | PASS | 0.491 | 3.332 | 0 | 250.267 ms |
| 5 | FAIL | 0.440 | 3.142 | 0 | 255.918 ms |
| 6 | FAIL | 0.444 | 3.156 | 0 | 253.760 ms |

The faster CPU viewer and wider mat were introduced together in runs 5/6.
The simulation slowed roughly 10%, increasing wall time in the command chain.
Viewer CPU load is a plausible contributor to scheduling pressure, but these
runs are **not a controlled A/B experiment**: geometry, route, viewer settings
and startup/hold duration differ. The simulator has zero recorded CPU-quota
throttling during all four armed intervals. Run 6 viewer cgroup records only
two throttled periods over the entire session. Lack of quota throttling does
not exclude ordinary run-queue contention. Do not label the viewer the proven
sole cause.

OpenShift AI observation timing passes in both failed runs (~254–256 ms p95,
limit 500 ms; ~7 results/s). Run 6 has no native clock fault. The simulator,
resource probe, camera bridge and Nav2 processes remained alive at shutdown.
No command-queue overflow was recorded. The mat-clearance shortfall is a
separate navigation-quality issue; it did not issue these native stop reasons.

## Reproduction and corrective direction

No runtime or safety policy was changed in this investigation; the cluster was
not restarted and no new navigation was launched.

- `analyze.py` derives the comparisons and event timings from retained runs;
  `analysis.json` contains exact measurements and scheduling counters.
- `replay_same_source.py` exercises the current Python gate and reproduces a
  **25 ms deadline regression and 1.08445 ms emitted lease** after same-source
  re-admission. `same-source-replay-result.json` records the assertions.
- `replay_guard.cpp` compiles the actual repository native guard header and
  consumes retained packet fields from `replay-input.json`. It rejects the run5
  short packet even with zero delivery delay. For run6, reception at the worker
  send time would succeed; reception 1 ns after the old expiry fails. These last
  two timings are explicit counterfactual tests, not fabricated receive logs.
  Results are in `replay-result.json`.

The correction should address both mechanisms, not relax the 100 ms command,
80 ms lease, 2 ms receiver allowance or 500 ms inference freshness limits:

1. Preserve already-authorized, bounded grace across repeated copies of the
   same captured source. Reset it only for a genuinely newer source, while
   retaining all current validation and invalid-command stop behavior. Test
   repeated checked commands, source change, lost-source expiry and no revival.
2. Prioritize valid renewal before lengthy polling/evidence/diagnostic work and
   measure margin against the native receiver's last accepted deadline. Remove
   avoidable scheduling and synchronous logging delays from the renewal path.
   Do not regenerate authority from receipt time or merely stretch deadlines.
3. Add bounded per-packet receive/lock/accept timing and finer guard-stage
   instrumentation, then validate under the same viewer load. A controlled
   viewer-load comparison is needed before attributing remaining jitter to it.
4. Verify the wider-mat clearance independently; a timing pass does not establish
   mat avoidance. Moving validation still requires advance notice for noVNC.

Relevant implementation locations: `apps/semantic-safety/safety_core.py:233`,
`guarded_coordinator.py:150`, `guarded_coordinator.py:279`,
`hotel_guard_adapter.py:309`, `verify_hotel_stack.py:910`,
`native_link.py:63`, `native/lease_guard.hpp:52`, `native/watchdog.cpp:100`.
