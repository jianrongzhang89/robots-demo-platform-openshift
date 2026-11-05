import copy
import importlib.util
from pathlib import Path
import unittest

import numpy as np

from inference_contract import success_response
from test_server import request

ROOT = Path(__file__).resolve().parents[3]


def module(name, path):
    spec = importlib.util.spec_from_file_location(name, ROOT / path)
    loaded = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(loaded)
    return loaded


renderer = module("serving_render", "helm/semantic-navigation/openshift-ai/render.py")
parity = module("serving_parity", "scripts/semantic-navigation/replay_serving_parity.py")


class QualificationTests(unittest.TestCase):
    def test_digest_required(self):
        for image in ("model:latest", "model@sha256:short", "model@sha256:" + "g" * 64):
            with self.assertRaises(ValueError):
                renderer.render(image)

    def test_isolated_candidate_invariants(self):
        items = renderer.render("model@sha256:" + "a" * 64)["items"]
        by_kind = {r["kind"]: r for r in items}
        predictor = by_kind["InferenceService"]["spec"]["predictor"]
        self.assertEqual((predictor["minReplicas"], predictor["maxReplicas"]), (1, 1))
        self.assertFalse(predictor["automountServiceAccountToken"])
        container = by_kind["ServingRuntime"]["spec"]["containers"][0]
        self.assertEqual(container["resources"]["limits"]["nvidia.com/gpu"], "1")
        self.assertTrue(container["securityContext"]["readOnlyRootFilesystem"])
        self.assertEqual(by_kind["NetworkPolicy"]["spec"]["egress"], [])
        self.assertEqual(by_kind["Service"]["spec"]["ports"][0]["port"], 8443)
        self.assertNotIn("Route", by_kind)
        for kind in ("Namespace", "ServingRuntime", "InferenceService"):
            self.assertEqual(by_kind[kind]["metadata"]["labels"]["opendatahub.io/dashboard"], "true")

    def test_reserved_gpu_placement(self):
        items = renderer.render("model@sha256:" + "a" * 64, node_name="reserved-node")["items"]
        predictor = next(r for r in items if r["kind"] == "InferenceService")["spec"]["predictor"]
        self.assertEqual(predictor["nodeSelector"]["kubernetes.io/hostname"], "reserved-node")
        self.assertEqual(predictor["nodeSelector"]["nvidia.com/gpu.product"], "NVIDIA-L40S")
        self.assertIn({"key": "g6e-gpu", "operator": "Equal", "value": "true",
                      "effect": "NoSchedule"}, predictor["tolerations"])

    def test_parity_rejects_empty_nonempty_mismatch(self):
        req = request()
        positive = success_response(req, np.ones((1, 2, 3)), [0.9])
        empty = success_response(req, np.empty((0, 2, 3)), [])
        result = parity.compare(req, positive, empty)
        self.assertFalse(result["passed"])
        self.assertFalse(result["empty_agreement"])
        self.assertTrue(parity.compare(req, empty, empty)["passed"])

    def test_parity_compares_union_not_instance_order(self):
        req = request()
        masks = np.array([[[1, 0, 0], [0, 0, 0]], [[0, 1, 0], [0, 0, 0]]])
        local = success_response(req, masks, [0.9, 0.9])
        remote = success_response(req, masks[::-1], [0.9, 0.9])
        self.assertTrue(parity.compare(req, local, remote)["passed"])
        remote["identity"] = copy.deepcopy(remote["identity"])
        remote["identity"]["robot"] = "robot_2"
        with self.assertRaises(ValueError):
            parity.compare(req, local, remote)


if __name__ == "__main__":
    unittest.main()
