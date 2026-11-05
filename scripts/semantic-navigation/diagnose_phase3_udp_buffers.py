#!/usr/bin/env python3
"""Read-only UDP drop snapshot for the current pod and compressor PID 1."""
import json
import os
import time
from pathlib import Path

fds = {}
for entry in Path("/proc/1/fd").iterdir():
    try:
        target = os.readlink(entry)
    except OSError:
        continue
    if target.startswith("socket:["):
        fds[target[8:-1]] = entry.name
lines = Path("/proc/net/snmp").read_text().splitlines()
udp = [line.split()[1:] for line in lines if line.startswith("Udp:")]
sockets = []
for line in Path("/proc/net/udp").read_text().splitlines()[1:]:
    fields = line.split()
    if fields[9] in fds:
        sockets.append({"fd": fds[fields[9]], "inode": fields[9],
            "port": int(fields[1].split(":")[1], 16), "drops": int(fields[-1]),
            "receive_queue_bytes": int(fields[4].split(":")[1], 16)})
print(json.dumps({"wall_ns":time.time_ns(), "pid_1_udp_sockets":sockets,
                  "pod_udp_counters":dict(zip(udp[0], map(int, udp[1])))}))
