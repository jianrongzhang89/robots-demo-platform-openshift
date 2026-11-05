import json
from pathlib import Path
import tempfile
import unittest
from g4_prearm import retryable, retain_attempt, sam3_readiness_death

class PrearmRetryTests(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory();self.addCleanup(self.temp.cleanup)
        self.path=Path(self.temp.name)/'trial';(self.path/'runtime').mkdir(parents=True)
        (self.path/'test.log').write_text('timeout: SAM3 observation readiness before arming')
    def history(self,events):
        (self.path/'runtime/guard-events.json').write_text(json.dumps({'coordinator':events}))
    def worker(self,results,semantic):
        (self.path/'observer-status.json').write_text(
            json.dumps({'results':results,'leases':{'semantic':semantic}}))
    def test_known_setup_death_needs_empty_arming_history(self):
        self.assertFalse(retryable(self.path));self.history([]);self.assertTrue(retryable(self.path))
    def test_any_arming_attempt_forbids_retry(self):
        self.history([{'event':'arm_requested'},{'event':'permission_revoked','reason':'semantic_stale'}])
        self.assertFalse(retryable(self.path))
    def test_unknown_failure_and_corrupt_history_do_not_retry(self):
        self.history([]);(self.path/'test.log').write_text('unknown error');self.assertFalse(retryable(self.path))
        (self.path/'test.log').write_text('timeout: SAM3 observation readiness before arming')
        (self.path/'runtime/guard-events.json').write_text('{broken');self.assertFalse(retryable(self.path))
    def test_retention_preserves_logs_and_refuses_overwrite(self):
        log=self.path.parent/'trial.log';log.write_text('original')
        retained=retain_attempt(self.path,1);self.assertTrue((retained/'test.log').exists())
        self.assertEqual((self.path.parent/'trial-liveness-1.log').read_text(),'original')
        self.path.mkdir()
        with self.assertRaises(RuntimeError):retain_attempt(self.path,1)

class Sam3ReadinessDeathTests(unittest.TestCase):
    """The zenoh cold-start binding failure: zero semantic results ever
    crossed, the readiness wait that sequentially precedes all arming timed
    out, and no end-of-main evidence (guard-events) was written."""
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory();self.addCleanup(self.temp.cleanup)
        self.path=Path(self.temp.name)/'trial';(self.path/'runtime').mkdir(parents=True)
        (self.path/'test.log').write_text(
            'WaitTimeout: timeout: SAM3 observation readiness before arming')
    def test_zero_results_without_guard_events_is_retryable(self):
        (self.path/'observer-status.json').write_text(
            json.dumps({'results':0,'leases':{'semantic':None,'camera':{'sequence':5781}}}))
        self.assertTrue(sam3_readiness_death(self.path));self.assertTrue(retryable(self.path))
    def test_results_flowing_is_not_the_cold_start_signature(self):
        (self.path/'observer-status.json').write_text(
            json.dumps({'results':12,'leases':{'semantic':{'sequence':12}}}))
        self.assertFalse(sam3_readiness_death(self.path))
        self.assertFalse(retryable(self.path))  # costs-gate path needs history
    def test_completed_summary_disqualifies(self):
        (self.path/'observer-status.json').write_text(
            json.dumps({'results':0,'leases':{'semantic':None}}))
        (self.path/'runtime/summary.json').write_text('{}')
        self.assertFalse(sam3_readiness_death(self.path))
    def test_missing_worker_status_disqualifies(self):
        self.assertFalse(sam3_readiness_death(self.path))

class Nav2ChildCrashPrearmTests(unittest.TestCase):
    """A child-process crash before the arm handshake began: the pump's
    child monitor recorded the exit and the native trace shows zero
    packets (the arm datagram itself would be counted)."""
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory();self.addCleanup(self.temp.cleanup)
        self.path=Path(self.temp.name)/'trial';(self.path/'runtime').mkdir(parents=True)
        (self.path/'test.log').write_text('RuntimeError: behavior_server exited -11')
    def trace(self,packets):
        (self.path/'runtime/trace.jsonl').write_text(
            json.dumps({'received_packets':packets,'reason':'startup_disarmed'})+'\n')
    def test_crash_with_zero_packets_is_retryable(self):
        self.trace(0)
        from g4_prearm import nav2_child_crash_prearm
        self.assertTrue(nav2_child_crash_prearm(self.path));self.assertTrue(retryable(self.path))
    def test_crash_after_arming_stays_terminal(self):
        self.trace(14)
        from g4_prearm import nav2_child_crash_prearm
        self.assertFalse(nav2_child_crash_prearm(self.path));self.assertFalse(retryable(self.path))
    def test_crash_text_without_trace_is_not_retryable(self):
        from g4_prearm import nav2_child_crash_prearm
        self.assertFalse(nav2_child_crash_prearm(self.path))
    def test_clean_log_is_not_retryable(self):
        (self.path/'test.log').write_text('all good')
        self.trace(0)
        from g4_prearm import nav2_child_crash_prearm
        self.assertFalse(nav2_child_crash_prearm(self.path))

if __name__=='__main__':unittest.main()
