#!/usr/bin/env python3
"""Build both physical ramps and a selected-corridor Nav2 qualification map."""
import argparse
import json
import math
from pathlib import Path
import xml.etree.ElementTree as ET
import yaml
from build_fixture import element, plugin, box, ramp_mesh, robot, elevation


def distance_to_segment(x,y,a,b):
    dx,dy=b[0]-a[0],b[1]-a[1]
    t=max(0,min(1,((x-a[0])*dx+(y-a[1])*dy)/(dx*dx+dy*dy)))
    return math.hypot(x-a[0]-t*dx,y-a[1]-t*dy)


def add_semantic_targets(world, route):
    """Add non-colliding visual-only target and distractor mats for semantic checks."""
    if route=='A':
        run=10.0;targets=[('semantic_red_mat',4.5,.50),
                         ('semantic_neutral_distractor',8.0,-.30)]
    else:
        run=20.0;targets=[('semantic_red_mat',7.0,6.50),
                         ('semantic_neutral_distractor',12.0,5.70)]
    for (name,x,y),rgba in zip(targets,['0.85 0.08 0.06 1','0.55 0.52 0.45 1']):
        model=element(world,'model',name=name);element(model,'static','true')
        z=elevation(x-2.0,run)+0.012
        element(model,'pose',f'{x} {y} {z} 0 0 0')
        link=element(model,'link',name='visual_only')
        visual=element(link,'visual',name='mat')
        box_geom=element(element(visual,'geometry'),'box');element(box_geom,'size','0.75 0.60 0.02')
        material=element(visual,'material')
        element(material,'ambient',rgba);element(material,'diffuse',rgba)


def generate(source, fixture, output, route, direction, payload, rtf, camera_width=640, camera_height=480, semantic=False, speed_mps=0.1):
    if camera_width<160 or camera_width>640 or camera_height<120 or camera_height>480:
        raise ValueError('camera size must remain within 160x120 and 640x480')
    output.mkdir(parents=True,exist_ok=True)
    cfg=json.loads(fixture.read_text());nodes=cfg['geometry']['nodes'];paths=cfg['geometry']['routes']
    speed_cap=float(cfg['robot']['speed_cap_mps'])
    if not 0.02<=speed_mps<=speed_cap:
        raise ValueError(f'planned speed {speed_mps} outside the qualified envelope [0.02, {speed_cap}]')
    path=paths[route] if direction=='up' else list(reversed(paths[route]))
    x,y,z=nodes[path[0]];nx,ny,_=nodes[path[1]];yaw=math.atan2(ny-y,nx-x)
    sdf=ET.Element('sdf',version='1.9');world=element(sdf,'world',name='warehouse')
    physics=element(world,'physics',name='step',type='ignored')
    for k,v in {'max_step_size':.002,'real_time_factor':rtf,'real_time_update_rate':rtf/.002}.items():element(physics,k,v)
    element(world,'gravity','0 0 -9.80665')
    for filename,name in [('physics','Physics'),('user-commands','UserCommands'),('scene-broadcaster','SceneBroadcaster')]:
        plugin(world,f'gz-sim-{filename}-system',f'gz::sim::systems::{name}',{})
    if semantic:
        scene=element(world,'scene')
        element(scene,'ambient','1 1 1');element(scene,'background','0.8 0.8 0.8')
        light=element(world,'light',type='directional',name='warehouse_sun')
        element(light,'cast_shadows','true');element(light,'pose','0 0 10 0 0 0')
        element(light,'diffuse','1 1 1 1');element(light,'specular','0.2 0.2 0.2 1')
        attenuation=element(light,'attenuation')
        element(attenuation,'range',1000);element(attenuation,'constant',0.09)
        element(attenuation,'linear',0.001);element(attenuation,'quadratic',0.001)
        element(light,'direction','-0.5 0.1 -0.9')
    plugin(world,'gz-sim-sensors-system','gz::sim::systems::Sensors',{'render_engine':'ogre2'})
    box(world,'ground',10,3,0,32,16)
    box(world,'upper_a',17.5,0,.2,11,1.5)
    # Clip the perpendicular deck at the ramp's side/end boundaries. Extending
    # its full-height box into the ramp creates a vertical collision lip at
    # x=21.25 before the 22 m crest, despite an apparently smooth rendered top.
    box(world,'upper_b_exit',22,2.25,.2,1.5,6.0)
    box(world,'upper_b_pad',22.75,6,.2,1.5,1.5)
    for name,run,ypos in [('A',10,0),('B',20,6)]:
        meshfile=output/f'ramp_{name}.obj';ramp_mesh(meshfile,run)
        ramp=element(world,'model',name=f'ramp_{name}');element(ramp,'static','true')
        element(ramp,'pose',f'2 {ypos} 0 0 0 0');link=element(ramp,'link',name='surface')
        for kind in ['collision','visual']:
            mesh=element(element(element(link,kind,name=kind),'geometry'),'mesh')
            element(mesh,'uri',str(meshfile.resolve()))
    camera_tilt_rad=0.35 if semantic else 0.0
    world.append(robot(source,payload,x,y,z,yaw,sensors=True,camera_size=(camera_width,camera_height),
        camera_tilt_rad=camera_tilt_rad))
    if semantic:add_semantic_targets(world,route)
    ET.indent(sdf)
    ET.ElementTree(sdf).write(output/'world.sdf',encoding='unicode',xml_declaration=True)
    # Only the selected corridor is traversable; both ramps remain in Gazebo/RMF.
    resolution=.05;origin=[-4.,-3.,0.];width,height=600,240
    edges=[(nodes[a],nodes[b]) for a,b in zip(path,path[1:])]
    pixels=bytearray()
    for iy in range(height-1,-1,-1):
        for ix in range(width):
            px,py=origin[0]+(ix+.5)*resolution,origin[1]+(iy+.5)*resolution
            pixels.append(254 if min(distance_to_segment(px,py,a,b) for a,b in edges)<.70 else 0)
    (output/'map.pgm').write_bytes(f'P5\n{width} {height}\n255\n'.encode()+pixels)
    (output/'map.yaml').write_text(yaml.safe_dump({'image':'map.pgm','resolution':resolution,
        'origin':origin,'negate':0,'occupied_thresh':.65,'free_thresh':.196,'mode':'trinary'}))
    names=list(nodes);indices={n:i for i,n in enumerate(names)};lanes=[];seen=set()
    for p in [*paths.values(),['loading','charger']]:
        for a,b in zip(p,p[1:]):
            for start,end in [(a,b),(b,a)]:
                edge=(indices[start],indices[end])
                if edge not in seen:lanes.append([*edge,{}]);seen.add(edge)
    graph={'building_name':'warehouse','levels':{'warehouse':{'vertices':[
        [*nodes[n][:2],{'name':n,'is_charger':n=='charger','is_holding_point':True}]
        for n in names],'lanes':lanes}}}
    (output/'graph.yaml').write_text(yaml.safe_dump(graph,sort_keys=False))
    fleet={'rmf_fleet':{'name':'warehouse_energy','limits':{'linear':[.1,.1],'angular':[.45,.7]},
        'profile':{'footprint':.246,'vicinity':.5},'reversible':False,
        'battery_system':{'voltage':12.,'capacity':2.,'charging_current':1.},
        'mechanical_system':{'mass':1.653+payload,'moment_of_inertia':.02,'friction_coefficient':.02},
        'ambient_system':{'power':2.},'tool_system':{'power':0.},'recharge_threshold':.2,
        'recharge_soc':.8,'account_for_battery_drain':False,'publish_fleet_state':.25,
        'task_capabilities':{'loop':True,'delivery':True},'finishing_request':'nothing',
        'responsive_wait':False,'robots':{'robot_1':{'charger':'charger','responsive_wait':False}},
        'robot_state_update_frequency':4.},'reference_coordinates':{'warehouse':{
            'rmf':[[0,0],[1,0],[0,1],[1,1]],'robot':[[0,0],[1,0],[0,1],[1,1]]}}}
    (output/'fleet.yaml').write_text(yaml.safe_dump(fleet,sort_keys=False))
    # Empty surveyed fixture: static corridor masks, no warehouse perception claims.
    def costmap(frame, global_map=False):
        plugins=['static_layer','inflation_layer']
        values={}
        if global_map and semantic:
            plugins=['static_layer','semantic_layer','inflation_layer']
            values['semantic_layer']={'plugin':'demo_semantic_costmap::SemanticLayer','enabled':True,
                'topic_prefix':'/robot_1/semantic','observation_lifetime':1.0,
                'max_capture_age':0.5,'target_cost':254,'optical_frame':'camera_color_optical_frame'}
        return {'ros__parameters':{'use_sim_time':True,'global_frame':frame,
        'robot_base_frame':'base_footprint','resolution':.05,'robot_radius':.246,
        'update_frequency':5.,'publish_frequency':2.,'transform_tolerance':.5,
        'plugins':plugins,
        'static_layer':{'plugin':'nav2_costmap_2d::StaticLayer','map_subscribe_transient_local':True},
        **values,
        'inflation_layer':{'plugin':'nav2_costmap_2d::InflationLayer','inflation_radius':.35,'cost_scaling_factor':5.}}}
    params={
      'map_server':{'ros__parameters':{'use_sim_time':True,'yaml_filename':str(output/'map.yaml')}},
      'planner_server':{'ros__parameters':{'use_sim_time':True,'planner_plugins':['GridBased'],
         'GridBased':{'plugin':'nav2_navfn_planner::NavfnPlanner','tolerance':.1,'use_astar':True,'allow_unknown':False}}},
      'controller_server':{'ros__parameters':{'use_sim_time':True,'controller_frequency':20.,
         'enable_stamped_cmd_vel':False,'min_x_velocity_threshold':.001,'min_theta_velocity_threshold':.001,
         'progress_checker_plugins':['progress_checker'],'goal_checker_plugins':['general_goal_checker'],
         'controller_plugins':['FollowPath'],'progress_checker':{'plugin':'nav2_controller::SimpleProgressChecker',
             'required_movement_radius':.04,'movement_time_allowance':60.},
         'general_goal_checker':{'plugin':'nav2_controller::SimpleGoalChecker','stateful':True,
             'xy_goal_tolerance':.06,'yaw_goal_tolerance':.12},
         'FollowPath':{'plugin':'nav2_regulated_pure_pursuit_controller::RegulatedPurePursuitController',
             'desired_linear_vel':speed_mps,'min_approach_linear_velocity':.02,'regulated_linear_scaling_min_speed':.03,
             'lookahead_dist':.35,'min_lookahead_dist':.2,'max_lookahead_dist':.5,
             'use_rotate_to_heading':True,'rotate_to_heading_angular_vel':.3,
             'rotate_to_heading_min_angle':.2,'max_angular_accel':.5,'allow_reversing':False,
             'use_collision_detection':True,'transform_tolerance':.5}}},
      'bt_navigator':{'ros__parameters':{'use_sim_time':True,'global_frame':'map','robot_base_frame':'base_footprint',
         'odom_topic':'odom','bt_loop_duration':10,'default_server_timeout':20000,
         'default_nav_to_pose_bt_xml':'/work/scripts/warehouse-energy/navigation.xml',
         'navigators':['navigate_to_pose'],'navigate_to_pose':{'plugin':'nav2_bt_navigator::NavigateToPoseNavigator'}}},
      'global_costmap':{'global_costmap':costmap('map',global_map=True)},
      'local_costmap':{'local_costmap':costmap('map')}}
    (output/'nav2.yaml').write_text(yaml.safe_dump(params,sort_keys=False))
    (output/'design.json').write_text(json.dumps({'route':route,'direction':direction,'payload_kg':payload,
        'start':[x,y,z,yaw],'path':path,'nodes':nodes,'rtf_target':rtf,'planned_speed_mps':speed_mps,
        'camera':{'width':camera_width,'height':camera_height,'configured_rate_hz':10,
            'downward_tilt_rad':camera_tilt_rad},
        'semantic_fixture':({'enabled':True,'prompt':'red mat','policy':'avoid-target/v1',
            'target_cost':254,'targets':[{'name':'semantic_red_mat','center':
                ([4.5,0.50,elevation(2.5,10)+.012] if route=='A' else [7.0,6.50,elevation(5.0,20)+.012]),
                'size':[0.75,0.60],'expected_label':'avoid_target'},
                {'name':'semantic_neutral_distractor','center':
                 ([8.0,-0.30,elevation(6.0,10)+.012] if route=='A' else [12.0,5.70,elevation(10.0,20)+.012]),
                 'size':[0.75,0.60],'expected_label':'not_target'}]}
            if semantic else {'enabled':False}),
        'source_fixture':cfg},indent=2)+'\n')


if __name__=='__main__':
    p=argparse.ArgumentParser();p.add_argument('--source',type=Path,required=True)
    p.add_argument('--fixture',type=Path,required=True);p.add_argument('--output',type=Path,required=True)
    p.add_argument('--route',choices=['A','B'],required=True);p.add_argument('--direction',choices=['up','down'],required=True)
    p.add_argument('--payload',type=float,default=.5);p.add_argument('--rtf',type=float,default=3)
    p.add_argument('--camera-width',type=int,default=640);p.add_argument('--camera-height',type=int,default=480)
    p.add_argument('--speed',type=float,default=0.1)
    p.add_argument('--semantic',action='store_true')
    a=p.parse_args();generate(a.source,a.fixture,a.output.resolve(),a.route,a.direction,a.payload,a.rtf,a.camera_width,a.camera_height,a.semantic,a.speed)
