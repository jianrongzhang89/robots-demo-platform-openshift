"""Real-input adapter for the isolated no-recovery hotel integration subgate.

Single executor thread only. Native status is the conservative capture clock;
scan/odom and capture-time TF are independently observed, never substituted
with physics status. No semantic policy or inference freshness is implied.
"""
import time
import math
import threading
from action_msgs.msg import GoalStatusArray
from action_msgs.srv import CancelGoal
from nav2_msgs.msg import CollisionMonitorState
from rclpy.qos import QoSProfile, DurabilityPolicy, ReliabilityPolicy
from rclpy.time import Time

from capture_joiner import CaptureJoiner
from command_audit import validate_graph, validate_observations
from guarded_coordinator import GuardedCoordinator
from hotel_task_registry import HotelTaskRegistry
from hotel_sensor_validation import valid_scan, valid_odom
from native_link import NativeLink
from nav_task_client import NavTaskClient
from safety_core import Evidence, MS
from priority_pump import StageTimings


class HotelGuardAdapter:
    def __init__(self, node, clock, tf, now, graph, endpoints, *, expected_scan_max=3.5,
                 allow_backup_wait=False, require_semantics=False):
        if expected_scan_max not in (3.5,12.): raise ValueError("unqualified scan contract")
        self.expected_scan_max=expected_scan_max
        validate_graph(graph)
        self.node,self.clock,self.tf,self.now,self.graph=node,clock,tf,now,graph
        self.registry=HotelTaskRegistry(endpoints,allow_backup_wait=allow_backup_wait)
        self.link=NativeLink()
        self.task=NavTaskClient(HotelTaskRegistry.PARENT,
            lambda _token,reason:self.co.stop(reason))
        self.co=GuardedCoordinator(clock,self.link,self.task,self.registry.idle,now,
                                   registry_owned=self.registry.owned,
                                   require_semantics=require_semantics)
        self.joiner=None
        self.samples={}
        self.invalid_inputs=set()
        # Fault-stop probe: stop refreshing ONLY the supervisor's scan
        # evidence. Nav2, the costmaps and the Collision Monitor keep
        # receiving the real scan stream; the gate's 500 ms input freshness
        # must then stop the chain fail-closed.
        self.fault_scan_blocked=False
        self.last_evidence={}
        self.events=[]
        self.command_trace=[]
        self.tf_trace=[]
        self.timings=StageTimings()
        self.cancel_clients={name:node.create_client(CancelGoal,name+"/_action/cancel_goal") for name in endpoints}
        self.cancel_pending={}
        self.cancel_acks=set()
        self.cancel_sweep_started=None
        self.last_cancel=0
        self.expected_clients=None
        self.prepared=False
        self.stopping=False
        # October 19 prescription, required by the observation load: the
        # synchronous graph audit is moved OFF the command processing path
        # (it reached 104 ms under the SAM3 observation pod and stopped a
        # trial native_capture_stale). A dedicated thread runs the same
        # audit; the tick enforces a bounded fail-closed freshness contract
        # instead of blocking on the audit itself.
        self.audit_freshness_ns=500*MS
        self.audit_state={"steady_ns":0,"duration_ns":0,"completed":0}
        self.audit_stop=threading.Event()
        self.audit_thread=None
        qos=QoSProfile(depth=1,reliability=ReliabilityPolicy.RELIABLE,
                       durability=DurabilityPolicy.TRANSIENT_LOCAL)
        self.subscriptions=[node.create_subscription(GoalStatusArray,name+"/_action/status",
            lambda m,n=name:self.action_status(n,m),qos) for name in endpoints]
        self.subscriptions.append(node.create_subscription(CollisionMonitorState,
            "/robot_1/collision_monitor_state",self.collision,10))

    def maybe_wait_hold(self):
        """Evaluate the zero-wait hold when the owned Wait child is active.

        Called from the observer loop and from the native-ingest path: the
        latter runs at pump frequency so the hold fires within milliseconds
        of the native confirming the settling tail, without waiting for the
        next (slower) observer pass.
        """
        now=self.co.now()
        if not (self.registry.waiting(self.co.task_token,now.steady)
                and self.co.commands_allowed()):
            return False
        return self.co.zero_wait_hold()

    def collision(self, message):
        self.events.append({"event":"collision_state","action":message.action_type,
                            "polygon":message.polygon_name,"wall_ns":time.time_ns()})
        self.co.collision(message.action_type)

    def action_status(self, endpoint, message):
        steady=time.monotonic_ns()
        self.registry.observe(endpoint,[(self.registry.uuid(s.goal_info.goal_id.uuid),s.status)
                                         for s in message.status_list],wall_ns=time.time_ns(),
                           steady_ns=steady)
        # Start a zero-only hold at the Wait acceptance event, not at the next
        # full observer-loop pass. Recovery BT callbacks can arrive close to
        # the original command deadline under simulator load.
        if (endpoint=="/robot_1/wait" and any(s.status==2 for s in message.status_list)
                and self.registry.waiting(self.co.task_token,steady)):
            self.co.zero_wait_hold()

    def client_graph(self):
        rows=[]
        for name,namespace in self.node.get_node_names_and_namespaces():
            for service,types in self.node.get_client_names_and_types_by_node(name,namespace):
                if "/_action/" in service:
                    rows.append((namespace,name,service,tuple(sorted(types))))
        return sorted(rows)

    def audit_graph(self):
        try:
            actual={topic:[{"node":r.node_name,"namespace":r.node_namespace,"type":r.topic_type,
                            "gid":list(r.endpoint_gid)}
                           for r in self.node.get_publishers_info_by_topic("/robot_1/"+topic)]
                    for topic in self.graph}
            validate_graph(actual)
            same=all(sorted(actual[t],key=lambda r:r["gid"])==sorted(self.graph[t],key=lambda r:r["gid"])
                     for t in self.graph)
            endpoints={s.split("/_action/",1)[0] for s,_ in self.node.get_service_names_and_types() if "/_action/" in s}
            same &= endpoints==self.registry.endpoints
            same &= not self.node.get_publishers_info_by_topic("/cmd_vel")
            same &= not self.node.get_publishers_info_by_topic("/robot_1/cmd_vel")
            clients=self.client_graph()
            same &= all(self.registry.client_allowed(namespace,name,service)
                        for namespace,name,service,_ in clients)
            if self.expected_clients is not None: same &= clients==self.expected_clients
            self.registry.graph_ok=bool(same)
            if self.prepared and not same: self.registry.fault="closed_graph_changed"
        except Exception as error:
            self.registry.graph_ok=False
            self.events.append({"event":"graph_error","detail":str(error)})

    def cancel_all(self):
        # Used ONLY inside the freshly launched private fixture. ACK is tracked
        # separately from terminal status and the parent's action result.
        now=time.monotonic()
        if self.cancel_sweep_started is None: self.cancel_sweep_started=now
        for name,client in self.cancel_clients.items():
            if name in self.cancel_pending: continue
            if not client.service_is_ready(): continue
            self.cancel_pending[name]=client.call_async(CancelGoal.Request())
        self.last_cancel=now

    def poll_cancel(self):
        for name,future in list(self.cancel_pending.items()):
            if not future.done(): continue
            del self.cancel_pending[name]
            try:
                reply=future.result()
                if reply.return_code==0: self.cancel_acks.add(name)
                self.events.append({"event":"cancel_all_ack","endpoint":name,"code":reply.return_code,
                                    "canceling":len(reply.goals_canceling)})
            except Exception as error:
                self.registry.fault="cancel_transport_error"
                self.events.append({"event":"cancel_error","detail":str(error)})

    def prepare(self):
        # Call after all action-client discovery and zero-authority startup.
        self.expected_clients=self.client_graph()
        self.audit_graph()
        if not self.registry.graph_ok: raise RuntimeError("closed hotel graph not ready")
        # Seed the freshness clock with this completed synchronous audit so
        # the gate cannot trip before the background thread's first pass.
        self.audit_state["steady_ns"]=time.monotonic_ns()
        self.start_background_audit()
        self.cancel_all()

    def ready(self):
        self.poll_cancel()
        if (self.cancel_acks==self.registry.endpoints and not any(self.registry.active().values())
                and self.link.ready and self.task.client.server_is_ready()):
            self.registry.primed=True
            self.prepared=True
        return (self.prepared and self.registry.idle() and not self.invalid_inputs
                and self.clock and not self.clock.fault
                and all(k in self.co.gate.leases for k in self.co.gate.required))

    def request(self, goal):
        self.audit_graph()
        if not self.ready() or not self.co.request(goal): return False
        self.joiner=CaptureJoiner(self.co.ledger,self.clock.wall_bound)
        return True

    def sensor(self, kind, message):
        if kind=="scan" and self.fault_scan_blocked:
            return
        if not (valid_scan(message,expected_max_range=self.expected_scan_max) if kind=="scan" else valid_odom(message)):
            self.invalid_inputs.add(kind)
            detail={"event":"sensor_payload_rejected","kind":kind,
                    "stamp":message.header.stamp.sec*1_000_000_000+message.header.stamp.nanosec,
                    "frame":message.header.frame_id,"wall_ns":time.time_ns()}
            if kind=="scan":
                detail.update(samples=len(message.ranges),range_min=message.range_min,range_max=message.range_max,
                    expected_range_max=self.expected_scan_max,
                    angle_min=message.angle_min,angle_max=message.angle_max,angle_increment=message.angle_increment,
                    nan=sum(math.isnan(v) for v in message.ranges),negative=sum(v<0 for v in message.ranges),
                    finite=sum(math.isfinite(v) for v in message.ranges),
                    ranges=[v if math.isfinite(v) else str(v) for v in message.ranges])
            self.events.append(detail)
            self.samples.pop(kind,None)
            self.co.stop(kind+"_payload_invalid")
            return
        self.invalid_inputs.discard(kind)
        stamp=message.header.stamp.sec*1_000_000_000+message.header.stamp.nanosec
        frame=message.header.frame_id
        # Latest-only mailbox bounds backlog; all timestamps remain capture time.
        old=self.samples.get(kind)
        if old and stamp<old[0]: self.co.stop(kind+"_rollback")
        self.samples[kind]=(stamp,frame)

    def evidence(self, kind, stamp):
        if stamp<=self.last_evidence.get(kind,-1): return
        now=self.now(); bound=self.clock.wall_bound(stamp,now.wall)
        if bound is None or stamp>now.ros: return
        if self.co.gate.observe(kind,Evidence(self.clock.epoch,stamp,bound,stamp),now):
            self.last_evidence[kind]=stamp

    def observe_semantic_lease(self, key, epoch, sequence, wall, ros):
        """Feed one armed-semantic lease observation to the gate.

        The evidence (epoch, strictly increasing sequence, capture wall,
        capture ros stamp) is supplied by the observation worker from the
        camera capture traces, the SAM3 timing records and the inference
        status heartbeat. The gate applies the unchanged 500 ms capture-age
        and wall-clock freshness contract; nothing here renews authority for
        a stopped session.
        """
        if key not in self.co.gate.required: return False
        return self.co.gate.observe(key,Evidence(epoch,sequence,wall,ros),self.now())

    def command(self, row):
        if not self.joiner or not self.co.commands_allowed(): return
        row=dict(row)
        self.command_trace.append(row)
        try:
            validate_observations(self.graph,[dict(row,bound=None)])
            if row["source_timestamp"]<=0: raise ValueError("missing DDS source timestamp")
        except (KeyError,ValueError) as error:
            self.co.stop("command_provenance_invalid")
            self.events.append({"event":"command_rejected","reason":str(error)})
            return
        if row["kind"] != "smoothed":
            now=self.now()
            self.joiner.receive(row,now)
            # Process each capture at ingress instead of waiting for the next
            # observer tick. The command pump can be busy servicing unrelated
            # observers long enough for an otherwise valid capture to age out
            # of the bounded join window. This does not extend either the join
            # window or the ledger's original capture deadline.
            if callable(getattr(self.joiner,"drain",None)):
                self._drain_commands(now)

    def scan_transform(self, stamp, frame):
        # An already-qualified capture cannot renew evidence. Avoid repeating
        # its TF lookup on every callback while waiting for the next scan.
        if stamp<=self.last_evidence.get("tf",-1): return
        now=self.now()
        if not self.tf_trace or self.tf_trace[-1]["stamp"]!=stamp:
            self.tf_trace.append({"stamp":stamp,"frame":frame,"first_wall":now.wall,"attempts":0})
        row=self.tf_trace[-1]
        row.update(last_wall=now.wall,ros_now=now.ros,attempts=row["attempts"]+1)
        capture=Time(nanoseconds=stamp)
        if self.tf.can_transform("map",frame,capture):
            self.tf.lookup_transform("map",frame,capture)
            self.evidence("tf",stamp)
            row.update(transform_available=True,qualified=self.last_evidence.get("tf")==stamp)
        elif "first_error" not in row:
            # Failure diagnostics only; no latest-TF substitution or authority.
            row["transform_available"]=False
            row.update(first_failure_wall_ns=now.wall,first_failure_steady_ns=now.steady)
            try: self.tf.lookup_transform("map",frame,capture)
            except Exception as error: row["first_error"]=str(error)
            for target,source in (("map","odom"),("odom",frame)):
                try:
                    transform=self.tf.lookup_transform(target,source,Time())
                    row[target+"_to_"+source+"_latest"]= (
                        transform.header.stamp.sec*1_000_000_000+transform.header.stamp.nanosec)
                except Exception as error: row[target+"_to_"+source+"_error"]=str(error)

    def start_background_audit(self):
        """Run the unchanged graph audit on a dedicated thread.

        The audit's checks, fault latching and event records are identical;
        only its execution leaves the command processing path. The tick
        enforces the freshness contract: no completed audit within
        audit_freshness_s latches a fault and stops the chain fail-closed.
        """
        if self.audit_thread is not None:
            return
        self.audit_thread=threading.Thread(target=self._audit_loop,
                                           name="phase5_graph_audit",daemon=True)
        self.audit_thread.start()

    def _audit_loop(self):
        while not self.audit_stop.is_set():
            started=time.monotonic_ns()
            try:
                self.audit_graph()
            except Exception as error:
                self.registry.graph_ok=False
                self.events.append({"event":"graph_error","detail":str(error)})
            self.audit_state["duration_ns"]=time.monotonic_ns()-started
            self.audit_state["completed"]+=1
            self.audit_state["steady_ns"]=time.monotonic_ns()
            self.audit_stop.wait(.05)

    def audit_fresh(self, steady_ns):
        return steady_ns-self.audit_state["steady_ns"]<=self.audit_freshness_ns

    def _drain_commands(self, now):
        if not (self.joiner and self.co.commands_allowed()):
            return
        for row in self.timings.call("command_drain",lambda:self.joiner.drain(now)):
            if row["bound"]>row["source_timestamp"]:
                self.co.stop("capture_after_publication"); break
            if row["kind"]=="checked":
                wait_owned=self.registry.waiting(self.co.task_token,now.steady)
                if wait_owned and any(abs(v)>0.005 for v in row["velocity"]):
                    wait_start=next((e["steady_ns"] for e in reversed(self.registry.events)
                        if e["endpoint"]=="/robot_1/wait" and e["status"]==2),None)
                    wait_hold_started=any(e["event"]=="wait_zero_hold" and e.get("task")==self.co.task_token
                                          for e in self.co.events)
                    vx,vy,wz=row["velocity"]
                    settling=(not wait_hold_started and wait_start is not None
                        and 0<=now.steady-wait_start<300*MS
                        and -0.055<=vx<-0.005 and abs(vy)<=0.005 and abs(wz)<=0.005)
                    if not settling:
                        self.co.stop("nonzero_command_during_wait"); break
                row["forwarded"]=self.timings.call("command_forward",
                    lambda:self.co.checked(row["stamp"],row["velocity"]))

    def tick(self):
        self.timings.call("cancel_poll", self.poll_cancel)
        now=self.now()
        # The graph audit runs on its dedicated thread; enforce its bounded
        # freshness instead of blocking the command path on it.
        if self.prepared and not self.audit_fresh(now.steady):
            self.registry.fault="graph_audit_stale"
        if self.clock is None:
            self.link.poll()
            return  # all transport/client discovery completes while disarmed
        self.evidence("clock",now.ros)
        for kind in ("scan","odom"):
            if kind in self.samples:
                stamp,frame=self.samples[kind]
                self.evidence(kind,stamp)
                # Map -> measured sensor frame at scan CAPTURE, not latest TF.
                if kind=="scan":
                    self.timings.call("scan_transform",lambda:self.scan_transform(stamp,frame))
        wait_active=any(status in (1,2,3) for status in
                        self.registry.goals["/robot_1/wait"].values())
        wait_owned=self.registry.waiting(self.co.task_token,now.steady)
        if self.co.state=="active" and wait_active and not wait_owned:
            self.co.stop("wait_duration_exceeded_or_unowned")
        # Drain the already-received checked commands BEFORE the gate's
        # deadline check (user-approved October 27, 2026): a received,
        # validated, in-window renewal must not be lost to the deadline
        # expiring first (pilot-1 off-arm: the collision monitor's ~74 ms
        # TF-wait stall delayed the checked copy 2-3 ms past the gate's
        # renewal deadline while it sat unprocessed in the joiner, still
        # inside the ledger's source window with ~4 ms of margin). The
        # ledger's own capture-based source window and the gate's per-command
        # issued-wall checks are unchanged; true command loss still trips
        # exactly as before. This mirrors the renewal/confirmation split:
        # ordering must not remove valid authority already in hand.
        if self.joiner and self.co.commands_allowed():
            self._drain_commands(now)
            # The terminal-deceleration hold (user-approved October 28, 2026,
            # after series-14 trial 003-on): when the smoother's terminal ramp
            # is in flight (the settling tail at or below 0.055 m/s) and its
            # terminal source is unbindable (the physics-stall bracket gap —
            # a newer validated raw sits in the joiner with no bound), stop
            # deliberately through zero-only authority so the goal checker
            # completes on the stopped robot. Mid-route stalls cannot trigger
            # it: the gate's velocity would exceed the tail.
            if self.co.commands_allowed():
                pending_terminal=None
                for row,_ in self.joiner.pending:
                    if row.get("kind")=="raw" and row.get("stamp",0)>self.co.gate.command_wall:
                        pending_terminal=row.get("stamp")
                        break
                if pending_terminal is not None:
                    self.co.renew_terminal_zero(pending_terminal, True)
        # Renew after draining checked commands: a queued zero may carry the
        # original, nearly-expired source deadline and must not undo the
        # narrowly authorized Wait hold. Nonzero commands are rejected above.
        if wait_owned and self.co.commands_allowed() and not self.maybe_wait_hold():
            # Pre-confirmation only: the smoother's terminal decel ramp reuses
            # the terminal command's stamp, so the settling-tail command keeps
            # only ~10-20 ms of source authority — not enough for the native
            # applied-value round trip. Renew zero authority immediately; the
            # confirmed hold above still anchors the measured interval.
            self.co.renew_wait_zero()
        self.timings.call("coordinator_tick",self.co.tick)
        if self.co.native_token and self.co.state=="stopped":
            if not self.stopping:
                self.stopping=True; self.cancel_acks.clear(); self.cancel_sweep_started=None
            if time.monotonic()-self.last_cancel>=.2: self.cancel_all()
            if self.cancel_sweep_started and time.monotonic()-self.cancel_sweep_started>2:
                if any(self.registry.active().values()) or self.cancel_acks!=self.registry.endpoints:
                    self.registry.fault="descendant_terminal_timeout"

    def close(self):
        self.audit_stop.set()
        if self.audit_thread is not None:
            self.audit_thread.join(timeout=2)
        self.co.stop("fixture_shutdown")
        self.link.close()
        self.task.destroy_node()
