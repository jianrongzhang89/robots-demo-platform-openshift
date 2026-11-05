import copy
import unittest
from evaluate_g3 import evaluate

class GateTests(unittest.TestCase):
    def sample(self):
        status={'work_queue_depth':1,'input_queue_depths':{'rgb':1,'depth':0,'camera_info':0},'backend_in_flight':1,'input_queue_drops':0,'work_queue_drops':0,'work_wait_drops':0,'trace_errors':0}
        capture={'counts':{'paired':3600,'mask':3600,'cloud':3600,'invalid':0},'duration_s':600,'outputs_within_500ms_per_s':6.,'capture_age_upper_ms':{'p95':240},'identity_errors':0,'age_errors':0,'order_errors':0,'payload_binding_errors':0,'gaps_over_500ms':0,'resources':[{'container_memory_bytes':100000000,'status':status}], 'observer_pair_capture_age_upper_ms':{'p95':245},'publication_gap_ms':{},'initial_status':status,'final_status':status,'stages_ms':{}}
        m={'capture_to_costmap_ms':{'p95':280},'pending_max':1,'cells_max':300}
        return capture,{'maps':{'global_semantic':copy.deepcopy(m),'local_semantic':copy.deepcopy(m)}}
    def test_valid(self):
        self.assertEqual(evaluate(*self.sample())['status'],'PASS')
    def test_every_hard_failure_rejects(self):
        for field,value in [('duration_s',599),('outputs_within_500ms_per_s',4.9999),('identity_errors',1),('age_errors',1),('order_errors',1),('payload_binding_errors',1),('gaps_over_500ms',1)]:
            c,m=self.sample();c[field]=value
            with self.subTest(field=field):self.assertEqual(evaluate(c,m)['status'],'FAIL')
    def test_tails_pairing_and_memory(self):
        for mode in ('result','consumer','costmap','pairing','memory','queue'):
            c,m=self.sample()
            if mode=='result':c['capture_age_upper_ms']['p95']=250.01
            if mode=='consumer':c['observer_pair_capture_age_upper_ms']['p95']=250.01
            if mode=='costmap':m['maps']['local_semantic']['capture_to_costmap_ms']['p95']=300.01
            if mode=='pairing':c['counts']['paired']=3400
            if mode=='memory':c['resources'][0]['container_memory_bytes']=2*1024**3
            if mode=='queue':c['resources'][0]['status']['work_queue_depth']=2
            with self.subTest(mode=mode):self.assertEqual(evaluate(c,m)['status'],'FAIL')
    def test_missing_binding_evidence_fails_closed(self):
        c,m=self.sample();del c['payload_binding_errors'];self.assertEqual(evaluate(c,m)['status'],'FAIL')
if __name__=='__main__':unittest.main()
