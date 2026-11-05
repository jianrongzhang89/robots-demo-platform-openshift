"""Real-mTLS deterministic fault server for adapter tests; never model evidence."""
import copy
import hashlib
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import json
from pathlib import Path
import ssl
import subprocess
import tempfile
import threading
import time

import numpy as np
from inference_contract import POLICY, VERSIONS, MAX_WIRE_BYTES, success_response, validate_request


def identity():
    root = Path(__file__).resolve().parents[1]
    return {'schema':'semantic-deployment/v1','model_name':'sam3-mat-v1',
        'weights_sha256':'9'*64,'source_revision':'a'*40,'container_digest':'sha256:'+'b'*64,
        'shared_sha256':{f:hashlib.sha256((root/f).read_bytes()).hexdigest() for f in
                        ('sam3_backend.py','inference_contract.py','sam3_runtime_core.py')},
        'versions':VERSIONS,'precision':'bfloat16','policy':POLICY,'prompt':'red mat','threshold':.5}


class Fixture:
    def __init__(self):
        self.temp = tempfile.TemporaryDirectory(); self.root = Path(self.temp.name)
        def openssl(*args):
            subprocess.run(['openssl',*args],cwd=self.root,check=True,stdout=subprocess.DEVNULL,stderr=subprocess.DEVNULL)
        openssl('req','-x509','-newkey','rsa:2048','-nodes','-days','1','-subj','/CN=G2 Test CA',
                '-keyout','ca.key','-out','ca.crt','-addext','basicConstraints=critical,CA:TRUE',
                '-addext','keyUsage=critical,keyCertSign,cRLSign')
        for name,usage,san in [('server','serverAuth','DNS:localhost'),('client','clientAuth','URI:spiffe://g2/client')]:
            openssl('req','-newkey','rsa:2048','-nodes','-subj','/CN='+name,'-keyout',name+'.key','-out',name+'.csr')
            (self.root/'ext').write_text(f'basicConstraints=critical,CA:FALSE\nkeyUsage=critical,digitalSignature,keyEncipherment\nextendedKeyUsage={usage}\nsubjectAltName={san}\n')
            openssl('x509','-req','-in',name+'.csr','-CA','ca.crt','-CAkey','ca.key','-CAcreateserial',
                    '-days','1','-extfile','ext','-out',name+'.crt')
        self.expected = identity(); (self.root/'identity.json').write_text(json.dumps(self.expected))
        self.mode = 'ok'; self.delay = .3; self.last = None; self.entered = threading.Event()
        self.requests = []; self.active = 0; self.max_active = 0; self.lock = threading.Lock()
        fixture = self
        class Handler(BaseHTTPRequestHandler):
            def log_message(self,*args):pass
            def reply(self,code,body):
                data=json.dumps(body,separators=(',',':')).encode();self.send_response(code)
                self.send_header('Content-Length',str(len(data)));self.end_headers();self.wfile.write(data)
            def do_GET(self):
                deployment=copy.deepcopy(fixture.expected)
                if fixture.mode=='wrong_metadata':deployment['container_digest']='sha256:'+'c'*64
                self.reply(200,{'ready':True,'deployment':deployment})
            def do_POST(self):
                req=json.loads(self.rfile.read(int(self.headers['Content-Length'])));validate_request(req)
                with fixture.lock:
                    fixture.active+=1;fixture.max_active=max(fixture.active,fixture.max_active)
                    fixture.requests.append(copy.deepcopy(req['identity']))
                fixture.entered.set();mode=fixture.mode
                try:
                    if mode in ('delay','hang'):time.sleep(fixture.delay if mode=='delay' else 1.5)
                    if isinstance(mode,int):return self.reply(mode,{'status':'injected_error'})
                    if mode=='drop':self.connection.shutdown(2);return
                    if mode=='oversized':
                        self.send_response(200);self.send_header('Content-Length',str(MAX_WIRE_BYTES+1));self.end_headers();return
                    if mode=='drip_headers':
                        self.connection.sendall(b'HTTP/1.1 200 OK\r\nX-Test: ')
                        for _ in range(30):self.connection.sendall(b'x');time.sleep(.02)
                        return
                    if mode=='truncated':
                        self.send_response(200);self.send_header('Content-Length','1000');self.end_headers();self.wfile.write(b'{}');return
                    masks=np.zeros((1,req['height'],req['width'])) if mode=='empty' else np.ones((1,req['height'],req['width']))
                    response=success_response(req,masks,[.9]);response['deployment']=copy.deepcopy(fixture.expected)
                    if mode=='wrong_deployment':response['deployment']['weights_sha256']='0'*64
                    if mode=='wrong_robot':response['identity']['robot']='other'
                    if mode=='wrong_sequence':response['identity']['sequence']-=1
                    if mode=='replay' and fixture.last is not None:response=copy.deepcopy(fixture.last)
                    else:fixture.last=copy.deepcopy(response)
                    self.reply(200,response)
                except (OSError,ssl.SSLError):pass
                finally:
                    with fixture.lock:fixture.active-=1
        self.server=ThreadingHTTPServer(('127.0.0.1',0),Handler);self.server.daemon_threads=True
        tls=ssl.SSLContext(ssl.PROTOCOL_TLS_SERVER);tls.verify_mode=ssl.CERT_REQUIRED
        tls.load_cert_chain(self.root/'server.crt',self.root/'server.key');tls.load_verify_locations(self.root/'ca.crt')
        self.server.socket=tls.wrap_socket(self.server.socket,server_side=True)
        self.thread=threading.Thread(target=self.server.serve_forever,daemon=True);self.thread.start()
        self.endpoint=f'https://localhost:{self.server.server_port}'
    def close(self):
        self.server.shutdown();self.server.server_close();self.thread.join();self.temp.cleanup()
