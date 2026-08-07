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
    s = screen_section(crashes(31) + crashes(20, "animal"), 1.0, "freeway")
    assert s.total == 31 and s.animal_excluded == 20
    assert s.rate == pytest.approx(31.0)
    assert f("F-2", s).total == 31


def test_both_minimums_must_be_met_not_either():
    """31 crashes over 2 miles is 15.5 per mile: enough crashes, too long."""
    assert screen_section(crashes(31), 1.0, "freeway").meets_minimums
    assert not screen_section(crashes(31), 2.0, "freeway").meets_minimums
    assert not screen_section(crashes(29), 0.5, "freeway").meets_minimums


def test_the_minimums_are_strictly_greater_than():
    """The workbook tests U6>min, not >=. Exactly 30 does not clear 30.

    The Overview's prose ("a minimum number ... are met") reads as >=, so
    strict=False is offered, but strict is what NCDOT actually runs.
    """
    assert not screen_section(crashes(30), 1.0, "freeway").meets_minimums
    assert screen_section(crashes(30), 1.0, "freeway", strict=False).meets_minimums
    assert screen_section(crashes(31), 1.0, "freeway").meets_minimums


def test_a_warrant_cannot_pass_when_the_minimums_fail():
    """100% run-off-road is irrelevant if the location is too small."""
    s = screen_section(crashes(10), 1.0, "freeway")
    assert f("F-2", s).share == 1.0
    assert not f("F-2", s).met
    assert f("F-2", s).note == "minimums not met"


@pytest.mark.parametrize("facility,mins", sorted(FACILITY_MINIMUMS.items()))
def test_every_facility_type_carries_the_published_minimums(facility, mins):
    total, rate = mins
    s = screen_section(crashes(total + 1), total / (rate + 1), facility)
    assert (s.min_total, s.min_rate) == mins
    assert s.meets_minimums


def test_freeway_thresholds():
    """F-1 48% ROR-wet, F-2 80% ROR, F-3 55% wet, F-4 52% dark."""
    base = crashes(20, "ROR-L", c=2, l=5) + crashes(20, "RE", c=1, l=1)
    s = screen_section(base, 1.0, "freeway")
    assert f("F-1", s).threshold == 0.48 and f("F-1", s).share == 0.5
    assert f("F-2", s).threshold == 0.80 and f("F-2", s).share == 0.5
    assert f("F-3", s).threshold == 0.55 and f("F-3", s).share == 0.5
    assert f("F-4", s).threshold == 0.52 and f("F-4", s).share == 0.5
    assert f("F-1", s).met and not f("F-2", s).met
    assert not f("F-3", s).met and not f("F-4", s).met


def test_wet_is_C_2_or_3_and_dark_is_L_4_5_or_6():
    """From the warrants workbook: COUNTIFS(C,">=2",C,"<=3") and
    COUNTIFS(L,">=4",L,"<=6"). Both are WIDER than the working sheet's
    conditional formatting, so a cell can be unhighlighted and still count."""
    assert Crash("1", "ROR-L", 2, 1).is_wet and Crash("1", "ROR-L", 3, 1).is_wet
    assert not Crash("1", "ROR-L", 1, 1).is_wet
    for l in (4, 5, 6):
        assert Crash("1", "ROR-L", 1, l).is_dark
    assert not Crash("1", "ROR-L", 1, 3).is_dark


def test_SSSD_is_run_off_road_on_a_multilane_facility_only():
    """The workbook lists "Sideswipe Same* (use SSSD)" with "*multi-lane only",
    and it is not in the 2024 Overview's prose list at all. On study
    41000079305 it moves F-2 from 82.1% to 89.7%."""
    assert not Crash("1", "SSSD").is_ror()
    assert Crash("1", "SSSD").is_ror(multilane=True)
    assert Crash("1", "ROR-L").is_ror() and Crash("1", "ROR-L").is_ror(True)


def test_N4_measures_against_non_intersection_crashes_only():
    """The one warrant whose base is not the total.

    The workbook derives non-intersection crashes as total minus the
    intersection crash TYPES (Angle, LTDR, LTSR, RTDR, RTSR, U-Turn), not from
    a flag.
    """
    rows = ([Crash(str(i), "ROR-L", 1, 5) for i in range(10)]
            + [Crash(f"x{i}", "angle", 1, 5) for i in range(15)])
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


# ---------------------------------------------------------------------------
# study types (engineer, 2026-08)
# ---------------------------------------------------------------------------
def test_the_three_study_types_and_what_branches():
    from safety_eval import study_type as st
    assert [k for k, _ in st.choices()] == ["hsip", "evaluation", "fatal"]
    assert st.get("hsip").runs_warrants and st.get("hsip").deletes_animals
    assert not st.get("evaluation").runs_warrants
    assert not st.get("fatal").runs_warrants


def test_only_hsip_deletes_animal_crashes():
    """An evaluation measures a built treatment and must account for every
    crash in the section, deer included. An HSIP package deletes them."""
    from safety_eval import study_type as st
    assert st.get("hsip").deletes_animals
    assert not st.get("evaluation").deletes_animals
    assert not st.get("fatal").deletes_animals


def test_study_types_resolve_by_key_label_or_instance():
    from safety_eval import study_type as st
    assert st.get("hsip") is st.get("HSIP Package Analysis")
    assert st.get(st.get("hsip")) is st.get("hsip")
    with pytest.raises(ValueError):
        st.get("package")


# ---------------------------------------------------------------------------
# intersection warrants (workbook sheets IU / IR)
# ---------------------------------------------------------------------------
import datetime as _dt

from safety_eval.warrants import (EPDO, FI_TYPES, RECENCY_YEARS,
                                  screen_intersection)

END = _dt.datetime(2023, 2, 28)


def icrashes(n, t="angle", sev="O", days_ago=30, c=1, l=1):
    return [Crash(str(i), t, c, l, severity=sev,
                  date=END - _dt.timedelta(days=days_ago)) for i in range(n)]


def w(name, s):
    return next(x for x in s.warrants if x.warrant == name)


def test_epdo_weights_are_the_ncdot_values():
    assert EPDO == {"K": 76.8, "A": 76.8, "B": 8.4, "C": 8.4, "O": 1.0}


def test_urban_looks_back_two_years_and_rural_three():
    assert RECENCY_YEARS == {"urban": 2, "rural": 3}
    s = screen_intersection(icrashes(30), "urban", END)
    assert s.recency_years == 2
    assert screen_intersection(icrashes(30), "rural", END).recency_years == 3


def test_frontal_impact_types():
    for t in ("angle", "LTDR", "LTSR", "RTDR", "RTSR", "U-Turn", "head-on"):
        assert t in FI_TYPES
    assert "ROR-L" not in FI_TYPES and "FO" not in FI_TYPES


def test_I3_is_a_count_of_K_and_A_frontal_impacts_not_a_share():
    """Three or more K/A frontal-impact crashes in the last 5 years."""
    s = screen_intersection(icrashes(3, sev="K") + icrashes(30), "urban", END)
    assert w("I-3", s).met and w("I-3", s).count == 3
    s2 = screen_intersection(icrashes(2, sev="K") + icrashes(30), "urban", END)
    assert not w("I-3", s2).met


def test_I3_ignores_K_and_A_on_a_non_frontal_impact_type():
    """The workbook counts the EPDO-FI column, which is blank off an FI type."""
    s = screen_intersection(icrashes(5, t="ROR-L", sev="K") + icrashes(30),
                            "urban", END)
    assert w("I-3", s).count == 0 and not w("I-3", s).met


def test_I3_is_reported_in_both_contexts():
    for ctx in ("urban", "rural"):
        names = {x.warrant for x in screen_intersection(icrashes(30), ctx, END).warrants}
        assert "I-3" in names


def test_urban_and_rural_report_only_their_own_warrants():
    u = {x.warrant for x in screen_intersection(icrashes(30), "urban", END).warrants}
    r = {x.warrant for x in screen_intersection(icrashes(30), "rural", END).warrants}
    assert u == {"I-1u", "I-2u", "I-3u", "I-4u", "I-3"}
    assert r == {"I-1r", "I-2r", "I-3r", "I-4r", "I-3"}


def test_I1u_has_two_alternative_paths():
    """%2yr>=25% AND either (FI>=12 AND %FI>=55%) or
    (Total>=35 AND %FI>=35% AND FI severity>=6)."""
    # path one: 20 FI of 30, all recent
    assert w("I-1u", screen_intersection(
        icrashes(20) + icrashes(10, t="ROR-L"), "urban", END)).met
    # path two: 40 total, 15 FI (37.5%), FI severity 76.8 from K
    s = screen_intersection(icrashes(15, sev="K") + icrashes(25, t="ROR-L"),
                            "urban", END)
    assert s.fi_share == pytest.approx(0.375) and s.fi_severity >= 6
    assert w("I-1u", s).met


def test_rural_I1_is_a_single_stricter_path():
    """%3yr>=20% AND FI>=9 AND %FI>=60%: no severity alternative."""
    assert w("I-1r", screen_intersection(
        icrashes(20) + icrashes(10, t="ROR-L"), "rural", END)).met      # 66.7%
    assert not w("I-1r", screen_intersection(
        icrashes(10) + icrashes(20, t="ROR-L"), "rural", END)).met      # 33.3%


def test_night_uses_the_warrant_light_codes():
    """L 4, 5 and 6 all count."""
    for l in (4, 5, 6):
        s = screen_intersection(icrashes(30, l=l), "urban", END)
        assert s.night == 30
    assert screen_intersection(icrashes(30, l=3), "urban", END).night == 0


def test_animal_crashes_are_excluded_here_too():
    s = screen_intersection(icrashes(30) + icrashes(20, t="animal"), "urban", END)
    assert s.total == 30


def test_bad_context_and_empty_input_are_refused():
    with pytest.raises(ValueError):
        screen_intersection(icrashes(10), "suburban", END)
    with pytest.raises(ValueError):
        screen_intersection([], "urban", END)
