"""Assembling the study fiche workbook (docs/02).

Pinned against what the delivered workbooks actually contain, not against what
would be tidier. The two that matter: the fiche sheet keeps its page footers,
and the ID sheet's columns land where the engineer's paste put them.
"""
import datetime

import openpyxl
import pytest

from safety_eval.fiche_workbook import (SHEET_DETAILED, SHEET_ID, SHEET_INDEX,
                                        SHEET_INITIAL, build_fiche_workbook,
                                        coerce, fiche_crash_ids,
                                        parse_initial_ids)

STUDY = "41000079305"
SHEET = f"{STUDY}_Fiche"

FICHE_CSV = '''"North Carolina Department of Transportation
Traffic Engineering Accident Analysis System
Fiche Report"
"County","County Code","Division"
,"POLK","075","14"
"Road Name","Road Code"
"US 74","20000074"
"08/07/2026","Page 1 of 2"
"Muni.
Code","On Road","Miles  /  Dir
From","From Road","Toward Road","Milepost Road","MP","MA","Crash ID","Date","T","C","F","L","S"
"0","US 74","0.500","E","*MILE 62 ","*MILE 63 ","I 26","4.138","","106686224","2021-09-03","19","1","0","1","O"
"0","US 74","0.000","","I 26","*MILE 65 ","I 26","7.818","Y","107401040","2023-07-13","23","1","19","1","O"
"08/07/2026","Page 2 of 2"
"Muni.
Code","On Road","Miles  /  Dir
From","From Road","Toward Road","Milepost Road","MP","MA","Crash ID","Date","T","C","F","L","S"
"0","US 74","0.100","W","I 26","*MILE 66 ","I 26","999.999","","107127776","2022-10-30","19","2","2","5","O"
"Legend:","Muni. Code - Municipality Code","T - Accident Type"
'''

INITIAL_ID = """CRASH ID|ON RD CD|SVRTY|DATE|TYPE|
106686224|20000074|5|09/03/2021 10:47|19|
999999999|20000074|5|01/06/2023 09:09|17|
"""


@pytest.fixture
def built(tmp_path):
    out = tmp_path / "41000079305_Fiche.xlsx"
    counts = build_fiche_workbook(
        str(out), study=STUDY, fiche_csv=FICHE_CSV, initial_id_txt=INITIAL_ID,
        initial_study_csv='"Study:","41000079305"\n',
        detailed_fiche_csv='"Crash ID","Latitude"\n"106686224","35.28863"\n')
    return openpyxl.load_workbook(str(out)), counts


# --------------------------------------------------------------------------- #
# cell typing
# --------------------------------------------------------------------------- #
def test_numbers_and_dates_are_typed_like_a_paste():
    """The ID sheet joins two crash lists; text "107" never matches numeric 107."""
    assert coerce("106686224") == 106686224
    assert coerce("999.999") == pytest.approx(999.999)
    assert coerce("2021-09-03") == datetime.datetime(2021, 9, 3)
    assert coerce("09/03/2021 10:47") == datetime.datetime(2021, 9, 3, 10, 47)
    assert coerce("10:47") == datetime.time(10, 47)


def test_leading_zero_identifiers_stay_text():
    """A county code is an identifier, not a quantity; 075 must not become 75."""
    assert coerce("075") == "075"
    assert coerce("20000074") == 20000074      # no leading zero, so a number
    assert coerce("") is None


# --------------------------------------------------------------------------- #
# the working fiche sheet (rules read off the delivered Filtered Fiche)
# --------------------------------------------------------------------------- #
def test_footers_headers_and_legend_are_removed(built):
    """This is the working sheet, not the raw paste. Only crash rows survive."""
    wb, _ = built
    ws = wb[SHEET]
    col_ab = [f"{ws.cell(row=r, column=1).value} {ws.cell(row=r, column=2).value}"
              for r in range(1, ws.max_row + 1)]
    assert not any("Page " in t for t in col_ab)
    assert not any("Legend" in t for t in col_ab)
    assert sum(t.startswith("Muni.") for t in col_ab) == 1      # the header only
    assert not any("Road Name" in t for t in col_ab)
    assert ws.max_row == 4                                      # header + 3 crashes


def test_miles_and_dir_are_split_so_labels_line_up(built):
    """The raw row has 16 fields under a 15-cell header; C/D fixes that."""
    wb, _ = built
    ws = wb[SHEET]
    assert [ws.cell(row=1, column=c).value for c in (3, 4)] == ["Miles", "Dir\nFrom"]
    row = {ws.cell(row=1, column=c).value: ws.cell(row=2, column=c).value
           for c in range(1, 24)}
    assert row["Miles"] == pytest.approx(0.5) and row["Dir\nFrom"] == "E"
    assert row["On Road"] == "US 74" and row["Crash ID"] == 106686224


def test_is_and_new_mp_are_inserted_after_mp_and_left_blank(built):
    wb, _ = built
    ws = wb[SHEET]
    assert [ws.cell(row=1, column=c).value for c in (8, 9, 10, 11)] == \
        ["MP", "IS?", "New MP", "MA"]
    assert ws.cell(row=2, column=9).value is None     # the engineer's to fill
    assert ws.cell(row=2, column=10).value is None


def test_rows_are_sorted_by_milepost_with_999_last(built):
    wb, _ = built
    ws = wb[SHEET]
    mps = [ws.cell(row=r, column=8).value for r in range(2, ws.max_row + 1)]
    assert mps == sorted(mps)
    assert mps[-1] == pytest.approx(999.999)


def test_type_is_a_vlookup_into_the_index_sheet(built):
    wb, _ = built
    assert wb[SHEET]["S2"].value == \
        '=IFERROR(VLOOKUP(N2,Index!$A$1:$B$26,2,FALSE),"")'
    idx = wb["Index"]
    codes = {idx.cell(row=r, column=1).value: idx.cell(row=r, column=2).value
             for r in range(1, 27)}
    assert codes[19] == "FO" and codes[23] == "LTSR" and codes[30] == "angle"


def test_dir_walks_the_initial_study_unit_lines(built):
    """Vehicle 1 is the row below the crash, vehicle 2 the one below that."""
    wb, _ = built
    ws = wb[SHEET]
    assert ws["T2"].value == "=AA2"
    v1, v2 = ws.cell(row=2, column=25).value, ws.cell(row=2, column=26).value
    assert "MATCH(L2, 'Initial Study'!B:B, 0)+1)" in v1.replace(" ", "")\
        .replace("MATCH(L2,'InitialStudy'!B:B,0)+1)", "MATCH(L2, 'Initial Study'!B:B, 0)+1)")
    assert "+1" in v1 and "+2" in v2
    assert "ISNUMBER" in v2          # stops a 1-vehicle crash taking the next row
    assert v2.endswith('"-"),"-")')  # no second unit -> "-"


def test_the_movement_pair_is_shaped_by_crash_type(built):
    """RE -> BT/BT, left turns -> BL/BT, right turns -> BR/BT."""
    pair = built[0][SHEET].cell(row=2, column=27).value
    assert '=IF(S2="RE"' in pair
    assert '"BT/"' in pair and '"BL"' in pair and '"BR"' in pair
    assert 'S2="LTDR"' in pair and 'S2="RTSR"' in pair


def test_coordinates_come_from_the_detailed_fiche_by_crash_id(built):
    wb, _ = built
    ws = wb[SHEET]
    assert ws["V2"].value == \
        '=IFERROR(INDEX(DetailedFiche!Q:Q,MATCH(L2,DetailedFiche!J:J,0)),"")'
    assert ws["W2"].value == \
        '=IFERROR(INDEX(DetailedFiche!R:R,MATCH(L2,DetailedFiche!J:J,0)),"")'


def test_every_formula_is_iferror_wrapped(built):
    """Most fiche crashes are not in the initial study; #N/A everywhere is not
    an acceptable working sheet."""
    ws = built[0][SHEET]
    for col in (19, 22, 23, 25, 26):
        assert ws.cell(row=2, column=col).value.startswith("=IFERROR(")


def test_header_is_bold_and_frozen(built):
    ws = built[0][SHEET]
    assert ws["A1"].font.bold is True
    assert ws.freeze_panes == "A2"


# --------------------------------------------------------------------------- #
# the ID sheet
# --------------------------------------------------------------------------- #
def test_crash_ids_are_found_by_header_not_by_position():
    """The column differs between exports, so it is located, never hardcoded."""
    import csv, io
    rows = list(csv.reader(io.StringIO(FICHE_CSV)))
    assert fiche_crash_ids(rows) == ["106686224", "107401040", "107127776"]


def test_crash_ids_are_deduplicated_and_keep_fiche_order():
    import csv, io
    rows = list(csv.reader(io.StringIO(FICHE_CSV + FICHE_CSV)))
    assert fiche_crash_ids(rows) == ["106686224", "107401040", "107127776"]


def test_the_pipe_export_splits_on_pipes_and_spaces():
    """5 fields land in 6 columns: the DATE field becomes a date and a time.

    This is how it was pasted, and the delivered ID sheet shows the result:
    an 8-cell header over 6-cell data rows.
    """
    header, rows = parse_initial_ids(INITIAL_ID)
    assert header == ["CRASH", "ID", "ON", "RD", "CD", "SVRTY", "DATE", "TYPE"]
    assert rows[0] == ["106686224", "20000074", "5", "09/03/2021", "10:47", "19"]


def test_id_sheet_columns_match_the_delivered_layout(built):
    wb, _ = built
    ws = wb[SHEET_ID]
    assert [ws.cell(row=1, column=c).value for c in range(1, 5)] == \
        ["Crash ID", "CRASH", "IS?", "Fiche?"]
    assert ws.cell(row=1, column=8).value == "CRASH"      # raw paste starts at H
    assert ws["A2"].value == 106686224                    # fiche list, col A
    assert ws["B2"].value == 106686224                    # initial list, col B
    assert ws["K2"].value == datetime.datetime(2021, 9, 3)
    assert ws["L2"].value == datetime.time(10, 47)


def test_fiche_flag_says_whether_an_initial_crash_is_in_the_fiche(built):
    """The whole point of the sheet: an initial-study crash the fiche missed."""
    wb, _ = built
    ws = wb[SHEET_ID]
    assert ws["D2"].value == "YES"        # 106686224 is in the fiche
    assert ws["D3"].value == "NO"         # 999999999 is not
    assert ws["C2"].value is None         # IS? is the engineer's to fill


# --------------------------------------------------------------------------- #
# the other two sheets
# --------------------------------------------------------------------------- #
def test_all_four_sheets_in_order(built):
    wb, counts = built
    assert wb.sheetnames == [SHEET, SHEET_ID, SHEET_INDEX, SHEET_INITIAL,
                             SHEET_DETAILED]
    assert counts[SHEET] == 4


def test_optional_sheets_are_omitted_when_not_supplied(tmp_path):
    out = tmp_path / "minimal.xlsx"
    build_fiche_workbook(str(out), study=STUDY, fiche_csv=FICHE_CSV)
    wb = openpyxl.load_workbook(str(out))
    assert wb.sheetnames == [SHEET, SHEET_ID, SHEET_INDEX]
