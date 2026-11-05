#!/usr/bin/env python3
"""Compare local DDS discovery in isolated domains; no camera/model needed.

Run inside a ROS Jazzy environment containing both DDS RMW packages. Each case
starts fresh processes (no ros2 CLI daemon) and uses only /semantic_dds_audit.
"""
import json
import os
import subprocess
import sys
import time

CYCLONE_XML = '''<CycloneDDS><Domain id="any"><General><Interfaces>
<NetworkInterface name="lo" /></Interfaces><AllowMulticast>false</AllowMulticast>
</General><Discovery><ParticipantIndex>auto</ParticipantIndex></Discovery>
</Domain></CycloneDDS>'''

CHILD = '''
import json, sys, time
import rclpy
from rclpy.utilities import get_rmw_implementation_identifier
from std_msgs.msg import UInt32
rclpy.init()
role = sys.argv[1]
node = rclpy.create_node("semantic_dds_audit_" + role, enable_rosout=False)
counts = {"sent": 0, "received": 0, "publishers_peak": 0}
if role == "publisher":
    pub = node.create_publisher(UInt32, "/semantic_dds_audit", 20)
    def publish():
        counts["sent"] += 1
        pub.publish(UInt32(data=counts["sent"]))
    node.create_timer(0.05, publish)
else:
    def receive(msg):
        counts["received"] += 1
    node.create_subscription(UInt32, "/semantic_dds_audit", receive, 20)
end = time.monotonic() + (14 if role == "publisher" else 10)
while time.monotonic() < end:
    rclpy.spin_once(node, timeout_sec=0.05)
    counts["publishers_peak"] = max(counts["publishers_peak"], node.count_publishers("/semantic_dds_audit"))
print(json.dumps({"role": role, "rmw": get_rmw_implementation_identifier(), **counts}), flush=True)
node.destroy_node()
rclpy.shutdown()
'''


def main():
    cases = [
        ("fastdds_default", "rmw_fastrtps_cpp", "SUBNET"),
        ("fastdds_localhost", "rmw_fastrtps_cpp", "LOCALHOST"),
        ("cyclone_matching_config", "rmw_cyclonedds_cpp", "SUBNET"),
        ("fastdds_default_repeat", "rmw_fastrtps_cpp", "SUBNET"),
    ]
    for number, (name, rmw, discovery) in enumerate(cases):
        env = dict(os.environ)
        for key in ("ROS_LOCALHOST_ONLY", "ROS_STATIC_PEERS", "ROS_DISCOVERY_SERVER",
                    "FASTDDS_DEFAULT_PROFILES_FILE", "FASTRTPS_DEFAULT_PROFILES_FILE"):
            env.pop(key, None)
        env.update(ROS_DOMAIN_ID=str(86 + number), CYCLONEDDS_URI=CYCLONE_XML,
                   RMW_IMPLEMENTATION="rmw_cyclonedds_cpp",
                   ROS_LOG_DIR="/tmp/semantic-dds-audit-log",
                   ROS_AUTOMATIC_DISCOVERY_RANGE="SUBNET")
        publisher = subprocess.Popen([sys.executable, "-c", CHILD, "publisher"],
                                     env=env, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
        try:
            time.sleep(0.5)
            receiver_env = dict(env, RMW_IMPLEMENTATION=rmw,
                                ROS_AUTOMATIC_DISCOVERY_RANGE=discovery)
            receiver = subprocess.run([sys.executable, "-c", CHILD, "subscriber"],
                                      env=receiver_env, capture_output=True, text=True, timeout=18)
            pub_stdout, pub_stderr = publisher.communicate(timeout=8)
            print(json.dumps({"case": name, "domain": env["ROS_DOMAIN_ID"],
                              "receiver_rc": receiver.returncode,
                              "receiver": receiver.stdout.strip(),
                              "receiver_stderr": receiver.stderr.strip(),
                              "publisher_rc": publisher.returncode,
                              "publisher": pub_stdout.strip(),
                              "publisher_stderr": pub_stderr.strip()}), flush=True)
            if receiver.returncode != 0 or publisher.returncode != 0:
                raise RuntimeError(f"{name}: process initialization/execution failed; no discovery conclusion")
        finally:
            if publisher.poll() is None:
                publisher.terminate()
                publisher.wait(timeout=5)


if __name__ == "__main__":
    main()
