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
