"""Small, ROS-independent decisions shared by the local RMF/Nav2 adapter."""


def ros_topic(topic: str, namespace: str | None) -> str:
    """Resolve a topic for a robot namespace or root-level Nav2 graph."""
    clean_topic = topic.strip("/")
    clean_namespace = (namespace or "").strip("/")
    return f"/{clean_namespace}/{clean_topic}" if clean_namespace else f"/{clean_topic}"


def nav2_success(status: int) -> bool:
    """ROS 2 action status 4 is SUCCEEDED; canceled/aborted are never success."""
    return status == 4


def cancellation_confirmed(acknowledged_goal_count: int, terminal_status: int) -> bool:
    """A cancel ACK alone is insufficient; require terminal CANCELED status 5."""
    return acknowledged_goal_count > 0 and terminal_status == 5


def keep_active_goal(same_activity: bool, same_target: bool,
                     goal_in_flight: bool) -> bool:
    """Do not churn a live Nav2 goal for repeated callbacks of one RMF activity."""
    return same_activity and same_target and goal_in_flight
