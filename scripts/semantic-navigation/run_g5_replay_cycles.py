#!/usr/bin/env python3
"""Three stopped replay update/rollback cycles. Does not qualify motion or G5.

Refuses other labeled serving clients. Uses Recreate and restores original runtime
and rollout strategy in finally. Requires a separately built, digest-pinned image.
"""
import argparse
import copy
from datetime import datetime, timezone
import json
from pathlib import Path
import re
import subprocess
import time

ROOT = Path(__file__).resolve().parents[2]
GATES = ROOT / 'docs/validation/semantic-navigation/openshift-ai'
NS = 'semantic-model-serving'
CLIENT = 'sam3-g5-client'


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument('--candidate-image', required=True)
    p.add_argument('--output-dir', type=Path, required=True)
    args = p.parse_args()
    if not re.fullmatch(r'[^\s@]+@sha256:[0-9a-f]{64}', args.candidate_image):
        raise ValueError('digest-pinned candidate required')
    args.output_dir.mkdir(parents=True, exist_ok=False)
    result = {'started_at': datetime.now(timezone.utc).isoformat(), 'status': 'FAIL',
              'scope': 'stopped replay only; no ROS, motion, timing or new-presenter qualification',
              'cycles': [], 'restoration': 'NOT_ATTEMPTED'}

    def oc(*argv, data=None, timeout=45):
        r = subprocess.run(['oc', '--request-timeout=30s', *argv], input=data,
                           capture_output=True, text=True, timeout=timeout)
        with (args.output_dir / 'commands.jsonl').open('a') as log:
            log.write(json.dumps({'at': datetime.now(timezone.utc).isoformat(),
                                 'args': argv, 'returncode': r.returncode,
                                 'stderr': r.stderr}) + '\n')
        if r.returncode:
            raise RuntimeError(f'oc {argv[0]} failed: {r.stderr}')
        return r.stdout

    def get(kind, name, namespace=NS):
        return json.loads(oc('get', kind, name, '-n', namespace, '-o', 'json'))

    original = get('servingruntime', 'sam3-runtime-v1')
    isvc = get('inferenceservice', 'sam3-mat-v1')
    (args.output_dir / 'original-runtime.json').write_text(json.dumps(original, indent=2) + '\n')
    (args.output_dir / 'original-isvc.json').write_text(json.dumps(isvc, indent=2) + '\n')
    baseline = json.loads((GATES / 'S2/gate-result.json').read_text())['deployment_identity']
    candidate = dict(baseline, container_digest=args.candidate_image.split('@')[1])
    if candidate == baseline:
        raise ValueError('candidate must have a distinct image identity')
    clients = json.loads(oc('get', 'pods', '-n', 'semantic-navigation', '-l',
        'semantic-serving-client=sam3-mat-v1', '-o', 'json'))['items']
    if [item['metadata']['name'] for item in clients] != [CLIENT]:
        raise ValueError('stopped replay requires exactly the G5 client and no other authorized client pods')
    for name, identity in [('baseline', baseline), ('candidate', candidate)]:
        oc('exec', '-i', '-n', 'semantic-navigation', CLIENT, '--', 'tee', f'/tmp/{name}-identity.json',
           data=json.dumps(identity))

    def patch_runtime(spec):
        oc('patch', 'servingruntime', 'sam3-runtime-v1', '-n', NS, '--type=json', '-p',
           json.dumps([{'op': 'replace', 'path': '/spec', 'value': spec}]))

    def wait_image(identity):
        deadline = time.monotonic() + 600
        while time.monotonic() < deadline:
            pods = json.loads(oc('get', 'pods', '-n', NS, '-l',
                'serving.kserve.io/inferenceservice=sam3-mat-v1', '-o', 'json'))['items']
            active = [pod for pod in pods if not pod['metadata'].get('deletionTimestamp')]
            if len(active) == 1:
                pod = active[0]
                statuses = pod.get('status', {}).get('containerStatuses', [])
                if statuses and all(c.get('ready') for c in statuses) and any(
                    c['name'] == 'kserve-container' and c.get('imageID', '').endswith('@' + identity['container_digest']) for c in statuses):
                    return {'pod': pod['metadata']['name'], 'uid': pod['metadata']['uid'],
                            'containers': statuses, 'at': datetime.now(timezone.utc).isoformat()}
            time.sleep(3)
        raise TimeoutError('expected image did not become Ready within 600 seconds')

    def replay(name, label):
        path = '/tmp/' + label + '.json'
        oc('exec', '-n', 'semantic-navigation', CLIENT, '--', '/opt/sam3-venv/bin/python',
           '/tmp/g5/scripts/semantic-navigation/replay_serving_parity.py',
           '--manifest', '/tmp/frozen/manifest.json', '--identity', f'/tmp/{name}-identity.json',
           '--ca', '/cert/ca.crt', '--cert', '/cert/tls.crt', '--key', '/cert/tls.key',
           '--endpoint', 'https://sam3-mat-v1-tls.semantic-model-serving.svc:8443', '--output', path)
        evidence = json.loads(oc('exec', '-n', 'semantic-navigation', CLIENT, '--', 'cat', path))
        (args.output_dir / (label + '.json')).write_text(json.dumps(evidence, indent=2) + '\n')
        if evidence['status'] != 'PASS':
            raise ValueError('parity failed')
        return evidence['status']

    updated = copy.deepcopy(original['spec'])
    container = next(c for c in updated['containers'] if c['name'] == 'kserve-container')
    container['image'] = args.candidate_image
    next(e for e in container['env'] if e['name'] == 'RUNTIME_IMAGE_DIGEST')['value'] = candidate['container_digest']
    try:
        result['baseline'] = wait_image(baseline)
        replay('baseline', 'baseline-parity')
        oc('patch', 'inferenceservice', 'sam3-mat-v1', '-n', NS, '--type=merge', '-p',
           json.dumps({'spec': {'predictor': {'deploymentStrategy': {'type': 'Recreate', 'rollingUpdate': None}}}}))
        for cycle in range(1, 4):
            row = {'cycle': cycle}; result['cycles'].append(row)
            patch_runtime(updated)
            row['update'] = wait_image(candidate)
            row['candidate_parity'] = replay('candidate', f'cycle-{cycle}-candidate')
            patch_runtime(original['spec'])
            row['rollback'] = wait_image(baseline)
            row['rollback_parity'] = replay('baseline', f'cycle-{cycle}-rollback')
            row['passed'] = row['update']['uid'] != row['rollback']['uid']
            if not row['passed']:
                raise ValueError('pod replacement not observed')
            (args.output_dir / 'progress.json').write_text(json.dumps(result, indent=2) + '\n')
        result['status'] = 'PASS'
    except Exception as error:
        result['error'] = str(error)
        raise
    finally:
        try:
            patch_runtime(original['spec'])
            result['restored_pod'] = wait_image(baseline)
            replay('baseline', 'restoration-parity')
            oc('patch', 'inferenceservice', 'sam3-mat-v1', '-n', NS, '--type=merge', '-p',
               json.dumps({'spec': {'predictor': {'deploymentStrategy': isvc['spec']['predictor'].get('deploymentStrategy')}}}))
            result['restoration'] = 'PASS'
        except Exception as error:
            result['status'] = 'FAIL'; result['restoration'] = 'FAIL'; result['restoration_error'] = str(error)
        (args.output_dir / 'result.json').write_text(json.dumps(result, indent=2) + '\n')
    if result['status'] != 'PASS':
        raise RuntimeError('cycle or restoration failed; see result.json')


if __name__ == '__main__':
    main()
