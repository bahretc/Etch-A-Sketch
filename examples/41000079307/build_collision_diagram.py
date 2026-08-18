"""Collision diagram for study 41000079307 in the TSU MicroStation idiom.

Builds the analysis set the sealed review left standing: the Initial Study
strip crashes minus the deleted 106814981, the two junction crashes held at
MP 1.450, and 108075100 added at the SR 1387 junction (MP 1.800, fixed
object per the fiche). Emits the house CollisionDiagramData CSV alongside
the rendered sheet so the same data file could drive the MicroStation
template directly.
"""
import json
import sys

sys.path.insert(0, "/home/user/Etch-A-Sketch")

from safety_eval.collision_diagram import (  # noqa: E402
    DiagramCrash, Unit, build_section_diagram, crashes_from_initial_study,
    write_data_csv)

SP = ("/tmp/claude-0/-home-user-Etch-A-Sketch/"
      "4d83860a-51f4-5f7b-a60e-765168dfbb13/scratchpad/cd79307")
REPO = "/home/user/Etch-A-Sketch/examples/41000079307"
WO = "41000079307"

import os  # noqa: E402
os.makedirs(SP, exist_ok=True)

crashes = crashes_from_initial_study(f"{REPO}/InitialStudy.csv")
crashes = [c for c in crashes if c.crash_id != "106814981"]
for c in crashes:
    if c.crash_id in ("107089722", "107666960"):
        c.mp = 1.450
crashes.append(DiagramCrash(
    crash_id="108075100", mp=1.800, dt="04/05/2025 12:00",
    severity="O", acc_typ=19, road_cond="D", night=False,
    units=[Unit(1, "E", None, 4)]))
from safety_eval.collision_diagram import _sortable_dt  # noqa: E402
crashes.sort(key=lambda c: _sortable_dt(c.dt))
for i, c in enumerate(crashes, start=1):
    c.seq = i

write_data_csv(f"{SP}/{WO}_CollisionDiagramData.txt", crashes,
               county_nbr="78", on_road_cd="40001320",
               from_road_cd="40001321")

layout = {
    "type": "section",
    "begin_mp": 1.31, "end_mp": 1.80,
    "title": [
        "PH# 77S00141",
        f"Order# {WO}",
        "Robeson County",
        "SR 1320 (Milk Dairy Road) from",
        "Stone Drive [MP 1.31] to SR 1387",
        "(Springside Road) [MP 1.80]",
        "7/1/2021 - 6/30/2026",
    ],
    "title_x": 560,
    "north_x": 856,
    "route_label": [
        "SR 1320 (Milk Dairy Road)",
        "AADT (Year)",
        "1,000 (2024)",
        "55 mph",
    ],
    "route_label_xy": [350, 958],
    "notes": [
        {"x": 1340, "y": 690,
         "text": ["Crash #10: Entered SR 1320 turning",
                  "from SR 1387 at the study end"]},
    ],
    "nudges": {"108075100": [26, -12], "108309866": [-8, -22]},
    "route_forward": "E",
    "junctions": [
        {"mp": 1.45, "label": "SR 1321 (McInnis Rd)", "side": 1},
    ],
    "prepared_by": "Chris Bahret, PE",
    "date": "8/18/2026",
    "logo": "/home/user/Etch-A-Sketch/examples/41000079305/mapdata/"
            "vhb_logo.png",
}
with open(f"{SP}/layout.json", "w") as fh:
    json.dump(layout, fh, indent=1)

n = build_section_diagram(f"{SP}/{WO}_CollisionDiagram.html",
                          f"{SP}/{WO}_CollisionDiagramData.txt",
                          f"{SP}/layout.json")
print(f"{n} crashes -> {SP}/{WO}_CollisionDiagram.html")
