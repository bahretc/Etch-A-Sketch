"""Populate the real NCDOT Evaluation Workbook templates (docs/02, docs/06).

Writes ONLY the manually-edited columns of the Before and After sheets, letting
the template's live formulas compute the KABCO/SI blocks. The column layout is
DETECTED from the template's header row (CLAUDE.md rule 8: the template is
ground truth; versions drift), which transparently supports both layouts:

* Intersection: A Crash ID, B Date, C-G T/C/F/L/S, H-K notes, L/M Target-1?/2?
* Section:      A Crash ID, B Date, C-G T/C/F/L/S, H Final MP, I-L notes,
                M/N Target-1?/2?

Crashes are written in INPUT ORDER (the completed 04-15-39049 workbook follows
the TEAAS ID-list order, not date order). The EB/CMF tracking section and
everything else in the template is untouched.
"""
from __future__ import annotations

import re
import zipfile

from .models import Crash
from .xlsx_patch import CellEdit, sheet_files, verify_integrity, xlsx_patch

HEADER_ROW = 3
DATA_START_ROW = 4          # header row 3, data from row 4 (docs/02, verified)

# header label (lowercased) -> logical field
_HEADER_FIELDS = {
    "crash id": "crash_id",
    "date": "date",
    "t": "t", "c": "c", "f": "f", "l": "l", "s": "s",
    "final mp": "final_mp",
    "target-1?": "target1",
    "target-2?": "target2",
}


def _shared_strings(z: zipfile.ZipFile) -> list[str]:
    try:
        xml = z.read("xl/sharedStrings.xml").decode("utf-8")
    except KeyError:
        return []
    return [re.sub(r"<[^>]+>", "", m)
            for m in re.findall(r"<si>(.*?)</si>", xml, re.S)]


def sheet_layout(template: str, sheet: str) -> dict[str, str]:
    """Detect field -> column letter from the sheet's header row.

    Notes columns are every column between the last coded field and Target-1?.
    """
    name_to_file = sheet_files(template)
    with zipfile.ZipFile(template) as z:
        xml = z.read(name_to_file[sheet]).decode("utf-8")
        strings = _shared_strings(z)

    m = re.search(rf'<row r="{HEADER_ROW}"[^>]*>(.*?)</row>', xml, re.S)
    if not m:
        raise ValueError(f"No header row {HEADER_ROW} in sheet {sheet!r}")
    layout: dict[str, str] = {}
    for cm in re.finditer(
            r'<c r="([A-Z]+)\d+"([^>]*)>(?:<is><t[^>]*>(.*?)</t></is>|<v>(.*?)</v>)</c>',
            m.group(1), re.S):
        col, attrs, inline, v = cm.groups()
        text = inline
        if text is None and 't="s"' in attrs and v is not None:
            idx = int(v)
            text = strings[idx] if idx < len(strings) else ""
        if text is None:
            continue
        field = _HEADER_FIELDS.get(text.strip().lower())
        if field and field not in layout:
            layout[field] = col
    missing = {"crash_id", "date", "t", "s", "target1"} - set(layout)
    if missing:
        raise ValueError(
            f"Sheet {sheet!r} header row lacks expected columns: {sorted(missing)}")
    return layout


def _manual_columns(layout: dict[str, str]) -> list[str]:
    """All manually-edited columns: crash_id through target2 inclusive."""
    def idx(col):
        n = 0
        for ch in col:
            n = n * 26 + ord(ch) - 64
        return n

    def letter(n):
        s = ""
        while n:
            n, r = divmod(n - 1, 26)
            s = chr(65 + r) + s
        return s

    first = idx(layout["crash_id"])
    last = idx(layout.get("target2", layout["target1"]))
    return [letter(i) for i in range(first, last + 1)]


def _crash_row_edits(row: int, crash: Crash, layout: dict[str, str],
                     target1: bool, target2: bool | None) -> list[CellEdit]:
    """Edits for one crash row. Numeric codes stay numeric, matching template
    storage (verified: A and C-F numeric, B a date serial, G a string)."""
    def num(v):
        return int(v) if v is not None else None

    edits = [
        CellEdit(f"{layout['crash_id']}{row}",
                 int(crash.crash_id) if crash.crash_id.isdigit() else crash.crash_id),
        CellEdit(f"{layout['date']}{row}", crash.date),
        CellEdit(f"{layout['t']}{row}", num(crash.t)),
        CellEdit(f"{layout['c']}{row}", num(crash.c)),
        CellEdit(f"{layout['f']}{row}", num(crash.f)),
        CellEdit(f"{layout['l']}{row}", num(crash.l)),
        CellEdit(f"{layout['s']}{row}", crash.s or None),
        CellEdit(f"{layout['target1']}{row}", "Y" if target1 else None),
    ]
    if "final_mp" in layout:
        edits.append(CellEdit(f"{layout['final_mp']}{row}", crash.mp))
    if "target2" in layout:
        # blank when a single target is defined (docs/02); writing None also
        # clears template sample values.
        edits.append(CellEdit(f"{layout['target2']}{row}", "Y" if target2 else None))
    return edits


def last_manual_data_row(template: str, sheet: str,
                         manual_cols: list[str]) -> int:
    """Highest row with a VALUE in the manual columns (template sample data).

    The templates ship with sample evaluation data that must be fully cleared;
    hardcoding a clear range undercounts when samples run long.
    """
    name_to_file = sheet_files(template)
    with zipfile.ZipFile(template) as z:
        xml = z.read(name_to_file[sheet]).decode("utf-8")
    colset = set(manual_cols)
    last = DATA_START_ROW
    for m in re.finditer(r'<c r="([A-Z]+)(\d+)"[^>]*>(?:<v>|<is>)', xml):
        if m.group(1) in colset:
            row = int(m.group(2))
            if row >= DATA_START_ROW:
                last = max(last, row)
    return last


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
    ``target2_name`` None the Target-2? column is cleared everywhere
    (single-target evaluation per docs/02).

    ``clear_rows_through`` clears leftover template sample values in the manual
    columns below the data; when None the used range is auto-detected.
    """
    names = sheet_files(template)
    for required in ("Before", "After"):
        if required not in names:
            raise KeyError(f"Template has no '{required}' sheet: {sorted(names)}")

    two_targets = target2_name is not None

    def _sheet_edits(sheet: str, crashes: list[Crash]) -> list[CellEdit]:
        layout = sheet_layout(template, sheet)
        manual_cols = _manual_columns(layout)
        clear_through = (clear_rows_through if clear_rows_through is not None
                         else last_manual_data_row(template, sheet, manual_cols))
        edits: list[CellEdit] = []
        row = DATA_START_ROW
        for crash in crashes:                      # input order, not sorted
            t1 = bool(target1_name and target1_name in crash.target_types)
            t2 = (target2_name in crash.target_types) if two_targets else None
            edits.extend(_crash_row_edits(row, crash, layout, t1, t2))
            row += 1
        for clear_row in range(row, clear_through + 1):
            edits.extend(CellEdit(f"{c}{clear_row}", None) for c in manual_cols)
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
