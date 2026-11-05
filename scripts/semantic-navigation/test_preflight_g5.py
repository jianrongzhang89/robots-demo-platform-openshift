"""Fail-closed inventory and evidence-preservation checks."""
import json
from pathlib import Path
import subprocess
import tempfile
import unittest
from unittest.mock import patch

import preflight_g5


class PreflightTests(unittest.TestCase):
    def test_api_timeout_is_retained_and_gate_stays_hold(self):
        with patch.object(preflight_g5.subprocess, "run", side_effect=subprocess.TimeoutExpired("oc", 35)):
            result = preflight_g5.collect()
        self.assertEqual(result["preflight_status"], "HOLD")
        self.assertEqual(result["gate_status"], "HOLD")
        self.assertFalse(result["accepted"])
        self.assertEqual(len(result["errors"]), 1)
        self.assertEqual(len(result["commands"]), 1)

    def test_not_ready_is_not_inferred_from_running(self):
        self.assertFalse(preflight_g5.ready({"status": {"phase": "Running"}}))
        self.assertFalse(preflight_g5.ready({"status": {"conditions": [{"type": "Ready", "status": "False"}]}}))

    def test_pod_summary_excludes_environment_and_annotations(self):
        pod = {"metadata": {"name": "p", "uid": "u", "annotations": {"sensitive": "hidden"}},
               "spec": {"containers": [{"env": [{"name": "TOKEN", "value": "hidden"}]}]},
               "status": {}}
        self.assertNotIn("hidden", json.dumps(preflight_g5.pod_summary(pod)))

    def test_existing_evidence_is_never_overwritten(self):
        with tempfile.TemporaryDirectory() as directory:
            output = Path(directory) / "attempt.json"
            output.write_text("original")
            with patch("sys.argv", ["preflight_g5.py", "--output", str(output)]), patch.object(preflight_g5, "collect") as collect:
                with self.assertRaises(FileExistsError):
                    preflight_g5.main()
                collect.assert_not_called()
            self.assertEqual(output.read_text(), "original")


if __name__ == "__main__":
    unittest.main()
