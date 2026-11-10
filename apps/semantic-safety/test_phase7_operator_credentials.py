import json
from pathlib import Path
import tempfile
import unittest

from verify_phase7_native_operator import prepare_operator_credentials


class Phase7OperatorCredentialTests(unittest.TestCase):
    def test_loads_managed_secret_files_without_copying_them(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            expected = {
                "signing.key": b"s" * 32,
                "operators.json": json.dumps({"operator-17": "credential"}).encode(),
                "server.crt": b"server-cert",
                "server.key": b"server-key",
                "client-ca.crt": b"client-ca",
                "operator-17.crt": b"client-cert",
                "operator-17.key": b"client-key",
            }
            for name, value in expected.items():
                (root / name).write_bytes(value)

            credential_root, key, operators = prepare_operator_credentials(
                root / "scratch", root)

            self.assertEqual(credential_root, root)
            self.assertEqual(key, expected["signing.key"])
            self.assertEqual(operators, {"operator-17": "credential"})
            self.assertFalse((root / "scratch").exists())

    def test_rejects_incomplete_or_weak_managed_credentials(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            for name in ("signing.key", "operators.json", "server.crt", "server.key",
                         "client-ca.crt", "operator-17.crt", "operator-17.key"):
                (root / name).write_text("x")
            (root / "operators.json").write_text(json.dumps({"operator-17": "credential"}))
            with self.assertRaisesRegex(ValueError, "fixture contract"):
                prepare_operator_credentials(root / "scratch", root)

    def test_ephemeral_fixture_provisioner_creates_tls_material(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory) / "credentials"
            root.mkdir()
            credential_root, key, operators = prepare_operator_credentials(root)
            self.assertEqual(credential_root, root)
            self.assertGreaterEqual(len(key), 32)
            self.assertEqual(set(operators), {"operator-17"})
            for name in ("client-ca.crt", "server.crt", "server.key",
                         "operator-17.crt", "operator-17.key"):
                self.assertTrue((root / name).is_file())


if __name__ == "__main__":
    unittest.main()
