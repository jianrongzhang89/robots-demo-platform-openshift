import os, textwrap
STUBS = [
    "BathroomSink","BedsideTable","Bookshelf","Cafe table","Chair",
    "CoffeeTable","Desk","DeskChair","DigitalKiosk","EscalatorStart",
    "FoodCourtBenchShort","FoodCourtTable1","Fridge","HeadphonesRack1",
    "KitchenCountertop","MainTable","NormalBed","NurseDesk","Shower",
    "Sofa","StorageRack","Suitcase1","Suitcase2","Toilet","TrashBin",
    "VendingMachine","WoodenChair",
]
BASE = "/opt/gz-models"
for name in STUBS:
    d = os.path.join(BASE, name)
    os.makedirs(d, exist_ok=True)
    with open(os.path.join(d, "model.config"), "w") as f:
        f.write(textwrap.dedent(f"""\
            <?xml version="1.0"?>
            <model>
              <name>{name}</name>
              <version>1.0</version>
              <sdf version="1.7">model.sdf</sdf>
              <description>Stub placeholder</description>
            </model>
        """))
    with open(os.path.join(d, "model.sdf"), "w") as f:
        f.write(textwrap.dedent(f"""\
            <?xml version="1.0"?>
            <sdf version="1.7">
              <model name="{name}">
                <static>true</static>
              </model>
            </sdf>
        """))
print(f"Created {len(STUBS)} stub models in {BASE}")
