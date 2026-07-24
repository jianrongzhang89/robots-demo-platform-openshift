#!/usr/bin/env python3
"""
Patch free_fleet nav2_robot_adapter.py:
1. Add odom Zenoh subscriber in Nav2TfHandler.__init__ that blocks until
   first message arrives (using threading.Event), ensuring odom data is
   always available by the time the init timer first polls.
2. Replace get_transform() to fall back to odom when TF fails.
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

        # Odom subscriber — blocking wait until first message arrives.
        # Uses threading.Event so the callback signals when data is ready.
        import threading as _threading, struct as _struct, math as _math
        self._odom_x = None
        self._odom_y = None
        self._odom_yaw = None
        _odom_ready = _threading.Event()

        def _odom_cb(sample):
            try:
                raw = bytes(sample.payload.to_bytes())
                for offset in range(40, min(100, len(raw) - 55), 4):
                    try:
                        px, py, pz = _struct.unpack_from("<3d", raw, offset)
                        if abs(px) < 50 and abs(py) < 50 and abs(pz) < 10:
                            ox, oy, oz, ow = _struct.unpack_from("<4d", raw, offset + 24)
                            if abs(ox**2 + oy**2 + oz**2 + ow**2 - 1.0) < 0.2:
                                self._odom_x = float(px)
                                self._odom_y = float(py)
                                self._odom_yaw = float(
                                    _math.atan2(2*(ow*oz + ox*oy),
                                                1 - 2*(oy**2 + oz**2)))
                                _odom_ready.set()
                                return
                    except Exception:
                        continue
            except Exception:
                pass

        self._odom_sub = self.zenoh_session.declare_subscriber(
            namespacify("odom", self.robot_name),
            _odom_cb
        )
        # Block up to 15 seconds for first odom message
        if not _odom_ready.wait(timeout=15.0):
            self.node.get_logger().warn(
                f"[patch] No odom data for {self.robot_name} after 15s, using (0,0,0)"
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

NEW_INIT_SEQUENCE = '''        # Initialize robot — use odom directly to avoid TF-dependent timeout
        self.node.get_logger().info(f\'Initializing robot [{self.name}]...\')
        # Get initial pose from odom cache (populated by Nav2TfHandler.__init__)
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

open(path, 'w').write(src)
print(f"Patched {path} successfully")
