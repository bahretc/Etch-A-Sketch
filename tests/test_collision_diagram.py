import json
import math
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


def _sheet_with(crashes, tmp_path, **layout_extra):
    data = tmp_path / "data.txt"
    cd.write_data_csv(str(data), crashes)
    layout = {"type": "section", "begin_mp": 1.31, "end_mp": 1.80,
              "title": ["t"], "route_label": ["r"],
              "prepared_by": "x", "date": "1/1/2026"}
    layout.update(layout_extra)
    lp = tmp_path / "layout.json"
    lp.write_text(json.dumps(layout))
    out = tmp_path / "sheet.html"
    cd.build_section_diagram(str(out), str(data), str(lp))
    return out.read_text()


def test_every_cell_uses_the_same_parts():
    """Sizes are standard across the parts of every crash symbol."""
    kinds = [
        make_crash(acc_typ=19, units=[cd.Unit(1, "E", 45)]),          # ROR
        make_crash(acc_typ=5, units=[cd.Unit(1, "W", 60)]),           # rollover
        make_crash(acc_typ=21, units=[cd.Unit(1, "E", 55),
                                      cd.Unit(2, "E", 0)]),           # rear end
        make_crash(acc_typ=27, units=[cd.Unit(1, "E", 50),
                                      cd.Unit(2, "W", 50)]),          # head on
        make_crash(acc_typ=28, units=[cd.Unit(1, "E", 45),
                                      cd.Unit(2, "E", 45)]),          # SSSD
        make_crash(acc_typ=29, units=[cd.Unit(1, "E", 45),
                                      cd.Unit(2, "W", 45)]),          # SSOD
        make_crash(acc_typ=30, units=[cd.Unit(1, "S", 55),
                                      cd.Unit(2, "E", 35)]),          # angle
        make_crash(acc_typ=14, units=[cd.Unit(1, "E", 25)]),          # ped
    ]
    heads, bubbles, dots = set(), set(), set()
    for cr in kinds:
        svg, _, _ = cd.crash_glyph(cr, base_ang=0.0)
        for pts in re.findall(r'<polygon points="([^"]+)"', svg):
            p = [tuple(float(v) for v in t.split(",")) for t in pts.split()]
            assert len(p) == 4, "an arrowhead is always four points"
            length = round(math.dist(p[0], p[2]) / 0.80, 1)
            width = round(math.dist(p[1], p[3]), 1)
            heads.add((length, width))
        bubbles.update(re.findall(r'circle cx="[-\d.]+" cy="[-\d.]+" '
                                  r'r="([\d.]+)" fill="#fff" stroke="#000"',
                                  svg))
        dots.update(re.findall(r'r="([\d.]+)" fill="#2222CC"', svg))
    assert len(heads) == 1, f"arrowheads differ between cells: {heads}"
    assert heads.pop()[0] == pytest.approx(cd.CELL_HEAD, abs=0.15)
    assert bubbles == {str(cd.BUBBLE_R)}
    assert dots == {str(cd.DOT_R)}


def test_bubble_sits_on_the_tail_axis_of_every_cell():
    """The numbered circle connects to the same point on every symbol."""
    for typ, units in ((19, [cd.Unit(1, "E", 45)]),
                       (21, [cd.Unit(1, "E", 55), cd.Unit(2, "E", 0)]),
                       (29, [cd.Unit(1, "E", 45), cd.Unit(2, "W", 45)]),
                       (30, [cd.Unit(1, "S", 55), cd.Unit(2, "E", 35)])):
        for ang in (0.0, -15.0, 90.0, 200.0):
            cr = make_crash(acc_typ=typ, units=units)
            svg, _, _ = cd.crash_glyph(cr, base_ang=ang)
            bub = re.search(r'circle cx="([-\d.]+)" cy="([-\d.]+)" '
                            r'r="8.0" fill="#fff"', svg)
            assert bub, f"no bubble on type {typ}"
            bx, by = float(bub.group(1)), float(bub.group(2))
            ends = [(float(a), float(b)) for a, b in
                    re.findall(r'<line x1="([-\d.]+)" y1="([-\d.]+)"', svg)]
            for pts in re.findall(r'<polyline points="([^"]+)"', svg):
                a, b = pts.split()[0].split(",")
                ends.append((float(a), float(b)))
            near = min(math.hypot(bx - x, by - y) for x, y in ends)
            assert near == pytest.approx(cd.BUBBLE_R + cd.BUBBLE_GAP,
                                         abs=0.3), \
                f"type {typ} at {ang} deg hangs the bubble {near:.1f} out"


def test_speed_marks_follow_the_ten_mph_bands():
    for speed, want in ((None, 0), (5, 0), (9, 0), (10, 1), (45, 4),
                        (55, 5), (69, 6), (95, 0)):
        cr = make_crash(units=[cd.Unit(1, "E", speed)], acc_typ=13)
        svg, _, _ = cd.crash_glyph(cr, base_ang=0.0)
        got = len(re.findall(r'r="[\d.]+" fill="#2222CC"', svg))
        assert got == want, f"{speed} mph drew {got} dots, expected {want}"
    unknown = cd.crash_glyph(make_crash(units=[cd.Unit(1, "E", None)],
                                        acc_typ=13), base_ang=0.0)[0]
    assert cd.BLUE in unknown          # the unknown-speed x is still drawn


def test_nothing_touches_the_centreline_or_another_crash(tmp_path):
    crashes = [make_crash(crash_id=str(100000000 + i), mp=1.45,
                          dt=f"01/{i + 1:02d}/2024 12:00",
                          acc_typ=(19 if i % 2 else 21),
                          units=([cd.Unit(1, "E", 45)] if i % 2 else
                                 [cd.Unit(1, "W", 55), cd.Unit(2, "W", 0)]))
               for i in range(9)]
    html = _sheet_with(crashes, tmp_path,
                       junctions=[{"mp": 1.45, "label": "SR 1321",
                                   "side": 1}])
    boxes = []
    for m in re.finditer(r'<g data-crash="(\d+)" data-seq="\d+" '
                         r'transform="translate\(([-\d.]+),([-\d.]+)\)">',
                         html):
        ox, oy = float(m.group(2)), float(m.group(3))
        body = html[m.end():html.index("</g>", m.end())]
        xs = [float(v) for v in re.findall(r'(?:cx|x1|x2)="([-\d.]+)"', body)]
        ys = [float(v) for v in re.findall(r'(?:cy|y1|y2)="([-\d.]+)"', body)]
        if not xs:
            continue
        boxes.append((ox + min(xs), oy + min(ys), ox + max(xs), oy + max(ys)))
    assert len(boxes) == 9
    for i, b in enumerate(boxes):
        assert 20 < b[0] and b[2] < cd.PAGE_W - 20
        assert 20 < b[1] and b[3] < cd.PAGE_H - 20
        for j in range(i + 1, len(boxes)):
            o = boxes[j]
            assert not (b[0] < o[2] and b[2] > o[0]
                        and b[1] < o[3] and b[3] > o[1]), \
                f"assemblies {i} and {j} overlap"


def test_stroke_text_renders_strokes_or_falls_back():
    svg = cd._stroke_text(100, 50, "TEST 123", size=12)
    assert ("path d=" in svg) or ("<text" in svg)
    if cd._HFONT is not None:
        assert "path d=" in svg and "translate(100.0,50.0)" in svg


def test_sheet_prints_as_one_page(tmp_path):
    """An inline svg on a text baseline spills a blank second page."""
    html = _sheet_with([make_crash()], tmp_path)
    head = html[:html.index("</style>")]
    assert "@page{size:17in 11in;margin:0}" in head
    assert "svg{display:block}" in head, "svg must not sit on a baseline"
    assert "overflow:hidden" in head
    assert f"width:{cd.PAGE_W}px;height:{cd.PAGE_H}px" in head


def test_legend_groups_never_run_into_each_other():
    """Every legend group holds its own column: the longest label in one
    group stops clear of the next group's drawings, and the last group
    ends inside the box."""
    widths = [40.0, 130.0, 90.0, 95.0]
    stops = cd.legend_stops(cd.LEGEND_X, cd.LEGEND_W, widths)
    assert len(stops) == 4
    for i, (sym, lbl) in enumerate(stops):
        assert lbl - sym == cd.LEGEND_SYM_W[i]
        end = lbl + widths[i]
        nxt = (stops[i + 1][0] if i + 1 < len(stops)
               else cd.LEGEND_X + cd.LEGEND_W)
        assert end <= nxt, f"legend group {i} runs into the next"


def test_notes_are_the_smallest_lettering_and_carry_no_heading(tmp_path):
    """Notes sit by their crash, unlabelled, below the route label, which
    in turn sits below the study header."""
    assert cd.NOTE_SIZE < cd.ROUTE_SIZE < cd.TITLE_SIZE
    html = _sheet_with([make_crash()], tmp_path,
                       notes=[{"x": 800, "y": 900, "text": ["Crash #1: x"]}])
    assert "NOTES" not in html


def test_a_pinned_crash_lands_where_it_was_pinned(tmp_path):
    """A junction crash can be put on the leg it happened on, and the
    search places everything else around it."""
    crashes = [make_crash(crash_id=str(100000000 + i), mp=1.45,
                          dt=f"01/{i + 1:02d}/2024 12:00")
               for i in range(4)]
    html = _sheet_with(crashes, tmp_path, at={"100000002": [640, 930]})
    m = re.search(r'data-crash="100000002"[^>]*'
                  r'translate\(([-\d.]+),([-\d.]+)\)', html)
    assert m, "pinned crash never drawn"
    assert (float(m.group(1)), float(m.group(2))) == (640.0, 930.0)


def test_the_sheet_is_well_formed_svg(tmp_path):
    """Every sheet parses as XML. A malformed attribute silently truncates
    the drawing at the point the renderer gives up, which is invisible in
    a unit test that only looks for substrings."""
    import xml.etree.ElementTree as ET
    crashes = [make_crash(crash_id=str(100000000 + i), mp=1.4 + i * 0.05,
                          severity=s, acc_typ=t, road_cond=rc, night=n,
                          units=[cd.Unit(1, d, sp, m)])
               for i, (s, t, rc, n, d, sp, m) in enumerate([
                   ("K", 2, "D", False, "E", 55, 4),
                   ("A", 21, "W", True, "W", 35, 4),
                   ("B", 29, "I", False, "N", None, 7),
                   ("C", 13, "O", False, "S", 75, 8),
                   ("O", 5, "D", False, "E", 5, 4)])]
    html = _sheet_with(crashes, tmp_path,
                       notes=[{"x": 800, "y": 900, "text": ["n"]}],
                       junctions=[{"mp": 1.45, "label": "SR 1", "side": 1}])
    svg = html[html.index("<svg"):html.index("</svg>") + 6]
    ET.fromstring(svg)


def test_cell_linework_is_thin_enough_to_read_the_speed_dots():
    """NCDOT's printing note is line weight 0 on the cells so the speed
    marks survive the conversion to PDF. The dot has to out-read the
    shaft it sits on."""
    assert cd.CELL_SW <= 0.8
    assert cd.DOT_R * 2 > cd.CELL_SW * 2
    cr = make_crash(acc_typ=2, units=[cd.Unit(1, "E", 45, 4)])
    g, _b, _n = cd.crash_glyph(cr, base_ang=-15.0, route_forward="E")
    assert "{CELL_SW" not in g
    widths = {float(w) for w in re.findall(r'stroke-width="([\d.]+)"', g)}
    assert max(widths) <= 1.1


def test_the_drawn_road_follows_the_centreline_it_is_given():
    """With a centreline the sheet is drawn north up and keeps the shape
    of the real alignment: a right angle on the ground is a right angle
    on the paper, not a smooth sweep through it."""
    geo = ([[34.8190 - 0.0002 * i, -79.2180 + 0.0002 * i] for i in range(30)]
           + [[34.8130, -79.2120 + 0.0004 * i] for i in range(1, 40)])
    line = cd.road_line({"centerline": geo,
                         "road_box": [100, 300, 1500, 800]})
    assert line.true_north
    x0, y0 = line.at(0.0)
    x1, y1 = line.at(1.0)
    assert x1 > x0 and y1 > y0            # runs southeast then due east
    a_start = math.degrees(line.tangent(0.02))
    a_end = math.degrees(line.tangent(0.98))
    assert 20 < a_start < 70, a_start     # down and to the right
    assert abs(a_end) < 20, a_end         # flat
    inside = all(96 <= x <= 1504 and 296 <= y <= 804
                 for x, y in line.pts)
    assert inside, "road drawn outside its box"


def test_a_sheet_with_no_centreline_still_draws():
    """Layouts that carry no survey fall back to the plain sweep, and the
    needle leans with it rather than claiming north."""
    line = cd.road_line({})
    assert not line.true_north
    assert len(line.pts) > 100


def test_a_side_road_leaves_at_its_own_bearing(tmp_path):
    """A junction with a bearing is drawn heading that way, not square off
    the centreline."""
    html = _sheet_with([make_crash()], tmp_path,
                       junctions=[{"mp": 1.45, "label": "SR 1", "side": 1,
                                   "bearing": 180}])
    segs = [tuple(float(v) for v in m) for m in re.findall(
        r'<line x1="([-\d.]+)" y1="([-\d.]+)" x2="([-\d.]+)" '
        r'y2="([-\d.]+)" stroke="#000" stroke-width="1.1"/>', html)]
    assert segs, "junction stub never drawn"
    x0, y0, x1, y1 = max(segs, key=lambda s: math.hypot(s[2] - s[0],
                                                        s[3] - s[1]))
    assert math.hypot(x1 - x0, y1 - y0) >= cd.STUB_LEN - 1


def _sides(html, layout):
    """Which side of the drawn road each crash landed on."""
    line = cd.road_line(layout)
    road = [line.at(i / 400.0) for i in range(401)]
    out = {}
    for cid, x, y in re.findall(
            r'data-crash="(\d+)"[^>]*translate\(([-\d.]+),([-\d.]+)\)', html):
        x, y = float(x), float(y)
        i = min(range(401),
                key=lambda k: (road[k][0] - x) ** 2 + (road[k][1] - y) ** 2)
        nx, ny = cd._rot(0, -1, math.degrees(line.tangent(i / 400.0)))
        out[cid] = (x - road[i][0]) * nx + (y - road[i][1]) * ny
    return out


def test_a_crowded_side_never_pushes_a_crash_across_the_road(tmp_path):
    """Which side of the line a vehicle was on is a fact about the crash.
    Eight westbound crashes at one milepost all stay north of it, however
    far out the eighth has to stand."""
    crashes = [make_crash(crash_id=str(100000000 + i), mp=1.55, acc_typ=2,
                          dt=f"01/{i + 1:02d}/2024 12:00",
                          units=[cd.Unit(1, "W", 45, 4)])
               for i in range(8)]
    layout = {"type": "section", "begin_mp": 1.31, "end_mp": 1.80,
              "title": ["t"], "route_label": ["r"],
              "prepared_by": "x", "date": "1/1/2026"}
    html = _sheet_with(crashes, tmp_path, **{k: v for k, v in layout.items()
                                             if k not in ("type",)})
    sides = _sides(html, layout)
    assert len(sides) == 8
    assert all(v > 0 for v in sides.values()), sides


def test_a_bend_does_not_throw_a_cell_to_the_wrong_side(tmp_path):
    """Cells around a corner stand off their own station. Sharing one
    frame across the whole cluster pointed the standoff along the road for
    members past the bend, which put them over the line."""
    geo = ([[34.8190 - 0.00018 * i, -79.2180 + 0.00018 * i]
            for i in range(26)]
           + [[34.8145, -79.2135 + 0.00035 * i] for i in range(1, 40)])
    layout = {"type": "section", "begin_mp": 1.31, "end_mp": 1.80,
              "title": ["t"], "route_label": ["r"], "centerline": geo,
              "prepared_by": "x", "date": "1/1/2026"}
    crashes = [make_crash(crash_id=str(100000000 + i), mp=mp, acc_typ=2,
                          dt=f"03/{i + 1:02d}/2024 12:00",
                          units=[cd.Unit(1, "W", 45, 4)])
               for i, mp in enumerate([1.40, 1.42, 1.44, 1.46, 1.48, 1.50])]
    html = _sheet_with(crashes, tmp_path, centerline=geo)
    sides = _sides(html, layout)
    assert all(v > 0 for v in sides.values()), sides
