"""Location resolution: derive the milepost, never infer it.

The regression that motivated this module: a drafting layer read the DMV-349
"04.20 Miles outside municipality" field as milepost 4.20 and reported high
confidence. Nothing on the form is a milepost; these tests pin that.
"""
import pytest

from safety_eval.location import (FeatureInventory, ReportLocation,
                                  interpolate_milepost, normalize_route,
                                  resolve)


def _inv():
    """US 13 with two intersections, mileposts increasing northbound."""
    inv = FeatureInventory()
    inv.features["US13"] = {"SR1132": 3.40, "SR1142": 5.10}
    return inv


def test_municipality_distance_is_never_a_milepost():
    loc = ReportLocation(on_road="US 13", municipality="Snow Hill",
                         in_municipality=False,
                         dist_from_municipality=4.20,
                         dir_from_municipality="N")
    res = resolve(loc, _inv())
    assert res.milepost is None
    assert res.method == "municipality"
    assert any("not a milepost" in n for n in res.notes)


def test_milepost_from_distance_to_an_intersecting_route():
    loc = ReportLocation(on_road="US 13", from_road="SR 1132",
                         toward_road="SR 1142", dist_from_intersection=0.80)
    res = resolve(loc, _inv())
    assert res.milepost == pytest.approx(4.20)      # 3.40 + 0.80 northbound
    assert res.method == "features" and res.confidence == "high"


def test_direction_comes_from_the_named_roads_not_a_convention():
    """Same distance, roads reversed: the milepost must go the other way."""
    inv = _inv()
    loc = ReportLocation(on_road="US 13", from_road="SR 1142",
                         toward_road="SR 1132", dist_from_intersection=0.80)
    res = resolve(loc, inv)
    assert res.milepost == pytest.approx(4.30)      # 5.10 - 0.80
    assert res.confidence == "high"


def test_distance_overshooting_the_named_road_is_flagged():
    loc = ReportLocation(on_road="US 13", from_road="SR 1132",
                         toward_road="SR 1142", dist_from_intersection=2.50)
    res = resolve(loc, _inv())
    assert res.confidence == "low"
    assert any("overshoots" in n for n in res.notes)


def test_at_intersection_marker_uses_the_feature_milepost():
    loc = ReportLocation(on_road="US 13", from_road="SR 1132",
                         at_intersection=True, dist_from_intersection=0.0)
    res = resolve(loc, _inv())
    assert res.milepost == pytest.approx(3.40) and res.confidence == "high"


def test_unknown_feature_leaves_the_milepost_unresolved():
    loc = ReportLocation(on_road="US 13", from_road="SR 9999",
                         toward_road="SR 1142", dist_from_intersection=0.80)
    res = resolve(loc, _inv())
    assert res.milepost is None
    assert any("not in the features report" in n for n in res.notes)


def test_no_inventory_at_all_resolves_nothing():
    """Without a features report the honest answer is 'unresolved'."""
    loc = ReportLocation(on_road="US 13", from_road="SR 1132",
                         toward_road="SR 1142", dist_from_intersection=0.80)
    res = resolve(loc, None)
    assert res.milepost is None and res.confidence == "low"


def test_coordinates_interpolate_a_milepost():
    inv = _inv()
    inv.shape["US13"] = [(3.40, 35.40, -77.60), (5.10, 35.42, -77.60)]
    lat = 35.40 + (35.42 - 35.40) * (0.80 / 1.70)
    loc = ReportLocation(on_road="US 13", latitude=lat, longitude=-77.60)
    res = resolve(loc, inv)
    assert res.method == "coordinates"
    assert res.milepost == pytest.approx(4.20, abs=0.02)
    assert res.confidence == "high"


def test_coordinates_far_off_the_route_lower_confidence():
    inv = _inv()
    inv.shape["US13"] = [(3.40, 35.40, -77.60), (5.10, 35.42, -77.60)]
    loc = ReportLocation(on_road="US 13", latitude=35.41, longitude=-77.70)
    res = resolve(loc, inv)
    assert res.confidence == "low" and res.milepost is None
    assert any("off" in n for n in res.notes)


def test_address_is_carried_through_without_a_milepost():
    loc = ReportLocation(on_road="", street="MOUNT CARMEL CHURCH RD")
    res = resolve(loc, _inv())
    assert res.method == "address" and res.milepost is None
    assert any("geocoder" in n for n in res.notes)


def test_disagreement_with_the_fiche_is_reported_as_the_RE_case():
    loc = ReportLocation(on_road="US 13", from_road="SR 1132",
                         toward_road="SR 1142", dist_from_intersection=0.80)
    res = resolve(loc, _inv(), fiche_milepost=8.10)
    assert res.agrees_with_fiche is False
    assert any("RE case" in n for n in res.notes)
    assert "DISAGREES" in res.summary()


def test_agreement_with_the_fiche_is_reported():
    loc = ReportLocation(on_road="US 13", from_road="SR 1132",
                         toward_road="SR 1142", dist_from_intersection=0.80)
    res = resolve(loc, _inv(), fiche_milepost=4.22)
    assert res.agrees_with_fiche is True


def test_route_names_normalize_across_sources():
    assert normalize_route("SR 1132") == normalize_route("sr-1132") == "SR1132"
    assert normalize_route("SR 1007 (Plank Road)") == "SR1007"


def test_interpolate_handles_a_single_point():
    mp, off = interpolate_milepost([(2.0, 35.4, -77.6)], 35.4, -77.6)
    assert mp == 2.0 and off == pytest.approx(0.0, abs=1e-6)
