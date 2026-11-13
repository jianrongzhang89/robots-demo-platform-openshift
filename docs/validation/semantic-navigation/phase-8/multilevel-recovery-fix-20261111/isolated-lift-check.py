import json,time
import rclpy
from rclpy.node import Node
from rmf_lift_msgs.msg import LiftRequest,LiftState
from std_msgs.msg import String
rclpy.init();node=Node('phase8_isolated_lift_check')
pub=node.create_publisher(LiftRequest,'/lift_requests',10)
state={};physical={};history=[]
def lift(m):
 if m.lift_name=='Lift2':state.update(floor=m.current_floor,motion=m.motion_state,door=m.door_state)
def pose(m):
 physical.update(json.loads(m.data));history.append(dict(physical))
node.create_subscription(LiftState,'/lift_states',lift,10)
node.create_subscription(String,'/phase8/physics',pose,5)
try:
 for floor in ['L1','L3','L1']:
  deadline=time.monotonic()+180;lastpub=0;lastreport=0
  while time.monotonic()<deadline:
   rclpy.spin_once(node,timeout_sec=.1)
   now=time.monotonic()
   if physical and (physical['z']<-.1 or abs(physical['z']-physical['lift2_z'])>.2):
    raise RuntimeError(f'lost lift support: {physical}')
   if now-lastpub>1:
    m=LiftRequest(lift_name='Lift2',destination_floor=floor,session_id='phase8-isolated-support-test',request_type=LiftRequest.REQUEST_AGV_MODE,door_state=LiftRequest.DOOR_OPEN);pub.publish(m);lastpub=now
   if now-lastreport>5:print(json.dumps({'target':floor,'state':state,'physical':physical}),flush=True);lastreport=now
   if state.get('floor')==floor and state.get('motion')==LiftState.MOTION_STOPPED and state.get('door')==LiftState.DOOR_OPEN and abs(physical.get('z',-100)-{'L1':0,'L3':16}[floor])<.1:break
  else:raise TimeoutError(f'failed to reach {floor}')
 print('PASS physical lift L1 -> L3 -> L1',flush=True)
finally:
 open('/tmp/phase8-isolated-lift-physics.json','w').write(json.dumps(history))
 node.destroy_node();rclpy.try_shutdown()
