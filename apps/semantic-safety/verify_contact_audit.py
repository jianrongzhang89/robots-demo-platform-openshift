"""Disarmed positive control: physics contact with a known obstacle is detected."""
import json
import os
from pathlib import Path
import subprocess
import time
import signal
import threading
import xml.etree.ElementTree as ET
from gz.transport13 import Node
from gz.msgs10.stringmsg_pb2 import StringMsg
from prepare_assets import write_assets
from contact_evidence import instrument, collision_inventory
from support_geometry import add_rear_casters


def main():
    if os.getenv("GZ_IP")!="127.0.0.1" or not os.getenv("GZ_PARTITION","").startswith("phase5-watchdog-"):
        raise RuntimeError("private fixture required")
    out=Path("/tmp/phase5-native-results"); out.mkdir(exist_ok=False)
    write_assets(out/"assets")
    world=out/"assets/watchdog.world"
    rear_casters=os.getenv("PHASE5_REAR_CASTERS")=="1"
    world_text=world.read_text()
    if rear_casters:
        world_text,_=add_rear_casters(world_text,(out/"assets/robot.urdf").read_text())
    tree=ET.fromstring(instrument(world_text,rear_casters=rear_casters))
    tree.find("world").append(ET.fromstring('''<model name="contact_probe"><static>true</static>
      <pose>0.08 0.10 0.12 0 0 0</pose><link name="link"><collision name="obstacle">
      <geometry><box><size>0.08 0.08 0.2</size></box></geometry></collision></link></model>'''))
    world.write_text(ET.tostring(tree,encoding="unicode"))
    rows=[]; native=[]; lock=threading.Lock(); node=Node()
    def receive(m,target):
        with lock: target.append(json.loads(m.data))
    node.subscribe(StringMsg,"/phase5/contact_audit",lambda m:receive(m,rows))
    node.subscribe(StringMsg,"/phase5/drive/status",lambda m:receive(m,native))
    passed=False
    with (out/"gazebo.log").open("w") as log:
        server=subprocess.Popen(["gz","sim","--force-version","8","-r","-s",
            "--record-path",str(out/"gz-record"),str(world)],stdout=log,stderr=subprocess.STDOUT)
        try:
            until=time.monotonic()+15
            while time.monotonic()<until:
                with lock: snap=list(rows); drive=list(native)
                if snap and snap[-1]["steps"]>1000: break
                if server.poll() is not None: raise RuntimeError("contact fixture exited")
                time.sleep(.02)
            assert snap and drive,"contact/native observer missing"
            latest=snap[-1]
            assert latest["missing"]==0 and {m["name"] for m in latest["monitored"]}==collision_inventory(rear_casters),latest
            pairs=[(latest["names"][str(p["a"])],latest["names"][str(p["b"])]) for p in latest["pairs"]]
            assert any(any("contact_probe" in name for name in pair) and
                       any("base_collision" in name for name in pair) for pair in pairs),pairs
            assert all(not r["armed"] and not r["pending"] and r["applied_vx"]==r["applied_wz"]==0 for r in drive)
            passed=True
        finally:
            server.send_signal(signal.SIGINT)
            try: server.wait(timeout=10)
            except subprocess.TimeoutExpired: server.kill(); server.wait(timeout=5)
            (out/"contacts.json").write_text(json.dumps(rows,indent=2))
            (out/"native.json").write_text(json.dumps(native,indent=2))
            (out/"summary.json").write_text(json.dumps({"passed":passed,"qualification":
                "disarmed positive contact control; no navigation or obstacle avoidance"},indent=2))
    if not passed: raise RuntimeError("contact observer qualification failed")


if __name__=="__main__": main()
