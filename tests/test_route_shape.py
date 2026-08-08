"""Loading NCDOT LRS route geometry (docs/11).

Route centrelines carrying milepost measures are the one input the coordinate
path has never had. Measured on 47 real reports, ``resolve`` produced zero
independent mileposts, and this is why: ``inventory.shape`` was empty, so
``interpolate_milepost`` had nothing to project onto. These pin the loader so
the data drops straight in when it arrives.
"""
import io
import json

import pytest

from safety_eval.location import FeatureInventory, interpolate_milepost


def _gj(features):
    return io.StringIO(json.dumps({"type": "FeatureCollection",
                                   "features": features}))


def test_measure_on_the_vertex_is_used_directly():
    """[lon, lat, m]: the LRS measure rides on the vertex. The useful case."""
    inv = FeatureInventory()
    added = inv.load_route_shape(_gj([{
        "properties": {"RouteID": "SR 1003"},
        "geometry": {"type": "LineString", "coordinates": [
            [-78.30, 35.60, 17.691], [-78.29, 35.60, 17.811]]}}]))
    assert added == {"SR1003": 2}
    assert inv.shape["SR1003"][0] == (17.691, 35.60, -78.30)


def test_a_z_coordinate_does_not_displace_the_measure():
    """[lon, lat, z, m]: ArcGIS exports both, and m is always last."""
    inv = FeatureInventory()
    inv.load_route_shape(_gj([{
        "properties": {"RouteID": "SR 1003"},
        "geometry": {"type": "LineString", "coordinates": [
            [-78.30, 35.60, 250.0, 17.691]]}}]))
    assert inv.shape["SR1003"] == [(17.691, 35.60, -78.30)]


def test_begin_end_mp_is_spread_when_vertices_carry_no_measure():
    inv = FeatureInventory()
    inv.load_route_shape(_gj([{
        "properties": {"RouteID": "SR 1003", "BeginMP": 15.0, "EndMP": 16.0},
        "geometry": {"type": "LineString", "coordinates": [
            [-78.40, 35.6], [-78.39, 35.6], [-78.38, 35.6]]}}]))
    assert [p[0] for p in inv.shape["SR1003"]] == [15.0, 15.5, 16.0]


def test_multilinestring_parts_are_merged_and_sorted():
    inv = FeatureInventory()
    inv.load_route_shape(_gj([{
        "properties": {"RouteID": "SR 1003"},
        "geometry": {"type": "MultiLineString", "coordinates": [
            [[-78.28, 35.60, 17.931]], [[-78.30, 35.60, 17.691]]]}}]))
    assert [p[0] for p in inv.shape["SR1003"]] == [17.691, 17.931]


def test_features_without_a_route_name_are_skipped():
    inv = FeatureInventory()
    assert inv.load_route_shape(_gj([{
        "properties": {}, "geometry": {"type": "LineString",
                                       "coordinates": [[-78.3, 35.6, 1.0]]}}])) == {}
    assert inv.shape == {}


def test_the_route_override_wins_for_a_single_route_export():
    inv = FeatureInventory()
    inv.load_route_shape(_gj([{
        "properties": {"RouteID": "whatever"},
        "geometry": {"type": "LineString",
                     "coordinates": [[-78.3, 35.6, 1.0]]}}]), route="SR 1003")
    assert set(inv.shape) == {"SR1003"}


def test_loaded_geometry_resolves_a_coordinate_to_a_milepost():
    """End to end: this is the step that returned None on all 47 reports.

    The 0.12 mi that separates the SR 1716 intersection (17.691) from
    SR 2637/2638 (17.811) is 634 ft, which is the scale of the correction the
    engineer actually made, so the geometry has to place a point well inside it.
    """
    inv = FeatureInventory()
    inv.load_route_shape(_gj([{
        "properties": {"RouteID": "SR 1003"},
        "geometry": {"type": "LineString", "coordinates": [
            [-78.3000, 35.6000, 17.691], [-78.2958, 35.6000, 17.811]]}}]))
    mp, offset = interpolate_milepost(inv.shape["SR1003"], 35.6000, -78.2979)
    assert mp == pytest.approx(17.751, abs=0.005)
    assert offset * 5280 < 5


# ---------------------------------------------------------------------------
# NCDOT_StateMaintainedRoadsQtr (the real schema, confirmed 2026-08)
# ---------------------------------------------------------------------------

def test_route_id_decodes_to_route_and_ncdot_county_number():
    """RouteID is the docs/09 road code plus NCDOT's county number.

    The county part is NCDOT's alphabetical numbering, not FIPS. Verified on
    two real records: 093 is Warren (the NC-58 record plots at 36.21 N; FIPS
    093 is Hoke, 200 miles southwest) and 083 is Scotland (US-74 BUS at
    Laurinburg). Johnston, which the SR 1003 evaluation runs in, is 51.
    """
    from safety_eval.location import decode_route_id
    assert decode_route_id("40001003051") == ("SR 1003", 51)
    assert decode_route_id("30000058093") == ("NC 58", 93)
    assert decode_route_id("29000074083") == ("US 74BUS", 83)   # qualifier 9
    assert decode_route_id("40001003") == ("SR 1003", None)     # 8-digit form


def test_route_id_declines_what_it_cannot_decode():
    from safety_eval.location import decode_route_id
    assert decode_route_id("50099562093") == ("", None)   # class 5, local street
    assert decode_route_id(None) == ("", None)
    assert decode_route_id("SR 1003") == ("", None)


def test_begin_end_mp_is_spread_by_distance_not_vertex_count():
    """NCDOT crowds vertices onto curves; counting them stretches mileposts.

    Real geometry from RouteID 30000058093, first four vertices and the last
    two: the opening hops are tens of feet and the closing ones are hundreds.
    Spreading by index would hand all six the same 371 ft.
    """
    inv = FeatureInventory()
    inv.load_route_shape(_gj([{
        "properties": {"RouteID": "30000058093", "RouteName": "NC-58",
                       "BeginMp1": 0, "EndMp1": 0.351111},
        "geometry": {"type": "LineString", "coordinates": [
            [-78.103073, 36.209055], [-78.102932, 36.209241],
            [-78.102898, 36.209291], [-78.102870, 36.209334],
            [-78.100555, 36.211882], [-78.099052, 36.212555]]}}]))
    pts = inv.shape["NC58"]
    mps = [p[0] for p in pts]
    assert mps[0] == 0 and mps[-1] == pytest.approx(0.351111)
    assert mps == sorted(mps)
    # the defining property: milepost advances in proportion to distance, so
    # every segment shares one scale factor. Vertex-index spreading would give
    # each of the six an identical 0.0702 mi regardless of how far apart it is.
    from safety_eval.location import haversine_mi
    scales = [(mps[i + 1] - mps[i])
              / haversine_mi(pts[i][1], pts[i][2], pts[i + 1][1], pts[i + 1][2])
              for i in range(len(pts) - 1)]
    assert max(scales) == pytest.approx(min(scales), rel=1e-6)
    hops = [mps[i + 1] - mps[i] for i in range(len(mps) - 1)]
    assert max(hops) > 5 * min(hops)          # they are genuinely uneven


def test_route_name_is_preferred_over_the_route_id():
    inv = FeatureInventory()
    inv.load_route_shape(_gj([{
        "properties": {"RouteID": "30000058093", "RouteName": "NC-58",
                       "BeginMp1": 0, "EndMp1": 1.0},
        "geometry": {"type": "LineString",
                     "coordinates": [[-78.10, 36.20], [-78.09, 36.20]]}}]))
    assert set(inv.shape) == {"NC58"}


def test_route_id_is_used_when_no_route_name_is_present():
    inv = FeatureInventory()
    inv.load_route_shape(_gj([{
        "properties": {"RouteID": "40001003051", "BeginMp1": 15.0, "EndMp1": 15.5},
        "geometry": {"type": "LineString",
                     "coordinates": [[-78.30, 35.60], [-78.29, 35.60]]}}]))
    assert set(inv.shape) == {"SR1003"}


# --------------------------------------------------------------------------- #
# the resolver does the work instead of punting (engineer, 2026-08)
# --------------------------------------------------------------------------- #
_MARKER_REPORT = """POLK 20000074 0.0            18.381
10.645    163.0   Mile Marker                                             0.970    North and East
12.662    165.0   Mile Marker                                             0.063    North and East
13.715    166.0   Mile Marker                                             0.740    North and East
14.455 30000009 NC 9 At grade intersection, 4 legs 0.000 South and East
"""


def test_mile_markers_land_in_the_inventory_under_every_alias():
    """Marker rows carry the MARKER NUMBER where road rows carry a route id,
    so the road regex dropped all 33 of them on the US 74 report and every
    'MILE 165 to MILE 166' location came back unresolved."""
    inv = FeatureInventory.from_features_report(_MARKER_REPORT, route="US 74")
    for name in ("*MILE 165", "MILE MARKER 165", "MM 165"):
        assert inv.mileposts_of("US 74", name) == [12.662], name
    assert inv.mileposts_of("US 74", "MILE MARKER 166") == [13.715]
    assert inv.mileposts_of("US 74", "NC 9") == [14.455]   # roads still parse


def test_clean_shape_buckets_medians_and_drops_the_miscoded_point():
    """A miscoded milepost is the very thing an RE fixes; it must not bend
    the shape used to fix it, and it must not survive by sorting to the
    end of the line either."""
    from safety_eval.location import clean_shape
    pts = [(13.00 + i * 0.01, 35.270 + i * 0.001, -82.130) for i in range(10)]
    pts.append((13.051, 35.2751, -82.130))    # honest second report at the mp
    pts.append((13.05, 35.9, -82.9))          # wild geocode at the same mp
    # the RE case: the crash sits back at ~MP 13.045 but was coded 13.42,
    # which sorts it to the END of the corridor where a neighbour-only
    # check never looks.
    pts.append((13.42, 35.2745, -82.130))
    shape = clean_shape(pts)
    mps = [p[0] for p in shape]
    assert 13.42 not in mps                   # endpoint outlier dropped
    lat_at_1305 = next(p[1] for p in shape if p[0] == 13.05)
    assert abs(lat_at_1305 - 35.275) < 0.002  # median beat the wild geocode


def test_resolve_falls_back_to_detailedfiche_coordinates():
    """'Needs mp lookup against coords' is the resolver's own work: with the
    corridor shape from the study's coded crashes, coordinates become a
    milepost and the note names the source."""
    from safety_eval.location import ReportLocation, clean_shape, resolve
    inv = FeatureInventory()
    inv.shape["US74"] = clean_shape(
        [(13.0 + i * 0.02, 35.270 + i * 0.002, -82.130) for i in range(20)])
    loc = ReportLocation(on_road="US 74")
    got = resolve(loc, inv, fallback_coordinates=(35.2789, -82.1300))
    assert got.milepost == pytest.approx(13.09, abs=0.02)
    assert got.method == "coordinates"
    assert any("DetailedFiche" in n and "starting point" in n
               for n in got.notes)
    # and without the fallback it still refuses to guess
    bare = resolve(loc, inv)
    assert bare.milepost is None


def test_the_report_location_outranks_the_coded_coordinate():
    """On 41000079305 crash 107660451 the DetailedFiche coordinate maps to
    MP 13.01 while the report's stated location gives the engineer's 13.44:
    the coordinate geocodes the CODED location, the very thing the review
    corrects, so it must never outrank the report - and when the two
    disagree, that disagreement is reported as the RE evidence it is."""
    from safety_eval.location import ReportLocation, clean_shape, resolve
    inv = FeatureInventory.from_features_report(_MARKER_REPORT, route="US 74")
    inv.shape["US74"] = clean_shape(
        [(13.0 + i * 0.02, 35.270 + i * 0.002, -82.130) for i in range(20)])
    loc = ReportLocation(on_road="US 74", from_road="MILE MARKER 165",
                         toward_road="MILE MARKER 166",
                         dist_from_intersection=0.78)
    coded = (35.2709, -82.1300)               # maps to ~MP 13.005
    got = resolve(loc, inv, fallback_coordinates=coded)
    assert got.milepost == pytest.approx(12.662 + 0.78, abs=0.01)
    assert got.method == "features"
    assert any("coded location is what the review corrects" in n
               for n in got.notes)
