import unittest
from baseline_metrics import metrics


class MetricsTests(unittest.TestCase):
    def test_missing_evidence_does_not_pass(self):
        self.assertFalse(metrics([],[])["passed"])
    def test_quiet_must_persist(self):
        events=[{"event":"permission_revoked","trigger_steady_ns":100_000_000,"reason":"goal_succeeded"}]
        trace=[]
        for ms in range(90,401,10):
            trace.append({"physical":{"sequence":ms,"steady_ns":ms*1_000_000,"velocity_valid":True,
                "speed":0.,"angular_speed":0.,"x":1.,"y":0.},
                "stop_applied_steady_ns":101_000_000 if ms>100 else 0,"applied_vx":0.,"applied_wz":0.})
        self.assertFalse(metrics(trace[:10],events)["passed"])
        result=metrics(trace,events)
        self.assertTrue(result["passed"]); self.assertEqual(result["revoke_to_applied_zero_ms"],1.)

    def fault_trace(self):
        events=[{"event":"permission_revoked","trigger_steady_ns":100_000_000,
                 "reason":"command_expired","session":"trial-session"}]
        trace=[]
        for ms in range(90,401,10):
            trace.append({"steady_ns":ms*1_000_000,
                "physical":{"sequence":ms,"steady_ns":ms*1_000_000,"velocity_valid":True,
                    "speed":0.,"angular_speed":0.,"x":1.,"y":0.},
                "stop_applied_steady_ns":99_000_000 if ms>=100 else 0,
                "stop_applied_trigger_ns":98_000_000 if ms>=100 else 0,
                "session":"trial-session" if ms<100 else "","armed":ms<100,"pending":False,
                "applied_vx":.1 if ms<100 else 0.,"applied_wz":0.})
        return trace,events

    def test_native_watchdog_can_stop_before_coordinator(self):
        trace,events=self.fault_trace()
        result=metrics(trace,events,fault_injected_steady_ns=80_000_000)
        self.assertTrue(result["passed"],result)
        self.assertEqual(result["measurement_origin"],"native_watchdog")
        self.assertEqual(result["first_trigger_to_applied_zero_ms"],1.)
        self.assertEqual(result["revoke_to_applied_zero_ms"],-1.)

    def test_prior_zero_wrong_session_and_resumed_motion_are_not_accepted(self):
        for mutation in ("old_stop","wrong_session","resume"):
            trace,events=self.fault_trace()
            if mutation=="old_stop":
                for row in trace: row["stop_applied_trigger_ns"]=70_000_000
            elif mutation=="wrong_session": trace[0]["session"]="different-session"
            else: trace[-1]["applied_vx"]=.1
            with self.subTest(mutation=mutation):
                self.assertFalse(metrics(trace,events,fault_injected_steady_ns=80_000_000)["passed"])

    def test_uninjected_native_stop_requires_bound_arm_and_session(self):
        trace,events=self.fault_trace()
        self.assertFalse(metrics(trace,events)["passed"])
        events.insert(0,{"event":"arm_requested","steady_ns":80_000_000,"session":"trial-session"})
        result=metrics(trace,events)
        self.assertTrue(result["passed"],result)
        self.assertEqual(result["measurement_origin"],"native_watchdog")
        self.assertEqual(result["first_trigger_to_applied_zero_ms"],1.)
        trace[0]["session"]="other-session"
        self.assertFalse(metrics(trace,events)["passed"])

    def test_native_stop_before_current_arm_is_never_accepted(self):
        trace,events=self.fault_trace()
        events.insert(0,{"event":"arm_requested","steady_ns":99_500_000,"session":"trial-session"})
        self.assertFalse(metrics(trace,events)["passed"])
