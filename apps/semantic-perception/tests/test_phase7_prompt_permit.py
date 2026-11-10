import json
from pathlib import Path
import sys
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / 'semantic-safety'))
from phase7_prompt_permit import PromptPermitVerifier, issue_prompt_permit


class QuietClock:
    epoch = 'native-epoch-1'
    def __init__(self, now, **changes):
        self.quiet_since = now - 300_000_000
        self.is_stationary = True
        self.status = {
            'physical': {'sequence': 9, 'wall_ns': now - 10_000_000,
                         'speed': 0.0, 'angular_speed': 0.0, 'paused': False},
            'applied_vx': 0.0, 'applied_wz': 0.0,
            'armed': False, 'pending': False,
        }
        self.status.update(changes)
    def stationary(self, _now):
        return self.is_stationary


class PromptPermitTests(unittest.TestCase):
    key = b'phase7-permit-test-signing-key-32-bytes'

    def issue(self, now, clock=None, **kwargs):
        return issue_prompt_permit(
            prompt=kwargs.get('prompt', 'blue crate'),
            generation=kwargs.get('generation', 2),
            stream_epoch=kwargs.get('stream_epoch', 'adapter-epoch-1'),
            approved_prompts=kwargs.get('approved_prompts', ['red mat', 'blue crate']),
            operator_credential=kwargs.get('credential', 'authorized'),
            expected_operator_credential='authorized',
            operator_id='operator-17', clock=clock or QuietClock(now), key=self.key,
            now_wall_ns=now, nonce=kwargs.get('nonce', '1' * 32))

    def test_permit_binds_prompt_generation_and_is_single_use(self):
        now = 10_000_000_000
        token = self.issue(now)
        verifier = PromptPermitVerifier(self.key, wall_now_ns=lambda: now)
        payload = verifier.verify_and_consume(token, prompt='blue crate', generation=2,
                                              stream_epoch='adapter-epoch-1')
        self.assertEqual(payload['motion']['native_epoch'], 'native-epoch-1')
        with self.assertRaises(PermissionError):
            verifier.verify_and_consume(token, prompt='blue crate', generation=2,
                                        stream_epoch='adapter-epoch-1')
        with self.assertRaises(PermissionError):
            PromptPermitVerifier(self.key, wall_now_ns=lambda: now).verify_and_consume(
                token, prompt='red mat', generation=2, stream_epoch='adapter-epoch-1')
        with self.assertRaises(PermissionError):
            PromptPermitVerifier(self.key, wall_now_ns=lambda: now).verify_and_consume(
                token, prompt='blue crate', generation=3, stream_epoch='adapter-epoch-1')
        with self.assertRaises(PermissionError):
            PromptPermitVerifier(self.key, wall_now_ns=lambda: now).verify_and_consume(
                token, prompt='blue crate', generation=2, stream_epoch='adapter-after-restart')

    def test_operator_and_native_stationarity_are_required_to_issue(self):
        now = 10_000_000_000
        with self.assertRaises(PermissionError):
            self.issue(now, credential='wrong')
        moving = QuietClock(now)
        moving.is_stationary = False
        with self.assertRaises(PermissionError):
            self.issue(now, clock=moving)
        armed = QuietClock(now, armed=True)
        with self.assertRaises(PermissionError):
            self.issue(now, clock=armed)
        stale = QuietClock(now)
        stale.status['physical']['wall_ns'] = now - 101_000_000
        with self.assertRaises(PermissionError):
            self.issue(now, clock=stale)

    def test_signature_tampering_expiry_and_prompt_allowlist_fail_closed(self):
        now = 10_000_000_000
        token = self.issue(now)
        envelope = json.loads(token)
        envelope['payload']['operator_id'] = 'forged'
        forged = json.dumps(envelope)
        with self.assertRaises(PermissionError):
            PromptPermitVerifier(self.key, wall_now_ns=lambda: now).verify_and_consume(
                forged, prompt='blue crate', generation=2, stream_epoch='adapter-epoch-1')
        with self.assertRaises(PermissionError):
            PromptPermitVerifier(self.key, wall_now_ns=lambda: now + 5_000_000_001).verify_and_consume(
                token, prompt='blue crate', generation=2, stream_epoch='adapter-epoch-1')
        with self.assertRaises(ValueError):
            self.issue(now, prompt='yellow cone')


if __name__ == '__main__':
    unittest.main()
