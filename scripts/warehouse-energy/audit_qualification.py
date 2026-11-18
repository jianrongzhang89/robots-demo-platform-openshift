#!/usr/bin/env python3
"""Independently recheck raw ramp traces; do not trust runner PASS flags."""
import argparse
import csv
import itertools
import json
import math
from pathlib import Path
import xml.etree.ElementTree as ET


def ground_height(x,run):
    # Frozen 1 m cosine entry/exit transition, 0.2 m rise.
    if x<=0:return 0.
    if x>=run:return .2
    grade=.2/(run-1)
    if x<1:return grade*(x/2-math.sin(math.pi*x)/(2*math.pi))
    if x>run-1:return .2-ground_height(run-x,run)
    return grade*(x-.5)


def audit_trial(directory):
    errors=[]
    def require(condition,message):
        if not condition:errors.append(message)
    design=json.loads((directory/'design.json').read_text())
    rows=[json.loads(line) for line in (directory/'physics.jsonl').read_text().splitlines()]
    with (directory/'torque.csv').open() as stream:
        torque=list(csv.DictReader(stream))
    require(len(rows)>100,'too few pose observations')
    require(len(torque)>100,'too few actuator observations')
    run=design['run_m'];direction=design['direction']
    require(run=={'A':10,'B':20}[design['route']],'unexpected ramp run')
    require(design['payload_kg'] in [0,.25,.5],'unexpected payload')
    require(all(math.isfinite(float(row[k])) for row in rows
                for k in ['sim_s','x','y','z','roll','pitch','yaw']),'nonfinite physical evidence')
    require(all(a['sim_s']<b['sim_s'] for a,b in zip(rows,rows[1:])),'clock regression')
    require(max((b['sim_s']-a['sim_s'] for a,b in zip(rows,rows[1:])),default=999)<.5,'physical sample gap')
    active=[r for r in rows if r['phase']!='settle']
    support=max((abs(r['z']-ground_height(r['x'],run)-.01) for r in active),default=999)
    roll=max((abs(r['roll']) for r in active),default=999)
    pitch=max((abs(r['pitch']) for r in active),default=999)
    lateral=max((abs(r['y']) for r in active),default=999)
    speed=max((math.hypot(b['x']-a['x'],b['y']-a['y'])/(b['sim_s']-a['sim_s'])
               for a,b in zip(active,active[1:]) if b['sim_s']>a['sim_s']),default=999)
    clearance=[]
    for r in active:
        cy,sy=math.cos(r['yaw']),math.sin(r['yaw']);cp,sp=math.cos(r['pitch']),math.sin(r['pitch'])
        cr,sr=math.cos(r['roll']),math.sin(r['roll'])
        for x,y in itertools.product([-.172,.108],[-.155,.155]):
            wx=r['x']+cy*cp*x+(cy*sp*sr-sy*cr)*y
            wz=r['z']-sp*x+cp*sr*y
            clearance.append(wz-ground_height(wx,run))
    chassis=min(clearance,default=-999)
    peak=max((abs(float(r[k])) for r in torque for k in ['left_nm','right_nm']),default=0)
    hold=[r for r in active if r['phase']=='hold']
    drift=max((math.hypot(r['x']-hold[0]['x'],r['y']-hold[0]['y']) for r in hold),default=999)
    require(support<=.06,'support error');require(roll<=.12 and pitch<=.1,'attitude limit')
    require(lateral<=.3,'corridor departure');require(speed<=.16,'speed limit')
    require(chassis>=.001,'chassis grounding');require(1e-6<peak<=.080001,'actuator bound/evidence')
    require(hold and hold[-1]['sim_s']-hold[0]['sim_s']>=2.7,'stationary observation duration')
    require(drift<=.03,'stationary drift')
    require(all(r['command_mps']==0 for r in hold),'nonzero stopped command')
    if rows:
        expected_start=-1 if direction=='up' else run+1
        expected_end=run+1 if direction=='up' else -1
        require(abs(rows[0]['x']-expected_start)<.03,'fresh start pose')
        require(abs(rows[-1]['x']-expected_end)<.10 and rows[-1]['phase']=='finish','terminal endpoint')
        require(any(r['x']<run/2-.2 for r in rows) and any(r['x']>run/2+.2 for r in rows),'full traversal')
    model=ET.parse(directory/'world.sdf').find(".//model[@name='robot_1']")
    mass=sum(float(m.text) for m in model.findall('link/inertial/mass'))
    require(abs(mass-(1.653+design['payload_kg']))<1e-9,'physical payload mass')
    require(not any('DiffDrive' in p.get('name','') for p in model.findall('plugin')),'velocity override present')
    controllers=[p for p in model.findall('plugin') if 'JointController' in p.get('name','')]
    require(len(controllers)==2 and all(p.findtext('use_force_commands')=='true' and
            float(p.findtext('cmd_max'))==.08 and float(p.findtext('cmd_min'))==-.08
            for p in controllers),'force controller configuration')
    return {'trial':directory.name,'status':'FAIL' if errors else 'PASS','errors':errors,
            'route':design['route'],'direction':direction,'payload_kg':design['payload_kg'],
            'peak_torque_nm':peak,'max_speed_mps':speed,'max_support_error_m':support,
            'max_roll_rad':roll,'max_pitch_rad':pitch,'max_lateral_m':lateral,
            'minimum_chassis_clearance_m':chassis,'hold_drift_m':drift,'physical_mass_kg':mass}


def audit_matrix(root):
    expected={f'{a}-{d}-p{p:g}-r{r}' for a,d,p,r in itertools.product(['A','B'],['up','down'],[0.,.25,.5],range(1,4))}
    found={p.name for p in root.iterdir() if p.is_dir()}
    rows=[audit_trial(root/n) for n in sorted(expected&found)]
    errors=[]
    if found!=expected:errors.append(f'trial set mismatch: missing={sorted(expected-found)}, extra={sorted(found-expected)}')
    if any(r['status']!='PASS' for r in rows):errors.append('raw evidence audit failed')
    return {'status':'FAIL' if errors else 'PASS','errors':errors,'audited_trials':len(rows),'trials':rows}


if __name__=='__main__':
    p=argparse.ArgumentParser();p.add_argument('matrix',type=Path);p.add_argument('--output',type=Path,required=True)
    args=p.parse_args();result=audit_matrix(args.matrix)
    args.output.write_text(json.dumps(result,indent=2)+'\n')
    print(json.dumps({k:v for k,v in result.items() if k!='trials'}))
    raise SystemExit(result['status']!='PASS')
