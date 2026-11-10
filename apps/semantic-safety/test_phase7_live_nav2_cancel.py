import copy
import unittest

from verify_phase7_live_nav2_cancel import live_sam3_status_qualified


class LiveNav2CancelVerifierStatusTests(unittest.TestCase):
    def setUp(self):
        self.status = {
            "ready": True,
            "backend": "http",
            "prompt": "red mat",
            "approved_prompts": ["red mat"],
            "prompt_transition_enabled": False,
            "policy_generation": 1,
            "emitted_results": 3,
            "paired_triplets": 4,
            "last_valid_result_age_ms": 120.0,
            "deployment_identity": {
                "container_digest": (
                    "sha256:f9bcc273a164f741426079ccf4c9d2269c9ec5e9530845029e593bf466a3aa2e"
                ),
                "weights_sha256": (
                    "9999e2341ceef5e136daa386eecb55cb414446a00ac2b55eb2dfd2f7c3cf8c9e"
                ),
            },
            "last_result": {
                "identity": {
                    "robot": "robot_1",
                    "stream": "camera/color",
                    "generation": 1,
                    "sequence": 8,
                    "request_id": "0df640d4-04ec-43ba-b378-d95e75e8f03c",
                }
            },
        }

    def test_accepts_fresh_pinned_red_mat_result_with_adapter_schema(self):
        self.assertTrue(live_sam3_status_qualified(self.status))

    def test_accepts_enabled_transition_verifier_only_when_requested(self):
        enabled = copy.deepcopy(self.status)
        enabled["prompt_transition_enabled"] = True
        self.assertFalse(live_sam3_status_qualified(enabled))
        self.assertTrue(live_sam3_status_qualified(
            enabled, prompt_transitions_enabled=True))

    def test_rejects_stale_or_unapproved_result(self):
        stale = copy.deepcopy(self.status)
        stale["last_valid_result_age_ms"] = 501.0
        self.assertFalse(live_sam3_status_qualified(stale))

        unapproved = copy.deepcopy(self.status)
        unapproved["prompt"] = "blue crate"
        self.assertFalse(live_sam3_status_qualified(unapproved))

    def test_rejects_old_generation_or_mismatched_model_identity(self):
        old_generation = copy.deepcopy(self.status)
        old_generation["last_result"]["identity"]["generation"] = 0
        self.assertFalse(live_sam3_status_qualified(old_generation))

        wrong_model = copy.deepcopy(self.status)
        wrong_model["deployment_identity"]["weights_sha256"] = "0" * 64
        self.assertFalse(live_sam3_status_qualified(wrong_model))


if __name__ == "__main__":
    unittest.main()
