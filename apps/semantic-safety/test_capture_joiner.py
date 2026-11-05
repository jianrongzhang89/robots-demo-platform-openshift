import unittest
from capture_joiner import CaptureJoiner
from command_ledger import CommandLedger
from safety_core import MS,Now


class JoinerTests(unittest.TestCase):
    def setUp(self):
        self.ledger=CommandLedger(); self.ledger.reset("one",0)
        self.bound=100*MS
        self.join=CaptureJoiner(self.ledger,lambda stamp,now:self.bound)
    def row(self,kind):
        return {"kind":kind,"stamp":100*MS,"velocity":[.1,0.,0.]}
    def now(self,ms): return Now(ms*MS,ms*MS,ms*MS)
    def test_checked_before_source_is_joined(self):
        checked,raw=self.row("checked"),self.row("raw")
        self.join.receive(checked,self.now(101)); self.join.drain(self.now(101))
        self.assertFalse(checked["admitted"])
        self.join.receive(raw,self.now(105)); self.join.drain(self.now(105))
        self.assertTrue(raw["admitted"]); self.assertTrue(checked["admitted"])
    def test_waits_for_native_upper_bracket(self):
        raw=self.row("raw"); self.bound=None
        self.join.receive(raw,self.now(101)); self.join.drain(self.now(105))
        self.assertFalse(raw["admitted"])
        self.bound=100*MS; self.join.drain(self.now(110))
        self.assertTrue(raw["admitted"])
        self.assertEqual(raw["bound"],100*MS)
    def test_wait_bound_cannot_be_extended(self):
        raw=self.row("raw"); self.bound=None
        self.join.receive(raw,self.now(101)); self.join.drain(self.now(115))
        self.bound=100*MS; self.join.drain(self.now(122))
        self.assertFalse(raw["admitted"]); self.assertEqual(raw["join_reason"],"join_wait_expired")
    def test_pending_cannot_renew_expired_source(self):
        raw=self.row("raw")
        self.join.receive(raw,self.now(190)); self.join.drain(self.now(201))
        self.assertFalse(raw["admitted"])
    def test_capacity_and_session_barriers(self):
        self.join.capacity=1
        old,new=self.row("raw"),self.row("checked")
        self.join.receive(old,self.now(101)); self.join.receive(new,self.now(102))
        self.assertEqual(old["join_reason"],"capacity_exceeded")
        self.ledger.reset("two",0); self.join.drain(self.now(103))
        self.assertFalse(new["admitted"]); self.assertEqual(new["join_reason"],"session_changed")

    def test_runtime_delivery_is_once_and_raw_precedes_checked(self):
        checked,raw=self.row("checked"),self.row("raw")
        self.join.receive(checked,self.now(101)); self.join.receive(raw,self.now(101))
        self.assertEqual(self.join.drain(self.now(102)),[raw,checked])
        self.assertEqual(self.join.drain(self.now(103)),[])

    def test_reset_does_not_deliver_pending_runtime_command(self):
        self.join.receive(self.row("checked"),self.now(101))
        self.ledger.reset("new",102*MS)
        self.assertEqual(self.join.drain(self.now(103)),[])
