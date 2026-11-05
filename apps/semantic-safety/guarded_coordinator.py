"""Combined admission core for the isolated single-owned-action fixture.

No sensor evidence is invented here. Caller supplies validated Evidence and an
audited registry predicate covering ALL task producers in its launch graph.
HotelGuardAdapter supplies the isolated hotel integration. Neither component
is a semantic payload validator or a safety-certified production supervisor.
Call on one executor thread; native transport is handled in a separate process.
"""
from dataclasses import asdict
from command_ledger import CommandLedger
from safety_core import COMMAND_GRACE_NS, SafetyGate, MS, UNCERTAINTY_NS, ZERO

# The terminal deceleration hold's total window (series-14 design): the
# smoother's terminal ramp completes in ~100-200 ms and the goal checker
# fires on the stopped robot within the BT's own tolerance window; two
# seconds bounds the deliberate stop's authority, after which the chain
# fails closed exactly as before (the honest outcome if the goal never
# completes).
TERMINAL_HOLD_MAX_S = 2_000_000_000


class GuardedCoordinator:
    def __init__(self, clock, link, task, registry_idle, now, *, registry_owned,
                 require_semantics=False):
        self.clock, self.link, self.task = clock, link, task
        self.registry_idle, self.now = registry_idle, now
        self.registry_owned = registry_owned
        self.gate = SafetyGate(require_semantics=require_semantics)
        self.ledger = CommandLedger()
        self.neutral = None
        self.state = "stopped"
        self.goal = None
        self.task_token = None
        self.native_ack = False
        self.seen_native_session = False
        self.sequence = 0
        self.events = []
        self.native_token = None
        self.last_send = None
        self.collision_blocked = False
        # The terminal-deceleration hold's bookkeeping (None until its first
        # application in a session; reset at each request/arm).
        self.terminal_hold_started = None
        self.terminal_hold_started_wall = 0

    def event(self, kind, **values):
        self.events.append({"event":kind,"steady_ns":self.now().steady,**values})

    def maybe_grace_command_deadline(self, now):
        """Apply the one-shot admission-scheduling grace (user-approved
        October 28, 2026, after pilot-1's mid-route renewal race).

        When the current command's lease is within COMMAND_GRACE_NS of
        expiry AND the ledger already holds a NEWER validated source — a
        smoother output that passed the record-time freshness checks, so
        the command pipeline is demonstrably alive end-to-end — extend the
        deadline by at most COMMAND_GRACE_NS once. The next source's
        checked admission then lands inside the grace instead of 1-3 ms
        past the previous source's fixed 100 ms expiry. Controller silence
        and monitor stalls record no newer source and trip at source+100
        unchanged; the worst-case applied authority age grows by at most
        COMMAND_GRACE_NS and only while a newer command is provably in
        flight. Every application is recorded as an event for the trial
        evidence."""
        deadline = self.gate.command_deadline
        if deadline is None or self.gate.command_grace_used:
            return
        if not 0 < deadline - now.steady <= COMMAND_GRACE_NS:
            return
        newer = [source for source in self.ledger.entries.values()
                 if source.wall_stamp > self.gate.command_wall]
        if not newer:
            return
        pending = max(newer, key=lambda source: source.wall_stamp)
        if self.gate.extend_command_deadline(now, COMMAND_GRACE_NS):
            # Force the VERY next tick's lease heartbeat to send at once
            # (negative-removal-on-pilot lesson): the packet issued just
            # before the grace window carries the ungraced expiry, and the
            # watchdog's lease runs from the last RECEIVED packet — a
            # regular >=20 ms heartbeat let the new-source packet land 2 ms
            # past the old expiry and drop the native session. The immediate
            # bridge packet carries the extended deadline.
            self.last_send = None
            self.event("command_deadline_grace", grace_ns=COMMAND_GRACE_NS,
                       pending_source_wall=pending.wall_stamp,
                       pending_ros_stamp=pending.ros_stamp,
                       extended_deadline=self.gate.command_deadline)

    def neutral_capture(self, ros_stamp, raw, checked):
        now = self.now()
        wall = self.clock.wall_bound(ros_stamp,now.wall)
        if wall is not None and tuple(raw)==ZERO and tuple(checked)==ZERO and now.wall-wall<98*MS:
            self.neutral = (wall,ros_stamp)

    def request(self, goal):
        now = self.now()
        if self.state != "stopped" or not self.link.ready or not self.clock.stationary(now.wall):
            return False
        if not self.registry_idle() or self.task.session.state != "idle": return False
        # NativeClock.stationary verifies 250 ms of independently captured
        # physical quiet AND applied zero while disarmed. Idle Nav2 publishes
        # no neutral heartbeat. Drain old commands with a new session/capture
        # barrier instead of requiring an unsolicited controller command.
        status = self.clock.status or {}
        neutral = (not self.collision_blocked and not self.clock.fault
                   and status.get("applied_vx") == 0 and status.get("applied_wz") == 0
                   and status.get("armed") is False and status.get("pending") is False)
        token = self.gate.arm(now, stationary=True, tasks_idle=True, neutral_command=neutral,
                              first_command_timeout_ns=5000*MS)
        if not token: return False
        self.ledger.reset(token,now.ros)
        self.native_token, self.last_send = token, None
        self.goal, self.state, self.task_token = goal, "arming", None
        self.terminal_hold_started = None
        self.terminal_hold_started_wall = 0
        self.native_ack = self.seen_native_session = False
        self.neutral = None
        self.event("arm_requested",session=token)
        if not self.link.send("arm", token, token): self.stop("native_queue_unavailable")
        return self.state == "arming"

    def stop(self, reason):
        if self.state == "stopped": return
        now = self.now()
        self.state, self.goal = "stopped", None
        token = self.native_token  # gate may already have tripped/cleared session
        self.gate.trip(reason,now)
        self.event("permission_revoked",reason=reason,session=token,trigger_steady_ns=self.gate.trigger_steady)
        self.link.send("stop",token,reason)
        self.task.stop(reason)

    def collision(self, action_type):
        # Clearing the monitor state restores readiness only, never permission.
        self.collision_blocked = action_type == 1
        if self.collision_blocked:
            self.stop("collision_monitor_stop")

    def commands_allowed(self):
        if self.state != "active": return False
        if not self.registry_owned(self.task_token):
            self.stop("unowned_or_unavailable_task"); return False
        return self.task.session.may_command(self.task_token)

    def source(self, ros_stamp, velocity):
        now = self.now()
        if not self.commands_allowed(): return False
        wall = self.clock.wall_bound(ros_stamp,now.wall)
        if wall is None: return False
        return self.ledger.record(self.gate.session,ros_stamp,wall,velocity,now)

    def checked(self, ros_stamp, velocity):
        now = self.now()
        if not self.commands_allowed(): return False
        source = self.ledger.resolve(self.gate.session,ros_stamp,velocity,now)
        if source is None: return False  # no receipt-time fallback, authority expires
        self.sequence += 1
        accepted = self.gate.command(self.gate.session,self.sequence,source.wall_stamp,velocity,now)
        if not accepted:
            if not self.gate.armed: self.stop(self.gate.reason)
            return False
        # Apply the existing one-shot, newer-source-proven grace before
        # forwarding, rather than sending a near-expired packet and only
        # considering grace in the following tick. This creates no new policy.
        self.maybe_grace_command_deadline(now)
        # Forward at admission, not up to 20 ms later. packet() still caps both
        # the original source deadline and the 80 ms native lease.
        return self.send_packet(now)

    def _wait_zero_ready(self):
        """Shared zero-Wait preconditions: an active owned task, the gate's
        last admitted command inside the <=0.005 settling tail, and a live
        armed non-pending native status for this session."""
        if (self.state!="active" or not self.registry_owned(self.task_token)
                or not self.task.session.may_command(self.task_token)
                or any(abs(v)>0.005 for v in self.gate.velocity)):
            return None
        status=self.clock.status if self.clock else None
        physical=status.get("physical") if status else None
        if (not status or not physical or status.get("session")!=self.gate.session
                or not status.get("armed") or status.get("pending")):
            return None
        return status

    def renew_terminal_zero(self, pending_stamp, pending_unbindable):
        """Stop deliberately through the unbindable terminal deceleration.

        Preconditions (the adapter supplies the joiner facts): the task is
        active and owned; the gate's last admitted velocity is within the
        terminal settling tail (<=0.055 m/s — the robot is already stopping
        at the qualified decel); a NEWER smoother output is validated and in
        hand (pending_stamp beyond the gate's command wall) but unbindable
        (the physics-stall bracket gap); and the hold's total duration stays
        within TERMINAL_HOLD_MAX_S of its first application. The hold applies
        the gate's terminal_zero_hold (zero-only, one decel step at most)
        and transmits immediately. A mid-route stall cannot trigger it (the
        gate's velocity would exceed the tail); a misfire is a stop, never
        motion."""
        if self.state != "active" or not self.registry_owned(self.task_token):
            return False
        if not pending_unbindable or not isinstance(pending_stamp, int):
            return False
        if pending_stamp <= self.gate.command_wall:
            return False
        now = self.now()
        if self.terminal_hold_started is None:
            if now.steady - self.terminal_hold_started_wall >= TERMINAL_HOLD_MAX_S:
                return False
        if not self.gate.terminal_zero_hold(self.gate.session, now):
            if not self.gate.armed:
                self.stop(self.gate.reason)
            return False
        if self.terminal_hold_started is None:
            self.terminal_hold_started = now.steady
            self.terminal_hold_started_wall = now.wall
        self.event("terminal_zero_renewal", task=self.task_token,
                   pending_stamp_ns=pending_stamp,
                   deadline=self.gate.command_deadline)
        return self.send_packet(now)

    def renew_wait_zero(self):
        """Renew zero-only Wait authority at settling-tail admission.

        The Nav2 command pipeline stamps the smoother's entire terminal
        deceleration ramp with the terminal command's stamp (7 x 10 ms steps
        at the qualified decel), so the last admissible settling-tail
        command carries only ~10-20 ms of its source lifetime: the October
        23 GPU series trial 2 lost the renewal by 1-4 ms of native-link
        delivery latency after the confirmation round trip. Renewal therefore
        must not wait for the native-status round trip that confirms the
        applied value. The zero lease only stops the robot sooner, the
        native watchdog revalidates every lease and stays fail-closed, and
        session disarm/loss still stops immediately. The confirmed hold
        (zero_wait_hold) remains the measured Wait-interval anchor, so the
        interval never begins on a deceleration step."""
        status=self._wait_zero_ready()
        if status is None: return False
        now=self.now()
        if not self.gate.zero_wait_hold(self.gate.session,now):
            if not self.gate.armed: self.stop(self.gate.reason)
            return False
        self.event("wait_zero_renewal",task=self.task_token,deadline=self.gate.command_deadline)
        return self.send_packet(now)

    def zero_wait_hold(self):
        """Keep an owned Nav2 Wait action fail-safe with short zero leases only.

        The native applied value must be inside the <=0.005 settling tail
        before this confirmed hold fires, so the measured Wait interval never
        begins on a deceleration step (October 23 gpu-render-2 interval-start
        race). Pre-confirmation authority renewal is renew_wait_zero above.
        The watchdog stays authoritative and fail-closed on every lease."""
        status=self._wait_zero_ready()
        if status is None: return False
        if abs(status.get("applied_vx",1))>0.005 or abs(status.get("applied_wz",1))>0.005:
            return False
        now=self.now()
        if not self.gate.zero_wait_hold(self.gate.session,now):
            if not self.gate.armed: self.stop(self.gate.reason)
            return False
        self.event("wait_zero_hold",task=self.task_token,deadline=self.gate.command_deadline)
        return self.send_packet(now)

    def send_packet(self, now):
        if self.state == "stopped": return False
        if self.state == "active" and not self.registry_owned(self.task_token):
            self.stop("unowned_or_unavailable_task"); return False
        if self.state == "arming" and not self.registry_idle():
            self.stop("task_appeared_during_arm"); return False
        if self.clock.fault or not self.clock.last or not 0 <= now.wall-self.clock.last["wall_ns"] < 100*MS:
            self.stop(self.clock.fault or "native_status_stale"); return False
        packet = self.gate.packet(now)
        if not packet:
            self.stop(self.gate.reason); return False
        if packet.expires_wall <= self.now().wall + UNCERTAINTY_NS:
            # Already inadmissible even with zero transport delay. Revoke;
            # never extend the source lifetime or send a known-invalid lease.
            self.stop("native_lease_margin_exhausted"); return False
        if not self.link.send("lease",packet.session,{"schema":"phase5-drive/v1",**asdict(packet)}):
            self.stop("native_queue_unavailable"); return False
        self.last_send = now.steady
        self.event("lease_enqueued",sequence=packet.sequence,issued_wall=packet.issued_wall,
                   expires_wall=packet.expires_wall,source_wall=self.gate.command_wall,
                   velocity=packet.velocity)
        return True

    def tick(self):
        now = self.now()
        self.maybe_grace_command_deadline(now)
        self.gate.tick(now)
        if self.state != "stopped" and not self.gate.armed:
            self.stop(self.gate.reason)
        for reply in self.link.poll():
            if reply["kind"] == "arm" and self.state == "arming" and reply["token"] == self.gate.session:
                if not reply["ok"]: self.stop("native_arm_rejected")
                else: self.native_ack = True
        if self.state == "stopped": return
        if self.state == "active" and not self.registry_owned(self.task_token):
            self.stop("unowned_or_unavailable_task"); return
        if self.clock.fault or not self.clock.last or now.wall-self.clock.last["wall_ns"]>=100*MS:
            self.stop(self.clock.fault or "native_status_stale"); return
        status = self.clock.status
        matches = status["session"] == self.gate.session and (status["armed"] or status["pending"])
        if matches: self.seen_native_session = True
        if self.seen_native_session and not matches:
            self.stop("native_session_lost"); return
        if self.state == "arming" and self.native_ack and matches:
            if not self.registry_idle() or self.task.session.state != "idle":
                self.stop("task_appeared_during_arm"); return
            goal, self.goal = self.goal, None
            try: self.task_token = self.task.start(goal)
            except Exception:
                self.stop("task_start_failed"); return
            self.state = "active"
            self.event("task_requested",task=self.task_token,session=self.gate.session)
        # Near-end-of-life heartbeat acceleration (user-approved October 28,
        # 2026, after series-17 trial 001-on): the regular 20 ms heartbeat
        # lets the watchdog's lease floor sit up to one cadence below the
        # gate's deadline while a source ages out — the grace's forced
        # packet then landed ~3 ms past the watchdog's expiry (series-17:
        # the last pre-grace packet carried 12 ms of life, the newer source
        # reached the ledger 6 ms after the watchdog's floor, the grace
        # fired at the next tick). When the current authority's remaining
        # life drops below 40 ms — exactly when admissions are gapping —
        # send every 5 ms instead, keeping the watchdog's floor within 5 ms
        # of the deadline so the one-shot grace always lands its rescue.
        # This creates no new authority: packets remain capped by the
        # source deadline; only their cadence changes.
        deadline=self.gate.command_deadline
        remaining=(deadline-now.steady) if deadline is not None else None
        interval=5*MS if (remaining is not None and remaining<40*MS) else 20*MS
        if self.last_send is None or now.steady-self.last_send >= interval:
            self.send_packet(now)

