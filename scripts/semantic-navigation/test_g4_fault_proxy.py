import json
import unittest
from g4_fault_proxy import response_fault

class FaultResponseTests(unittest.TestCase):
    def test_healthy_preserves_model_bytes(self):
        data=b'{"deployment":{"versions":{"model":"pinned"}},"mask":[1]}'
        self.assertEqual(response_fault('healthy',200,data),(200,data))
    def test_failures_are_explicit_and_do_not_include_predictions(self):
        for mode,expected in [('serving',503)]:
            code,body=response_fault(mode,200,b'{"prediction":"discard"}')
            self.assertEqual(code,expected);self.assertEqual(set(json.loads(body)),{'error'})
    def test_wrong_identity_preserves_result_for_real_adapter_identity_check(self):
        data={'deployment':{'versions':{'model':'pinned'}},'mask':[1],'identity':{'request_id':'bound'}}
        code,body=response_fault('wrong_version',200,json.dumps(data).encode())
        changed=json.loads(body)
        self.assertEqual(changed['mask'],data['mask']);self.assertEqual(changed['identity'],data['identity'])
        self.assertNotEqual(changed['deployment']['versions']['model'],'pinned')

if __name__=='__main__':unittest.main()
