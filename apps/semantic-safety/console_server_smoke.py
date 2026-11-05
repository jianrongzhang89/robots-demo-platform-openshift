"""Exercise the actual pinned launcher before the moving trial can start."""
import json
import os
import signal
import subprocess
import time
from console_evidence import EXECUTABLE, recording_absent, lifecycle_complete
from process_shutdown import gazebo_stop


def verify(output):
    output.mkdir(exist_ok=False)
    world=output/"empty.world"
    world.write_text('<sdf version="1.9"><world name="console_smoke"/></sdf>')
    checks=[]
    blocked=output/"not-a-directory"; blocked.write_text("console path rejection test")
    existing=output/"existing-console"; existing.mkdir()
    sentinel=existing/"preserve.txt"; sentinel.write_text("do not overwrite")
    for name,env,world_path,log_path in (
        ("wrong_domain",dict(os.environ,ROS_DOMAIN_ID="84"),world,output/"domain"),
        ("wrong_transport",dict(os.environ,GZ_IP="0.0.0.0"),world,output/"transport"),
        ("wrong_partition",dict(os.environ,GZ_PARTITION="not-private"),world,output/"partition"),
        ("missing_world",dict(os.environ),output/"missing.world",output/"missing"),
        ("invalid_console_path",dict(os.environ),world,blocked/"console"),
        ("existing_console_path",dict(os.environ),world,existing)):
        run=subprocess.run([str(EXECUTABLE),str(world_path),str(log_path)],env=env,
                           capture_output=True,text=True,timeout=10)
        checks.append({"case":name,"passed":run.returncode==2,"returncode":run.returncode,
                       "stdout":run.stdout,"stderr":run.stderr})
    checks.append({"case":"existing_log_preserved","passed":sentinel.read_text()=="do not overwrite"})
    child=None
    child_env=dict(os.environ,GZ_PARTITION=os.environ["GZ_PARTITION"]+"-console-smoke")
    with (output/"smoke.log").open("x") as log:
        try:
            child=subprocess.Popen([str(EXECUTABLE),str(world),str(output/"console")],
                                   stdout=log,stderr=subprocess.STDOUT,start_new_session=True,
                                   env=child_env)
            deadline=time.monotonic()+5
            while child.poll() is None and time.monotonic()<deadline:
                if (output/"console/server_console.log").is_file() and \
                        "world_recording=false" in (output/"smoke.log").read_text():
                    break
                time.sleep(.02)
            time.sleep(.3)
            checks.append({"case":"valid_server_stays_alive","passed":child.poll() is None
                and (output/"console/server_console.log").is_file()
                and "world_recording=false" in (output/"smoke.log").read_text()})
            rejected=gazebo_stop(env=child_env,stop=False)
            # Boolean is proto3: false can render as an empty text message.
            checks.append({"case":"non_stop_request_rejected","passed":rejected.get("returncode")==0
                and rejected.get("stdout","").strip() in ("", "data: false")
                and not rejected.get("stderr","").strip() and child.poll() is None,
                "reply":rejected})
        finally:
            forced=False
            if child is not None:
                reply=gazebo_stop(env=child_env) if child.poll() is None else {"passed":False}
                if child.poll() is None and not reply["passed"]: os.killpg(child.pid,signal.SIGINT)
                try: child.wait(timeout=5)
                except subprocess.TimeoutExpired:
                    forced=True; os.killpg(child.pid,signal.SIGKILL); child.wait(timeout=5)
                log_text=(output/"smoke.log").read_text()
                lifecycle=lifecycle_complete(log_text)
                checks.append({"case":"bounded_serialized_shutdown","passed":not forced
                    and reply["passed"] and child.returncode==0
                    and lifecycle["passed"],
                    "returncode":child.returncode,"reply":reply,"lifecycle":lifecycle})
    checks.append({"case":"no_world_recording",**recording_absent(output)})
    report={"passed":all(c["passed"] for c in checks),"checks":checks}
    (output/"summary.json").write_text(json.dumps(report,indent=2))
    return report
