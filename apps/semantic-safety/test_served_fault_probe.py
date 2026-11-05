import unittest
from semantic_fault_probe import SERVED_MODES, stop_reason_qualified, late_success_key, stop_wait_seconds

class ServedFaultPolicyTests(unittest.TestCase):
    def test_serving_failures_require_semantic_stop_and_recovered_result(self):
        for mode in SERVED_MODES:
            with self.subTest(mode=mode):
                self.assertTrue(stop_reason_qualified(mode,'semantic_stale'))
                self.assertFalse(stop_reason_qualified(mode,'command_expired'))
                self.assertFalse(stop_reason_qualified(mode,'goal_succeeded'))
                self.assertFalse(stop_reason_qualified(mode,'native_session_lost'))
                self.assertEqual(late_success_key(mode),'semantic')
                self.assertEqual(stop_wait_seconds(mode),45.0)

class ServedHeartbeatTests(unittest.TestCase):
    def test_uses_source_publication_and_successful_capture_not_receiver_clock(self):
        from semantic_fault_probe import served_heartbeat
        status={'backend':'http','status_wall_ns':123,'last_result':{'identity':{'epoch':'source'},'capture':{'stamp_ns':42}}}
        self.assertEqual(served_heartbeat(status,7),{'epoch':'source','sequence':7,'wall_ns':123,'ros_ns':42})
    def test_missing_or_malformed_capture_grants_no_lease(self):
        from semantic_fault_probe import served_heartbeat
        for status in ({}, {'backend':'http','status_wall_ns':123}, {'backend':'http','status_wall_ns':123,'last_result':{'identity':{'epoch':'source'},'capture':{'stamp_ns':True}}}):
            self.assertIsNone(served_heartbeat(status,1))

if __name__=='__main__':unittest.main()
