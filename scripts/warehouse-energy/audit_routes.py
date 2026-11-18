#!/usr/bin/env python3
"""Replay raw schedule, goal and physical records independently of the live monitor."""
import argparse
import csv
import json
import math
from pathlib import Path


def read_rows(path):
    return [json.loads(line) for line in path.read_text().splitlines()]


def segment_distance(point,a,b):
    dx,dy=b[0]-a[0],b[1]-a[1]
    ratio=max(0.,min(1.,((point[0]-a[0])*dx+(point[1]-a[1])*dy)/(dx*dx+dy*dy)))
    return math.hypot(point[0]-a[0]-ratio*dx,point[1]-a[1]-ratio*dy)


def audit(directory):
    design=json.loads((directory/'design.json').read_text())
    reported=json.loads((directory/'result.json').read_text())
    request=json.loads((directory/'task-request.json').read_text())
    physics=read_rows(directory/'physical.jsonl');events=read_rows(directory/'adapter-events.jsonl')
    mirror=read_rows(directory/'schedule-mirror.jsonl');plans=read_rows(directory/'plans.jsonl')
    itinerary=read_rows(directory/'itineraries.jsonl')
    errors=[]
    def require(condition,reason):
        if not condition:errors.append(reason)
    path=design['path'];nodes=design['nodes'];edges=[(nodes[a],nodes[b]) for a,b in zip(path,path[1:])]
    destinations=[p['activity']['description']['one_of'][0]['waypoint'] for p in request['request']['description']['phases']]
    require(destinations==path[1:],'dispatched destinations differ from selected route')
    require(request['request']['fleet_name']=='warehouse_energy','wrong fleet')
    require(reported['response']['success'] and reported['task_id']==reported['response']['state']['booking']['id'],
            'missing correlated dispatch response')
    # The callback record comes from the completed NavigateToPose future, including its real goal UUID.
    terminals=[e for e in events if e['event']=='nav2_terminal']
    require(terminals and all(e['status']==4 and len(e.get('goal_id') or '')==32 for e in terminals),
            'missing or failed Nav2 goal results')
    require(len({e['goal_id'] for e in terminals})==len(terminals),'duplicate terminal goal UUID')
    for targets,label,radius in [([[e['x'],e['y']] for e in physics],'physical',.2),
                                ([e['target'][:2] for e in terminals],'Nav2',.01)]:
        expected=path if label=='physical' else path[1:];cursor=0
        for point in targets:
            if cursor<len(expected) and math.dist(point,nodes[expected[cursor]][:2])<radius:cursor+=1
        require(cursor==len(expected),f'{label} ordered route incomplete')
    accepted=[point for update in mirror for participant in update['participants']
              for route in participant['routes'] for point in route['points']]
    submitted=[point for row in itinerary for route in row['routes'] for point in route['points']]
    planned=[point for row in plans for point in row['xy']]
    require(all(math.isfinite(float(r[k])) for r in physics for k in ['sim_s','x','y','z','roll','pitch']),
            'nonfinite physical evidence')
    require(all(math.isfinite(float(v)) for p in accepted+submitted+planned for v in p),
            'nonfinite schedule/path evidence')
    distances={}
    for label,points in [('schedule',accepted),('itinerary',submitted),('Nav2_plan',planned),
                         ('physical',[[r['x'],r['y']] for r in physics])]:
        maximum=max((min(segment_distance(p,a,b) for a,b in edges) for p in points),default=999)
        distances[label]=maximum
        require(maximum<=(.4 if label=='physical' else .71),f'{label} missing or outside corridor')
        if label in ['schedule','itinerary']:
            for name in path[1:]:
                require(any(math.dist(p[:2],nodes[name][:2])<.15 for p in points),f'{label} missing {name}')
    require(all(p.get('fault') is None for p in physics),'physical monitor fault')
    require(all(abs(p['roll'])<=.12 and abs(p['pitch'])<=.1 for p in physics),'physical attitude bound')
    require(all(abs(p['support_error_m'])<=.06 for p in physics),'physical support bound')
    require(all(a['sim_s']<b['sim_s'] for a,b in zip(physics,physics[1:])),'physical clock regression')
    require(physics and math.dist([physics[-1]['x'],physics[-1]['y']],nodes[path[-1]][:2])<.12,'final physical endpoint')
    fleet=reported['final_fleet']
    require(fleet and not fleet['task_id'] and fleet['mode']==0,'fleet not idle')
    require(reported['status']=='PASS','live runner did not pass')
    with (directory/'torque.csv').open() as stream:
        torque=list(csv.DictReader(stream))
    require(all(math.isfinite(float(r[k])) for r in torque for k in ['sim_s','left_nm','right_nm']),
            'nonfinite actuator evidence')
    peak=max((abs(float(r[k])) for r in torque for k in ['left_nm','right_nm']),default=0)
    require(1e-6<peak<=.080001,'missing/beyond-limit actuator effort')
    require(torque and all(abs(float(torque[-1][k]))<.2 for k in ['left_rad_s','right_rad_s']),
            'physical wheels not stopped at completion')
    return {'status':'FAIL' if errors else 'PASS','errors':errors,'task_id':reported['task_id'],
        'route':design['route'],'direction':design['direction'],'payload_kg':design['payload_kg'],
        'successful_nav2_goals':len(terminals),'physical_samples':len(physics),
        'accepted_schedule_updates':len(mirror),'maximum_centerline_distance_m':distances,
        'peak_torque_nm':peak,'final_distance_m':math.dist([physics[-1]['x'],physics[-1]['y']],nodes[path[-1]][:2])}


if __name__=='__main__':
    p=argparse.ArgumentParser();p.add_argument('series',type=Path);p.add_argument('--output',type=Path,required=True)
    args=p.parse_args();rows=[audit(args.series/f'{route}-{direction}') for route in ['A','B'] for direction in ['up','down']]
    result={'status':'PASS' if all(r['status']=='PASS' for r in rows) else 'FAIL','trials':rows}
    args.output.write_text(json.dumps(result,indent=2)+'\n');print(json.dumps(result))
    raise SystemExit(result['status']!='PASS')
