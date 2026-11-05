import unittest
from analyze_phase5_resources import delta, window


class ResourceAnalysisTests(unittest.TestCase):
    def test_missing_counters_are_not_zero(self):
        self.assertEqual(delta({"a":1,"b":4},{"a":3}),{"a":2})
        self.assertEqual(window([],10,20),{"covered":False})

    def test_brackets_and_pressure_totals_use_original_times(self):
        samples=[{"steady_ns":n*1_000_000,"end_steady_ns":(n+1)*1_000_000,
            "errors":{},"cpu.stat":{"nr_throttled":n},
            "cpu.pressure":{"some":{"avg10":0.,"total":n*100}}} for n in (0,20,40,60)]
        result=window(samples,25_000_000,55_000_000)
        self.assertTrue(result["covered"])
        self.assertEqual(result["before_margin_ms"],4.)
        self.assertEqual(result["after_margin_ms"],5.)
        self.assertEqual(result["cpu.stat"],{"nr_throttled":40})
        self.assertEqual(result["cpu.pressure"],{"some":4000})
        self.assertIsNone(result["memory.events"])
        self.assertEqual(result["maximum_sample_gap_ms"],20.)


if __name__=="__main__": unittest.main()
