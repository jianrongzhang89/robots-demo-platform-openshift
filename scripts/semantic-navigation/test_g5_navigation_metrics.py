import unittest
from g5_navigation_metrics import metrics

class MetricsTests(unittest.TestCase):
    def test_stale_sources_never_show_armed_or_ready(self):
        text=metrics({'observed_wall_ns':1,'adapter':{'ready':True,'status_wall_ns':1},'fixture':{'armed':True,'written_wall_ns':1}},20_000_000_000).decode()
        self.assertIn('adapter_available 0',text)
        self.assertNotIn('adapter_ready',text)
        self.assertNotIn('navigation_armed',text)
    def test_wall_capture_and_missing_costmap_are_distinct(self):
        text=metrics({'observed_wall_ns':2_000_000_000,'adapter':{'status_wall_ns':2_000_000_000,'last_result':{'capture_wall_ns':1_000_000_000,'result_wall_ns':1_250_000_000}},'fixture':{'written_wall_ns':2_000_000_000,'armed':False,'gate_reason':'semantic_stale'}},2_000_000_000).decode()
        self.assertIn('capture_to_result_seconds 0.25',text)
        self.assertIn('costmap_available 0',text)
        self.assertNotIn('capture_to_costmap_seconds',text)
        self.assertIn('reason="semantic_stale"',text)
    def test_costmap_uses_applied_wall_time_and_rejects_future(self):
        row={'observed_wall_ns':2_000_000_000,'costmap':{'observed_wall_ns':2_000_000_000,'capture_wall_ns':1_000_000_000,'costmap_wall_ns':1_300_000_000}}
        self.assertIn('capture_to_costmap_seconds 0.3',metrics(row,2_000_000_000).decode())
        row['costmap']['costmap_wall_ns']=3_000_000_000
        self.assertNotIn('capture_to_costmap_seconds',metrics(row,2_000_000_000).decode())
    def test_future_samples_and_arbitrary_reason_do_not_leak(self):
        self.assertIn('snapshot_available 0',metrics({'observed_wall_ns':3},2).decode())
        text=metrics({'observed_wall_ns':2,'fixture':{'written_wall_ns':2,'gate_reason':'unexpected-user-string'}},2).decode()
        self.assertIn('reason="other"',text);self.assertNotIn('unexpected-user-string',text)

if __name__=='__main__':unittest.main()
