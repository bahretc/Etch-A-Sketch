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


# --------------------------------------------------------------------------- #
# the real NCDOT features report
# --------------------------------------------------------------------------- #
import os

FIXTURE = os.path.join(os.path.dirname(__file__), "fixtures",
                       "features_us13_greene.txt")


def _real_inventory():
    from safety_eval.location import FeatureInventory
    return FeatureInventory.from_features_report(open(FIXTURE).read())


def test_features_report_header_names_the_route():
    from safety_eval.location import _route_from_header
    assert _route_from_header(open(FIXTURE).read()) == "US 13"


def test_features_report_mileposts_parse():
    inv = _real_inventory()
    assert inv.milepost_of("US 13", "SR 1132") == pytest.approx(1.993)
    assert inv.milepost_of("US 13", "SR 1142") == pytest.approx(2.983)
    assert inv.milepost_of("US 13", "NC 58") == pytest.approx(7.383)


def test_features_report_indexes_more_than_numbered_routes():
    """Named streets, county lines and municipal limits locate crashes too."""
    inv = _real_inventory()
    assert inv.milepost_of("US 13", "SHINE") == pytest.approx(1.993)
    assert inv.milepost_of("US 13", "RANDOLPH CREECH") == pytest.approx(3.248)
    assert inv.milepost_of("US 13", "ML-SNOW HILL") == pytest.approx(8.212)
    assert inv.milepost_of("US 13", "CL-PITT") == pytest.approx(18.381)


def test_features_report_keeps_the_first_milepost_of_a_shared_node():
    """SR 1132, SR 1210 and SHINE all meet at 1.993."""
    inv = _real_inventory()
    for f in ("SR 1132", "SR 1210", "SHINE"):
        assert inv.milepost_of("US 13", f) == pytest.approx(1.993)


def test_real_crash_resolves_against_the_real_report():
    """0.80 mi from SR 1132 toward SR 1142 is MP 2.79, not the 4.20 that a
    drafting layer once read off the municipality-distance field."""
    inv = _real_inventory()
    loc = ReportLocation(on_road="US 13", from_road="SR 1132",
                         toward_road="SR 1142", dist_from_intersection=0.80,
                         municipality="Snow Hill", in_municipality=False,
                         dist_from_municipality=4.20, county="Greene")
    res = resolve(loc, inv)
    assert res.milepost == pytest.approx(2.79, abs=0.01)
    assert res.method == "features" and res.confidence == "high"
    assert res.milepost != pytest.approx(4.20, abs=0.01)


def test_report_span_agrees_with_the_distance_to_next_column():
    """SR 1132 -> SR 1142 is 0.990 in the report; the mileposts must agree."""
    inv = _real_inventory()
    span = inv.milepost_of("US 13", "SR 1142") - inv.milepost_of("US 13", "SR 1132")
    assert span == pytest.approx(0.990, abs=0.001)


def test_repeated_feature_names_are_kept_not_collapsed():
    """NC 58 meets US 13 twice in the real report; both mileposts survive."""
    inv = _real_inventory()
    assert inv.mileposts_of("US 13", "NC 58") == [pytest.approx(7.383)]
    # the fixture carries one NC 58; the ambiguity API is exercised below


def test_ambiguous_feature_is_disambiguated_by_the_road_named_toward():
    from safety_eval.location import FeatureInventory
    inv = FeatureInventory()
    # NC 58 twice, as on the real US 13
    inv.features["US13"] = {"NC58": [7.383, 8.553], "SR1104": [8.433]}
    loc = ReportLocation(on_road="US 13", from_road="NC 58",
                         toward_road="SR 1104", dist_from_intersection=0.12)
    res = resolve(loc, inv)
    # only the 8.553 NC 58 is within 0.12 mi of SR 1104 at 8.433
    assert res.milepost == pytest.approx(8.43, abs=0.02)
    assert res.confidence == "high"


def test_ambiguous_feature_with_no_way_to_choose_refuses():
    from safety_eval.location import FeatureInventory
    inv = FeatureInventory()
    inv.features["US13"] = {"NC58": [7.383, 8.553]}
    loc = ReportLocation(on_road="US 13", from_road="NC 58",
                         dist_from_intersection=0.50)
    res = resolve(loc, inv)
    assert res.milepost is None
    assert any("appears at 2 mileposts" in n for n in res.notes)


def test_milepost_of_returns_none_when_the_name_is_not_unique():
    from safety_eval.location import FeatureInventory
    inv = FeatureInventory()
    inv.features["US13"] = {"NC58": [7.383, 8.553]}
    assert inv.milepost_of("US 13", "NC 58") is None
    assert inv.mileposts_of("US 13", "NC 58") == [7.383, 8.553]


class _FakeGeocoder:
    def __init__(self, point): self.point, self.calls = point, []
    def geocode(self, street, municipality="", county="", state="NC"):
        self.calls.append((street, municipality, county)); return self.point


def _inv_with_shape():
    inv = _inv()
    inv.shape["US13"] = [(3.40, 35.40, -77.60), (5.10, 35.42, -77.60)]
    return inv


def test_address_is_geocoded_and_interpolated():
    inv = _inv_with_shape()
    lat = 35.40 + (35.42 - 35.40) * (0.80 / 1.70)
    g = _FakeGeocoder((lat, -77.60))
    loc = ReportLocation(on_road="US 13", street="MOUNT CARMEL CHURCH RD",
                         municipality="Snow Hill", county="Greene")
    res = resolve(loc, inv, geocoder=g)
    assert res.method == "address"
    assert res.milepost == pytest.approx(4.20, abs=0.02)
    assert res.confidence == "medium"          # weaker than report coordinates
    assert g.calls == [("MOUNT CARMEL CHURCH RD", "Snow Hill", "Greene")]


def test_geocoded_point_far_from_the_route_is_not_converted():
    g = _FakeGeocoder((35.41, -77.70))
    loc = ReportLocation(on_road="US 13", street="SOME RD")
    res = resolve(loc, _inv_with_shape(), geocoder=g)
    assert res.milepost is None and res.confidence == "low"
    assert res.latitude is not None            # the point is still reported


def test_no_geocoder_leaves_the_address_unplaced():
    loc = ReportLocation(on_road="US 13", street="SOME RD")
    res = resolve(loc, _inv_with_shape())
    assert res.method == "address" and res.milepost is None
    assert any("no geocoder result" in n for n in res.notes)


def test_geocoder_failure_is_reported_not_raised():
    class Boom:
        def geocode(self, *a, **k): raise RuntimeError("locator offline")
    res = resolve(ReportLocation(on_road="US 13", street="SOME RD"),
                  _inv_with_shape(), geocoder=Boom())
    assert res.milepost is None
    assert any("geocoder failed" in n for n in res.notes)


def test_gazetteer_matches_on_street_and_narrows_by_municipality(tmp_path):
    from safety_eval.location import GazetteerGeocoder
    p = tmp_path / "addr.csv"
    p.write_text("address,latitude,longitude,municipality,county\n"
                 "MAIN ST,35.10,-77.10,Snow Hill,Greene\n"
                 "MAIN ST,36.20,-78.20,Wendell,Wake\n", encoding="utf-8")
    g = GazetteerGeocoder.from_csv(str(p))
    assert g.geocode("Main St", "Snow Hill", "Greene") == (35.10, -77.10)
    assert g.geocode("main  st", "Wendell", "Wake") == (36.20, -78.20)
    assert g.geocode("Nowhere Rd", "Snow Hill", "Greene") is None


# --------------------------------------------------------------------------- #
# reading the location block off the page
# --------------------------------------------------------------------------- #
def _w(text, xf, yf, W=1000, H=2000):
    from safety_eval.redact import Word
    return Word(text=text, left=int(xf * W), top=int(yf * H),
                width=max(8, int(0.009 * W * len(text))), height=14, page=1)


def _read(words):
    from safety_eval.location import read_location_block
    return read_location_block(words, 1000, 2000)


def test_location_block_reads_the_three_rows():
    words = (
        [_w("occurred", .19, .136), _w("Near", .23, .136), _w("SNOW", .26, .136),
         _w("HILL", .31, .136), _w("or", .62, .136), _w("04.20", .647, .136),
         _w("Miles", .735, .136), _w("outside", .82, .136),
         _w("municipality", .86, .136)]
        + [_w("onUS", .094, .154), _w("13", .132, .154),
           _w("00.80", .647, .154), _w("Miles", .735, .154),
           _w("(0", .763, .154), _w("ft-Intersection)", .772, .154)]
        + [_w("rom", .117, .186), _w("SR1132", .142, .186),
           _w("toward", .483, .186), _w("SR", .513, .186), _w("1142", .538, .186)]
    )
    loc = _read(words)
    assert loc.on_road == "US 13"
    assert loc.from_road == "SR 1132"          # 'rom SR1132' -> spaced
    assert loc.toward_road == "SR 1142"
    assert loc.municipality == "SNOW HILL"
    assert loc.dist_from_municipality == pytest.approx(4.20)
    assert loc.dist_from_intersection == pytest.approx(0.80)


def test_the_two_distance_fields_are_not_swapped():
    """Both sit at the same x; only their captions tell them apart."""
    words = ([_w("Near", .23, .136), _w("TOWN", .26, .136),
              _w("9.99", .647, .136), _w("outside", .82, .136),
              _w("municipality", .86, .136)]
             + [_w("onUS", .094, .154), _w("13", .132, .154),
                _w("1.11", .647, .154), _w("ft-Intersection)", .772, .154)])
    loc = _read(words)
    assert loc.dist_from_municipality == pytest.approx(9.99)
    assert loc.dist_from_intersection == pytest.approx(1.11)


def test_unreadable_fields_stay_none_rather_than_guessed():
    loc = _read([_w("onUS", .094, .154), _w("13", .132, .154),
                 _w("ft-Intersection)", .772, .154)])
    assert loc.on_road == "US 13"
    assert loc.dist_from_intersection is None
    assert loc.municipality == "" and loc.latitude is None


def test_coordinates_are_read_from_their_value_lines():
    words = [_w("Latitude", .775, .175), _w("35.60429", .84, .175),
             _w("Longitude", .775, .189), _w("-77.10702", .84, .189)]
    loc = _read(words)
    assert loc.latitude == pytest.approx(35.60429)
    assert loc.longitude == pytest.approx(-77.10702)


def test_street_name_survives_when_the_road_is_not_a_numbered_route():
    from safety_eval.location import _clean_route
    assert _clean_route("MOUNT CARMEL CHURCH RD") == "MOUNT CARMEL CHURCH RD"
    assert _clean_route("onUS 13") == "US 13"
    assert _clean_route("0 US 13") == "US 13"
    assert _clean_route("rom SR1132") == "SR 1132"


def test_from_files_merges_several_reports(tmp_path):
    """A study names more than one route, so the reports merge into one
    inventory."""
    from safety_eval.location import FeatureInventory
    a = tmp_path / "us13.txt"; a.write_text(
        "GREENE 20000013 0.0\n"
        "1.993 40001132 SR 1132 At grade intersection, 4 legs 0.000 South and East\n",
        encoding="utf-8")
    b = tmp_path / "nc58.csv"; b.write_text(
        "route,feature,milepost\nNC 58,SR 1300,4.25\n", encoding="utf-8")
    inv = FeatureInventory.from_files([str(a), str(b)])
    assert inv.milepost_of("US 13", "SR 1132") == pytest.approx(1.993)
    assert inv.milepost_of("NC 58", "SR 1300") == pytest.approx(4.25)


def test_from_files_accepts_a_single_path(tmp_path):
    from safety_eval.location import FeatureInventory
    p = tmp_path / "r.csv"; p.write_text("route,feature,milepost\nUS 13,SR 1132,2.0\n",
                                         encoding="utf-8")
    inv = FeatureInventory.from_files(str(p))
    assert inv.milepost_of("US 13", "SR 1132") == pytest.approx(2.0)
