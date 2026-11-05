import copy
import json
import socket
import sys
import threading
import time
import unittest
from unittest.mock import patch

from PIL import Image
from backend_factory import create_backend
from http_backend import HttpSam3Backend, BackendFailure, IdentityMismatch
from inference_contract import ResultGuard, make_request
from http_fixture import Fixture


class HttpBackendTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):cls.fixture=Fixture()
    @classmethod
    def tearDownClass(cls):cls.fixture.close()
    def setUp(self):
        self.fixture.mode='ok';self.fixture.entered.clear();self.fixture.last=None
        self.backend=self.create();self.backend.initialize()
        self.req=make_request(Image.new('RGB',(3,2)),sequence=1,epoch='epoch',generation=1,
            stamp=10,frame='optical',prompt='red mat',threshold=.5,budget_ms=200)
    def tearDown(self):self.backend.close()
    def create(self,**kw):
        f=self.fixture
        return HttpSam3Backend(kw.pop('endpoint',f.endpoint),f.root/'ca.crt',f.root/'client.crt',
                               f.root/'client.key',kw.pop('identity',f.expected),**kw)
    def guard(self,req=None):
        g=ResultGuard('epoch');g.register(req or self.req,time.monotonic()+1,time.monotonic()+1,object());return g
    def test_remote_factory_does_not_construct_local_runner(self):
        f=self.fixture
        with patch('sam3_backend.Sam3ModelRunner',side_effect=AssertionError('CUDA path used')):
            b=create_backend('http',checkpoint='/missing',prompt='red mat',threshold=.5,
                endpoint=f.endpoint,ca=f.root/'ca.crt',cert=f.root/'client.crt',key=f.root/'client.key',identity=f.root/'identity.json')
            b.initialize();b.close()
        self.assertNotIn('torch',sys.modules)
    def test_explicit_selection_and_complete_identity(self):
        with self.assertRaises(ValueError):create_backend('automatic',checkpoint='',prompt='',threshold=.5)
        for uri in ('http://localhost','https://user:pass@localhost','https://localhost/path'):
            with self.assertRaises(ValueError):self.create(endpoint=uri)
        with self.assertRaises(ValueError):self.create(identity={})
    def test_health_is_not_a_sensor_result(self):
        self.assertTrue(self.backend.initialized)
        self.assertEqual(self.guard().last_sequence,-1)
    def test_success_empty_and_correlation(self):
        g=self.guard();mask,_,_=g.accept(self.backend.predict(self.req));self.assertTrue(mask.any())
        self.fixture.mode='empty';mask,_,_=self.guard().accept(self.backend.predict(self.req));self.assertFalse(mask.any())
    def test_identity_mismatch_latches_until_restart(self):
        self.fixture.mode='wrong_deployment'
        with self.assertRaises(IdentityMismatch):self.backend.predict(self.req)
        self.fixture.mode='ok'
        with self.assertRaises(BackendFailure):self.backend.predict(self.req)
        with self.assertRaises(IdentityMismatch):self.backend.initialize()
    def test_wrong_initial_identity(self):
        self.fixture.mode='wrong_metadata';b=self.create()
        try:
            with self.assertRaises(IdentityMismatch):b.initialize()
        finally:b.close()
    def test_server_hostname_is_verified(self):
        b=self.create(endpoint=self.fixture.endpoint.replace('localhost','127.0.0.1'))
        try:
            with self.assertRaises(Exception):b.initialize()
            self.assertFalse(b.initialized)
        finally:b.close()
    def test_http_failures_are_not_empty_successes(self):
        for code in (401,403,429,500,503,504):
            self.fixture.mode=code
            with self.subTest(code=code),self.assertRaisesRegex(BackendFailure,str(code)):
                self.backend.predict(self.req)
    def test_network_loss_and_bad_framing(self):
        for mode in ('drop','truncated','oversized'):
            self.fixture.mode=mode
            with self.subTest(mode=mode),self.assertRaises(Exception):self.backend.predict(self.req)
        self.fixture.mode='ok';self.guard().accept(self.backend.predict(self.req))
    def test_slow_headers_and_hang_obey_total_deadline(self):
        for mode in ('drip_headers','hang'):
            self.fixture.mode=mode;t=time.monotonic()
            with self.assertRaises(Exception):self.backend.predict({**self.req,'budget_ms':80})
            self.assertLess(time.monotonic()-t,.4)
    def test_single_flight_no_hidden_retry(self):
        self.fixture.mode='delay';errors=[]
        def call():
            try:self.backend.predict(self.req)
            except Exception as e:errors.append(e)
        thread=threading.Thread(target=call);thread.start();self.assertTrue(self.fixture.entered.wait(1))
        count=len(self.fixture.requests)
        with self.assertRaisesRegex(BackendFailure,'already in flight'):self.backend.predict(self.req)
        self.assertEqual(len(self.fixture.requests),count);thread.join(1);self.assertFalse(thread.is_alive())
    def test_old_duplicate_and_reordered_responses_rejected(self):
        response=self.backend.predict(self.req);g=self.guard();g.accept(response)
        with self.assertRaises(ValueError):g.accept(response)
        for mode in ('replay','wrong_robot','wrong_sequence'):
            self.fixture.mode=mode;r=copy.deepcopy(self.req);r['identity'].update(request_id=mode,sequence=2)
            with self.subTest(mode=mode),self.assertRaises(ValueError):self.guard(r).accept(self.backend.predict(r))
    def test_reset_or_lost_depth_rejects_inflight_reply(self):
        response=self.backend.predict(self.req)
        for mode in ('reset','lost'):
            g=self.guard()
            if mode=='reset':g.reset('new',1)
            else:g.cancel(self.req['identity']['request_id'])
            with self.assertRaises(ValueError):g.accept(response)
    def test_dns_resolution_is_bounded_and_not_duplicated(self):
        release=threading.Event();calls=[]
        def stalled(*a,**kw):calls.append(1);release.wait(1);return []
        b=self.create(metadata_timeout=.04)
        try:
            with patch('http_backend.socket.getaddrinfo',side_effect=stalled):
                for _ in range(2):
                    t=time.monotonic()
                    with self.assertRaises(TimeoutError):b.initialize()
                    self.assertLess(time.monotonic()-t,.2)
                self.assertEqual(len(calls),1)
        finally:release.set();b.close()
    def test_close_interrupts_a_stalled_request(self):
        self.fixture.mode='hang';done=threading.Event()
        def call():
            try:self.backend.predict({**self.req,'budget_ms':1000})
            except Exception:pass
            finally:done.set()
        t=threading.Thread(target=call);t.start();self.assertTrue(self.fixture.entered.wait(1));self.backend.close()
        self.assertTrue(done.wait(.3));t.join()
