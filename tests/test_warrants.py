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


def test_SSOD_counts_and_SSSD_does_not_unless_opted_in():
    """The Overview lists Sideswipe OPPOSITE Direction. Sideswipe Same is a
    workbook addition whose abbreviation cell (AB9) is left BLANK inside the
    MATCH range, so it matches nothing until an engineer types it in."""
    assert "SSOD" in ROR_TYPES and "SSSD" not in ROR_TYPES
    assert Crash("1", "SSOD").is_ror()          # always counts
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
    assert s.fi_share == pytest.approx(0.38) and s.fi_severity >= 6   # 0.375 rounded as tested
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


# ---------------------------------------------------------------------------
# the Warrant sheet
# ---------------------------------------------------------------------------
def _wsheet(tmp_path, rows, **kw):
    import openpyxl

    from safety_eval.warrant_sheet import add_warrant_sheet
    wb = openpyxl.Workbook()
    ws, screen, _ = add_warrant_sheet(wb, rows, kw.pop("length_mi", 1.0), **kw)
    return ws, screen


def _row(cid, mp, typ="ROR-L", c=1, l=1, s="O", t=2):
    return dict(mp=mp, crash_id=cid, t=t, c=c, f=0, l=l, s=s, type=typ)


def test_the_warrant_sheet_lists_only_the_analysis_crashes(tmp_path):
    """Which is the point: the highlight covers the whole table, so its extent
    can never drift out of step with the determinations."""
    ws, _ = _wsheet(tmp_path, [_row(1, 13.1), _row(2, 12.9), _row(3, 13.5)])
    # max_row counts the summary block to the right, so measure the table.
    table = [r for r in range(2, ws.max_row + 1)
             if ws.cell(row=r, column=3).value is not None]
    assert table == [2, 3, 4]                    # 3 crashes, no more
    assert [ws.cell(row=r, column=2).value for r in (2, 3, 4)] == [12.9, 13.1, 13.5]
    assert ws.cell(row=2, column=1).value == 1   # renumbered by milepost


def test_the_highlight_covers_every_row_and_matches_the_warrant(tmp_path):
    ws, _ = _wsheet(tmp_path, [_row(i, 13.0 + i / 100) for i in range(5)])
    rules = {str(rng.sqref): [r for r in rs]
             for rng, rs in ws.conditional_formatting._cf_rules.items()}
    assert "F2:F6" in rules and "H2:H6" in rules      # C and L, whole table
    assert rules["F2:F6"][0].formula == ["1.1", "3.9"]   # wet C in {2,3}
    assert rules["H2:H6"][0].formula == ["3.1", "6.9"]   # dark L in {4,5,6}


def test_each_warrant_column_has_its_own_colour_and_none_is_yellow(tmp_path):
    """All-yellow highlighting made the one hand-changed cell invisible: the
    override was the same colour as the ordinary highlight around it. One
    colour per column, and yellow appears in no rule at all."""
    ws, _ = _wsheet(tmp_path, [_row(i, 13.0 + i / 100) for i in range(5)])
    colours = set()
    for rng, rules in ws.conditional_formatting._cf_rules.items():
        col = str(rng.sqref)[0]
        for rule in rules:
            rgb = str(rule.dxf.fill.bgColor.rgb)
            assert not rgb.endswith("FFFF00"), "yellow is reserved"
            colours.add((col, rgb[-6:]))
    per_col = {c: {rgb for cc, rgb in colours if cc == c} for c, _ in colours}
    assert all(len(v) == 1 for v in per_col.values())     # one colour per column
    assert len({next(iter(v)) for v in per_col.values()}) == 3   # all distinct


def test_an_override_cell_is_carved_out_of_the_conditional_formatting(tmp_path):
    """Excel paints a matching rule OVER a direct fill, so without the carve-
    out the engineer's yellow is hidden under the ordinary highlight."""
    rows = [_row(1, 13.0, l=5), _row(2, 13.2, l=1), _row(3, 13.4, l=5)]
    rows[1]["l"] = 5
    rows[1]["fills"] = {"L": "FFFF00"}
    ws, _ = _wsheet(tmp_path, rows)
    l_ranges = [str(rng.sqref) for rng in ws.conditional_formatting._cf_rules
                if str(rng.sqref).startswith("H")]
    assert l_ranges == ["H2 H4"]                     # row 3 carved out
    assert str(ws.cell(row=3, column=8).fill.fgColor.rgb).endswith("FFFF00")


def _summary(ws):
    """``{label: value-cell content}`` for the block below the crash table."""
    return {ws.cell(row=r, column=1).value: ws.cell(row=r, column=4).value
            for r in range(2, ws.max_row + 1)
            if ws.cell(row=r, column=1).value is not None}


def test_the_summary_sits_below_the_table_not_beside_it(tmp_path):
    """A side block collides with comment text spilling rightward; below the
    table nothing collides and the sheet prints as one column."""
    rows = [_row(i, 13.0 + i / 200, c=2, l=5) for i in range(40)]
    ws, screen = _wsheet(tmp_path, rows, length_mi=1.0, facility="freeway")
    assert screen.total == 40
    # Nothing to the right of the table on its own rows...
    assert all(ws.cell(row=r, column=14).value is None
               for r in range(1, 42))
    # ...a clear gap, then the block starts in column A.
    assert ws.cell(row=42, column=1).value is None
    assert ws.cell(row=43, column=1).value == "Warrant Summary"


def test_the_summary_is_live_formulas_not_computed_values(tmp_path):
    """CLAUDE.md hard rule #4: a reviewer traces every number, and an engineer
    who edits a code sees the warrant answer move."""
    rows = [_row(i, 13.0 + i / 200, c=2, l=5) for i in range(40)]
    ws, _ = _wsheet(tmp_path, rows, length_mi=1.0, facility="freeway")
    got = _summary(ws)
    assert got["Total Crashes"] == "=COUNT(C2:C41)"
    assert got["Wet Crashes"] == '=COUNTIFS(F2:F41,">=2",F2:F41,"<=3")'
    assert got["Night Crashes"] == '=COUNTIFS(H2:H41,">=4",H2:H41,"<=6")'
    assert got["ROR Crashes"].startswith("=SUMPRODUCT(COUNTIF(J2:J41,{")
    # Shares are ROUNDed to two places BEFORE the >= test (docs/12)...
    assert got["% ROR"].startswith("=ROUND(")
    # ...the minimums come off the on-sheet facility table...
    assert got["Required Crashes"].startswith("=VLOOKUP(")
    # ...and each warrant row is one live sentence chaining minimums and the
    # rounded share against the threshold of the chosen facility.
    sents = [str(ws.cell(row=r, column=1).value)
             for r in range(2, ws.max_row + 1)
             if str(ws.cell(row=r, column=1).value).startswith("=IF(")]
    f2 = next(s for s in sents if '"F-2 Run Off Road (80%): "' in s)
    assert '"Met","Not met"' in f2 and ">=IF(" in f2 and "0.8" in f2


def test_the_facility_cell_is_a_dropdown_that_switches_the_warrants(tmp_path):
    """A typed FREEWAY label does nothing. The facility is an input: a
    dropdown whose choice drives the minimums (VLOOKUP into the on-sheet
    table) and flips every warrant row between its F and N forms."""
    rows = [_row(i, 13.0 + i / 200, c=2, l=5) for i in range(40)]
    ws, _ = _wsheet(tmp_path, rows, length_mi=1.0, facility="freeway")
    dvs = ws.data_validations.dataValidation
    assert len(dvs) == 1
    for label in ("Freeway", "US Route", "NC Route", "Secondary Road",
                  "City Street"):
        assert label in dvs[0].formula1
    got = _summary(ws)
    assert got["Facility"] == "Freeway"
    sents = [str(ws.cell(row=r, column=1).value)
             for r in range(2, ws.max_row + 1)
             if str(ws.cell(row=r, column=1).value).startswith("=IF(")]
    assert len(sents) == 4
    assert all('"F-' in s and '"N-' in s and '="Freeway"' in s for s in sents)
    # The minimums table the VLOOKUPs read is on the sheet, labels matching
    # the dropdown exactly.
    col_a = [ws.cell(row=r, column=1).value for r in range(1, ws.max_row + 1)]
    t = col_a.index("Facility Minimums")
    assert col_a[t + 2:t + 7] == ["Freeway", "US Route", "NC Route",
                                  "Secondary Road", "City Street"]
    assert ws.cell(row=t + 3, column=4).value == 30    # freeway 30 / 30


def test_summary_labels_fit_before_the_value_column(tmp_path):
    """Labels sit in column A and can only spill across B and C before the
    value in D: roughly 21 characters of room. A longer label is clipped in
    Excel, which is exactly the kind of thing that never shows up in code
    review and looks broken the moment the file is opened."""
    rows = [_row(i, 13.0 + i / 200, c=2, l=5) for i in range(40)]
    ws, _ = _wsheet(tmp_path, rows, length_mi=1.0, facility="freeway")
    for r in range(2, ws.max_row + 1):
        a = ws.cell(row=r, column=1).value
        d = ws.cell(row=r, column=4).value
        if a is None or d is None or str(a).startswith("="):
            continue
        assert len(str(a)) <= 21, f"row {r}: label {a!r} would clip"


def test_the_summary_has_no_animal_row(tmp_path):
    """The table already holds post-DEL crashes, so an animal count of the
    rows above it could only ever say zero: noise, not information."""
    rows = [_row(i, 13.0 + i / 200) for i in range(5)]
    ws, _ = _wsheet(tmp_path, rows, length_mi=1.0, facility="freeway")
    assert not any("animal" in str(ws.cell(row=r, column=1).value).lower()
                   for r in range(1, ws.max_row + 1))


def _mixed_rows():
    """40 crashes, all ROR: 4 wet, the first 18 at night. Exercises every
    finding status at once on a freeway: F-2 met over the full section
    (100% ROR), F-4 met only in a sub-section (18/40 = 45% overall but 58%
    over the first 31 crashes), F-1 and F-3 out of reach anywhere (4 wet
    crashes is 13% at best)."""
    return [_row(i, 13.0 + i * 0.005,
                 c=2 if i in (0, 5, 10, 15) else 1,
                 l=5 if i < 18 else 1) for i in range(40)]


def test_the_findings_are_one_conclusion_per_warrant(tmp_path):
    """Not the raw window list: on a real corridor the windows overlap so
    heavily the list reads as the same line six times. The reader's question
    is per warrant, and each gets exactly one answer."""
    ws, _ = _wsheet(tmp_path, _mixed_rows(), length_mi=1.0,
                    facility="freeway")
    col_a = [str(ws.cell(row=r, column=1).value)
             for r in range(1, ws.max_row + 1)]
    head = col_a.index("Sub-section Findings (Freeway)")
    lines = []
    for v in col_a[head + 1:]:
        if v == "None":                          # the blank row below
            break
        lines.append(v)
    assert [line.split()[0] for line in lines] == ["F-1", "F-2", "F-3", "F-4"]
    assert "met over the full section at 100%" in lines[1]
    assert "not met in any sub-section" in lines[0] and "best" in lines[0]
    assert "met only in a sub-section" in lines[3]
    assert "widest" in lines[3] and "tightest" in lines[3]


def test_the_sheet_is_rebuilt_not_duplicated(tmp_path):
    import openpyxl

    from safety_eval.warrant_sheet import SHEET_WARRANT, add_warrant_sheet
    wb = openpyxl.Workbook()
    for _ in range(3):
        add_warrant_sheet(wb, [_row(1, 13.0)], 1.0)
    assert wb.sheetnames.count(SHEET_WARRANT) == 1


# ---------------------------------------------------------------------------
# scanning for a section that warrants
# ---------------------------------------------------------------------------
from safety_eval.warrants import MIN_SECTION_MI, best_windows, scan_sections


def placed(n, lo=13.0, step=0.01, **kw):
    return [(lo + i * step, Crash(str(i), kw.get("t", "ROR-L"),
                                  kw.get("c", 1), kw.get("l", 1)))
            for i in range(n)]


def test_a_window_shorter_than_the_minimum_is_refused():
    """Ten crashes in 0.02 mi is 500 per mile: arithmetic, not engineering."""
    assert scan_sections(placed(10, step=0.002), "freeway") == []
    assert MIN_SECTION_MI == 0.10


def test_crashes_sharing_a_milepost_do_not_break_the_sort():
    """Routine on a real corridor, and a Crash is not orderable."""
    rows = [(13.0, Crash("1", "ROR-L")), (13.0, Crash("2", "ROR-L")),
            (13.5, Crash("3", "ROR-L"))]
    scan_sections(rows, "freeway")          # must not raise


def test_the_scan_finds_the_windows_that_warrant():
    wins = scan_sections(placed(40, step=0.01), "freeway")
    assert wins, "40 ROR crashes over 0.39 mi warrants somewhere"
    assert all("F-2" in w.names for w in wins)
    assert all(w.length >= MIN_SECTION_MI for w in wins)
    assert wins[0].length == max(w.length for w in wins)     # longest first


def test_boundaries_are_the_crash_mileposts():
    """A boundary between two crashes gives the same crash set as one at the
    crash, and only a worse length, so scanning the mileposts is complete."""
    mps = {w.lo for w in scan_sections(placed(40), "freeway")}
    assert mps <= {13.0 + i * 0.01 for i in range(40)}


def test_best_windows_drops_the_contained_duplicates():
    wins = scan_sections(placed(40), "freeway")
    best = best_windows(wins)
    assert len(best) < len(wins)
    assert best[0].length == wins[0].length          # keeps the longest


def test_a_section_with_no_pattern_warrants_nothing():
    """Enough crashes and enough rate, but they are rear-ends."""
    assert scan_sections(placed(40, t="RE"), "freeway") == []


def test_best_achievable_reports_the_ceiling_for_every_warrant():
    """A warrant missed by one crash and a warrant that is structurally out of
    reach look identical in a met/not-met list, and are not the same finding."""
    from safety_eval.warrants import best_achievable
    rows = placed(40, step=0.01)            # all ROR, all dry, all daylight
    best = best_achievable(rows, "freeway")
    assert set(best) == {"F-1", "F-2", "F-3", "F-4"}
    assert best["F-2"][0] == 1.0            # every crash is ROR
    assert best["F-3"][0] == 0.0            # no wet crash anywhere: settled
    for name, (share, lo, hi, count, base, threshold) in best.items():
        assert lo < hi and 0 <= share <= 1 and count <= base


def test_findings_give_one_answer_per_warrant():
    """The scan's window list collapses to a per-warrant conclusion: met over
    the section, met only in a sub-section (and then the widest and the
    tightest), or out of reach anywhere (and then the ceiling)."""
    from safety_eval.warrants import format_finding, subsection_findings
    pl = [(13.0 + i * 0.005, Crash(str(i), "ROR-L",
                                   2 if i in (0, 5, 10, 15) else 1,
                                   5 if i < 18 else 1))
          for i in range(40)]
    s = screen_section([c for _, c in pl], 1.0, "freeway")
    fs = subsection_findings(pl, s)
    assert [x.warrant for x in fs] == ["F-1", "F-2", "F-3", "F-4"]
    assert [x.status for x in fs] == ["none", "section", "none", "subsection"]
    f4 = fs[3]
    assert f4.widest.length >= f4.tightest.length
    assert f4.tightest.length >= MIN_SECTION_MI
    line = format_finding(f4)
    assert line.startswith("F-4 Night Location (52%): met only in a")
    assert "widest" in line and "tightest" in line
    assert "the best is" in format_finding(fs[0])   # the F-1 ceiling, placed
    assert format_finding(fs[1]).endswith("met over the full section at 100%.")


def test_shares_are_rounded_to_whole_percents_before_the_test():
    """ROUND(count/total, 2) >= threshold, exactly as the workbook computes.

    16 of 31 is 51.6%, which rounds to 52% and MEETS a 52% threshold. On study
    41000079305 this is the difference between F-4 met and not met, so it is
    the test itself, not presentation.
    """
    from safety_eval.warrants import rounded_share
    assert rounded_share(16, 31) == 0.52
    dark = [Crash(str(i), "ROR-L", 1, 5) for i in range(16)]
    day = [Crash(f"d{i}", "ROR-L", 1, 1) for i in range(15)]
    s = screen_section(dark + day, 0.5, "freeway")
    f4 = f("F-4", s)
    assert f4.exact_share == pytest.approx(16 / 31)
    assert f4.share == 0.52 and f4.met


def test_rounding_can_also_push_a_share_down():
    """15/31 = 48.4% rounds to 48%, which still fails 52%: symmetric, not a
    grace margin."""
    dark = [Crash(str(i), "ROR-L", 1, 5) for i in range(15)]
    day = [Crash(f"d{i}", "ROR-L", 1, 1) for i in range(16)]
    assert not f("F-4", screen_section(dark + day, 0.5, "freeway")).met


def test_an_overridden_value_carries_its_fill_and_the_analysis_uses_it(tmp_path):
    """A hand-corrected code shows solid yellow on the Warrant sheet; the
    original stays on the fiche sheet, which this sheet never edits."""
    rows = [_row(1, 13.0, l=5), _row(2, 13.2, l=1)]
    rows[1]["l"] = 5
    rows[1]["fills"] = {"L": "FFFF00"}
    ws, screen = _wsheet(tmp_path, rows)
    cell = ws.cell(row=3, column=8)                  # L of the second crash
    assert cell.value == 5
    assert cell.fill.patternType == "solid"
    assert str(cell.fill.fgColor.rgb).endswith("FFFF00")
    assert ws.cell(row=2, column=8).fill.patternType is None   # others untouched
    f4 = next(w for w in screen.warrants if w.warrant == "F-4")
    assert f4.count == 2                             # the override counts
