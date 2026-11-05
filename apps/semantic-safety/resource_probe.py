"""Read-only private-fixture resource sampling in a separate process.

No ROS/Gazebo imports, control endpoints, or readiness decisions. Samples retain
their own steady timestamps; sampling gaps are evidence, never interpolated.
Write once on shutdown so diagnostic disk traffic is outside the moving trial.
"""
import argparse
import json
from pathlib import Path
import signal
import time


def counters(text):
    return {parts[0]:int(parts[1]) for line in text.splitlines()
            if len(parts:=line.split())==2}


def pressure(text):
    return {parts[0]:{k:float(v) if k!="total" else int(v)
                     for k,v in (item.split("=",1) for item in parts[1:])}
            for line in text.splitlines() if (parts:=line.split())}


def process_stat(text):
    # comm may include spaces or parentheses. Fields below are kernel stat
    # field numbers, with field 3 (state) at tail[0]. Tick counts stay raw.
    end=text.rfind(")")
    tail=text[end+2:].split()
    return {"comm":text[text.index("(")+1:end],"state":tail[0],
            "ppid":int(tail[1]),"minflt":int(tail[7]),"majflt":int(tail[9]),
            "utime_ticks":int(tail[11]),"stime_ticks":int(tail[12]),
            "threads":int(tail[17]),"start_ticks":int(tail[19]),"rss_pages":int(tail[21])}


def snapshot(cgroup=Path("/sys/fs/cgroup"), proc=Path("/proc"), *, processes=False):
    row={"steady_ns":time.monotonic_ns(),"wall_ns":time.time_ns(),"errors":{}}
    for name,parse in (("cpu.stat",counters),("cpu.pressure",pressure),
                       ("io.pressure",pressure),("memory.events",counters),
                       ("memory.pressure",pressure)):
        try: row[name]=parse((cgroup/name).read_text())
        except (OSError,ValueError) as error: row["errors"][name]=str(error)
    if processes:
        row["processes"]={}
        try:
            pids=(cgroup/"cgroup.procs").read_text().split()
            for pid in pids:
                try:
                    details=process_stat((proc/pid/"stat").read_text())
                    details["io"]=counters((proc/pid/"io").read_text().replace(":", ""))
                    details["schedstat"]=[int(n) for n in (proc/pid/"schedstat").read_text().split()]
                    row["processes"][pid]=details
                except (OSError,ValueError,IndexError) as error:
                    row["errors"]["pid:"+pid]=str(error)
        except OSError as error: row["errors"]["cgroup.procs"]=str(error)
    row["end_steady_ns"]=time.monotonic_ns()
    return row


def resolve_watched_processes(cgroup, proc, targets):
    """Find the first in-cgroup PID for each requested kernel comm name."""
    found={}
    try:
        pids=(cgroup/"cgroup.procs").read_text().split()
    except OSError:
        return found
    for pid in pids:
        try:
            comm=(proc/pid/"comm").read_text().strip()
            if comm in targets and comm not in found:
                found[comm]=pid
        except OSError:
            continue
    return found


def read_watched_schedstat(proc, watched):
    rows={}
    errors={}
    for comm,pid in watched.items():
        try:
            values=[int(value) for value in (proc/pid/"schedstat").read_text().split()]
            rows[comm]={"pid":int(pid),"schedstat":values}
        except (OSError,ValueError) as error:
            errors[comm]=str(error)
    return rows,errors


def read_watched_process_threads(proc, watched):
    """Sample every thread of each watched process.

    schedstat splits on-CPU time from run-queue wait; utime/stime and the
    voluntary/involuntary context-switch counters separate scheduler
    starvation from in-thread blocking (locks/IO). Read-only; thread comm
    identifies the Gazebo physics/worker threads during stall analysis.
    """
    rows={}
    errors={}
    for comm,pid in watched.items():
        threads={}
        try:
            tids=[item.name for item in (proc/str(pid)/"task").iterdir()
                  if item.name.isdigit()]
        except OSError as error:
            errors[comm]=str(error); continue
        for tid in tids:
            try:
                sched=[int(value) for value in
                       (proc/str(pid)/"task"/tid/"schedstat").read_text().split()]
                stat=(proc/str(pid)/"task"/tid/"stat").read_text()
                end=stat.rfind(")")
                tail=stat[end+2:].split()
                switches={}
                for line in (proc/str(pid)/"task"/tid/"status").read_text().splitlines():
                    if line.startswith(("voluntary_ctxt_switches:","nonvoluntary_ctxt_switches:")):
                        key,value=line.split(":",1)
                        switches[key.strip()]=int(value)
                threads[tid]={"comm":stat[stat.index("(")+1:end],"state":tail[0],
                              "utime_ticks":int(tail[11]),"stime_ticks":int(tail[12]),
                              "schedstat":sched,**switches}
                # Best-effort wait-channel and syscall: names WHERE a thread
                # sits during a physics-stall window (futex address vs poll
                # vs sendto) — the blocking-site discriminator.
                for detail in ("wchan","syscall"):
                    try:
                        threads[tid][detail]=(proc/str(pid)/"task"/tid/detail).read_text().strip()
                    except OSError:
                        pass
            except (OSError,ValueError,IndexError) as error:
                threads[tid]={"error":str(error)}
        rows[comm]={"pid":int(pid),"threads":threads}
    return rows,errors


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output",required=True,type=Path)
    parser.add_argument("--max-samples",type=int,default=20_000,
                        help="bounded sample capacity; presentations must include the disarmed viewing hold")
    parser.add_argument("--watch-comm",action="append",default=[],
                        help="sample this process main thread's schedstat every 20 ms")
    parser.add_argument("--watch-threads-of",action="append",default=[],
                        help="sample every thread of this process every 20 ms")
    args=parser.parse_args()
    if args.max_samples <= 0:
        parser.error("--max-samples must be positive")
    if args.output.exists(): raise RuntimeError("refusing to replace resource evidence")
    stopping=False
    def stop(_signum,_frame):
        nonlocal stopping
        stopping=True
    signal.signal(signal.SIGINT,stop); signal.signal(signal.SIGTERM,stop)
    samples=[]
    watched={}
    thread_watched={}
    while not stopping and len(samples)<args.max_samples:
        started=time.monotonic()
        row=snapshot(processes=len(samples)%5==0)
        targets=set(args.watch_comm)|set(args.watch_threads_of)
        if targets:
            if len(watched)<len(targets) and len(samples)%5==0:
                watched.update(resolve_watched_processes(Path("/sys/fs/cgroup"),Path("/proc"),
                                                         targets))
            if args.watch_comm:
                row["watched_threads"],row["watch_errors"]=read_watched_schedstat(
                    Path("/proc"),{c:watched[c] for c in args.watch_comm if c in watched})
            if args.watch_threads_of:
                row["watched_process_threads"],row["watch_thread_errors"]=read_watched_process_threads(
                    Path("/proc"),{c:watched[c] for c in args.watch_threads_of if c in watched})
        samples.append(row)
        time.sleep(max(0.,.02-(time.monotonic()-started)))
    with args.output.open("x") as handle:
        json.dump({"interval_target_ms":20,"process_interval_target_ms":100,
                   "watched_thread_interval_target_ms":20 if args.watch_comm or args.watch_threads_of else None,
                   "watched_process_comms":args.watch_comm,
                   "watched_process_thread_comms":args.watch_threads_of,
                   "capacity":args.max_samples,"capacity_reached":len(samples)==args.max_samples,
                   "samples":samples},handle)


if __name__=="__main__": main()
