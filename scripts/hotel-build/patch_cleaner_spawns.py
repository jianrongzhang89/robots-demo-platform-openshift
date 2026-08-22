"""
Patch hotel.world AND cleanerBotA nav graph to place cleanerBotA robots
in the open south lobby instead of their enclosed spawn rooms.

The EasyFullControl fleet adapter sends each robot to its charger waypoint
at startup. To keep cleaners in the lobby, we must move BOTH:
  1. The spawn pose in hotel.world (where Gazebo places the model)
  2. The charger waypoint in nav_graphs/1.yaml (where fleet_adapter parks the robot)
"""
import yaml

# ── 1. Patch hotel.world spawn poses ──────────────────────────────────────────
WORLD = "/opt/rmf_demos_ws/install/share/rmf_demos_maps/maps/hotel/hotel.world"
content = open(WORLD).read()

old1 = "26.364960871641816 -27.752566946910367 0.0 0 0 -1.1937327924690353"
old2 = "29.239395125069194 -27.6631445578858 0.0 0 0 1.3444867767299777"
new1 = "19.0 -32.0 0.0 0 0 0.0"   # cleanerBotA_1: open west lobby
new2 = "23.0 -32.0 0.0 0 0 0.0"   # cleanerBotA_2: open center lobby

assert old1 in content, "cleanerBotA_1 spawn not found in hotel.world"
assert old2 in content, "cleanerBotA_2 spawn not found in hotel.world"
content = content.replace(old1, new1).replace(old2, new2)
open(WORLD, "w").write(content)
print(f"hotel.world: cleanerBotA_1 -> (19,-32), cleanerBotA_2 -> (23,-32)")

# ── 2. Patch nav_graph charger waypoints ──────────────────────────────────────
NAV = "/opt/rmf_demos_ws/install/share/rmf_demos_maps/maps/hotel/nav_graphs/1.yaml"
with open(NAV) as f:
    g = yaml.safe_load(f)

for lvl, data in g.get("levels", {}).items():
    for v in data.get("vertices", []):
        name = v[2].get("name", "") if len(v) > 2 else ""
        if name == "cleanerbot_charger1":
            v[0], v[1] = 19.0, -32.0
            print(f"nav_graph: cleanerbot_charger1 -> (19,-32)")
        elif name == "cleanerbot_charger2":
            v[0], v[1] = 23.0, -32.0
            print(f"nav_graph: cleanerbot_charger2 -> (23,-32)")

with open(NAV, "w") as f:
    yaml.dump(g, f, default_flow_style=False, allow_unicode=True)

print("Cleaner spawn + charger patches applied.")
