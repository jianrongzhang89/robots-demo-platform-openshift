"""Transport-independent primitives for the live SAM3 ROS adapter."""

from __future__ import annotations

from collections import deque
from typing import Any

import numpy as np


def work_wait_expired(received: float, now: float, limit_ms: float) -> bool:
    """Admission-only wait bound; zero disables it, never refreshes capture age."""
    if not np.isfinite([received, now, limit_ms]).all() or limit_ms < 0:
        raise ValueError("invalid work-wait timing")
    return limit_ms > 0 and (now - received) * 1000 > limit_ms


def stamp_ns(message: Any) -> int:
    stamp = message.header.stamp
    return int(stamp.sec) * 1_000_000_000 + int(stamp.nanosec)


def pop_synchronized_triplet(
    rgb: deque,
    depth: deque,
    info: deque,
    tolerance_ns: int,
) -> tuple[tuple[Any, Any, Any] | None, dict[str, int]]:
    """Return the oldest synchronized RGB/depth/CameraInfo triplet.

    Inputs must be appended in source timestamp order. When head timestamps do
    not fit within tolerance, only the provably oldest head is discarded.
    """
    if tolerance_ns < 0:
        raise ValueError("tolerance_ns must be non-negative")
    discarded = {"rgb": 0, "depth": 0, "info": 0}
    queues = (("rgb", rgb), ("depth", depth), ("info", info))
    while all(queue for _, queue in queues):
        stamps = [(name, queue, stamp_ns(queue[0])) for name, queue in queues]
        oldest = min(stamps, key=lambda item: item[2])
        newest_ns = max(item[2] for item in stamps)
        if newest_ns - oldest[2] <= tolerance_ns:
            return tuple(queue.popleft() for _, queue in queues), discarded
        oldest[1].popleft()
        discarded[oldest[0]] += 1
    return None, discarded


def replace_oldest_bounded(queue: deque, item: Any) -> bool:
    """Append to a bounded deque; return True when an older item was dropped."""
    dropped = len(queue) == queue.maxlen
    if dropped:
        queue.popleft()
    queue.append(item)
    return dropped


def normalize_masks(masks: np.ndarray, scores: np.ndarray,
                    width: int, height: int) -> tuple[np.ndarray, np.ndarray]:
    """Validate/union model masks into policy labels 0=unobserved, 2=avoid."""
    mask_array = np.asarray(masks)
    score_array = np.asarray(scores, dtype=np.float32).reshape(-1)
    if not np.isfinite(score_array).all() or np.any((score_array < 0) | (score_array > 1)):
        raise ValueError("model returned invalid confidence scores")
    if not np.isfinite(mask_array).all():
        raise ValueError("model returned non-finite mask values")
    if mask_array.ndim == 4 and mask_array.shape[1] == 1:
        mask_array = mask_array[:, 0, :, :]
    if mask_array.ndim == 4 and mask_array.shape[0] == 1:
        mask_array = mask_array[0]
    if mask_array.ndim == 2:
        mask_array = mask_array[None, ...]
    if mask_array.ndim != 3:
        raise ValueError(f"expected masks [N,H,W], got {mask_array.shape}")
    if mask_array.shape[1:] != (height, width):
        raise ValueError(
            f"mask dimensions {mask_array.shape[2]}x{mask_array.shape[1]} "
            f"do not match input {width}x{height}"
        )
    if len(score_array) != mask_array.shape[0]:
        raise ValueError("mask and score counts differ")
    if np.any((mask_array < 0) | (mask_array > 1)):
        raise ValueError("masks must be binary or probabilities in [0,1]")
    union = np.any(mask_array > 0.5, axis=0)
    return union.astype(np.uint8) * 2, score_array
