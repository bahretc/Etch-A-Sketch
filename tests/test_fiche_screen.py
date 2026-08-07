"""Screening the fiche: which reports to pull (docs/02, engineer 2026-08).

The rule is the colour and nothing else. Green means the crash is measured off
a feature inside the study limits; two different colours mean the pair brackets
the limits, so the crash can fall between them and land inside.
"""
import pytest

from safety_eval.fiche_screen import classify, needs_review, normalize_feature

#: The real US 74 / Polk picture around limits 12.800-14.500.
FEATURES = {
    "*MILE 62": [3.638], "*MILE 163": [10.645], "*MILE 165": [12.662],
    "*MILE 166": [13.715], "*MILE 167": [14.655], "*MILE 170": [17.690],
    "NC 9": [14.455], "NC 108": [10.125], "SR 1326": [17.275],
    "SR 1526": [12.725], "I 26": [7.818, 8.377],
}
LO, HI = 12.800, 14.500


def screen(fr, tw, on="US 74"):
    return needs_review(fr, tw, on, FEATURES, LO, HI, route="US 74")


def test_features_bucket_by_side_of_the_study():
    assert classify("*MILE 166", FEATURES, LO, HI)[0] == "in"     # green
    assert classify("NC 9", FEATURES, LO, HI)[0] == "in"          # green
    assert classify("*MILE 167", FEATURES, LO, HI)[0] == "ne"     # blue
    assert classify("*MILE 165", FEATURES, LO, HI)[0] == "sw"     # yellow
    assert classify("NOWHERE RD", FEATURES, LO, HI)[0] is None


def test_a_green_cell_means_review():
    assert screen("*MILE 165", "*MILE 166") == "?"      # yellow + green
    assert screen("*MILE 167", "*MILE 166") == "?"      # blue + green
    assert screen("*MILE 166", "*MILE 166") == "?"      # green + green


def test_two_different_colours_mean_review():
    """Blue against yellow: whatever lies between them crosses the study."""
    assert screen("*MILE 167", "*MILE 163") == "?"
    assert screen("*MILE 163", "*MILE 167") == "?"


def test_the_same_colour_on_both_sides_is_NIS():
    assert screen("*MILE 62", "*MILE 163") == "NIS"     # both yellow
    assert screen("*MILE 167", "*MILE 170") == "NIS"    # both blue
    assert screen("I 26", "NC 108") == "NIS"            # both yellow


def test_distance_never_overrides_the_colour():
    """Crash 108018739 is measured 6.000 mi west of MILE 167.

    That puts its coded milepost at 8.655, four miles clear of the limits, and
    it is still reviewed: the distance is the officer's, and checking it is
    what the report review is for. A milepost derived from the number under
    review cannot be used to skip the review.
    """
    assert screen("*MILE 167", "*MILE 163") == "?"


def test_an_unresolvable_pair_is_reviewed():
    """Nothing placed it, so nothing rules it out."""
    assert screen("*LCL SOME DRIVE", "*LCL OTHER DRIVE") == "?"
    assert screen("*MILE 167", "*LCL SOME DRIVE") == "?"


def test_a_cross_street_crash_is_placed_where_it_meets_the_route():
    """A crash on NC 9 is at US 74 MP 14.455, inside; NC 108 is at 10.125."""
    assert needs_review("US 74", "SR 1525", "NC 9", FEATURES, LO, HI) == "?"
    assert needs_review("US 74", "SR 1186", "NC 108", FEATURES, LO, HI) == "NIS"
    assert needs_review("US 74", "SR 1324", "SR 1326", FEATURES, LO, HI) == "NIS"


def test_the_two_mile_marker_series_are_kept_apart():
    """Marker 62 is at MP 3.638 and 162 at 9.696; a loose match moves 6 miles."""
    assert normalize_feature("*MILE 62 ") == "*MILE 62"
    assert normalize_feature("*MILE 162 ") == "*MILE 162"
    assert classify("*MILE 62", FEATURES, LO, HI)[1] == pytest.approx(3.638)


def test_a_blank_on_road_is_treated_as_the_study_route():
    assert screen("*MILE 165", "*MILE 166", on="") == "?"
