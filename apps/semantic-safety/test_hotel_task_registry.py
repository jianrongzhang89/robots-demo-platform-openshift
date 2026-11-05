import unittest
from hotel_task_registry import HotelTaskRegistry


class RegistryTests(unittest.TestCase):
    def setUp(self):
        self.r=HotelTaskRegistry(HotelTaskRegistry.ENDPOINTS)
        self.r.graph_ok=True; self.r.primed=True

    def test_unprimed_is_not_idle(self):
        self.r.primed=False; self.assertFalse(self.r.idle())

    def test_legitimate_child_uuid_differs_from_parent(self):
        self.r.observe(self.r.PARENT,[("parent",2)])
        self.r.observe("/robot_1/follow_path",[("child",2)])
        self.assertTrue(self.r.owned("parent")); self.assertFalse(self.r.idle())

    def test_other_parent_is_rejected(self):
        self.r.observe(self.r.PARENT,[("other",1)])
        self.assertFalse(self.r.owned("parent"))

    def test_recovery_not_in_baseline_tree_is_rejected(self):
        self.r.observe("/robot_1/spin",[("spin",2)])
        self.assertFalse(self.r.owned("parent"))

    def test_backup_wait_children_require_explicit_recovery_profile(self):
        self.r.observe(self.r.PARENT,[("parent",2)])
        self.r.observe("/robot_1/backup",[("backup",2)])
        self.assertFalse(self.r.owned("parent"))
        recovery=HotelTaskRegistry(HotelTaskRegistry.ENDPOINTS,allow_backup_wait=True)
        recovery.graph_ok=recovery.primed=True
        recovery.observe(recovery.PARENT,[("parent",2)])
        recovery.observe("/robot_1/backup",[("backup",2)])
        self.assertTrue(recovery.owned("parent"))
        recovery.observe("/robot_1/wait",[("wait",2)])
        self.assertFalse(recovery.owned("parent"))

    def test_recovery_graph_does_not_authorize_other_behavior_actions(self):
        recovery=HotelTaskRegistry(HotelTaskRegistry.ENDPOINTS,allow_backup_wait=True)
        service="/robot_1/spin/_action/send_goal"
        self.assertFalse(recovery.client_allowed("/robot_1",
            "bt_navigator_navigate_to_pose_rclcpp_node",service))
        self.assertTrue(recovery.client_allowed("/robot_1",
            "bt_navigator_navigate_to_pose_rclcpp_node",
            "/robot_1/backup/_action/send_goal"))

    def test_cancel_ack_or_empty_status_does_not_clear_active(self):
        self.r.observe("/robot_1/follow_path",[("child",3)])
        self.r.observe("/robot_1/follow_path",[])
        self.assertFalse(self.r.idle())
        self.r.observe("/robot_1/follow_path",[("child",5)])
        self.assertTrue(self.r.idle())

    def test_terminal_reactivation_fault_latches(self):
        self.r.observe(self.r.PARENT,[("p",5)])
        self.r.observe(self.r.PARENT,[("p",2)])
        self.assertFalse(self.r.idle()); self.assertFalse(self.r.owned("p"))

    def test_graph_loss_revokes(self):
        self.r.graph_ok=False
        self.assertFalse(self.r.idle()); self.assertFalse(self.r.owned("p"))

    def test_unknown_endpoint_is_not_silently_inventoried(self):
        with self.assertRaises(ValueError): HotelTaskRegistry(self.r.endpoints|{"/other"})

    def test_only_expected_private_clients_may_be_frozen(self):
        service="/robot_1/follow_path/_action/send_goal"
        self.assertTrue(self.r.client_allowed("/robot_1","bt_navigator_navigate_to_pose_rclcpp_node",service))
        self.assertFalse(self.r.client_allowed("/","foreign_dispatcher",service))
        self.assertFalse(self.r.client_allowed("/","phase5_task_client",service))
