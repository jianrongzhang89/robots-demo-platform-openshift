import json,time,math
import rclpy
from rclpy.node import Node
from rclpy.action import ActionClient
from rmf_lift_msgs.msg import LiftRequest,LiftState
from nav2_msgs.action import BackUp
from std_msgs.msg import String
from gz.transport13 import Node as GzNode
from gz.msgs10.empty_pb2 import Empty
from gz.msgs10.stringmsg_pb2 import StringMsg
rclpy.init();node=Node('phase8_payload_fixture')
pub=node.create_publisher(LiftRequest,'/lift_requests',10)
state={};physical={};history=[];joint={'state':None}
gz=GzNode();ap=gz.advertise('/phase8/lift2/attach',Empty);dp=gz.advertise('/phase8/lift2/detach',Empty)
gz.subscribe(StringMsg,'/phase8/lift2/joint_state',lambda m:joint.update(state=m.data))
def lift(m):
 if m.lift_name=='Lift2':state.update(floor=m.current_floor,motion=m.motion_state,door=m.door_state)
def pose(m):
 physical.update(json.loads(m.data));history.append(dict(physical,joint_state=joint['state']))
node.create_subscription(LiftState,'/lift_states',lift,10)
node.create_subscription(String,'/phase8/physics',pose,5)
def wait(seconds):
 end=time.monotonic()+seconds
 while time.monotonic()<end:rclpy.spin_once(node,timeout_sec=.05)
def constraint(attached):
 before=dict(physical);target='attached' if attached else 'detached';end=time.monotonic()+10
 while joint['state']!=target and time.monotonic()<end:
  (ap if attached else dp).publish(Empty());wait(.2)
 assert joint['state']==target,f'no {target} acknowledgment'
 wait(.5)
 assert math.dist([before[k] for k in ('x','y','z')],[physical[k] for k in ('x','y','z')])<.03,'joint changed robot pose'
 print(json.dumps({'joint':target,'physical':physical}),flush=True)
def trip(floor):
 deadline=time.monotonic()+180;lastpub=0;lastreport=0
 while time.monotonic()<deadline:
  rclpy.spin_once(node,timeout_sec=.05);now=time.monotonic()
  if physical and (physical['z']<-.1 or abs(physical['z']-physical['lift2_z'])>.1):raise RuntimeError(f'lost support: {physical}')
  if now-lastpub>1:
   pub.publish(LiftRequest(lift_name='Lift2',destination_floor=floor,session_id='phase8-fixed-payload-test',request_type=LiftRequest.REQUEST_AGV_MODE,door_state=LiftRequest.DOOR_OPEN));lastpub=now
  if now-lastreport>10:print(json.dumps({'target':floor,'state':state,'physical':physical}),flush=True);lastreport=now
  if state.get('floor')==floor and state.get('motion')==LiftState.MOTION_STOPPED and state.get('door')==LiftState.DOOR_OPEN and abs(physical.get('z',-100)-{'L1':0,'L3':16}[floor])<.1:return
 raise TimeoutError(f'failed to reach {floor}')
try:
 wait(2);trip('L1')
 for cycle in range(3):
  constraint(True);trip('L3');constraint(False)
  constraint(True);trip('L1');constraint(False)
  before=dict(physical);a=ActionClient(node,BackUp,'/robot_1/backup');assert a.wait_for_server(timeout_sec=10)
  goal=BackUp.Goal();goal.target.x=-.05;goal.speed=.05;goal.time_allowance.sec=15
  f=a.send_goal_async(goal);rclpy.spin_until_future_complete(node,f);assert f.result().accepted
  result=f.result().get_result_async();rclpy.spin_until_future_complete(node,result,timeout_sec=60);assert result.done() and result.result().status==4,'Nav2 could not move after detach'
  wait(1);assert math.hypot(physical['x']-before['x'],physical['y']-before['y'])>.035,'robot remained constrained'
  print(f'PASS cycle {cycle+1}: ascent, descent, attachment acknowledgments and Nav2 motion after release',flush=True)
 print('PASS three physical payload round trips',flush=True)
finally:
 open('/tmp/phase8-payload-check-physics.json','w').write(json.dumps(history))
 node.destroy_node();rclpy.try_shutdown()
