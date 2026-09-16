"""Package maps: spec loading, payload assembly and page rendering without
any network (synthetic centerline, roads, places, hydro and stations)."""
import json

import pytest

from safety_eval import package_maps as pm
from safety_eval import route_geometry as rg

LAT0, LON0 = 36.2200, -80.1700
K = 364000.0


@pytest.fixture
def cl():
    coords = [[LON0, LAT0 + y / K] for y in range(0, 10561, 528)]
    coll = {"type": "FeatureCollection", "features": [{
        "type": "Feature", "properties": {"RouteID": "20000311034",
                                          "BeginMP": 10.0, "EndMP": 12.0},
        "geometry": {"type": "LineString", "coordinates": coords}}]}
    return rg.centerline_from_segments(coll, route_id="20000311034")


@pytest.fixture
def spec():
    return pm.MapSpec(wo="260307016EA", division="9", county="Forsyth",
                      route="US 311", route_id="20000311034", mp_lo=10.4,
                      mp_hi=11.6, description=["US 311 from A [MP 10.4]",
                                               "to B [MP 11.6]",
                                               "in Forsyth County"],
                      road_label="Walnut Cove Road", crash_lat=LAT0 + 0.01,
                      crash_lon=LON0, crash_text="Fatal Crash<br>at X",
                      median_year=2023)


def _ways():
    return [
        {"tags": {"highway": "primary", "name": "Walnut Cove Rd", "ref": "US 311"},
         "geometry": [{"lat": LAT0 + y / K, "lon": LON0} for y in range(0, 10561, 528)]},
        {"tags": {"highway": "secondary", "name": "Grubbs Rd", "ref": ""},
         "geometry": [{"lat": LAT0 + 0.01, "lon": LON0 + d / K}
                      for d in range(0, 3001, 500)]},
        {"tags": {"highway": "residential", "name": "State Rd 1234", "ref": ""},
         "geometry": [{"lat": LAT0 + 0.005, "lon": LON0 - d / K}
                      for d in range(0, 2001, 500)]},
    ]


def _stations():
    def st(sid, lat, rte_cls, route_id, years):
        a = {"LocationID": sid, "RTE_CLS": rte_cls, "RouteID": route_id,
             "Located_On": "US 311", "Approach": "SOUTH OF",
             "Crossroad": "SR 1979 (Grubbs Rd)"}
        a.update({f"AADT_{y}": v for y, v in years.items()})
        return {"attributes": a, "geometry": {"x": LON0, "y": lat}}
    return [st("0340000299", LAT0 + 0.006, 2, "20000311034",
               {2022: None, 2023: 4400, 2024: 4400}),
            st("0340000301", LAT0 + 0.012, 2, "20000311034",
               {2023: 4500, 2024: 4400}),
            st("0340000733", LAT0 + 0.009, 4, "40001979034", {2023: 300})]


def test_spec_round_trips_through_yaml(tmp_path, spec):
    import yaml
    d = {k: getattr(spec, k) for k in ("wo", "division", "county", "route",
                                       "route_id", "mp_lo", "mp_hi",
                                       "description", "road_label",
                                       "crash_lat", "crash_lon", "crash_text",
                                       "median_year")}
    d["area_half"] = [0.08, 0.15]
    p = tmp_path / "maps.yaml"
    p.write_text(yaml.safe_dump(d), encoding="utf-8")
    loaded = pm.load_spec(str(p))
    assert loaded.wo == "260307016EA" and loaded.area_half == (0.08, 0.15)
    assert loaded.coords == f"{spec.crash_lat:.5f}, {spec.crash_lon:.5f}"
    d["bogus"] = 1
    p.write_text(yaml.safe_dump(d), encoding="utf-8")
    with pytest.raises(ValueError):
        pm.load_spec(str(p))


def test_tiger_ways_and_refs():
    roads = [{"attributes": {"NAME": "US Hwy 311", "MTFCC": "S1200"},
              "geometry": {"paths": [[[LON0, LAT0], [LON0, LAT0 + 0.01]]]}},
             {"attributes": {"NAME": "State Rd 1979", "MTFCC": "S1400"},
              "geometry": {"paths": [[[LON0, LAT0], [LON0 + 0.01, LAT0]]]}},
             {"attributes": {"NAME": "Ramp", "MTFCC": "S1630"},
              "geometry": {"paths": [[[LON0, LAT0], [LON0 + 0.01, LAT0]]]}}]
    ways = pm.ways_from_tiger(roads)
    assert len(ways) == 2
    assert ways[0]["tags"]["ref"] == "US 311"
    assert ways[1]["tags"]["name"] == ""          # numbered SR names dropped
    assert pm.ref_of("State Hwy 65") == "NC 65" and pm.ref_of("I-40") == "I 40"


def test_location_payload_has_limits_crash_and_route_name(spec, cl):
    payload, tiles = pm.location_payload(spec, cl, _ways())
    assert tiles is None
    assert [m["txt"] for m in payload["limits"]] == ["Begin Study", "End Study"]
    assert payload["limits"][0]["ll"] == list(cl.mp_to_ll(10.4))
    assert payload["crash"]["ll"] == [spec.crash_lat, spec.crash_lon]
    names = [l["html"] for l in payload["labels"]]
    assert names.count("US 311 (Walnut Cove Rd)") == 2
    assert "Grubbs Rd" in names


def test_area_payload_pin_places_and_shield(spec, cl):
    places = [{"NAME": "Walkertown town", "CENTLAT": f"{LAT0 + 0.03:.6f}",
               "CENTLON": f"{LON0 + 0.02:.6f}"},
              {"NAME": "Far city", "CENTLAT": "35.0", "CENTLON": "-79.0"}]
    hydro = [{"attributes": {"NAME": "Belews Creek"},
              "geometry": {"paths": [[[LON0 + 0.05, LAT0], [LON0 + 0.06, LAT0 + 0.01]]]}},
             {"attributes": {"NAME": "Branch"},
              "geometry": {"paths": [[[LON0, LAT0], [LON0, LAT0 + 0.01]]]}},
             {"attributes": {"NAME": None},
              "geometry": {"rings": [[[LON0, LAT0], [LON0 + 0.01, LAT0],
                                      [LON0 + 0.01, LAT0 + 0.01], [LON0, LAT0]]]}}]
    payload = pm.area_payload(spec, cl, _ways(), places, hydro)
    assert payload["pin"] == list(cl.mp_to_ll(11.0))
    htmls = [l["html"] for l in payload["labels"]]
    assert "Walkertown" in htmls and "Far city" not in htmls
    assert any("<svg" in h for h in htmls)         # the US 311 shield
    assert len(payload["waterLine"]) == 1 and len(payload["waterPoly"]) == 1
    assert "hwy" in payload["roads"] and "res" in payload["roads"]


def test_aadt_payload_panels_box_the_median_year(spec, cl):
    payload, panels = pm.aadt_payload(spec, cl, _ways(), _stations())
    assert len(payload["stations"]) == 3
    assert [n["n"] for n in payload["numbered"]] == [1, 2]
    assert panels.count('class="panel"') == 2
    assert 'class="row hot"><b>AADT_2023</b>' in panels
    assert 'class="row hot"><b>AADT_2024</b>' not in panels
    assert "0340000733" not in panels            # a side road station
    assert payload["crash"]["txt"] == "Fatal Crash<br>at X"
    assert payload["order"][-1] == "route"


def test_governing_stations_follow_the_spec_order(spec, cl):
    spec.stations = ["0340000301", "0340000299"]
    got = pm.governing_stations(spec, cl, _stations())
    assert [g[0] for g in got] == ["0340000301", "0340000299"]


def test_render_page_is_self_contained(spec, cl):
    payload, _ = pm.location_payload(spec, cl, _ways())
    html = pm.render_page(spec, "Location Map", payload,
                          datasource="Esri, Maxar")
    assert html.count("<script>") == 3
    assert "https://" not in html.split("<body>")[1].split("<script>")[0]
    assert 'id="frame"' in html and "WO Number</b> 260307016EA" in html
    assert "PH Number" not in html
    spec.ph = "77S00141"
    assert "PH Number</b> 77S00141" in pm.render_page(spec, "x", payload)
    assert "#CC1111" in pm.locator_svg("Forsyth")


def test_build_maps_writes_three_pages_offline(tmp_path, spec, cl, monkeypatch):
    cache = tmp_path / "mapdata"
    cache.mkdir()
    (cache / "tiger_roads.json").write_text(json.dumps([
        {"layer": 2, "attributes": {"NAME": "US Hwy 311", "MTFCC": "S1100"},
         "geometry": {"paths": [[[LON0, LAT0], [LON0, LAT0 + 0.03]]]}}]))
    (cache / "tiger_places.json").write_text("[]")
    (cache / "tiger_hydro.json").write_text("[]")
    (cache / "aadt_stations.json").write_text(json.dumps(_stations()))
    out = pm.build_maps(spec, str(tmp_path), cache_dir=str(cache), tiles=False,
                        centerline=cl, log=lambda *a: None)
    assert sorted(out) == ["aadt", "area", "location"]
    for p in out.values():
        assert p.endswith(".html") and (tmp_path / p).exists()
