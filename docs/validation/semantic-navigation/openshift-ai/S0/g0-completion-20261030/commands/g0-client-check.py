import ssl,http.client,json,socket
from PIL import Image
from inference_contract import make_request
host='sam3-mat-v1-tls.semantic-model-serving.svc';path='/v1/models/sam3-mat-v1'
def call(cert='cert',request=None,ip=False):
 c=ssl.create_default_context(cafile='/cert/ca.crt')
 if cert:c.load_cert_chain('/'+cert+'/tls.crt','/'+cert+'/tls.key')
 h=http.client.HTTPSConnection(socket.gethostbyname(host) if ip else host,8443,context=c,timeout=8)
 try:
  if request is None:h.request('GET',path)
  else:h.request('POST',path+':predict',body=json.dumps(request),headers={'Content-Type':'application/json'})
  r=h.getresponse();return {'code':r.status,'body':r.read().decode()}
 except ssl.SSLError as ex:return {'tls_rejected':True,'reason':str(ex)}
 finally:h.close()
r={'authorized_metadata':call(),'missing_certificate':call(None),'unbound_principal':call('unbound'),'wrong_server_identity':call(ip=True)}
req=make_request(Image.new('RGB',(3,2)),sequence=1,epoch='g0',generation=1,stamp=100,frame='optical',prompt='red mat',threshold=0.5,budget_ms=1000)
r['authorized_predict']=call(request=req);req['identity']['robot']='robot_2';r['spoofed_robot']=call(request=req)
r['passed']=r['authorized_metadata']['code']==503 and r['authorized_predict']['code']==503 and r['missing_certificate'].get('tls_rejected') and r['wrong_server_identity'].get('tls_rejected') and r['unbound_principal']['code']==403 and r['spoofed_robot']['code']==403
print(json.dumps(r,indent=2));assert r['passed']
