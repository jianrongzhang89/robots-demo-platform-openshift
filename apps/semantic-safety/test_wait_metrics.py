import unittest
from wait_metrics import wait_zero_metrics


class WaitMetricsTests(unittest.TestCase):
    def trace(self):
        return [{"steady_ns":n*1_000_000,"applied_steady_ns":(n-1)*1_000_000,
                 "applied_vx":-.002 if n==2 else 0.,"applied_wz":0.,
                 "session":"task","armed":True,"pending":False} for n in range(2,103,5)]

    def test_bounded_initial_tail_is_separate_from_exact_native_zero(self):
        result=wait_zero_metrics(self.trace(),0,104_000_000,"task")
        self.assertTrue(result["passed"],result)
        self.assertEqual(result["normalization_to_native_zero_ms"],6.)
        self.assertEqual(result["pre_zero_samples"],1)

    def test_pre_confirmation_decel_step_precedes_the_confirmed_anchor(self):
        # With zero-authority renewal preceding native confirmation (October
        # 23 Wait-transition race fix), the deceleration step still applying
        # when the renewal fired stays outside the measured interval:
        # first_hold is the confirmed hold, never the earlier renewal.
        rows=[{"steady_ns":-3_000_000,"applied_steady_ns":-4_000_000,
               "applied_vx":-.01,"applied_wz":0.,
               "session":"task","armed":True,"pending":False}]+self.trace()
        result=wait_zero_metrics(rows,0,104_000_000,"task")
        self.assertTrue(result["passed"],result)
        self.assertEqual(result["pre_zero_samples"],1)

    def test_no_nonzero_after_first_native_zero(self):
        rows=self.trace();rows[-1]["applied_vx"]=-.002
        self.assertFalse(wait_zero_metrics(rows,0,104_000_000,"task")["passed"])

    def test_big_tail_wrong_session_or_lost_authority_fail(self):
        for key,value in (("applied_vx",-.01),("session","different"),("armed",False),("pending",True)):
            rows=self.trace();rows[0][key]=value
            with self.subTest(key=key):
                self.assertFalse(wait_zero_metrics(rows,0,104_000_000,"task")["passed"])

    def test_late_zero_missing_samples_and_coverage_fail(self):
        self.assertFalse(wait_zero_metrics([],0,104_000_000,"task")["passed"])
        rows=self.trace()
        self.assertFalse(wait_zero_metrics(rows[:5],0,104_000_000,"task")["passed"])
        self.assertFalse(wait_zero_metrics(rows[:2]+rows[15:],0,104_000_000,"task")["passed"])
        for row in rows:
            row["steady_ns"]+=110_000_000; row["applied_steady_ns"]+=110_000_000
        self.assertFalse(wait_zero_metrics(rows,0,214_000_000,"task")["passed"])


if __name__=="__main__": unittest.main()
