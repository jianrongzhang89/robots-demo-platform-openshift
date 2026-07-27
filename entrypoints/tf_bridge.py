#!/usr/bin/env python3
"""
TF bridge: re-publish the peer robot's dynamic and static TF transforms into
the own robot's namespace TF topic so that the Nav2 costmap can transform the
peer robot's scan data into the local reference frame.

Usage (called from entrypoint-nav2.sh):
  ros2 run --ros-args ... python3 /tf_bridge.py <own_namespace> <peer_namespace>

The node subscribes to:
  /<peer_ns>/tf        (absolute, from Zenoh-bridged peer pod)
  /<peer_ns>/tf_static (absolute, transient-local QoS)

And publishes to:
  tf        (relative → /<own_ns>/tf,        read by Nav2's TF2 buffer)
  tf_static (relative → /<own_ns>/tf_static, read by Nav2's TF2 buffer)

Because Nav2 nodes in namespace <own_ns> remap /tf → tf and /tf_static →
tf_static, they subscribe to /<own_ns>/tf. Publishing to the same topic
(via the relative name) makes the peer robot's frames visible to Nav2's
TF2 buffer without any changes to Nav2 itself.
"""

import sys
import rclpy
from rclpy.node import Node
from rclpy.qos import QoSProfile, DurabilityPolicy, HistoryPolicy, ReliabilityPolicy
from tf2_msgs.msg import TFMessage


def main():
    if len(sys.argv) != 3:
        print(f'Usage: {sys.argv[0]} <own_namespace> <peer_namespace>', file=sys.stderr)
        sys.exit(1)

    own_ns  = sys.argv[1].lstrip('/')
    peer_ns = sys.argv[2].lstrip('/')

    rclpy.init()

    node = Node('tf_bridge', namespace=own_ns)

    # QoS for dynamic TF: reliable, keep last 100
    dyn_qos = QoSProfile(
        depth=100,
        reliability=ReliabilityPolicy.RELIABLE,
        history=HistoryPolicy.KEEP_LAST,
        durability=DurabilityPolicy.VOLATILE,
    )

    # QoS for static TF: transient-local so late subscribers receive the
    # last published message (equivalent to ROS 1 latched topics).
    static_qos = QoSProfile(
        depth=100,
        reliability=ReliabilityPolicy.RELIABLE,
        history=HistoryPolicy.KEEP_LAST,
        durability=DurabilityPolicy.TRANSIENT_LOCAL,
    )

    # Publishers: relative topics → /<own_ns>/tf and /<own_ns>/tf_static
    pub_dyn    = node.create_publisher(TFMessage, 'tf',        dyn_qos)
    pub_static = node.create_publisher(TFMessage, 'tf_static', static_qos)

    # Subscribers: absolute topics — receive peer robot's transforms via Zenoh bridge
    node.create_subscription(
        TFMessage,
        f'/{peer_ns}/tf',
        lambda msg: pub_dyn.publish(msg),
        dyn_qos,
    )
    node.create_subscription(
        TFMessage,
        f'/{peer_ns}/tf_static',
        lambda msg: pub_static.publish(msg),
        static_qos,
    )

    node.get_logger().info(
        f'tf_bridge: merging /{peer_ns}/tf[_static] → /{own_ns}/tf[_static]'
    )

    try:
        rclpy.spin(node)
    except KeyboardInterrupt:
        pass
    finally:
        node.destroy_node()
        rclpy.shutdown()


if __name__ == '__main__':
    main()
