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
