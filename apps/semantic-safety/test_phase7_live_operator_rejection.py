import unittest
from unittest.mock import Mock, patch

from verify_phase7_live_operator_rejection import (
    expected_unchanged_response,
    expected_unapproved_response,
    require_loopback_only_listener,
)


class LiveOperatorRejectionVerifierTests(unittest.TestCase):
    def test_requires_authenticated_approved_prompt_to_be_idempotent(self):
        self.assertTrue(expected_unchanged_response(200, {
            "result": {
                "prompt": "red mat", "generation": 1,
                "stream_epoch": "epoch-a", "changed": False,
            }
        }))
        self.assertFalse(expected_unchanged_response(200, {
            "result": {
                "prompt": "red mat", "generation": 2,
                "stream_epoch": "epoch-a", "changed": False,
            }
        }))
        self.assertFalse(expected_unchanged_response(200, {
            "result": {
                "prompt": "red mat", "generation": 1,
                "stream_epoch": "epoch-a", "changed": True,
            }
        }))

    def test_requires_unapproved_prompt_rejection(self):
        self.assertTrue(expected_unapproved_response(
            400, {"error": "prompt is not approved"}))
        self.assertFalse(expected_unapproved_response(
            403, {"error": "prompt is not approved"}))
        self.assertFalse(expected_unapproved_response(
            200, {"result": {"changed": True}}))

    @patch("verify_phase7_live_operator_rejection.socket.create_connection")
    def test_live_listener_probe_requires_loopback_only_binding(self, connect):
        local = Mock()
        connect.side_effect = [local, OSError("pod interface not listening")]
        require_loopback_only_listener("10.0.0.5")
        self.assertEqual(connect.call_args_list[0].args[0], ("127.0.0.1", 9443))
        self.assertEqual(connect.call_args_list[1].args[0], ("10.0.0.5", 9443))
        local.close.assert_called_once()

        connect.reset_mock()
        connect.side_effect = [Mock(), Mock()]
        with self.assertRaisesRegex(RuntimeError, "reachable through the pod IP"):
            require_loopback_only_listener("10.0.0.5")


if __name__ == "__main__":
    unittest.main()
