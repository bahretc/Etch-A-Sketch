"""Collision diagram for study 41000079307 in the TSU MicroStation idiom.

Reads the TEAAS CollisionDiagramData export as delivered and renders the
11x17 section sheet from it. Two layers sit on top of the export, both
from the fiche review and the DMV-349 narratives:

* review mileposts, so the two SR 1321 approach crashes plot at the
  junction they were remileposted to and the SR 1387 crash plots at the
  study terminus it was added at;
* crash types, because TEAAS codes a ditch strike as FIXED OBJECT, a
  rollover after leaving the road as OVERTURN and one of these as OTHER
  NON-COLLISION, none of which has a cell. The NCDOT deck requires the
  type be corrected before plotting.
"""
import json
import os
import sys

sys.path.insert(0, "/home/user/Etch-A-Sketch")

from safety_eval.collision_diagram import (  # noqa: E402
    build_section_diagram, read_data_csv, write_data_csv)

SP = ("/tmp/claude-0/-home-user-Etch-A-Sketch/"
      "4d83860a-51f4-5f7b-a60e-765168dfbb13/scratchpad/cd79307")
REPO = "/home/user/Etch-A-Sketch/examples/41000079307"
WO = "41000079307"
os.makedirs(SP, exist_ok=True)

crashes = read_data_csv(f"{REPO}/{WO}_CollisionDiagramData.txt")

#: Milepost the review settled on, where it differs from the export.
REVIEW_MP = {
    "107089722": 1.450,     # RE: SR 1321 approach, carried through the junction
    "107666960": 1.450,     # RE: SR 1321 approach, carried through the junction
    "108075100": 1.800,     # ADD: SR 1387 junction crash at the study terminus
}

#: Type the DMV-349 narrative supports, where the coded type has no cell
#: or contradicts the report.
RETYPE = {
    "107822778": 2,   # WB, crossed centreline, ran off road to the LEFT
    "108067609": 2,   # WB, ran off road to the LEFT, struck ditch
    "107089722": 3,   # ran the stop sign, off the roadway STRAIGHT AHEAD
    "107666960": 3,   # NB SR 1321, off the roadway STRAIGHT AHEAD
    "106918221": 2,   # EB, crossed centreline, ran off road to the LEFT
    "108052444": 1,   # WB, ran off road to the RIGHT, struck ditch
    "108309866": 2,   # EB, over corrected, ran off road to the LEFT
    "108075100": 1,   # SB SR 1387, off to the RIGHT turning onto SR 1320
}

for c in crashes:
    if c.crash_id in REVIEW_MP:
        c.mp = REVIEW_MP[c.crash_id]
    if c.crash_id in RETYPE:
        c.acc_typ = RETYPE[c.crash_id]

# The export is already in the order TEAAS wants them plotted, matching
# 41000079307_CrashID.txt: milepost, then date. Keep it.
for i, c in enumerate(crashes, start=1):
    c.seq = i

write_data_csv(f"{SP}/{WO}_CollisionDiagramData_plotted.txt", crashes,
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
    "route_label_xy": [250, 604],
    "notes": [
        {"x": 1330, "y": 640,
         "text": ["Crash #12: ran the stop sign on SR 1387",
                  "and left the road turning onto SR 1320.",
                  "Carried at the study end, MP 1.800"]},
        {"x": 1330, "y": 726,
         "text": ["Crash #10: second unit was an ATV",
                  "crossing SR 1320 from a dirt road"]},
    ],
    "nudges": {},
    "route_forward": "E",
    # McInnis Road leaves SR 1320 heading 192 degrees, so its stub and the
    # crashes remileposted onto the junction from it sit south of the line
    "junctions": [
        {"mp": 1.45, "label": "SR 1321 (McInnis Rd)", "side": -1},
    ],
    # sides the narratives establish, where the coded type alone would put
    # the cell on the wrong side of the centreline
    "sides": {
        "107089722": -1,        # SR 1321 approach, south of SR 1320
        "107666960": -1,        # SR 1321 approach, south of SR 1320
        "108244836": -1,        # off to the left while turning right onto
                                # SR 1321, so the departure is southbound
        "108075100": -1,        # off to the right through a left turn from
                                # SR 1387, coming to rest facing east
    },
    "prepared_by": "Chris Bahret, PE",
    "date": "8/18/2026",
    "logo": "/home/user/Etch-A-Sketch/examples/41000079305/mapdata/"
            "vhb_logo.png",
}
with open(f"{SP}/layout.json", "w") as fh:
    json.dump(layout, fh, indent=1)

n = build_section_diagram(f"{SP}/{WO}_CollisionDiagram.html",
                          f"{SP}/{WO}_CollisionDiagramData_plotted.txt",
                          f"{SP}/layout.json")
print(f"{n} crashes -> {SP}/{WO}_CollisionDiagram.html")
