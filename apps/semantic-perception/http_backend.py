"""Single-flight mTLS inference transport with a whole-operation deadline.

No CUDA, model imports, retries, fallback, or readiness inferred from HTTP health.
The caller still owns capture freshness, retained depth and publication guards.
"""
import copy
import http.client
import json
import math
from pathlib import Path
import re
import socket
import ssl
import threading
import time
from urllib.parse import urlsplit

from inference_contract import MAX_WIRE_BYTES, POLICY, VERSIONS, dumps, loads, validate_request


class BackendFailure(RuntimeError):
    pass


class IdentityMismatch(BackendFailure):
    pass


class HttpSam3Backend:
    def __init__(self, endpoint, ca, cert, key, expected_identity, metadata_timeout=2.0):
        uri = urlsplit(endpoint)
        if (uri.scheme != 'https' or not uri.hostname or uri.username or uri.password or
                uri.query or uri.fragment or uri.path not in ('', '/')):
            raise ValueError('an HTTPS origin without credentials or path is required')
        if not math.isfinite(metadata_timeout) or not 0 < metadata_timeout <= 5:
            raise ValueError('metadata deadline must be in (0, 5] seconds')
        self.host, self.port = uri.hostname, uri.port or 443
        self.expected = copy.deepcopy(expected_identity)
        required = {'schema', 'model_name', 'weights_sha256', 'source_revision', 'container_digest',
                    'shared_sha256', 'versions', 'precision', 'policy', 'prompt', 'threshold'}
        if (set(self.expected) != required or self.expected['schema'] != 'semantic-deployment/v1' or
                self.expected['model_name'] != 'sam3-mat-v1' or self.expected['versions'] != VERSIONS or
                self.expected['policy'] != POLICY or self.expected['precision'] not in ('bfloat16', 'float16') or
                not re.fullmatch('[a-f0-9]{64}', self.expected['weights_sha256']) or
                not re.fullmatch('[a-f0-9]{40}', self.expected['source_revision']) or
                not re.fullmatch('sha256:[a-f0-9]{64}', self.expected['container_digest']) or
                set(self.expected['shared_sha256']) != {'sam3_backend.py', 'inference_contract.py', 'sam3_runtime_core.py'} or
                any(not re.fullmatch('[a-f0-9]{64}', h) for h in self.expected['shared_sha256'].values())):
            raise ValueError('complete pinned deployment identity required')
        self.context = ssl.create_default_context(cafile=str(ca))
        self.context.minimum_version = ssl.TLSVersion.TLSv1_2
        self.context.load_cert_chain(cert, key)
        self.metadata_timeout = metadata_timeout
        self.initialized = False
        self.identity_fault = False
        self.loaded_identity = None
        self._flight = threading.Lock()
        self._state = threading.Lock()
        self._socket = None
        self._closed = False
        self._resolved = threading.Event()
        self._addresses = None
        self._resolver_started = False

    @property
    def in_flight(self):
        return int(self._flight.locked())

    def _remaining(self, deadline):
        remaining = deadline - time.monotonic()
        if remaining <= 0:
            raise TimeoutError('inference transport deadline expired')
        if self._closed:
            raise BackendFailure('backend closed')
        return remaining

    def _resolve(self):
        try:
            self._addresses = socket.getaddrinfo(self.host, self.port, type=socket.SOCK_STREAM)[:8]
        except OSError:
            self._addresses = []
        finally:
            self._resolved.set()

    def _connect(self, deadline):
        # At most one resolver thread, even if libc DNS stalls. No per-frame
        # thread/future accumulation; a failed resolution needs explicit restart.
        if not self._resolver_started:
            self._resolver_started = True
            threading.Thread(target=self._resolve, daemon=True, name='semantic-dns').start()
        if not self._resolved.wait(self._remaining(deadline)):
            raise TimeoutError('endpoint DNS deadline expired')
        if not self._addresses:
            raise BackendFailure('endpoint DNS unavailable')
        for family, kind, proto, _, address in self._addresses:
            sock = socket.socket(family, kind, proto)
            try:
                sock.settimeout(self._remaining(deadline))
                sock.connect(address)
                sock.settimeout(self._remaining(deadline))
                tls = self.context.wrap_socket(sock, server_hostname=self.host)
                with self._state:
                    if self._closed:
                        tls.close()
                        raise BackendFailure('backend closed')
                    self._socket = tls
                return tls
            except ssl.SSLError:
                sock.close()
                raise
            except OSError:
                sock.close()
                self._remaining(deadline)
        raise BackendFailure('endpoint connection unavailable')

    @staticmethod
    def _interrupt(sock):
        try:
            sock.shutdown(socket.SHUT_RDWR)
        except OSError:
            pass

    def close(self):
        with self._state:
            self._closed = True
            self._resolved.set()
            if self._socket is not None:
                self._interrupt(self._socket)

    def _exchange(self, method, path, body, deadline):
        sock = self._connect(deadline)
        connection = http.client.HTTPSConnection(self.host, self.port, context=self.context)
        connection.sock = sock
        timer = None
        try:
            timer = threading.Timer(self._remaining(deadline), self._interrupt, args=(sock,))
            timer.daemon = True
            timer.start()
            connection.request(method, path, body, {'Content-Type': 'application/json', 'Connection': 'close'})
            response = connection.getresponse()
            lengths = response.headers.get_all('Content-Length', [])
            if (response.getheader('Transfer-Encoding') or len(lengths) != 1 or
                    not lengths[0].isdigit() or len(lengths[0]) > 10 or
                    not 0 < int(lengths[0]) <= MAX_WIRE_BYTES):
                raise BackendFailure('invalid or oversized response framing')
            remaining = int(lengths[0]); data = bytearray()
            while remaining:
                self._remaining(deadline)
                chunk = response.read1(min(65536, remaining))
                if not chunk:
                    raise BackendFailure('truncated inference response')
                data.extend(chunk); remaining -= len(chunk)
            result = loads(data)
            self._remaining(deadline)
            if not isinstance(result, dict):
                raise BackendFailure('invalid response envelope')
            return response.status, result
        finally:
            if timer is not None:
                timer.cancel()
            connection.close()
            with self._state:
                self._socket = None

    def _identity(self, identity):
        if identity != self.expected:
            self.identity_fault = True
            self.loaded_identity = None
            raise IdentityMismatch('served deployment differs from pinned identity; restart required')
        self.loaded_identity = copy.deepcopy(identity)

    def initialize(self):
        if self.identity_fault:
            raise IdentityMismatch('identity fault latched; restart required')
        if not self._flight.acquire(blocking=False):
            raise BackendFailure('inference already in flight')
        try:
            code, result = self._exchange('GET', '/v1/models/sam3-mat-v1', None,
                                          time.monotonic()+self.metadata_timeout)
            if code != 200 or result.get('ready') is not True:
                raise BackendFailure('model metadata not ready')
            self._identity(result.get('deployment'))
            self.initialized = True
        finally:
            self._flight.release()

    def predict(self, request):
        if not self.initialized or self.identity_fault:
            raise BackendFailure('backend identity unavailable or faulted')
        if not self._flight.acquire(blocking=False):
            raise BackendFailure('inference already in flight')
        deadline = time.monotonic()
        try:
            budget = request['budget_ms']
            if type(budget) not in (int, float) or not math.isfinite(budget) or not 0 < budget <= 5000:
                raise ValueError('invalid request deadline')
            deadline += budget / 1000
            validate_request(request)
            if request['prompt'] != self.expected['prompt'] or request['threshold'] != self.expected['threshold']:
                raise ValueError('request differs from pinned prompt policy')
            wire_request = dict(request, budget_ms=self._remaining(deadline) * 1000)
            body = dumps(wire_request)
            self._remaining(deadline)
            code, result = self._exchange('POST', '/v1/models/sam3-mat-v1:predict', body, deadline)
            if code != 200:
                raise BackendFailure('inference HTTP '+str(code))
            self._identity(result.get('deployment'))
            # Correlation/mask validation remains in ResultGuard, which owns
            # the original retained bundle and capture deadline.
            return result
        finally:
            self._flight.release()
