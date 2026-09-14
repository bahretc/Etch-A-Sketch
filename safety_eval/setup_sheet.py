"""Populate the Evaluation Set-up sheet (Date Range + AADT calculators).

Cell addresses are DETECTED from labels in the template (CLAUDE.md rule 8),
not hardcoded. Verified against the 2023-12-04 templates and the completed
SS-6002AD (intersection) and 04-15-39049 (section) workbooks:

Intersection variant
    D4 TEAAS date; D5 construction months; D9:E11 period date overrides;
    N5/N6 representative years; year table rows keyed by column K
    (Major legs L/M, Minor legs O/P).

Section variant
    D4 TEAAS date; D5 construction months; E10 construction end;
    AL5/AL6 representative years; year headers across row 16 from column O;
    sub-sections down rows 17+ (Begin MP L, End MP M).

Only actual station values should be written into the AADT tables; estimated
or interpolated years stay with the analyst (the black/red font convention in
docs/02). 2020 must never be a representative year.
"""
from __future__ import annotations

import re
import zipfile
from dataclasses import dataclass, field
from datetime import date

from .xlsx_patch import CellEdit, sheet_files, xlsx_patch

SHEET = "Evaluation Set-up"


@dataclass
class SubSection:
    begin_mp: float
    end_mp: float
    aadt_by_year: dict = field(default_factory=dict)   # {year: aadt}


@dataclass
class SetupData:
    teaas_date: date | None = None
    construction_months: int | None = None
    construction_start: date | None = None       # intersection D10 override
    construction_end: date | None = None         # section E10
    before_period_start: date | None = None      # intersection D9 override
    rep_before_year: int | None = None
    rep_after_year: int | None = None
    # intersection: {year: {"leg1": v, "leg2": v, "leg3": v, "leg4": v}}
    legs_by_year: dict = field(default_factory=dict)
    # section: ordered sub-sections
    subsections: list = field(default_factory=list)


# --------------------------------------------------------------------------- #
# sheet scanning
# --------------------------------------------------------------------------- #
_CELL_RE = re.compile(
    r'<c r="([A-Z]+)(\d+)"([^>]*)>(?:<is><t[^>]*>(.*?)</t></is>|<v>(.*?)</v>)</c>',
    re.S)


def _col_index(col: str) -> int:
    n = 0
    for ch in col:
        n = n * 26 + ord(ch) - 64
    return n


def _col_letter(n: int) -> str:
    s = ""
    while n:
        n, r = divmod(n - 1, 26)
        s = chr(65 + r) + s
    return s


def _scan_sheet(template: str, sheet: str = SHEET) -> dict[tuple[str, int], str]:
    """(col, row) -> cell text/value for every non-empty non-formula cell."""
    name_to_file = sheet_files(template)
    if sheet not in name_to_file:
        raise KeyError(f"Template has no {sheet!r} sheet")
    with zipfile.ZipFile(template) as z:
        xml = z.read(name_to_file[sheet]).decode("utf-8")
        try:
            sst = z.read("xl/sharedStrings.xml").decode("utf-8")
            strings = [re.sub(r"<[^>]+>", "", m)
                       for m in re.findall(r"<si>(.*?)</si>", sst, re.S)]
        except KeyError:
            strings = []
    cells: dict[tuple[str, int], str] = {}
    for m in _CELL_RE.finditer(xml):
        col, row, attrs, inline, v = m.groups()
        text = inline
        if text is None and v is not None:
            text = strings[int(v)] if ('t="s"' in attrs and v.isdigit()
                                       and int(v) < len(strings)) else v
        if text is not None:
            cells[(col, int(row))] = text.strip()
    return cells


def _find_label(cells: dict, pattern: str) -> tuple[str, int] | None:
    rx = re.compile(pattern, re.I | re.S)
    for (col, row), text in cells.items():
        if rx.search(re.sub(r"\s+", " ", text)):
            return col, row
    return None


def _value_cell_right(cells: dict, label: tuple[str, int],
                      max_offset: int = 6) -> str | None:
    """Cell right of a label that holds (or held) its value: first cell with a
    numeric/sample value; falls back to the next column."""
    col, row = label
    start = _col_index(col)
    for off in range(1, max_offset + 1):
        cand = _col_letter(start + off)
        if (cand, row) in cells:
            return f"{cand}{row}"
    return f"{_col_letter(start + 1)}{row}"


# --------------------------------------------------------------------------- #
# populate
# --------------------------------------------------------------------------- #
def detect_variant(cells: dict) -> str:
    if _find_label(cells, r"Section AADT Calculator"):
        return "section"
    return "intersection"


def build_setup_edits(template: str, data: SetupData) -> list[CellEdit]:
    cells = _scan_sheet(template)
    variant = detect_variant(cells)
    edits: list[CellEdit] = []

    def _set(ref: str | None, value):
        if ref and value is not None:
            edits.append(CellEdit(ref, value))

    lbl = _find_label(cells, r"Most recent TEAAS date")
    if lbl:
        _set(_value_cell_right(cells, lbl, 1), data.teaas_date)
    lbl = _find_label(cells, r"Construction Period Length")
    if lbl:
        _set(_value_cell_right(cells, lbl, 1), data.construction_months)

    # period-date overrides (row located by its label in the period table)
    for label_rx, attr, col_off in (
        (r"^Before Period$", "before_period_start", 1),
        (r"^Construction Period$", "construction_start", 1),
        (r"^Construction Period$", "construction_end", 2),
    ):
        value = getattr(data, attr)
        if value is None:
            continue
        lbl = _find_label(cells, label_rx)
        if lbl:
            col, row = lbl
            _set(f"{_col_letter(_col_index(col) + col_off)}{row}", value)

    lbl = _find_label(cells, r"Select Before Period Year")
    if lbl:
        _set(_value_cell_right(cells, lbl), data.rep_before_year)
    lbl = _find_label(cells, r"Select After Period Year")
    if lbl:
        _set(_value_cell_right(cells, lbl), data.rep_after_year)

    if data.rep_before_year == 2020 or data.rep_after_year == 2020:
        raise ValueError("2020 must not be a representative AADT year (COVID; docs/02).")

    if variant == "intersection" and data.legs_by_year:
        edits.extend(_intersection_aadt_edits(cells, data))
    if variant == "section" and data.subsections:
        edits.extend(_section_aadt_edits(cells, data))
    return edits


def _intersection_aadt_edits(cells: dict, data: SetupData) -> list[CellEdit]:
    """Year rows keyed by a column of consecutive year values (col K).

    The template ships with sample leg volumes; every leg cell in the table is
    cleared first so leftovers cannot pollute averages, then actual values are
    written. Estimated/interpolated years stay with the analyst.
    """
    counts: dict[str, list[tuple[int, int]]] = {}
    for (col, row), text in cells.items():
        if re.fullmatch(r"(19|20)\d{2}", text):
            counts.setdefault(col, []).append((int(text), row))
    if not counts:
        return []
    year_col, pairs = max(counts.items(), key=lambda kv: len(kv[1]))
    row_of_year = {y: r for y, r in pairs}
    base = _col_index(year_col)
    leg_cols = {  # offsets from the year column (K -> L,M,O,P)
        "leg1": _col_letter(base + 1), "leg2": _col_letter(base + 2),
        "leg3": _col_letter(base + 4), "leg4": _col_letter(base + 5),
    }
    planned: dict[str, object] = {}
    for row in row_of_year.values():
        for col in leg_cols.values():
            planned[f"{col}{row}"] = None
    for year, legs in sorted(data.legs_by_year.items()):
        row = row_of_year.get(int(year))
        if row is None:
            continue
        for leg, value in legs.items():
            if leg in leg_cols and value is not None:
                planned[f"{leg_cols[leg]}{row}"] = value
    return [CellEdit(ref, value) for ref, value in planned.items()]


def _section_aadt_edits(cells: dict, data: SetupData) -> list[CellEdit]:
    """Year headers across one row; sub-sections down rows below it."""
    counts: dict[int, list[tuple[int, str]]] = {}
    for (col, row), text in cells.items():
        if re.fullmatch(r"(19|20)\d{2}", text):
            counts.setdefault(row, []).append((int(text), col))
    if not counts:
        return []
    header_row, pairs = max(counts.items(), key=lambda kv: len(kv[1]))
    col_of_year = {y: c for y, c in pairs}
    lbl = _find_label(cells, r"^Begin MP$")
    if lbl is None:
        return []
    begin_col, label_row = lbl
    end_col = _col_letter(_col_index(begin_col) + 1)
    num_col = _col_letter(_col_index(begin_col) - 1)   # the '#' column

    # table extent: consecutive numbered rows below the header
    table_rows: list[int] = []
    row = label_row + 1
    while (num_col, row) in cells and cells[(num_col, row)].isdigit():
        table_rows.append(row)
        row += 1
    if not table_rows:
        table_rows = list(range(label_row + 1, label_row + 1 + len(data.subsections)))
    if len(data.subsections) > len(table_rows):
        raise ValueError(
            f"{len(data.subsections)} sub-sections but the template table has "
            f"only {len(table_rows)} rows.")

    # clear the whole table (template sample data), then write actual values
    planned: dict[str, object] = {}
    for r in table_rows:
        planned[f"{begin_col}{r}"] = None
        planned[f"{end_col}{r}"] = None
        for col in col_of_year.values():
            planned[f"{col}{r}"] = None
    for i, sub in enumerate(data.subsections):
        r = table_rows[i]
        planned[f"{begin_col}{r}"] = sub.begin_mp
        planned[f"{end_col}{r}"] = sub.end_mp
        for year, aadt in sorted(sub.aadt_by_year.items()):
            col = col_of_year.get(int(year))
            if col and aadt is not None:
                planned[f"{col}{r}"] = aadt
    return [CellEdit(ref, value) for ref, value in planned.items()]


def load_setup_yaml(path: str) -> SetupData:
    """Load a SetupData YAML, e.g.::

        teaas_date: 2026-05-31
        construction_months: 14
        construction_end: 2021-06-30
        rep_before_year: 2018
        rep_after_year: 2024
        subsections:                    # section workbooks
          - begin_mp: 17.691
            end_mp: 17.811
            aadt: {2012: 3600, 2013: 4100, 2016: 5600, 2018: 8100}
        legs_by_year:                   # intersection workbooks
          2018: {leg1: 1500, leg3: 400}
    """
    import yaml

    from .assignment import _as_date

    with open(path) as fh:
        d = yaml.safe_load(fh) or {}
    subs = [SubSection(begin_mp=float(s["begin_mp"]), end_mp=float(s["end_mp"]),
                       aadt_by_year={int(k): v for k, v in (s.get("aadt") or {}).items()})
            for s in d.get("subsections", []) or []]
    return SetupData(
        teaas_date=_as_date(d.get("teaas_date")),
        construction_months=(int(d["construction_months"])
                             if d.get("construction_months") is not None else None),
        construction_start=_as_date(d.get("construction_start")),
        construction_end=_as_date(d.get("construction_end")),
        before_period_start=_as_date(d.get("before_period_start")),
        rep_before_year=(int(d["rep_before_year"])
                         if d.get("rep_before_year") is not None else None),
        rep_after_year=(int(d["rep_after_year"])
                        if d.get("rep_after_year") is not None else None),
        legs_by_year={int(y): dict(v) for y, v in (d.get("legs_by_year") or {}).items()},
        subsections=subs,
    )


def populate_setup_sheet(template: str, output: str, data: SetupData,
                         extra_edits: dict | None = None) -> None:
    """Write the Set-up values into a copy of ``template`` (docs/06 rules).

    ``extra_edits`` merges additional per-sheet edits (e.g. Before/After crash
    rows from :mod:`eval_workbook`) into the same single-pass patch.
    """
    edits = {SHEET: build_setup_edits(template, data)}
    for sheet, sheet_edits in (extra_edits or {}).items():
        edits.setdefault(sheet, []).extend(sheet_edits)
    xlsx_patch(template, output, edits=edits)
