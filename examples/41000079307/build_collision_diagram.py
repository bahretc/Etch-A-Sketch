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
# The DMV-349 narratives correct several TEAAS types before plotting, the
# way the NCDOT deck requires: a ditch is not a fixed object cell, an
# overturn after leaving the road plots as ran off road, and Other Non
# Collision has no cell at all. Direction of departure comes from the
# narrative, which also sets which side of the line the cell belongs on.
RETYPE = {
    "107822778": 2,   # WB, crossed centreline, ran off road to the LEFT
    "108067609": 2,   # WB, ran off road to the LEFT, struck ditch
    "107089722": 3,   # EB on SR 1321, ran off roadway STRAIGHT AHEAD
    "107666960": 3,   # NB on SR 1321, ran off road STRAIGHT AHEAD
    "106918221": 2,   # EB, crossed centreline, ran off road to the LEFT
    "108052444": 1,   # WB, ran off road to the RIGHT, struck ditch
    "108309866": 2,   # EB, over corrected, ran off road to the LEFT
}
for c in crashes:
    if c.crash_id in RETYPE:
        c.acc_typ = RETYPE[c.crash_id]

crashes.append(DiagramCrash(
    crash_id="108075100", mp=1.800, dt="04/05/2025 12:00",
    severity="O", acc_typ=19, road_cond="D", night=False,
    units=[Unit(1, "E", None, 4)]))
# Strip studies number by milepost then by date; intersection studies
# number by date (NCDOT Collision Diagrams deck, step 1 method 2).
from safety_eval.collision_diagram import _sortable_dt  # noqa: E402
crashes.sort(key=lambda c: (c.mp if c.mp is not None else 0.0,
                            _sortable_dt(c.dt)))
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
        f"WO #{WO}",
        "Robeson County",
        "SR 1320 (Milk Dairy Road) from Stone Drive",
        "to SR 1387 (Springside Road)",
        "7/1/2021 - 6/30/2026",
    ],
    "title_x": 430,
    "north_x": 856,
    "route_label": [
        "SR 1320 (Milk Dairy Road)",
        "AADT: 1,000 vpd (2024)",
        "55 mph",
    ],
    "route_label_xy": [455, 906],
    "notes": [
        {"x": 1330, "y": 640,
         "text": ["Crash #12 coded 0.007 mile east of",
                  "SR 1387; added at the study end,",
                  "MP 1.800"]},
        {"x": 1330, "y": 726,
         "text": ["Crash #10: second unit was an ATV",
                  "crossing SR 1320 from a dirt road"]},
    ],
    "nudges": {},
    "route_forward": "E",
    # McInnis Road leaves SR 1320 heading 192 degrees, so the stub and
    # the crashes mileposted onto the junction from it belong south of
    # the mainline (checked against the OSM centreline for the section)
    "junctions": [
        {"mp": 1.45, "label": "SR 1321 (McInnis Rd)", "side": -1},
    ],
    # sides the narratives establish, where the coded type alone would
    # put the cell on the wrong side of the centreline
    "sides": {
        "107089722": -1,        # SR 1321 approach, south of SR 1320
        "107666960": -1,        # SR 1321 approach, south of SR 1320
        "108244836": -1,        # off to the left while turning right onto
                                # SR 1321, so the departure is southbound
    },
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
