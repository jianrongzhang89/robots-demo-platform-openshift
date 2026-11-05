import copy
import unittest
from run_g4_faults import internal_fault_proof

class InternalFaultEvidenceTests(unittest.TestCase):
    def setUp(self):
        self.events=[{'event':'semantic_fault_injected','mode':'camera_path_loss','injected_by':'fixture','steady_ns':100,
                     'native_status':{'armed':True,'applied_vx':.15,'physical':{'velocity_valid':True,'speed':.15}}},
                     {'event':'semantic_fault_restored','mode':'camera_path_loss','steady_ns':200}]
    def test_native_event_proves_short_fault_between_cli_polls(self):
        self.assertTrue(internal_fault_proof('camera_path_loss',self.events))
    def test_missing_wrong_mode_or_stationary_injection_is_not_proof(self):
        self.assertFalse(internal_fault_proof('camera_path_loss',[]))
        self.assertFalse(internal_fault_proof('tf_loss',self.events))
        self.events[0]['native_status']['physical']['speed']=0
        self.assertFalse(internal_fault_proof('camera_path_loss',self.events))
    def test_restoration_must_follow_injection(self):
        self.events[1]['steady_ns']=99
        self.assertFalse(internal_fault_proof('camera_path_loss',self.events))

if __name__=='__main__':unittest.main()
