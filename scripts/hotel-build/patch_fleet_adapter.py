import sys

FA = "/opt/rmf_demos_ws/install/lib/python3.12/site-packages/rmf_demos_fleet_adapter/fleet_adapter.py"
content = open(FA).read()

# Fix A: keep callbacks alive (prevent Python GC)
old_a = (
    "        robot.update_handle = robot.fleet_handle.add_robot(\n"
    "            robot.name, state, robot.configuration, robot.make_callbacks()\n"
    "        )"
)
new_a = (
    "        robot._callbacks = robot.make_callbacks()  # keep alive: prevent GC\n"
    "        robot.update_handle = robot.fleet_handle.add_robot(\n"
    "            robot.name, state, robot.configuration, robot._callbacks\n"
    "        )"
)
assert old_a in content, "Pattern A not found"
content = content.replace(old_a, new_a)

# Fix B: wrap callbacks to run in Python daemon threads
# (prevents SIGSEGV when C++ librmf_fleet_adapter calls into Python from a C++ thread
#  without proper GIL setup in rmf_fleet_adapter 2.7.x)
old_b = (
    "    def make_callbacks(self):\n"
    "        return rmf_easy.RobotCallbacks(\n"
    "            lambda destination, execution: self.navigate(\n"
    "                destination, execution\n"
    "            ),\n"
    "            lambda activity: self.stop(activity),\n"
    "            lambda category, description, execution: self.execute_action(\n"
    "                category, description, execution\n"
    "            ),\n"
    "        )"
)
new_b = (
    "    def make_callbacks(self):\n"
    "        import threading\n"
    "        def _run_in_thread(fn, *args):\n"
    "            t = threading.Thread(target=fn, args=args, daemon=True)\n"
    "            t.start()\n"
    "        return rmf_easy.RobotCallbacks(\n"
    "            lambda destination, execution: _run_in_thread(\n"
    "                self.navigate, destination, execution\n"
    "            ),\n"
    "            lambda activity: _run_in_thread(self.stop, activity),\n"
    "            lambda category, description, execution: _run_in_thread(\n"
    "                self.execute_action, category, description, execution\n"
    "            ),\n"
    "        )"
)
assert old_b in content, "Pattern B not found"
content = content.replace(old_b, new_b)

open(FA, "w").write(content)
print("fleet_adapter.py patched: thread-safe callbacks + GC protection")
