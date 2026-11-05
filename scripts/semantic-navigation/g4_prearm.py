"""Reuse the accepted Phase 6 liveness ladder only with proof of no arming."""
import json
from pathlib import Path
import time
from phase6_trial import costs_gate_liveness_death

POLICY = ('two fresh-fixture retries, then one topology recycle, only for accepted pre-arm '
          'liveness signatures (costs-gate liveness death, SAM3-readiness death where the '
          'zenoh bridge never delivered a semantic result, or a nav2 child-process crash '
          'before the arm handshake began) with proof that no arming occurred; '
          'never retry a motion or injected-fault failure')


def sam3_readiness_death(directory):
    """Pre-arm SAM3 observation readiness never achieved. The zenoh bridge
    (1.5.0) intermittently fails to bind its routes at cold start (~1 in 15
    observed): the worker records zero semantic results and no heartbeat
    while the camera stream is live, and the verify script's bounded
    readiness wait times out. That wait precedes every arming statement
    sequentially, so this signature proves no arming occurred even when no
    guard-events were retained."""
    if (directory/'runtime/summary.json').exists():
        return False
    try:
        text=(directory/'test.log').read_text()
    except OSError:
        return False
    if 'SAM3 observation readiness before arming' not in text:
        return False
    try:
        worker=json.loads((directory/'observer-status.json').read_text())
    except (OSError, ValueError):
        return False
    return (worker.get('results') in (0, None)
            and (worker.get('leases') or {}).get('semantic') is None)


def nav2_child_crash_prearm(directory):
    """A fixture child process crashed (for example nav2's behavior_server
    SIGSEGV, qualification-17 trial-02) before the arm handshake began.
    Proof of no arming: the pump's child monitor recorded the exit in
    test.log, and the retained native trace shows ZERO received packets —
    the arm datagram itself is counted, so any arming would leave packets
    behind. A mid-motion crash has packets > 0 and stays terminal."""
    import re
    try:
        text=(directory/'test.log').read_text()
    except OSError:
        return False
    if not re.search(r"\b[a-z_]+ exited -?\d+", text):
        return False
    for base in ('runtime', 'runtime-partial'):
        trace=directory/base/'trace.jsonl'
        if not trace.is_file():
            continue
        try:
            rows=[json.loads(line) for line in trace.read_text().splitlines() if line.strip()]
        except (OSError, ValueError):
            continue
        packets=[r.get('received_packets') for r in rows
                 if isinstance(r, dict) and isinstance(r.get('received_packets'), int)]
        if packets and max(packets)==0:
            return True
    return False


def settle_before_retry(seconds=20.0):
    """Let a failed fixture's zenoh retirement (liveliness lease 10 s)
    propagate before the replacement announces, so route re-binding is
    ordered rather than raced (announcement/retirement ordering,
    zenoh-bridge 1.5.0; see the qualification-5 addendum)."""
    time.sleep(seconds)


def retryable(directory):
    if sam3_readiness_death(directory):
        return True
    if nav2_child_crash_prearm(directory):
        return True
    if not costs_gate_liveness_death(directory):
        return False
    history = next((p for p in (directory/'runtime/guard-events.json', directory/'runtime-partial/guard-events.json') if p.exists()), None)
    if history is None:
        return False
    try:
        events=json.loads(history.read_text()).get('coordinator')
    except (ValueError, OSError):
        return False
    # A single arm attempt makes the run ineligible, regardless of whether
    # the resulting stop happened before the intended fault injection.
    return isinstance(events,list) and not any(e.get('event')=='arm_requested' for e in events)


def retain_attempt(directory, attempt):
    target=directory.with_name(directory.name+f'-liveness-{attempt}')
    if target.exists():raise RuntimeError('refusing to overwrite retained attempt')
    directory.rename(target)
    log=directory.parent/(directory.name+'.log')
    if log.exists():log.rename(directory.parent/(target.name+'.log'))
    return target
