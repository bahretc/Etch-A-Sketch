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
                       Crash, best_windows, scan_sections, screen_section)

SHEET_WARRANT = "Warrant"

#: Column layout, matching SN24 in the NCDOT warrants workbook.
COLUMNS = ["#", "MP", "Crash ID", "Date", "T", "C", "F", "L", "S", "Type",
           "Dir", "Comment"]
_COL = {name: i + 1 for i, name in enumerate(COLUMNS)}

#: One colour per warrant input, so the columns read apart at a glance and
#: yellow stays free. Wet C light blue, dark L lavender, ROR Type pale orange.
FILL_WET = PatternFill("solid", bgColor="DDEBF7")
FILL_DARK = PatternFill("solid", bgColor="E4DFEC")
FILL_ROR = PatternFill("solid", bgColor="FCE4D6")
FILL_HEAD = PatternFill("solid", fgColor="D9D9D9")

#: Yellow is RESERVED for a value the engineer overrode by hand, and appears
#: nowhere else on the sheet, so the one changed cell is findable on sight.
#: The override cell is also EXCLUDED from the column's conditional formatting,
#: because Excel paints a matching rule over a direct fill: without the carve-
#: out the yellow would be hidden under the very highlight it must stand out
#: from, which is exactly the bug this replaced.
OVERRIDE_COLOUR = "FFFF00"

#: Value column for the summary block: Date, the widest table column, so
#: numbers never render as ####.
_VAL = _COL["Date"]


def _ranges(letter: str, last_row: int, skip_rows) -> str:
    """``H2:H40`` minus the skipped rows, as a space-separated sqref."""
    rows = [r for r in range(2, last_row + 1) if r not in skip_rows]
    parts, i = [], 0
    while i < len(rows):
        j = i
        while j + 1 < len(rows) and rows[j + 1] == rows[j] + 1:
            j += 1
        parts.append(f"{letter}{rows[i]}" if i == j
                     else f"{letter}{rows[i]}:{letter}{rows[j]}")
        i = j + 1
    return " ".join(parts)


def _highlight(ws, last_row: int, multilane: bool = False, skip=()) -> None:
    """Wet C, dark L and ROR Types, one colour per column.

    ``skip`` holds ``(column name, row)`` cells carved out of the rules:
    engineer-overridden cells keep their direct yellow instead of being painted
    over. SSSD is highlighted only when ``multilane`` is on, matching the
    warrant: highlighting a type that does not count would overstate the ROR
    share to anyone reading the sheet.
    """
    if last_row < 2:
        return
    for name, codes, fill in (("C", WET_CODES, FILL_WET),
                              ("L", DARK_CODES, FILL_DARK)):
        letter = get_column_letter(_COL[name])
        rng = _ranges(letter, last_row,
                      {r for col, r in skip if col == name})
        if rng:
            ws.conditional_formatting.add(rng, CellIsRule(
                operator="between",
                formula=[str(min(codes) - 0.9), str(max(codes) + 0.9)],
                fill=fill))
    letter = get_column_letter(_COL["Type"])
    rng = _ranges(letter, last_row, {r for col, r in skip if col == "Type"})
    style = DifferentialStyle(fill=FILL_ROR)
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
    overridden = set()
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
                    overridden.add((name, i))
    last = len(ordered) + 1
    _highlight(ws, last, multilane, skip=overridden)
    ws.freeze_panes = "A2"

    crashes = [Crash(crash_id=str(r.get("crash_id", "")),
                     crash_type=str(r.get("type") or ""),
                     road_condition=r.get("c") if isinstance(r.get("c"), int) else None,
                     light_condition=r.get("l") if isinstance(r.get("l"), int) else None)
               for r in ordered]
    screen = screen_section(crashes, length_mi, facility, multilane=multilane)
    placed = [(r.get("mp"), c) for r, c in zip(ordered, crashes)]
    windows = best_windows(scan_sections(placed, facility, multilane=multilane),
                           limit=8)
    _write_summary(ws, screen, facility, multilane, lo, hi, last, windows)
    # Widths come from the crash table alone: the summary sits below it, and
    # its long labels must spill across empty cells, not set column widths.
    autofit_columns(ws, last_row=last)
    return ws, screen


def _array(names) -> str:
    """An Excel array constant of quoted names, sorted for stable output."""
    return "{" + ",".join(f'"{n}"' for n in sorted(names)) + "}"


def _write_summary(ws, s, facility, multilane, lo, hi, last_row: int,
                   windows) -> None:
    """The calculation block, BELOW the crash table, in live Excel formulas.

    Below rather than beside: comment text spills rightward and a side block
    sits on top of it, slicing the comments and burying the numbers. Under the
    table nothing collides, and the whole sheet prints and pastes as one
    column.

    Live formulas rather than Python-computed values is the project's hard
    rule (CLAUDE.md #4): a reviewer must be able to trace every number, and an
    engineer who edits a code must see the warrant answer move. The formulas
    mirror NCDOT's own warrants workbook (COUNTIFS for wet and dark,
    exact-match COUNTIF over the ROR list, shares ROUNDed to two places
    BEFORE the >= test).
    """
    tab = f"2:{last_row}"                       # the crash table's data rows
    C_ID, C_C, C_L, C_TY = "C", "F", "H", "J"
    ror = _array(ROR_TYPES | (MULTILANE_ROR_TYPES if multilane else set()))
    V = get_column_letter(_VAL)

    r = last_row + 2
    cells = {}

    def title(text):
        nonlocal r
        cell = ws.cell(row=r, column=1, value=text)
        cell.font = Font(bold=True)
        for c in range(1, 7):
            ws.cell(row=r, column=c).fill = FILL_HEAD
        r += 1

    def put(label, value, fmt=None, key=None):
        nonlocal r
        ws.cell(row=r, column=1, value=label)
        cell = ws.cell(row=r, column=_VAL, value=value)
        if fmt:
            cell.number_format = fmt
        if key:
            cells[key] = f"{V}{r}"
        r += 1

    title("Warrant Summary")
    put("Facility Type", facility.upper())
    if lo is not None:
        put("MP Begin", lo, "0.000", key="lo")
        put("MP End", hi, "0.000", key="hi")
        put("Length (miles)", f"={cells['hi']}-{cells['lo']}", "0.000",
            key="len")
    else:
        put("Length (miles)", round(s.length_mi, 3), "0.000", key="len")
    if multilane:
        put("Multi-lane (SSSD counts as ROR)", "Yes")
    put("Total Crashes", f"=COUNT({C_ID}{tab.replace(':', f':{C_ID}')})",
        key="total")
    put("Crashes/Mile", f"=ROUND({cells['total']}/{cells['len']},1)", "0.0",
        key="rate")
    put(f"Min # Crashes ({s.min_total}) Met?",
        f'=IF({cells["total"]}>{s.min_total},"Yes","No")', key="m1")
    put(f"Min Crashes/Mile ({s.min_rate}) Met?",
        f'=IF({cells["rate"]}>{s.min_rate},"Yes","No")', key="m2")
    r += 1

    rng = lambda col: f"{col}2:{col}{last_row}"
    put("ROR Crashes", f"=SUMPRODUCT(COUNTIF({rng(C_TY)},{ror}))", key="ror")
    put("% ROR", f"=ROUND({cells['ror']}/{cells['total']},2)", "0%",
        key="p_ror")
    put("Wet Crashes",
        f'=COUNTIFS({rng(C_C)},">=2",{rng(C_C)},"<=3")', key="wet")
    put("% Wet", f"=ROUND({cells['wet']}/{cells['total']},2)", "0%",
        key="p_wet")
    put("Wet ROR Crashes",
        f"=SUMPRODUCT(({rng(C_C)}>=2)*({rng(C_C)}<=3)"
        f"*ISNUMBER(MATCH({rng(C_TY)},{ror},0)))", key="wetror")
    put("% Wet ROR", f"=ROUND({cells['wetror']}/{cells['total']},2)", "0%",
        key="p_wetror")
    put("Night Crashes",
        f'=COUNTIFS({rng(C_L)},">=4",{rng(C_L)},"<=6")', key="night")
    put("% Night", f"=ROUND({cells['night']}/{cells['total']},2)", "0%",
        key="p_night")
    if any(w.warrant == "N-4" for w in s.warrants):
        from .warrants import INTERSECTION_TYPES
        put("Non-Intersection Crashes",
            f"={cells['total']}-SUMPRODUCT(COUNTIF({rng(C_TY)},"
            f"{_array(INTERSECTION_TYPES)}))", key="nonint")
        put("Night ROR Crashes",
            f"=SUMPRODUCT(({rng(C_L)}>=4)*({rng(C_L)}<=6)"
            f"*ISNUMBER(MATCH({rng(C_TY)},{ror},0)))", key="nightror")
        put("% Night ROR of Non-Int",
            f"=ROUND({cells['nightror']}/{cells['nonint']},2)", "0%",
            key="p_n4")
    r += 1

    share_of = {"1": "p_wetror", "2": "p_ror", "3": "p_wet", "4": "p_night"}
    ws.cell(row=r, column=1, value="Warrant").font = Font(bold=True)
    ws.cell(row=r, column=_VAL, value="Met?").font = Font(bold=True)
    r += 1
    for w in s.warrants:
        pkey = "p_n4" if w.warrant == "N-4" else share_of[w.warrant[-1]]
        ws.cell(row=r, column=1,
                value=f"{w.warrant}  {w.description} ({w.threshold:.0%})")
        ws.cell(row=r, column=_VAL,
                value=f'=IF(AND({cells["m1"]}="Yes",{cells["m2"]}="Yes",'
                      f'{cells[pkey]}>={w.threshold}),"Yes","No")')
        r += 1
    r += 1

    title("Sub-sections Meeting Warrants")
    if not windows:
        ws.cell(row=r, column=1, value="None at the minimum section length.")
        r += 1
    for win in windows:
        met = ", ".join(win.names)
        ws.cell(row=r, column=1,
                value=f"MP {win.lo:.3f} to {win.hi:.3f}: {win.screen.total} "
                      f"crashes, {win.screen.rate:.1f} per mile, meets {met}")
        r += 1
