"""Location check: coordinates and addresses against the coded milepost."""
import math

from safety_eval import location_check as lc
from safety_eval import route_geometry as rg

LAT0, LON0 = 36.2200, -80.1700
K = 364000.0


def _straight():
    coords = [[LON0, LAT0 + y / K] for y in range(0, 10561, 528)]
    coll = {"type": "FeatureCollection", "features": [{
        "type": "Feature", "properties": {"RouteID": "r", "BeginMP": 10.0,
                                          "EndMP": 12.0},
        "geometry": {"type": "LineString", "coordinates": coords}}]}
    return rg.centerline_from_segments(coll)


def _row(cid, mp, lat="", lon=""):
    return {"Crash ID": cid, "MP": mp, "Latitude": lat, "Longitude": lon,
            "On Road": "US 311"}


def test_coordinates_confirm_or_contradict_the_coded_milepost():
    cl = _straight()
    lat_105 = LAT0 + (0.5 * 5280) / K
    lat_115 = LAT0 + (1.5 * 5280) / K
    far_lon = LON0 + 600 / (K * math.cos(math.radians(LAT0)))
    rows = lc.check_crashes([
        _row("1", "10.500", f"{lat_105:.6f}", f"{LON0:.6f}"),     # agrees
        _row("2", "10.500", f"{lat_115:.6f}", f"{LON0:.6f}"),     # off by 1 mi
        _row("3", "999.999", f"{lat_115:.6f}", f"{LON0:.6f}"),   # not mileposted
        _row("4", "10.500"),                                      # no coords
        _row("5", "10.500", f"{lat_105:.6f}", f"{far_lon:.6f}"),  # off route
        _row("9", "10.500", f"{lat_105:.6f}", f"{LON0:.6f}"),     # not asked
    ], ["1", "2", "3", "4", "5"], cl)
    by = {r.crash_id: r for r in rows}
    assert set(by) == {"1", "2", "3", "4", "5"}
    assert by["1"].note == "agrees" and not by["1"].differs
    assert by["2"].differs and by["2"].coord_mp == 11.5
    assert by["3"].coded_mp is None and by["3"].coord_mp == 11.5
    assert by["4"].coord_mp is None and "no coordinates" in by["4"].note
    assert "off the route" in by["5"].note and not by["5"].differs


def test_addresses_are_geocoded_and_snapped():
    cl = _straight()
    lat_110 = LAT0 + 5280 / K

    def fake(addr):
        if "7350" in addr:
            return lc.GeocodeHit(addr, lat_110, LON0, "7350 WALNUT COVE RD")
        return lc.GeocodeHit(addr, None, None)
    rows = lc.check_addresses([("a", "7350 Walnut Cove Rd"),
                               ("b", "nowhere")], cl, geocoder=fake)
    assert rows[0].address_mp == 11.0 and rows[0].offset_ft == 0
    assert rows[1].address_mp is None and "no geocoder" in rows[1].note
    md = lc.report_markdown([], rows)
    assert "7350 Walnut Cove Rd" in md and "11.000" in md


def test_address_list_and_csv_round_trip(tmp_path):
    p = tmp_path / "addr.txt"
    p.write_text("# crash|address\n108359870|7570 Walnut Cove Rd, Walnut Cove, NC\n"
                 "bad line\n", encoding="utf-8")
    assert lc.parse_address_list(str(p)) == [
        ("108359870", "7570 Walnut Cove Rd, Walnut Cove, NC")]
    out = tmp_path / "out.csv"
    lc.write_csv(str(out), [lc.LocationRow("1", 10.5, 10.5, 12, note="agrees")])
    assert "agrees" in out.read_text(encoding="utf-8")
