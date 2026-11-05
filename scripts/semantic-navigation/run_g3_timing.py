#!/usr/bin/env python3
"""One independent G3 measurement. Retains failures; never retries measurements."""
import argparse
import json
import os
from pathlib import Path
import subprocess
import time
from evaluate_g3 import evaluate


def main():
    p=argparse.ArgumentParser(description=__doc__);p.add_argument('--oc',default='oc');p.add_argument('--resources',type=Path,required=True);p.add_argument('--output-dir',type=Path,required=True);p.add_argument('--moving',action='store_true');a=p.parse_args()
    a.output_dir.mkdir(parents=True,exist_ok=False);root=Path(__file__).resolve().parents[2];children=[];logs=[]
    base=[a.oc,'-n','semantic-navigation']
    def oc(*args,check=True,input=None):return subprocess.run(base+list(args),text=True,capture_output=True,timeout=60,check=check,input=input)
    def save(name,value):(a.output_dir/name).write_text(json.dumps(value,indent=2)+'\n')
    def launch(name,command):
        f=(a.output_dir/(name+'.log')).open('w');logs.append(f);proc=subprocess.Popen(command,stdout=f,stderr=subprocess.STDOUT,env=os.environ.copy());children.append(proc);return proc
    capture=None;costmap=None;motion=None;summary={'status':'FAIL'};samples=[]
    try:
        obj=next(x for x in json.loads(a.resources.read_text())['items'] if x['kind']=='Pod' and x['metadata']['name']=='semantic-s3-inference')
        save('adapter-resources.json',obj)
        oc('delete','pod','semantic-s3-inference','--wait=true','--timeout=50s')
        oc('exec','semantic-s3-simulator','-c','simulator','--','bash','-ec','source /opt/ros/jazzy/setup.bash; gz service -s /world/sim_world/control --reqtype gz.msgs.WorldControl --reptype gz.msgs.Boolean --timeout 5000 --req "reset: {all: true}"')
        oc('create','-f','-',input=json.dumps(obj))
        deadline=time.monotonic()+180
        while time.monotonic()<deadline:
            pod=json.loads(oc('get','pod','semantic-s3-inference','-o','json').stdout)
            statuses=pod.get('status',{}).get('containerStatuses',[])
            if len(statuses)==4 and all(x['ready'] for x in statuses):break
            time.sleep(2)
        else:raise RuntimeError('fresh-input readiness not achieved')
        save('pod-start.json',pod);time.sleep(5)
        if a.moving:
            oc('exec','semantic-s3-simulator','-c','simulator','--','rm','-f','/tmp/g3-motion-stop')
            oc('cp','-c','simulator',str(root/'scripts/semantic-navigation/g3_observation_motion.py'),'semantic-s3-simulator:/tmp/g3_observation_motion.py')
            motion=launch('motion',base+['exec','semantic-s3-simulator','-c','simulator','--','bash','-ec',f'source /opt/ros/jazzy/setup.bash; python3 /tmp/g3_observation_motion.py --duration 630 --output /tmp/{a.output_dir.name}-motion.json'])
            time.sleep(3)
            if motion.poll() is not None:raise RuntimeError('motion fixture failed at start')
        capture=launch('capture',base+['exec','semantic-s3-inference','-c','adapter','--','bash','-ec','source /opt/ros/jazzy/setup.bash; python3 /g3-config/audit_g3_capture_timing.py --duration 600 --progress --output /tmp/g3-measurement.json'])
        costmap=launch('costmap',['python3',str(root/'scripts/semantic-navigation/collect_phase4_evidence.py'),'--pod','semantic-s3-inference','--duration','600','--output-dir',str(a.output_dir/'costmap')])
        started=time.monotonic();sample=started;progress=started+30
        while capture.poll() is None or costmap.poll() is None:
            now=time.monotonic()
            if now-started>800:raise TimeoutError('measurement did not finish')
            if motion is not None and motion.poll() is not None and motion.returncode!=0:raise RuntimeError('motion fixture failed')
            if now>=sample:
                stats=oc('adm','top','pod','-l','app in (semantic-s3-inference,semantic-s3-simulator)','--containers',check=False)
                samples.append({'elapsed_s':now-started,'wall_ns':time.time_ns(),'stdout':stats.stdout,'stderr':stats.stderr,'returncode':stats.returncode});sample+=15
            if now>=progress:
                print(json.dumps({'event':'measurement_progress','run':a.output_dir.name,'elapsed_s':now-started}),flush=True);progress+=30
            time.sleep(1)
        if capture.returncode or costmap.returncode:raise RuntimeError('observer process failed')
        oc('cp','-c','adapter','semantic-s3-inference:/tmp/g3-measurement.json',str(a.output_dir/'capture.json'))
        if motion is not None:
            motion.wait(timeout=60)
            oc('cp','-c','simulator',f'semantic-s3-simulator:/tmp/{a.output_dir.name}-motion.json',str(a.output_dir/'motion.json'))
            if motion.returncode or not json.loads((a.output_dir/'motion.json').read_text())['pass']:raise RuntimeError('moving observation did not finish stopped')
        summary=evaluate(json.loads((a.output_dir/'capture.json').read_text()),json.loads((a.output_dir/'costmap/summary.json').read_text()))
        pod=json.loads(oc('get','pod','semantic-s3-inference','-o','json').stdout);save('pod-final.json',pod)
        summary['checks']['no_restarts']=all(x['restartCount']==0 for x in pod['status']['containerStatuses'])
        summary['status']='PASS' if all(summary['checks'].values()) else 'FAIL'
    except Exception as error:
        summary['error']=repr(error)
        raise
    finally:
        for proc in children:
            if proc.poll() is None:proc.terminate()
        # Explicit zero for the private simulation even if a remote motion exec was interrupted.
        if a.moving:
            oc('exec','semantic-s3-simulator','-c','simulator','--','touch','/tmp/g3-motion-stop',check=False)
            stop=oc('exec','semantic-s3-simulator','-c','simulator','--','bash','-ec','export ROS_LOG_DIR=/tmp/g3-motion-logs; source /opt/ros/jazzy/setup.bash; timeout 4 ros2 topic pub --once /robot_1/cmd_vel geometry_msgs/msg/Twist "{}"',check=False)
            save('stop-command.json',{'returncode':stop.returncode,'stdout':stop.stdout,'stderr':stop.stderr})
        save('resources.json',samples);save('evaluation.json',summary)
        for name in ('adapter','costmap-observer'):
            r=oc('logs','semantic-s3-inference','-c',name,check=False);(a.output_dir/(name+'.log')).write_text(r.stdout+r.stderr)
        for f in logs:f.close()
    print(json.dumps(summary,indent=2),flush=True)
    if summary['status']!='PASS':raise SystemExit(1)

if __name__=='__main__':main()
