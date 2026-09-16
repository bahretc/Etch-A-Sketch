"""Route geometry: mileposts, curves and grades from synthetic lines.

No network: the centerline is built from a hand-made segment collection
and the elevation profile from a function.
"""
import math

import pytest

from safety_eval import route_geometry as rg

LAT0, LON0 = 36.2200, -80.1700
FT_PER_DEG_LAT = 364000.0


def _ll(x_ft: float, y_ft: float):
    """Local east/north feet -> (lon, lat) GeoJSON order."""
    lon = LON0 + x_ft / (FT_PER_DEG_LAT * math.cos(math.radians(LAT0)))
    lat = LAT0 + y_ft / FT_PER_DEG_LAT
    return [lon, lat]


def _segments(coords_by_segment):
    """Two consecutive traffic segments, milepost 10.0 to 11.0 and 11.0 to
    12.0, each one mile of line."""
    feats = []
    for i, coords in enumerate(coords_by_segment):
        feats.append({"type": "Feature",
                      "properties": {"RouteID": "20000311034",
                                     "BeginMP": 10.0 + i, "EndMP": 11.0 + i},
                      "geometry": {"type": "LineString",
                                   "coordinates": coords}})
    return {"type": "FeatureCollection", "features": feats}


@pytest.fixture
def straight():
    """A due-north line, two segments of exactly one mile each."""
    seg1 = [_ll(0, y) for y in range(0, 5281, 528)]
    seg2 = [_ll(0, y) for y in range(5280, 10561, 528)]
    return rg.centerline_from_segments(_segments([seg1, seg2]),
                                       route_id="20000311034")


def test_route_id_pads_the_county_code():
    assert rg.route_id("20000311", 34) == "20000311034"
    assert rg.route_id(40001940, "34") == "40001940034"


def test_mileposts_run_along_the_chained_segments(straight):
    assert straight.mp_min == 10.0 and straight.mp_max == 12.0
    lat, lon = straight.mp_to_ll(10.5)
    assert abs(lat - (LAT0 + 2640 / FT_PER_DEG_LAT)) < 1e-6
    lat, _ = straight.mp_to_ll(11.25)
    assert abs(lat - (LAT0 + 6600 / FT_PER_DEG_LAT)) < 1e-6


def test_snap_gives_the_milepost_and_the_offset(straight):
    lat, lon = straight.mp_to_ll(10.75)
    off_lon = lon + 100 / (FT_PER_DEG_LAT * math.cos(math.radians(LAT0)))
    mp, off = straight.snap(lat, off_lon)
    assert mp == pytest.approx(10.75, abs=0.001)
    assert 98 <= off <= 102


def test_polyline_lands_exactly_on_the_limits(straight):
    pts = straight.polyline(10.2, 10.8)
    assert pts[0] == list(straight.mp_to_ll(10.2))
    assert pts[-1] == list(straight.mp_to_ll(10.8))
    assert all(10.2 <= straight.snap(*p)[0] <= 10.8 for p in pts)


def test_a_straight_line_has_no_curves(straight):
    assert rg.horizontal_curves(straight, 10.1, 11.9) == []


def test_a_circular_arc_is_found_with_its_radius():
    """A tangent, then a 1000 ft radius arc turning 45 degrees left, then a
    tangent: one curve, radius within 10 percent, PC/PT within 60 ft."""
    R = 1000.0
    pts = [(0.0, y) for y in range(0, 2001, 50)]          # tangent north
    for k in range(1, 46):                                # arc to the left
        a = math.radians(k)
        pts.append((-R * (1 - math.cos(a)), 2000 + R * math.sin(a)))
    ex, ey = pts[-1]
    for d in range(50, 2001, 50):                          # tangent NW
        pts.append((ex - d * math.sin(math.radians(45)),
                    ey + d * math.cos(math.radians(45))))
    length_mi = 0.0
    coords = []
    for i, (x, y) in enumerate(pts):
        if i:
            length_mi += math.hypot(x - pts[i - 1][0], y - pts[i - 1][1]) / 5280
        coords.append(_ll(x, y))
    coll = {"type": "FeatureCollection", "features": [{
        "type": "Feature",
        "properties": {"RouteID": "x", "BeginMP": 0.0, "EndMP": length_mi},
        "geometry": {"type": "LineString", "coordinates": coords}}]}
    cl = rg.centerline_from_segments(coll)
    curves = rg.horizontal_curves(cl, 0.0, length_mi)
    assert len(curves) == 1
    c = curves[0]
    assert abs(c.radius_ft - R) / R < 0.10
    assert c.direction == "LT"
    assert abs(c.pc - 2000 / 5280) < 60 / 5280
    assert abs(c.pt - (2000 + R * math.radians(45)) / 5280) < 60 / 5280
    assert 40 <= c.delta_deg <= 50


def test_profile_crests_and_sags_with_grades(straight):
    """A hill: rises 2 percent for 0.25 mi, falls 3 percent for 0.25 mi."""
    def elev(lat, lon):
        mp = straight.snap(lat, lon)[0]
        d = (mp - 10.0) * 5280
        return 800 + (0.02 * d if d <= 1320 else 0.02 * 1320 - 0.03 * (d - 1320))
    prof = rg.elevation_profile(straight, 10.0, 10.5, fetch=elev)
    assert len(prof) == 51 and all(p[3] is not None for p in prof)
    feats = rg.vertical_features(prof, min_prominence_ft=6)
    crests = [f for f in feats if f.kind == "CREST"]
    assert len(crests) == 1
    c = crests[0]
    assert abs(c.mp - 10.25) <= 0.02
    assert c.grade_in_pct == pytest.approx(2.0, abs=0.6)
    assert c.grade_out_pct == pytest.approx(-3.0, abs=0.6)
    # looking over the crest from 0.1 mi before it, the view is cut short
    assert rg.sight_distance(prof, 10.15, +1) < 1500
    # and looking back down the tangent it is not
    assert rg.sight_distance(prof, 10.15, -1) >= 700


def test_feature_pairs_and_text_limit():
    curves = [rg.Curve(10.5, 10.55, 10.6, 1200, 20, "LT", 528)]
    verts = [rg.VerticalFeature("CREST", 10.7, 850, 12, 2.0, -1.5),
             rg.VerticalFeature("SAG", 10.9, 830, 8, -1.5, 1.0)]
    rows = rg.feature_pairs(curves, verts, 10.52, 10.95)
    assert rows == [("CURVE 1 PI", 10.55), ("CURVE 1 PT", 10.6),
                    ("CREST 1", 10.7), ("SAG 1", 10.9)]
    assert all(len(t) <= 20 for t, _ in rows)
    assert "Curve 1" in rg.features_markdown(curves, verts)
