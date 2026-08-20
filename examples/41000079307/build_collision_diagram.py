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
    Unit, build_section_diagram, read_data_csv, write_data_csv)

SP = ("/tmp/claude-0/-home-user-Etch-A-Sketch/"
      "4d83860a-51f4-5f7b-a60e-765168dfbb13/scratchpad/cd79307")
REPO = "/home/user/Etch-A-Sketch/examples/41000079307"
WO = "41000079307"
os.makedirs(SP, exist_ok=True)

crashes = read_data_csv(f"{REPO}/{WO}_CollisionDiagramData.txt")

with open(f"{REPO}/mapdata/centerline.json", encoding="utf-8") as fh:
    #: SR 1320 between the study limits, as [lat, lon] along the road.
    CENTERLINE = [list(p) for p in json.load(fh)["study"]]

#: Milepost the review settled on, where it differs from the export.
REVIEW_MP = {
    "107089722": 1.450,     # RE: SR 1321 approach, carried through the junction
    "107666960": 1.450,     # RE: SR 1321 approach, carried through the junction
    "108075100": 1.800,     # ADD: SR 1387 junction crash at the study terminus
}

#: TEAAS types 107421047 an ANGLE and the Crash Analysis export carries
#: two units for it, but the collision diagram export drops unit two: it
#: has no direction, speed or maneuver coded, and the plotting program
#: needs a direction. The through vehicle on SR 1320 is restored here so
#: the crash draws as the angle it is; its speed stays unknown because
#: the export does not carry one.
ADD_UNIT = {
    "107421047": ("S", None, 4),    # the crossing ATV, direction per the
                                    # engineer; TEAAS codes it with no data
}

#: Direction the review resolves for a unit whose coded direction cannot
#: be right. 107421047 unit 1 is the through vehicle on SR 1320 but is
#: coded southbound; on an east-west road the through unit is eastbound
#: per the engineer's read, and its 55 mph stays with it.
REDIRECT = {
    "107421047": "E",
}

#: Severity the review resolves where TEAAS codes unknown. 107822778 is
#: SVRTY 6 (unknown); the Intersection Analysis Report shows zero K/A/B/C
#: injuries and $9,500 damage, so it is property damage only.
RESEVERITY = {
    "107822778": "O",
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
    if c.crash_id in REDIRECT:
        c.units[0].direction = REDIRECT[c.crash_id]
    if c.crash_id in ADD_UNIT and len(c.units) == 1:
        d, sp, mv = ADD_UNIT[c.crash_id]
        c.units.append(Unit(2, d, sp, mv))
    if c.crash_id in RESEVERITY:
        c.severity = RESEVERITY[c.crash_id]

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
    # The road label sits by the road it names, the way the NCDOT
    # examples letter each approach.
    "route_label_xy": [1000, 570],
    # Both turning crashes left the road during the turn, which the cell
    # cannot show alongside the corner, so each carries a note.
    # Each note sits by the crash it explains, so nothing has to be read
    # off a list in the corner.
    "notes": [
        {"x": 232, "y": 812,
         "text": ["Crash #6: eastbound vehicle",
                  "turning right onto SR 1321",
                  "ran off the road to the left."]},
        # TEAAS carries two units for this one: unit 2 is vehicle type 27,
        # the only one in the study that is not an ordinary passenger
        # type, and it has no direction, speed or maneuver coded. The
        # collision diagram export drops it for want of a direction, so
        # the cell shows one vehicle and the note carries the rest.
        {"x": 1155, "y": 726,
         "text": ["Crash #10: an ATV entered SR 1320 southbound",
                  "from a driveway without yielding."]},
        {"x": 1200, "y": 782,
         "text": ["Crash #12: ran the stop sign on SR 1387 and",
                  "left the road to the right while turning",
                  "onto SR 1320. Carried at the end, MP 1.800."]},
    ],
    "nudges": {},
    "route_forward": "E",
    # The drawn line follows the real alignment: a steep run down to the
    # McInnis Road corner, then a long, near flat leg east to Springside
    # Road. Points are the TEAAS centreline between the study limits,
    # projected and drawn north up.
    "centerline": CENTERLINE,
    "road_box": [150, 330, 1470, 800],
    # McInnis Road leaves SR 1320 heading 192 degrees, so its stub and the
    # crashes remileposted onto the junction from it sit south of the line
    # Sides checked against the OSM centreline: McInnis Road leaves SR 1320
    # heading 192 degrees and Springside Road 38 degrees, so one is south
    # of the line and the other north. The begin junction is the local
    # street OSM carries as Hucks Drive, leaving to the southwest; TEAAS
    # names the study from it as Stone Drive.
    # Bearing is the direction each side road leaves SR 1320, measured off
    # the OSM geometry where it carries the road: McInnis Road 192,
    # Springside 20. Stone Drive leaves to the north-northeast at the bend
    # per the engineer's aerial (OSM carries no street by that name; its
    # Hucks Drive is a different leg further west). The two Watermelon
    # Road legs are in neither the TEAAS Features Report nor the OSM
    # extract, so their mileposts come off the aerial as well and want
    # checking against the county map before this is issued.
    "junctions": [
        {"mp": 1.31, "label": "Stone Dr", "bearing": 32},
        {"mp": 1.45, "label": "SR 1321 (McInnis Rd)", "bearing": 192},
        {"mp": 1.54, "label": "Watermelon Rd", "bearing": 185},
        {"mp": 1.62, "label": "Watermelon Rd", "bearing": 200},
        {"mp": 1.80, "label": "SR 1387 (Springside Rd)", "bearing": 20},
    ],
    # sides the narratives establish, where the coded type alone would put
    # the cell on the wrong side of the centreline
    # approach headings for the two crashes that came in off a side road,
    # where the cardinal direction code cannot say which leg they used
    # Two crashes the milepost search cannot resolve on its own: the ADD
    # crash belongs in the northwest quadrant of the SR 1387 junction, and
    # 108309866 stacks out of reach of the line among the five that share
    # the SR 1321 station.
    # Pins are for crashes whose position the domain fixes, not for
    # working around placement: which leg of a junction a crash came in
    # on, and which quadrant it ended up in. Everything else is placed by
    # the rule, so a sheet does not need hand tuning to read.
    "at": {
        "107421047": [1319, 597],   # the angle at the crossing: the pin
                                    # keeps the crossing arm at the track,
                                    # which the mainline clearance search
                                    # can never accept on its own
        "107829164": [326, 684],    # at its station, downstream of 1
        "106918221": [678, 700],    # at its station, past Watermelon Rd
        "107089722": [489, 749],    # up the SR 1321 approach, beside 5
        "107666960": [452, 738],    # up the SR 1321 approach
        "108244836": [420, 747],    # off to the left in the SR 1321 turn
        "108075100": [1414, 742],   # SW quadrant, south of SR 1320 and
                                    # west of the stub, per the engineer
    },
    "headings": {
        "107089722": -78,       # ran the SR 1321 stop sign straight ahead,
                                # same movement as 107666960 beside it
        "107666960": -78,       # northbound on SR 1321, so the cell runs
                                # parallel to that leg, not square to it
        "108244836": 38,        # eastbound into the SR 1321 turn, SE quad
        "108075100": 120,       # down SR 1387 toward SR 1320, SW
    },
    "sides": {
        "107666960": -1,        # northbound SR 1321, so on the east half
                                # of that approach, south of SR 1320
        "108244836": -1,        # off to the left while turning right onto
                                # SR 1321, so the departure is southbound
        "108075100": -1,        # left the road to the right off the turn
                                # onto SR 1320, so it ends south of it
    },
    "prepared_by": "Chris Bahret, PE",
    "date": "8/20/2026",
    "logo": "/home/user/Etch-A-Sketch/examples/41000079305/mapdata/"
            "vhb_logo.png",
}
with open(f"{SP}/layout.json", "w") as fh:
    json.dump(layout, fh, indent=1)

n = build_section_diagram(f"{SP}/{WO}_CollisionDiagram.html",
                          f"{SP}/{WO}_CollisionDiagramData_plotted.txt",
                          f"{SP}/layout.json")
print(f"{n} crashes -> {SP}/{WO}_CollisionDiagram.html")
