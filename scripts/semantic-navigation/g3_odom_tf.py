"""Capture-stamped odometry TF for the private G3 observer; no commands."""
import math
import rclpy
from rclpy.node import Node
from nav_msgs.msg import Odometry
from geometry_msgs.msg import TransformStamped
from tf2_ros import TransformBroadcaster

rclpy.init(args=['--ros-args','-r','/tf:=/robot_1/tf']); node=Node('g3_odometry_tf'); broadcaster=TransformBroadcaster(node)
origin=None; previous=None

def receive(msg):
    global origin, previous
    stamp=msg.header.stamp.sec*10**9+msg.header.stamp.nanosec
    p=msg.pose.pose.position; q=msg.pose.pose.orientation
    yaw=math.atan2(2*(q.w*q.z+q.x*q.y),1-2*(q.y*q.y+q.z*q.z))
    if origin is None or previous is not None and stamp<previous:
        origin=(p.x,p.y,yaw)
    previous=stamp
    dx,dy=p.x-origin[0],p.y-origin[1]; c,s=math.cos(origin[2]),math.sin(origin[2])
    t=TransformStamped();t.header.stamp=msg.header.stamp;t.header.frame_id='odom';t.child_frame_id='base_footprint'
    t.transform.translation.x=c*dx+s*dy;t.transform.translation.y=-s*dx+c*dy
    t.transform.rotation.z=math.sin((yaw-origin[2])/2);t.transform.rotation.w=math.cos((yaw-origin[2])/2)
    broadcaster.sendTransform(t)
node.create_subscription(Odometry,'/robot_1/odom',receive,50)
rclpy.spin(node)
