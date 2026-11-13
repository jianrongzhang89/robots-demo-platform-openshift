"""Verify the payload gate never releases during travel or before landing."""
import sys
import unittest
from pathlib import Path
from types import SimpleNamespace
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from phase8_lift_payload import LiftPayload


class PayloadGateTests(unittest.TestCase):
    def setUp(self):
        self.payload=LiftPayload.__new__(LiftPayload)
        self.payload.state='detached'
        self.payload.wanted=False
        self.payload.destination=None
        self.payload._motion_stopped=0
        self.payload._door_open=2

    def state(self, floor='L3', motion=0, door=2):
        return SimpleNamespace(lift_name='Lift2',current_floor=floor,
                               motion_state=motion,door_state=door)

    def test_travel_requires_attachment_acknowledgment(self):
        self.assertFalse(self.payload.prepare())
        self.assertTrue(self.payload.wanted)
        with self.assertRaisesRegex(RuntimeError,'before payload attachment'):
            self.payload.begin_trip('L3')
        self.payload.state='attached'
        self.assertTrue(self.payload.prepare())
        self.payload.begin_trip('L3')
        self.assertEqual(self.payload.destination,'L3')

    def test_nearest_floor_and_opening_do_not_release(self):
        self.payload.state='attached';self.payload.prepare();self.payload.begin_trip('L3')
        for state in [self.state('L2'),self.state(motion=1),self.state(door=1)]:
            self.payload.observe_lift(state)
            self.assertTrue(self.payload.wanted)
            self.assertEqual(self.payload.destination,'L3')

    def test_arrival_requests_release_but_still_requires_transport_ack(self):
        self.payload.state='attached';self.payload.prepare();self.payload.begin_trip('L3')
        self.payload.observe_lift(self.state())
        self.assertFalse(self.payload.wanted)
        self.assertIsNone(self.payload.destination)
        self.assertEqual(self.payload.state,'attached')


if __name__=='__main__':unittest.main()
