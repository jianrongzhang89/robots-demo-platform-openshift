"""Lifecycle fence for a closed, freshly launched private hotel fixture.

NOT caller authentication: ROS status UUIDs contain no parent lineage. The
adapter must audit/freeze the client graph, prohibit external dispatch, and
complete an initial cancel-all sweep on every freshly launched server. Only
the pinned baseline tree's planner/follower children are permitted. Status is
event-driven, not a heartbeat. Unresolved cancellations never establish idle.
"""
import uuid


class HotelTaskRegistry:
    PARENT = "/robot_1/navigate_to_pose"
    BASELINE_CHILDREN = {"/robot_1/compute_path_to_pose", "/robot_1/follow_path"}
    RECOVERY_CHILDREN = BASELINE_CHILDREN | {"/robot_1/backup", "/robot_1/wait"}
    ENDPOINTS = {"/robot_1/"+name for name in ("navigate_to_pose","navigate_through_poses",
        "follow_path","compute_path_to_pose","compute_path_through_poses","smooth_path",
        "spin","backup","drive_on_heading","wait")}

    def __init__(self, endpoints, *, allow_backup_wait=False):
        self.endpoints = set(endpoints)
        if self.endpoints != self.ENDPOINTS:
            raise ValueError("unexpected or missing hotel actions")
        self.goals = {name:{} for name in endpoints}
        self.children = self.RECOVERY_CHILDREN if allow_backup_wait else self.BASELINE_CHILDREN
        self.primed = False
        self.graph_ok = False
        self.fault = None
        self.events = []

    def observe(self, endpoint, rows, *, wall_ns=None, steady_ns=None):
        if endpoint not in self.endpoints:
            self.fault = "unexpected_action_endpoint"; return
        # Keep prior active entries until an explicit terminal status arrives;
        # an empty/missing status array is not terminal evidence.
        for token, status in rows:
            if status not in (1,2,3,4,5,6):
                self.fault = "invalid_action_status"; return
            old = self.goals[endpoint].get(token)
            if old in (4,5,6) and status in (1,2,3):
                self.fault = "terminal_action_reactivated"; return
            self.goals[endpoint][token] = status
            if old!=status:
                self.events.append({"endpoint":endpoint,"token":token,"status":status,
                                    "wall_ns":wall_ns,"steady_ns":steady_ns})

    def active(self):
        return {name:{token for token,status in rows.items() if status in (1,2,3)}
                for name,rows in self.goals.items()}

    def idle(self):
        return self.primed and self.graph_ok and not self.fault and not any(self.active().values())

    def waiting(self, token, now_steady, *, max_duration_ns=2500_000_000):
        # The ownership cap bounds how long an owned /robot_1/wait goal may
        # run before the coordinator fails closed. The recovery tree's Wait
        # is 1.0 s of SIMULATION time; its wall duration is 1.0 s / RTF plus
        # dispatch overhead. The previous 1.5 s wall value was implicitly
        # calibrated to the 15 Hz-era RTF (~0.70, wait ~1.46 s wall); the
        # user-approved 30 Hz candidate runs at RTF ~0.675, where the
        # legitimate wait reaches ~1.50 s and raced the cap by milliseconds
        # (qualification-9 recovery trial-03 lost by 4 ms with the wait
        # actually succeeding). 2.5 s keeps a stuck or unowned wait
        # detectable within 2.5 s while accommodating RTF down to ~0.45.
        if not self.owned(token): return False
        active=self.active()["/robot_1/wait"]
        if len(active)!=1: return False
        goal=next(iter(active))
        started=next((e["steady_ns"] for e in reversed(self.events)
                      if e["endpoint"]=="/robot_1/wait" and e["token"]==goal
                      and e["status"]==2),None)
        return bool(started is not None and 0<=now_steady-started<=max_duration_ns)

    def owned(self, token):
        if not self.primed or not self.graph_ok or self.fault or not token: return False
        active = self.active()
        # Parent/children legitimately have DIFFERENT UUIDs. This is a closed
        # graph lifecycle constraint, not inferred cryptographic ownership.
        if active[self.PARENT] - {token}: return False
        return (all(not ids for name,ids in active.items()
                    if name not in self.children and name != self.PARENT)
                and sum(len(active[name]) for name in self.children)<=1)

    @staticmethod
    def uuid(raw):
        return str(uuid.UUID(bytes=bytes(raw)))

    def client_allowed(self, namespace, node, service):
        cls=type(self)
        endpoint,method=service.split("/_action/",1)
        if method not in ("send_goal","get_result","cancel_goal"): return False
        if namespace=="/" and node=="phase5_hotel_observer":
            return endpoint in cls.ENDPOINTS if method=="cancel_goal" else endpoint in {
                cls.PARENT,"/robot_1/compute_path_to_pose"}
        if (namespace,node) in (("/","phase5_task_client"),("/robot_1","bt_navigator")):
            return endpoint==cls.PARENT
        if namespace=="/robot_1" and node=="bt_navigator_navigate_to_pose_rclcpp_node":
            return endpoint in self.children
        if namespace=="/robot_1" and node=="bt_navigator_navigate_through_poses_rclcpp_node":
            return endpoint in {"/robot_1/"+name for name in
                                ("compute_path_through_poses","follow_path","spin","backup","wait")}
        return False
