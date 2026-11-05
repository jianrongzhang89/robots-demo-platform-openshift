#!/usr/bin/env python3
"""Loopback-only G4 mTLS fault injector; healthy calls reach the pinned model.

Used only for fault qualification, never for the nominal paired series.
HTTP failure modes are explicit response injections, not claims of changing
production auth/admission policy. Each prediction records the active mode.
"""
import http.client
from concurrent.futures import ThreadPoolExecutor
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import json
from pathlib import Path
import socket
import ssl
import threading
import time

MODES = ('healthy', 'serving', 'network', 'auth', 'overload', 'hang', 'wrong_version')
MODE = Path('/tmp/g4-fault-mode')
EVENTS = Path('/tmp/g4-proxy-events.jsonl')
UPSTREAM = 'sam3-mat-v1-tls.semantic-model-serving.svc'
LOCK = threading.Lock()


def response_fault(mode, code, body):
    if mode == 'serving':
        return 503, json.dumps({'error':'g4_injected_'+mode}).encode()
    if mode == 'wrong_version' and code == 200:
        data=json.loads(body)
        data['deployment']['versions']['model']='g4-injected-wrong-version'
        return code, json.dumps(data).encode()
    return code, body


class Handler(BaseHTTPRequestHandler):
    protocol_version='HTTP/1.1'
    def log_message(self,*args): pass
    def handle_request(self):
        self.connection.settimeout(3)
        self.connection.setsockopt(socket.IPPROTO_TCP, socket.TCP_NODELAY, 1)
        mode=MODE.read_text().strip() if MODE.exists() else 'healthy'
        if mode not in MODES: mode='serving'
        prediction=self.command=='POST'
        if not prediction: mode='healthy'
        event={'wall_ns':time.time_ns(),'mode':mode,'method':self.command,'path':self.path}
        try:
            size=int(self.headers.get('Content-Length','0'))
            if not 0<=size<=16*1024*1024: raise ValueError('request too large')
            body_started=time.monotonic_ns()
            if hasattr(socket, 'TCP_QUICKACK'):
                self.connection.setsockopt(socket.IPPROTO_TCP,socket.TCP_QUICKACK,1)
            body=self.rfile.read(size)
            event['body_read_ms']=(time.monotonic_ns()-body_started)/1e6
            if prediction and mode=='network':
                self.connection.shutdown(socket.SHUT_RDWR); self.close_connection=True; return
            if prediction and mode=='hang':
                time.sleep(1.5); self.close_connection=True; return
            if prediction and mode=='auth':
                request=json.loads(body)
                request['identity']['robot']='g4_unauthorized_robot'
                body=json.dumps(request).encode()
            def forward():
                conn=http.client.HTTPSConnection(UPSTREAM,8443,context=self.server.upstream_context,timeout=1)
                try:
                    conn.request(self.command,self.path,body,{'Content-Type':'application/json','Connection':'close'})
                    reply=conn.getresponse(); status=reply.status
                    size=int(reply.getheader('Content-Length','-1'))
                    if not 0<=size<=28*1024*1024: raise ValueError('response too large')
                    output=bytearray()
                    while len(output)<size:
                        chunk=reply.read1(min(65536,size-len(output)))
                        if not chunk:raise ValueError('truncated response')
                        output.extend(chunk)
                    output=bytes(output)
                    return status, output
                finally: conn.close()
            if mode=='serving':
                code,output=response_fault(mode,200,b'{}')
            elif mode=='overload':
                # Two simultaneous real requests exercise the server's single
                # admission slot. Only its real 429 is delivered to the adapter.
                barrier=threading.Barrier(2)
                def competing():
                    barrier.wait(timeout=1)
                    return forward()
                with ThreadPoolExecutor(max_workers=2) as pool:
                    futures=[pool.submit(competing) for _ in range(2)]
                    replies=[f.result() for f in futures]
                event['upstream_statuses']=[r[0] for r in replies]
                rejected=next((r for r in replies if r[0]==429),None)
                if rejected is None: raise RuntimeError('overload injection did not obtain real 429')
                code,output=rejected
            else:
                code,output=forward()
                event['upstream_status']=code
                code,output=response_fault(mode,code,output)
            event['status']=code
            self.send_response(code);self.send_header('Content-Type','application/json')
            self.send_header('Content-Length',str(len(output)));self.send_header('Connection','close');self.end_headers()
            self.wfile.write(output);self.close_connection=True
        except Exception as exc:
            event['error']=type(exc).__name__;self.close_connection=True
        finally:
            event['finished_wall_ns']=time.time_ns()
            with LOCK:
                with EVENTS.open('a') as f:f.write(json.dumps(event)+'\n')
    do_GET=handle_request
    do_POST=handle_request


if __name__=='__main__':
    server=ThreadingHTTPServer(('127.0.0.1',9443),Handler,bind_and_activate=False)
    # Loopback's large MSS combines badly with the pinned client's TLS
    # writes and delayed ACKs. Match ordinary network segmentation without
    # changing the approved adapter or any inference deadline.
    server.socket.setsockopt(socket.IPPROTO_TCP,socket.TCP_MAXSEG,1440)
    server.server_bind();server.server_activate()
    server.upstream_context=ssl.create_default_context(cafile='/cert/ca.crt')
    server.upstream_context.load_cert_chain('/cert/tls.crt','/cert/tls.key')
    ctx=ssl.SSLContext(ssl.PROTOCOL_TLS_SERVER)
    ctx.load_cert_chain('/proxy-tls/tls.crt','/proxy-tls/tls.key')
    ctx.load_verify_locations('/cert/ca.crt');ctx.verify_mode=ssl.CERT_REQUIRED
    server.socket=ctx.wrap_socket(server.socket,server_side=True)
    server.serve_forever()
