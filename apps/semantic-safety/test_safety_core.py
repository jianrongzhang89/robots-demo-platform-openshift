import dataclasses
import unittest

from safety_core import (COMMAND_NS, LEASE_NS, MS, TICK_NS, ZERO, Command,
                         Evidence, FinalReceiver, Now, SafetyGate)


def instant(ms=0, *, ros_ms=None, wall_ms=None):
    return Now(10_000 * MS + round(ms * MS),
               100_000 * MS + round((ms if wall_ms is None else wall_ms) * MS),
               20_000 * MS + round((ms if ros_ms is None else ros_ms) * MS))


def refresh(gate, ms, *, exclude=(), epoch="stream-1"):
    now = instant(ms)
    for key in gate.required:
        if key not in exclude:
            gate.observe(key, Evidence(epoch, int(ms) + 1, now.wall, now.ros), now)


def armed(semantics=True):
    gate = SafetyGate(require_semantics=semantics)
    refresh(gate, 0)
    session = gate.arm(instant(), stationary=True, tasks_idle=True, neutral_command=True)
    assert session
    return gate, session


def command(gate, session, ms, velocity=(0.1, 0.0, 0.0)):
    return gate.command(session, int(ms), instant(ms).wall, velocity, instant(ms))


class SafetyGateTests(unittest.TestCase):
    def test_bounded_zero_motion_setup_does_not_extend_first_real_command(self):
        gate = SafetyGate(require_semantics=False); refresh(gate,0)
        token = gate.arm(instant(),stationary=True,tasks_idle=True,neutral_command=True,
                         first_command_timeout_ns=5000*MS)
        for ms in range(100,1001,100):
            refresh(gate,ms)
            self.assertEqual(gate.packet(instant(ms)).velocity,ZERO)
        self.assertTrue(command(gate,token,1001))
        self.assertEqual(gate.tick(instant(1099)),ZERO)
        self.assertFalse(gate.armed)

    def test_setup_still_requires_fresh_inputs_and_has_fixed_end(self):
        for fresh in (True,False):
            gate = SafetyGate(require_semantics=False); refresh(gate,0)
            gate.arm(instant(),stationary=True,tasks_idle=True,neutral_command=True,
                     first_command_timeout_ns=5000*MS)
            if fresh:
                for ms in range(100,5000,100): refresh(gate,ms)
            self.assertEqual(gate.tick(instant(5000 if fresh else 500)),ZERO)
            self.assertFalse(gate.armed)

    def test_unbounded_setup_rejected(self):
        gate = SafetyGate(require_semantics=False); refresh(gate,0)
        for duration in (True,0,5001*MS):
            self.assertIsNone(gate.arm(instant(),stationary=True,tasks_idle=True,neutral_command=True,
                                      first_command_timeout_ns=duration))

    def test_startup_never_moves(self):
        gate = SafetyGate()
        self.assertEqual(gate.tick(instant()), ZERO)
        self.assertIsNone(gate.packet(instant()))
        self.assertFalse(command(gate, "unarmed", 0))

    def test_arm_requires_all_inputs_and_idle_stationary_neutral(self):
        gate = SafetyGate()
        conditions = dict(stationary=True, tasks_idle=True, neutral_command=True)
        self.assertIsNone(gate.arm(instant(), **conditions))
        refresh(gate, 0)
        for key in conditions:
            self.assertIsNone(gate.arm(instant(), **{**conditions, key: False}))
        self.assertTrue(gate.arm(instant(), **conditions))
        self.assertIsNone(gate.arm(instant(), **conditions))

    def test_normal_motion_and_bounds(self):
        gate, session = armed()
        self.assertTrue(command(gate, session, 1, (0.15, 0.0, 0.5)))
        self.assertEqual(gate.tick(instant(10)), (0.15, 0.0, 0.5))
        self.assertTrue(command(gate, session, 50, (-0.1, 0.0, -0.5)))

    def test_invalid_velocity_latches(self):
        for velocity in ((float("nan"), 0, 0), (float("inf"), 0, 0),
                         (0.151, 0, 0), (-0.101, 0, 0), (0, .001, 0), (0, 0, .501),
                         (True, 0, 0), (0, 0)):
            with self.subTest(velocity=velocity):
                gate, session = armed()
                self.assertFalse(command(gate, session, 1, velocity))
                self.assertEqual(gate.reason, "command_invalid")
                self.assertEqual(gate.tick(instant(2)), ZERO)

    def test_command_expiry_and_late_command_cannot_resume(self):
        gate, session = armed()
        command(gate, session, 1)
        self.assertEqual(gate.tick(instant(99)), ZERO)  # 2 ms uncertainty
        self.assertEqual(gate.reason, "command_expired")
        self.assertFalse(command(gate, session, 100))

    def test_command_grace_extends_once_only_while_imminent(self):
        """The admission-scheduling grace: one-shot, bounded, imminent-only."""
        from safety_core import COMMAND_GRACE_NS
        gate, session = armed()
        command(gate, session, 1)
        # The command was issued at its own capture wall, so the deadline sits
        # COMMAND_NS - UNCERTAINTY_NS after the issuing instant.
        offset = (gate.command_deadline - instant().steady) // MS
        # Far from expiry: no extension.
        self.assertFalse(gate.extend_command_deadline(instant(10), COMMAND_GRACE_NS))
        self.assertEqual(gate.command_deadline - instant().steady, offset * MS)
        # Inside the grace window (5 ms before expiry): one bounded extension.
        self.assertTrue(gate.extend_command_deadline(
            instant(offset - 5), COMMAND_GRACE_NS))
        self.assertEqual(gate.command_deadline - instant().steady,
                         (offset + COMMAND_GRACE_NS // MS) * MS)
        # One-shot: never a second extension for this source.
        self.assertFalse(gate.extend_command_deadline(
            instant(offset + COMMAND_GRACE_NS // MS - 5), COMMAND_GRACE_NS))
        # Past the ORIGINAL deadline the gate survives on the grace alone...
        refresh(gate, offset + 10)
        self.assertTrue(gate.armed, gate.reason)
        # ...and trips at deadline+grace, fail-closed, with no resume.
        self.assertEqual(gate.tick(instant(offset + COMMAND_GRACE_NS // MS + 2)), ZERO)
        self.assertEqual(gate.reason, "command_expired")
        self.assertFalse(command(gate, session, offset + COMMAND_GRACE_NS // MS + 3))

    def test_command_grace_resets_on_each_accepted_command(self):
        from safety_core import COMMAND_GRACE_NS
        gate, session = armed()
        command(gate, session, 1)
        offset = (gate.command_deadline - instant().steady) // MS
        self.assertTrue(gate.extend_command_deadline(
            instant(offset - 5), COMMAND_GRACE_NS))
        # A newer admitted command resets the one-shot allowance.
        self.assertTrue(command(gate, session, offset - 2))
        offset2 = (gate.command_deadline - instant().steady) // MS
        self.assertGreater(offset2, offset + COMMAND_GRACE_NS // MS)
        self.assertTrue(gate.extend_command_deadline(
            instant(offset2 - 5), COMMAND_GRACE_NS))
        self.assertEqual(gate.command_deadline - instant().steady,
                         (offset2 + COMMAND_GRACE_NS // MS) * MS)

    def test_same_source_copy_preserves_grace_and_remains_native_admissible(self):
        from safety_core import COMMAND_GRACE_NS
        gate, session = armed()
        command(gate, session, 1)
        original = gate.command_deadline
        self.assertTrue(gate.extend_command_deadline(instant(80), COMMAND_GRACE_NS))
        granted = gate.command_deadline
        # Reproduce run 5's 1.08445 ms ungraced remainder. Same-source
        # smoothing may alter velocity, but cannot withdraw/regrant grace.
        now = instant(97.91555)
        self.assertTrue(gate.command(session, 2, instant(1).wall, (.09,0.,0.), now))
        self.assertEqual(gate.command_deadline,granted)
        self.assertTrue(gate.command_grace_used)
        self.assertFalse(gate.extend_command_deadline(now,COMMAND_GRACE_NS))
        packet=gate.packet(now)
        self.assertAlmostEqual((packet.expires_wall-packet.issued_wall)/MS,26.08445)
        receiver=FinalReceiver()
        self.assertTrue(receiver.arm(session,now,stationary=True))
        self.assertTrue(receiver.receive(packet,now))
        self.assertEqual(gate.command_deadline,original+COMMAND_GRACE_NS)
        # No fresh source follows: the original bounded grace still expires.
        self.assertEqual(gate.tick(instant(124)),ZERO)
        self.assertEqual(gate.reason,"command_expired")
        self.assertFalse(gate.command(session,3,instant(1).wall,ZERO,instant(125)))

    def test_same_source_motion_cannot_inherit_zero_hold_deadline(self):
        from safety_core import COMMAND_GRACE_NS
        gate,session=armed()
        command(gate,session,1,ZERO)
        original=gate.command_deadline
        self.assertTrue(gate.extend_command_deadline(instant(80),COMMAND_GRACE_NS))
        self.assertTrue(gate.zero_wait_hold(session,instant(85)))
        self.assertTrue(gate.command(session,2,instant(1).wall,(.1,0.,0.),instant(90)))
        self.assertEqual(gate.command_deadline,original)
        self.assertFalse(gate.wait_hold_active)
        self.assertFalse(gate.command_grace_used)

    def test_first_command_at_arm_timestamp_does_not_inherit_setup_budget(self):
        gate=SafetyGate(require_semantics=False);refresh(gate,0)
        token=gate.arm(instant(),stationary=True,tasks_idle=True,neutral_command=True,
                       first_command_timeout_ns=5000*MS)
        self.assertTrue(gate.command(token,0,instant().wall,(.1,0.,0.),instant(1)))
        self.assertEqual(gate.command_deadline,instant(98).steady)

    def test_terminal_zero_hold_permits_the_settling_tail_only(self):
        """The terminal-deceleration hold (series-14 design): the settling
        tail (<=0.055) normalizes to zero; anything faster is rejected."""
        gate, session = armed()
        # A cruising command (0.15) is outside the tail: no hold.
        command(gate, session, 10, velocity=(0.15, 0.0, 0.0))
        self.assertFalse(gate.terminal_zero_hold(session, instant(12)))
        self.assertEqual(gate.velocity, (0.15, 0.0, 0.0))
        # The terminal ramp's settling tail (0.05) IS held to zero.
        command(gate, session, 40, velocity=(0.05, 0.0, 0.0))
        deadline = gate.command_deadline
        self.assertTrue(gate.terminal_zero_hold(
            session, instant((deadline - instant().steady) // MS - 5)))
        self.assertEqual(gate.velocity, ZERO)
        self.assertGreater(gate.command_deadline, deadline)
        # Zero-only after entry: it never commands motion, and the hold
        # still trips on the (extended) deadline, fail-closed.
        refresh(gate, 60)
        self.assertEqual(gate.tick(instant(150)), ZERO)
        # A disarmed gate never holds.
        self.assertFalse(gate.terminal_zero_hold(session, instant(200)))

    def test_zero_wait_holds_only_existing_zero_and_preserves_source_stamp(self):
        gate,session=armed(semantics=False)
        command(gate,session,1,ZERO)
        source_wall=gate.command_wall
        self.assertTrue(gate.zero_wait_hold(session,instant(20)))
        first_deadline=gate.command_deadline
        for ms in (40,60,80):
            refresh(gate,ms)
            self.assertTrue(gate.zero_wait_hold(session,instant(ms)))
            self.assertEqual(gate.packet(instant(ms)).velocity,ZERO)
        self.assertGreater(gate.command_deadline,first_deadline)
        self.assertEqual(gate.command_wall,source_wall)
        self.assertTrue(command(gate,session,90,(.1,0.,0.)))

    def test_zero_wait_hold_cannot_convert_motion_to_zero_or_revive_expired_gate(self):
        gate,session=armed(semantics=False)
        command(gate,session,1,(.1,0.,0.))
        deadline=gate.command_deadline
        self.assertFalse(gate.zero_wait_hold(session,instant(20)))
        self.assertEqual(gate.command_deadline,deadline)
        self.assertEqual(gate.velocity,(.1,0.,0.))
        self.assertEqual(gate.tick(instant(100)),ZERO)
        self.assertFalse(gate.zero_wait_hold(session,instant(101)))
        self.assertEqual(gate.reason,"command_expired")

    def test_zero_wait_hold_normalizes_only_terminal_near_zero(self):
        gate,session=armed(semantics=False)
        command(gate,session,1,(-0.004,0.,0.))
        self.assertTrue(gate.zero_wait_hold(session,instant(20)))
        self.assertEqual(gate.velocity,ZERO)
        held_deadline=gate.command_deadline
        self.assertTrue(command(gate,session,21,ZERO))
        self.assertEqual(gate.command_deadline,held_deadline)
        gate,session=armed(semantics=False)
        command(gate,session,1,(-0.006,0.,0.))
        self.assertFalse(gate.zero_wait_hold(session,instant(20)))
        self.assertEqual(gate.velocity,(-0.006,0.,0.))

    def test_zero_wait_hold_still_checks_sensor_freshness(self):
        gate,session=armed(semantics=False)
        command(gate,session,1,ZERO)
        for ms in range(20,500,20):
            refresh(gate,ms,exclude=("scan",))
            self.assertTrue(gate.zero_wait_hold(session,instant(ms)))
        self.assertFalse(gate.zero_wait_hold(session,instant(501)))
        self.assertEqual(gate.reason,"scan_stale")

    def test_delayed_callback_cannot_conceal_command_expiry(self):
        gate, session = armed()
        command(gate, session, 1)
        self.assertFalse(command(gate, session, 101))
        self.assertEqual(gate.trigger_steady, instant(99).steady)

    def test_each_missing_input_stops_by_deadline(self):
        for missing in SafetyGate().required:
            with self.subTest(missing=missing):
                gate, session = armed()
                for ms in range(1, 498, 20):
                    refresh(gate, ms, exclude=(missing,))
                    self.assertTrue(command(gate, session, ms))
                self.assertEqual(gate.tick(instant(498)), ZERO)
                self.assertEqual(gate.reason, missing + "_stale")

    def test_repeated_capture_does_not_refresh_lease(self):
        gate, session = armed()
        old = Evidence("stream-1", 1, instant().wall, instant().ros)
        for ms in range(1, 498, 20):
            refresh(gate, ms, exclude=("semantic",))
            command(gate, session, ms)
            self.assertFalse(gate.observe("semantic", old, instant(ms)))
        self.assertEqual(gate.tick(instant(498)), ZERO)
        self.assertEqual(gate.reason, "semantic_stale")

    def test_late_success_cannot_hide_input_deadline(self):
        gate, session = armed()
        for ms in range(1, 498, 20):
            refresh(gate, ms, exclude=("semantic",))
            command(gate, session, ms)
        refresh(gate, 499)  # callbacks, without an intervening timer
        self.assertFalse(gate.armed)
        self.assertEqual(gate.reason, "semantic_stale")

    def test_capture_age_not_arrival_age(self):
        gate = SafetyGate()
        now = instant(450)
        gate.observe("semantic", Evidence("e", 1, instant().wall, instant().ros), now)
        self.assertEqual(gate.leases["semantic"].deadline, instant(498).steady)

    def test_future_expired_and_malformed_inputs(self):
        for ev in (Evidence("e", 1, instant(3).wall, instant().ros),
                   Evidence("e", 1, instant(-500).wall, instant().ros),
                   Evidence("e", 1, instant().wall, instant(1).ros),
                   Evidence("", 1, instant().wall, instant().ros),
                   Evidence("e", True, instant().wall, instant().ros)):
            gate, _ = armed()
            self.assertFalse(gate.observe("semantic", ev, instant()))
            self.assertFalse(gate.armed)

    def test_paused_simulation_still_expires(self):
        gate, session = armed()
        command(gate, session, 1)
        self.assertEqual(gate.tick(instant(501, ros_ms=1)), ZERO)
        self.assertFalse(gate.armed)

    def test_clock_rollback_latches_and_clears(self):
        gate, session = armed()
        command(gate, session, 10)
        self.assertEqual(gate.tick(instant(11, ros_ms=0)), ZERO)
        self.assertEqual(gate.reason, "clock_rollback")
        self.assertFalse(gate.leases)

    def test_wall_jump_latches(self):
        for wall_ms in (-100, 100):
            gate, session = armed()
            command(gate, session, 1)
            self.assertEqual(gate.tick(instant(2, wall_ms=wall_ms)), ZERO)
            self.assertEqual(gate.reason, "wall_clock_discontinuity")

    def test_epoch_change_latches(self):
        gate, _ = armed()
        now = instant(1)
        self.assertFalse(gate.observe("semantic", Evidence("new", 2, now.wall, now.ros), now))
        self.assertEqual(gate.reason, "semantic_epoch_changed")

    def test_local_and_remote_faults_share_stop_path(self):
        for reason in ("camera_loss", "tf_loss", "stale_mask", "hung_inference",
                       "backend:timeout", "backend:overload", "backend:connection_loss",
                       "cancel", "collision_intervention", "node_restart"):
            with self.subTest(reason=reason):
                gate, session = armed()
                command(gate, session, 1)
                gate.trip(reason, instant(2))
                refresh(gate, 3)
                self.assertFalse(command(gate, session, 4))
                self.assertEqual(gate.tick(instant(4)), ZERO)
                self.assertEqual(gate.reason, reason)

    def test_rearm_requires_new_evidence_and_changes_session(self):
        gate, old = armed()
        gate.trip("cancel", instant(1))
        args = dict(stationary=True, tasks_idle=True, neutral_command=True)
        self.assertIsNone(gate.arm(instant(2), **args))
        refresh(gate, 5)
        new = gate.arm(instant(5), **args)
        self.assertTrue(new)
        self.assertNotEqual(old, new)
        self.assertFalse(command(gate, old, 6))

    def test_second_fault_during_recovery_clears_partial_inputs(self):
        gate, _ = armed()
        gate.trip("cancel", instant(1))
        refresh(gate, 5)
        gate.trip("backend:connection_loss", instant(6))
        self.assertFalse(gate.leases)
        self.assertEqual(gate.reason, "cancel")
        self.assertEqual(gate.trigger_steady, instant(1).steady)
        refresh(gate, 10, epoch="restarted")
        self.assertTrue(gate.arm(instant(10), stationary=True, tasks_idle=True, neutral_command=True))

    def test_reset_capture_barrier_includes_clock_uncertainty(self):
        gate, _ = armed()
        gate.trip("cancel", instant(1))
        almost = Evidence("stream-1", 3, instant(3).wall, instant(3).ros)
        self.assertFalse(gate.observe("semantic", almost, instant(3)))

    def test_delayed_inputs_during_recovery_do_not_chase_barrier(self):
        gate, _ = armed()
        gate.trip("cancel", instant(1))
        # Continuous 250 ms inference latency must not keep moving the reset
        # barrier forward forever as pre-fault captures finish processing.
        for ms in (100, 200):
            capture = instant(ms - 250)
            self.assertFalse(gate.observe("semantic", Evidence("stream-1", ms, capture.wall, capture.ros), instant(ms)))
            self.assertEqual(gate.barrier_wall, instant(1).wall)
        capture = instant(50)
        self.assertTrue(gate.observe("semantic", Evidence("stream-1", 300, capture.wall, capture.ros), instant(300)))
        refresh(gate, 300, exclude=("semantic",))
        self.assertTrue(gate.arm(instant(300), stationary=True, tasks_idle=True, neutral_command=True))

    def test_geometry_baseline_is_separate_startup_policy(self):
        gate, session = armed(semantics=False)
        self.assertNotIn("semantic", gate.required)
        self.assertTrue(command(gate, session, 1))
        with self.assertRaises(ValueError):
            gate.observe("semantic", Evidence("e", 1, 0, 0), instant(1))

    def test_packet_cannot_extend_command_authority(self):
        gate, session = armed()
        command(gate, session, 1)
        packet = gate.packet(instant(90))
        self.assertEqual(packet.expires_wall, instant(99).wall)


class ReceiverTests(unittest.TestCase):
    def setup_motion(self):
        gate, session = armed()
        receiver = FinalReceiver()
        self.assertTrue(receiver.arm(session, instant(), stationary=True))
        command(gate, session, 1)
        packet = gate.packet(instant(1))
        self.assertTrue(receiver.receive(packet, instant(2)))
        return gate, session, receiver, packet

    def test_startup_packet_does_not_arm(self):
        gate, session = armed()
        command(gate, session, 1)
        receiver = FinalReceiver()
        self.assertFalse(receiver.receive(gate.packet(instant(1)), instant(1)))
        self.assertEqual(receiver.tick(instant(2)), ZERO)

    def test_lost_supervisor_or_transport_expires_locally(self):
        _, _, receiver, packet = self.setup_motion()
        self.assertEqual(receiver.tick(instant(78)), (0.1, 0, 0))
        self.assertEqual(receiver.tick(instant(79)), ZERO)
        self.assertEqual(receiver.reason, "lease_expired")
        self.assertFalse(receiver.receive(packet, instant(80)))

    def test_renewals_and_explicit_revoke(self):
        gate, session, receiver, _ = self.setup_motion()
        for ms in range(20, 201, 20):
            refresh(gate, ms)
            command(gate, session, ms)
            self.assertTrue(receiver.receive(gate.packet(instant(ms)), instant(ms)))
        self.assertFalse(receiver.receive(None, instant(201)))
        self.assertEqual(receiver.tick(instant(201)), ZERO)

    def test_late_packet_never_renews_expired_receiver(self):
        gate, session, receiver, _ = self.setup_motion()
        command(gate, session, 79)
        self.assertFalse(receiver.receive(gate.packet(instant(79)), instant(79)))
        self.assertEqual(receiver.tick(instant(80)), ZERO)

    def test_replay_wrong_session_bad_velocity_and_deadline_latch(self):
        for change in ({"session": "another"}, {"sequence": 0},
                       {"velocity": (9, 0, 0)}, {"issued_wall": instant(20).wall},
                       {"expires_wall": instant(200).wall}, {"expires_wall": instant(3).wall},
                       {"sequence": True}):
            _, _, receiver, packet = self.setup_motion()
            bad = dataclasses.replace(packet, sequence=1)
            bad = dataclasses.replace(bad, **change)
            self.assertFalse(receiver.receive(bad, instant(3)))
            self.assertEqual(receiver.reason, "packet_invalid")

    def test_no_session_reuse_or_rearm_while_running(self):
        _, session, receiver, _ = self.setup_motion()
        self.assertFalse(receiver.arm(session, instant(3), stationary=True))
        receiver.stop("cancel")
        self.assertFalse(receiver.arm(session, instant(4), stationary=True))
        self.assertFalse(receiver.arm("a" * 36, instant(4), stationary=False))

    def test_clock_jump_and_restart_stop(self):
        _, _, receiver, packet = self.setup_motion()
        self.assertEqual(receiver.tick(instant(3, wall_ms=-100)), ZERO)
        self.assertEqual(receiver.reason, "clock_discontinuity")
        receiver = FinalReceiver()
        self.assertFalse(receiver.receive(packet, instant(4)))

    def test_worst_timer_phase_is_within_100ms_lease_budget(self):
        # Exhaust all integer-ms positions within one 20 ms timer period.
        for phase in range(20):
            _, _, receiver, _ = self.setup_motion()
            zero_at = None
            for ms in range(3 + phase, 121, 20):
                if receiver.tick(instant(ms)) == ZERO:
                    zero_at = ms
                    break
            self.assertIsNotNone(zero_at)
            self.assertLessEqual(zero_at - 1, 100)
        self.assertLessEqual(LEASE_NS + TICK_NS, 100 * MS)


if __name__ == "__main__":
    unittest.main(verbosity=2)
