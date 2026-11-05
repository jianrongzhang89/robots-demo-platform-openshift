#!/usr/bin/env python3
"""Render G5 authenticated scraping and a Perses serving dashboard; no writes."""
import json


def render():
    ns = 'semantic-model-serving'
    def resource(api, kind, name, namespace=ns, **extra):
        return {'apiVersion':api, 'kind':kind, 'metadata':{'name':name, 'namespace':namespace}, **extra}
    monitor = resource('monitoring.coreos.com/v1', 'ServiceMonitor', 'sam3-g5-authenticated', spec={
        'selector': {'matchLabels':{'semantic-g5-monitor':'sam3'}},
        'endpoints':[{'port':'https', 'path':'/metrics', 'scheme':'https', 'interval':'15s', 'scrapeTimeout':'5s',
          'tlsConfig':{'serverName':'sam3-mat-v1-tls.semantic-model-serving.svc',
            'ca':{'secret':{'name':'sam3-g5-monitor-tls','key':'ca.crt'}},
            'cert':{'secret':{'name':'sam3-g5-monitor-tls','key':'tls.crt'}},
            'keySecret':{'name':'sam3-g5-monitor-tls','key':'tls.key'}}}]})
    policy = resource('networking.k8s.io/v1','NetworkPolicy','sam3-g5-monitor-ingress', spec={
        'podSelector':{'matchLabels':{'serving.kserve.io/inferenceservice':'sam3-mat-v1','component':'predictor'}},
        'policyTypes':['Ingress'], 'ingress':[{'from':[{
            'namespaceSelector':{'matchLabels':{'kubernetes.io/metadata.name':'openshift-user-workload-monitoring'}},
            'podSelector':{'matchLabels':{'prometheus':'user-workload'}}}],
            'ports':[{'protocol':'TCP','port':8443}]}]})
    scope = '{namespace="semantic-model-serving",service="sam3-mat-v1-tls"}'
    charts = [
        ('scrape','Authenticated scrape health','up'+scope,'decimal'),
        ('rate','Inference requests / second by status','sum by (status) (rate(semantic_requests_total'+scope+'[5m]))','decimal'),
        ('count','Inference outcomes since worker start','sum by (status) (semantic_requests_total'+scope+')','decimal'),
        ('ready','Worker ready','semantic_worker_ready'+scope,'decimal'),
        ('busy','Worker busy','semantic_worker_busy'+scope,'decimal'),
        ('backend','Candidate backend p95 (not capture latency)','histogram_quantile(0.95, sum by (le) (rate(semantic_backend_duration_seconds_bucket'+scope+'[5m])))','seconds'),
        ('admission','Candidate admission p95','histogram_quantile(0.95, sum by (le) (rate(semantic_admission_duration_seconds_bucket'+scope+'[5m])))','seconds'),
        ('queue','Candidate queue capacity (zero = immediate rejection)','semantic_queue_capacity'+scope,'decimal'),
        ('gpu','Serving GPU utilization','accelerator_gpu_utilization{exported_namespace="semantic-model-serving"}','percent'),
        ('memory','Serving GPU memory used','accelerator_memory_used_bytes{exported_namespace="semantic-model-serving"}','bytes'),
    ]
    panels = {}; items = []
    for index, (key,title,query,unit) in enumerate(charts):
        panels[key] = {'kind':'Panel','spec':{'display':{'name':title},
            'plugin':{'kind':'TimeSeriesChart','spec':{'visual':{'display':'line','connectNulls':False},'yAxis':{'format':{'unit':unit},'min':0}}},
            'queries':[{'kind':'TimeSeriesQuery','spec':{'plugin':{'kind':'PrometheusTimeSeriesQuery','spec':{
                'datasource':{'kind':'PrometheusDatasource','name':'cluster-prometheus-tenancy-datasource'},'query':query}}}}]}}
        items.append({'content':{'$ref':'#/spec/panels/'+key},'x':12*(index%2),'y':8*(index//2),'width':12,'height':8})
    panels['identity'] = {'kind':'Panel','spec':{'display':{'name':'Running image identity (pod inventory)'},
        'plugin':{'kind':'Table','spec':{'columnSettings':[{'name':'timestamp','hide':True},{'name':'image_id','header':'Image digest'}]}},
        'queries':[{'kind':'TimeSeriesQuery','spec':{'plugin':{'kind':'PrometheusTimeSeriesQuery','spec':{
            'datasource':{'kind':'PrometheusDatasource','name':'cluster-prometheus-tenancy-datasource'},
            'query':'kube_pod_container_info{namespace="semantic-model-serving",container="kserve-container"}'}}}}]}}
    items.append({'content':{'$ref':'#/spec/panels/identity'},'x':0,'y':40,'width':24,'height':8})
    navscope='{namespace="semantic-navigation",service="semantic-g5-navigation-metrics"}'
    navcharts=[('source','Navigation snapshot available','g5_navigation_snapshot_available'+navscope,'decimal'),
        ('capture','Wall age of last valid capture','time() - g5_navigation_last_capture_timestamp_seconds'+navscope,'seconds'),
        ('result','Last capture-to-result latency','g5_navigation_capture_to_result_seconds'+navscope,'seconds'),
        ('costmap_source','Applied costmap telemetry available','g5_navigation_costmap_available'+navscope,'decimal'),
        ('costmap','Capture-to-costmap (absent when not observed)','g5_navigation_capture_to_costmap_seconds'+navscope,'seconds'),
        ('rtf','Observed capture-stream RTF','g5_navigation_capture_stream_rtf'+navscope,'decimal'),
        ('armed','Semantic supervisor armed','g5_navigation_armed'+navscope,'decimal'),
        ('reason','Supervisor gate / stop reason','g5_navigation_stop_reason'+navscope,'decimal'),
        ('drops','Adapter work queue drops','g5_navigation_work_queue_drops'+navscope,'decimal'),
        ('safety_source','Safety status available','g5_navigation_safety_available'+navscope,'decimal')]
    for index,(key,title,query,unit) in enumerate(navcharts):
        key='navigation_'+key
        panels[key]={'kind':'Panel','spec':{'display':{'name':title},
            'plugin':{'kind':'TimeSeriesChart','spec':{'visual':{'display':'line','connectNulls':False},'yAxis':{'format':{'unit':unit},'min':0}}},
            'queries':[{'kind':'TimeSeriesQuery','spec':{'plugin':{'kind':'PrometheusTimeSeriesQuery','spec':{
                'datasource':{'kind':'PrometheusDatasource','name':'cluster-prometheus-tenancy-datasource'},'query':query}}}}]}}
        items.append({'content':{'$ref':'#/spec/panels/'+key},'x':12*(index%2),'y':48+8*(index//2),'width':12,'height':8})
    dashboard = resource('perses.dev/v1alpha2','PersesDashboard','semantic-g5-serving','redhat-ods-monitoring', spec={'config':{
        'display':{'name':'SAM3 G5 serving and navigation',
            'description':'G5 HOLD. Missing series mean unavailable, never healthy zero. Candidate histograms are absent on the accepted rollback image. Navigation data is passive operator telemetry; missing or stale sources are unavailable. Costmap latency is absent when the fixture does not expose applied updates. Evidence: https://github.com/jianrongzhang89/robots-demo-platform-openshift/tree/be091bd2/docs/validation/semantic-navigation/openshift-ai/S4'},
        'duration':'1h','panels':panels,'layouts':[{'kind':'Grid','spec':{'display':{'title':'Authenticated serving telemetry'},'items':items}}]}})
    dashboard['metadata']['labels'] = {'app.opendatahub.io/dashboard':'true'}
    return {'apiVersion':'v1','kind':'List','items':[monitor, policy, dashboard]}


if __name__ == '__main__':
    print(json.dumps(render(),indent=2))
