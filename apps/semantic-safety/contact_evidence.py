"""Read-only contact instrumentation and strict offline baseline assessment."""
import xml.etree.ElementTree as ET
from support_geometry import CASTERS


HOTEL_SUPPORT_PAIRS = frozenset(tuple(sorted((
    "sim_world::hotel_L1::floor_3::collision",
    "sim_world::robot_1::"+wheel))) for wheel in (
        "wheel_left_link::left_wheel_collision", "wheel_right_link::right_wheel_collision"))
# Deliberately excludes chassis/lidar and every other floor/wall/object. The
# present four-collision robot has no caster; chassis-floor contact is a failed
# geometry precondition, not an implicit exemption or a collision-free result.
ORIGINAL_COLLISIONS=frozenset("robot_1::"+name for name in (
    "base_link::base_collision","base_scan::lidar_collision",
    "wheel_left_link::left_wheel_collision","wheel_right_link::right_wheel_collision"))


def collision_inventory(rear_casters=False):
    return ORIGINAL_COLLISIONS | (frozenset("robot_1::"+name+"::support" for name,_,_ in CASTERS)
                                  if rear_casters else frozenset())


def support_pairs(rear_casters=False):
    extra=frozenset(tuple(sorted(("sim_world::hotel_L1::floor_3::collision",
            "sim_world::robot_1::"+name+"::support"))) for name,_,_ in CASTERS)
    return HOTEL_SUPPORT_PAIRS | (extra if rear_casters else frozenset())


def instrument(world, *, rear_casters=False):
    tree=ET.fromstring(world)
    robot=tree.find(".//model[@name='robot_1']")
    names=set() if robot is None else {"robot_1::"+link.get("name")+"::"+c.get("name")
        for link in robot.findall("link") for c in link.findall("collision")}
    if names!=collision_inventory(rear_casters):
        raise ValueError("unexpected robot collision inventory")
    if robot.find("plugin[@name='phase5::ContactAudit']") is not None:
        raise ValueError("contact audit already installed")
    plugin=ET.SubElement(robot,"plugin",filename="libphase5_contact_audit.so",name="phase5::ContactAudit")
    ET.SubElement(plugin,"expected_collision_count").text=str(len(names))
    return ET.tostring(tree,encoding="unicode")


def assess(rows, *, allowed_pairs, start_sim, end_sim, expected_names=None):
    """Cumulative counters prevent missed contacts between sampled messages.

    allowed_pairs must be explicitly reviewed exact collision names. No substring
    'floor' exemption; no silence-is-clear or receipt-time freshness fallback.
    """
    try:
        return _assess(rows,allowed_pairs=allowed_pairs,start_sim=start_sim,end_sim=end_sim,expected_names=expected_names)
    except (KeyError,TypeError,ValueError):
        return {"passed":False,"reason":"malformed_contact_evidence"}


def _assess(rows, *, allowed_pairs, start_sim, end_sim, expected_names):
    if end_sim<=start_sim: return {"passed":False,"reason":"empty_contact_window"}
    if not rows: return {"passed":False,"reason":"missing_contact_evidence"}
    ordered=[r for r in rows if r["sim_ns"]>=start_sim-100_000_000 and r["sim_ns"]<=end_sim+100_000_000]
    if not ordered or ordered[0]["sim_ns"]>start_sim or ordered[-1]["sim_ns"]<end_sim:
        return {"passed":False,"reason":"contact_window_not_bracketed"}
    previous=None; unexpected=[]
    initial={(p["a"],p["b"]):p["contact_steps"] for p in ordered[0]["pairs"]}
    previous_counts=initial
    monitored=ordered[0]["monitored"]
    for row in ordered:
        valid_inventory=({m["name"] for m in row["monitored"]}==set(expected_names)
                         if expected_names is not None else len(row["monitored"])==4)
        if row["missing"] or not valid_inventory or row["monitored"]!=monitored:
            return {"passed":False,"reason":"contact_component_missing"}
        if previous and (row["steps"]<=previous["steps"] or row["sim_ns"]<=previous["sim_ns"]
                         or row["sim_ns"]-previous["sim_ns"]>200_000_000
                         or not 0<row["wall_ns"]-previous["wall_ns"]<=200_000_000):
            return {"passed":False,"reason":"contact_coverage_gap_or_rollback"}
        previous=row
        current={(p["a"],p["b"]):p["contact_steps"] for p in row["pairs"]}
        if any(current.get(pair,-1)<count for pair,count in previous_counts.items()):
            return {"passed":False,"reason":"contact_counter_rollback"}
        previous_counts=current
        for pair in row["pairs"]:
            names=tuple(sorted((row["names"][str(pair["a"])],row["names"][str(pair["b"])])))
            if (names not in allowed_pairs and pair["contact_steps"]>initial.get((pair["a"],pair["b"]),0)
                    and names not in unexpected):
                unexpected.append(names)
    return {"passed":not unexpected,"reason":"unexpected_contact" if unexpected else "clear",
            "unexpected":unexpected,"samples":len(ordered),"steps":ordered[-1]["steps"]-ordered[0]["steps"],
            "qualification":"exact allowlisted support contacts only; no force/depth exemption"}
