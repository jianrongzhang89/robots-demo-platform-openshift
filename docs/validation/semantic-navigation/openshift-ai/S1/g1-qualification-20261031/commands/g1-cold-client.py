import http.client,ssl,socket,time,json,sys
host='sam3-mat-v1-tls.semantic-model-serving.svc';ip=sys.argv[1];ctx=ssl.create_default_context(cafile='/cert/ca.crt');ctx.load_cert_chain('/cert/tls.crt','/cert/tls.key')
class Direct(http.client.HTTPSConnection):
 def connect(self):self.sock=ctx.wrap_socket(socket.create_connection((ip,8443),timeout=2),server_hostname=host)
start=time.monotonic();samples=[];last=None
while time.monotonic()-start<360:
 c=Direct(host,8443,context=ctx,timeout=2)
 try:
  c.request('GET','/v1/models/sam3-mat-v1');r=c.getresponse();body=json.loads(r.read());code=r.status
  row={'seconds':round(time.monotonic()-start,3),'http_status':code,'ready':body.get('ready'),'has_identity':body.get('deployment') is not None}
  samples.append(row)
  if code==200:
   print(json.dumps({'passed':any(s.get('http_status')==503 and s.get('ready') is False and not s.get('has_identity') for s in samples) and body['ready'] and body['deployment'] is not None,'first_ready_seconds':row['seconds'],'samples':samples,'deployment':body['deployment']},indent=2));break
 except Exception as ex:samples.append({'seconds':round(time.monotonic()-start,3),'error':type(ex).__name__})
 finally:c.close()
 time.sleep(.25)
else:
 print(json.dumps({'passed':False,'samples':samples,'reason':'not ready within 360 seconds'},indent=2));sys.exit(1)
