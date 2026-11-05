#!/usr/bin/env python3
"""Register G5-owned metadata via authenticated v1alpha3; never edit other entries.

Uses the current oc identity in memory. TLS verification is mandatory. Retains
partial results on failure; re-runs reuse only exact matching metadata.
"""
import argparse
from datetime import datetime, timezone
import json
from pathlib import Path
import subprocess
import urllib.parse
import urllib.request


def register(metadata, endpoint, token, evidence):
    if not endpoint.startswith('https://'):
        raise ValueError('verified HTTPS endpoint required')
    base = endpoint.rstrip('/') + '/api/model_registry/v1alpha3'

    def api(path, body=None):
        request = urllib.request.Request(base + path,
            data=None if body is None else json.dumps(body).encode(),
            headers={'Authorization': 'Bearer ' + token, 'Content-Type': 'application/json'})
        with urllib.request.urlopen(request, timeout=30) as response:
            return json.load(response)

    def ensure(collection, body, detail):
        found = api(collection + '?' + urllib.parse.urlencode({'name': body['name'], 'pageSize': 100}))
        items = [item for item in found['items'] if item['name'] == body['name']]
        if found.get('nextPageToken'):
            raise ValueError('ambiguous paginated name lookup')
        if len(items) > 1:
            raise ValueError('duplicate name')
        item = items[0] if items else api(collection, body)
        # Record creation before readback so failure cannot hide a partial write.
        evidence['operations'].append({'collection': collection, 'id': item['id'], 'created': not items})
        actual = api(detail + '/' + item['id'])
        if any(actual.get(key) != value for key, value in body.items()):
            raise ValueError('registry readback differs: ' + detail)
        evidence['readback'][detail] = actual
        return actual

    def properties(values):
        return {key: {'metadataType': 'MetadataStringValue', 'string_value':
                value if isinstance(value, str) else json.dumps(value, sort_keys=True)}
                for key, value in values.items()}

    model = ensure('/registered_models', {
        'name': metadata['registered_model_name'],
        'description': 'Semantic navigation SAM3 demonstration. Recognition waiver retained; G5 pending.',
        'customProperties': properties({'owner': 'robots-demo-platform-openshift', 'scope': 'semantic-navigation'})
    }, '/registered_models')
    identity = metadata['deployment_identity']
    version = ensure('/registered_models/' + model['id'] + '/versions', {
        'name': 'g4-accepted-' + identity['container_digest'].split(':')[1][:12],
        'registeredModelId': model['id'],
        'customProperties': properties({key: metadata[key] for key in
            ('deployment_identity', 'runtime_manifest', 'prompt_policy', 'evaluation_status', 'evidence_uris', 'limitations')})
    }, '/model_versions')
    artifact = ensure('/model_versions/' + version['id'] + '/artifacts', {
        'name': 'sam3-' + identity['weights_sha256'][:12], 'artifactType': 'model-artifact',
        'uri': metadata['artifact_uri'], 'modelFormatName': 'sam3', 'modelFormatVersion': '1',
        'customProperties': properties({'weights_sha256': identity['weights_sha256'],
                                        'locator_note': metadata['artifact_uri_note']})
    }, '/model_artifacts')
    evidence['ids'] = {'registered_model': model['id'], 'model_version': version['id'], 'artifact': artifact['id']}


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument('--metadata', type=Path, required=True)
    p.add_argument('--endpoint', required=True)
    p.add_argument('--output', type=Path, required=True)
    args = p.parse_args()
    evidence = {'recorded_at': datetime.now(timezone.utc).isoformat(), 'endpoint': args.endpoint,
                'status': 'FAIL', 'operations': [], 'readback': {}}
    with args.output.open('x') as output:
        try:
            token = subprocess.check_output(['oc', 'whoami', '-t'], text=True, timeout=20).strip()
            register(json.loads(args.metadata.read_text()), args.endpoint, token, evidence)
            evidence['status'] = 'PASS'
        except Exception as error:
            evidence['error'] = str(error)
            raise
        finally:
            output.write(json.dumps(evidence, indent=2) + '\n')
    print(json.dumps({'status': evidence['status'], 'ids': evidence['ids']}))


if __name__ == '__main__':
    main()
