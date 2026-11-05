"""Phase 5 candidate: ROS-independent, fail-latched command admission.

This is not a safety-certified controller or an actuator watchdog. Adapters must
validate/bind payloads before submitting Evidence, cancel tasks on a trip, and
independently establish stationary + idle before explicit rearm. A final receiver
must run next to the actuator; its own death still requires an actuator-side
watchdog. No functions in this module publish commands or automatically rearm.
All times are integer nanoseconds; monotonic clocks never cross machines.
"""
from dataclasses import dataclass
import math
import uuid

MS = 1_000_000
STALE_NS = 500 * MS
COMMAND_NS = 100 * MS
# One-shot bounded admission-scheduling grace on the command lease (user
# approved October 28, 2026, after pilot-1): the mid-route renewal race
# loses the next source's checked admission 1-3 ms past the previous
# source's fixed 100 ms expiry when ordinary chain jitter (controller cycle
# + smoother + monitor + delivery + drain, after the conservative bound
# lead) coincides with a cadence hitch — observed at ~0.02% of renewal
# cycles, route-independent. The grace extends the CURRENT command's lease
# deadline by at most COMMAND_GRACE_NS, once per source, and ONLY on the
# coordinator's proof that the ledger already holds a NEWER validated
# source (a smoother output that passed the record-time freshness checks —
# the command pipeline is demonstrably alive end-to-end). Controller
# silence and monitor stalls record no newer source and trip at source+100
# unchanged; the worst-case applied authority age grows by at most
# COMMAND_GRACE_NS and only while a newer command is provably in flight.
COMMAND_GRACE_NS = 25 * MS
LEASE_NS = 80 * MS
UNCERTAINTY_NS = 2 * MS
TICK_NS = 20 * MS
ZERO = (0.0, 0.0, 0.0)  # x, y, yaw; diff-drive only


@dataclass(frozen=True)
class Now:
    steady: int
    wall: int
    ros: int


@dataclass(frozen=True)
class Evidence:
    epoch: str
    sequence: int
    wall: int
    ros: int


@dataclass(frozen=True)
class Lease:
    evidence: Evidence
    deadline: int


@dataclass(frozen=True)
class Command:
    session: str
    sequence: int
    issued_wall: int
    expires_wall: int
    velocity: tuple[float, float, float]


def integer(value):
    return type(value) is int and value >= 0


def velocity_ok(value):
    return (isinstance(value, (tuple, list)) and len(value) == 3
            and all(type(v) in (int, float) and math.isfinite(v) for v in value)
            and -0.10 <= value[0] <= 0.15 and value[1] == 0.0
            and abs(value[2]) <= 0.5)


def velocity_finite(value):
    """Structural validity only: a 3-tuple of finite numbers.

    For the ledger's SOURCE record (the provenance path). The collision
    monitor is the final velocity limiter: the controller/smoother's raw
    command may legitimately exceed the applied bounds (the goal-approach
    rotation commands reach ~0.65 rad/s while the monitor limits the applied
    value well inside them — pair-1-on-lethal254-grace2 lost its run to the
    ledger rejecting those raws, leaving the monitor's valid limited outputs
    sourceless). The authority path is unchanged: resolve(), gate.command()
    and the native lease all keep the full magnitude bounds on the APPLIED
    (checked) velocity.
    """
    return (isinstance(value, (tuple, list)) and len(value) == 3
            and all(type(v) in (int, float) and math.isfinite(v) for v in value))


class SafetyGate:
    """Pure state machine. Call tick on a wall/steady timer, never a ROS timer."""

    def __init__(self, *, require_semantics=True):
        self.required = ("clock", "scan", "odom", "tf") + (
            ("camera", "semantic", "inference_heartbeat") if require_semantics else ())
        self.leases = {}
        self.last_time = None
        self.barrier_wall = -1
        self.armed = False
        self.reason = "startup_disarmed"
        self.trigger_steady = None
        self.session = None
        self.sequence = -1
        self.command_sequence = -1
        self.command_deadline = None
        self.command_wall = -1
        self.command_grace_used = False
        self.wait_hold_active = False
        self.velocity = ZERO

    def trip(self, reason, now):
        # Retain the first trigger/reason; subsequent late successes or faults
        # must not move its stopping-latency origin or silently clear it.
        if self.armed or self.trigger_steady is None:
            self.reason = reason
            self.trigger_steady = now.steady
        # A second fault during recovery invalidates partially refreshed input
        # too, without rewriting the original stop reason/latency origin.
        self.barrier_wall = now.wall
        self.leases.clear()
        self.armed = False
        self.velocity = ZERO
        self.command_deadline = None
        self.wait_hold_active = False
        self.session = None

    def _advance(self, now):
        if not all(integer(v) for v in (now.steady, now.wall, now.ros)):
            raise ValueError("invalid local clock")
        previous, self.last_time = self.last_time, now
        if previous is not None:
            if now.steady < previous.steady or now.ros < previous.ros:
                self.trip("clock_rollback", now)
                self.leases.clear()
                self.barrier_wall = now.wall
                return False
            if abs((now.wall - previous.wall) - (now.steady - previous.steady)) > 20 * MS:
                self.trip("wall_clock_discontinuity", now)
                self.leases.clear()
                self.barrier_wall = now.wall
                return False
        if self.armed:
            # Check BEFORE accepting callbacks; late refreshed inputs cannot
            # conceal a missed deadline if the event loop was delayed.
            failures = []
            for key in self.required:
                item = self.leases.get(key)
                if item is None:
                    failures.append((now.steady, key + "_missing"))
                elif self._expired(item, now):
                    failures.append((min(now.steady, item.deadline), key + "_stale"))
            if now.steady >= self.command_deadline:
                failures.append((self.command_deadline, "command_expired"))
            if failures:
                trigger, reason = min(failures)
                self.trip(reason, now)
                self.trigger_steady = trigger
        return True

    @staticmethod
    def _expired(item, now):
        return (now.steady >= item.deadline
                or now.wall - item.evidence.wall + UNCERTAINTY_NS >= STALE_NS
                or not 0 <= now.ros - item.evidence.ros < STALE_NS)

    def observe(self, key, evidence, now):
        if key not in self.required:
            raise ValueError("unconfigured safety input")
        if not self._advance(now):
            return False
        if (not isinstance(evidence.epoch, str) or not 1 <= len(evidence.epoch) <= 128
                or not all(integer(v) for v in (evidence.sequence, evidence.wall, evidence.ros))):
            self.trip(key + "_invalid", now)
            return False
        age = now.wall - evidence.wall
        if (evidence.wall - UNCERTAINTY_NS <= self.barrier_wall or age < -UNCERTAINTY_NS
                or age + UNCERTAINTY_NS >= STALE_NS
                or not 0 <= now.ros - evidence.ros < STALE_NS):
            # While stopped, drain pre-barrier/late replies without advancing
            # the barrier: otherwise ordinary inference latency can prevent
            # recovery forever. Still fail closed if motion was authorized.
            if self.armed:
                self.trip(key + "_invalid_age", now)
            return False
        prior = self.leases.get(key)
        if prior:
            if evidence.epoch != prior.evidence.epoch:
                self.trip(key + "_epoch_changed", now)
                return False
            if (evidence.sequence <= prior.evidence.sequence
                    or evidence.wall <= prior.evidence.wall
                    or evidence.ros < prior.evidence.ros):
                # Duplicate reception cannot renew a capture lease.
                return False
        remaining = STALE_NS - max(0, age + UNCERTAINTY_NS)
        self.leases[key] = Lease(evidence, now.steady + remaining)
        return True

    def arm(self, now, *, stationary, tasks_idle, neutral_command,
            first_command_timeout_ns=COMMAND_NS):
        """Trusted coordinator must independently verify all three conditions.

        Disallow repeated arm while moving; a fresh session is required for
        every downstream command and independent receiver rearm.
        """
        if not self._advance(now) or self.armed:
            return None
        if not (stationary is True and tasks_idle is True and neutral_command is True):
            return None
        # Optional bounded ZERO-motion setup interval for native arming / goal
        # planning. Once a real command arrives its ordinary 100 ms lifetime
        # applies; subsequent packets can never restore this setup interval.
        if not integer(first_command_timeout_ns) or not COMMAND_NS <= first_command_timeout_ns <= 5000*MS:
            return None
        if any(k not in self.leases or self._expired(self.leases[k], now) for k in self.required):
            return None
        self.session = str(uuid.uuid4())
        self.armed, self.reason, self.trigger_steady = True, "armed", None
        self.sequence = self.command_sequence = -1
        self.command_deadline = now.steady + first_command_timeout_ns
        self.command_wall = now.wall
        self.command_grace_used = False
        self.wait_hold_active = False
        self.velocity = ZERO
        return self.session

    def command(self, session, sequence, issued_wall, velocity, now):
        self._advance(now)
        if not self.armed:
            return False
        if (session != self.session or not integer(sequence) or sequence <= self.command_sequence
                or not integer(issued_wall) or issued_wall < self.command_wall
                or not -UNCERTAINTY_NS <= now.wall - issued_wall < COMMAND_NS - UNCERTAINTY_NS
                or not velocity_ok(velocity)):
            self.trip("command_invalid", now)
            return False
        # Repeated checked copies retain a grace already granted to this
        # captured source. Withdrawing it and immediately forwarding the
        # ungraced deadline can emit a lease shorter than the receiver's
        # 2 ms allowance before the coordinator reapplies grace (G5 run 5).
        # A first/new source and zero-hold transitions retain their original
        # behavior; in particular, motion never inherits zero-only authority.
        preserve_grace = (self.command_sequence >= 0
                          and issued_wall == self.command_wall
                          and self.command_grace_used
                          and not self.wait_hold_active)
        self.command_sequence = sequence
        self.command_wall = issued_wall
        if not preserve_grace:
            self.command_grace_used = False
        if not preserve_grace and not (self.wait_hold_active and tuple(velocity)==ZERO):
            self.command_deadline = now.steady + COMMAND_NS - max(0, now.wall - issued_wall + UNCERTAINTY_NS)
        if any(abs(v)>0.005 for v in velocity): self.wait_hold_active = False
        self.velocity = tuple(velocity)
        return True

    def extend_command_deadline(self, now, grace_ns):
        """One-shot bounded admission-scheduling grace (COMMAND_GRACE_NS).

        Extends the current command's lease deadline by at most grace_ns,
        ONCE per source (reset by each accepted command). The caller (the
        coordinator) must prove a newer validated source is already
        recorded before calling. The extension never compounds and never
        applies to a disarmed gate or a first-command timeout.
        """
        if not self.armed or self.command_deadline is None or self.command_grace_used:
            return False
        if not 0 < self.command_deadline - now.steady <= grace_ns:
            return False
        self.command_deadline = self.command_deadline + grace_ns
        self.command_grace_used = True
        return True

    def zero_wait_hold(self, session, now):
        """Finish a near-stationary Wait handoff, then refresh its short lease.

        The task/registry adapter must prove that the configured Wait BT child
        is active and owned. A requested/applied command within 0.005 m/s is
        normalized to exact zero; larger motion is never modified. This never
        changes the source-command wall stamp or command sequence, and still
        advances/checks every sensor lease.
        """
        if (not self.armed or session!=self.session or
                any(abs(v)>0.005 for v in self.velocity)):
            return False
        if not self._advance(now) or not self.armed:
            return False
        self.velocity=ZERO
        self.command_deadline=now.steady+COMMAND_NS-UNCERTAINTY_NS
        self.wait_hold_active=True
        return True

    def terminal_zero_hold(self, session, now):
        """Stop deliberately through an unbindable terminal deceleration
        (user-approved October 28, 2026, after series-14 trial 003-on).

        A ~120 ms physics stall at the goal-approach boundary can leave the
        smoother's terminal stamp inside a >30 ms bracket gap: the native
        clock's wall_bound for that stamp is then permanently None, the
        terminal source never records, and the deceleration ramp reusing
        that stamp expires the command chain at the goal — with the robot
        already inside the arrival tolerance and decelerating through the
        settling tail (<=0.055 m/s, the qualified decel's own step). This
        hold completes that stop DELIBERATELY: it normalizes the settling
        tail to exact zero and refreshes the zero lease, so the goal
        checker completes on the stopped robot instead of the authority
        expiring under it. Zero-only after entry: it can never command
        motion, and the transition is at most one decel step earlier than
        the ramp's own next step. Every sensor lease still advances and
        gates; the native watchdog still revalidates each packet.
        """
        if (not self.armed or session!=self.session or
                any(abs(v)>0.055 for v in self.velocity)):
            return False
        if not self._advance(now) or not self.armed:
            return False
        self.velocity=ZERO
        self.command_deadline=now.steady+COMMAND_NS-UNCERTAINTY_NS
        return True

    def tick(self, now):
        self._advance(now)
        return self.velocity if self.armed else ZERO

    def packet(self, now):
        """None means revoke/zero, never a live lease with an old session."""
        self.tick(now)
        if not self.armed:
            return None
        self.sequence += 1
        # Do not extend a command/input's authority by periodically republishing.
        remaining = min(LEASE_NS, self.command_deadline - now.steady,
                        *(v.deadline - now.steady for v in self.leases.values()))
        return Command(self.session, self.sequence, now.wall, now.wall + remaining, self.velocity)


class FinalReceiver:
    """Receiver-side, independently fail-latched short lease (no ROS/Gazebo I/O).

    Must be rearmed explicitly together with SafetyGate; never adopt a session
    from a command packet. Requires a local 20 ms steady timer and synchronized
    wall clocks with <=2 ms allowance, same as the existing capture contract.
    """

    def __init__(self):
        self.session = None
        self.sequence = -1
        self.deadline = None
        self.expires_wall = None
        self.reason = "startup_disarmed"
        self.velocity = ZERO
        self.last_time = None
        self.used_sessions = set()

    def stop(self, reason):
        self.session = None
        self.velocity = ZERO
        self.reason = reason
        self.deadline = self.expires_wall = None

    def arm(self, session, now, *, stationary):
        self.tick(now)
        if (self.session is not None or stationary is not True
                or not isinstance(session, str) or len(session) != 36
                or session in self.used_sessions or len(self.used_sessions) >= 1024):
            return False
        self.used_sessions.add(session)
        self.session, self.sequence = session, -1
        self.reason = "armed_waiting_first_packet"
        self.deadline = now.steady + LEASE_NS
        self.expires_wall = now.wall + LEASE_NS
        return True

    def tick(self, now):
        if not all(integer(v) for v in (now.steady, now.wall, now.ros)):
            raise ValueError("invalid local clock")
        prior, self.last_time = self.last_time, now
        if prior and (now.steady < prior.steady or now.ros < prior.ros
                      or abs(now.wall-prior.wall-now.steady+prior.steady) > 20 * MS):
            self.stop("clock_discontinuity")
        if self.session is not None and (now.steady >= self.deadline
                                         or now.wall >= self.expires_wall):
            self.stop("lease_expired")
        return self.velocity if self.session is not None else ZERO

    def receive(self, packet, now):
        self.tick(now)
        if packet is None:
            self.stop("supervisor_revoked")
            return False
        if self.session is None:
            return False
        if (packet.session != self.session or not integer(packet.sequence)
                or packet.sequence <= self.sequence or not velocity_ok(packet.velocity)
                or not all(integer(v) for v in (packet.issued_wall, packet.expires_wall))
                or not 0 < packet.expires_wall-packet.issued_wall <= LEASE_NS
                or packet.issued_wall > now.wall + UNCERTAINTY_NS
                or packet.expires_wall <= now.wall + UNCERTAINTY_NS):
            self.stop("packet_invalid")
            return False
        self.sequence = packet.sequence
        self.expires_wall = packet.expires_wall - UNCERTAINTY_NS
        self.deadline = now.steady + self.expires_wall - now.wall
        self.velocity = tuple(packet.velocity)
        self.reason = "armed"
        return True
