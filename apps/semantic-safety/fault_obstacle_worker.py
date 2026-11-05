"""Persistent pre-warmed mover for the private fault obstacle.

Gazebo transport's service-connection establishment sleeps while holding
the node's shared mutex, which blocks the simulation server's publications
and stalls physics ~100 ms (the native-7 fixture lesson, reproduced by the
October 24 obstacle pilots: a fresh subprocess calling set_pose mid-trial
stalled the iteration 104 ms and the 100 ms command-freshness contract
correctly failed the trial). This worker therefore starts with the fixture
while the robot is disarmed, establishes and warms the blocking set_pose
connection with a no-op move to the staging pose, and then serves move
requests through a target file so no new transport connection is ever
created during the armed trial. It moves one pre-placed model; it publishes
no commands and changes no deadline.
"""
import argparse
import json
import sys
import time
from pathlib import Path


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--world", required=True, help="Gazebo world name")
    parser.add_argument("--name", required=True, help="model name to move")
    parser.add_argument("--x", type=float, required=True, help="staging pose for the warm-up move")
    parser.add_argument("--y", type=float, required=True)
    parser.add_argument("--z", type=float, default=0.2,
                        help="model-origin z for the moves; the fault post keeps the historical 0.2, "
                             "thin floor slabs must pass their exact SDF z (Phase 6 smoke attempt 6: "
                             "the mat was lifted to 0.2 m and the layer's height filter rejected "
                             "every projected point)")
    parser.add_argument("--ready-file", required=True)
    parser.add_argument("--target-file", required=True)
    parser.add_argument("--reply-file", required=True)
    args = parser.parse_args()
    from gz.transport13 import Node
    from gz.msgs10.pose_pb2 import Pose
    from gz.msgs10.boolean_pb2 import Boolean
    node = Node()

    def move(x, y, z):
        request = Pose()
        request.name = args.name
        request.position.x = x
        request.position.y = y
        request.position.z = z
        request.orientation.w = 1.0
        ok, reply = node.request(f"/world/{args.world}/set_pose/blocking",
                                 request, Pose, Boolean, 5000)
        return bool(ok and reply.data)

    # Warm the connection before any session is armed. The model already
    # sits at the staging pose, so this is a no-op move that exercises the
    # full service path while a physics stall is harmless.
    deadline = time.monotonic() + 90
    warmed = False
    while not warmed and time.monotonic() < deadline:
        warmed = move(args.x, args.y, args.z)
        if not warmed:
            time.sleep(.5)
    Path(args.ready_file).write_text(json.dumps({"warmed": warmed}))
    if not warmed:
        sys.exit(1)
    target, reply = Path(args.target_file), Path(args.reply_file)
    while True:
        if target.is_file():
            try:
                command = json.loads(target.read_text())
            except (ValueError, OSError):
                time.sleep(.005)
                continue
            moved = move(command["x"], command["y"], command.get("z", args.z))
            reply.write_text(json.dumps({"moved": moved, "x": command["x"],
                                         "y": command["y"], "z": command.get("z", args.z),
                                         "name": args.name}))
            target.unlink()
        time.sleep(.005)


if __name__ == "__main__":
    main()
