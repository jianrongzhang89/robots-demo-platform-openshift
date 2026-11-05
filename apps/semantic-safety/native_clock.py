"""Conservative capture-time mapping and live readiness from a private native peer.

Bind epoch only during explicit stopped setup after auditing the single publisher.
Source wall/steady timestamps originate in Gazebo, not at Python reception.
Clock mapping returns an EARLIER wall bound, never a synthetic fresh receipt.
"""
from collections import deque
import math
from safety_core import MS, integer


class NativeClock:
    def __init__(self, epoch):
        if not isinstance(epoch, str) or not 1 <= len(epoch) <= 128:
            raise ValueError("native epoch required")
        self.epoch = epoch
        self.samples = deque(maxlen=2048)
        self.last = None
        self.quiet_since = None
        self.quiet_pose = None
        self.fault = None
        self.status = None

    def observe(self, status, now_wall):
        try:
            if self.fault:
                return False
            if status["clock_epoch"] != self.epoch:
                raise ValueError("native_epoch_changed")
            p = status["physical"]
            if not p or not all(integer(p[k]) for k in ("wall_ns", "steady_ns", "sim_ns", "sequence")):
                raise ValueError("native_capture_invalid")
            if not -2*MS <= now_wall-p["wall_ns"] < 100*MS:
                raise ValueError("native_capture_stale")
            if not p["velocity_valid"] or not all(type(p[k]) in (int,float) and math.isfinite(p[k]) and p[k]>=0
                                                 for k in ("speed", "angular_speed")):
                raise ValueError("native_velocity_invalid")
            if not all(type(p[k]) in (int,float) and math.isfinite(p[k]) for k in ("x", "y", "yaw")):
                raise ValueError("native_capture_invalid")
            old = self.last
            if old:
                if p["sequence"] == old["sequence"]:
                    return False  # repeated status cannot refresh capture readiness
                if (p["sequence"] < old["sequence"] or p["sim_ns"] < old["sim_ns"]
                        or p["steady_ns"] <= old["steady_ns"] or p["wall_ns"] <= old["wall_ns"]):
                    raise ValueError("native_clock_rollback")
                if abs((p["wall_ns"]-old["wall_ns"])-(p["steady_ns"]-old["steady_ns"]))>20*MS:
                    raise ValueError("native_wall_clock_jump")
                if p["wall_ns"]-old["wall_ns"] >= 100*MS:
                    self.quiet_since = self.quiet_pose = None
            self.last, self.status = p.copy(), status
            if p["paused"]:
                raise ValueError("native_simulation_paused")
            if not self.samples or p["sim_ns"] > self.samples[-1][0]:
                self.samples.append((p["sim_ns"],p["wall_ns"]))
            # Quiet opens only on the velocity criterion; it then SURVIVES a
            # velocity-norm rebound only while the pose provably has not
            # moved since the window opened (series-19 trial 005-on: gz
            # physics reported a permanently frozen 0.185 rad/s angular-
            # velocity norm for a body at rest — the norm decayed through
            # quiet, rebounded, and froze while the pose stayed bit-static
            # with resting contacts and 0.34 mm displacement). The pose-
            # delta bounds (<=1 mm, <=0.005 rad from the window-opening
            # pose) accept no more motion than the velocity criterion
            # itself (<=4 mm/s, <=0.02 rad/s average), and the linear
            # speed — a live, unjammed signal in the observed artifact —
            # must stay quiet. The native watchdog's own arm proof keeps
            # requiring the uncorroborated velocity norm, so arming
            # authority is unchanged (a rejected native arm fails closed
            # through the first-command timeout).
            velocity_quiet = p["speed"]<.005 and p["angular_speed"]<.02
            chain_quiet = (status["applied_vx"]==0 and status["applied_wz"]==0
                           and not status["armed"] and not status["pending"])
            if not chain_quiet:
                self.quiet_since = self.quiet_pose = None
            elif velocity_quiet:
                if self.quiet_since is None:
                    self.quiet_since = p["wall_ns"]
                    self.quiet_pose = (p["x"], p["y"], p["yaw"])
            elif self.quiet_since is not None:
                x0, y0, yaw0 = self.quiet_pose
                dyaw = p["yaw"] - yaw0
                dyaw -= 2*math.pi*round(dyaw/(2*math.pi))
                if (p["speed"] >= .01
                        or math.hypot(p["x"]-x0, p["y"]-y0) > .001
                        or abs(dyaw) > .005):
                    self.quiet_since = self.quiet_pose = None
            else:
                self.quiet_since = self.quiet_pose = None
            return True
        except (KeyError, TypeError, ValueError) as error:
            self.fault = str(error)
            self.quiet_since = self.quiet_pose = None
            return False

    def stationary(self, now_wall):
        return bool(not self.fault and self.last and self.quiet_since is not None
                    and 0 <= now_wall-self.last["wall_ns"] < 100*MS
                    and self.last["wall_ns"]-self.quiet_since >= 250*MS)

    def wall_bound(self, ros_stamp, now_wall):
        if (self.fault or not self.last or not integer(ros_stamp)
                or not -2*MS <= now_wall-self.last["wall_ns"] < 100*MS):
            return None
        # Strictly earlier physics sample: PostUpdate at the SAME stamp may
        # have run after a command was captured during that simulation step.
        lower = None
        for sim, wall in reversed(self.samples):
            if sim < ros_stamp:
                lower = (sim,wall)
                break
        upper = next(((sim,wall) for sim,wall in self.samples if sim >= ros_stamp), None)
        if lower is None or upper is None or upper[1]-lower[1] > 30*MS:
            return None
        return lower[1]

