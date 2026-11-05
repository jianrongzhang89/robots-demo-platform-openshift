"""Bounded private Gazebo transport worker: never renew or cache a command.

Blocking service calls and publisher discovery never run on the ROS safety
executor. If this worker stalls/dies, the independent native lease expires.
"""
import json
import multiprocessing
import os
import queue
import time


# Send-path instrumentation (user-approved November 2, after qualification-15
# and qualification-16 both lost armed trials to native_session_lost): each
# lease enqueue (including silent queue-full drops) and each worker sendto is
# timestamped with the packet's carried window, so any future watchdog lease
# expiry is attributable to a sender stall, a dropped renewal or a near-zero
# command-boundary window. Logging only; no send semantics change.
# The path is resolved lazily per call: the supervisor sets the env var in
# main() AFTER this module is imported, so an import-time constant would
# silently disable the enqueue side (qualification-18: 228 worker rows,
# 0 enqueue rows).
_SEND_LOG_PATH = None


def _log_row(row):
    global _SEND_LOG_PATH
    if _SEND_LOG_PATH is None:
        _SEND_LOG_PATH = os.getenv("PHASE5_NATIVE_LINK_LOG") or ""
    if not _SEND_LOG_PATH:
        return
    try:
        with open(_SEND_LOG_PATH, "a") as handle:
            handle.write(json.dumps(row) + "\n")
    except OSError:
        pass


def worker(commands, results):
    from gz.transport13 import Node
    from gz.msgs10.stringmsg_pb2 import StringMsg
    from gz.msgs10.boolean_pb2 import Boolean
    import json
    import socket
    node = Node()
    publisher = node.advertise("/phase5/drive/lease", StringMsg)
    # UDP companion path for leases: the console server's shared gz transport
    # mutex is held by the perception camera's image publications long enough
    # to delay lease delivery past the 80 ms watchdog expiry under the SAM3
    # observation load. The watchdog listens on loopback 45986; the gz path
    # remains active and unchanged.
    udp = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    # Service discovery in gz-transport can block its internal shared mutex.
    # Warm up while no session has been armed, never relax moving leases.
    deadline = time.monotonic()+20
    while not publisher.has_connections() and time.monotonic()<deadline:
        time.sleep(.02)
    ok, response = node.request("/phase5/drive/stop",StringMsg(data="link_setup"),StringMsg,Boolean,2000)
    time.sleep(3)
    results.put({"kind": "ready", "connected": publisher.has_connections() and ok and response.data})
    while True:
        command = commands.get()
        if command is None: return
        kind, token, value = command
        if kind == "lease":
            # UDP only: the watchdog's gz lease subscription remains active,
            # so also publishing on gz would deliver a duplicate that its
            # replay protection (sequence monotonicity) correctly rejects,
            # stopping the session as packet_invalid.
            payload = json.dumps(value)
            try:
                udp.sendto(payload.encode(), ("127.0.0.1", 45986))
                _log_row({"side": "worker", "kind": "lease", "wall_ns": time.time_ns(),
                          "sequence": value.get("sequence"),
                          "window_ms": (value.get("expires_wall", 0)
                                        - value.get("issued_wall", 0)) / 1e6})
            except OSError:
                publisher.publish(StringMsg(data=payload))
        else:
            # Arm/stop also travel the UDP companion path: the console
            # server's gz SERVICE round trips suffer the same transport
            # mutex contention as its publications under the observation
            # camera load, and a delayed arm reply deadlocks arming. The
            # worker acknowledges TRANSMISSION only; the coordinator proves
            # arm acceptance through the status stream's session, and any
            # stop is backstopped by the independent watchdog lease expiry.
            try:
                udp.sendto(f"{kind}:{value}".encode(), ("127.0.0.1", 45986))
                results.put({"kind": kind, "token": token, "ok": True})
            except OSError:
                # Fall back to the unchanged gz service path.
                ok, response = node.request("/phase5/drive/"+kind, StringMsg(data=value), StringMsg, Boolean, 2000)
                results.put({"kind": kind, "token": token, "ok": ok and response.data})


class NativeLink:
    def __init__(self):
        if not os.getenv("GZ_PARTITION", "").startswith("phase5-watchdog-") or os.getenv("GZ_IP") != "127.0.0.1":
            raise RuntimeError("private native partition required")
        context = multiprocessing.get_context("spawn")
        self.commands, self.results = context.Queue(8), context.Queue(16)
        self.process = context.Process(target=worker, args=(self.commands,self.results))
        self.process.start()
        self.ready = False

    def send(self, kind, token, value):
        if not self.process.is_alive(): return False
        window = None
        if kind == "lease" and isinstance(value, dict):
            window = (value.get("expires_wall", 0) - value.get("issued_wall", 0)) / 1e6
        try:
            self.commands.put_nowait((kind,token,value))
            _log_row({"side": "enqueue", "kind": kind, "wall_ns": time.time_ns(),
                      "window_ms": window, "dropped": False})
            return True
        except queue.Full:
            # The dropped renewal is recorded: a silently dropped lease is a
            # prime suspect for an unexplained watchdog lease expiry.
            _log_row({"side": "enqueue", "kind": kind, "wall_ns": time.time_ns(),
                      "window_ms": window, "dropped": True})
            return False  # no blocking and no source-deadline extension

    def poll(self):
        replies = []
        while True:
            try: reply = self.results.get_nowait()
            except queue.Empty: break
            if reply["kind"] == "ready": self.ready = reply["connected"]
            replies.append(reply)
        return replies

    def close(self):
        try: self.commands.put_nowait(None)
        except queue.Full: pass
        self.process.join(timeout=3)
        if self.process.is_alive(): self.process.terminate(); self.process.join(timeout=3)
        for channel in (self.commands,self.results):
            channel.cancel_join_thread(); channel.close()

