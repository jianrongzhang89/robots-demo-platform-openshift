import unittest
from task_session import TaskSession


class TaskTests(unittest.TestCase):
    def test_only_accepted_current_goal_allows_command(self):
        s = TaskSession(); t = s.begin(0)
        self.assertFalse(s.may_command(t))
        self.assertEqual(s.accepted(t, True, .1), "run")
        self.assertTrue(s.may_command(t)); self.assertFalse(s.may_command("old"))

    def test_cancel_ack_does_not_clear_task(self):
        s = TaskSession(); t = s.begin(0); s.accepted(t, True, .1)
        s.revoke("camera_stale", .2); s.acknowledge_cancel(t, True)
        self.assertFalse(s.may_command(t))
        with self.assertRaises(RuntimeError): s.begin(.3)
        s.tick(3); self.assertEqual(s.timeout, "terminal_result_timeout")
        self.assertEqual(s.state, "stopping")
        s.finish(t, 5, 4); self.assertEqual(s.state, "idle")
        self.assertNotEqual(s.begin(5), t)

    def test_cancel_before_acceptance_cancels_late_handle(self):
        s = TaskSession(); t = s.begin(0); s.revoke("cancel", .1)
        self.assertEqual(s.accepted(t, True, .2), "cancel")
        self.assertFalse(s.may_command(t))

    def test_late_acceptance_does_not_hide_timeout(self):
        s = TaskSession(); t = s.begin(0)
        self.assertEqual(s.accepted(t, True, 6), "cancel")
        self.assertEqual(s.reason, "goal_accept_timeout")

    def test_late_success_preserves_fault_and_does_not_resume(self):
        s = TaskSession(); t = s.begin(0); s.accepted(t, True, .1)
        s.revoke("tf_stale", .2); s.finish(t, 4, .3)
        self.assertEqual(s.reason, "tf_stale"); self.assertFalse(s.may_command(t))
        self.assertEqual(s.outcome, "stopped")

    def test_old_callbacks_cannot_change_new_session(self):
        s = TaskSession(); old = s.begin(0); s.accepted(old, False, .1)
        new = s.begin(.2); s.accepted(new, True, .3)
        self.assertFalse(s.finish(old, 6, .4)); s.acknowledge_cancel(old, True)
        self.assertEqual(s.accepted(old, True, .5), "ignore")
        self.assertTrue(s.may_command(new)); self.assertIsNone(s.cancel_ack)

    def test_cancel_rejection_and_invalid_result_stay_blocked(self):
        s = TaskSession(); t = s.begin(0); s.accepted(t, True, .1)
        s.revoke("cancel", .2); s.acknowledge_cancel(t, False)
        self.assertFalse(s.finish(t, 2, .3)); self.assertEqual(s.state, "stopping")

    def test_success_revokes_and_requires_new_explicit_request(self):
        s = TaskSession(); t = s.begin(0); s.accepted(t, True, .1); s.finish(t, 4, .2)
        self.assertFalse(s.may_command(t)); self.assertTrue(s.revoked)
        self.assertEqual(s.reason, "goal_succeeded")

    def test_duplicate_request_denied(self):
        s = TaskSession(); s.begin(0)
        with self.assertRaises(RuntimeError): s.begin(.1)

