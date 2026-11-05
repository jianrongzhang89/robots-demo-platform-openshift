import copy
import unittest
from native_clock import NativeClock
from safety_core import MS


def sample(t, **changes):
    p = {"wall_ns": (10000+t)*MS, "steady_ns": (1000+t)*MS, "sim_ns":t*MS,
         "sequence":t+1,"paused":False,"speed":0.,"angular_speed":0.,"velocity_valid":True,
         "x":19.4,"y":-31.6,"yaw":0.2}
    p.update(changes)
    return {"clock_epoch":"epoch-1","physical":p,"applied_vx":0.,"applied_wz":0.,
            "armed":False,"pending":False}


class ClockTests(unittest.TestCase):
    def setUp(self): self.clock = NativeClock("epoch-1")

    def feed(self,t,**changes): return self.clock.observe(sample(t,**changes),(10000+t)*MS)

    def test_mapping_strictly_earlier_not_interpolated_or_receipt(self):
        self.feed(10); self.feed(20); self.feed(30)
        self.assertEqual(self.clock.wall_bound(20*MS,10035*MS),10010*MS)
        self.assertEqual(self.clock.wall_bound(25*MS,10035*MS),10020*MS)
        self.assertIsNone(self.clock.wall_bound(40*MS,10035*MS))

    def test_large_bracket_rejected(self):
        self.feed(10); self.feed(50)
        self.assertIsNone(self.clock.wall_bound(30*MS,10050*MS))

    def test_stationary_requires_contiguous_fresh_capture(self):
        for t in range(0,251,10): self.feed(t)
        self.assertTrue(self.clock.stationary(10251*MS))
        self.assertFalse(self.clock.stationary(10350*MS))
        self.feed(400); self.assertFalse(self.clock.stationary(10400*MS))

    def test_moving_invalidates_stationary(self):
        for t in range(0,251,10): self.feed(t)
        self.feed(260,speed=.1)
        self.assertFalse(self.clock.stationary(10260*MS))

    def test_duplicate_does_not_refresh(self):
        self.feed(10)
        self.assertFalse(self.clock.observe(sample(10),10050*MS))
        self.assertEqual(self.clock.last["wall_ns"],10010*MS)
        self.assertIsNone(self.clock.wall_bound(10*MS,10200*MS))

    def test_restart_latches_until_explicit_new_binding(self):
        self.feed(10); changed = sample(20); changed["clock_epoch"]="epoch-2"
        self.assertFalse(self.clock.observe(changed,10020*MS))
        self.assertEqual(self.clock.fault,"native_epoch_changed")
        self.assertFalse(self.feed(30))

    def test_pause_and_rollback_latch(self):
        for changed in ({"paused":True},{"sim_ns":0},{"wall_ns":10000*MS}):
            self.clock = NativeClock("epoch-1"); self.feed(10)
            self.assertFalse(self.feed(20,**changed))
            self.assertIsNotNone(self.clock.fault)

    def test_malformed_velocity_and_future_capture_rejected(self):
        self.assertFalse(self.feed(10,speed=float("nan")))
        self.clock = NativeClock("epoch-1")
        self.assertFalse(self.clock.observe(sample(30),10010*MS))

    def test_clock_jump_rejected(self):
        self.feed(10)
        self.assertFalse(self.feed(50,steady_ns=1020*MS))

    def test_velocity_rebound_over_static_pose_stays_quiet(self):
        """The series-19 trial 005-on replay: the angular-velocity norm
        decays through quiet, rebounds, and freezes at 0.185 rad/s while
        the pose stays bit-static (a resting body — contacts resting,
        displacement 0.34 mm). The quiet window survives the rebound on
        pose evidence; stationary confirms."""
        for t in range(0,60,10): self.feed(t)             # window opens, velocity quiet
        self.feed(70,angular_speed=.09,speed=.0005)       # the rebound begins, pose static
        self.feed(80,angular_speed=.18547,speed=.00186)   # the frozen artifact value
        for t in range(90,331,10): self.feed(t,angular_speed=.18547,speed=.00186)
        self.assertTrue(self.clock.stationary(10331*MS))

    def test_rebound_with_rotating_pose_resets(self):
        for t in range(0,60,10): self.feed(t)
        yaw=0.2
        for t in range(70,331,10):                         # the pose actually rotates
            yaw+=0.01
            self.feed(t,angular_speed=.18547,speed=.00186,yaw=yaw)
        self.assertFalse(self.clock.stationary(10331*MS))

    def test_rebound_with_linear_speed_resets(self):
        for t in range(0,60,10): self.feed(t)
        for t in range(70,331,10):
            self.feed(t,angular_speed=.18547,speed=.05)   # the live linear signal must stay quiet
        self.assertFalse(self.clock.stationary(10331*MS))

    def test_rebound_with_translation_resets(self):
        for t in range(0,60,10): self.feed(t)
        x=19.4
        for t in range(70,331,10):
            x+=0.0005                                      # 0.5 mm per sample: past the 1 mm bound
            self.feed(t,angular_speed=.18547,speed=.001,x=x)
        self.assertFalse(self.clock.stationary(10331*MS))

    def test_window_never_opens_without_velocity_quiet(self):
        """Fail-closed: a window opens only on the velocity criterion —
        a static pose alone cannot start one (the native arm proof keeps
        requiring the uncorroborated velocity norm)."""
        for t in range(0,331,10):
            self.feed(t,angular_speed=.18547,speed=.00186)
        self.assertFalse(self.clock.stationary(10331*MS))

    def test_armed_resets_window(self):
        for t in range(0,60,10): self.feed(t)
        changed = sample(70,angular_speed=.18547,speed=.00186)
        changed["armed"]=True
        self.assertTrue(self.clock.observe(changed,10070*MS))
        self.assertFalse(self.clock.stationary(10331*MS))

    def test_nonfinite_pose_rejected(self):
        self.assertFalse(self.feed(10,x=float("nan")))
        self.assertEqual(self.clock.fault,"native_capture_invalid")


