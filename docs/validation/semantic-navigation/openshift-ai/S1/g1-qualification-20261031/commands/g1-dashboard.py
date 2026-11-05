import json,subprocess,ssl,urllib.request,urllib.error
from pathlib import Path
oc='/Users/zhangj/bin/oc';p=Path('docs/validation/semantic-navigation/openshift-ai/S1/g1-qualification-20261031')
token=subprocess.check_output([oc,'whoami','-t'],text=True).strip()
host=subprocess.check_output([oc,'get','route','rhods-dashboard','-n','redhat-ods-applications','-o','jsonpath={.spec.host}'],text=True).strip()
ctx=ssl.create_default_context();results={}
for name,path in [('project-list','/api/k8s/apis/project.openshift.io/v1/projects?labelSelector=opendatahub.io%2Fdashboard%3Dtrue&fieldSelector=metadata.name%3Dsemantic-model-serving'),('namespace','/api/k8s/api/v1/namespaces/semantic-model-serving'),('inferenceservices','/api/k8s/apis/serving.kserve.io/v1beta1/namespaces/semantic-model-serving/inferenceservices'),('servingruntimes','/api/k8s/apis/serving.kserve.io/v1alpha1/namespaces/semantic-model-serving/servingruntimes')]:
 try:
  req=urllib.request.Request('https://'+host+path,headers={'Authorization':'Bearer '+token,'Accept':'application/json'})
  with urllib.request.urlopen(req,context=ctx,timeout=30) as resp:
   raw=resp.read();data=json.loads(raw);(p/f'dashboard-{name}.json').write_text(json.dumps(data,indent=2)+'\n');results[name]={'http_status':resp.status,'url':'https://'+host+path,'returned_names':[v['metadata']['name'] for v in data.get('items',[data])]}
 except Exception as exc:results[name]={'error_type':type(exc).__name__,'reason':str(exc)[:250]}
(p/'dashboard-api-results.json').write_text(json.dumps(results,indent=2)+'\n');print(json.dumps(results,indent=2))
