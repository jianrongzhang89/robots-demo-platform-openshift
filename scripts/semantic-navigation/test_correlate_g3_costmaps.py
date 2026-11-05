import copy
import unittest
from correlate_g3_costmaps import correlate

class CorrelationTests(unittest.TestCase):
    def fixture(self):
        capture={'results':[{'identity':{'request_id':'r','robot':'robot_1','stream':'camera/color'},'capture_wall_ns':100,'capture':{'stamp_ns':10}}]}
        last={'request_id':'r','stamp_ns':10,'capture_wall_ns':100,'costmap_wall_ns':120}
        return capture,[{'maps':{n:{'last':copy.deepcopy(last)} for n in ('global_semantic','local_semantic')}}]
    def test_exact(self):self.assertEqual(correlate(*self.fixture())['status'],'PASS')
    def test_wrong_capture_and_unknown_identity_rejected(self):
        for key,value in [('stamp_ns',11),('capture_wall_ns',101),('request_id','unknown')]:
            c,u=self.fixture();u[0]['maps']['local_semantic']['last'][key]=value
            with self.subTest(key=key):self.assertEqual(correlate(c,u)['status'],'FAIL')
    def test_wrong_stream_rejected(self):
        c,u=self.fixture();c['results'][0]['identity']['stream']='wrong';self.assertEqual(correlate(c,u)['status'],'FAIL')
if __name__=='__main__':unittest.main()
