import json
import re

import pytest

from safety_eval import collision_diagram as cd


def make_crash(**kw):
    base = dict(crash_id="100000001", mp=1.5, dt="01/02/2024 13:00",
                severity="B", acc_typ=19, road_cond="W", night=False,
                units=[cd.Unit(1, "E", 45, 4)])
    base.update(kw)
    return cd.DiagramCrash(**base)


def test_code_mappings():
    assert cd.severity_from_code(1) == "K"
    assert cd.severity_from_code("4") == "C"
    assert cd.severity_from_code("") == "O"
    assert cd.road_cond_letter(1) == "D"
    assert cd.road_cond_letter(2) == "W"
    assert cd.road_cond_letter(5) == "I"
    assert cd.acc_type_code("REAR END, SLOW OR STOP") == 21
    assert cd.acc_type_code("RAN OFF ROAD - LEFT") == 2
    assert cd.acc_type_code("SIDESWIPE, OPPOSITE DIRECTION") == 29
    assert cd.acc_type_code("OVERTURN/ROLLOVER") == 5
    assert cd.acc_type_code("banana") == 13


def test_data_csv_round_trip(tmp_path):
    crashes = [
        make_crash(),
        make_crash(crash_id="100000002", severity="K", acc_typ=21,
                   night=True, road_cond="D",
                   units=[cd.Unit(1, "W", 55, 4), cd.Unit(2, "W", 0, 1)]),
    ]
    p = tmp_path / "data.txt"
    cd.write_data_csv(str(p), crashes, county_nbr="78",
                      on_road_cd="40001320")
    back = cd.read_data_csv(str(p))
    assert [c.crash_id for c in back] == ["100000001", "100000002"]
    two = back[1]
    assert two.severity == "K" and two.night and two.acc_typ == 21
    assert [u.direction for u in two.units] == ["W", "W"]
    assert two.units[0].speed == 55
    assert back[0].road_cond == "W" and not back[0].night
    assert [c.seq for c in back] == [1, 2]


def test_initial_study_parse(tmp_path):
    rows = (
        '"1","107822778","1.413","08/18/2024 05:08","OVERTURN/ROLLOVER",'
        '"$","9500","0","0","0","0","1","5","1","5","0","13","1"\n'
        '"Unit","1",":","4","Alchl/Drgs:","7","Speed:","45","MPH","Dir:",'
        '"W","Veh Mnvr/Ped Actn:","4","Obj Strk:","58"\n'
        '"2","107304540","1.469","04/14/2023 16:51","REAR END, SLOW OR '
        'STOP","$","2200","0","0","0","0","1","1","1","1","0","0",""\n'
        '"Unit","1",":","1","Alchl/Drgs:","0","Speed:","45","MPH","Dir:",'
        '"W","Veh Mnvr/Ped Actn:","4","Obj Strk:",""\n'
        '"Unit","2",":","1","Alchl/Drgs:","0","Speed:","0","MPH","Dir:",'
        '"W","Veh Mnvr/Ped Actn:","1","Obj Strk:",""\n')
    p = tmp_path / "InitialStudy.csv"
    p.write_text(rows)
    crashes = cd.crashes_from_initial_study(str(p))
    assert len(crashes) == 2
    ovr, re_ = crashes
    assert ovr.acc_typ == 5 and ovr.night and ovr.road_cond == "W"
    assert ovr.units[0].direction == "W" and ovr.units[0].speed == 45
    assert re_.acc_typ == 21 and not re_.night and re_.road_cond == "D"
    assert len(re_.units) == 2 and re_.units[1].speed == 0


def test_section_sheet_places_every_crash_on_page(tmp_path):
    crashes = [make_crash(crash_id=str(100000000 + i), mp=1.45,
                          dt=f"01/{i + 1:02d}/2024 12:00")
               for i in range(8)]
    data = tmp_path / "data.txt"
    cd.write_data_csv(str(data), crashes)
    layout = {"type": "section", "begin_mp": 1.31, "end_mp": 1.80,
              "title": ["t"], "route_label": ["r"],
              "junctions": [{"mp": 1.45, "label": "SR 1321", "side": 1}],
              "prepared_by": "x", "date": "1/1/2026"}
    lp = tmp_path / "layout.json"
    lp.write_text(json.dumps(layout))
    out = tmp_path / "sheet.html"
    n = cd.build_section_diagram(str(out), str(data), str(lp))
    assert n == 8
    html = out.read_text()
    groups = [(float(x), float(y)) for x, y in re.findall(
        r'<g transform="translate\(([-\d.]+),([-\d.]+)\)">', html)]
    crash_groups = groups[:8] if len(groups) >= 8 else groups
    assert len([g for g in groups]) >= 8
    for x, y in crash_groups:
        assert 20 < x < cd.PAGE_W - 20 and 20 < y < cd.PAGE_H - 20


def test_stroke_text_renders_strokes_or_falls_back():
    svg = cd._stroke_text(100, 50, "TEST 123", size=12)
    assert ("path d=" in svg) or ("<text" in svg)
    if cd._HFONT is not None:
        assert "path d=" in svg and "translate(100.0,50.0)" in svg
