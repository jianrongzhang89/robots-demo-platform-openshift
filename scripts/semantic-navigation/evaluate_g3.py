#!/usr/bin/env python3
"""Assess fixed G3 thresholds, preserving raw timing tails and drop counts."""
import argparse
import json
from pathlib import Path


def evaluate(capture, costmap, duration=600):
    c=capture['counts'];pairing=c['paired']/max(1,c['mask'],c['cloud'])
    checks={'duration':capture['duration_s']>=duration,
      'fresh_rate':capture['outputs_within_500ms_per_s']>=5,
      'capture_result_p95':capture['capture_age_upper_ms']['p95']<=250,
      'validated_consumer_p95':capture['observer_pair_capture_age_upper_ms'].get('p95',float('inf'))<=250,
      'pairing':pairing>=.95,'no_wrong_pairs':c['invalid']==0 and capture['identity_errors']==0 and capture['age_errors']==0 and capture['order_errors']==0 and capture.get('payload_binding_errors', 1)==0,
      'publication_gaps':capture['gaps_over_500ms']==0,
      'global_costmap_p95':costmap['maps']['global_semantic']['capture_to_costmap_ms']['p95'] is not None and costmap['maps']['global_semantic']['capture_to_costmap_ms']['p95']<=300,
      'local_costmap_p95':costmap['maps']['local_semantic']['capture_to_costmap_ms']['p95'] is not None and costmap['maps']['local_semantic']['capture_to_costmap_ms']['p95']<=300,
      'bounded_costmap_buffers':all(m['pending_max']<=8 and m['cells_max']<=65536 for m in costmap['maps'].values()),
      'bounded_adapter_buffers':all(r['status']['work_queue_depth']<=1 and max(r['status']['input_queue_depths'].values())<=20 and r['status']['backend_in_flight']<=1 for r in capture['resources'])}
    memory=[r['container_memory_bytes'] for r in capture['resources']]
    checks['memory_limit']=max(memory)<2*1024**3
    return {'status':'PASS' if all(checks.values()) else 'FAIL','checks':checks,'pairing_fraction':pairing,
      'fresh_results_per_s':capture['outputs_within_500ms_per_s'],'capture_result_ms':capture['capture_age_upper_ms'],
      'observer_pair_ms':capture['observer_pair_capture_age_upper_ms'],'publication_gap_ms':capture['publication_gap_ms'],
      'gaps_over_500ms':capture['gaps_over_500ms'],'costmaps':costmap['maps'],'memory_bytes':{'first':memory[0],'last':memory[-1],'min':min(memory),'max':max(memory)},
      'drops':{k:capture['final_status'][k]-capture['initial_status'][k] for k in ('input_queue_drops','work_queue_drops','work_wait_drops','trace_errors')},'stages_ms':capture['stages_ms']}

if __name__=='__main__':
    p=argparse.ArgumentParser(description=__doc__);p.add_argument('--capture',type=Path,required=True);p.add_argument('--costmap',type=Path,required=True);p.add_argument('--output',type=Path,required=True);p.add_argument('--duration',type=float,default=600);a=p.parse_args()
    result=evaluate(json.loads(a.capture.read_text()),json.loads(a.costmap.read_text()),a.duration)
    a.output.write_text(json.dumps(result,indent=2)+'\n');print(json.dumps(result,indent=2))
