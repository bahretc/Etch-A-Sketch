"""Populate the real NCDOT Evaluation Workbook template (docs/02, docs/06).

Writes ONLY the manually-edited columns A-M of the Before and After sheets
(A Crash ID, B Date, C T, D C, E F, F L, G S, H-K analyst notes, L Target-1?,
M Target-2?), letting the template's live formulas compute the KABCO/SI blocks.
The EB/CMF tracking section and everything else in the template is untouched.
"""
from __future__ import annotations

import re
import zipfile

from .models import Crash
from .xlsx_patch import CellEdit, sheet_files, verify_integrity, xlsx_patch

DATA_START_ROW = 4          # header row 3, data from row 4 (docs/02, verified)
MANUAL_COLS = list("ABCDEFGHIJKLM")

def last_manual_data_row(template: str, sheet: str) -> int:
    """Highest row with a VALUE in manual columns A-M (template sample data).

    The template ships with sample evaluation data that must be fully cleared;
    hardcoding a clear range undercounts when samples run long (the 2023-12-04
    intersection template has sample rows past row 400).
    """
    name_to_file = sheet_files(template)
    with zipfile.ZipFile(template) as z:
        xml = z.read(name_to_file[sheet]).decode("utf-8")
    last = DATA_START_ROW
    for m in re.finditer(r'<c r="([A-M])(\d+)"[^>]*>(?:<v>|<is>)', xml):
        row = int(m.group(2))
        if row >= DATA_START_ROW:
            last = max(last, row)
    return last


def _crash_row_edits(row: int, crash: Crash, target1: bool, target2: bool | None) -> list[CellEdit]:
    """Column A-M edits for one crash row. Numeric codes stay numeric, matching
    the template's storage (verified on the 2023-12-04 template: A and C-F are
    numbers, B a date serial, G a string)."""
    def num(v):
        return int(v) if v is not None else None

    edits = [
        CellEdit(f"A{row}", int(crash.crash_id) if crash.crash_id.isdigit() else crash.crash_id),
        CellEdit(f"B{row}", crash.date),
        CellEdit(f"C{row}", num(crash.t)),
        CellEdit(f"D{row}", num(crash.c)),
        CellEdit(f"E{row}", num(crash.f)),
        CellEdit(f"F{row}", num(crash.l)),
        CellEdit(f"G{row}", crash.s or None),
        CellEdit(f"L{row}", "Y" if target1 else None),
        # Target-2? stays blank everywhere when a single target is defined
        # (docs/02); writing None also clears template sample values.
        CellEdit(f"M{row}", "Y" if target2 else None),
    ]
    return edits


def _clear_row_edits(row: int, include_m: bool) -> list[CellEdit]:
    cols = MANUAL_COLS if include_m else [c for c in MANUAL_COLS if c != "M"]
    return [CellEdit(f"{c}{row}", None) for c in cols]


def populate_evaluation_workbook(
    template: str,
    output: str,
    before: list[Crash],
    after: list[Crash],
    target1_name: str | None = None,
    target2_name: str | None = None,
    clear_rows_through: int | None = None,
    verify: bool = True,
):
    """Fill Before/After sheets of a copy of ``template`` and verify integrity.

    ``target1_name`` / ``target2_name`` select which entry of each crash's
    ``target_types`` list drives the Target-1?/Target-2? flags.  With
    ``target2_name`` None the M column is left blank everywhere (single-target
    evaluation per docs/02).

    ``clear_rows_through`` clears leftover template sample values in columns
    A-M below the data (formulas from column O onward are never touched).
    When None, the used range of each sheet's manual columns is auto-detected
    so every sample row is cleared.
    """
    names = sheet_files(template)
    for required in ("Before", "After"):
        if required not in names:
            raise KeyError(f"Template has no '{required}' sheet: {sorted(names)}")

    two_targets = target2_name is not None

    def _sheet_edits(sheet: str, crashes: list[Crash]) -> list[CellEdit]:
        clear_through = (clear_rows_through if clear_rows_through is not None
                         else last_manual_data_row(template, sheet))
        edits: list[CellEdit] = []
        row = DATA_START_ROW
        for crash in sorted(crashes, key=lambda c: (c.date or __import__("datetime").date.min, c.crash_id)):
            t1 = bool(target1_name and target1_name in crash.target_types)
            t2 = (target2_name in crash.target_types) if two_targets else None
            edits.extend(_crash_row_edits(row, crash, t1, t2))
            row += 1
        for clear_row in range(row, clear_through + 1):
            edits.extend(_clear_row_edits(clear_row, include_m=True))
        return edits

    xlsx_patch(
        template, output,
        edits={"Before": _sheet_edits("Before", before),
               "After": _sheet_edits("After", after)},
        style_rows={"Before": DATA_START_ROW, "After": DATA_START_ROW},
    )
    if verify:
        report = verify_integrity(template, output)
        if not report.ok:
            raise RuntimeError(
                "Template integrity verification FAILED:\n  "
                + "\n  ".join(report.problems))
        return report
    return None
