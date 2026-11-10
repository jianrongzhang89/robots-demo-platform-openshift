import unittest

from phase7_operator_control import PromptTransitionControl


class StationaryClock:
    epoch = 'native-control-epoch'
    quiet_since = 9_700_000_000
    def __init__(self, now):
        self.is_stationary = True
        self.fault = None
        self.status = {'physical': {'sequence': 10, 'wall_ns': now - 10_000_000,
            'speed': 0.0, 'angular_speed': 0.0, 'paused': False},
            'applied_vx': 0.0, 'applied_wz': 0.0, 'armed': False, 'pending': False}
    def stationary(self, _now):
        return self.is_stationary


class PromptOperatorControlTests(unittest.TestCase):
    def setup_control(self, *, ready_after=2, stop_ok=True, loses_stationarity=False,
                      operator_credential='operator-token'):
        now = 10_000_000_000
        clock = StationaryClock(now)
        status = {'prompt': 'red mat', 'policy_generation': 1,
            'stream_epoch': 'adapter-epoch-1', 'prompt_transition_ready': True,
            'ready': True}
        events = []
        ticks = [0]
        def stop():
            events.append('stop')
            return stop_ok
        def apply(prompt, _permit):
            events.append('apply')
            status.update(prompt=prompt, policy_generation=2,
                stream_epoch='adapter-epoch-2', prompt_transition_ready=False,
                ready=False)
            return True
        def pump():
            ticks[0] += 1
            if loses_stationarity and ticks[0] >= 1:
                clock.is_stationary = False
            if ticks[0] >= ready_after:
                status.update(prompt_transition_ready=True, ready=True)
        control = PromptTransitionControl(clock=clock,
            approved_prompts=['red mat','blue crate'],
            operator_credential=operator_credential, operator_id='operator-17',
            signing_key=b'phase7-controller-key-material-32',
            adapter_status=lambda:status.copy(), stop_navigation=stop,
            apply_prompt=apply, pump=pump, wall_now_ns=lambda:now,
            sleep=lambda _seconds:None)
        return control, status, events, ticks

    def test_operator_stop_permit_and_fresh_generation_are_ordered(self):
        control, status, events, ticks = self.setup_control()
        result = control.transition({'action':'change_prompt','token':'operator-token',
                                     'prompt':'blue crate'})
        self.assertEqual(events, ['stop','apply'])
        self.assertGreaterEqual(ticks[0], 2)
        self.assertEqual(result, {'prompt':'blue crate','generation':2,
            'stream_epoch':'adapter-epoch-2','changed':True,'resumed':False})
        self.assertTrue(status['ready'])

    def test_bad_operator_bad_prompt_and_unconfirmed_stop_fail_before_apply(self):
        for request, expected in [
            ({'action':'change_prompt','token':'bad','prompt':'blue crate'}, PermissionError),
            ({'action':'change_prompt','token':'operator-token','prompt':'yellow cone'}, ValueError),
        ]:
            control, _status, events, _ticks = self.setup_control()
            with self.assertRaises(expected): control.transition(request)
            self.assertEqual(events, [])
        control, _status, events, _ticks = self.setup_control(stop_ok=False)
        with self.assertRaises(RuntimeError):
            control.transition({'action':'change_prompt','token':'operator-token',
                                'prompt':'blue crate'})
        self.assertEqual(events, ['stop'])

    def test_loss_of_stationarity_during_transition_never_returns_ready(self):
        control, _status, events, _ticks = self.setup_control(loses_stationarity=True)
        with self.assertRaises(RuntimeError):
            control.transition({'action':'change_prompt','token':'operator-token',
                                'prompt':'blue crate'})
        self.assertEqual(events, ['stop','apply'])

    def test_mtls_identity_selects_its_own_operator_credential(self):
        control, _status, _events, _ticks = self.setup_control(
            operator_credential={'operator-17':'operator-token'})
        request = {'action':'change_prompt','token':'operator-token',
                   'prompt':'blue crate','operator_id':'operator-17'}
        result = control.transition(request)
        self.assertEqual(result['prompt'], 'blue crate')
        request['operator_id'] = 'unmapped-operator'
        with self.assertRaises(PermissionError):
            control.transition(request)


if __name__ == '__main__':
    unittest.main()
