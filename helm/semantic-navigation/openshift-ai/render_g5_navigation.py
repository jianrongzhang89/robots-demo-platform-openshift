#!/usr/bin/env python3
"""Passive telemetry sink: no ROS, service-account token or actuator access."""
import json
from pathlib import Path
ROOT=Path(__file__).resolve().parents[3]

def render():
    ns='semantic-navigation';name='semantic-g5-navigation-metrics';labels={'app':name}
    image=json.loads((ROOT/'docs/validation/semantic-navigation/openshift-ai/S2/gate-result.json').read_text())['runtime_image']
    def obj(api,kind,spec=None,**extra):
        r={'apiVersion':api,'kind':kind,'metadata':{'name':name,'namespace':ns,'labels':labels},**extra}
        if spec is not None:r['spec']=spec
        return r
    return {'apiVersion':'v1','kind':'List','items':[
        obj('v1','ConfigMap',data={'exporter.py':(ROOT/'scripts/semantic-navigation/g5_navigation_metrics.py').read_text()}),
        obj('v1','Pod',{'automountServiceAccountToken':False,'containers':[{'name':'metrics','image':image,'command':['python3','/config/exporter.py'],'resources':{'requests':{'cpu':'10m','memory':'32Mi'},'limits':{'cpu':'100m','memory':'64Mi'}},'ports':[{'name':'metrics','containerPort':8080}],'securityContext':{'runAsNonRoot':True,'allowPrivilegeEscalation':False,'readOnlyRootFilesystem':True,'capabilities':{'drop':['ALL']},'seccompProfile':{'type':'RuntimeDefault'}},'volumeMounts':[{'name':'config','mountPath':'/config','readOnly':True},{'name':'tmp','mountPath':'/tmp'}]}],'volumes':[{'name':'config','configMap':{'name':name}},{'name':'tmp','emptyDir':{'sizeLimit':'8Mi'}}]}),
        obj('v1','Service',{'selector':labels,'ports':[{'name':'metrics','port':8080,'targetPort':'metrics'}]}),
        obj('networking.k8s.io/v1','NetworkPolicy',{'podSelector':{'matchLabels':labels},'policyTypes':['Ingress','Egress'],'egress':[],'ingress':[{'from':[{'namespaceSelector':{'matchLabels':{'kubernetes.io/metadata.name':'openshift-user-workload-monitoring'}},'podSelector':{'matchLabels':{'prometheus':'user-workload'}}}],'ports':[{'protocol':'TCP','port':8080}]}]}),
        obj('monitoring.coreos.com/v1','ServiceMonitor',{'selector':{'matchLabels':labels},'endpoints':[{'port':'metrics','interval':'5s','scrapeTimeout':'2s'}]})]}

if __name__=='__main__':print(json.dumps(render(),indent=2))
