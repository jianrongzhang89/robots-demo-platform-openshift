#!/usr/bin/env python3
"""Simulator-only measured pose/clock bridge and bounded wheel-command conversion."""
import json
import math
import os
from pathlib import Path
import threading
import time

import rclpy
from rclpy.node import Node as RosNode
from geometry_msgs.msg import Twist, TransformStamped
from nav_msgs.msg import Odometry
from rosgraph_msgs.msg import Clock
from std_msgs.msg import String
from tf2_ros import TransformBroadcaster, StaticTransformBroadcaster
from gz.transport13 import Node
from gz.msgs10.pose_v_pb2 import Pose_V
from gz.msgs10.clock_pb2 import Clock as GzClock
from gz.msgs10.double_pb2 import Double
from build_fixture import elevation
from build_navigation import distance_to_segment


def quaternion_multiply(a,b):
    ax,ay,az,aw=a;bx,by,bz,bw=b
    return (aw*bx+ax*bw+ay*bz-az*by,
            aw*by-ax*bz+ay*bw+az*bx,
            aw*bz+ax*by-ay*bx+az*bw,
            aw*bw-ax*bx-ay*by-az*bz)


def quaternion_rotate(q,v):
    p=(*v,0.0);inverse=(-q[0],-q[1],-q[2],q[3])
    return quaternion_multiply(quaternion_multiply(q,p),inverse)[:3]


def quaternion_from_euler(roll,pitch,yaw):
    cr,sr=math.cos(roll/2),math.sin(roll/2)
    cp,sp=math.cos(pitch/2),math.sin(pitch/2)
    cy,sy=math.cos(yaw/2),math.sin(yaw/2)
    return (sr*cp*cy-cr*sp*sy,cr*sp*cy+sr*cp*sy,
            cr*cp*sy-sr*sp*cy,cr*cp*cy+sr*sp*sy)


class Bridge(RosNode):
    def __init__(self):
        super().__init__('warehouse_physical_bridge')
        self.design=json.loads(Path(os.environ['WAREHOUSE_RUN_DIR'],'design.json').read_text())
        self.camera_tilt=float(self.design.get('camera',{}).get('downward_tilt_rad',0.0))
        self.trace=open(Path(os.environ['WAREHOUSE_RUN_DIR'],'physical.jsonl'),'a',buffering=1)
        self.pose=None;self.clock=None;self.previous=None;self.command=(0.,0.)
        self.command_at=0.;self.speed=0.;self.angular=0.;self.last_command_sim=None
        self.last_publish=-1.;self.fault=None;self.gz=Node();self.lock=threading.RLock()
        self.gz.subscribe(Pose_V,'/world/warehouse/pose/info',self.on_pose)
        self.gz.subscribe(GzClock,'/world/warehouse/clock',self.on_clock)
        self.wheels=[self.gz.advertise(f'/warehouse/{s}/cmd_vel',Double) for s in ['left','right']]
        self.clock_pub=self.create_publisher(Clock,'/clock',10)
        self.odom_pub=self.create_publisher(Odometry,'/odom',10)
        self.physics_pub=self.create_publisher(String,'/warehouse/physics',10)
        self.create_subscription(Twist,'/cmd_vel',self.on_command,10)
        self.tf=TransformBroadcaster(self);self.static=StaticTransformBroadcaster(self)
        transform=TransformStamped();transform.header.frame_id='map';transform.child_frame_id='odom'
        transform.transform.rotation.w=1.;self.static.sendTransform(transform)
        self.create_timer(.005,self.tick)

    def on_clock(self,msg):
        with self.lock:self.clock=(msg.sim.sec,msg.sim.nsec)

    def on_pose(self,msg):
        p=next((p for p in msg.pose if p.name=='robot_1'),None)
        if p is None:return
        q=p.orientation
        with self.lock:self.pose={'sim_s':msg.header.stamp.sec+msg.header.stamp.nsec*1e-9,
            'stamp':(msg.header.stamp.sec,msg.header.stamp.nsec),'x':p.position.x,'y':p.position.y,'z':p.position.z,
            'qx':q.x,'qy':q.y,'qz':q.z,'qw':q.w,
            'yaw':math.atan2(2*(q.w*q.z+q.x*q.y),1-2*(q.y*q.y+q.z*q.z)),
            'roll':math.atan2(2*(q.w*q.x+q.y*q.z),1-2*(q.x*q.x+q.y*q.y)),
            'pitch':math.asin(max(-1,min(1,2*(q.w*q.y-q.z*q.x)))),'received_wall':time.monotonic()}

    def on_command(self,msg):
        with self.lock:self.command=(msg.linear.x,msg.angular.z);self.command_at=time.monotonic()

    def tick(self):
        with self.lock:
            clock=self.clock;row=dict(self.pose) if self.pose else None
            command=self.command;command_at=self.command_at
        if clock is None:return
        msg=Clock();msg.clock.sec,msg.clock.nanosec=clock;self.clock_pub.publish(msg)
        sim=clock[0]+clock[1]*1e-9
        dt=0 if self.last_command_sim is None else max(0,min(.1,sim-self.last_command_sim))
        self.last_command_sim=sim
        nodes=self.design['nodes'];path=self.design['path']
        edges=[(nodes[a],nodes[b]) for a,b in zip(path,path[1:])]
        if row:
            nearest=min(edges,key=lambda edge:distance_to_segment(row['x'],row['y'],*edge))
            distance=distance_to_segment(row['x'],row['y'],*nearest)
            a,b=nearest
            if a[2]!=b[2]:
                run=10 if self.design['route']=='A' else 20
                ground=elevation(row['x']-2,run)
            else:ground=a[2]
            row['corridor_distance_m']=distance;row['support_error_m']=row['z']-ground-.01
            if distance>.40:self.fault='corridor_departure'
            if abs(row['support_error_m'])>.06:self.fault='support_loss'
            if abs(row['pitch'])>.10 or abs(row['roll'])>.12:self.fault='attitude_limit'
        fresh=row and time.monotonic()-row['received_wall']<.5
        v,w=command if fresh and not self.fault and time.monotonic()-command_at<.5 else (0.,0.)
        if not math.isfinite(v) or not math.isfinite(w):self.fault='nonfinite_command';v=w=0.
        v=max(-.1,min(.1,v));w=max(-.45,min(.45,w))
        self.speed+=max(-.1*dt,min(.1*dt,v-self.speed))
        self.angular+=max(-.5*dt,min(.5*dt,w-self.angular))
        for pub,val in zip(self.wheels,[(self.speed-self.angular*.288/2)/.033,(self.speed+self.angular*.288/2)/.033]):
            pub.publish(Double(data=val))
        if not row or not fresh or row['sim_s']<=self.last_publish:return
        self.last_publish=row['sim_s']
        odom=Odometry();odom.header.stamp.sec,odom.header.stamp.nanosec=row['stamp']
        odom.header.frame_id='odom';odom.child_frame_id='base_footprint'
        odom.pose.pose.position.x=row['x'];odom.pose.pose.position.y=row['y']
        odom.pose.pose.orientation.z=math.sin(row['yaw']/2);odom.pose.pose.orientation.w=math.cos(row['yaw']/2)
        if self.previous:
            delta=row['sim_s']-self.previous['sim_s']
            if delta>0:
                vx=(row['x']-self.previous['x'])/delta;vy=(row['y']-self.previous['y'])/delta
                odom.twist.twist.linear.x=math.cos(row['yaw'])*vx+math.sin(row['yaw'])*vy
                odom.twist.twist.angular.z=math.atan2(math.sin(row['yaw']-self.previous['yaw']),math.cos(row['yaw']-self.previous['yaw']))/delta
                row['speed_mps']=math.hypot(vx,vy)
                if row['speed_mps']>.16:self.fault='physical_overspeed'
        self.previous=row.copy();self.odom_pub.publish(odom)
        tf=TransformStamped();tf.header=odom.header;tf.child_frame_id='base_footprint'
        tf.transform.translation.x=row['x'];tf.transform.translation.y=row['y']
        tf.transform.rotation=odom.pose.pose.orientation;self.tf.sendTransform(tf)
        # Sensor consumers use the capture-time 3D camera transform. Keep this
        # independent from Nav2's planar base_footprint transform so pitch and
        # roll on the ramp are retained without changing the planar controller.
        robot_q=(row['qx'],row['qy'],row['qz'],row['qw'])
        camera_offset=quaternion_rotate(robot_q,(.11,0.,.15))
        optical_q=quaternion_from_euler(-math.pi/2,0.,-math.pi/2)
        sensor_mount_q=quaternion_from_euler(0.,self.camera_tilt,0.)
        camera_q=quaternion_multiply(robot_q,quaternion_multiply(sensor_mount_q,optical_q))
        camera=TransformStamped();camera.header=odom.header
        camera.child_frame_id='camera_color_optical_frame'
        camera.transform.translation.x=row['x']+camera_offset[0]
        camera.transform.translation.y=row['y']+camera_offset[1]
        camera.transform.translation.z=row['z']+camera_offset[2]
        camera.transform.rotation.x,camera.transform.rotation.y,camera.transform.rotation.z,camera.transform.rotation.w=camera_q
        self.tf.sendTransform(camera)
        row.update(command_mps=self.speed,command_rad_s=self.angular,fault=self.fault,wall_time=time.time())
        row.pop('stamp');row.pop('received_wall')
        payload=json.dumps(row);self.physics_pub.publish(String(data=payload));self.trace.write(payload+'\n')


if __name__=='__main__':
    rclpy.init();node=Bridge()
    try:rclpy.spin(node)
    finally:
        for pub in node.wheels:pub.publish(Double(data=0.))
        node.trace.close();node.destroy_node();rclpy.try_shutdown()
