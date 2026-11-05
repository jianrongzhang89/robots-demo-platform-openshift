#!/usr/bin/env python3
"""Live G1 transport/contract checks against a loaded, isolated mTLS model.

Run in the authorized replay pod. Retain each output; never log certificates,
keys, RGB input, or masks. This is backend qualification, not navigation.
"""
import argparse
import concurrent.futures
import copy
import hashlib
import http.client
import json
from pathlib import Path
import socket
import ssl
import sys
import threading
import time
import uuid

ROOT = Path(__file__).resolve().parents[2]
sys.path[:0] = [str(ROOT / 'apps/semantic-model-server'), str(ROOT / 'apps/semantic-perception')]
from artifact import verify_deployment_identity
from inference_contract import MAX_WIRE_BYTES, decode_response, dumps


def qualify(args):
    host = args.host
    identity = json.loads(args.identity.read_text())
    request = json.loads(args.request.read_text())
    checks = []

    def context(cert='authorized'):
        ctx = ssl.create_default_context(cafile=str(args.ca))
        if cert == 'authorized':
            ctx.load_cert_chain(args.cert, args.key)
        elif cert == 'unbound':
            ctx.load_cert_chain(args.unbound_cert, args.unbound_key)
        return ctx

    def call(body=None, *, cert='authorized', path='/v1/models/sam3-mat-v1', headers=None, declared=None, slow=False):
        conn = http.client.HTTPSConnection(host, 8443, context=context(cert), timeout=8)
        started = time.monotonic()
        try:
            if body is None and declared is None:
                conn.request('GET', path)
            elif declared is not None:
                conn.putrequest('POST', '/v1/models/sam3-mat-v1:predict')
                conn.putheader('Content-Type', 'application/json')
                conn.putheader('Content-Length', str(declared))
                conn.endheaders()
                if slow:
                    conn.send(b'{')
            else:
                conn.request('POST', '/v1/models/sam3-mat-v1:predict', body,
                             headers or {'Content-Type': 'application/json'})
            response = conn.getresponse()
            raw = response.read(MAX_WIRE_BYTES + 1)
            return response.status, json.loads(raw), round((time.monotonic()-started)*1000, 3)
        finally:
            conn.close()

    def check(name, fn):
        start = time.monotonic()
        try:
            detail = fn()
            checks.append({'case': name, 'passed': True, 'detail': detail,
                           'duration_seconds': round(time.monotonic()-start, 3)})
        except Exception as error:
            checks.append({'case': name, 'passed': False, 'error_type': type(error).__name__,
                           'reason': str(error)[:300]})

    def expected(code, body=None, **kw):
        actual, response, elapsed = call(body, **kw)
        assert actual == code, f'expected HTTP {code}, got {actual}'
        return {'http_status': actual, 'status': response.get('status'), 'elapsed_ms': elapsed}

    def successful(req):
        code, response, elapsed = call(dumps(req))
        assert code == 200, f'expected success, got {code}'
        verify_deployment_identity(response['deployment'], identity)
        mask, _ = decode_response(req, response)
        return {'http_status': code, 'occupied_pixels': int(mask.sum()), 'elapsed_ms': elapsed}

    def metadata():
        code, data, _ = call()
        assert code == 200 and data['ready']
        verify_deployment_identity(data['deployment'], identity)
        return {'http_status': code, 'identity_matches': True}

    check('loaded_identity', metadata)
    check('authorized_full_resolution_prediction', lambda: successful(request))

    def no_certificate():
        try:
            call(cert=None)
        except (ssl.SSLError, ConnectionResetError):
            return {'tls_rejected': True}
        raise AssertionError('missing client certificate was not rejected at TLS')
    check('missing_client_certificate', no_certificate)
    check('issuer_signed_unbound_principal', lambda: expected(403, cert='unbound'))

    def wrong_server():
        conn = http.client.HTTPSConnection(socket.gethostbyname(host), 8443,
                                           context=context(), timeout=5)
        try:
            conn.request('GET', '/v1/models/sam3-mat-v1')
        except ssl.SSLCertVerificationError:
            return {'hostname_verification_rejected': True}
        finally:
            conn.close()
        raise AssertionError('wrong server hostname accepted')
    check('wrong_server_identity', wrong_server)

    for key, value in [('robot', 'robot_2'), ('stream', 'other-camera')]:
        req = copy.deepcopy(request); req['identity'][key] = value
        check('unauthorized_'+key, lambda req=req: expected(403, dumps(req)))
    for name, data in [('malformed_json', b'{bad'), ('nonfinite_json', b'{"budget_ms":NaN}'),
                       ('invalid_envelope', b'[]')]:
        check(name, lambda data=data: expected(400, data))
    check('wrong_content_type', lambda: expected(415, b'{}', headers={'Content-Type':'text/plain'}))
    for name, change in [('wrong_model_version', lambda r: r['versions'].update(model='unapproved')),
                          ('wrong_policy', lambda r: r.update(policy='unapproved')),
                          ('wrong_prompt', lambda r: r.update(prompt='other target')),
                          ('too_many_pixels', lambda r: r.update(width=641, height=480))]:
        req = copy.deepcopy(request); change(req)
        check(name, lambda req=req: expected(400, dumps(req)))
    req = copy.deepcopy(request); req['budget_ms'] = .001
    check('expired_budget', lambda: expected(504, dumps(req)))
    check('over_wire_limit', lambda: expected(413, declared=MAX_WIRE_BYTES+1))
    check('slow_upload_timeout', lambda: expected(408, declared=100, slow=True))

    def wire_boundary():
        req = copy.deepcopy(request); req['padding'] = ''
        base = json.dumps(req, separators=(',', ':')).encode()
        req['padding'] = 'x' * (MAX_WIRE_BYTES-len(base))
        data = json.dumps(req, separators=(',', ':')).encode()
        assert len(data) == MAX_WIRE_BYTES
        code, response, elapsed = call(data)
        assert code == 200, f'maximum-size legal envelope failed: {code}'
        verify_deployment_identity(response['deployment'], identity)
        decode_response(req, response)
        return {'request_bytes':len(data), 'http_status':code, 'elapsed_ms':elapsed}
    check('exact_wire_limit', wire_boundary)

    def concurrency():
        barrier = threading.Barrier(16)
        def one(index):
            req = copy.deepcopy(request); req['identity']['request_id'] = str(uuid.uuid4())
            wire = dumps(req); barrier.wait()
            try:
                code, response, elapsed = call(wire)
                assert code in (200, 429), f'unexpected concurrent status {code}'
                if code == 200:
                    verify_deployment_identity(response['deployment'], identity)
                    decode_response(req, response)
                else:
                    assert response['status'] == 'overload'
                return {'http_status':code, 'elapsed_ms':elapsed}
            except (ConnectionResetError, ssl.SSLError, BrokenPipeError, http.client.RemoteDisconnected) as error:
                return {'transport_rejected':type(error).__name__}
        with concurrent.futures.ThreadPoolExecutor(max_workers=16) as pool:
            rows = list(pool.map(one, range(16)))
        assert any(r.get('http_status') == 200 for r in rows)
        assert any(r.get('http_status') == 429 for r in rows)
        return {'concurrent_requests':16, 'results':rows}
    check('bounded_concurrent_admission', concurrency)
    check('healthy_after_negative_tests', metadata)
    check('prediction_after_negative_tests', lambda: successful(request))
    return {'scope':'G1 live model endpoint contract/security; no navigation claim',
            'status':'PASS' if all(c['passed'] for c in checks) else 'FAIL', 'checks':checks}


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--host', default='sam3-mat-v1-tls.semantic-model-serving.svc')
    for flag in ('identity', 'request', 'ca', 'cert', 'key', 'unbound-cert', 'unbound-key', 'output'):
        parser.add_argument('--'+flag, type=Path, required=True)
    args = parser.parse_args()
    if args.output.exists():
        parser.error('retain previous attempts; use a new output path')
    result = qualify(args)
    args.output.write_text(json.dumps(result, indent=2)+'\n')
    print(json.dumps({'status':result['status'], 'checks':len(result['checks'])}))
    sys.exit(0 if result['status']=='PASS' else 1)
