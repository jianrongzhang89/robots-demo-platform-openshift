import copy
import unittest
from command_audit import EXPECTED, validate_graph, validate_observations, validate_publisher_binding


def graph():
    result={}
    index=0
    for topic,counts in EXPECTED.items():
        result[topic]=[]
        for node,count in counts.items():
            for _ in range(count):
                index+=1
                result[topic].append({"node":node,"namespace":"/robot_1",
                    "type":"geometry_msgs/msg/TwistStamped","gid":[index]+[0]*15})
    return result


class AuditTests(unittest.TestCase):
    def setUp(self):
        self.graph=graph()
        self.row={"kind":"raw","publisher_gid":self.graph["cmd_vel_nav"][0]["gid"],
                  "frame":"base_footprint","unused_axes":[0,0,0],"bound":100,"source_timestamp":101}

    def test_real_profile_shape(self):
        validate_graph(self.graph)
        validate_observations(self.graph,[self.row])

    def test_publisher_binding_is_separate_from_command_semantics(self):
        validate_publisher_binding(self.graph,[{**self.row,"frame":""}])
        with self.assertRaises(ValueError):
            validate_publisher_binding(self.graph,[{**self.row,"publisher_gid":[99]*16}])

    def test_duplicate_named_publisher_not_hidden_by_set(self):
        self.graph["cmd_vel_nav"].append(copy.deepcopy(self.graph["cmd_vel_nav"][0]))
        with self.assertRaises(ValueError): validate_graph(self.graph)

    def test_unexpected_writer_rejected(self):
        self.graph["cmd_vel_nav"].append({"node":"unexpected_writer","namespace":"/robot_1",
            "type":"geometry_msgs/msg/TwistStamped","gid":[99]+[0]*15})
        with self.assertRaises(ValueError): validate_graph(self.graph)

    def test_restarted_writer_requires_new_discovered_identity(self):
        old_gid=self.graph["cmd_vel_nav"][0]["gid"]
        new_gid=[99]+[0]*15
        self.graph["cmd_vel_nav"][0]["gid"]=new_gid
        with self.assertRaises(ValueError):
            validate_publisher_binding(self.graph,[{**self.row,"publisher_gid":old_gid}])
        validate_publisher_binding(self.graph,[{**self.row,"publisher_gid":new_gid}])

    def test_reused_gid(self):
        self.graph["cmd_vel_nav"][1]["gid"]=self.graph["cmd_vel_nav"][0]["gid"]
        with self.assertRaises(ValueError): validate_graph(self.graph)

    def test_wrong_topic_source_or_frame(self):
        for key,value in (("kind","checked"),("frame",""),("unused_axes",[1,0,0]),
                          ("publisher_gid",[99]*16)):
            with self.subTest(key=key):
                row={**self.row,key:value}
                with self.assertRaises(ValueError): validate_observations(self.graph,[row])

    def test_future_capture_bound_and_missing_source_time(self):
        for value in (0,99):
            with self.assertRaises(ValueError):
                validate_observations(self.graph,[{**self.row,"source_timestamp":value}])

    def test_no_receipt_time_substitution_required_for_unmapped_evidence(self):
        validate_observations(self.graph,[{**self.row,"bound":None}])

    def test_missing_evidence_rejected(self):
        with self.assertRaises(ValueError): validate_observations(self.graph,[])
