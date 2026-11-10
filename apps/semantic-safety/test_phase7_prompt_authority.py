from pathlib import Path
import sys
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'semantic-perception'))
from native_clock import NativeClock
from phase7_prompt_permit import issue_prompt_permit
from safety_core import MS


def status_at(t_ms, *, speed=0.0, angular_speed=0.0, armed=False, pending=False):
    wall = (10_000 + t_ms) * MS
    physical = {'wall_ns': wall, 'steady_ns': (1_000 + t_ms) * MS,
        'sim_ns': t_ms * MS, 'sequence': t_ms // 10 + 1, 'paused': False,
        'speed': speed, 'angular_speed': angular_speed, 'velocity_valid': True,
        'x': 1.0, 'y': 2.0, 'yaw': 0.0}
    return {'clock_epoch': 'native-epoch', 'physical': physical,
        'applied_vx': 0.0, 'applied_wz': 0.0, 'armed': armed, 'pending': pending}


class Phase7NativeAuthorityTests(unittest.TestCase):
    key = b'phase7-native-authority-key-material'

    def stationary_clock(self):
        clock = NativeClock('native-epoch')
        for t in range(0, 251, 10):
            now = (10_000 + t) * MS
            self.assertTrue(clock.observe(status_at(t), now))
        return clock, 10_250 * MS

    def issue(self, clock, now, credential='operator-secret'):
        return issue_prompt_permit(prompt='blue crate', generation=2,
            stream_epoch='adapter-epoch', approved_prompts=['red mat', 'blue crate'],
            operator_credential=credential, expected_operator_credential='operator-secret',
            operator_id='phase7-operator', clock=clock, key=self.key,
            now_wall_ns=now, nonce='a' * 32)

    def test_permit_uses_native_clock_stationary_window(self):
        clock, now = self.stationary_clock()
        token = self.issue(clock, now)
        self.assertIn('"schema":"semantic-prompt-transition-permit/v1"', token)
        self.assertTrue(clock.stationary(now))

    def test_motion_arm_stale_status_and_bad_operator_cannot_issue(self):
        clock, now = self.stationary_clock()
        self.assertTrue(self.issue(clock, now, credential='operator-secret'))
        self.assertRaises(PermissionError, self.issue, clock, now, 'wrong')
        self.assertRaises(PermissionError, self.issue, clock, now + 100 * MS)

        moving = NativeClock('native-epoch')
        for t in range(0, 251, 10):
            sample = status_at(t, speed=.1 if t == 250 else 0.)
            moving.observe(sample, sample['physical']['wall_ns'])
        self.assertRaises(PermissionError, self.issue, moving, now)

        armed = NativeClock('native-epoch')
        for t in range(0, 251, 10):
            sample = status_at(t, armed=(t == 250))
            armed.observe(sample, sample['physical']['wall_ns'])
        self.assertRaises(PermissionError, self.issue, armed, now)


if __name__ == '__main__':
    unittest.main()
