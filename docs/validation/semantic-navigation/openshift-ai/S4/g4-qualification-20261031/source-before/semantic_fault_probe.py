"""Armed semantic fault-matrix contract for the private guarded fixture.

Pure routing/evidence predicates only: no clock, command, lease or
freshness threshold is changed by these helpers. Each mode injects one
perception fault after independently verified semantic-armed motion and
requires the guarded chain to stop fail-closed with a mode-qualified first
reason, zero within 100 ms of the 500 ms semantic freshness trigger, and no
automatic resume after the fault is restored — even though fresh successful
perception responses flow again (the late-success proof).
"""

MODES = ("camera_path_loss", "tf_loss", "hung_inference", "process_loss",
         "transport_loss")

# Sustained semantic-freshness streak: a result counts toward the streak only
# if its capture age and the gap since the previous result are both below this
# bound (tighter than the gate's 500 ms lease so a qualifying streak always
# keeps the lease renewed). The armed supervisor may only arm from a sustained
# streak: the SAM3 result stream has a reproducible burst phase (multi-second
# gaps clustered in the pre-arm readiness window in every recorded trial),
# and arming on a momentary fresh receipt during those bursts starves the
# semantic lease within seconds (matrix 7 trial 4 stopped 0.2 s after arming).
STREAK_GAP_NS = 400_000_000
ARMING_STREAK_S = 5.0


def observe_result_for_streak(state, now_ns, capture_wall_ns):
    """Fold one SAM3 timing record into the sustained-freshness streak."""
    fresh = now_ns - capture_wall_ns < STREAK_GAP_NS
    continuing = (state.get("streak_start_ns") is not None and fresh
                  and state.get("last_result_ns") is not None
                  and now_ns - state["last_result_ns"] < STREAK_GAP_NS)
    if not continuing:
        state["streak_start_ns"] = now_ns if fresh else None
    state["last_result_ns"] = now_ns


def result_streak_seconds(state, now_ns):
    """The current streak length, or zero once the results stop flowing."""
    start = state.get("streak_start_ns")
    last = state.get("last_result_ns")
    if start is None or last is None or now_ns - last >= STREAK_GAP_NS:
        return 0.0
    return (last - start) / 1e9

# First coordinator stop reasons that prove the injected fault class stopped
# the armed semantic supervisor. Every perception-side fault manifests as one
# of the three semantic leases expiring (the "stale mask" condition of the
# plan is the semantic lease expiry itself); which key trips first depends on
# the pipeline's internal latencies, so the qualified set covers the honest
# orderings. TF loss stops through the existing TF/command path exactly as
# the geometry-only subgate qualified.
SEMANTIC_REASON_SET = ("camera_stale", "camera_invalid_age", "camera_epoch_changed",
                       "semantic_stale", "semantic_invalid_age", "semantic_epoch_changed",
                       "inference_heartbeat_stale", "inference_heartbeat_invalid_age",
                       "inference_heartbeat_epoch_changed")
QUALIFIED_REASONS = {
    "camera_path_loss": SEMANTIC_REASON_SET,
    # Pausing AMCL freezes map->odom; the supervisor's semantic leases stay
    # fresh (the camera and SAM3 are healthy), so the stop must come from
    # the existing TF freshness or command path.
    "tf_loss": ("tf_stale", "command_expired"),
    "hung_inference": SEMANTIC_REASON_SET,
    "process_loss": SEMANTIC_REASON_SET,
    "transport_loss": SEMANTIC_REASON_SET,
}


def stop_reason_qualified(mode, reason):
    return reason in QUALIFIED_REASONS.get(mode, ())


def stop_wait_seconds(mode):
    """Bounded wait from injection (or motion verification for externally
    injected modes) to the guarded stop."""
    return 45.0 if mode in ("hung_inference", "process_loss", "transport_loss") else 10.0


def late_success_wait_seconds(mode):
    """Bounded wait after fault restoration for a fresh successful
    perception response (or restored TF) to arrive, proving that the late
    success exists and still cannot resume motion. Process loss waits for
    the container restart and model reload."""
    return {"camera_path_loss": 30.0, "tf_loss": 20.0, "hung_inference": 30.0,
            "process_loss": 240.0, "transport_loss": 120.0}.get(mode, 30.0)


def late_success_key(mode):
    """The worker lease key whose sequence advancing again proves the late
    successful response; TF loss is proven by restored capture-time TF."""
    return {"camera_path_loss": "camera", "tf_loss": None,
            "hung_inference": "inference_heartbeat", "process_loss": "inference_heartbeat",
            "transport_loss": "semantic"}.get(mode)


def observation_window_end(stop_wall, receipts):
    """Scope the observation timing window to the pre-fault period.

    The semantic fault stops perception results for the remainder of the
    trial (the late-success dwell); the throughput contract is evaluated
    over the results that arrived before the guarded stop, which is the
    period the armed supervisor actually observed.
    """
    if stop_wall is None:
        return list(receipts)
    return [wall for wall in receipts if wall <= stop_wall]


def observation_window(stop_wall, receipts, warmup_gap_s=1.0):
    """Scope the observation timing window to the settled pre-fault period.

    The end is the guarded stop. The start skips the stream's warmup: the
    SAM3 result stream has a reproducible burst phase before it settles
    (multi-second gaps clustered before arming), and the arming streak
    already requires the settled stream — the throughput contract measures
    the period the armed supervisor actually observed, not the pipeline's
    warmup (matrix 11 trial 5: a fresh pod's stream began during the camera
    warmup, and the leading 14 s gap dragged the average below the limit
    while the settled stream ran at 7.5 results/s). Gaps larger than the
    lease's 500 ms freshness cannot occur during armed motion without
    stopping the supervisor, so trimming at the last large gap only ever
    removes warmup.
    """
    scoped = observation_window_end(stop_wall, receipts)
    start = 0
    for index in range(1, len(scoped)):
        if (scoped[index] - scoped[index - 1]) / 1e9 > warmup_gap_s:
            start = index
    return scoped[start:]
