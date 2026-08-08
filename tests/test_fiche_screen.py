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


# ---------------------------------------------------------------------------
# presentation (engineer, 2026-08)
# ---------------------------------------------------------------------------
_HDR = ('"Muni.\nCode","On Road","Miles  /  Dir\nFrom","From Road",'
        '"Toward Road","Milepost Road","MP","MA","Crash ID","Date",'
        '"T","C","F","L","S"\n')
#: one IS (in the ID export), one "?" (green), one NIS (both yellow).
SCREEN_CSV = _HDR + (
    '"0","US 74","0.500","E","*MILE 165 ","*MILE 166 ","US 74","12.719","",'
    '"106686224","2021-09-03","19","1","0","1","O"\n'
    '"0","US 74","0.100","W","*MILE 167 ","*MILE 166 ","US 74","14.615","",'
    '"107401040","2023-07-13","23","1","19","1","O"\n'
    '"0","US 74","0.500","E","*MILE 62 ","*MILE 163 ","US 74","4.138","",'
    '"107127776","2022-10-30","19","2","2","5","O"\n')
SCREEN_IDS = "CRASH ID|ON RD CD|SVRTY|DATE|TYPE|\n106686224|20000074|5|09/03/2021 10:47|19|\n"


def _screened(tmp_path):
    import openpyxl
    from safety_eval.fiche_screen import screen_sheet
    from safety_eval.fiche_workbook import build_fiche_workbook
    out = tmp_path / "s.xlsx"
    build_fiche_workbook(str(out), study="41000079305", fiche_csv=SCREEN_CSV,
                         initial_id_txt=SCREEN_IDS)
    wb = openpyxl.load_workbook(str(out))
    ws = wb["41000079305_Fiche"]
    screen_sheet(ws, FEATURES, LO, HI, ["106686224"], route="US 74")
    return ws


def test_animals_del_only_inside_the_initial_study_branch(tmp_path):
    """DEL exists only inside the Initial Study branch (docs/03). On the real
    corridor fiche the old rule marked 112 out-of-study animal crashes DEL,
    an off-branch status on nearly a third of the sheet; they are NIS, final
    and unreviewed, because an HSIP study does not consider animals at all."""
    import openpyxl

    from safety_eval.fiche_screen import screen_sheet
    from safety_eval.fiche_workbook import build_fiche_workbook

    animal_csv = _HDR + (
        # in the Initial Study, animal -> DEL
        '"0","US 74","0.500","E","*MILE 165 ","*MILE 166 ","US 74","12.719",'
        '"","201","2021-09-03","17","1","0","1","O"\n'
        # not in the study, animal -> NIS even though the colours say review
        '"0","US 74","0.100","W","*MILE 165 ","*MILE 166 ","US 74","12.8",'
        '"","202","2023-07-13","17","1","0","1","O"\n'
        # not in the study, not an animal, same colours -> reviewed
        '"0","US 74","0.100","W","*MILE 165 ","*MILE 166 ","US 74","12.8",'
        '"","203","2023-07-14","19","1","0","1","O"\n')
    out = tmp_path / "animals.xlsx"
    build_fiche_workbook(str(out), study="X", fiche_csv=animal_csv)
    ws = openpyxl.load_workbook(str(out))["X_Fiche"]
    tally = screen_sheet(ws, FEATURES, LO, HI, ["201"], route="US 74",
                         study="hsip")
    got = {str(ws.cell(row=r, column=12).value):
           ws.cell(row=r, column=9).value
           for r in range(2, ws.max_row + 1)
           if ws.cell(row=r, column=12).value is not None}
    assert got["201"] == "DEL" and got["202"] == "NIS" and got["203"] == "?"
    assert tally == {"IS": 0, "?": 1, "NIS": 1, "DEL": 1}


def test_the_banner_sits_two_rows_below_the_last_question(tmp_path):
    """Blank row, then the banner. The delivered workbook does the same."""
    from safety_eval.fiche_screen import BANNER_TEXT
    ws = _screened(tmp_path)
    banner = next(r for r in range(1, ws.max_row + 1)
                  if ws.cell(row=r, column=1).value == BANNER_TEXT)
    assert all(ws.cell(row=banner - 1, column=c).value is None
               for c in range(1, ws.max_column + 1))          # blank row above
    assert ws.cell(row=banner - 2, column=9).value == "?"     # last "?"
    assert ws.cell(row=banner + 1, column=9).value == "NIS"   # NIS starts after


def test_the_banner_is_grey_and_bold_across_the_row(tmp_path):
    """A6A6A6 is what the delivered workbook uses (theme 0, tint -0.35)."""
    from safety_eval.fiche_screen import BANNER_TEXT
    ws = _screened(tmp_path)
    banner = next(r for r in range(1, ws.max_row + 1)
                  if ws.cell(row=r, column=1).value == BANNER_TEXT)
    cell = ws.cell(row=banner, column=1)
    assert str(cell.fill.fgColor.rgb).endswith("A6A6A6")
    assert cell.font.bold is True
    assert all(ws.cell(row=banner, column=c).fill.patternType
               for c in range(1, ws.max_column + 1))


def test_the_banner_text_does_not_set_a_column_width(tmp_path):
    """It is a heading, not content; 34 characters must not widen column A."""
    ws = _screened(tmp_path)
    assert ws.column_dimensions["A"].width < 10


def test_dates_lose_their_time(tmp_path):
    ws = _screened(tmp_path)
    assert ws.cell(row=2, column=13).number_format == "m/d/yyyy"


def test_columns_are_narrow_but_capped(tmp_path):
    from safety_eval.fiche_workbook import MAX_WIDTH
    ws = _screened(tmp_path)
    widths = {k: v.width for k, v in ws.column_dimensions.items() if v.width}
    assert widths, "autofit ran"
    assert all(w <= 30 for w in widths.values())
    assert ws.column_dimensions["Q"].width < 6      # a one-letter code column


# ---------------------------------------------------------------------------
# cut-and-paste row moves (the values-only re-sort incident)
# ---------------------------------------------------------------------------
def test_cut_and_paste_moves_styles_formats_and_formulas_together():
    """A values-only move scrambled a reviewed fiche: fills, date formats and
    group headers stayed at their old rows. Whole rows move as units."""
    import openpyxl
    from openpyxl.styles import Font, PatternFill

    from safety_eval.fiche_screen import cut_and_paste_row, reanchor_sheet
    wb = openpyxl.Workbook()
    ws = wb.active
    ws["A2"] = "keep"                                # bystander
    ws["A2"].fill = PatternFill("solid", fgColor="FF0000")
    ws["A5"] = 42
    ws["A5"].fill = PatternFill("solid", fgColor="C6EFCE")
    ws["A5"].font = Font(bold=True)
    ws["B5"] = "=A5*2"
    ws["C5"] = 45000
    ws["C5"].number_format = "m/d/yyyy"

    landed = cut_and_paste_row(ws, 5, 3)
    reanchor_sheet(ws)

    assert landed == 3
    assert ws["A3"].value == 42
    assert str(ws["A3"].fill.fgColor.rgb).endswith("C6EFCE")   # fill travelled
    assert ws["A3"].font.bold is True                          # font travelled
    assert ws["B3"].value == "=A3*2"                           # re-anchored
    assert ws["C3"].number_format == "m/d/yyyy"                # format travelled
    assert str(ws["A2"].fill.fgColor.rgb).endswith("FF0000")   # bystander kept
    assert ws["A5"].value is None                              # nothing left behind
