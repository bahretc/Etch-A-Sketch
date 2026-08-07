"""Assemble the study fiche workbook: OriginalFiche + ID + Initial Study + DetailedFiche.

This is the first step of a review, before any determination is made. Four
TEAAS exports arrive as CSV or pipe-delimited text and become one workbook the
engineer works in.

What "fiche formatting" actually means, read off the delivered workbooks rather
than assumed (``examples/SS-6002AD`` and ``examples/04-15-39049``):

* The fiche sheet is a **verbatim paste**. Page footers ("Page 1 of 13") and
  the repeated ``Muni. Code`` header blocks are KEPT, not stripped. docs/02
  says to strip them on ingest and that is right for *parsing*, but the sheet
  the engineer reads is the raw pull, and every delivered workbook has the
  footers still in it (SS-6002AD: rows 12, 46, 78, ... ).
* Cells are typed the way Excel types a paste: a crash ID lands as a number, a
  milepost as a float, a date as a date. Nothing is left as text that Excel
  would have converted, because the ID sheet's lookups depend on it.
* The crash header row is one column SHORT of its data rows, because
  "Miles / Dir From" is one header over two data columns. That misalignment is
  in the TEAAS export and is preserved; do not try to correct it.
* Visual formatting is almost nothing: wrap on the multi-line header cells,
  column A around 19 wide. No bold, no fill, no freeze, no autofilter.

The ID sheet is the cross-reference between the two crash lists, and its odd
column layout is a record of how the export was pasted. The pipe-delimited ID
file was split on BOTH ``|`` and whitespace, so its 5 fields land in 6 columns
(the date splits into date and time) under an 8-column header. Reproduced
exactly, because an engineer opening this next to an old workbook should not
have to notice a difference.
"""
from __future__ import annotations

import csv
import io
import os
import re
from datetime import datetime

from openpyxl import Workbook
from openpyxl.styles import Alignment

#: Sheet names, following the delivered intersection workbook, which is the
#: only example carrying all four of these sheets.
SHEET_FICHE = "Original Fiche"
SHEET_ID = "ID"
SHEET_INITIAL = "Initial Study"
SHEET_DETAILED = "DetailedFiche"

#: The ID sheet header, spread one word per cell across H:O exactly as
#: "CRASH ID|ON RD CD|SVRTY|DATE|TYPE|" lands when split on pipes and spaces.
_ID_RAW_HEADER = ("CRASH", "ID", "ON", "RD", "CD", "SVRTY", "DATE", "TYPE")
_ID_RAW_COL = 8                      # column H

_DATE_FORMATS = ("%Y-%m-%d %H:%M:%S", "%Y-%m-%d %H:%M", "%Y-%m-%d",
                 "%m/%d/%Y %H:%M:%S", "%m/%d/%Y %H:%M", "%m/%d/%Y")
_TIME_RE = re.compile(r"^\d{1,2}:\d{2}(:\d{2})?$")


def coerce(value):
    """One CSV cell as Excel would type it on paste.

    Numbers become numbers and dates become dates, because the ID sheet joins
    the two crash lists on the crash ID and a text "107206325" does not match a
    numeric one. Leading-zero strings (county code "075", route code
    "20000074") are the trap: a route code is an identifier, not a quantity,
    and must keep its width, so anything with a leading zero stays text.
    """
    if value is None:
        return None
    text = str(value).strip()
    if not text:
        return None
    if _TIME_RE.match(text):
        for fmt in ("%H:%M:%S", "%H:%M"):
            try:
                return datetime.strptime(text, fmt).time()
            except ValueError:
                pass
    for fmt in _DATE_FORMATS:
        try:
            return datetime.strptime(text, fmt)
        except ValueError:
            pass
    if re.fullmatch(r"-?\d+", text):
        if len(text.lstrip("-")) > 1 and text.lstrip("-").startswith("0"):
            return text                      # "075", "08:50" already handled
        return int(text)
    if re.fullmatch(r"-?\d*\.\d+", text):
        return float(text)
    return text


def _write_rows(ws, rows) -> int:
    """Paste rows verbatim, typed. Returns the number of rows written."""
    n = 0
    for r, row in enumerate(rows, start=1):
        for c, cell in enumerate(row, start=1):
            v = coerce(cell)
            if v is None:
                continue
            target = ws.cell(row=r, column=c, value=v)
            if isinstance(v, str) and "\n" in v:
                target.alignment = Alignment(wrap_text=True)
        n += 1
    return n


def _read_csv_rows(source) -> list:
    """CSV rows, honouring the embedded newlines TEAAS puts in header cells."""
    if hasattr(source, "read"):
        text = source.read()
    elif os.path.exists(str(source)):
        with open(source, encoding="utf-8-sig", newline="") as fh:
            text = fh.read()
    else:
        text = str(source)
    return list(csv.reader(io.StringIO(text)))


def fiche_crash_ids(rows) -> list:
    """Crash IDs from pasted fiche rows, in fiche order, deduplicated.

    The crash-ID column is located from the ``Crash ID`` header rather than
    hardcoded, because the header row is one column short of its data rows and
    the offset differs between exports.
    """
    out, seen, col = [], set(), None
    for row in rows:
        cells = [str(c or "").strip() for c in row]
        if any(c.replace("\n", " ").strip() == "Crash ID" for c in cells):
            hdr = [c.replace("\n", " ").strip() for c in cells]
            col = hdr.index("Crash ID") + 1        # data sits one column right
            continue
        if col is None or col >= len(cells):
            continue
        cid = cells[col]
        if cid.isdigit() and len(cid) >= 6 and cid not in seen:
            seen.add(cid)
            out.append(cid)
    return out


def parse_initial_ids(source) -> tuple:
    """The pipe-delimited TEAAS ID export -> (header cells, data rows).

    Split on pipes AND whitespace, which is how it was pasted: the single
    ``DATE`` field becomes a date cell and a time cell.
    """
    if hasattr(source, "read"):
        text = source.read()
    elif os.path.exists(str(source)):
        with open(source, encoding="utf-8-sig") as fh:
            text = fh.read()
    else:
        text = str(source)
    lines = [ln for ln in text.splitlines() if ln.strip()]
    if not lines:
        return list(_ID_RAW_HEADER), []
    rows = [[p for p in re.split(r"[|\s]+", ln.strip()) if p] for ln in lines[1:]]
    return list(_ID_RAW_HEADER), rows


def build_fiche_workbook(out_path, fiche_csv, initial_study_csv=None,
                         initial_id_txt=None, detailed_fiche_csv=None) -> dict:
    """Write the study workbook. Returns a per-sheet row count."""
    wb = Workbook()
    counts = {}

    ws = wb.active
    ws.title = SHEET_FICHE
    fiche_rows = _read_csv_rows(fiche_csv)
    counts[SHEET_FICHE] = _write_rows(ws, fiche_rows)
    ws.column_dimensions["A"].width = 18.9
    ids = fiche_crash_ids(fiche_rows)

    idws = wb.create_sheet(SHEET_ID)
    idws["A1"] = "Crash ID"
    for i, cid in enumerate(ids, start=2):
        idws.cell(row=i, column=1, value=int(cid))
    initial_ids = []
    if initial_id_txt is not None:
        header, raw = parse_initial_ids(initial_id_txt)
        for j, name in enumerate(header):
            idws.cell(row=1, column=_ID_RAW_COL + j, value=name)
        for i, row in enumerate(raw, start=2):
            for j, cell in enumerate(row):
                idws.cell(row=i, column=_ID_RAW_COL + j, value=coerce(cell))
            if row:
                initial_ids.append(row[0])
        idws["B1"], idws["C1"], idws["D1"] = "CRASH", "IS?", "Fiche?"
        fiche_set = set(ids)
        for i, cid in enumerate(initial_ids, start=2):
            idws.cell(row=i, column=2, value=int(cid) if cid.isdigit() else cid)
            idws.cell(row=i, column=4,
                      value="YES" if cid in fiche_set else "NO")
    counts[SHEET_ID] = max(len(ids), len(initial_ids)) + 1

    if initial_study_csv is not None:
        counts[SHEET_INITIAL] = _write_rows(
            wb.create_sheet(SHEET_INITIAL), _read_csv_rows(initial_study_csv))
    if detailed_fiche_csv is not None:
        counts[SHEET_DETAILED] = _write_rows(
            wb.create_sheet(SHEET_DETAILED), _read_csv_rows(detailed_fiche_csv))

    wb.save(out_path)
    return counts
