"""Fiche roads and combinations: the Patton Avenue case, settled by hand
first (2026-09): 24 combinations, cross x mainline only, suffixes attached
to the number with no space."""
import pytest

from safety_eval.intersection_roads import (Road, combinations,
                                            defensive_roads, fiche_roads,
                                            leg_group, parse_road, render)

MAINLINE = ["US 19", "US 23", "US 74 ALT", "Patton Ave"]
CROSSES = [["SR 1319", "Johnston Blvd"],
           ["US 19BUS", "US 23 Bus", "Haywood Rd"],
           ["Ormand Ave"]]


def _legs():
    return leg_group(MAINLINE), [leg_group(c) for c in CROSSES]


def test_route_parsing_attaches_the_suffix_and_derives_the_code():
    assert parse_road("US 74 ALT").name == "US 74ALT"
    assert parse_road("US 74 ALT").code == "21000074"
    assert parse_road("us 74alt").name == "US 74ALT"
    assert parse_road("US 19BUS").code == "29000019"
    assert parse_road("US 23-BYP").code == "22000023"
    assert parse_road("US 64").code == "20000064"      # the docs/09 example
    assert parse_road("SR 1319").code == "40001319"
    assert parse_road("NC 63").code == "30000063"
    assert parse_road("I 240").code == "10000240"


def test_a_local_name_and_a_suffixed_nc_route_leave_the_code_open():
    r = parse_road("Patton Ave")
    assert r.name == "PATTON AVE" and r.code is None
    assert "road search" in r.note
    r = parse_road("NC 24 ALT")
    assert r.code is None and "verify" in r.note


def test_defensive_expansion_covers_every_us_suffix_not_on_a_leg():
    mainline, crosses = _legs()
    extra = defensive_roads([mainline] + crosses)
    names = {r.name for r in extra}
    assert names == {"US 19ALT", "US 19BYP", "US 23ALT", "US 23BYP",
                     "US 74", "US 74BYP", "US 74BUS"}
    assert all(r.source == "defensive" for r in extra)
    by = {r.name: r.code for r in extra}
    assert by["US 74"] == "20000074" and by["US 19BYP"] == "22000019"


def test_the_fiche_roads_are_legs_then_defensive_then_extras():
    mainline, crosses = _legs()
    roads = fiche_roads(mainline, crosses, extra=["Ormond Ave"])
    names = [r.name for r in roads]
    assert names.index("US 19") < names.index("US 74BYP") < names.index(
        "ORMOND AVE")
    assert len(names) == len(set(names))               # no duplicates
    assert next(r for r in roads if r.name == "ORMOND AVE").source == "extra"


def test_combinations_are_cross_by_mainline_only_24_for_patton():
    mainline, crosses = _legs()
    combos = combinations(mainline, crosses)
    assert len(combos) == 24
    pairs = {(c.name, m.name) for c, m in combos}
    assert ("SR 1319", "US 74ALT") in pairs
    assert ("ORMAND AVE", "PATTON AVE") in pairs
    # never cross x cross, never same-street, never a defensive road
    cross_names = {r.name for g in crosses for r in g}
    for c, m in combos:
        assert c.name in cross_names
        assert m.name in {r.name for r in mainline}
    assert ("SR 1319", "HAYWOOD RD") not in pairs
    assert ("US 19BUS", "HAYWOOD RD") not in pairs
    assert not any("BYP" in c.name or "BYP" in m.name for c, m in combos)


def test_the_rendering_never_puts_a_space_before_a_suffix():
    mainline, crosses = _legs()
    text = render(mainline, crosses, extra=["Ormond Ave"])
    assert "US 74ALT" in text and "US 74 ALT" not in text
    assert "US 19BUS" in text and "US 19 BUS" not in text
    assert "INTERSECTION COMBINATIONS (24)" in text
    assert "________" in text                           # local code to fill


def test_an_empty_name_is_rejected():
    with pytest.raises(ValueError):
        parse_road("   ")
