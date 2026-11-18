#!/usr/bin/env python3
"""Generate the isolated, bounded-drive fixture from the pinned hotel SDF."""
import argparse
import copy
import json
import math
from pathlib import Path
import xml.etree.ElementTree as ET


def element(parent, tag, text=None, **attrs):
    node = ET.SubElement(parent, tag, attrs)
    if text is not None:
        node.text = str(text)
    return node


def elevation(x, run, rise=0.2, transition=1.0):
    """C1 profile: cosine slope transitions, exact rise, horizontal end tangents."""
    if x <= 0:
        return 0.0
    if x >= run:
        return rise
    slope = rise / (run - transition)
    def start(u):
        return slope * (u / 2 - transition * math.sin(math.pi*u/transition) / (2*math.pi))
    if x < transition:
        return start(x)
    if x > run-transition:
        return rise-start(run-x)
    return slope*(x-transition/2)


def ramp_mesh(path, run, width=1.5, rise=0.2):
    # Closed mesh, 5 cm longitudinal sampling; no staircase or disconnected tiles.
    count = round(run/0.05)
    vertices = []
    for i in range(count+1):
        x = run*i/count
        h = elevation(x, run, rise)
        vertices.extend([(x, -width/2, h), (x, width/2, h),
                         (x, -width/2, -0.1), (x, width/2, -0.1)])
    faces = []
    for i in range(count):
        a, b = 4*i+1, 4*(i+1)+1
        for q in [(a,b,b+1,a+1), (a+2,a+3,b+3,b+2),
                  (a,a+2,b+2,b), (a+1,b+1,b+3,a+3)]:
            faces.extend([(q[0],q[1],q[2]),(q[0],q[2],q[3])])
    for q in [(1,2,4,3),(4*count+1,4*count+3,4*count+4,4*count+2)]:
        faces.extend([(q[0],q[1],q[2]),(q[0],q[2],q[3])])
    normals=[]
    for a,b,c in faces:
        u=[vertices[b-1][i]-vertices[a-1][i] for i in range(3)]
        v=[vertices[c-1][i]-vertices[a-1][i] for i in range(3)]
        n=[u[1]*v[2]-u[2]*v[1],u[2]*v[0]-u[0]*v[2],u[0]*v[1]-u[1]*v[0]]
        length=math.sqrt(sum(x*x for x in n))
        normals.append(tuple(x/length for x in n))
    path.write_text(''.join('v %s %s %s\n'%v for v in vertices)+
                    ''.join('vn %s %s %s\n'%n for n in normals)+
                    ''.join('f '+' '.join(f'{v}//{i+1}' for v in face)+'\n'
                            for i,face in enumerate(faces)))


def plugin(parent, filename, name, values):
    p = element(parent, 'plugin', filename=filename, name=name)
    for k,v in values.items():
        element(p,k,v)
    return p


def box(world, name, x, y, top, sx, sy, depth=0.1):
    model = element(world,'model',name=name)
    element(model,'static','true')
    element(model,'pose',f'{x} {y} {top-depth/2} 0 0 0')
    link=element(model,'link',name='surface')
    for kind in ['collision','visual']:
        item=element(link,kind,name=kind)
        element(element(element(item,'geometry'),'box'),'size',f'{sx} {sy} {depth}')


def robot(source, payload, x, y, z, yaw, sensors=False, camera_size=(640,480), camera_tilt_rad=0.0):
    model=copy.deepcopy(ET.parse(source).find(".//model[@name='robot_1']"))
    if model is None:
        raise ValueError('pinned robot absent')
    canonical=model.find('canonical_link')
    if canonical is not None:
        model.set('canonical_link',canonical.text);model.remove(canonical)
    model.find('pose').text=f'{x} {y} {z+0.02} 0 0 {yaw}'
    for p in list(model.findall('plugin')):
        model.remove(p)
    # This qualification fixture tests surveyed empty corridors, not perception.
    for link in model.findall('link'):
        for sensor in list(link.findall('sensor')):
            link.remove(sensor)
    for side in ['left','right']:
        joint=f'{side}_wheel_joint'
        axis=model.find(f"joint[@name='{joint}']/axis")
        axis.find('limit/effort').text='0.08'
        axis.find('limit/velocity').text='8.0'
        axis.find('dynamics/friction').text='0.001'
        plugin(model,'gz-sim-joint-controller-system','gz::sim::systems::JointController',
               {'joint_name':joint,'topic':f'/warehouse/{side}/cmd_vel',
                'use_force_commands':'true','p_gain':0.05,'i_gain':0.1,
                'i_max':0.08,'i_min':-0.08,'cmd_max':0.08,'cmd_min':-0.08})
    plugin(model,'gz-sim-joint-state-publisher-system','gz::sim::systems::JointStatePublisher',{})
    plugin(model,'/work/libWarehouseTelemetry.so','WarehouseTelemetry',{})
    if sensors:
        camera=model.find("link[@name='camera_link']")
        if camera is None:
            camera=element(model,'link',name='camera_link')
            element(camera,'pose','0.11 0 0.15 0 0 0')
        sensor=element(camera,'sensor',name='rgbd_camera',type='rgbd_camera')
        if camera_tilt_rad:
            element(sensor,'pose',f'0 0 0 0 {camera_tilt_rad} 0')
        element(sensor,'always_on','false'); element(sensor,'update_rate','10')
        element(sensor,'topic','/robot_1/camera'); element(sensor,'gz_frame_id','camera_color_optical_frame')
        camera_config=element(sensor,'camera')
        element(camera_config,'horizontal_fov',1.04719755)
        image=element(camera_config,'image')
        element(image,'width',camera_size[0]); element(image,'height',camera_size[1]); element(image,'format','R8G8B8')
        clip=element(camera_config,'clip'); element(clip,'near',0.15); element(clip,'far',5.0)
        element(sensor,'visualize','false')
        if model.find("joint[@name='camera_joint']") is None:
            joint=element(model,'joint',name='camera_joint',type='fixed')
            element(joint,'parent','base_link'); element(joint,'child','camera_link')
        if model.find("link[@name='camera_color_optical_frame']") is None:
            element(model,'link',name='camera_color_optical_frame')
        if model.find("joint[@name='camera_color_optical_joint']") is None:
            optical_joint=element(model,'joint',name='camera_color_optical_joint',type='fixed')
            element(optical_joint,'parent','camera_link'); element(optical_joint,'child','camera_color_optical_frame')
            element(optical_joint,'pose','0 0 0 -1.57079632679 0 -1.57079632679')
    if payload:
        link=element(model,'link',name='payload')
        element(link,'pose','-0.06 0 0.165 0 0 0')
        inertial=element(link,'inertial')
        element(inertial,'mass',payload)
        inertia=element(inertial,'inertia')
        for key,val in {'ixx':payload*0.0125/12,'iyy':payload*0.0125/12,
                        'izz':payload*0.02/12,'ixy':0,'ixz':0,'iyz':0}.items():
            element(inertia,key,val)
        for kind in ['collision','visual']:
            element(element(element(element(link,kind,name=kind),'geometry'),'box'),'size','0.1 0.1 0.05')
        joint=element(model,'joint',name='payload_fixed',type='fixed')
        element(joint,'parent','base_link'); element(joint,'child','payload')
    return model


def generate(source, output, route='A', direction='up', payload=0.0, rtf=10.0, sensors=False):
    output.mkdir(parents=True,exist_ok=True)
    run={'A':10.,'B':20.}[route]
    sdf=ET.Element('sdf',version='1.9'); world=element(sdf,'world',name='warehouse')
    physics=element(world,'physics',name='step',type='ignored')
    element(physics,'max_step_size',0.002)
    element(physics,'real_time_factor',rtf)
    element(physics,'real_time_update_rate',rtf/0.002)
    element(world,'gravity','0 0 -9.80665')
    for filename,name in [('physics','Physics'),('user-commands','UserCommands'),('scene-broadcaster','SceneBroadcaster')]:
        plugin(world,f'gz-sim-{filename}-system',f'gz::sim::systems::{name}',{})
    if sensors:
        plugin(world,'gz-sim-sensors-system','gz::sim::systems::Sensors',{'render_engine':'ogre2'})
    box(world,'lower',-1.5,0,0,3,1.5)
    box(world,'upper',run+1.5,0,.2,3,1.5)
    ramp_mesh(output/'ramp.obj',run)
    ramp=element(world,'model',name='ramp'); element(ramp,'static','true')
    link=element(ramp,'link',name='surface')
    for kind in ['collision','visual']:
        mesh=element(element(element(link,kind,name=kind),'geometry'),'mesh')
        element(mesh,'uri',str((output/'ramp.obj').resolve()))
    start=(-1.,0.,0.,0.) if direction=='up' else (run+1,0.,.2,math.pi)
    world.append(robot(source,payload,*start,sensors=sensors))
    ET.indent(sdf)
    ET.ElementTree(sdf).write(output/'world.sdf',encoding='unicode',xml_declaration=True)
    (output/'design.json').write_text(json.dumps({'route':route,'direction':direction,
        'payload_kg':payload,'run_m':run,'rise_m':.2,'start':start,
        'end_x':run+1 if direction=='up' else -1.,'effort_limit_nm':.08,'sensors_enabled':sensors,
        'max_peak_grade':.2/(run-1),'max_step_s':.002,'rtf_target':rtf},indent=2)+'\n')


if __name__=='__main__':
    p=argparse.ArgumentParser(); p.add_argument('--source',type=Path,required=True)
    p.add_argument('--output',type=Path,required=True);p.add_argument('--route',choices=['A','B'],default='A')
    p.add_argument('--direction',choices=['up','down'],default='up')
    p.add_argument('--payload',type=float,default=0);p.add_argument('--rtf',type=float,default=10)
    a=p.parse_args();generate(a.source,a.output,a.route,a.direction,a.payload,a.rtf)
