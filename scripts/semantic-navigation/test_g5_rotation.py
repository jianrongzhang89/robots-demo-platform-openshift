import json
from pathlib import Path
import subprocess
import tempfile
from types import SimpleNamespace
import unittest
from unittest.mock import patch

import rotate_g5_credentials as rotation


class RotationTests(unittest.TestCase):
    def test_failed_restart_restores_all_original_secret_data(self):
        expected = json.loads((rotation.ROOT / 'docs/validation/semantic-navigation/openshift-ai/S2/gate-result.json').read_text())['deployment_identity']
        original_data = {'sentinel': 'b3JpZ2luYWw='}
        applied = []; deletes = []; pod_reads = []
        real_run = subprocess.run

        def run(command, **kwargs):
            if command[0] != 'oc':
                return real_run(command, **kwargs)
            args = list(command[2:]); out = b''; rc = 0
            if args[:2] == ['get', 'pods']:
                if 'semantic-navigation' in args:
                    data = {'items': [{'metadata': {'name': rotation.CLIENT}}]}
                else:
                    pod_reads.append(True)
                    data = {'items': [{'metadata': {'name': 'server', 'uid': str(len(pod_reads))},
                         'status': {'conditions': [{'type': 'Ready', 'status': 'True'}],
                           'containerStatuses': [{'name': 'kserve-container', 'imageID': 'registry/model@'+expected['container_digest']}]}}]}
                out = json.dumps(data).encode()
            elif args[:2] == ['get', 'secret']:
                out = json.dumps({'data': original_data}).encode()
            elif args[0] == 'apply':
                applied.append(json.loads(kwargs['input']))
            elif args[:2] == ['delete', 'pod']:
                deletes.append(True)
                if len(deletes) == 1:
                    rc = 1
            elif args[0] != 'exec':
                raise AssertionError(args)
            return SimpleNamespace(stdout=out, stderr=b'', returncode=rc)

        with tempfile.TemporaryDirectory() as directory:
            output = Path(directory)/'attempt'
            with patch('sys.argv', ['rotate', '--output-dir', str(output)]), patch.object(rotation.subprocess, 'run', side_effect=run):
                with self.assertRaises(RuntimeError):
                    rotation.main()
            report = json.loads((output/'result.json').read_text())
        self.assertEqual(len(applied), 6)
        self.assertTrue(all(secret['data'] == original_data for secret in applied[-3:]))
        self.assertEqual(report['status'], 'FAIL')
        self.assertEqual(report['rollback'], 'SECRETS_RESTORED_RECHECK_CLIENT_PROJECTION')
        self.assertNotIn('PRIVATE KEY', json.dumps(report))
        self.assertNotIn('b3JpZ2luYWw=', json.dumps(report))


if __name__ == '__main__':
    unittest.main()
