import unittest
from g5_demo_result import endpoint_result

class EndpointTests(unittest.TestCase):
    def setUp(self):
        self.summary={'passed':True,'phase6_goal_xy':[19.4008,-31.594],
                      'phase6_mat_ground_truth':{'xmax':18.0014}}
        self.row={'armed':False,'applied_vx':0,'applied_wz':0,
                  'physical':{'x':19.4,'y':-31.6,'speed':0,'angular_speed':0}}
    def test_stationary_arrival_on_far_side_passes(self):
        self.assertTrue(endpoint_result(self.summary,[self.row])['passed'])
    def test_nav2_success_with_run17_physical_offset_fails(self):
        self.row['physical'].update(x=19.333734,y=-33.048591)
        self.assertFalse(endpoint_result(self.summary,[self.row])['passed'])
    def test_failed_navigation_cannot_pass_from_pose_alone(self):
        self.summary['passed']=False
        self.assertFalse(endpoint_result(self.summary,[self.row])['passed'])
    def test_motion_or_missing_evidence_fails(self):
        self.row['physical']['speed']=0.1
        self.assertFalse(endpoint_result(self.summary,[self.row])['passed'])
        self.assertFalse(endpoint_result(self.summary,[])['passed'])
    def test_goal_on_mat_is_not_accepted(self):
        self.summary['phase6_goal_xy']=[17.5,-31.6]
        self.row['physical']['x']=17.5
        self.assertFalse(endpoint_result(self.summary,[self.row])['passed'])

if __name__=='__main__':unittest.main()
