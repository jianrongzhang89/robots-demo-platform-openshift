from http.client import HTTPSConnection
import json
from pathlib import Path
import ssl
import subprocess
import tempfile
import threading
import unittest

from phase7_operator_api import create_operator_server, certificate_common_name


class DummyController:
    def __init__(self): self.requests=[]
    def transition(self, request):
        self.requests.append(request)
        return {'prompt':request['prompt'],'generation':2,'resumed':False}


class MutualTlsOperatorApiTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name)
        def openssl(*args):
            subprocess.run(['openssl', *args], cwd=self.root, check=True,
                           stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        openssl('req','-x509','-newkey','rsa:2048','-nodes','-days','1',
            '-subj','/CN=Phase7 Test CA','-keyout','ca.key','-out','ca.crt',
            '-addext','basicConstraints=critical,CA:TRUE',
            '-addext','keyUsage=critical,keyCertSign,cRLSign')
        for name, usage, san in [('server','serverAuth','DNS:localhost'),
                                 ('operator-17','clientAuth','URI:spiffe://operator-17'),
                                 ('untrusted','clientAuth','URI:spiffe://untrusted')]:
            openssl('req','-newkey','rsa:2048','-nodes','-subj',f'/CN={name}',
                '-keyout',f'{name}.key','-out',f'{name}.csr')
            (self.root/'ext').write_text(
                f'basicConstraints=critical,CA:FALSE\nkeyUsage=critical,digitalSignature,keyEncipherment\n'
                f'extendedKeyUsage={usage}\nsubjectAltName={san}\n')
            openssl('x509','-req','-in',f'{name}.csr','-CA','ca.crt','-CAkey','ca.key',
                '-CAcreateserial','-days','1','-extfile','ext','-out',f'{name}.crt')
        self.controller = DummyController()
        self.server = create_operator_server(controller=self.controller,
            host='127.0.0.1',port=0,server_cert=self.root/'server.crt',
            server_key=self.root/'server.key',client_ca=self.root/'ca.crt',
            authorized_operators={'operator-17':'private-operator-credential'})
        self.thread = threading.Thread(target=self.server.serve_forever,daemon=True)
        self.thread.start()

    def tearDown(self):
        self.server.shutdown(); self.server.server_close(); self.thread.join()
        self.tmp.cleanup()

    def request(self, *, client_cert='operator-17.crt', body=None):
        context=ssl.create_default_context(cafile=str(self.root/'ca.crt'))
        context.load_cert_chain(str(self.root/client_cert),
                                str(self.root/client_cert.replace('.crt','.key')))
        conn=HTTPSConnection('localhost',self.server.server_port,context=context,timeout=3)
        payload=json.dumps({'prompt':'blue crate'} if body is None else body)
        conn.request('POST','/v1/prompt-transitions',body=payload,
                     headers={'Content-Type':'application/json'})
        response=conn.getresponse(); data=response.read(); conn.close()
        return response.status,json.loads(data)

    def test_authorized_client_certificate_maps_to_operator_request(self):
        status,payload=self.request()
        self.assertEqual(status,200)
        self.assertEqual(payload['result']['generation'],2)
        self.assertEqual(self.controller.requests,[{'action':'change_prompt',
            'token':'private-operator-credential','prompt':'blue crate',
            'operator_id':'operator-17'}])

    def test_unmapped_certificate_and_invalid_request_never_reach_controller(self):
        status,_=self.request(client_cert='untrusted.crt')
        self.assertEqual(status,403)
        status,_=self.request(body={'prompt':'blue crate','token':'forged'})
        self.assertEqual(status,400)
        self.assertEqual(self.controller.requests,[])

    def test_certificate_name_must_be_unambiguous(self):
        self.assertIsNone(certificate_common_name(None))
        self.assertIsNone(certificate_common_name({'subject':((('commonName','a'),
                                                               ('commonName','b')) ,)}))
        self.assertEqual(certificate_common_name({'subject':((('commonName','operator-17'),),)}),
                         'operator-17')


if __name__ == '__main__':
    unittest.main()
