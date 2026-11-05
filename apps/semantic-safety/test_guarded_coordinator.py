import unittest
from types import SimpleNamespace
from guarded_coordinator import GuardedCoordinator
from safety_core import Evidence, MS, Now, ZERO
from task_session import TaskSession


class Link:
    def __init__(self): self.ready=True; self.sent=[]; self.replies=[]; self.available=True
    def send(self,*args): self.sent.append(args); return self.available
    def poll(self): result,self.replies=self.replies,[]; return result


class Task:
    def __init__(self): self.session=TaskSession(); self.starts=0
    def start(self,goal): self.starts+=1; return self.session.begin(1)
    def stop(self,reason): self.session.revoke(reason,1)


class CoordinatorTests(unittest.TestCase):
    def setUp(self):
        self.now=Now(1000*MS,10000*MS,2000*MS)
        self.quiet,self.idle=True,True
        self.clock=SimpleNamespace(stationary=lambda _:self.quiet, fault=None,
            last={"wall_ns":self.now.wall},status={"session":"","armed":False,"pending":False,
                                                     "applied_vx":0,"applied_wz":0},
            wall_bound=lambda stamp,wall:wall-5*MS)
        self.link,self.task=Link(),Task()
        self.owned=True
        self.co=GuardedCoordinator(self.clock,self.link,self.task,lambda:self.idle,lambda:self.now,
                                   registry_owned=lambda token:self.owned)
        for key in self.co.gate.required:
            self.co.gate.observe(key,Evidence("e",1,self.now.wall,self.now.ros),self.now)
        self.co.neutral_capture(self.now.ros-5*MS,ZERO,ZERO)

    def test_live_preconditions_not_caller_boolean_arm(self):
        self.quiet=False; self.assertFalse(self.co.request("goal"))
        self.quiet=True; self.idle=False; self.assertFalse(self.co.request("goal"))
        self.idle=True; self.clock.status["applied_vx"]=.1; self.assertFalse(self.co.request("goal"))
        self.assertEqual(self.link.sent,[])

    def activate(self):
        self.assertTrue(self.co.request("goal")); token=self.co.gate.session
        self.link.replies=[{"kind":"arm","token":token,"ok":True}]
        self.clock.status={"session":token,"pending":True,"armed":False}
        self.co.tick()
        self.task.session.accepted(self.co.task_token,True,1)
        self.now=Now(self.now.steady+10*MS,self.now.wall+10*MS,self.now.ros+10*MS)

    def test_cold_start_needs_native_zero_not_idle_nav2_heartbeat(self):
        self.co.neutral=None
        self.assertTrue(self.co.request("goal"))
        self.assertFalse(self.co.ledger.entries)

    def test_idle_race_before_dispatch(self):
        self.co.request("goal"); token=self.co.gate.session
        self.idle=False
        self.link.replies=[{"kind":"arm","token":token,"ok":True}]
        self.clock.status={"session":token,"pending":True,"armed":False}
        self.co.tick()
        self.assertEqual(self.task.starts,0)
        self.assertEqual(self.co.state,"stopped")

    def test_checked_forwards_immediately_without_extending_deadline(self):
        self.activate()
        stamp=self.now.ros; velocity=(.1,0.,0.)
        self.assertTrue(self.co.source(stamp,velocity))
        count=len(self.link.sent)
        self.assertTrue(self.co.checked(stamp,velocity))
        self.assertEqual(len(self.link.sent),count+1)
        packet=self.link.sent[-1][2]
        self.assertLessEqual(packet["expires_wall"],self.now.wall-5*MS+98*MS)
        self.co.tick(); self.assertEqual(len(self.link.sent),count+1)

    def test_command_grace_requires_a_newer_recorded_source(self):
        """The admission-scheduling grace fires only with a newer validated
        source in the ledger, extends once, and is recorded as an event."""
        from safety_core import COMMAND_GRACE_NS
        self.activate()
        velocity=(.1,0.,0.)
        self.assertTrue(self.co.source(self.now.ros,velocity))
        self.assertTrue(self.co.checked(self.now.ros,velocity))
        deadline=self.co.gate.command_deadline
        # Advance to just inside the grace window with NO newer source: no
        # extension (controller silence / monitor stall trip unchanged).
        self.now=Now(deadline-5*MS,deadline-5*MS+9_000*MS,self.now.ros+95*MS)
        for key in self.co.gate.required:
            self.co.gate.observe(key,Evidence("e",2,self.now.wall,self.now.ros),self.now)
        self.co.maybe_grace_command_deadline(self.now)
        self.assertEqual(self.co.gate.command_deadline,deadline)
        # A newer validated source arrives (the ledger records it)...
        self.now=Now(deadline-3*MS,deadline-3*MS+9_000*MS,self.now.ros+2*MS)
        self.assertTrue(self.co.source(self.now.ros,velocity))
        self.co.maybe_grace_command_deadline(self.now)
        # ...and the grace extends once, with an evidence event.
        self.assertEqual(self.co.gate.command_deadline,deadline+COMMAND_GRACE_NS)
        self.assertTrue(any(e["event"]=="command_deadline_grace"
                            for e in self.co.events))
        # One-shot: no further extension even with more newer sources.
        self.now=Now(deadline-1*MS,deadline-1*MS+9_000*MS,self.now.ros+2*MS)
        self.assertTrue(self.co.source(self.now.ros,velocity))
        self.co.maybe_grace_command_deadline(self.now)
        self.assertEqual(self.co.gate.command_deadline,deadline+COMMAND_GRACE_NS)
        self.assertEqual(sum(1 for e in self.co.events
                             if e["event"]=="command_deadline_grace"),1)

    def test_checked_applies_proven_grace_before_forwarding_short_lease(self):
        self.activate()
        stamp=self.now.ros;velocity=(.1,0.,0.)
        self.assertTrue(self.co.source(stamp,velocity))
        self.assertTrue(self.co.checked(stamp,velocity))
        deadline=self.co.gate.command_deadline
        self.now=Now(deadline-MS,deadline-MS+9000*MS,stamp+92*MS)
        self.clock.last={"wall_ns":self.now.wall}
        # A newer validated raw source exists; the checked copy of the old
        # source must carry grace on its FIRST forward, not on a later tick.
        self.assertTrue(self.co.source(self.now.ros,velocity))
        self.assertTrue(self.co.checked(stamp,velocity))
        packet=self.link.sent[-1][2]
        self.assertEqual(packet["expires_wall"]-packet["issued_wall"],26*MS)
        self.assertTrue(self.co.gate.command_grace_used)
        events=[e["event"] for e in self.co.events]
        self.assertEqual(events[-2:],["command_deadline_grace","lease_enqueued"])

    def test_no_newer_source_revokes_instead_of_sending_inadmissible_lease(self):
        self.activate()
        stamp=self.now.ros;velocity=(.1,0.,0.)
        self.assertTrue(self.co.source(stamp,velocity))
        self.assertTrue(self.co.checked(stamp,velocity))
        deadline=self.co.gate.command_deadline
        self.now=Now(deadline-MS,deadline-MS+9000*MS,stamp+92*MS)
        self.clock.last={"wall_ns":self.now.wall}
        leases_before=sum(kind=="lease" for kind,_,_ in self.link.sent)
        self.assertFalse(self.co.checked(stamp,velocity))
        self.assertEqual(sum(kind=="lease" for kind,_,_ in self.link.sent),leases_before)
        self.assertEqual(self.co.gate.reason,"native_lease_margin_exhausted")
        self.assertEqual(self.co.state,"stopped")
        self.assertEqual(self.link.sent[-1][0],"stop")

    def test_command_grace_saves_a_late_admission(self):
        """The race the grace exists for: the next source's checked admission
        lands a few ms past the previous source's expiry and still renews."""
        from safety_core import COMMAND_GRACE_NS
        self.activate()
        velocity=(.15,0.,0.)
        self.assertTrue(self.co.source(self.now.ros,velocity))
        self.assertTrue(self.co.checked(self.now.ros,velocity))
        deadline=self.co.gate.command_deadline
        newer_ros=self.now.ros
        def advance(steady,ros):
            self.now=Now(steady,steady+9_000*MS,ros)
            self.clock.last={"wall_ns":self.now.wall}
        # A newer validated source is recorded just before the old deadline...
        advance(deadline-4*MS,newer_ros+94*MS)
        self.assertTrue(self.co.source(self.now.ros,velocity))
        # ...the coordinator's tick inside the grace window applies it...
        advance(deadline-2*MS,self.now.ros+2*MS)
        for key in self.co.gate.required:
            self.co.gate.observe(key,Evidence("e",3,self.now.wall,self.now.ros),self.now)
        self.co.tick()
        self.assertTrue(self.co.gate.armed,self.co.gate.reason)
        self.assertEqual(self.co.gate.command_deadline,deadline+COMMAND_GRACE_NS)
        # The grace forces that same tick's heartbeat: the bridge packet
        # carrying the extended deadline is sent at once, not on the 20 ms
        # cadence.
        sent_after_grace=len(self.link.sent)
        self.assertGreater(sent_after_grace,0)
        bridge=self.link.sent[-1][2]
        self.assertGreaterEqual(bridge["expires_wall"],
                                deadline+COMMAND_GRACE_NS-5*MS)
        # ...time passes the ORIGINAL deadline and the chain survives...
        advance(deadline+2*MS,self.now.ros+4*MS)
        for key in self.co.gate.required:
            self.co.gate.observe(key,Evidence("e",4,self.now.wall,self.now.ros),self.now)
        self.co.tick()
        self.assertTrue(self.co.gate.armed,self.co.gate.reason)
        # ...and the late checked admission still renews the chain.
        self.assertTrue(self.co.checked(newer_ros+94*MS,velocity))
        self.assertTrue(self.co.gate.armed,self.co.gate.reason)

    def test_heartbeat_accelerates_near_end_of_life(self):
        """Series-17 trial 001-on: the 20 ms heartbeat cadence lets the
        watchdog's lease floor sit one cadence below the gate's deadline
        while a source ages out, so the grace's forced packet can land past
        the watchdog's expiry. Inside the last 40 ms of authority the
        heartbeat runs at 5 ms; outside it the regular 20 ms cadence holds.
        The packets carry no new authority — only their cadence changes."""
        self.activate()
        velocity=(.15,0.,0.)
        self.assertTrue(self.co.source(self.now.ros,velocity))
        self.assertTrue(self.co.checked(self.now.ros,velocity))
        deadline=self.co.gate.command_deadline
        first=len(self.link.sent)  # the admission packet
        def advance(steady):
            self.now=Now(steady,steady+9_000*MS,self.now.ros)
            self.clock.last={"wall_ns":self.now.wall}
            for key in self.co.gate.required:
                self.co.gate.observe(key,Evidence("e",3,self.now.wall,self.now.ros),self.now)
        # Plenty of authority left: the regular 20 ms cadence applies (the
        # admission packet went out at deadline-93).
        advance(deadline-85*MS)
        self.co.tick()
        self.assertEqual(len(self.link.sent),first)  # 8 ms since last: nothing
        advance(deadline-70*MS)
        self.co.tick()
        self.assertEqual(len(self.link.sent),first+1)  # 23 ms since last: the 20 ms cadence sends
        advance(deadline-66*MS)
        self.co.tick()
        self.assertEqual(len(self.link.sent),first+1)  # 4 ms since last, 66 ms left: nothing
        # Inside the final 40 ms the heartbeat accelerates to 5 ms.
        advance(deadline-34*MS)
        self.co.tick(); sent_low=len(self.link.sent)
        self.assertEqual(sent_low,first+2)  # 36 ms since last, 34 ms left: sends
        advance(deadline-30*MS)
        self.co.tick()
        self.assertEqual(len(self.link.sent),sent_low)  # 4 ms since last: nothing
        advance(deadline-28*MS)
        self.assertEqual(len(self.link.sent),sent_low)
        self.co.tick()
        self.assertEqual(len(self.link.sent),sent_low+1)  # 6 ms since last: the 5 ms cadence sends
        # The authority cap is unchanged: packet() still bounds every lease
        # by min(LEASE_NS, the command deadline, every sensor lease) — the
        # acceleration changes only the cadence (covered by safety_core).

    def test_wait_hold_requires_native_settling_tail(self):
        # October 23 pilots: the hold must not fire while the native still
        # applies a deceleration step (-0.01 exceeds the <=0.005 settling
        # tail the wait-interval contract permits), or the measured Wait
        # interval begins pre-zero. Values inside the tail are accepted.
        self.activate()
        token=self.co.gate.session
        stamp=self.now.ros
        self.assertTrue(self.co.source(stamp,ZERO))
        self.assertTrue(self.co.checked(stamp,ZERO))
        count=len(self.link.sent)
        for applied in (0.0, 0.004, -0.004):
            self.clock.status={"session":token,"armed":True,"pending":False,
                               "applied_vx":applied,"applied_wz":0.0,
                               "physical":{"wall_ns":self.now.wall}}
            self.assertTrue(self.co.zero_wait_hold())
            self.assertEqual(len(self.link.sent),count+1)
            packet=self.link.sent[-1][2]
            self.assertEqual(tuple(packet["velocity"]),tuple(ZERO))
            count=len(self.link.sent)
        self.clock.status={"session":token,"armed":True,"pending":False,
                           "applied_vx":-.01,"applied_wz":0.0,
                           "physical":{"wall_ns":self.now.wall}}
        self.assertFalse(self.co.zero_wait_hold())
        for status in ({"session":"other","armed":True,"pending":False},
                       {"session":token,"armed":False,"pending":False},
                       {"session":token,"armed":False,"pending":True}):
            self.clock.status={**status,"applied_vx":0,"applied_wz":0,
                               "physical":{"wall_ns":self.now.wall}}
            self.assertFalse(self.co.zero_wait_hold())

    def test_wait_renewal_precedes_native_confirmation(self):
        # October 23 GPU series trial 2: the smoother's terminal decel ramp
        # reuses the terminal command's stamp, so the settling-tail command
        # keeps only ~10-20 ms of source authority. Renewal must not wait for
        # the native applied-value round trip; the confirmed hold must.
        self.activate()
        token=self.co.gate.session
        stamp=self.now.ros
        self.assertTrue(self.co.source(stamp,ZERO))
        self.assertTrue(self.co.checked(stamp,ZERO))
        count=len(self.link.sent)
        # Lagging applied value (-0.01 deceleration step): the confirmed hold
        # stays blocked, but renewal enqueues the zero lease immediately.
        self.clock.status={"session":token,"armed":True,"pending":False,
                           "applied_vx":-.01,"applied_wz":0.0,
                           "physical":{"wall_ns":self.now.wall}}
        self.assertFalse(self.co.zero_wait_hold())
        self.assertTrue(self.co.renew_wait_zero())
        self.assertEqual(len(self.link.sent),count+1)
        packet=self.link.sent[-1][2]
        self.assertEqual(tuple(packet["velocity"]),tuple(ZERO))
        events=[e["event"] for e in self.co.events]
        self.assertIn("wait_zero_renewal",events)
        self.assertNotIn("wait_zero_hold",events)
        # Once the native applied value is inside the settling tail, the
        # confirmed hold fires and remains the interval anchor.
        self.clock.status={**self.clock.status,"applied_vx":-0.002}
        self.assertTrue(self.co.zero_wait_hold())
        self.assertIn("wait_zero_hold",[e["event"] for e in self.co.events])
        # Renewal keeps every blocking precondition except applied value.
        for status in ({"session":"other","armed":True,"pending":False},
                       {"session":token,"armed":False,"pending":False},
                       {"session":token,"armed":True,"pending":True}):
            self.clock.status={**status,"applied_vx":0,"applied_wz":0,
                               "physical":{"wall_ns":self.now.wall}}
            self.assertFalse(self.co.renew_wait_zero())

    def test_wait_renewal_blocked_outside_settling_tail(self):
        # A real motion command (beyond the <=0.005 tail) must never be
        # converted to zero by the renewal path either.
        self.activate()
        stamp=self.now.ros
        self.assertTrue(self.co.source(stamp,(.1,0.,0.)))
        self.assertTrue(self.co.checked(stamp,(.1,0.,0.)))
        token=self.co.gate.session
        self.clock.status={"session":token,"armed":True,"pending":False,
                           "applied_vx":.1,"applied_wz":0.0,
                           "physical":{"wall_ns":self.now.wall}}
        self.assertFalse(self.co.renew_wait_zero())
        self.assertFalse(self.co.zero_wait_hold())
        self.assertNotIn("wait_zero_renewal",[e["event"] for e in self.co.events])

    def test_ownership_loss_before_admission(self):
        self.activate(); self.owned=False
        self.assertFalse(self.co.source(self.now.ros,(.1,0.,0.)))
        self.assertEqual(self.co.state,"stopped")

    def test_collision_stop_does_not_resume_when_clear(self):
        self.activate(); self.co.collision(1); self.co.collision(0)
        self.assertFalse(self.co.checked(self.now.ros,(.1,0.,0.)))
        self.assertEqual(self.co.state,"stopped")
        self.assertEqual(self.co.gate.reason,"collision_monitor_stop")

    def test_old_command_drained_by_session_barrier(self):
        self.activate()
        self.assertFalse(self.co.source(self.now.ros-20*MS,(.1,0.,0.)))

    def test_expired_gate_retains_native_stop_token(self):
        self.activate(); token=self.co.native_token
        self.co.gate.trip("test_fault",self.now); self.co.tick()
        self.assertEqual(self.link.sent[-1],("stop",token,"test_fault"))

    def test_missing_sensor_evidence_blocks_arm(self):
        self.co.gate.leases.pop("tf")
        self.assertFalse(self.co.request("goal"))
        self.assertEqual(self.link.sent,[])

    def test_native_ack_and_matching_session_both_required(self):
        self.assertTrue(self.co.request("goal")); token=self.co.gate.session
        self.co.tick(); self.assertEqual(self.task.starts,0)
        self.assertEqual(self.link.sent[-1][2]["velocity"],ZERO)
        self.link.replies=[{"kind":"arm","token":token,"ok":True}]
        self.co.tick(); self.assertEqual(self.task.starts,0)
        self.clock.status={"session":token,"pending":True,"armed":False}
        self.co.tick(); self.assertEqual(self.task.starts,1)
        self.co.tick(); self.assertEqual(self.task.starts,1)

    def test_late_arm_ack_after_cancel_never_dispatches_goal(self):
        self.co.request("goal"); token=self.co.gate.session
        self.co.stop("cancel")
        self.link.replies=[{"kind":"arm","token":token,"ok":True}]
        self.clock.status={"session":token,"pending":True,"armed":False}
        self.co.tick()
        self.assertEqual(self.task.starts,0); self.assertFalse(self.co.gate.armed)

    def test_negative_or_wrong_session_ack_cannot_activate(self):
        self.co.request("goal"); token=self.co.gate.session
        self.link.replies=[{"kind":"arm","token":"old","ok":True}]
        self.co.tick(); self.assertEqual(self.task.starts,0)
        self.link.replies=[{"kind":"arm","token":token,"ok":False}]
        self.co.tick(); self.assertEqual(self.co.state,"stopped")

    def test_queue_failure_revokes_without_blocking(self):
        self.link.available=False
        self.assertFalse(self.co.request("goal"))
        self.assertFalse(self.co.gate.armed); self.assertEqual(self.task.starts,0)

    def test_native_loss_stops_pending_task(self):
        self.co.request("goal"); token=self.co.gate.session
        self.link.replies=[{"kind":"arm","token":token,"ok":True}]
        self.clock.status={"session":token,"pending":True,"armed":False}
        self.co.tick()
        self.clock.status={"session":"","pending":False,"armed":False}
        self.co.tick()
        self.assertEqual(self.co.state,"stopped")
        self.assertEqual(self.task.session.state,"stopping")

    def test_unowned_active_task_revokes(self):
        self.co.request("goal"); token=self.co.gate.session
        self.link.replies=[{"kind":"arm","token":token,"ok":True}]
        self.clock.status={"session":token,"pending":True,"armed":False}
        self.co.tick(); self.owned=False; self.co.tick()
        self.assertEqual(self.co.state,"stopped")
        self.assertEqual(self.co.gate.reason,"unowned_or_unavailable_task")


    def test_terminal_zero_renewal_requires_the_unbindable_newer_source(self):
        """The terminal-deceleration hold (series-14 trial 003-on): a newer
        unbindable raw in the joiner plus the settling tail renews zero-only
        authority; faster velocities, stale stamps and boundable sources are
        rejected; the hold is bounded in total duration."""
        self.activate()
        # Cruising velocity (0.15): outside the settling tail — no renewal.
        self.assertTrue(self.co.source(self.now.ros,(.15,0.,0.)))
        self.assertTrue(self.co.checked(self.now.ros,(.15,0.,0.)))
        pending=self.co.gate.command_wall+5*MS
        self.assertFalse(self.co.renew_terminal_zero(pending, True))
        self.assertTrue(self.co.gate.armed)
        # The terminal settling tail (0.05) with a NEWER unbindable raw: held.
        self.now=Now(self.now.steady+10*MS,self.now.wall+10*MS,self.now.ros+10*MS)
        self.clock.last={"wall_ns":self.now.wall}
        self.assertTrue(self.co.source(self.now.ros,(.05,0.,0.)))
        self.assertTrue(self.co.checked(self.now.ros,(.05,0.,0.)))
        command_wall=self.co.gate.command_wall
        events=len([e for e in self.co.events
                    if e["event"]=="terminal_zero_renewal"])
        self.assertTrue(self.co.renew_terminal_zero(command_wall+5*MS, True))
        self.assertEqual(self.co.gate.velocity, ZERO)
        self.assertEqual(len([e for e in self.co.events
                              if e["event"]=="terminal_zero_renewal"]), events+1)
        # A stale pending stamp (not newer than the command wall): rejected.
        self.assertFalse(self.co.renew_terminal_zero(command_wall, True))
        # A boundable pending source is not the hold's business (the grace
        # and the ordinary drain own that case).
        self.assertFalse(self.co.renew_terminal_zero(command_wall+6*MS, False))
        # The total-duration bound: after TERMINAL_HOLD_MAX_S from the first
        # hold, no further renewal — the chain fails closed as before.
        from guarded_coordinator import TERMINAL_HOLD_MAX_S
        self.now=Now(self.co.terminal_hold_started+TERMINAL_HOLD_MAX_S+2*MS,
                     self.co.terminal_hold_started+TERMINAL_HOLD_MAX_S+2*MS+9_000*MS,
                     self.now.ros+10*MS)
        self.clock.last={"wall_ns":self.now.wall}
        for key in self.co.gate.required:
            self.co.gate.observe(key,Evidence("e",5,self.now.wall,self.now.ros),self.now)
        self.assertFalse(self.co.renew_terminal_zero(command_wall+7*MS, True))
