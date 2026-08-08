"""The Warrant sheet: the crashes in the analysis, and the warrant arithmetic.

Modelled on the SN24 sheet in NCDOT's own warrants workbook: the crash table on
the left, the calculation block to the right.

This sheet exists so the conditional formatting has somewhere to live where it
cannot be wrong. On the working fiche sheet the highlight has an extent, and
the extent has to be adjusted every time a determination changes: a crash moving
from NIS to DEL, or a limit shifting, silently leaves the highlight covering the
wrong rows. Here **every row is in the analysis by construction**, so the rule
covers the whole table and there is nothing to maintain.

The ranges match the warrant rather than the eye: C in {2, 3} is wet and L in
{4, 5, 6} is dark, both wider than the highlight originally used on the working
sheet (docs/12).
"""
from __future__ import annotations

from openpyxl.formatting.rule import CellIsRule, Rule
from openpyxl.styles import Alignment, Font, PatternFill
from openpyxl.styles.differential import DifferentialStyle
from openpyxl.utils import get_column_letter

from .fiche_workbook import DATE_FORMAT, autofit_columns
from .warrants import (DARK_CODES, MULTILANE_ROR_TYPES, ROR_TYPES, WET_CODES,
                       Crash, screen_section)

SHEET_WARRANT = "Warrant"

#: Column layout, matching SN24 in the NCDOT warrants workbook.
COLUMNS = ["#", "MP", "Crash ID", "Date", "T", "C", "F", "L", "S", "Type",
           "Dir", "Comment"]
_COL = {name: i + 1 for i, name in enumerate(COLUMNS)}

FILL_WARRANT = PatternFill("solid", bgColor="FFEB9C")
FILL_HEAD = PatternFill("solid", fgColor="D9D9D9")

#: Where the calculation block starts (one blank column after the table).
_CALC = len(COLUMNS) + 2


def _highlight(ws, last_row: int, multilane: bool = False) -> None:
    """Wet C, dark L and ROR Types, over the whole table.

    SSSD is highlighted only when ``multilane`` is on, matching the warrant:
    highlighting a type that does not count would overstate the ROR share to
    anyone reading the sheet.
    """
    if last_row < 2:
        return
    for name, codes in (("C", WET_CODES), ("L", DARK_CODES)):
        letter = get_column_letter(_COL[name])
        ws.conditional_formatting.add(
            f"{letter}2:{letter}{last_row}",
            CellIsRule(operator="between",
                       formula=[str(min(codes) - 0.9), str(max(codes) + 0.9)],
                       fill=FILL_WARRANT))
    letter = get_column_letter(_COL["Type"])
    rng = f"{letter}2:{letter}{last_row}"
    style = DifferentialStyle(fill=FILL_WARRANT)
    names = ROR_TYPES | MULTILANE_ROR_TYPES if multilane else ROR_TYPES
    for i, name in enumerate(sorted(names)):
        rule = Rule(type="containsText", operator="containsText", text=name,
                    dxf=style, priority=i + 1)
        rule.formula = [f'NOT(ISERROR(SEARCH("{name}",{letter}2)))']
        ws.conditional_formatting.add(rng, rule)


def add_warrant_sheet(wb, rows, length_mi: float, facility: str = "freeway",
                      multilane: bool = False, lo=None, hi=None):
    """Build the Warrant sheet from the in-study crash rows.

    ``rows`` are dicts carrying at least ``mp``, ``crash_id``, ``t``, ``c``,
    ``f``, ``l``, ``s``, ``type``; ``dir`` and ``comment`` are optional. A row
    may carry ``fills``, a mapping of column name to hex colour, for values the
    engineer overrode by hand: the analysis uses the corrected value and the
    solid fill marks it as an engineering call rather than TEAAS data. The
    original stays on the fiche sheet.
    Returns ``(worksheet, SectionScreen)``.
    """
    if SHEET_WARRANT in wb.sheetnames:
        del wb[SHEET_WARRANT]
    ws = wb.create_sheet(SHEET_WARRANT)

    for i, name in enumerate(COLUMNS, start=1):
        cell = ws.cell(row=1, column=i, value=name)
        cell.font = Font(bold=True)
        cell.fill = FILL_HEAD
        cell.alignment = Alignment(horizontal="center")

    ordered = sorted(rows, key=lambda r: (r.get("mp") is None, r.get("mp") or 0))
    for n, r in enumerate(ordered, start=1):
        i = n + 1
        ws.cell(row=i, column=_COL["#"], value=n)
        for key, name in (("mp", "MP"), ("crash_id", "Crash ID"),
                          ("date", "Date"), ("t", "T"), ("c", "C"),
                          ("f", "F"), ("l", "L"), ("s", "S"),
                          ("type", "Type"), ("dir", "Dir"),
                          ("comment", "Comment")):
            v = r.get(key)
            if v is not None and v != "":
                cell = ws.cell(row=i, column=_COL[name], value=v)
                if name == "Date":
                    cell.number_format = DATE_FORMAT
                colour = (r.get("fills") or {}).get(name)
                if colour:
                    cell.fill = PatternFill("solid", fgColor=colour)
    last = len(ordered) + 1
    _highlight(ws, last, multilane)
    ws.freeze_panes = "A2"

    crashes = [Crash(crash_id=str(r.get("crash_id", "")),
                     crash_type=str(r.get("type") or ""),
                     road_condition=r.get("c") if isinstance(r.get("c"), int) else None,
                     light_condition=r.get("l") if isinstance(r.get("l"), int) else None)
               for r in ordered]
    screen = screen_section(crashes, length_mi, facility, multilane=multilane)
    _write_summary(ws, screen, facility, multilane, lo, hi)
    autofit_columns(ws)
    return ws, screen


def _write_summary(ws, s, facility, multilane, lo, hi) -> None:
    """The calculation block, to the right of the table (SN24 does the same)."""
    c, v = _CALC, _CALC + 1

    def put(row, label, value, bold=False, pct=False):
        a = ws.cell(row=row, column=c, value=label)
        b = ws.cell(row=row, column=v, value=value)
        if bold:
            a.font = b.font = Font(bold=True)
        if pct:
            b.number_format = "0%"

    put(1, "Facility Type", facility.upper(), bold=True)
    if lo is not None:
        put(2, "MP Begin", lo)
        put(3, "MP End", hi)
    put(4, "Length (miles)", round(s.length_mi, 3))
    put(5, "Multi-lane (SSSD counts as ROR)", "Yes" if multilane else "No")
    put(6, "Total", s.total)
    put(7, "Animal crashes deleted", s.animal_excluded)
    put(8, "Crashes/Mile", round(s.rate, 1))
    put(9, f"Min # Crashes ({s.min_total}) Met?",
        "Yes" if s.total > s.min_total else "No")
    put(10, f"Min Crashes/Mile ({s.min_rate}) Met?",
        "Yes" if s.rate > s.min_rate else "No")

    row = 12
    put(row, "Warrant", "Met?", bold=True)
    for wr in s.warrants:
        row += 1
        ws.cell(row=row, column=c, value=f"{wr.warrant}  {wr.description}")
        ws.cell(row=row, column=v, value="Yes" if wr.met else "No")
        ws.cell(row=row, column=v + 1,
                value=f"{wr.count}/{wr.total} = {wr.share:.0%} "
                      f"(needs {wr.threshold:.0%})")
