"""Opt-in rear ball supports for the private simplified robot, not canonical assets.

Like upstream Waffle, use two freely rotating ball-joint casters. Locations are
adapted to this demo's smaller box hull; all existing collisions/inertias remain.
URDF represents spherical centres as fixed transforms (orientation is immaterial
to a sphere); dynamics are defined only by the Gazebo SDF ball joints.
"""
import xml.etree.ElementTree as ET


CASTERS = (("rear_left_caster", -.14, .064), ("rear_right_caster", -.14, -.064))


def add_rear_casters(world_text, urdf_text):
    world,urdf=ET.fromstring(world_text),ET.fromstring(urdf_text)
    robot=world.find(".//model[@name='robot_1']")
    if robot is None or len(robot.findall("link/collision"))!=4:
        raise ValueError("expected original four-collision robot")
    base=robot.find("link[@name='base_link']/collision[@name='base_collision']")
    if (base is None or [float(x) for x in base.findtext("pose", "").split()]!=[-.032,0,.07,0,0,0]
            or [float(x) for x in base.findtext("geometry/box/size", "").split()]!=[.28,.31,.14]):
        raise ValueError("unqualified chassis geometry")
    for side in ("left","right"):
        wheel=robot.find(f"link[@name='wheel_{side}_link']")
        y=.144 if side=="left" else -.144
        if (wheel is None or [float(x) for x in wheel.findtext("pose", "").split()]!=[0,y,.023,-1.57,0,0]
                or float(wheel.findtext("collision/geometry/cylinder/radius", "nan"))!=.033):
            raise ValueError("unqualified wheel geometry")
    for name,x,y in CASTERS:
        if robot.find(f"link[@name='{name}']") is not None or urdf.find(f"link[@name='{name}']") is not None:
            raise ValueError("refusing duplicate caster")
        robot.append(ET.fromstring(f'''<link name="{name}"><pose>{x} {y} -0.005 0 0 0</pose>
          <inertial><mass>0.001</mass><inertia><ixx>1e-8</ixx><iyy>1e-8</iyy><izz>1e-8</izz></inertia></inertial>
          <collision name="support"><geometry><sphere><radius>0.005</radius></sphere></geometry>
            <surface><friction><ode><mu>1</mu><mu2>1</mu2></ode>
              <bullet><friction>1</friction><friction2>1</friction2></bullet></friction></surface></collision>
          <visual name="support"><geometry><sphere><radius>0.005</radius></sphere></geometry></visual></link>'''))
        robot.append(ET.fromstring(f'''<joint name="{name}_joint" type="ball">
          <parent>base_link</parent><child>{name}</child></joint>'''))
        urdf.append(ET.fromstring(f'''<link name="{name}">
          <collision><geometry><sphere radius="0.005"/></geometry></collision>
          <visual><geometry><sphere radius="0.005"/></geometry></visual></link>'''))
        urdf.append(ET.fromstring(f'''<joint name="{name}_centre" type="fixed">
          <parent link="base_link"/><child link="{name}"/><origin xyz="{x} {y} -0.005" rpy="0 0 0"/></joint>'''))
    return ET.tostring(world,encoding="unicode"),ET.tostring(urdf,encoding="unicode")
