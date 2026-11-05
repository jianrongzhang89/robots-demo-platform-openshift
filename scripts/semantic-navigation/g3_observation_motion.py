#!/usr/bin/env python3
"""Bounded private-simulator observation yaw sweep; semantic output is not consulted."""
import argparse
import json
import math
import os
import signal
from pathlib import Path
import time
import rclpy
from rclpy.node import Node
from nav_msgs.msg import Odometry
from geometry_msgs.msg import Twist


def main():
    p=argparse.ArgumentParser(description=__doc__);p.add_argument('--duration',type=float,default=610);p.add_argument('--output',type=Path,required=True);a=p.parse_args()
    if not 10<=a.duration<=650: p.error('duration must be 10..650 seconds')
    if a.output.exists():p.error('new output required')
    def interrupted(*_): raise KeyboardInterrupt()
    signal.signal(signal.SIGTERM, interrupted)
    os.environ['ROS_LOG_DIR']='/tmp/g3-motion-logs'
    rclpy.init();node=Node('g3_private_observation_motion');pub=node.create_publisher(Twist,'/robot_1/cmd_vel',10)
    latest=None;received=None;rows=[];result={'pass':False}
    def receive(msg):
        nonlocal latest,received
        latest=msg;received=time.monotonic()
    node.create_subscription(Odometry,'/robot_1/odom',receive,10)
    def spin(seconds):
        end=time.monotonic()+seconds
        while time.monotonic()<end:rclpy.spin_once(node,timeout_sec=.005)
    def yaw(msg):
        q=msg.pose.pose.orientation
        return math.atan2(2*(q.w*q.z+q.x*q.y),1-2*(q.y*q.y+q.z*q.z))
    try:
        deadline=time.monotonic()+10
        while latest is None and time.monotonic()<deadline:spin(.05)
        assert latest is not None,'no odometry'
        assert abs(latest.twist.twist.angular.z)<.01 and abs(latest.twist.twist.linear.x)<.01,'not stopped at start'
        initial=(latest.pose.pose.position.x,latest.pose.pose.position.y,yaw(latest));start=time.monotonic();sample=start
        while time.monotonic()-start<a.duration:
            if Path("/tmp/g3-motion-stop").exists(): raise RuntimeError("external stop requested")
            elapsed=time.monotonic()-start
            assert time.monotonic()-received<.5,'odometry stale; stop'
            pos=latest.pose.pose.position
            assert math.hypot(pos.x-initial[0],pos.y-initial[1])<.35,'unexpected translation; stop'
            angle=math.atan2(math.sin(yaw(latest)-initial[2]),math.cos(yaw(latest)-initial[2]))
            assert abs(angle)<.3,'yaw bound exceeded; stop'
            target=.12*math.sin(2*math.pi*elapsed/16)
            cmd=Twist();cmd.angular.z=max(-.08,min(.08,1.5*(target-angle)));pub.publish(cmd)
            if time.monotonic()>=sample:
                rows.append({'elapsed_s':elapsed,'stamp_ns':latest.header.stamp.sec*10**9+latest.header.stamp.nanosec,'wall_ns':time.time_ns(),'yaw_delta':angle,'angular_velocity':latest.twist.twist.angular.z,'command':cmd.angular.z,'x':pos.x,'y':pos.y});sample+=.2
            spin(.04)
        result['pass']=True
    except Exception as error:
        result['error']=repr(error);raise
    finally:
        for _ in range(30):pub.publish(Twist());spin(.04)
        result['stopped']=latest is not None and abs(latest.twist.twist.angular.z)<.01 and abs(latest.twist.twist.linear.x)<.01
        result['samples']=rows
        result['moving_fraction']=sum(abs(r['angular_velocity'])>.005 for r in rows)/max(1,len(rows))
        result['pass']=result['pass'] and result['stopped'] and result['moving_fraction']>.5
        a.output.write_text(json.dumps(result,indent=2)+'\n');node.destroy_node();rclpy.shutdown()
    if not result['pass']:raise SystemExit(1)

if __name__=='__main__':main()
