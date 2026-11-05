import base64
import copy
import unittest

import numpy as np
from PIL import Image

from inference_contract import (ResultGuard, decode_response, dumps, loads,
                                make_request, response_base, success_response)
from sam3_backend import LocalSam3Backend, Sam3ModelRunner


class DeterministicRunner:
    def infer(self, image, prompt, threshold):
        array = np.asarray(image)
        return (array[:, :, 0] > 100)[None, ...], np.array([0.9])


class ContractTests(unittest.TestCase):
    def setUp(self):
        image = Image.new("RGB", (3, 2), (200, 0, 0))
        self.request = make_request(image, sequence=1, epoch="epoch-a", generation=1,
            stamp=100, frame="optical", prompt="red mat", threshold=0.5, budget_ms=500)
        self.backend = LocalSam3Backend(DeterministicRunner())
        self.response = self.backend.predict(self.request)

    def guard(self, request=None, deadline=20, cloud_deadline=20):
        guard = ResultGuard("epoch-a", max_pending=2)
        guard.register(request or self.request, deadline, cloud_deadline, "original-cloud")
        return guard

    def test_local_and_serialized_test_double_identical_normalization(self):
        direct, _ = decode_response(self.request, self.response)
        wire_request = loads(dumps(self.request))
        wire_response = loads(dumps(self.backend.predict(wire_request)))
        mask, _, bundle = self.guard().accept(wire_response, now=10)
        np.testing.assert_array_equal(direct, mask)
        self.assertEqual(set(mask.flat), {2})
        self.assertEqual(bundle, "original-cloud")

    def test_empty_is_success_not_error(self):
        result = success_response(self.request, np.empty((0, 1, 2, 3)), [])
        mask, _ = decode_response(self.request, loads(dumps(result)))
        self.assertFalse(mask.any())
        for status in ("not_ready", "timeout", "invalid_input", "overload", "inference_error"):
            with self.subTest(status=status), self.assertRaises(RuntimeError):
                self.guard().accept(response_base(self.request, status, "test"), now=10)

    def test_all_identity_header_and_version_mismatches_rejected(self):
        mutations = [("identity", key, value) for key, value in
            [("request_id", "other"), ("robot", "robot_2"), ("stream", "other"),
             ("epoch", "old"), ("generation", 0), ("sequence", 2)]]
        mutations += [("versions", key, "wrong") for key in ("model", "preprocess", "decoder")]
        mutations += [("capture", "stamp_ns", 99), ("capture", "frame_id", "wrong")]
        for section, key, value in mutations:
            result = copy.deepcopy(self.response)
            result[section][key] = value
            with self.subTest(section=section, key=key), self.assertRaises(ValueError):
                self.guard().accept(result, now=10)
        for key, value in [("schema", "v0"), ("policy", "wrong"), ("width", 4), ("height", 3)]:
            result = {**self.response, key: value}
            with self.subTest(key=key), self.assertRaises(ValueError):
                self.guard().accept(result, now=10)

    def test_malformed_masks_and_scores_rejected(self):
        for field, value in [("masks", "!"), ("encoding", "float32"), ("count", -1),
            ("count", 65), ("scores", []), ("scores", [float("nan")]), ("scores", [2]),
            ("masks", base64.b64encode(bytes([255] * 6)).decode())]:
            result = {**self.response, field: value}
            with self.subTest(field=field, value=value), self.assertRaises(ValueError):
                self.guard().accept(result, now=10)
        with self.assertRaises(ValueError):
            success_response(self.request, np.empty((0, 1, 3, 3)), [])

    def test_duplicate_and_out_of_order(self):
        guard = self.guard()
        guard.accept(self.response, now=10)
        with self.assertRaises(ValueError):
            guard.accept(self.response, now=10)
        older = copy.deepcopy(self.request)
        older["identity"].update(request_id="older", sequence=0)
        guard.register(older, 20, 20, "old-cloud")
        with self.assertRaises(ValueError):
            guard.accept(self.backend.predict(older), now=10)

    def test_deadlines_and_cloud_expiry(self):
        for deadline, cloud_deadline in [(10, 20), (20, 10)]:
            with self.subTest(deadline=deadline), self.assertRaises(TimeoutError):
                self.guard(deadline=deadline, cloud_deadline=cloud_deadline).accept(self.response, now=10)

    def test_reset_and_policy_change_invalidate_retained_requests(self):
        for epoch, generation in [("epoch-b", 1), ("epoch-a", 2)]:
            guard = self.guard()
            guard.reset(epoch, generation)
            with self.assertRaises(ValueError):
                guard.accept(self.response, now=10)
            with self.assertRaises(ValueError):
                guard.register(self.request, 20, 20, "cloud")

    def test_inflight_bound(self):
        guard = ResultGuard("epoch-a")
        guard.register(self.request, 20, 20, "cloud")
        with self.assertRaises(ValueError):
            guard.register(self.request, 20, 20, "cloud")

    def test_invalid_request_and_backend_exception_are_errors(self):
        for key, value in [("width", 100000), ("image", "invalid"), ("budget_ms", -1),
                           ("encoding", "bgr8"), ("prompt", "")]:
            result = self.backend.predict({**self.request, key: value})
            self.assertEqual(result["status"], "invalid_input")
        class Broken:
            def infer(self, *args):
                raise RuntimeError("injected failure")
        self.assertEqual(LocalSam3Backend(Broken()).predict(self.request)["status"], "inference_error")
        self.assertEqual(LocalSam3Backend(None).predict(self.request)["status"], "not_ready")

    def test_missing_checkpoint_without_importing_torch(self):
        with self.assertRaises(FileNotFoundError):
            Sam3ModelRunner("/nonexistent-phase3-checkpoint/sam3.pt", 0.5)


if __name__ == "__main__":
    unittest.main()
