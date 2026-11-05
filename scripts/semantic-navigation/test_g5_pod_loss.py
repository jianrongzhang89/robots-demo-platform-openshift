import unittest
from evaluate_g5_pod_loss import evaluate

class AttributionTests(unittest.TestCase):
    def proof(self,at):
        result={'fixture_passed':True,'cleanup_ok':True,'events':[{'event':'delete_serving_pod','uid':'old','fixture_delete_lower_ns':at-1,'fixture_delete_upper_ns':at}]}
        events=[{'event':'semantic_fault_injected','wall_ns':100,'steady_ns':1000,'native_status':{'armed':True,'applied_vx':.15,'physical':{'velocity_valid':True,'speed':.15}}},{'event':'guard_stopped_after_semantic_fault','steady_ns':1200}]
        return evaluate(result,events,{'metadata':{'uid':'new'},'status':{'containerStatuses':[{'name':'kserve-container','imageID':'model@sha256:pin'}]}},'sha256:pin')
    def test_actual_deletion_precedes_stop(self):self.assertTrue(self.proof(150)['passed'])
    def test_preexisting_stop_never_counts_as_injected_fault(self):self.assertFalse(self.proof(350)['passed'])

if __name__=='__main__':unittest.main()
