import copy
import json
from pathlib import Path
import tempfile
from types import SimpleNamespace
import unittest
from unittest.mock import patch

import run_g5_replay_cycles as cycles


class LifecycleTests(unittest.TestCase):
    def exercise(self, fail_candidate=False):
        baseline = json.loads((cycles.GATES / 'S2/gate-result.json').read_text())['deployment_identity']
        old_image = 'registry/model@' + baseline['container_digest']
        candidate = 'registry/model@sha256:' + 'a' * 64
        original = {'spec': {'containers': [{'name': 'kserve-container', 'image': old_image,
                     'env': [{'name': 'RUNTIME_IMAGE_DIGEST', 'value': baseline['container_digest']}]}]}}
        state = {'runtime': copy.deepcopy(original), 'uid': 0, 'failed': False, 'strategy': None}

        def run(command, **kwargs):
            args = command[2:]
            out = ''
            rc = 0
            if args[:2] == ['get', 'servingruntime']:
                out = json.dumps(state['runtime'])
            elif args[:2] == ['get', 'inferenceservice']:
                out = json.dumps({'spec': {'predictor': {}}})
            elif args[:2] == ['get', 'pods']:
                if 'semantic-navigation' in args:
                    out = json.dumps({'items': [{'metadata': {'name': cycles.CLIENT}}]})
                else:
                    out = json.dumps({'items': [{'metadata': {'name': 'serving', 'uid': str(state['uid'])},
                         'status': {'containerStatuses': [{'name': 'kserve-container', 'ready': True,
                         'imageID': state['runtime']['spec']['containers'][0]['image']}]}}]})
            elif args[:2] == ['patch', 'servingruntime']:
                new = json.loads(args[-1])[0]['value']
                if new != state['runtime']['spec']:
                    state['uid'] += 1
                state['runtime']['spec'] = new
            elif args[:2] == ['patch', 'inferenceservice']:
                state['strategy'] = json.loads(args[-1])['spec']['predictor']['deploymentStrategy']
            elif args[0] == 'exec':
                if 'cat' in args:
                    out = json.dumps({'status': 'PASS'})
                if fail_candidate and '--identity' in args and '/tmp/candidate-identity.json' in args and not state['failed']:
                    state['failed'] = True
                    rc = 1
            else:
                raise AssertionError(command)
            return SimpleNamespace(stdout=out, stderr='injected replay failure' if rc else '', returncode=rc)

        with tempfile.TemporaryDirectory() as directory:
            output = Path(directory) / 'attempt'
            with patch('sys.argv', ['cycles', '--candidate-image', candidate, '--output-dir', str(output)]), patch.object(cycles.subprocess, 'run', side_effect=run):
                if fail_candidate:
                    with self.assertRaises(RuntimeError):
                        cycles.main()
                else:
                    cycles.main()
            result = json.loads((output / 'result.json').read_text())
        self.assertEqual(state['runtime'], original)
        self.assertIsNone(state['strategy'])
        self.assertEqual(result['restoration'], 'PASS')
        return result

    def test_three_cycles_restore_original_spec_and_strategy(self):
        result = self.exercise()
        self.assertEqual(result['status'], 'PASS')
        self.assertEqual(len(result['cycles']), 3)
        self.assertTrue(all(c['passed'] for c in result['cycles']))

    def test_failed_candidate_stops_without_retry_and_restores(self):
        result = self.exercise(fail_candidate=True)
        self.assertEqual(result['status'], 'FAIL')
        self.assertEqual(len(result['cycles']), 1)
        self.assertNotIn('passed', result['cycles'][0])


if __name__ == '__main__':
    unittest.main()
