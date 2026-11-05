"""Payload validation for the pinned hotel sensor bridge (no ROS imports)."""
import math


def valid_scan(message, *, expected_max_range=3.5):
    return (expected_max_range in (3.5,12.)
            and message.header.frame_id=="lidar_frame" and len(message.ranges)==360
            and all(math.isfinite(v) for v in (message.range_min,message.range_max,
                                              message.angle_min,message.angle_max,message.angle_increment))
            and 0<=message.range_min<message.range_max
            and math.isclose(message.range_max,expected_max_range,rel_tol=0,abs_tol=1e-6)
            and message.angle_increment>0
            # REP-117: +Inf is a legitimate no-return reading, including an
            # entirely open scan. NaN is erroneous; -Inf means too close.
            # Neither of the latter may silently become clear space.
            and all(not math.isnan(v) and v>=0 for v in message.ranges))


def valid_odom(message):
    p,q=message.pose.pose.position,message.pose.pose.orientation
    linear,angular=message.twist.twist.linear,message.twist.twist.angular
    values=(p.x,p.y,p.z,q.x,q.y,q.z,q.w,linear.x,linear.y,linear.z,angular.x,angular.y,angular.z)
    return (message.header.frame_id=="odom" and message.child_frame_id=="base_footprint"
            and all(math.isfinite(v) for v in values)
            and abs(sum(v*v for v in (q.x,q.y,q.z,q.w))-1)<.01)
