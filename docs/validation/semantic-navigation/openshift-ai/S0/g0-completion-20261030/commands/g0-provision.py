import json,sys,subprocess,importlib.util
from pathlib import Path
oc='/Users/zhangj/bin/oc'; ns='semantic-model-serving'
e=Path('docs/validation/semantic-navigation/openshift-ai/S0/g0-completion-20261030')
spec=importlib.util.spec_from_file_location('render','helm/semantic-navigation/openshift-ai/render.py');m=importlib.util.module_from_spec(spec);spec.loader.exec_module(m)
image=json.loads(Path('docs/validation/semantic-navigation/openshift-ai/S0/gate-result.json').read_text())['runtime_image']
r=m.render(image); pred=next(x for x in r['items'] if x['kind']=='InferenceService')['spec']['predictor'];pred['nodeSelector']['kubernetes.io/hostname']='ip-10-0-55-175.ec2.internal'
(e/'rendered-candidate.json').write_text(json.dumps(r,indent=2)+'\n')
items=[x for x in r['items'] if x['kind'] not in ('ServingRuntime','InferenceService')]
def obj(kind,name,spec=None,**kw):
 v={'apiVersion':'v1','kind':kind,'metadata':{'name':name,'namespace':ns},**kw}
 if spec is not None:v['spec']=spec
 return v
items += [obj('PersistentVolumeClaim','sam3-checkpoint',{'accessModes':['ReadWriteOnce'],'storageClassName':'gp3-csi','resources':{'requests':{'storage':'10Gi'}}}),obj('ResourceQuota','sam3-serving-budget',{'hard':{'requests.cpu':'8','requests.memory':'28Gi','limits.cpu':'16','limits.memory':'56Gi','requests.nvidia.com/gpu':'1','requests.storage':'10Gi','persistentvolumeclaims':'1','pods':'8'}})]
(e/'prerequisites.json').write_text(json.dumps({'apiVersion':'v1','kind':'List','items':items},indent=2)+'\n')
subprocess.run([oc,'apply','-f',str(e/'prerequisites.json')],check=True)
rb={'apiVersion':'rbac.authorization.k8s.io/v1','kind':'RoleBinding','metadata':{'name':'sam3-serving-image-puller','namespace':'semantic-navigation'},'roleRef':{'apiGroup':'rbac.authorization.k8s.io','kind':'ClusterRole','name':'system:image-puller'},'subjects':[{'kind':'ServiceAccount','name':'sam3-serving','namespace':ns}]}
(e/'image-pull-rolebinding.json').write_text(json.dumps(rb,indent=2)+'\n');subprocess.run([oc,'apply','-f',str(e/'image-pull-rolebinding.json')],check=True)
c=next(x for x in r['items'] if x['kind']=='ServingRuntime')['spec']['containers'][0]
pod=obj('Pod','sam3-g0-reservation',{'serviceAccountName':'sam3-serving','automountServiceAccountToken':False,'restartPolicy':'Never','nodeSelector':pred['nodeSelector'],'tolerations':pred['tolerations'],'containers':[{'name':'reservation','image':image,'command':['/opt/sam3-venv/bin/python','-u','-c'],'args':['import torch,json,time; print(json.dumps({"gpu":torch.cuda.get_device_name(),"cuda":torch.version.cuda,"torch":torch.__version__,"bf16":torch.cuda.is_bf16_supported()}),flush=True); time.sleep(604800)'],'resources':c['resources'],'securityContext':{**c['securityContext'],'readOnlyRootFilesystem':False},'volumeMounts':[{'name':'model','mountPath':'/models'}]}],'volumes':[{'name':'model','persistentVolumeClaim':{'claimName':'sam3-checkpoint'}}]})
(e/'reservation-pod.json').write_text(json.dumps(pod,indent=2)+'\n');subprocess.run([oc,'create','-f',str(e/'reservation-pod.json')],check=True)
