import unittest
from command_ledger import CommandLedger
from safety_core import MS, Now


def at(n):
    return Now((1000+n)*MS, (10000+n)*MS, (2000+n)*MS)


class LedgerTests(unittest.TestCase):
    def setUp(self):
        self.ledger = CommandLedger(); self.ledger.reset("new", at(0).ros)

    def record(self, n=1):
        return self.ledger.record("new", at(n).ros, at(n).wall, (.1, 0, 0), at(n))

    def test_stamp_and_session_required(self):
        self.assertTrue(self.record())
        self.assertIsNone(self.ledger.resolve("old", at(1).ros, (.1,0,0), at(2)))
        self.assertIsNone(self.ledger.resolve("new", at(2).ros, (.1,0,0), at(2)))

    def test_smoothing_does_not_renew_deadline(self):
        self.record()
        for n in range(2,99):
            source = self.ledger.resolve("new", at(1).ros, (.05,0,0), at(n))
            self.assertIsNotNone(source); self.assertEqual(source.deadline, at(99).steady)
        self.assertIsNone(self.ledger.resolve("new", at(1).ros, (.05,0,0), at(99)))

    def test_duplicate_cannot_change_wall_capture(self):
        self.record()
        self.assertFalse(self.ledger.record("new", at(1).ros, at(50).wall, (.1,0,0), at(50)))
        self.assertEqual(self.ledger.entries[at(1).ros].wall_stamp, at(1).wall)

    def test_old_capture_and_pre_rearm_commands_rejected(self):
        self.record(); self.ledger.reset("next", at(20).ros)
        self.assertIsNone(self.ledger.resolve("new", at(1).ros, (.1,0,0), at(21)))
        self.assertFalse(self.ledger.record("next", at(1).ros, at(1).wall, (.1,0,0), at(21)))

    def test_wall_capture_cannot_be_hidden_by_slow_simulation(self):
        self.record()
        self.assertIsNone(self.ledger.resolve("new", at(1).ros, (.1,0,0), Now(at(120).steady,at(120).wall,at(2).ros)))

    def test_delayed_raw_and_invalid_velocity_rejected(self):
        self.assertFalse(self.ledger.record("new",at(1).ros,at(1).wall,(.1,0,0),at(120)))
        self.record()
        self.assertIsNone(self.ledger.resolve("new",at(1).ros,(.16,0,0),at(2)))

    def test_raw_source_accepts_pre_monitor_rotation_magnitude(self):
        """The provenance path records the pre-monitor raw; the applied bound
        stays at resolve(). The goal-approach rotation commands reach ~0.65
        rad/s while the collision monitor limits the applied value well inside
        the envelope — the ledger must not leave the monitor's valid limited
        outputs sourceless (pair-1-on-lethal254-grace2)."""
        # The raw (source) records at a magnitude the monitor will limit...
        self.assertTrue(self.ledger.record("new",at(1).ros,at(1).wall,(.05,0,-.65),at(1)))
        # ...and the monitor's limited output resolves against it.
        self.assertIsNotNone(self.ledger.resolve("new",at(1).ros,(.05,0,-.08),at(2)))
        # The APPLIED magnitude bound is unchanged: a checked output at the
        # raw's excessive magnitude still fails closed at resolve().
        self.assertTrue(self.ledger.record("new",at(3).ros,at(3).wall,(.05,0,-.6),at(3)))
        self.assertIsNone(self.ledger.resolve("new",at(3).ros,(.05,0,-.6),at(4)))
        # Structurally invalid sources are still rejected.
        self.assertFalse(self.ledger.record("new",at(5).ros,at(5).wall,(.1,0,float("nan")),at(5)))
        self.assertFalse(self.ledger.record("new",at(6).ros,at(6).wall,(.1,0),at(6)))

