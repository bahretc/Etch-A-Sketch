"""The measured-junction collision diagram: spec loading, crash resolution,
and the placement contract (every cell on the pavement, none over another
or over the linework, overflow in insets)."""
import csv
import json
import os

import pytest

from safety_eval import collision_diagram as cd
from safety_eval import junction_diagram as jd


def four_leg_spec():
    """A plain four-leg signalized crossing: Main Street east-west with a
    left lane and two through lanes each way, Side Street north-south
    with one lane each way, curbs filleted at the corners, crosswalks
    on every leg."""
    legs = {}
    for key, brg, road, codes in (("E", 90, "MAIN", ["10000001"]), ("W", 270, "MAIN", ["10000001"]),
                                  ("N", 0, "SIDE", ["20000002"]), ("S", 180, "SIDE", ["20000002"])):
        if road == "MAIN":
            legs[key] = {"bearing": brg, "road": road, "codes": codes, "stop": 40, "cw": [28, 38],
                         "in_edge": -36, "out_edge": 36, "centre": 0,
                         "lanes_in": {"L": -6, "T1": -18, "T2": -30}, "lanes_out": {"T1": 18, "T2": 30},
                         "lines": [[-12, 40, "FAR", "dashed"], [-24, 40, "FAR", "dashed"],
                                   [12, 40, "FAR", "dashed"], [24, 40, "FAR", "dashed"]],
                         "double": [[0, 40, "FAR"]]}
        else:
            legs[key] = {"bearing": brg, "road": road, "codes": codes, "stop": 40, "cw": [28, 38],
                         "in_edge": -14, "out_edge": 14, "centre": 0,
                         "lanes_in": {"T1": -7}, "lanes_out": {"T1": 7},
                         "lines": [], "double": [[0, 40, "FAR"]]}
    edges = []
    for a, na, b, nb in (("E", -36, "S", 14), ("S", -14, "W", 36), ("W", -36, "N", 14), ("N", -14, "E", 36)):
        edges.append([{"leg": a, "a": "FAR", "n": na},
                      {"fillet": {"a": {"leg": a, "a": 60, "n": na}, "da": a,
                                  "b": {"leg": b, "a": 60, "n": nb}, "db": b, "r": 25}},
                      {"leg": b, "a": "FAR", "n": nb}])
    cws = []
    for key in ("E", "W", "N", "S"):
        L = legs[key]
        cws.append({"p0": {"leg": key, "a": 33, "n": L["in_edge"]}, "p1": {"leg": key, "a": 33, "n": L["out_edge"]},
                    "width": 8, "bar_brg": legs[key]["bearing"], "leg": key})
    return {
        "title": ["Order# 41000000000", "Test County", "Main Street at Side Street", "1/1/2020 - 12/31/2024"],
        "north": [655, 40], "rotate": 0.0, "px_per_ft": 2.8, "center": [800, 600], "cell_scale": 0.72,
        "signal": True, "main_road": "MAIN", "notes": ["Signalized intersection."],
        "order": ["N", "E", "S", "W"], "legs": legs, "edges": edges, "islands": [], "crosswalks": cws,
        "labels": [{"xy": [140, 560], "lines": ["Main Street", "AADT (Year)", "12,000 (2024)", "45 mph"]},
                   {"xy": [1450, 560], "lines": ["Main Street", "AADT (Year)", "12,000 (2024)", "45 mph"]}],
        "keep_out": [], "inset_rows": [[40, 700, 40, 300]],
    }


def crash(cid, typ, units, on="10000001", frm="20000002", dist=0.0, ddir="", sev="O", night=False):
    """Unit 1 carries the violation (is at fault) unless the units say otherwise."""
    if units and all(u.violation is None for u in units):
        units[0].violation = 12
    return cd.DiagramCrash(crash_id=cid, dt="01/02/2024 13:00", severity=sev, acc_typ=typ,
                           road_cond="D", night=night, units=units, on_road=on, from_road=frm,
                           dist_mi=dist, dist_dir=ddir)


def sample_crashes():
    U = cd.Unit
    out = [
        crash("100000001", 21, [U(1, "E", 35, 4), U(2, "E", 0, 1)]),                 # rear end EB at the bar
        crash("100000002", 21, [U(1, "E", 25, 4), U(2, "E", 0, 1)], night=True),
        crash("100000003", 21, [U(1, "W", 30, 4), U(2, "W", 5, 4)], sev="C"),
        crash("100000004", 30, [U(1, "E", 40, 4), U(2, "N", 20, 4)], sev="B"),      # angle
        crash("100000005", 30, [U(1, "E", 35, 4, violation=0), U(2, "N", 25, 4, violation=13)]),  # unit 2 at fault
        crash("100000006", 23, [U(1, "W", 15, 8), U(2, "E", 45, 4)], sev="A"),      # left turn vs opposing
        crash("100000007", 26, [U(1, "N", 10, 7), U(2, "W", 40, 4)]),               # right turn, different roads
        crash("100000008", 1, [U(1, "E", 55, 4)], sev="C"),                          # ran off road right
        crash("100000009", 14, [U(1, "N", 10, 4)], on="20000002", frm="10000001", sev="B"),  # pedestrian
        crash("100000010", 27, [U(1, "N", 30, 4, violation=33), U(2, "S", 30, 4, violation=33)],
              on="20000002", frm="10000001", sev="K"),                              # both at fault
        crash("100000011", 21, [U(1, "E", 40, 4), U(2, "E", 0, 1)], dist=0.05, ddir="W"),   # 264 ft out the west leg
        crash("100000012", 28, [U(1, "W", 40, 4), U(2, "W", 35, 4)]),               # sideswipe same direction
    ]
    for i, c in enumerate(out, 1):
        c.seq = i
    return out


def write_data(tmp_path, crashes):
    """A CollisionDiagramData export carrying each crash's own road codes
    and coded distance (the generic writer fixes those per file)."""
    p = tmp_path / "data.txt"
    sev = {"K": 1, "A": 2, "B": 3, "C": 4, "O": 5}
    cols = ["CRSH_ID", "CNTY_NBR", "MLPST_NBR", "NBR_UNT_CNT", "FRM_RD_CD", "RD_ON_CD",
            "DSTNC_MILE_FRM_RD_QTY", "DRCTN_FRM_RD_CD", "ACDNT_DT_TM", "SVRTY_CD", "ACC_TYP",
            "RD_CONFIG", "RD_COND", "LT_COND", "TRFC_CTRL", "SPD_LMT_NBR", "SPD_EST_NBR",
            "SPD_AT_IMPCT_NBR", "MANEUVER", "VIOLATION", "DIRECT", "UNT_NBR"]
    with open(str(p), "w", newline="") as fh:
        w = csv.writer(fh, quoting=csv.QUOTE_ALL)
        w.writerow(cols)
        for cr in crashes:
            for u in cr.units:
                w.writerow([cr.crash_id, "99", "999.999", len(cr.units), cr.from_road, cr.on_road,
                            f"{cr.dist_mi:.3f}", cr.dist_dir, cr.dt, sev[cr.severity], cr.acc_typ, "2",
                            "1", "5" if cr.night else "1", "1", "", u.speed if u.speed is not None else "",
                            "", u.maneuver or "", "", u.direction, u.number])
    return str(p)


def test_configure_and_resolution():
    jd.configure(four_leg_spec())
    assert jd.MAIN == "MAIN"
    assert jd.road_of("10000001") == "MAIN" and jd.road_of("20000002") == "SIDE"
    assert jd.road_of("30000003") is None
    assert jd.leg_of("10000001") is None          # two legs share the code
    c = sample_crashes()
    apps, turner = jd.resolve(c[3])
    assert apps == ["W_in", "S_in"] and turner is None
    apps, turner = jd.resolve(c[5])
    assert turner == 0 and apps[0] == "E_in" and apps[1] == "W_in"
    loc = jd.leg_from_location(c[10])
    assert loc is not None and loc[0] == "W" and abs(loc[1] - 264) < 0.5
    assert jd.leg_from_location(c[0]) is None


def test_geometry_helpers():
    assert jd.gap(("s", (0, 0), (10, 0), 1.0), ("s", (0, 5), (10, 5), 1.0)) == pytest.approx(3.0)
    assert jd.gap(("d", (0, 0), 2.0), ("d", (10, 0), 3.0)) == pytest.approx(5.0)
    assert jd.gap(("s", (0, 0), (10, 10), 0.5), ("s", (0, 10), (10, 0), 0.5)) == pytest.approx(-1.0)
    square = ("p", [(0, 0), (10, 0), (10, 10), (0, 10)])
    assert jd.gap(("d", (5, 5), 1.0), square) < 0
    assert jd.gap(("d", (15, 5), 1.0), square) == pytest.approx(4.0)
    jd.configure(four_leg_spec())
    assert jd.on_pavement((0.0, 0.0))
    assert jd.on_pavement((100.0, -20.0))
    assert not jd.on_pavement((60.0, 60.0))      # the sidewalk corner
    # n is right of outbound travel, so the east leg's westbound approach
    # lanes lie north of its centreline (y > 0)
    assert jd.on_travel_side((100.0, 20.0), 270.0)
    assert not jd.on_travel_side((100.0, -20.0), 270.0)


def _all_prims(cells):
    return [(c, p) for c in cells for p, _ in c.prims]


def test_render_places_every_crash_without_overlap(tmp_path):
    spec = four_leg_spec()
    crashes = sample_crashes()
    data = write_data(tmp_path, crashes)
    out = str(tmp_path / "sheet.html")
    res = jd.render(spec, data, out)
    assert res["crashes"] == len(crashes)
    assert res["placed"] + res["inset"] == len(crashes)
    assert res["unplaced"] == []
    assert os.path.exists(out)
    html = open(out, encoding="utf-8").read()
    for c in crashes:
        assert f'data-crash="{c.crash_id}"' in html
    with open(str(tmp_path / "sheet_index.csv"), newline="") as fh:
        rows = list(csv.DictReader(fh))
    assert [r["crash_id"] for r in rows] == [c.crash_id for c in crashes]
    assert all("not placed" not in r["placed_at"] for r in rows)
    with open(str(tmp_path / "sheet_review.csv"), newline="") as fh:
        rev = list(csv.DictReader(fh))
    where = {r["crash_id"]: r["placed_at"] for r in rev}
    assert where["100000001"].startswith("queue W_in")   # eastbound: the west leg approach
    assert where["100000004"].startswith("angle")
    assert where["100000006"].startswith("turn 23")
    assert where["100000009"].endswith("crosswalk")
    assert where["100000011"].startswith("W in at 264 ft")
    # the placement contract, checked on the cells themselves
    jd.configure(spec)
    roads, obstacles = jd.junction_svg()
    scene = jd.Scene(obstacles)
    _, rects = jd.furniture(["Signalized intersection."])
    for r in rects:
        scene.add_rect("furniture", r)
    _, sb = jd.signal_symbol()
    scene.add_rect("signal", sb)
    placed, overflow, chosen = jd.place(jd.plan(crashes), scene)
    assert not overflow
    # the fault indicator sits beside every unit whose driver was at fault, and nowhere else
    for c in placed:
        want = sum(1 for u in c.cr.units[:2] if u.violation)
        assert c.svg.count(cd.MAGENTA) == want, (c.cr.crash_id, c.svg.count(cd.MAGENTA), want)
    for i, a in enumerate(placed):
        for b in placed[i + 1:]:
            for p, _ in a.prims:
                for q, _ in b.prims:
                    assert jd.gap(p, q) >= jd.CLEAR_CELL - 1e-6, (a.cr.seq, b.cr.seq)
        for kind, prim in obstacles:
            if kind in a.exempt:
                continue
            if kind == "line":
                # a shaft may cross a painted line but never lie along it
                assert not any(p[0] == "s" and jd._along_line(p, prim) for p, _ in a.prims), (a.cr.seq, "line")
                continue
            for p, ex in a.prims:
                if ex and kind in ("edge", "cw", "stop", "island"):
                    continue
                need = 0.5 if kind == "edge" else jd.CLEAR_OBS
                assert jd.gap(p, prim) >= need - 1e-6, (a.cr.seq, kind)


def test_overflow_goes_to_a_lettered_inset(tmp_path):
    """Far more rear ends on one approach than the leg can hold: the
    extra cells go to an inset box with the letter marked at the queue."""
    spec = four_leg_spec()
    U = cd.Unit
    crashes = [crash(f"1000001{k:02d}", 21, [U(1, "N", 30, 4), U(2, "N", 0, 1)],
                     on="20000002", frm="10000001") for k in range(40)]
    for i, c in enumerate(crashes, 1):
        c.seq = i
    data = write_data(tmp_path, crashes)
    out = str(tmp_path / "many.html")
    res = jd.render(spec, data, out)
    assert res["inset"] > 0
    html = open(out, encoding="utf-8").read()
    assert 'data-at="inset A"' in html
    assert res["placed"] + res["inset"] + len(res["unplaced"]) == 40


def test_build_reads_spec_and_exclusions(tmp_path):
    spec_path = tmp_path / "spec.json"
    spec_path.write_text(json.dumps(four_leg_spec()))
    crashes = sample_crashes()
    data = write_data(tmp_path, crashes)
    excl = tmp_path / "drop.txt"
    excl.write_text("100000001\n100000002\n")
    out = str(tmp_path / "b.html")
    res = jd.build(str(spec_path), data, out, exclude_path=str(excl))
    assert res["crashes"] == len(crashes) - 2
    with open(str(tmp_path / "b_index.csv"), newline="") as fh:
        rows = list(csv.DictReader(fh))
    assert rows[0]["crash_id"] == "100000003" and rows[0]["sheet_no"] == "1"
