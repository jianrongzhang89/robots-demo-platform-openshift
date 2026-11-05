"""Timestamp-ordered one-to-one pairing for RGB-D message queues."""

from __future__ import annotations

from typing import Callable, Deque, TypeVar

T = TypeVar("T")


def drain_synchronized_pairs(
    rgb_queue: Deque[T],
    depth_queue: Deque[T],
    stamp_ns: Callable[[T], int],
    tolerance_ns: int,
) -> tuple[list[tuple[T, T]], dict[str, int], int, int]:
    """Drain all currently matchable pairs, dropping provably older frames.

    Each message can participate in at most one pair. Queues must preserve
    per-topic timestamp order, as ROS subscriptions do for this camera stream.
    If one side is empty, unmatched messages remain buffered for its next sample.
    """
    if tolerance_ns < 0:
        raise ValueError("tolerance_ns must be non-negative")

    pairs: list[tuple[T, T]] = []
    discarded = {"rgb": 0, "depth": 0}
    checks = 0
    max_skew_ns = 0
    while rgb_queue and depth_queue:
        rgb_stamp = stamp_ns(rgb_queue[0])
        depth_stamp = stamp_ns(depth_queue[0])
        delta_ns = rgb_stamp - depth_stamp
        skew_ns = abs(delta_ns)
        checks += 1
        max_skew_ns = max(max_skew_ns, skew_ns)
        if skew_ns <= tolerance_ns:
            pairs.append((rgb_queue.popleft(), depth_queue.popleft()))
        elif delta_ns < 0:
            rgb_queue.popleft()
            discarded["rgb"] += 1
        else:
            depth_queue.popleft()
            discarded["depth"] += 1

    return pairs, discarded, checks, max_skew_ns
