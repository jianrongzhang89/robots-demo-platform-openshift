"""Source capture trace validation; wall stamps are never ROS observation stamps."""
import math


def validate_capture_trace(trace):
    if trace.get("schema") != "semantic-capture/v1":
        raise ValueError("unsupported capture trace")
    for key in ("sequence", "stamp_ns", "capture_wall_ns", "rendered_wall_ns",
                "source_publish_wall_ns", "render_duration_ns", "source_duration_ns"):
        if type(trace.get(key)) is not int or trace[key] < 0:
            raise ValueError(f"invalid capture trace {key}")
    if not isinstance(trace.get("source_epoch"), str) or not 1 <= len(trace["source_epoch"]) <= 128:
        raise ValueError("invalid source epoch")
    if not trace["capture_wall_ns"] <= trace["rendered_wall_ns"] <= trace["source_publish_wall_ns"]:
        raise ValueError("source clock moved backwards")
    if abs(trace["source_publish_wall_ns"] - trace["capture_wall_ns"] - trace["source_duration_ns"]) > 2_000_000:
        raise ValueError("source wall/steady clock discontinuity")
    return trace


def capture_age_upper_ms(trace, now_wall_ns, uncertainty_ms):
    if not math.isfinite(uncertainty_ms) or not 0 <= uncertainty_ms <= 50:
        raise ValueError("invalid clock uncertainty")
    age = (now_wall_ns - trace["capture_wall_ns"]) / 1e6
    if age < -uncertainty_ms:
        raise ValueError("source clock is in the future beyond uncertainty")
    return max(0.0, age + uncertainty_ms)


def capture_deadline(trace, now_wall_ns, now_monotonic, stale_after_s, uncertainty_ms):
    age = capture_age_upper_ms(trace, now_wall_ns, uncertainty_ms)
    remaining_s = stale_after_s - age / 1000
    if remaining_s <= 0:
        raise TimeoutError("source capture expired before inference")
    return now_monotonic + remaining_s


def simulation_capture_age_ms(clock_ns, capture_ns, limit_ms):
    """Final publication guard: a clock reset must not authorize an old frame."""
    age = (clock_ns - capture_ns) / 1e6
    if not 0 <= age <= limit_ms:
        raise TimeoutError("capture invalidated by simulation clock change")
    return age
