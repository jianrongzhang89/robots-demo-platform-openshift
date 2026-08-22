"""
Patch DeliveryRobot model.sdf to add a red material override so the robot
is clearly visible in the Gazebo view. The original model uses a gray texture
(DeliveryRobot_Diffuse.png) that is hard to spot. Red makes it stand out.
"""

SDF = "/opt/rmf_demos_ws/install/share/rmf_demos_assets/models/DeliveryRobot/model.sdf"
content = open(SDF).read()

# Find the body visual and add a red material
# We insert a <material> block after the <geometry> block in body_visual
old = '      <visual name="body_visual">\n        <geometry>\n          <mesh><uri>model://DeliveryRobot/meshes/body.obj</uri></mesh>\n        </geometry>\n      </visual>'
new = '      <visual name="body_visual">\n        <geometry>\n          <mesh><uri>model://DeliveryRobot/meshes/body.obj</uri></mesh>\n        </geometry>\n        <material>\n          <ambient>0.8 0.0 0.0 1</ambient>\n          <diffuse>0.8 0.0 0.0 1</diffuse>\n          <specular>0.2 0.0 0.0 1</specular>\n        </material>\n      </visual>'

if old in content:
    content = content.replace(old, new)
    open(SDF, "w").write(content)
    print("DeliveryRobot patched: body color -> RED")
else:
    # Simpler fallback: just insert material into first visual block
    old2 = '<visual name="body_visual">'
    if old2 in content:
        # Add material after the geometry closing tag in body_visual
        import re
        content = re.sub(
            r'(<visual name="body_visual">.*?<geometry>.*?</geometry>)',
            r'\1\n        <material>\n          <ambient>0.8 0.0 0.0 1</ambient>\n          <diffuse>0.8 0.0 0.0 1</diffuse>\n          <specular>0.2 0.0 0.0 1</specular>\n        </material>',
            content,
            count=1,
            flags=re.DOTALL
        )
        open(SDF, "w").write(content)
        print("DeliveryRobot patched (fallback): body color -> RED")
    else:
        print("WARNING: Could not find body_visual in DeliveryRobot model.sdf")
