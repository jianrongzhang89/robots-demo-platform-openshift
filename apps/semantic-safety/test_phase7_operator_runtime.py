import json
import os
from pathlib import Path
import tempfile
import threading
import time
import unittest
from types import SimpleNamespace
from unittest.mock import patch

from phase7_operator_runtime import (
    NativeClockFeed, runtime_config, serve_until_stopped,
    startup_gate_diagnostics,
)


def native_status(sequence, wall_ns, steady_ns, sim_ns):
    return {
        'schema':'phase5-drive-status/v1', 'clock_epoch':'phase7-test-epoch',
        'sequence':sequence, 'armed':False, 'pending':False,
        'applied_vx':0.0, 'applied_wz':0.0,
        'physical':{'sequence':sequence,'wall_ns':wall_ns,'steady_ns':steady_ns,
            'sim_ns':sim_ns,'x':0.0,'y':0.0,'yaw':0.0,'paused':False,
            'velocity_valid':True,'speed':0.0,'angular_speed':0.0},
    }


class Phase7OperatorRuntimeTests(unittest.TestCase):
    def test_startup_gate_diagnostics_identify_missing_prerequisites_without_secrets(self):
        bindings = SimpleNamespace(
            clock=SimpleNamespace(epoch=None, fault="native_status_unavailable"),
            cancel_proxy_client=SimpleNamespace(service_is_ready=lambda: True),
            parameter_client=SimpleNamespace(service_is_ready=lambda: False),
        )
        status = {
            "ready": True,
            "prompt_transition_enabled": False,
            "approved_prompts": ["red mat"],
            "operator_credential": "must-not-be-copied",
        }

        result = startup_gate_diagnostics(bindings, status)

        self.assertEqual(result, {
            "adapter_status_received": True,
            "adapter_ready": True,
            "prompt_transition_enabled": False,
            "approved_prompt_count": 1,
            "native_status_ready": False,
            "native_status_fault": "native_status_unavailable",
            "nav_cancel_proxy_ready": True,
            "adapter_parameter_service_ready": False,
        })
        self.assertNotIn("must-not-be-copied", json.dumps(result))

    def test_operator_http_server_stops_from_runtime_signal_event(self):
        stopped = threading.Event()
        started = threading.Event()
        closed = threading.Event()

        class Server:
            def serve_forever(self, poll_interval):
                self.poll_interval = poll_interval
                started.set()
                stopped.wait()

            def shutdown(self):
                stopped.set()

            def server_close(self):
                closed.set()

        stop_event = threading.Event()
        thread = threading.Thread(
            target=serve_until_stopped, args=(Server(), stop_event), daemon=True)
        thread.start()
        self.assertTrue(started.wait(1.0))
        stop_event.set()
        thread.join(timeout=2.0)
        self.assertFalse(thread.is_alive())
        self.assertTrue(closed.is_set())

    def test_native_status_feed_requires_fresh_capture_and_stationary_window(self):
        feed = NativeClockFeed()
        first = time.time_ns()
        self.assertTrue(feed.observe_json(json.dumps(
            native_status(1,first,1_000_000_000,1_000_000_000)), first))
        for sequence in range(2, 8):
            second = first + (sequence-1)*50_000_000
            self.assertTrue(feed.observe_json(json.dumps(native_status(
                sequence,second,1_000_000_000+(sequence-1)*50_000_000,
                1_000_000_000+(sequence-1)*50_000_000)), second))
        self.assertTrue(feed.stationary(second))
        self.assertEqual(feed.epoch, 'phase7-test-epoch')

    def test_bad_or_stale_native_status_never_becomes_ready(self):
        feed = NativeClockFeed()
        now = time.time_ns()
        self.assertFalse(feed.observe_json('{bad', now))
        self.assertFalse(feed.stationary(now))
        self.assertFalse(feed.observe_json(json.dumps(
            native_status(1,now-200_000_000,1_000_000_000,1_000_000_000)),now))

    def test_pre_physics_status_does_not_poison_later_native_capture(self):
        feed = NativeClockFeed()
        now = time.time_ns()
        startup = {'clock_epoch':'phase7-test-epoch','physical':None}
        self.assertFalse(feed.observe_json(json.dumps(startup), now))
        self.assertIsNone(feed.epoch)
        self.assertTrue(feed.observe_json(json.dumps(
            native_status(1,now,1_000_000_000,1_000_000_000)),now))
        self.assertIsNone(feed.fault)

    def test_monotonic_stale_capture_does_not_poison_later_fresh_samples(self):
        feed = NativeClockFeed()
        first = time.time_ns()
        self.assertTrue(feed.observe_json(json.dumps(
            native_status(1, first, 1_000_000_000, 1_000_000_000)), first))
        late_receive = first + 200_000_000
        stale = native_status(2, first + 50_000_000, 1_050_000_000, 1_050_000_000)
        self.assertFalse(feed.observe_json(json.dumps(stale), late_receive))
        self.assertIsNone(feed.fault)
        for sequence in range(3, 11):
            capture = first + sequence*50_000_000
            self.assertTrue(feed.observe_json(json.dumps(native_status(
                sequence, capture, 1_000_000_000+sequence*50_000_000,
                1_000_000_000+sequence*50_000_000)), capture))
        self.assertTrue(feed.stationary(capture))

    def test_runtime_requires_isolated_partition_and_managed_credentials(self):
        with self.assertRaises(RuntimeError):
            runtime_config({'PHASE7_RUNTIME_ENABLE':'1','GZ_PARTITION':'semantic_navigation_phase6_demo',
                            'GZ_IP':'127.0.0.1'})
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            (root/'signing.key').write_bytes(b'x'*32)
            (root/'operators.json').write_text(json.dumps({'operator-17':'credential'}))
            for name in ('server.crt','server.key','client-ca.crt'):
                (root/name).write_text('fixture')
            config = {
                'PHASE7_RUNTIME_ENABLE':'1', 'GZ_PARTITION':'phase5-watchdog-phase7-isolated-test',
                'GZ_IP':'127.0.0.1','PHASE7_SIGNING_KEY_FILE':str(root/'signing.key'),
                'PHASE7_OPERATOR_MAP_FILE':str(root/'operators.json'),
                'PHASE7_SERVER_CERT_FILE':str(root/'server.crt'),
                'PHASE7_SERVER_KEY_FILE':str(root/'server.key'),
                'PHASE7_CLIENT_CA_FILE':str(root/'client-ca.crt'),
                'PHASE7_ADAPTER_NODE':'/sam3_inference',
                'PHASE7_ADAPTER_STATUS_TOPIC':'/robot_1/semantic/status',
                'PHASE7_NAV_ACTIONS':'/navigate_to_pose,/navigate_through_poses',
                'PHASE7_NAV_CANCEL_PROXY':'/phase7/cancel_navigation',
            }
            result = runtime_config(config)
            self.assertEqual(result['nav_actions'],
                ('/navigate_to_pose','/navigate_through_poses'))
            self.assertEqual(result['operators'], {'operator-17':'credential'})
            self.assertEqual(result['host'], '127.0.0.1')
            config['PHASE7_OPERATOR_HOST'] = '0.0.0.0'
            external = runtime_config(config)
            self.assertEqual(external['host'], '0.0.0.0')


if __name__ == '__main__':
    unittest.main()
