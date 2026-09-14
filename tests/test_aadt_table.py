"""aadt_table: black/red convention, interpolation, rounding, representative years."""
from safety_eval.aadt_table import (LegSeries, colours_by_year, intersection_table,
                                    intersection_volume, representative_year, series_from_station,
                                    to_legs_by_year)

YEARS = list(range(2016, 2027))


def _legs():
    return {
        "leg1": LegSeries("leg1", {2017: 4100, 2019: 4500, 2021: 3500}),
        "leg2": LegSeries("leg2", {2016: 2200, 2018: 3100, 2022: 2100, 2024: 3200, 2025: 3200}),
        "leg4": LegSeries("leg4", {2016: 1600, 2022: 1200, 2024: 1900, 2025: 1900}, is_minor=True),
        "leg3": LegSeries("leg3", is_minor=True, assumed_from="leg4"),
    }


def test_published_black_everything_else_red():
    t = intersection_table(_legs(), YEARS)
    assert t[2017]["leg1"].colour == "black" and t[2017]["leg1"].source == "published"
    assert t[2016]["leg1"].colour == "red" and t[2016]["leg1"].source == "carried"
    assert t[2022]["leg1"].source == "carried" and t[2022]["leg1"].value == 3500
    assert t[2026]["leg2"].colour == "red" and t[2026]["leg2"].value == 3200
    assert all(t[y]["leg3"].colour in ("red", None) for y in YEARS)   # assumed leg never black
    assert t[2024]["leg3"].value == t[2024]["leg4"].value == 1900


def test_interpolation_rounding_major_50_minor_100():
    t = intersection_table(_legs(), YEARS)
    assert t[2017]["leg2"].value == 2650          # major: 50 vpd granularity
    assert t[2023]["leg2"].value == 2650
    assert t[2017]["leg4"].value == 1500          # 1533 -> nearest hundred
    assert t[2018]["leg4"].value == 1500
    assert t[2019]["leg4"].value == 1400
    assert t[2021]["leg4"].value == 1300
    assert t[2023]["leg4"].value == 1600          # 1550 tie rounds half up


def test_representative_years_and_volumes():
    t = intersection_table(_legs(), YEARS)
    assert representative_year(t, list(range(2016, 2021))) == 2019
    assert representative_year(t, list(range(2021, 2027))) == 2025
    # 2020 is never chosen even when it is the last year with data
    t2 = intersection_table({"leg1": LegSeries("leg1", {2018: 1000, 2020: 1100})}, [2018, 2019, 2020])
    assert representative_year(t2, [2018, 2019, 2020]) == 2018
    assert intersection_volume(t, 2019)["rounded"] == 5100
    assert intersection_volume(t, 2025)["rounded"] == 5300
    assert intersection_volume(t, 2025)["total"] == 5250


def test_shapes_for_setup_sheet_and_colour_patches():
    t = intersection_table(_legs(), YEARS)
    legs_by_year = to_legs_by_year(t)
    assert legs_by_year[2019] == {"leg1": 4500, "leg2": 2850, "leg4": 1400, "leg3": 1400}
    colours = colours_by_year(t)
    assert colours[2025] == {"leg1": "red", "leg2": "black", "leg4": "black", "leg3": "red"}


def test_series_from_station_filters_years():
    s = series_from_station("leg2", {2012: 2700, 2016: 2200, 2025: 3200}, years=YEARS)
    assert s.published == {2016: 2200, 2025: 3200}


def test_unknown_assumed_leg_rejected():
    import pytest

    with pytest.raises(ValueError):
        intersection_table({"leg3": LegSeries("leg3", assumed_from="leg9")}, YEARS)
