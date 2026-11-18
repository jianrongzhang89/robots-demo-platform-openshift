#!/usr/bin/env python3
"""Fresh-world force-limited ramp traversal with stop/restart and physical audit."""
import argparse
import csv
import hashlib
import json
import math
import os
from pathlib import Path
import signal
import subprocess
import threading
import time

from gz.transport13 import Node
from gz.msgs10.pose_v_pb2 import Pose_V
from gz.msgs10.double_pb2 import Double
from build_fixture import generate, elevation


def trial(args):
    generate(args.source,args.output,args.route,args.direction,args.payload,args.rtf)
    code=Path(__file__).parent
    (args.output/'source-sha256.json').write_text(json.dumps({str(p):hashlib.sha256(p.read_bytes()).hexdigest()
        for p in [code/'build_fixture.py',code/'physics_trial.py',code/'WarehouseTelemetry.cc',
                  Path('/work/libWarehouseTelemetry.so'),args.source]},indent=2)+'\n')
    design=json.loads((args.output/'design.json').read_text())
    env=dict(os.environ,WAREHOUSE_TORQUE_TRACE=str(args.output/'torque.csv'))
    log=open(args.output/'gazebo.log','w')
    gz=subprocess.Popen(['gz','sim','-s','-r',str(args.output/'world.sdf')],env=env,
                        stdout=log,stderr=subprocess.STDOUT,start_new_session=True)
    node=Node(); latest=None; lock=threading.Lock()
    def receive(msg):
        nonlocal latest
        p=next((p for p in msg.pose if p.name=='robot_1'),None)
        if p is None:return
        q=p.orientation
        row={'sim_s':msg.header.stamp.sec+msg.header.stamp.nsec*1e-9,
             'x':p.position.x,'y':p.position.y,'z':p.position.z,
             'yaw':math.atan2(2*(q.w*q.z+q.x*q.y),1-2*(q.y*q.y+q.z*q.z)),
             'roll':math.atan2(2*(q.w*q.x+q.y*q.z),1-2*(q.x*q.x+q.y*q.y)),
             'pitch':math.asin(max(-1,min(1,2*(q.w*q.y-q.z*q.x)))),
             'received':time.monotonic()}
        with lock:latest=row
    node.subscribe(Pose_V,'/world/warehouse/pose/info',receive)
    pubs=[node.advertise(f'/warehouse/{side}/cmd_vel',Double) for side in ['left','right']]
    trace=[]; errors=[]; stopped=[]; phase='settle'; phase_at=None
    deadline=time.monotonic()+180; first=None; previous=None; last_t=None
    speed=0.; stop_done=False; brake_anchor=None
    try:
        while time.monotonic()<deadline:
            time.sleep(.002)
            if gz.poll() is not None:raise RuntimeError('Gazebo exited')
            with lock: row=dict(latest) if latest else None
            if row is None:continue
            if time.monotonic()-row['received']>2:raise RuntimeError('stale physical pose')
            t=row['sim_s']
            if last_t is not None and t<=last_t:continue
            dt=min(.1,t-last_t) if last_t is not None else .02;last_t=t
            if first is None:first=t;phase_at=t
            if t-first > (design['run_m']+6)/.07+20:raise RuntimeError('simulation deadline')
            ground=elevation(row['x'],design['run_m'])
            row['support_error_m']=row['z']-ground-.01
            # Four bottom chassis corners transformed by the measured full attitude.
            cy,sy=math.cos(row['yaw']),math.sin(row['yaw'])
            cp,sp=math.cos(row['pitch']),math.sin(row['pitch'])
            cr,sr=math.cos(row['roll']),math.sin(row['roll'])
            clearances=[]
            for bx in [-.172,.108]:
                for by in [-.155,.155]:
                    wx=row['x']+cy*cp*bx+(cy*sp*sr-sy*cr)*by
                    wz=row['z']-sp*bx+cp*sr*by
                    clearances.append(wz-elevation(wx,design['run_m']))
            row['chassis_clearance_m']=min(clearances)
            if phase!='settle':
                if abs(row['y'])>.30:raise RuntimeError('corridor departure')
                if abs(row['roll'])>.12 or abs(row['pitch'])>.10:raise RuntimeError('attitude limit')
                if abs(row['support_error_m'])>.06:raise RuntimeError('loss of ramp support')
                if row['chassis_clearance_m']<.001:raise RuntimeError('chassis grounding')
            if previous:
                delta=t-previous['sim_s']
                row['speed_mps']=math.hypot(row['x']-previous['x'],row['y']-previous['y'])/delta
                if phase!='settle' and row['speed_mps']>.16:raise RuntimeError('physical overspeed')
            previous=row.copy()
            if phase=='settle' and t-phase_at>=3:phase='drive';phase_at=t
            if phase=='drive' and not stop_done and abs(row['x']-design['run_m']/2)<.12:
                phase='brake';phase_at=t
            if phase=='brake' and t-phase_at>=3:
                phase='hold';phase_at=t;brake_anchor=[row['x'],row['y']]
            if phase=='hold':
                drift=math.dist(brake_anchor,[row['x'],row['y']])
                if drift>.03:raise RuntimeError('stopped ramp drift')
                if t-phase_at>=3:
                    stopped.append({'drift_m':drift,'speed_mps':row.get('speed_mps',0)})
                    if row.get('speed_mps',0)>.015:raise RuntimeError('not stationary on ramp')
                    phase='drive';stop_done=True
            if phase=='drive' and abs(row['x']-design['end_x'])<.08:
                phase='finish';phase_at=t
            target=.10 if phase=='drive' else 0.
            speed+=max(-.1*dt,min(.1*dt,target-speed))
            yaw_target=0 if args.direction=='up' else math.pi
            yaw_error=math.atan2(math.sin(yaw_target-row['yaw']),math.cos(yaw_target-row['yaw']))
            # Correct lateral drift while heading forwards along the corridor.
            correction=(-row['y'] if args.direction=='up' else row['y'])*1.2
            angular=max(-.3,min(.3,yaw_error*2+correction)) if phase=='drive' else 0.
            wheels=[(speed-angular*.288/2)/.033,(speed+angular*.288/2)/.033]
            for pub,value in zip(pubs,wheels):pub.publish(Double(data=value))
            row.update(phase=phase,command_mps=speed);row.pop('received',None);trace.append(row)
            if phase=='finish' and t-phase_at>4:break
        else:raise RuntimeError('wall deadline')
        if not stop_done or phase!='finish':raise RuntimeError('traversal incomplete')
    except Exception as exc:errors.append(str(exc))
    finally:
        for pub in pubs:pub.publish(Double(data=0.))
        if gz.poll() is None:
            os.killpg(gz.pid,signal.SIGTERM)
        try:gz.wait(timeout=10)
        except subprocess.TimeoutExpired:os.killpg(gz.pid,signal.SIGKILL);gz.wait()
        log.close()
    torque=list(csv.DictReader((args.output/'torque.csv').open())) if (args.output/'torque.csv').exists() else []
    peak=max((abs(float(row[k])) for row in torque for k in ['left_nm','right_nm']),default=0)
    if not torque:errors.append('no actuator evidence')
    if peak<1e-6:errors.append('no nonzero actuator effort observed')
    if peak>.080001:errors.append('torque limit exceeded')
    result={'status':'FAIL' if errors else 'PASS','errors':errors,'design':design,
            'samples':len(trace),'actuator_samples':len(torque),'peak_torque_nm':peak,
            'stop_checks':stopped,'final_pose':trace[-1] if trace else None,
            'maximum_abs_roll_rad':max((abs(r['roll']) for r in trace),default=0),
            'maximum_abs_pitch_rad':max((abs(r['pitch']) for r in trace),default=0),
            'maximum_support_error_m':max((abs(r['support_error_m']) for r in trace),default=0)}
    result['minimum_chassis_clearance_m']=min((r['chassis_clearance_m'] for r in trace),default=0)
    (args.output/'physics.jsonl').write_text(''.join(json.dumps(r)+'\n' for r in trace))
    (args.output/'result.json').write_text(json.dumps(result,indent=2)+'\n')
    print(json.dumps(result),flush=True)
    return not errors


if __name__=='__main__':
    p=argparse.ArgumentParser();p.add_argument('--source',type=Path,required=True)
    p.add_argument('--output',type=Path,required=True);p.add_argument('--route',choices=['A','B'],default='A')
    p.add_argument('--direction',choices=['up','down'],default='up');p.add_argument('--payload',type=float,default=0)
    p.add_argument('--rtf',type=float,default=10);args=p.parse_args()
    args.output=args.output.resolve()
    if args.output.exists():p.error('output exists; preserve prior attempt')
    raise SystemExit(0 if trial(args) else 1)
