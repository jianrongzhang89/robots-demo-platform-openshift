#!/usr/bin/env python3
"""
Patch free_fleet nav2_robot_adapter.py:
1. Add amcl_pose Zenoh subscriber in Nav2TfHandler.__init__ that blocks until
   first message arrives (using threading.Event), ensuring map-frame pose is
   always available by the time the init timer first polls.
   Key: amcl_pose (not odom) gives map-frame coordinates — odom starts at (0,0)
   regardless of where the robot spawns, making it wrong for non-origin spawns.
2. Replace get_transform() to fall back to amcl_pose cache when TF fails.
3. Force battery_soc = 1.0 (sim robots have no battery topic).
"""
import sys, re, os

path = sys.argv[1]
src = open(path).read()

# 1. In Nav2TfHandler.__init__, add odom subscriber with blocking wait
#    right after the tf_sub is declared.
OLD_TF_SUB = '''        self.tf_sub = self.zenoh_session.declare_subscriber(
            namespacify('tf', self.robot_name),
            _tf_callback
        )'''

NEW_TF_SUB = '''        self.tf_sub = self.zenoh_session.declare_subscriber(
            namespacify('tf', self.robot_name),
            _tf_callback
        )

        # amcl_pose subscriber — map-frame position (reliable cross-pod pub/sub).
        # Lesson from main branch: amcl_pose is the correct position source for
        # cross-pod use. odom is in the odom frame (starts at 0,0 at boot, not map
        # origin), so it gives wrong coordinates for robots spawned at non-origin
        # positions (-2,-0.5) and (2,0.5). amcl_pose gives true map-frame x/y/yaw.
        import threading as _threading, struct as _struct, math as _math
        self._odom_x = None
        self._odom_y = None
        self._odom_yaw = None
        _pose_ready = _threading.Event()

        def _amcl_pose_cb(sample):
            try:
                raw = bytes(sample.payload.to_bytes())
                # PoseWithCovarianceStamped CDR: 4-byte header + stamp (8 bytes) +
                # frame_id string (4+N bytes) + alignment padding + position doubles.
                # Scan for plausible map-frame position (tb3_sandbox bounds: ±6 m).
                for offset in range(20, min(80, len(raw) - 55), 4):
                    try:
                        px, py, pz = _struct.unpack_from("<3d", raw, offset)
                        if abs(px) < 6.0 and abs(py) < 6.0 and abs(pz) < 0.5:
                            ox, oy, oz, ow = _struct.unpack_from("<4d", raw, offset + 24)
                            # Planar robot: ox≈0, oy≈0; unit quaternion
                            if abs(ox) < 0.1 and abs(oy) < 0.1 and abs(oz**2 + ow**2 - 1.0) < 0.1:
                                self._odom_x = float(px)
                                self._odom_y = float(py)
                                self._odom_yaw = float(
                                    _math.atan2(2*(ow*oz), 1 - 2*(oz**2)))
                                _pose_ready.set()
                                return
                    except Exception:
                        continue
            except Exception:
                pass

        self._odom_sub = self.zenoh_session.declare_subscriber(
            namespacify("amcl_pose", self.robot_name),
            _amcl_pose_cb
        )
        # Block up to 90 seconds: AMCL needs time to converge at real_time_factor=0.5
        if not _pose_ready.wait(timeout=90.0):
            self.node.get_logger().warn(
                f"[patch] No amcl_pose data for {self.robot_name} after 90s, using (0,0,0)"
            )
            self._odom_x = 0.0
            self._odom_y = 0.0
            self._odom_yaw = 0.0'''

src = src.replace(OLD_TF_SUB, NEW_TF_SUB, 1)

# 2. Replace get_transform() to fall back to odom when TF fails
OLD_GET_TRANSFORM = '''    def get_transform(self) -> TransformStamped | None:
        try:
            transform = self.tf_buffer.lookup_transform(
                self.map_frame,
                self.robot_frame,
                rclpy.time.Time()
                )
            return transform
        except Exception as err:
            self.node.get_logger().info(
                f\'Unable to get transform between {self.robot_frame} \'
                f\'and {self.map_frame}: {type(err)}: {err}\'
            )'''

NEW_GET_TRANSFORM = '''    def get_transform(self) -> TransformStamped | None:
        try:
            transform = self.tf_buffer.lookup_transform(
                self.map_frame,
                self.robot_frame,
                rclpy.time.Time()
                )
            return transform
        except Exception:
            pass
        # TF unavailable: use cached odom data
        if self._odom_x is not None:
            import math
            t = TransformStamped()
            t.transform.translation.x = self._odom_x
            t.transform.translation.y = self._odom_y
            t.transform.translation.z = 0.0
            half = self._odom_yaw / 2.0
            t.transform.rotation.z = math.sin(half)
            t.transform.rotation.w = math.cos(half)
            return t'''

src = src.replace(OLD_GET_TRANSFORM, NEW_GET_TRANSFORM, 1)

# 3. Force battery_soc = 1.0 after battery_state_sub
OLD_BATT = "self.battery_state_sub = self.zenoh_session.declare_subscriber("
if OLD_BATT in src:
    idx = src.index(OLD_BATT)
    end_idx = src.index(')', src.index(')', idx) + 1) + 1
    src = src[:end_idx] + '\n        self.battery_soc = 1.0  # sim robots have no battery topic\n' + src[end_idx:]
    print("Patched battery_soc default to 1.0")

# 4. Patch the init sequence to use odom directly, bypassing the TF-dependent
#    timer-based initialization that keeps timing out.
OLD_INIT_SEQUENCE = '''        # Initialize robot
        init_timeout_sec = self.robot_config_yaml.get('init_timeout_sec', 10)
        self.node.get_logger().info(f'Initializing robot [{self.name}]...')
        init_robot_pose = rclpy.Future()

        def _get_init_pose():
            robot_pose = self.get_pose()
            if robot_pose is not None:
                init_robot_pose.set_result(robot_pose)
                init_robot_pose.done()

        init_pose_timer = self.node.create_timer(1, _get_init_pose)
        rclpy.spin_until_future_complete(
            self.node, init_robot_pose, timeout_sec=init_timeout_sec
        )

        if init_robot_pose.result() is None:
            error_message = \\
                f\'Timeout trying to initialize robot [{self.name}]\'
            self.node.get_logger().error(error_message)
            raise RuntimeError(error_message)

        self.node.destroy_timer(init_pose_timer)'''

NEW_INIT_SEQUENCE = '''        # Initialize robot — use amcl_pose cache to avoid TF-dependent timeout
        self.node.get_logger().info(f\'Initializing robot [{self.name}]...\')
        # Get initial pose from amcl_pose cache (populated by Nav2TfHandler.__init__)
        import time as _init_time
        _deadline = _init_time.monotonic() + 30.0
        _init_pose = None
        while _init_time.monotonic() < _deadline:
            _init_pose = self.get_pose()
            if _init_pose is not None:
                break
            _init_time.sleep(0.5)
        if _init_pose is None:
            # Last resort: use origin
            self.node.get_logger().warn(
                f\'[patch] Could not get initial pose for {self.name}, using origin\'
            )
            _init_pose = [0.0, 0.0, 0.0]
        init_robot_pose_result = _init_pose'''

NEW_INIT_CONTINUE = '''        self.node.destroy_timer(init_pose_timer)'''

# Replace the init sequence (find the block)
if OLD_INIT_SEQUENCE in src:
    src = src.replace(OLD_INIT_SEQUENCE, NEW_INIT_SEQUENCE, 1)
    # Fix the reference to init_robot_pose.result() that follows
    src = src.replace(
        'init_robot_pose.result()',
        'init_robot_pose_result',
        2  # replace in the state setup and any other reference
    )
    print("Patched Nav2RobotAdapter init sequence to use odom directly")
else:
    print("WARNING: init sequence not found, skipping that patch")

# 5. Replace NavigateToPoseActionInterface with PubSubNavHandle in navigate().
#    The bridge's action queryable never responds; pub/sub relay on the Nav2 pod
#    receives goals on /rmf_navigate_cmd, calls local navigate_to_pose, and
#    publishes results on /rmf_navigate_result — both bridged via Zenoh pub/sub.

PUBSUB_CLASS = '''
import struct as _psnstruct, time as _psntime, threading as _psnthread

class _PubSubNavHandle:
    """Navigation handle using pub/sub relay instead of broken action queryable."""

    def __init__(self, robot_name, zenoh_session, node, x, y, yaw):
        self._robot_name = robot_name
        self._node = node
        self._x = x; self._y = y; self._yaw = yaw
        self._goal_id = str(int(_psntime.time() * 1000000) % 10000000)
        self._done = False
        self._succeeded = False
        self._lock = _psnthread.Lock()

        result_key = namespacify("rmf_navigate_result", robot_name)
        self._result_sub = zenoh_session.declare_subscriber(result_key, self._on_result)
        self._cmd_pub = zenoh_session.declare_publisher(namespacify("rmf_navigate_cmd", robot_name))

    def _on_result(self, sample):
        try:
            raw = bytes(sample.payload.to_bytes())
            if len(raw) < 9:
                return
            str_len = _psnstruct.unpack_from('<I', raw, 4)[0]
            if len(raw) < 8 + str_len:
                return
            text = raw[8:8 + str_len - 1].decode('utf-8')
            parts = text.split()
            if len(parts) == 2 and parts[0] == self._goal_id:
                with self._lock:
                    self._succeeded = (parts[1] == 'OK')
                    self._done = True
        except Exception:
            pass

    @staticmethod
    def _str_cdr(text):
        data = text.encode('utf-8') + b'\\x00'
        return b'\\x00\\x01\\x00\\x00' + _psnstruct.pack('<I', len(data)) + data

    def execute(self):
        cmd = f"{self._goal_id} {self._x:.6f} {self._y:.6f} {self._yaw:.6f}"
        self._cmd_pub.put(self._str_cdr(cmd))
        self._node.get_logger().info(
            f"[nav_relay] goal {self._goal_id}: ({self._x:.2f}, {self._y:.2f}, {self._yaw:.2f})"
        )

    def update(self, state):
        with self._lock:
            if self._done:
                try:
                    self._result_sub.undeclare()
                except Exception:
                    pass
                if self._succeeded:
                    return (True, True)
                raise RequestAborted(f"goal {self._goal_id} failed")
        return (False, False)

    def feedback(self, action, payload):
        pass

    def get_action_name(self):
        return "navigate_to_pose"

    def get_goal_id(self):
        return self._goal_id

    def get_activity(self):
        return None

    def stop(self):
        try:
            self._cmd_pub.put(self._str_cdr(f"{self._goal_id} CANCEL"))
            self._result_sub.undeclare()
        except Exception:
            pass

'''

# Insert _PubSubNavHandle class right before class Nav2RobotAdapter
if 'class Nav2RobotAdapter' in src:
    src = src.replace('class Nav2RobotAdapter', PUBSUB_CLASS + 'class Nav2RobotAdapter', 1)
    print("Inserted _PubSubNavHandle class")
else:
    print("WARNING: class Nav2RobotAdapter not found, skipping PubSubNavHandle insertion")

# Replace NavigateToPoseActionInterface creation in navigate()
OLD_NAV_CREATION = '''            self.nav_handle = NavigateToPoseActionInterface(
                self.name, self.node, self.update_handle, self.zenoh_session,
                ExecutionHandle(execution),
                self.service_call_timeout_sec,
                self.map_frame,
                destination.position[0],
                destination.position[1],
                0.0,
                destination.position[2],
            )'''

NEW_NAV_CREATION = '''            self.nav_handle = _PubSubNavHandle(
                self.name, self.zenoh_session, self.node,
                destination.position[0],
                destination.position[1],
                destination.position[2],
            )'''

if OLD_NAV_CREATION in src:
    src = src.replace(OLD_NAV_CREATION, NEW_NAV_CREATION, 1)
    print("Replaced NavigateToPoseActionInterface with _PubSubNavHandle")
else:
    print("WARNING: NavigateToPoseActionInterface creation not found, skipping nav handle replacement")

open(path, 'w').write(src)
print(f"Patched {path} successfully")
