"""Bounded private-fixture teardown, preserving Gazebo's display dependency."""
import os
from pathlib import Path
import re
import signal
import subprocess
import time


def timeout_snapshot(pid):
    """Post-failure evidence only; never extends the qualification deadline.

    Best-effort unprivileged reads / debugger attachment. No ptrace capability,
    seccomp changes, or writes to the inferior. Debugger attachment can pause
    threads, so it is permitted only after shutdown has already failed.
    """
    report={"pid":pid,"steady_ns":time.monotonic_ns(),"threads":[]}
    try:
        for task in sorted(Path(f"/proc/{pid}/task").iterdir()):
            row={"tid":int(task.name)}
            for name in ("comm","wchan","syscall","stack"):
                try: row[name]=(task/name).read_text()
                except OSError as error: row[name+"_error"]=str(error)
            report["threads"].append(row)
    except OSError as error:
        report["proc_error"]=str(error)
    try:
        run=subprocess.run(["gdb","--batch","-nx","-nh","-p",str(pid),
                            "-ex","set pagination off","-ex","thread apply all bt",
                            "-ex","detach"],capture_output=True,text=True,timeout=3)
        report["debugger"]={"returncode":run.returncode,"stdout":run.stdout,"stderr":run.stderr}
    except subprocess.TimeoutExpired as error:
        report["debugger_error"]=str(error)
        report["debugger_partial_stdout"]=(error.stdout or b"").decode(errors="replace") if isinstance(error.stdout,bytes) else error.stdout
        report["debugger_partial_stderr"]=(error.stderr or b"").decode(errors="replace") if isinstance(error.stderr,bytes) else error.stderr
    except OSError as error:
        report["debugger_error"]=str(error)
    return report


CONSOLE_STOP_SERVICE="/phase5/console_stop"


def gazebo_stop(*, env=None, stop=True):
    env=dict(os.environ) if env is None else env
    if env.get("GZ_IP")!="127.0.0.1" or not env.get("GZ_PARTITION","").startswith("phase5-watchdog-"):
        return {"passed":False,"reason":"not_private_transport"}
    try:
        run=subprocess.run(["gz","service","-s",CONSOLE_STOP_SERVICE,"--reqtype","gz.msgs.ServerControl",
            "--reptype","gz.msgs.Boolean","--timeout","2000","--req",f"stop: {str(stop).lower()}"],
            capture_output=True,text=True,timeout=5,env=env)
        return {"passed":run.returncode==0 and bool(re.fullmatch(r"\s*data:\s*true\s*",run.stdout)),
                "returncode":run.returncode,"stdout":run.stdout,"stderr":run.stderr}
    except (OSError,subprocess.TimeoutExpired) as error:
        return {"passed":False,"reason":str(error)}


def shutdown(processes, *, signal_group=os.killpg, timeout=5, graceful=None, on_timeout=None):
    alive={name:child.poll() is None for name,child in processes}
    forced=[]
    events=[]
    graceful_results={}
    timeout_evidence={}
    # Do not kill Xvfb while Gazebo/Ogre is still using its X connection.
    # The resource sampler flushes only after the moving processes have exited.
    batches=([p for p in reversed(processes) if p[0] not in ("display","resource_probe")],
             [p for p in reversed(processes) if p[0] in ("display","resource_probe")])
    for batch in batches:
        for name,child in batch:
            if child.poll() is None:
                if graceful and name in graceful:
                    result=graceful[name]()
                    graceful_results[name]=result
                    events.append({"event":"graceful_request","name":name,"result":result,
                                   "steady_ns":time.monotonic_ns()})
                    if result.get("passed") is True: continue
                try: signal_group(child.pid,signal.SIGINT)
                except ProcessLookupError: pass
                events.append({"event":"sigint","name":name,"steady_ns":time.monotonic_ns()})
        for name,child in batch:
            try: child.wait(timeout=timeout)
            except subprocess.TimeoutExpired:
                forced.append(name)
                if on_timeout and name in on_timeout:
                    try: timeout_evidence[name]=on_timeout[name](child.pid)
                    except Exception as error: timeout_evidence[name]={"error":str(error)}
                try: signal_group(child.pid,signal.SIGKILL)
                except ProcessLookupError: pass
                child.wait(timeout=timeout)
            events.append({"event":"reaped","name":name,"returncode":child.returncode,
                           "steady_ns":time.monotonic_ns()})
    return {"alive_at_shutdown":alive,"forced":forced,"events":events,"graceful":graceful_results,
            "timeout_evidence":timeout_evidence}
