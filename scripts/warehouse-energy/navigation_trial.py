#!/usr/bin/env python3
"""Dispatch an ordered RMF task and audit schedule, Nav2 and Gazebo evidence."""
import json
import math
import os
from collections import OrderedDict
from pathlib import Path
import time
import uuid
import rclpy
from rclpy.node import Node
from rclpy.qos import QoSProfile, ReliabilityPolicy, DurabilityPolicy
from rmf_task_msgs.msg import ApiRequest, ApiResponse
from rmf_fleet_msgs.msg import FleetState
from rmf_traffic_msgs.msg import ItinerarySet, MirrorUpdate
from nav_msgs.msg import Path as NavPath
from rosgraph_msgs.msg import Clock
from std_msgs.msg import String
from sensor_msgs.msg import Image, CameraInfo, PointCloud2
from tf2_msgs.msg import TFMessage
from lifecycle_msgs.srv import GetState
from build_navigation import distance_to_segment
from PIL import Image as PILImage


class Trial(Node):
    def __init__(self):
        super().__init__('warehouse_route_trial')
        self.output=Path(os.environ['WAREHOUSE_RUN_DIR'])
        self.design=json.loads((self.output/'design.json').read_text())
        self.task_id=None;self.request_id=None;self.response=None;self.clock=0
        self.robot=None;self.seen_task=False;self.physics=[];self.itineraries=[];self.plans=[];self.events=[]
        self.mirrors=[]
        self.rgb_samples=[];self.depth_samples=[];self.camera_info_samples=[]
        self.camera_tf_samples=[];self.camera_tf_count=0
        self.semantic_labels=[];self.semantic_masks=[];self.semantic_timing=[];self.semantic_status=[]
        self.raw_rgb_cache=OrderedDict();self.semantic_pair_count=0
        self.last_rgb_snapshot_s=-1e9;self.rgb_snapshot_count=0
        self.dispatched_at=None;self.subscribed=set();self.dynamic_subs=[]
        qos=QoSProfile(depth=10,reliability=ReliabilityPolicy.RELIABLE,durability=DurabilityPolicy.TRANSIENT_LOCAL)
        self.pub=self.create_publisher(ApiRequest,'/task_api_requests',qos)
        self.create_subscription(ApiResponse,'/task_api_responses',self.on_api,qos)
        self.create_subscription(FleetState,'/fleet_states',self.on_fleet,10)
        self.create_subscription(Clock,'/clock',lambda m:setattr(self,'clock',m.clock.sec*1000+m.clock.nanosec//1000000),10)
        self.create_subscription(String,'/warehouse/physics',lambda m:self.physics.append(json.loads(m.data)),20)
        self.create_subscription(String,'/warehouse/adapter_events',lambda m:self.events.append(json.loads(m.data)),20)
        self.create_subscription(NavPath,'/plan',self.on_plan,10)
        self.create_subscription(Image,'/robot_1/camera/color/image_raw',self.on_rgb,10)
        self.create_subscription(Image,'/robot_1/camera/depth/image_raw',self.on_depth,10)
        self.create_subscription(CameraInfo,'/robot_1/camera/color/camera_info',self.on_camera_info,10)
        self.create_subscription(TFMessage,'/tf',self.on_tf,100)
        if self.design.get('semantic_fixture',{}).get('enabled'):
            label_qos=QoSProfile(depth=1,reliability=ReliabilityPolicy.RELIABLE,
                durability=DurabilityPolicy.TRANSIENT_LOCAL)
            self.create_subscription(String,'/robot_1/semantic/label_info',self.on_semantic_labels,label_qos)
            self.create_subscription(Image,'/robot_1/semantic/mask',self.on_semantic_mask,20)
            self.create_subscription(String,'/robot_1/semantic/timing',self.on_semantic_timing,20)
            self.create_subscription(String,'/robot_1/semantic/status',self.on_semantic_status,10)
            self.create_subscription(PointCloud2,'/robot_1/semantic/points',self.on_semantic_cloud,20)
        self.lifecycle_clients={n:self.create_client(GetState,f'/{n}/get_state') for n in ['planner_server','controller_server','bt_navigator']}

    @staticmethod
    def image_sample(msg):
        stamp=msg.header.stamp.sec+msg.header.stamp.nanosec*1e-9
        return {'stamp_s':stamp,'frame_id':msg.header.frame_id,'width':msg.width,'height':msg.height,
                'encoding':msg.encoding,'step':msg.step,'data_bytes':len(msg.data)}

    def on_rgb(self,msg):
        self.rgb_samples.append(self.image_sample(msg))
        if self.design.get('semantic_fixture',{}).get('enabled'):
            stamp=msg.header.stamp.sec+msg.header.stamp.nanosec*1e-9
            stamp_ns=msg.header.stamp.sec*10**9+msg.header.stamp.nanosec
            self.raw_rgb_cache[stamp_ns]=msg
            while len(self.raw_rgb_cache)>64:self.raw_rgb_cache.popitem(last=False)
        # Operator snapshots are saved for every trial (one frame per 5 s,
        # up to eight); semantic pairing keeps its own separate capture set.
        stamp=msg.header.stamp.sec+msg.header.stamp.nanosec*1e-9
        if self.rgb_snapshot_count<8 and stamp-self.last_rgb_snapshot_s>=5:
            directory=self.output/'rgb-snapshots';directory.mkdir(exist_ok=True)
            path=directory/f'frame-{self.rgb_snapshot_count:02d}.png'
            PILImage.frombytes('RGB',(msg.width,msg.height),bytes(msg.data)).save(path)
            self.last_rgb_snapshot_s=stamp;self.rgb_snapshot_count+=1
    def on_depth(self,msg):self.depth_samples.append(self.image_sample(msg))
    def on_camera_info(self,msg):
        self.camera_info_samples.append({'stamp_s':msg.header.stamp.sec+msg.header.stamp.nanosec*1e-9,
            'frame_id':msg.header.frame_id,'width':msg.width,'height':msg.height,
            'fx':msg.k[0],'fy':msg.k[4]})
    def on_tf(self,msg):
        for transform in msg.transforms:
            if transform.child_frame_id!='camera_color_optical_frame':continue
            t=transform.transform.translation;q=transform.transform.rotation
            self.camera_tf_samples.append({'stamp_s':transform.header.stamp.sec+transform.header.stamp.nanosec*1e-9,
                'parent':transform.header.frame_id,'child':transform.child_frame_id,
                'translation':[t.x,t.y,t.z],'rotation_xyzw':[q.x,q.y,q.z,q.w]})
            self.camera_tf_count+=1
            if len(self.camera_tf_samples)>2000:del self.camera_tf_samples[:-2000]

    def on_semantic_labels(self,msg):
        self.semantic_labels.append(json.loads(msg.data))
    def on_semantic_timing(self,msg):
        row=json.loads(msg.data);self.semantic_timing.append(row)
        with (self.output/'semantic-timing.jsonl').open('a') as stream:stream.write(json.dumps(row,sort_keys=True)+'\n')
    def on_semantic_status(self,msg):
        row=json.loads(msg.data);self.semantic_status.append(row)
    def on_semantic_mask(self,msg):
        stamp_ns=msg.header.stamp.sec*10**9+msg.header.stamp.nanosec
        row={'stamp_s':msg.header.stamp.sec+msg.header.stamp.nanosec*1e-9,
            'width':msg.width,'height':msg.height,'encoding':msg.encoding,
            'stamp_ns':stamp_ns,'target_pixels':sum(value==2 for value in msg.data),
            'frame_id':msg.header.frame_id}
        self.semantic_masks.append(row)
        with (self.output/'semantic-masks.jsonl').open('a') as stream:stream.write(json.dumps(row,sort_keys=True)+'\n')
        rgb=self.raw_rgb_cache.get(stamp_ns)
        if row['target_pixels'] and rgb is not None and self.semantic_pair_count<24:
            directory=self.output/'semantic-label-pairs';directory.mkdir(exist_ok=True)
            stem=f'capture-{stamp_ns}'
            PILImage.frombytes('RGB',(rgb.width,rgb.height),bytes(rgb.data)).save(directory/f'{stem}-rgb.png')
            binary=bytes(255 if value==2 else 0 for value in msg.data)
            PILImage.frombytes('L',(msg.width,msg.height),binary).save(directory/f'{stem}-mask.png')
            self.semantic_pair_count+=1
    def on_semantic_cloud(self,msg):
        if self.semantic_timing:
            self.semantic_timing[-1]['cloud_points']={'width':msg.width,'height':msg.height,
                'point_step':msg.point_step,'row_step':msg.row_step,'frame_id':msg.header.frame_id}

    @staticmethod
    def stream_rate(rows):
        stamps=sorted({row['stamp_s'] for row in rows})
        gaps=[b-a for a,b in zip(stamps,stamps[1:])]
        return {'first_stamp_s':stamps[0] if stamps else None,
                'last_stamp_s':stamps[-1] if stamps else None,
                'average_hz':(len(stamps)-1)/(stamps[-1]-stamps[0]) if len(stamps)>1 and stamps[-1]>stamps[0] else 0.0,
                'max_gap_s':max(gaps) if gaps else None}

    def on_api(self,msg):
        if msg.request_id==self.request_id:
            self.response=json.loads(msg.json_msg)
            self.task_id=(self.response.get('state',{}).get('booking',{})).get('id')

    def on_fleet(self,msg):
        if msg.name!='warehouse_energy':return
        robot=next((r for r in msg.robots if r.name=='robot_1'),None)
        if robot is None:return
        self.robot={'task_id':robot.task_id,'mode':int(robot.mode.mode),'x':robot.location.x,'y':robot.location.y}
        if self.task_id and robot.task_id==self.task_id:self.seen_task=True

    def on_plan(self,msg):
        self.plans.append({'wall_time':time.time(),'xy':[[p.pose.position.x,p.pose.position.y] for p in msg.poses]})

    def on_itinerary(self,msg):
        self.itineraries.append({'wall_time':time.time(),'participant':msg.participant,'plan':msg.plan,
            'version':msg.itinerary_version,'routes':[{'map':r.map,'points':[list(w.position) for w in r.trajectory.waypoints]}
                                                    for r in msg.itinerary]})

    def on_mirror(self,msg):
        self.mirrors.append({'wall_time':time.time(),'database_version':msg.database_version,
            'participants':[{'participant':p.participant_id,'version':p.itinerary_version,
                'routes':[{'map':item.route.map,'points':[list(w.position) for w in item.route.trajectory.waypoints]}
                          for item in p.additions.items]} for p in msg.patch.participants]})

    def spin(self):
        rclpy.spin_once(self,timeout_sec=.02)
        for topic,types in self.get_topic_names_and_types():
            if 'rmf_traffic_msgs/msg/ItinerarySet' in types and topic not in self.subscribed:
                self.dynamic_subs.append(self.create_subscription(ItinerarySet,topic,self.on_itinerary,100))
                self.subscribed.add(topic)
            if 'rmf_traffic_msgs/msg/MirrorUpdate' in types and topic not in self.subscribed:
                self.dynamic_subs.append(self.create_subscription(MirrorUpdate,topic,self.on_mirror,100))
                self.subscribed.add(topic)

    def wait(self,predicate,timeout,label):
        deadline=time.monotonic()+timeout
        while time.monotonic()<deadline:
            self.spin()
            if predicate():return
        raise TimeoutError(label)

    def run(self):
        semantic_enabled=self.design.get('semantic_fixture',{}).get('enabled',False)
        self.wait(lambda:self.robot is not None and self.physics and self.clock and self.pub.get_subscription_count()
                  and len(self.rgb_samples)>=3 and len(self.depth_samples)>=3 and self.camera_info_samples
                  and (not semantic_enabled or any(row.get('ready') and row.get('last_result')
                                                   for row in self.semantic_status)),
                  180,'fleet/physics/dispatcher/RGB-D startup')
        self.wait(lambda:self.camera_tf_samples,30,'full-pose camera transform')
        for name,client in self.lifecycle_clients.items():
            self.wait(lambda:client.service_is_ready(),30,f'{name} lifecycle service')
            for _ in range(30):
                future=client.call_async(GetState.Request())
                self.wait(future.done,5,f'{name} lifecycle response')
                if future.result().current_state.id==3:break
                until=time.monotonic()+1
                while time.monotonic()<until:self.spin()
            else:raise RuntimeError(f'{name} inactive')
        self.wait(lambda:any('itinerary_set' in t for t in self.subscribed)
                  and any('query_update' in t for t in self.subscribed),30,'RMF itinerary/mirror topic not discovered')
        path=self.design['path']
        request={'type':'dispatch_task_request','request':{'category':'compose','fleet_name':'warehouse_energy',
            'requester':'warehouse-phase0','unix_millis_request_time':self.clock,'unix_millis_earliest_start_time':self.clock,
            'description':{'category':'warehouse_route','phases':[{'activity':{'category':'go_to_place',
                'description':{'one_of':[{'waypoint':p}]}}} for p in path[1:]]}}}
        (self.output/'task-request.json').write_text(json.dumps(request,indent=2)+'\n')
        # Optional presentation hold: with WAREHOUSE_DEMO_HOLD set to a file
        # path, wait (bounded) for that file to appear before the first
        # dispatch. The robot, sensors and RMF are already up and visible.
        hold=os.environ.get('WAREHOUSE_DEMO_HOLD')
        if hold:
            print(json.dumps({'event':'presentation_hold','waiting_for':hold}),flush=True)
            deadline=time.monotonic()+1800
            while time.monotonic()<deadline and not os.path.exists(hold):
                self.spin();time.sleep(.2)
            print(json.dumps({'event':'presentation_hold_released'}),flush=True)
        self.request_id=str(uuid.uuid4());self.dispatched_at=time.time()
        self.pub.publish(ApiRequest(request_id=self.request_id,json_msg=json.dumps(request)))
        self.wait(lambda:self.response is not None,30,'task API response')
        if not self.response.get('success') or not self.task_id:raise RuntimeError(f'RMF rejected: {self.response}')
        print(json.dumps({'event':'dispatched','task_id':self.task_id}),flush=True)
        end=self.design['nodes'][path[-1]];deadline=time.monotonic()+900;report_at=0
        while time.monotonic()<deadline:
            self.spin();physical=self.physics[-1]
            if physical.get('fault'):raise RuntimeError(physical['fault'])
            if time.time()-physical['wall_time']>2:raise RuntimeError('stale physical evidence')
            terminal=[e for e in self.events if e['event']=='nav2_terminal']
            if any(e['status']!=4 for e in terminal):raise RuntimeError('Nav2 action failed')
            if time.monotonic()>report_at:
                print(json.dumps({'event':'progress','task_id':self.task_id,'xy':[physical['x'],physical['y']],
                    'goals_succeeded':len(terminal),'itineraries':len(self.itineraries)}),flush=True);report_at=time.monotonic()+20
            if (self.seen_task and self.robot and not self.robot['task_id'] and self.robot['mode']==0
                and terminal and math.hypot(physical['x']-end[0],physical['y']-end[1])<.12
                and physical.get('speed_mps',1)<.02):return
        raise TimeoutError('warehouse task completion')

    def audit(self,error=None):
        errors=[error] if error else []
        path=self.design['path'];nodes=self.design['nodes'];edges=[(nodes[a],nodes[b]) for a,b in zip(path,path[1:])]
        physical=[p for p in self.physics if self.dispatched_at and p['wall_time']>=self.dispatched_at]
        itinerary=[p for row in self.itineraries if self.dispatched_at and row['wall_time']>=self.dispatched_at
                   for route in row['routes'] for p in route['points']]
        mirrored=[p for row in self.mirrors if self.dispatched_at and row['wall_time']>=self.dispatched_at
                  for participant in row['participants'] for route in participant['routes'] for p in route['points']]
        goals=[e for e in self.events if e['event']=='nav2_terminal']
        maximum_plan=max((min(distance_to_segment(*p,a,b) for a,b in edges)
                          for row in self.plans for p in row['xy']),default=999)
        maximum_itinerary=max((min(distance_to_segment(*p[:2],a,b) for a,b in edges) for p in itinerary),default=999)
        maximum_mirror=max((min(distance_to_segment(*p[:2],a,b) for a,b in edges) for p in mirrored),default=999)
        reached=[];cursor=0
        for p in physical:
            if cursor<len(path) and math.dist([p['x'],p['y']],nodes[path[cursor]][:2])<.20:
                reached.append(path[cursor]);cursor+=1
        goal_targets=[g['target'][:2] for g in goals];goal_cursor=0
        for target in goal_targets:
            if goal_cursor<len(path)-1 and math.dist(target,nodes[path[goal_cursor+1]][:2])<.01:goal_cursor+=1
        if reached!=path:errors.append(f'physical ordered waypoint mismatch: {reached}')
        if goal_cursor!=len(path)-1:errors.append('Nav2 ordered target mismatch')
        if not itinerary or maximum_itinerary>.71:errors.append('RMF itinerary outside selected corridor or missing')
        if not mirrored or maximum_mirror>.71:errors.append('accepted schedule mirror outside selected corridor or missing')
        if maximum_plan>.71:errors.append('Nav2 plan outside selected corridor or missing')
        if len(self.rgb_samples)<3 or len(self.depth_samples)<3 or not self.camera_info_samples:
            errors.append('RGB-D stream/camera calibration missing')
        semantic=self.design.get('semantic_fixture',{})
        if semantic.get('enabled'):
            if not any(row.get('policy')=='avoid-target/v1' and row.get('prompt')=='red mat'
                       and row.get('active_labels')==[0,2] for row in self.semantic_labels):
                errors.append('semantic policy/label contract missing')
            if not self.semantic_masks or not self.semantic_timing:
                errors.append('live SAM3 mask/timing outputs missing')
            if not any(row['target_pixels']>0 for row in self.semantic_masks):
                errors.append('SAM3 produced no avoid_target pixels for the red mat fixture')
            if any(row['target_pixels']>0 for row in self.semantic_masks) and self.semantic_pair_count==0:
                errors.append('SAM3 nonempty masks could not be paired with their raw RGB captures')
            if not any(row.get('ready') and row.get('last_result') for row in self.semantic_status):
                errors.append('SAM3 did not reach a valid ready state')
        camera=self.design.get('camera',{'width':640,'height':480})
        if any(s['width']!=camera['width'] or s['height']!=camera['height'] or s['data_bytes']==0
               for s in self.rgb_samples+self.depth_samples):
            errors.append('RGB-D image dimensions/data invalid')
        if any(b['stamp_s']<a['stamp_s'] for rows in [self.rgb_samples,self.depth_samples]
               for a,b in zip(rows,rows[1:])):
            errors.append('RGB-D simulation timestamps are not increasing')
        tf_deltas=[]
        if self.camera_tf_samples:
            for sample in [self.rgb_samples[-1] if self.rgb_samples else None,
                           self.depth_samples[-1] if self.depth_samples else None]:
                if sample:
                    tf_deltas.append(min(abs(sample['stamp_s']-tf['stamp_s']) for tf in self.camera_tf_samples))
        if not self.camera_tf_samples or any(tf['parent']!='odom' for tf in self.camera_tf_samples):
            errors.append('full-pose camera TF is missing or has an unexpected parent')
        if not tf_deltas or max(tf_deltas)>.06:
            errors.append('RGB-D capture stamps lack a nearby full-pose camera transform')
        battery=[e for e in self.events if e['event']=='battery_state']
        if not battery or any(not 0<=e['soc']<=1 or e['cumulative_wh']<0 for e in battery):
            errors.append('missing or invalid adapter battery telemetry')
        if not self.seen_task:errors.append('task not observed in fleet state')
        if not goals or any(g['status']!=4 or not g['goal_id'] for g in goals):errors.append('missing/failed correlated Nav2 terminals')
        for n in path[1:]:
            if not any(math.dist(p[:2],nodes[n][:2])<.15 for p in itinerary):errors.append(f'itinerary missing {n}')
            if not any(math.dist(p[:2],nodes[n][:2])<.15 for p in mirrored):errors.append(f'accepted schedule missing {n}')
        result={'status':'FAIL' if errors else 'PASS','errors':errors,'task_id':self.task_id,
            'request_id':self.request_id,'response':self.response,'selected_path':path,'physical_waypoints':reached,
            'nav2_goals':goals,'itinerary_messages':len(self.itineraries),'itinerary_topics':sorted(self.subscribed),
            'schedule_mirror_messages':len(self.mirrors),'maximum_schedule_centerline_distance_m':maximum_mirror,
            'maximum_itinerary_centerline_distance_m':maximum_itinerary,'maximum_plan_centerline_distance_m':maximum_plan,
            'final_fleet':self.robot,'physical_samples':len(physical),'final_physical':physical[-1] if physical else None,
            'semantic':({'enabled':True,'prompt':'red mat','policy':'avoid-target/v1',
                'label_info':self.semantic_labels[-1] if self.semantic_labels else None,
                'mask_samples':len(self.semantic_masks),'nonempty_target_masks':sum(row['target_pixels']>0 for row in self.semantic_masks),
                'saved_rgb_mask_pairs':self.semantic_pair_count,
                'timing_samples':len(self.semantic_timing),'status':self.semantic_status[-1] if self.semantic_status else None,
                'timing_artifact':'semantic-timing.jsonl','mask_artifact':'semantic-masks.jsonl'}
                if semantic.get('enabled') else {'enabled':False}),
            'rgbd':{'rgb_samples':len(self.rgb_samples),'depth_samples':len(self.depth_samples),
                'configured_rate_hz':camera.get('configured_rate_hz',10),
                'rgb_rate':self.stream_rate(self.rgb_samples),'depth_rate':self.stream_rate(self.depth_samples),
                'camera_info_samples':len(self.camera_info_samples),'rgb_latest':self.rgb_samples[-1] if self.rgb_samples else None,
                'depth_latest':self.depth_samples[-1] if self.depth_samples else None,
                'camera_info':self.camera_info_samples[-1] if self.camera_info_samples else None,
                'camera_tf_samples':self.camera_tf_count,
                'camera_tf_latest':self.camera_tf_samples[-1] if self.camera_tf_samples else None,
                'capture_tf_nearest_delta_s':tf_deltas},
            'battery_state_samples':len(battery),
            'scope':'simulation sensing and modeled battery telemetry; SAM3 warehouse semantic labels and electrical calibration remain unqualified'}
        for name,rows in [('itineraries',self.itineraries),('schedule-mirror',self.mirrors),('plans',self.plans),('observed-physics',self.physics)]:
            (self.output/f'{name}.jsonl').write_text(''.join(json.dumps(row)+'\n' for row in rows))
        (self.output/'sensing.json').write_text(json.dumps(result['rgbd'],indent=2)+'\n')
        (self.output/'result.json').write_text(json.dumps(result,indent=2)+'\n')
        return result


if __name__=='__main__':
    rclpy.init();node=Trial();error=None
    try:node.run()
    except Exception as exc:
        error=str(exc)
        if node.task_id:
            node.pub.publish(ApiRequest(request_id=str(uuid.uuid4()),json_msg=json.dumps({
                'type':'cancel_task_request','task_id':node.task_id,'requester':'warehouse-phase0'})))
            until=time.monotonic()+2
            while time.monotonic()<until:rclpy.spin_once(node,timeout_sec=.05)
    result=node.audit(error);print(json.dumps(result),flush=True)
    node.destroy_node();rclpy.try_shutdown();raise SystemExit(result['status']!='PASS')
