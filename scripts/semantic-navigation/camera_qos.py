"""Configuration helpers for the semantic RGB-D camera path."""


def subscription_history_depth(value: str | None, default: int = 2) -> int:
    """Parse and validate the bounded ROS subscription history depth."""
    if value is None:
        depth = default
    else:
        try:
            depth = int(value)
        except (TypeError, ValueError) as error:
            raise ValueError(
                f"SEMANTIC_CAMERA_SUBSCRIPTION_DEPTH must be a positive integer, got {value!r}"
            ) from error
    if depth < 1:
        raise ValueError(
            f"SEMANTIC_CAMERA_SUBSCRIPTION_DEPTH must be positive, got {depth}"
        )
    return depth
