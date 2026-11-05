"""Prepare private Phase 5 assets; never edit canonical source assets in place."""
import copy
import hashlib
import json
import math
from pathlib import Path
import xml.etree.ElementTree as ET


def values(text):
    return [float(v) for v in text.split()]


def prepare(world_text, urdf_text, *, lidar_update_rate=None, lidar_max_range=None, physics_step=None, odom_frequency=None):
    world, urdf = ET.fromstring(world_text), ET.fromstring(urdf_text)
    model = world.find(".//model[@name='robot_1']")
    if model is None:
        raise ValueError("robot_1 absent")
    for name in ("base_link", "base_footprint"):
        if values(model.find(f"link[@name='{name}']").findtext("pose", "0 0 0 0 0 0")) != [0]*6:
            raise ValueError("unqualified base pose")
    lidar = model.find("link[@name='base_scan']")
    if values(lidar.findtext("pose")) != [-.032, 0, .172, 0, 0, 0]:
        raise ValueError("unqualified lidar pose")
    sensor = lidar.find("sensor[@name='lidar']")
    if values(sensor.findtext("pose")) != [0, 0, .01, 0, 0, 0]:
        raise ValueError("unqualified lidar sensor offset")
    if lidar_max_range is not None:
        maximum=sensor.find("lidar/range/max")
        if lidar_max_range not in (3.5,12.) or maximum is None or float(maximum.text)!=3.5:
            raise ValueError("unqualified virtual lidar range")
        maximum.text=str(lidar_max_range)
    if physics_step is not None:
        step=world.find("world/physics/max_step_size")
        if physics_step not in (.001,.002,.01) or step is None or float(step.text)!=.01:
            raise ValueError("unqualified private physics step")
        step.text=str(physics_step)
    if lidar_update_rate is not None:
        if type(lidar_update_rate) not in (int,float) or not math.isfinite(lidar_update_rate) or lidar_update_rate<=0:
            raise ValueError("lidar update rate must be a finite positive number")
        rate=sensor.find("update_rate")
        if rate is None:
            raise ValueError("lidar update-rate element is missing")
        rate.text=str(lidar_update_rate)
    for child, expected, replacement in (("base_link", [0, 0, .10], "0 0 0"),
                                         ("base_scan", [-.064, 0, .172], "-0.032 0 0.172")):
        joint = next(j for j in urdf.findall("joint") if j.find("child").get("link") == child)
        origin = joint.find("origin")
        if values(origin.get("xyz")) != expected:
            raise ValueError("unexpected input URDF; refusing double/unknown patch")
        origin.set("xyz", replacement)
    if urdf.find("link[@name='lidar_frame']") is not None:
        raise ValueError("lidar_frame already exists")
    ET.SubElement(urdf, "link", {"name": "lidar_frame"})
    joint = ET.SubElement(urdf, "joint", {"name": "lidar_sensor_joint", "type": "fixed"})
    ET.SubElement(joint, "parent", {"link": "base_scan"})
    ET.SubElement(joint, "child", {"link": "lidar_frame"})
    ET.SubElement(joint, "origin", {"xyz": "0 0 0.01", "rpy": "0 0 0"})
    frame = sensor.find("gz_frame_id")
    if frame is None:
        frame = ET.SubElement(sensor, "gz_frame_id")
    frame.text = "lidar_frame"
    drive = next(p for p in model.findall("plugin") if "DiffDrive" in p.get("name", ""))
    if odom_frequency is not None:
        rate=drive.find("odom_publish_frequency")
        if odom_frequency not in (50.,200.) or rate is None or float(rate.text)!=50.:
            raise ValueError("unqualified odometry publication rate")
        rate.text=str(odom_frequency)
    for key, expected in (("wheel_radius", ".033"), ("wheel_separation", ".287")):
        if float(drive.findtext(key, "nan")) != float(expected):
            raise ValueError("unqualified wheel geometry")
    if drive.findtext("topic") != "/robot_1/cmd_vel":
        raise ValueError("unexpected/double-patched drive topic")
    drive.find("topic").text = "/phase5/internal_drive"
    plugin = ET.SubElement(model, "plugin", {"filename": "libphase5_drive_watchdog.so", "name": "phase5::DriveWatchdog"})
    ET.SubElement(plugin, "output_topic").text = "/phase5/internal_drive"
    ET.SubElement(plugin, "prefix").text = "/phase5/drive"
    return ET.tostring(world, encoding="unicode"), ET.tostring(urdf, encoding="unicode")


def micro_world(patched_world):
    """Same actual robot physics/drive, no hotel, camera or navigation stack."""
    model = copy.deepcopy(ET.fromstring(patched_world).find(".//model[@name='robot_1']"))
    model.find("pose").text = "0 0 0.1 0 0 0"
    for link in model.findall("link"):
        for sensor in link.findall("sensor"):
            link.remove(sensor)
    root = ET.fromstring('''<sdf version="1.9"><world name="phase5_watchdog_fixture">
      <physics name="physics" type="ignored"><max_step_size>0.001</max_step_size><real_time_factor>1</real_time_factor></physics>
      <gravity>0 0 -9.8</gravity>
      <plugin filename="gz-sim-physics-system" name="gz::sim::systems::Physics"/>
      <plugin filename="gz-sim-user-commands-system" name="gz::sim::systems::UserCommands"/>
      <model name="ground"><static>true</static><link name="ground">
        <collision name="ground"><geometry><plane><normal>0 0 1</normal><size>20 20</size></plane></geometry></collision>
      </link></model></world></sdf>''')
    root.find("world").append(model)
    return ET.tostring(root, encoding="unicode")


def write_assets(directory, *, lidar_update_rate=5.0, lidar_max_range=None, physics_step=None, odom_frequency=None):
    directory = Path(directory)
    directory.mkdir(parents=True, exist_ok=False)
    source_world = Path("/opt/ros2-demo/hotel-assets/hotel.world").read_text()
    source_urdf = Path("/opt/ros2-demo/robot/turtlebot3_waffle.urdf").read_text()
    world, urdf = prepare(source_world, source_urdf, lidar_update_rate=lidar_update_rate,
                         lidar_max_range=lidar_max_range,physics_step=physics_step,odom_frequency=odom_frequency)
    # Private Sensors-system override (user-approved October 28, 2026): the
    # world's sensors plugin must resolve to OUR override library. gz-sim's
    # SystemLoader appends GZ_SIM_SYSTEM_PLUGIN_PATH entries AFTER its own
    # install dir, so a bare filename always resolves to the system plugin
    # (sensors-override-smoke-1: the system library loaded and the fixture's
    # fail-closed marker check stopped the trial). An ABSOLUTE filename
    # short-circuits the search entirely (SystemPaths::FindSharedLibrary
    # returns an existing absolute path directly). Conditional on the
    # override being present so older pinned chains keep their original
    # behavior; the console_sensors_system_override_loaded check fails
    # closed when the override is expected but did not load.
    sensors_override = Path("/opt/semantic-safety/lib/libgz-sim-sensors-system.so")
    if sensors_override.is_file():
        pattern = 'filename="libgz-sim-sensors-system.so"'
        if world.count(pattern) != 1:
            raise ValueError("expected exactly one sensors-system plugin element")
        world = world.replace(pattern, 'filename="%s"' % sensors_override)
    (directory / "hotel.world").write_text(world)
    (directory / "robot.urdf").write_text(urdf)
    (directory / "watchdog.world").write_text(micro_world(world))
    # Retain the actual installed map pair, not the different repository map.
    import yaml
    import numpy as np
    from PIL import Image
    map_path = Path("/opt/ros2-demo/maps/hotel_L1.yaml")
    map_config = yaml.safe_load(map_path.read_text())
    image_path = map_path.parent / map_config["image"]
    if image_path.name != "hotel_L1.pgm" or map_config.get("negate", 0) != 0:
        raise ValueError("unqualified map encoding")
    raster = np.asarray(Image.open(image_path).convert("L"))
    origin, resolution = map_config["origin"], map_config["resolution"]
    if origin[2] != 0:
        raise ValueError("rotated map needs separate audit")
    free = (255-raster.astype(float))/255 < map_config["free_thresh"]
    initial = values(ET.fromstring(world).find(".//model[@name='robot_1']/pose").text)
    def hull_free(x, y):
        # Conservative grid AABB for the qualified yaw-zero padded hull.
        c0, c1 = [int(np.floor((x+offset-origin[0])/resolution)) for offset in (-.182,.118)]
        r0, r1 = [int(np.floor((y+offset-origin[1])/resolution)) for offset in (-.165,.165)]
        if not (0<=c0<=c1<raster.shape[1] and 0<=r0<=r1<raster.shape[0]):
            return False
        return bool(np.all(free[raster.shape[0]-1-r1:raster.shape[0]-r0, c0:c1+1]))
    map_audit = {"resolution": resolution, "origin": origin, "dimensions": list(raster.shape[::-1]),
                 "initial_model_pose": initial, "initial_padded_hull_free": hull_free(*initial[:2]),
                 "candidate_straight_segments": [], "qualification": "static map-only, not localization or planning"}
    for distance in (1.0, 3.0):
        samples = [(initial[0]+float(d),initial[1]) for d in np.arange(0,distance+.001,.025)]
        map_audit["candidate_straight_segments"].append({"goal": [initial[0]+distance,initial[1],0],
            "length_m": distance, "padded_hull_free_all_samples": all(hull_free(x,y) for x,y in samples)})
    (directory / "hotel_L1.yaml").write_bytes(map_path.read_bytes())
    (directory / "hotel_L1.pgm").write_bytes(image_path.read_bytes())
    (directory / "map-audit.json").write_text(json.dumps(map_audit,indent=2))
    report = {"source_world_sha256": hashlib.sha256(source_world.encode()).hexdigest(),
              "source_urdf_sha256": hashlib.sha256(source_urdf.encode()).hexdigest(),
              "outputs": {p.name: hashlib.sha256(p.read_bytes()).hexdigest() for p in directory.iterdir()}}
    (directory / "assets.json").write_text(json.dumps(report, indent=2))
    return report
