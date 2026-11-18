#!/usr/bin/env python3
"""Independently audit one integrated warehouse SAM3/costmap route trial."""
import argparse
import json
import re
from bisect import bisect_left
from pathlib import Path

import numpy as np
import yaml
from PIL import Image


def audit(trial: Path, baseline_nav2: Path):
    errors=[]
    result=json.loads((trial/'result.json').read_text())
    design=json.loads((trial/'design.json').read_text())
    candidate=yaml.safe_load((trial/'nav2.yaml').read_text())
    baseline=yaml.safe_load(baseline_nav2.read_text())
    semantic=design.get('semantic_fixture',{})
    if result.get('status')!='PASS':errors.append('RMF/Nav2 route did not complete successfully')
    if not semantic.get('enabled'):errors.append('semantic warehouse fixture is disabled')
    policy=result.get('semantic',{}).get('label_info') or {}
    if (policy.get('policy')!='avoid-target/v1' or policy.get('prompt')!='red mat' or
        policy.get('active_labels')!=[0,2]):errors.append('SAM3 policy/label metadata mismatch')
    status=result.get('semantic',{}).get('status') or {}
    if status.get('backend')!='http' or not status.get('ready') or not status.get('capture_trace_required'):
        errors.append('pinned HTTP SAM3 backend or source trace is not ready')
    if not result.get('semantic',{}).get('nonempty_target_masks'):
        errors.append('SAM3 emitted no avoid_target pixels')
    if not result.get('semantic',{}).get('saved_rgb_mask_pairs'):
        errors.append('no nonempty mask is paired with its RGB capture')

    params=candidate['global_costmap']['global_costmap']['ros__parameters']
    base_global=baseline['global_costmap']['global_costmap']['ros__parameters']
    layer=params.get('semantic_layer',{})
    if (layer.get('plugin')!='demo_semantic_costmap::SemanticLayer' or
        layer.get('target_cost')!=254 or layer.get('enabled') is not True):
        errors.append('global semantic costmap is not active at lethal cost 254')
    if 'semantic_layer' in candidate['local_costmap']['local_costmap']['ros__parameters'].get('plugins',[]):
        errors.append('semantic layer unexpectedly loaded into the local controller costmap')
    for key in ('controller_server','planner_server','bt_navigator','local_costmap'):
        if candidate.get(key)!=baseline.get(key):errors.append(f'{key} safety/navigation settings changed')
    if [x for x in params.get('plugins',[]) if x!='semantic_layer']!=base_global.get('plugins',[]):
        errors.append('global costmap plugin order changed outside the semantic layer insertion')
    for key,value in base_global.items():
        if key=='plugins':continue
        if params.get(key)!=value:errors.append(f'global costmap parameter {key} changed')

    timing=(trial/'semantic-timing.jsonl').read_text().splitlines()
    if not timing:errors.append('semantic timing trace is missing')
    if any(json.loads(row).get('source',{}).get('schema')!='semantic-capture/v1' for row in timing):
        errors.append('semantic result lacks simulator capture receipt provenance')
    navlog=(trial/'nav2.log').read_text(errors='replace')
    accepted=[int(x) for x in re.findall(r'semantic observation accepted=(\d+)',navlog)]
    projected=[int(x) for x in re.findall(r'projected=(\d+)',navlog)]
    if not accepted or max(accepted,default=0)==0:errors.append('semantic costmap accepted no observation')
    if not projected or max(projected,default=0)==0:errors.append('semantic costmap projected no lethal cells')

    physical=sorted((json.loads(line) for line in (trial/'physical.jsonl').read_text().splitlines()),
                    key=lambda row:row['sim_s'])
    times=[row['sim_s'] for row in physical]
    target=next((x for x in semantic.get('targets',[]) if x.get('expected_label')=='avoid_target'),None)
    mask_rows=[json.loads(line) for line in (trial/'semantic-masks.jsonl').read_text().splitlines()]
    positives=[]
    for row in mask_rows:
        if not row.get('target_pixels'):continue
        i=bisect_left(times,row['stamp_s'])
        near=min(physical[max(0,i-1):min(len(physical),i+1)],key=lambda x:abs(x['sim_s']-row['stamp_s']))
        positives.append(near)
    if target:
        tx,ty=target['center'][:2]
        if any(np.hypot(row['x']-tx,row['y']-ty)>4.0 for row in positives):
            errors.append('nonempty SAM3 masks occurred away from the red target approach')

    precision=[];coverage=[]
    pair_dir=trial/'semantic-label-pairs'
    for mask_path in sorted(pair_dir.glob('*-mask.png')):
        rgb_path=mask_path.with_name(mask_path.name.replace('-mask.png','-rgb.png'))
        if not rgb_path.exists():continue
        rgb=np.asarray(Image.open(rgb_path).convert('RGB'))
        mask=np.asarray(Image.open(mask_path))>0
        red=(rgb[:,:,0]>rgb[:,:,1]*1.35)&(rgb[:,:,0]>rgb[:,:,2]*1.35)&(rgb[:,:,0]>50)
        overlap=int((mask&red).sum())
        if mask.any():
            precision.append(overlap/int(mask.sum()))
            coverage.append(overlap/int(red.sum()) if red.any() else 0.0)
    if not precision or min(precision)<.95 or min(coverage)<.95:
        errors.append('paired semantic masks do not consistently overlap the visible red pixels')

    max_plan=float(result.get('maximum_plan_centerline_distance_m',999))
    max_physical=max((float(row.get('corridor_distance_m',999)) for row in physical),default=999)
    if max_plan>.70 or max_physical>.40:errors.append('detour exceeded the surveyed corridor or physical guard')
    if any(goal.get('status')!=4 for goal in result.get('nav2_goals',[])):
        errors.append('one or more Nav2 route goals failed')

    report={'status':'FAIL' if errors else 'PASS','errors':errors,
        'scope':f"one simulated {design.get('route')}-{design.get('direction')} semantic obstacle/distractor route; no physical electrical calibration",
        'route':design.get('route'),'direction':design.get('direction'),
        'task_id':result.get('task_id'),'prompt':policy.get('prompt'),'policy':policy.get('policy'),
        'active_labels':policy.get('active_labels'),'target_cost':layer.get('target_cost'),
        'costmap_accepted_count_max':max(accepted,default=0),
        'costmap_projected_cells_max':max(projected,default=0),
        'nonempty_target_masks':result.get('semantic',{}).get('nonempty_target_masks'),
        'mask_samples':result.get('semantic',{}).get('mask_samples'),
        'saved_rgb_mask_pairs':result.get('semantic',{}).get('saved_rgb_mask_pairs'),
        'mask_red_pixel_precision_min_mean':[min(precision,default=0),float(np.mean(precision)) if precision else 0],
        'mask_red_pixel_coverage_min_mean':[min(coverage,default=0),float(np.mean(coverage)) if coverage else 0],
        'nonzero_mask_robot_x_range':[min((r['x'] for r in positives),default=None),
                                      max((r['x'] for r in positives),default=None)],
        'max_plan_centerline_distance_m':max_plan,'max_physical_corridor_distance_m':max_physical,
        'nav2_goal_statuses':[goal.get('status') for goal in result.get('nav2_goals',[])],
        'rgb_hz':result.get('rgbd',{}).get('rgb_rate',{}).get('average_hz'),
        'depth_hz':result.get('rgbd',{}).get('depth_rate',{}).get('average_hz')}
    return report


if __name__=='__main__':
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('trial',type=Path)
    parser.add_argument('--baseline-nav2',type=Path,required=True)
    parser.add_argument('--output',type=Path)
    args=parser.parse_args();report=audit(args.trial,args.baseline_nav2)
    if args.output:args.output.write_text(json.dumps(report,indent=2)+'\n')
    print(json.dumps(report));raise SystemExit(report['status']!='PASS')
