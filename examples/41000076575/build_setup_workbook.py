"""Start the 05-08-203 (TIP W-5601HP, order 41000076575) evaluation in the
office Accessible Intersection Evaluation Workbook: the Assumptions sheet
and the Evaluation Set-up sheet (CLAUDE.md rule 10, the workbook's own
Step-by-Step Instructions steps 1 and 2).

The engineer's starting copy in the WO folder is the previous evaluation's
workbook (08-17-5149, SS-4908BK) renamed, so this script also clears that
project's data from the sheets the later steps fill (Parameters, Initial
Crash ID list, Original/Filtered Fiche, Binned Crashes, Before, After, the
One Pager picks, template path and the staff CRF row), removes its map
block and station map pictures, and drops the formula caches LibreOffice
cannot recompute, all without deleting rows or columns (the instructions:
that breaks the formulas and macros). Trends, the One Pager layout, the
lists and the links are left exactly as the template carries them.

Every write is an XML-level cell edit on a copy (docs/06); drawings, media,
the VBA project and the Power Query parts stay byte-identical, and the
integrity gate runs at the end. LibreOffice then fills the formula caches
(cache transplant); Excel recalculates everything again on open.

Usage:
    python examples/41000076575/build_setup_workbook.py \
        --source "<the WO folder's Accessible Intersection Evaluation Workbook>" \
        --out "deliverables/05-08-203/Accessible Intersection Evaluation Workbook - 05-08-203 (W-5601HP).xlsm"

Sources for every fact are listed next to it in FACTS below.
"""
from __future__ import annotations

import argparse
import os
import re
import sys
import zipfile
from datetime import date

import openpyxl

from safety_eval.xlsx_patch import (CellEdit, excel_only_cells, recalc,
                                    sheet_files, verify_integrity, xlsx_patch)

# --------------------------------------------------------------------------- #
# the facts (source in brackets: MES = Master Evaluation Spreadsheet row for
# 41000076575; PJS = 05-08-203 Update.pdf, the Project Justification Sheet
# and the 1/29/2016 TEAAS strip analysis; HNTB = compliance memo 6/24/2024;
# SIG22 = signal plan 051723-20220225g; SIG19 = flasher plan 051723-20190417g;
# AADT = NCDOT AADT stations and 2025 traffic segments, ArcGIS services)
# --------------------------------------------------------------------------- #
TEAAS_DATE = date(2026, 8, 31)        # TEAAS data available through August 2026
CONSTRUCTION_END = date(2021, 7, 31)  # completed July 2, 2021 (HNTB; MES CON Completion), rounded to the month end
CONSTRUCTION_MONTHS = 3               # CON start (let) 5/24/2021 (MES DM3) rounded to the first of May: May to July
REP_BEFORE_YEAR = 2019                # last full before year that is not 2020
REP_AFTER_YEAR = 2025                 # last full after year

ASSUMPTIONS = {
    "D6": 41000076575,                                   # MES B3
    "D7": "05-08-203 (TIP #W-5601HP)",                   # MES AB3/AC3
    "D8": "05-1723",                                     # MES CQ3; SIG19/SIG22
    "D9": "SR 1375 (Lake Wheeler Road) at SR 1390 (Optimist Farm Road)/"
          "SR 1503 (Donnybrook Road)",                   # MES AF3
    "D10": "35.657816, -78.717261",                      # MES AG3 (3 ft from the geocoded junction)
    "D11": "Wake",                                       # MES AE3
    "D12": "None (outside city limits; Fuquay-Varina area)",   # MES GA3; SIG22 title block
    "D14": "Realign SR 1390 (Optimist Farm Road) and SR 1503 (Donnybrook "
           "Road) to tie directly across from one another and install "
           "shoulder-mounted actuated flashers in both directions on "
           "SR 1375 (Lake Wheeler Road).",               # MES AH3; PJS p1
    "D15": "Intersection Realignment",                   # Typical Target Crash Types row 12; MES U3
    "D16": 665000,                                       # MES AI3 (TMSD approved total 861,000: MES FH3)
    "D17": date(2021, 7, 2),                             # HNTB; MES AJ3/DN3
    "D18": "The Master Evaluation Spreadsheet carries a construction start "
           "(let) date of May 24, 2021 and a completion date of July 2, "
           "2021; the HNTB compliance memo of June 24, 2024 lists July 2, "
           "2021 as both the construction begin and completion date, and "
           "the RTE was notified complete on September 16, 2021. The "
           "construction period is set to the three whole months May to "
           "July 2021 (start rounded to the first of the month, completion "
           "to the end of the month). The two-phase fully actuated signal "
           "05-1723 (plan sealed February 25, 2022) later replaced the "
           "flashers; its turn-on date is not in the project files, and the "
           "assignment comment expects an extended construction period to "
           "cover it. Confirm the turn-on date and, if so, extend the "
           "construction period on the Evaluation Set-up sheet (cells D5 "
           "and E10).",
    "D19": 150,
    "D20": "Frontal Impact Crashes in Intersection: Angle, Left Turn "
           "Different Roadways (LTDR), Left Turn Same Roadway (LTSR), Right "
           "Turn Different Roadways (RTDR), Right Turn Same Roadway (RTSR) "
           "and Head-On",                                # guidance row 12, Target-1
    "D21": "Rear End Crashes on the SR 1375 (Lake Wheeler Road) Approaches",  # guidance row 12, Target-2; PJS problem statement
    "D22": None,
    "D23": "Limited sight distance on SR 1375 (Lake Wheeler Road) and the "
           "offset condition of SR 1390 (Optimist Farm Road) with SR 1503 "
           "(Donnybrook Road) is contributing to angle and rear end type "
           "crashes.",                                   # MES FY3; PJS p1
    "D24": "SR 1375 (Lake Wheeler Road) is a two-lane, two-way shoulder "
           "facility with a horizontal curve just north of the intersection; "
           "before the project SR 1390 and SR 1503 met SR 1375 offset from "
           "one another just south of the curve, and rear end crashes "
           "occurred exiting the curve behind vehicles turning right from "
           "SR 1390 and then left onto SR 1503 (project justification). The "
           "realignment moved the SR 1390 tie-in about 190 ft south (the "
           "pre-realignment Census TIGER centerline end measured against the "
           "current junction; confirm against the plan sheet), so the y-line "
           "may need to be extended to cover the old leg (target crash "
           "guidance for realignments). Prior project "
           "W-5205W (05-13-6035, sight distance improvements, completed 2017) "
           "was not evaluated because this project began construction in "
           "2021; to be mentioned in the report (assignment comment). Speed "
           "limits are from the February 2022 signal plan: SR 1375 45 mph, "
           "SR 1390 35 mph, SR 1503 45 mph; the April 2019 flasher plan "
           "showed SR 1390 at 45 mph. Project development crash data is the "
           "1/1/2011 to 12/31/2015 TEAAS strip analysis on SR 1375 (35 "
           "crashes, severity index 2.90). Leg #3 (SR 1390) has no count "
           "station between the intersection and SR 1404 (Johnson Pond "
           "Road); the station about 1 mile west is used. The Leg #4 (SR "
           "1503) station is east of SR 1392 (Ransdell Road), 0.15 mi from "
           "the intersection. The Division status comment says construction "
           "was completed under contract R-2721A. The NC 540 ramps at US 401 "
           "(AADT stations 0920002579 to 0920002585, no counts yet) are about "
           "half a mile away; confirm when that interchange opened before "
           "discussing after-period volumes.",
    # project development (PJS p1 and the strip analysis severity summary)
    "H7": date(2011, 1, 1), "H8": date(2015, 12, 31),
    "H10": 35, "H11": 0, "H12": 0, "H13": 2, "H14": 7, "H15": 26,
    # speed limits (SIG22)
    "O6": 45, "O7": 35,
    # legs (north up; SR 1375 runs north-south here)
    "K12": "North", "L12": "SR 1375 (Lake Wheeler Road)", "M12": 45, "N12": REP_AFTER_YEAR,
    "K13": "South", "L13": "SR 1375 (Lake Wheeler Road)", "M13": 45, "N13": REP_AFTER_YEAR,
    "K14": "West", "L14": "SR 1390 (Optimist Farm Road)", "M14": 35, "N14": REP_AFTER_YEAR,
    "K15": "East", "L15": "SR 1503 (Donnybrook Road)", "M15": 45, "N15": REP_AFTER_YEAR,
}

# AADT stations by leg (NCDOT AADT stations layer, 2025 release with the
# 2024 counts from the 2024 release): column -> (identity rows, counts)
STATIONS = {
    "L": {"id": "0920000868", "route_id": "40001375092",
          "on": "SR 1375 (Lake Wheeler Rd)", "approach": "NORTH OF",
          "cross": "SR 1390 (Optimist Farm Rd)", "fnc": "Major Collector",
          "counts": {2011: 6400, 2013: 9400, 2015: 6700, 2017: 7300, 2019: 8200,
                     2021: 8400, 2023: 7800, 2024: 8000, 2025: 8900}},
    "M": {"id": "0920000991", "route_id": "40001375092",
          "on": "SR 1375 (Lake Wheeler Rd)", "approach": "SOUTH OF",
          "cross": "SR 1503 (Donny Brook Rd)", "fnc": "Major Collector",
          "counts": {2011: 4300, 2013: 9500, 2015: 4400, 2017: 5100, 2019: 6100,
                     2021: 6100, 2023: 6000, 2024: 6200, 2025: 7400}},
    "O": {"id": "0920001913", "route_id": "40001390092",
          "on": "SR 1390 (Optimist Farm Rd)", "approach": "WEST OF",
          "cross": "SR 1404 (Johnson Pond Rd)", "fnc": "Major Collector",
          "counts": {2014: 4200, 2017: 5400, 2019: 5500, 2021: 5600, 2023: 4800,
                     2024: 4900, 2025: 4800}},
    "P": {"id": "0920001914", "route_id": "40001503092",
          "on": "SR 1503 (Donny Brook Rd)", "approach": "EAST OF",
          "cross": "SR 1392 (Ransdell Rd)", "fnc": "Major Collector",
          "counts": {2014: 3000, 2017: 3600, 2019: 3700, 2021: 3300, 2023: 2000,
                     2024: 2100, 2025: 2400}},
}
STATION_NOTES = {
    "L72": "Leg #3 (SR 1390) has no count station between the intersection "
           "and SR 1404 (Johnson Pond Rd); station 0920001913 about 1 mile "
           "west is used. The Leg #4 (SR 1503) station 0920001914 is east of "
           "SR 1392 (Ransdell Rd), 0.15 mi from the intersection. The 2013 "
           "counts on SR 1375 (9,400 and 9,500) are out of line with 2011 "
           "and 2015 and are not used in the table.",
    "L73": "Red = interpolated between counts (2020 = 0.85 x the "
           "interpolated value, COVID; 2016 on Legs #3 and #4 interpolated "
           "between the 2014 and 2017 counts; 2026 carried from 2025).",
}

STATION_ROW = {"id": 37, "county": 38, "category": 39, "direction": 40,
               "route_id": 41, "on": 42, "approach": 43, "cross": 44,
               "class": 45, "fnc": 46}
FIRST_AADT_YEAR, FIRST_AADT_ROW = 2002, 47        # AADT_2002 is row 47 ... AADT_2025 row 70
TABLE_FIRST_YEAR, TABLE_FIRST_ROW = 2010, 11      # year table: 2010 is row 11 ... 2034 row 35
TABLE_YEARS = range(2016, 2027)                   # before period start year to the TEAAS year


def station_row(year: int) -> int:
    return FIRST_AADT_ROW + (year - FIRST_AADT_YEAR)


def table_row(year: int) -> int:
    return TABLE_FIRST_ROW + (year - TABLE_FIRST_YEAR)


# --------------------------------------------------------------------------- #
# XML helpers (cell clearing without deleting rows; bulk row drops)
# --------------------------------------------------------------------------- #
_CELL = re.compile(r'<c r="([A-Z]+)(\d+)"([^>]*?)(/>|>(.*?)</c>)', re.S)


def clear_cells(xml: str, cols: set, lo: int, hi: int, keep_formulas=True) -> str:
    """Blank the value of every cell in ``cols`` x rows lo..hi, keeping the
    cell (its style) and, by default, any formula."""
    def sub(m):
        col, row, attrs, body = m.group(1), int(m.group(2)), m.group(3), m.group(5) or ""
        if col not in cols or not lo <= row <= hi:
            return m.group(0)
        if keep_formulas and "<f" in body:
            return m.group(0)
        attrs = re.sub(r'\s+t="[^"]*"', "", attrs)
        return f'<c r="{col}{row}"{attrs}/>'
    return _CELL.sub(sub, xml)


def drop_rows_from(xml: str, from_row: int) -> str:
    """Remove every ``<row>`` numbered ``from_row`` or higher (a data sheet
    the later steps refill from TEAAS), plus hyperlinks into them."""
    sd_start = xml.index("<sheetData")
    sd_open_end = xml.index(">", sd_start) + 1
    sd_close = xml.index("</sheetData>")
    body = xml[sd_open_end:sd_close]
    kept = [m.group(0) for m in re.finditer(
        r'<row r="(\d+)"[^>]*(?:/>|>.*?</row>)', body, re.S)
        if int(m.group(1)) < from_row]
    xml = xml[:sd_open_end] + "".join(kept) + xml[sd_close:]
    xml = re.sub(r"<hyperlinks>.*?</hyperlinks>", "", xml, flags=re.S)
    xml = re.sub(r'<dimension ref="[^"]*"/>', "", xml, 1)
    return xml


def style_of(xml: str, ref: str) -> str | None:
    m = re.search(rf'<c r="{ref}"[^>]*?\bs="(\d+)"', xml)
    return m.group(1) if m else None


def constant_cells(path: str, sheet: str, row: int) -> list[str]:
    """Refs of the typed (non-formula) cells on one row, via openpyxl."""
    ws = openpyxl.load_workbook(path, keep_vba=True, read_only=False)[sheet]
    out = []
    for c in ws[row]:
        if c.value is None:
            continue
        if isinstance(c.value, str) and c.value.startswith("="):
            continue
        if type(c.value).__name__ == "ArrayFormula":
            continue
        out.append(c.coordinate)
    return out


# --------------------------------------------------------------------------- #
# the edits
# --------------------------------------------------------------------------- #
def setup_edits(setup_xml: str) -> list[CellEdit]:
    black = style_of(setup_xml, "L18")      # a counted year, black font
    red = style_of(setup_xml, "L19")        # an interpolated year, red font
    count_style = style_of(setup_xml, "L62")   # a count in the station block
    if not black or not red or not count_style:
        raise RuntimeError("could not read the Set-up styles from L18/L19/L62")
    edits = [
        CellEdit("D4", TEAAS_DATE),
        CellEdit("D5", CONSTRUCTION_MONTHS),
        CellEdit("E10", CONSTRUCTION_END),
        CellEdit("N5", REP_BEFORE_YEAR),
        CellEdit("N6", REP_AFTER_YEAR),
    ]
    # year table: clear every leg cell, then the formulas for the study years
    for row in range(TABLE_FIRST_ROW, TABLE_FIRST_ROW + 25):
        for col in "LMOP":
            edits.append(CellEdit(f"{col}{row}", None))
    for col, st in STATIONS.items():
        counts = st["counts"]
        for year in TABLE_YEARS:
            r = table_row(year)
            if year in counts:
                edits.append(CellEdit(f"{col}{r}", formula=f"{col}{station_row(year)}",
                                      style=black))
                continue
            prev = max((y for y in counts if y < year), default=None)
            nxt = min((y for y in counts if y > year), default=None)

            def ref(y):
                # a counted year inside the table reads from the table (the
                # engineer's own convention); one outside it, from the count
                return f"{col}{table_row(y) if y in TABLE_YEARS else station_row(y)}"

            if prev is not None and nxt is not None:
                if nxt - prev == 2:            # the usual odd-year gap
                    f = f"ROUND(AVERAGE({ref(prev)},{ref(nxt)}),-2)"
                else:                          # a longer gap: linear between the counts
                    k, n = year - prev, nxt - prev
                    f = (f"ROUND({col}{station_row(prev)}+({col}{station_row(nxt)}"
                         f"-{col}{station_row(prev)})*{k}/{n},-2)")
                if year == 2020:
                    f = f.replace(",-2)", "*0.85,-2)")
            elif prev is not None:             # past the last count: carry forward
                f = ref(prev)
            else:
                raise RuntimeError(f"no count before {year} on leg {col}")
            edits.append(CellEdit(f"{col}{r}", formula=f, style=red))
    # station identity block and the yearly counts
    for col, st in STATIONS.items():
        edits += [
            CellEdit(f"{col}{STATION_ROW['id']}", int(st["id"])),
            CellEdit(f"{col}{STATION_ROW['county']}", "Wake"),
            CellEdit(f"{col}{STATION_ROW['category']}", "VOLUME"),
            CellEdit(f"{col}{STATION_ROW['direction']}", "2-WAY"),
            CellEdit(f"{col}{STATION_ROW['route_id']}", int(st["route_id"])),
            CellEdit(f"{col}{STATION_ROW['on']}", st["on"]),
            CellEdit(f"{col}{STATION_ROW['approach']}", st["approach"]),
            CellEdit(f"{col}{STATION_ROW['cross']}", st["cross"]),
            CellEdit(f"{col}{STATION_ROW['class']}", "SR"),
            CellEdit(f"{col}{STATION_ROW['fnc']}", st["fnc"]),
        ]
        for year in range(FIRST_AADT_YEAR, 2026):
            edits.append(CellEdit(f"{col}{station_row(year)}",
                                  st["counts"].get(year), style=count_style))
    for ref, text in STATION_NOTES.items():
        edits.append(CellEdit(ref, text))
    return edits


def assumptions_edits() -> list[CellEdit]:
    return [CellEdit(ref, value) for ref, value in ASSUMPTIONS.items()]


#: Cells whose formula is Excel-only (XLOOKUP) or depends on one, with the
#: value Excel will compute: LibreOffice cannot evaluate them, so the recalc
#: pass keeps the previous project's cache (Division 8, Moore). Wake is
#: Division 5 in the workbook's own county table; the build checks that.
DIVISION_CELLS = (("Assumptions", "D13"), ("One Pager", "I10"),
                  ("For NCDOT staff - Email", "E22"))


def county_division(path: str, county: str) -> int:
    ws = openpyxl.load_workbook(path, keep_vba=True, read_only=True)[
        "For NCDOT staff - for Tracking"]
    for r in range(39, 140):
        if ws.cell(r, 7).value == county:
            return int(ws.cell(r, 8).value)
    raise RuntimeError(f"{county} is not in the county table G39:H139")


def set_cached(path: str, values: dict) -> None:
    """Write the cached value of formula cells ({(sheet, ref): number})
    without touching the formulas; every other member is copied as is."""
    files = sheet_files(path)
    with zipfile.ZipFile(path) as z:
        infos = z.infolist()
        payload = {i.filename: z.read(i.filename) for i in infos}
    for (sheet, ref), value in values.items():
        member = files[sheet]
        xml = payload[member].decode("utf-8")
        m = re.search(rf'<c r="{ref}"([^>]*)>(<f\b.*?(?:/>|</f>))(?:<v>[^<]*</v>)?</c>', xml, re.S)
        if not m:
            raise RuntimeError(f"{sheet}!{ref} is not a formula cell")
        attrs = re.sub(r'\s+t="[^"]*"', "", m.group(1))
        cell = f'<c r="{ref}"{attrs}>{m.group(2)}<v>{value}</v></c>'
        payload[member] = (xml[:m.start()] + cell + xml[m.end():]).encode("utf-8")
    tmp = path + ".cache.tmp"
    with zipfile.ZipFile(tmp, "w", zipfile.ZIP_DEFLATED) as zout:
        for info in infos:
            zout.writestr(info, payload[info.filename])
    os.replace(tmp, path)


#: The previous project's map block (Assumptions: aerial, location map and
#: four leg text boxes) and station map (Evaluation Set-up): the pictures
#: and their media go; the drawing parts stay, empty, so the sheets keep
#: their drawing relationships. The map block for this project is composed
#: later (the Map Block page) with alt text from the Assumptions leg table.
STALE_DRAWINGS = {
    "xl/drawings/drawing2.xml": ("xl/drawings/_rels/drawing2.xml.rels",
                                 ("xl/media/image3.jpeg", "xl/media/image4.png")),
    "xl/drawings/drawing3.xml": ("xl/drawings/_rels/drawing3.xml.rels",
                                 ("xl/media/image5.png",)),
}
_ANCHOR = re.compile(r"<xdr:(twoCellAnchor|oneCellAnchor|absoluteAnchor)\b.*?</xdr:\1>", re.S)
_REL = re.compile(r"<Relationship\b[^>]*/>")


def empty_drawing(xml: str) -> str:
    return _ANCHOR.sub("", xml)


def prune_rels(rels_xml: str, keep_ids: set | None = None, drop_types=()) -> str:
    """Drop relationships of the given types (by suffix) that are not in
    ``keep_ids``; an empty Relationships element is valid."""
    def sub(m):
        rel = m.group(0)
        rid = re.search(r'\bId="([^"]+)"', rel)
        typ = re.search(r'\bType="([^"]+)"', rel)
        if typ and typ.group(1).endswith(tuple(drop_types)) and (
                keep_ids is None or (rid and rid.group(1) not in keep_ids)):
            return ""
        return rel
    return _REL.sub(sub, rels_xml)


def hyperlink_ids(sheet_xml: str) -> set:
    return set(re.findall(r'<hyperlink\b[^>]*\br:id="([^"]+)"', sheet_xml))


def strip_hyperlinks(sheet_xml: str) -> str:
    return re.sub(r"<hyperlinks>.*?</hyperlinks>", "", sheet_xml, flags=re.S)


def strip_saved_path(workbook_xml: str) -> str:
    """The absPath Excel writes on save names the folder the copy was last
    saved in (the previous WO folder); Excel writes a fresh one next save."""
    return re.sub(r"<mc:AlternateContent\b(?:(?!</mc:AlternateContent>).)*?absPath"
                  r"(?:(?!</mc:AlternateContent>).)*</mc:AlternateContent>",
                  "", workbook_xml, flags=re.S)


def drop_members(path: str, names: set) -> None:
    with zipfile.ZipFile(path) as z:
        infos = z.infolist()
        payload = {i.filename: z.read(i.filename) for i in infos}
    tmp = path + ".drop.tmp"
    with zipfile.ZipFile(tmp, "w", zipfile.ZIP_DEFLATED) as zout:
        for info in infos:
            if info.filename in names:
                continue
            zout.writestr(info, payload[info.filename])
    os.replace(tmp, path)


def clear_cached(path: str, cells) -> int:
    """Remove the cached value of formula cells LibreOffice could not
    compute (Excel-only functions and their dependents): the previous
    project's results must not show anywhere; Excel recomputes on open."""
    files = sheet_files(path)
    by_sheet = {}
    for sheet, ref in cells:
        by_sheet.setdefault(sheet, set()).add(ref)
    with zipfile.ZipFile(path) as z:
        infos = z.infolist()
        payload = {i.filename: z.read(i.filename) for i in infos}
    n = 0
    for sheet, refs in by_sheet.items():
        member = files[sheet]
        xml = payload[member].decode("utf-8")

        def sub(m):
            nonlocal n
            if m.group(1) + m.group(2) not in refs or "<f" not in (m.group(5) or ""):
                return m.group(0)
            attrs = re.sub(r'\s+t="[^"]*"', "", m.group(3))
            f_part = re.search(r"<f\b.*?(?:/>|</f>)", m.group(5), re.S).group(0)
            n += 1
            return f'<c r="{m.group(1)}{m.group(2)}"{attrs}>{f_part}</c>'
        payload[member] = re.sub(
            r'<c r="([A-Z]+)(\d+)"([^>]*?)(/>|>(.*?)</c>)', sub, xml, flags=re.S).encode("utf-8")
    tmp = path + ".cache.tmp"
    with zipfile.ZipFile(tmp, "w", zipfile.ZIP_DEFLATED) as zout:
        for info in infos:
            zout.writestr(info, payload[info.filename])
    os.replace(tmp, path)
    return n


def build(source: str, out: str, do_recalc: bool = True) -> None:
    files = sheet_files(source)
    with zipfile.ZipFile(source) as z:
        xml = {name: z.read(member).decode("utf-8") for name, member in files.items()}
        raw = {i.filename: z.read(i.filename) for i in z.infolist()}

    replace_members = {}
    # the previous project's map block and station map
    for drawing, (rels, _media) in STALE_DRAWINGS.items():
        replace_members[drawing] = empty_drawing(raw[drawing].decode("utf-8")).encode("utf-8")
        replace_members[rels] = prune_rels(raw[rels].decode("utf-8"),
                                           drop_types=("/image",)).encode("utf-8")
    # the One Pager's hyperlink to the previous WO folder, and the folder
    # path Excel saved on the workbook
    xml["One Pager"] = strip_hyperlinks(xml["One Pager"])
    replace_members[files["One Pager"]] = xml["One Pager"].encode("utf-8")
    replace_members["xl/workbook.xml"] = strip_saved_path(
        raw["xl/workbook.xml"].decode("utf-8")).encode("utf-8")
    # the previous project's data: rows go on the TEAAS paste sheets, cell
    # values go on the sheets whose rows carry formulas
    for sheet in ("Original Fiche", "Filtered Fiche", "Binned Crashes"):
        xml[sheet] = drop_rows_from(xml[sheet], 2)
        replace_members[files[sheet]] = xml[sheet].encode("utf-8")
    # hyperlink relationships the dropped rows (and the One Pager path) used
    for sheet in ("Original Fiche", "Filtered Fiche", "Binned Crashes", "One Pager"):
        rels = files[sheet].replace("worksheets/", "worksheets/_rels/") + ".rels"
        if rels in raw:
            replace_members[rels] = prune_rels(
                raw[rels].decode("utf-8"), keep_ids=hyperlink_ids(xml[sheet]),
                drop_types=("/hyperlink",)).encode("utf-8")
    for sheet in ("Before", "After"):
        replace_members[files[sheet]] = clear_cells(
            xml[sheet], set("ABCDEFGHIJKLMN"), 4, 1003).encode("utf-8")
    replace_members[files["Parameters"]] = clear_cells(
        xml["Parameters"], set("ABCDEFGHIJK"), 2, 200).encode("utf-8")
    replace_members[files["Initial Crash ID list"]] = clear_cells(
        xml["Initial Crash ID list"], set("BCDEF"), 4, 2000).encode("utf-8")

    edits = {
        "Assumptions": assumptions_edits(),
        "Evaluation Set-up": setup_edits(xml["Evaluation Set-up"]),
        # One Pager: the previous project's picks and typed counts go; the
        # target count boxes follow the two targets; the date is today's
        "One Pager": [CellEdit(f"{c}{r}", None) for r in range(5, 11) for c in "JKLM"]
                     + [CellEdit("E5", False), CellEdit("E6", True), CellEdit("E7", False),
                        CellEdit("I24", date.today()),
                        CellEdit("I26", None)],       # the previous WO folder's template path
        # staff email sheet: the CRF row is copied from the NCDOT CRF sheet
        # for THIS countermeasure; the previous one is cleared
        "For NCDOT staff - Email": [CellEdit(ref, None) for ref in
                                    constant_cells(source, "For NCDOT staff - Email", 3)],
    }
    xlsx_patch(source, out, edits=edits, replace_members=replace_members)
    if do_recalc:
        ok = recalc(out, timeout=600)
        print("LibreOffice recalc:", "done" if ok else "not available (Excel recalculates on open)")
    division = county_division(out, ASSUMPTIONS["D11"])
    set_cached(out, {cell: division for cell in DIVISION_CELLS})
    print(f"Division cache set to {division} on {len(DIVISION_CELLS)} XLOOKUP-dependent cells")
    stale = excel_only_cells(out) - set(DIVISION_CELLS)
    print(f"cleared {clear_cached(out, stale)} Excel-only caches (recomputed by Excel on open)")
    media = {m for _, (_, ms) in STALE_DRAWINGS.items() for m in ms}
    drop_members(out, media)
    changed = set(STALE_DRAWINGS) | {rels for rels, _ in STALE_DRAWINGS.values()}
    rep = verify_integrity(source, out, allow_added=media | changed,
                           allow_modified=changed, allow_removed=media)
    print("integrity:", "ok" if rep.ok else rep.problems, f"({rep.checked_members} drawing/media parts)")
    if not rep.ok:
        sys.exit(1)


def main(argv=None) -> None:
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    ap.add_argument("--source", required=True)
    ap.add_argument("--out", required=True)
    ap.add_argument("--no-recalc", action="store_true")
    args = ap.parse_args(argv)
    os.makedirs(os.path.dirname(os.path.abspath(args.out)), exist_ok=True)
    build(args.source, args.out, do_recalc=not args.no_recalc)
    print("wrote", args.out)


if __name__ == "__main__":
    main()
