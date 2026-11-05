import unittest
from contact_evidence import assess, instrument, HOTEL_SUPPORT_PAIRS, collision_inventory, support_pairs
from test_support_geometry import WORLD
from support_geometry import add_rear_casters


class ContactTests(unittest.TestCase):
    def row(self,t):
        return {"sim_ns":t*1_000_000,"wall_ns":t*1_000_000,"steps":t,"missing":0,"monitored":[1,2,3,4],
                "names":{"1":"wheel","2":"ground"},"pairs":[{"a":1,"b":2,"contact_steps":t}]}
    def check(self,rows,allowed={("ground","wheel")}):
        return assess(rows,allowed_pairs=allowed,start_sim=100_000_000,end_sim=200_000_000)
    def test_covered_support_only(self):
        self.assertTrue(self.check([self.row(t) for t in (90,150,210)])["passed"])
    def test_silence_and_unbracketed_window_fail(self):
        self.assertFalse(self.check([])["passed"])
        self.assertFalse(self.check([self.row(150)])["passed"])
    def test_contact_is_not_hidden_by_floor_substring(self):
        rows=[self.row(t) for t in (90,150,210)]
        rows[-1]["names"]["2"]="floor_obstacle"
        self.assertEqual(self.check(rows)["reason"],"unexpected_contact")
    def test_missing_component_and_rollback_fail(self):
        row=self.row(210); row["missing"]=1
        self.assertFalse(self.check([self.row(90),row])["passed"])
        self.assertFalse(self.check([self.row(90),self.row(90),self.row(210)])["passed"])
    def test_instrument_only_robot_and_reject_double_patch(self):
        result=instrument(WORLD)
        self.assertIn('libphase5_contact_audit.so',result)
        with self.assertRaises(ValueError): instrument(result)
    def test_chassis_floor_is_not_accepted_as_support(self):
        rows=[self.row(t) for t in (90,150,210)]
        for row in rows:
            row["names"]={"1":"sim_world::robot_1::base_link::base_collision",
                          "2":"sim_world::hotel_L1::floor_3::collision"}
        self.assertEqual(self.check(rows,HOTEL_SUPPORT_PAIRS)["reason"],"unexpected_contact")
        for row in rows:
            row["names"]["1"]="sim_world::robot_1::wheel_left_link::left_wheel_collision"
        self.assertTrue(self.check(rows,HOTEL_SUPPORT_PAIRS)["passed"])
    def test_wall_stall_and_malformed_evidence_fail_closed(self):
        rows=[self.row(t) for t in (90,150,210)]
        rows[-1]["wall_ns"]+=500_000_000
        self.assertEqual(self.check(rows)["reason"],"contact_coverage_gap_or_rollback")
        rows=[self.row(t) for t in (90,150,210)]
        del rows[-1]["names"]
        self.assertEqual(self.check(rows)["reason"],"malformed_contact_evidence")
    def test_caster_inventory_requires_explicit_mode_and_all_six_names(self):
        world,_=add_rear_casters(WORLD,'<robot/>')
        with self.assertRaises(ValueError): instrument(world)
        self.assertIn('<expected_collision_count>6</expected_collision_count>',instrument(world,rear_casters=True))
        rows=[self.row(t) for t in (90,150,210)]
        for row in rows:
            row['monitored']=[{'id':i,'name':name} for i,name in enumerate(sorted(collision_inventory(True)))]
            row['names']={'1':'sim_world::robot_1::rear_left_caster::support',
                          '2':'sim_world::hotel_L1::floor_3::collision'}
        kwargs=dict(allowed_pairs=support_pairs(True),expected_names=collision_inventory(True),
                    start_sim=100_000_000,end_sim=200_000_000)
        self.assertTrue(assess(rows,**kwargs)['passed'])
        rows[-1]['monitored'][-1]['name']='robot_1::unexpected::collision'
        self.assertFalse(assess(rows,**kwargs)['passed'])
