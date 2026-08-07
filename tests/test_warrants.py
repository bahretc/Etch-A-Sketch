"""NCDOT HSIP section warrants (2024 HSIP Overview, May 2024)."""
import pytest

from safety_eval.warrants import (Crash, FACILITY_MINIMUMS, ROR_TYPES,
                                  screen_section)


def crashes(n, crash_type="ROR-L", c=1, l=1):
    return [Crash(str(i), crash_type, c, l) for i in range(n)]


def f(name, s):
    return next(w for w in s.warrants if w.warrant == name)


def test_the_ror_set_is_all_eight_types_the_overview_lists():
    """Run Off Road right/left/STRAIGHT, Fixed Object, Overturn/Rollover,
    Sideswipe Opposite Direction, Parked Motor Vehicle, Head On.

    ROR-T and PMV are the two easily dropped by eye, and both belong.
    """
    assert ROR_TYPES == {"ROR-R", "ROR-L", "ROR-T", "FO", "overturn", "SSOD",
                         "PMV", "head-on"}


def test_animal_crashes_leave_the_analysis_entirely():
    """Not just the numerator: the total, the rate and every share."""
    s = screen_section(crashes(30) + crashes(20, "animal"), 1.0, "freeway")
    assert s.total == 30 and s.animal_excluded == 20
    assert s.rate == pytest.approx(30.0)
    assert f("F-2", s).total == 30


def test_both_minimums_must_be_met_not_either():
    """30 crashes over 2 miles is 15 per mile: enough crashes, too long."""
    assert screen_section(crashes(30), 1.0, "freeway").meets_minimums
    assert not screen_section(crashes(30), 2.0, "freeway").meets_minimums
    assert not screen_section(crashes(29), 0.5, "freeway").meets_minimums


def test_a_warrant_cannot_pass_when_the_minimums_fail():
    """100% run-off-road is irrelevant if the location is too small."""
    s = screen_section(crashes(10), 1.0, "freeway")
    assert f("F-2", s).share == 1.0
    assert not f("F-2", s).met
    assert f("F-2", s).note == "minimums not met"


@pytest.mark.parametrize("facility,mins", sorted(FACILITY_MINIMUMS.items()))
def test_every_facility_type_carries_the_published_minimums(facility, mins):
    s = screen_section(crashes(mins[0]), mins[0] / mins[1], facility)
    assert (s.min_total, s.min_rate) == mins
    assert s.meets_minimums                      # exactly at both thresholds


def test_freeway_thresholds():
    """F-1 48% ROR-wet, F-2 80% ROR, F-3 55% wet, F-4 52% dark."""
    base = crashes(20, "ROR-L", c=2, l=5) + crashes(20, "SSSD", c=1, l=1)
    s = screen_section(base, 1.0, "freeway")
    assert f("F-1", s).threshold == 0.48 and f("F-1", s).share == 0.5
    assert f("F-2", s).threshold == 0.80 and f("F-2", s).share == 0.5
    assert f("F-3", s).threshold == 0.55 and f("F-3", s).share == 0.5
    assert f("F-4", s).threshold == 0.52 and f("F-4", s).share == 0.5
    assert f("F-1", s).met and not f("F-2", s).met
    assert not f("F-3", s).met and not f("F-4", s).met


def test_wet_is_C_2_and_dark_is_L_4_or_5():
    """From the engineer's own conditional formatting: C between 1.1 and 2.9
    selects 2; L between 3.1 and 5.9 selects 4 and 5."""
    assert Crash("1", "ROR-L", 2, 1).is_wet
    assert not Crash("1", "ROR-L", 1, 1).is_wet
    assert Crash("1", "ROR-L", 1, 4).is_dark and Crash("1", "ROR-L", 1, 5).is_dark
    assert not Crash("1", "ROR-L", 1, 3).is_dark


def test_N4_measures_against_non_intersection_crashes_only():
    """The one warrant whose base is not the total."""
    rows = ([Crash(str(i), "ROR-L", 1, 5) for i in range(10)]
            + [Crash(f"x{i}", "ROR-L", 1, 5, at_intersection=True)
               for i in range(15)])
    s = screen_section(rows, 0.5, "us")
    assert f("N-4", s).total == 10          # not 25
    assert f("N-4", s).count == 10


def test_a_freeway_screen_reports_no_non_freeway_warrants():
    s = screen_section(crashes(30), 1.0, "freeway")
    assert {w.warrant for w in s.warrants} == {"F-1", "F-2", "F-3", "F-4"}


def test_bad_inputs_are_refused():
    with pytest.raises(ValueError):
        screen_section(crashes(30), 1.0, "interstate")
    with pytest.raises(ValueError):
        screen_section(crashes(30), 0.0, "freeway")
