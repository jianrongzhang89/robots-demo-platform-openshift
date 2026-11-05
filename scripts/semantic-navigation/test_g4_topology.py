import copy
import unittest
from g4_topology import initialized

class InitializationTests(unittest.TestCase):
    def setUp(self):
        self.pod={'metadata':{'labels':{'semantic-qualification':'g4'}},'status':{'phase':'Running','containerStatuses':[{'name':'sam3-zenoh-bridge','ready':True},{'name':'sam3-inference','ready':False,'state':{'running':{}}}]}}
        self.identity={'pinned':'identity'}
        self.envelope={'observed_wall_ns':3_000_000_000,'status':{'status_wall_ns':2_000_000_000,'backend':'http','deployment_identity':self.identity,'ready':False}}
    def test_idle_initialization_does_not_require_or_grant_ros_readiness(self):
        self.assertTrue(initialized(self.pod,self.envelope,self.identity))
        self.assertFalse(self.envelope['status']['ready'])
    def test_stale_and_future_status_rejected_on_same_clock(self):
        for now in (1_000_000_000,4_000_000_000):
            e=copy.deepcopy(self.envelope);e['observed_wall_ns']=now
            self.assertFalse(initialized(self.pod,e,self.identity))
    def test_wrong_identity_or_dead_process_rejected(self):
        self.assertFalse(initialized(self.pod,self.envelope,{'other':'identity'}))
        self.pod['status']['containerStatuses'][1]['state']={'terminated':{}}
        self.assertFalse(initialized(self.pod,self.envelope,self.identity))

if __name__=='__main__':unittest.main()
