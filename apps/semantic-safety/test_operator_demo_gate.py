import json
from pathlib import Path
import tempfile
import unittest
from operator_demo_gate import wait_for_operator


class OperatorGateTests(unittest.TestCase):
    def test_only_matching_explicit_release_proceeds(self):
        zero = {'armed': False, 'pending': False, 'applied_vx': 0, 'applied_wz': 0}
        for supplied in [None, {'token': 'old', 'action': 'start_navigation'},
                         {'token': 'current', 'action': 'start_navigation'}]:
            with self.subTest(supplied=supplied), tempfile.TemporaryDirectory() as tmp:
                now = [0]
                def pump():
                    now[0] += 1
                    if supplied:
                        (Path(tmp)/'operator-start.json').write_text(json.dumps(supplied))
                if supplied is None:
                    with self.assertRaises(TimeoutError):
                        wait_for_operator(tmp, 'current', pump, lambda: zero, 2, lambda: now[0])
                elif supplied['token'] == 'old':
                    with self.assertRaises(RuntimeError):
                        wait_for_operator(tmp, 'current', pump, lambda: zero, 2, lambda: now[0])
                else:
                    wait_for_operator(tmp, 'current', pump, lambda: zero, 2, lambda: now[0])
                    self.assertFalse((Path(tmp)/'operator-start.json').exists())

    def test_existing_request_and_nonzero_state_fail_closed(self):
        with tempfile.TemporaryDirectory() as tmp:
            request = Path(tmp)/'operator-start.json'; request.write_text('{}')
            with self.assertRaises(RuntimeError):
                wait_for_operator(tmp, 'token', lambda: None, lambda: {})
            request.unlink()
            for state in [{}, {'armed': True}, {'armed': False, 'pending': False,
                                                'applied_vx': .1, 'applied_wz': 0}]:
                with self.assertRaises(RuntimeError):
                    wait_for_operator(tmp, 'token', lambda: None, lambda: state)
