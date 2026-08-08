"""Assemble the study fiche workbook: OriginalFiche + ID + Initial Study + DetailedFiche.

This is the first step of a review, before any determination is made. Four
TEAAS exports arrive as CSV or pipe-delimited text and become one workbook the
engineer works in.

The ``<study>_Fiche`` sheet is the **working sheet**, not a raw paste. The
delivered *Original Fiche* sheets are verbatim pastes, which is a red herring:
the sheet an engineer actually works is the formatted one, and its rules were
read off the delivered *Filtered Fiche* (``examples/SS-6002AD``):

* **Column setup.** The raw fiche row has 16 fields under a 15-cell header,
  because "Miles / Dir From" is one header spanning two data columns. Those are
  split into ``Miles`` and ``Dir From``, and ``IS?`` / ``New MP`` are inserted
  after ``MP``, so the labels finally line up with the data.
* **Rows removed.** Title block, County/Division header block, Road Name / Road
  Code table, every "Page 1 of 13" footer, every repeated ``Muni. Code`` header
  block, and the trailing legend. One row per crash, nothing else.
* **Sorted by milepost** ascending. MP 999.999 (never mileposted) sorts to the
  end on its own value.
* **Type** is ``VLOOKUP(T, Index!$A$1:$B$26, 2, FALSE)`` against the T-code map.
* **Dir** is the movement pair, built from the two vehicle directions the
  Initial Study records on the "Unit" lines under each crash: MATCH the crash
  ID in column B, step down one row for vehicle 1 and two for vehicle 2, read
  column K. The ``NOT(ISNUMBER(...))`` guard on vehicle 2 is what stops a
  single-vehicle crash from picking up the *next* crash's row. The pair is then
  shaped by crash type: RE is BT/BT, LTSR and LTDR are BL/BT, RTSR and RTDR are
  BR/BT.
* **Latitude / Longitude** are INDEX/MATCH into the DetailedFiche sheet on
  crash ID. Every formula is wrapped in IFERROR, because most fiche crashes are
  not in the initial study and would otherwise show #N/A across the sheet.
* Cells are typed as Excel types a paste: crash ID a number, milepost a float,
  date a date. The lookups depend on it, since text "107206325" never matches a
  numeric one.

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
from openpyxl.styles import Alignment, Font
from openpyxl.utils import get_column_letter

#: Sheet names. The fiche sheet is named for the study, e.g. "41000079305_Fiche".
SHEET_ID = "ID"
SHEET_INITIAL = "Initial Study"
SHEET_DETAILED = "DetailedFiche"
SHEET_INDEX = "Index"

#: T code -> crash type abbreviation, read off the delivered Index sheet
#: (SS-6002AD, A1:B26). The Type column is a VLOOKUP into this.
T_CODES = {
    0: "unknown", 1: "ROR-R", 2: "ROR-L", 3: "ROR-T", 4: "jackknife",
    5: "overturn", 13: "other", 14: "pedestrian", 15: "cyclist", 16: "RR",
    17: "animal", 18: "MO", 19: "FO", 20: "PMV", 21: "RE", 22: "RE-T",
    23: "LTSR", 24: "LTDR", 25: "RTSR", 26: "RTDR", 27: "head-on",
    28: "SSSD", 29: "SSOD", 30: "angle", 31: "backing", 32: "other",
}

#: The working sheet, column by column. A-H and K-R come straight off the fiche
#: row; I/J/U are the engineer's to fill; S/T/V/W are formulas.
FICHE_COLUMNS = [
    "Muni.\nCode", "On Road", "Miles", "Dir\nFrom", "From Road", "Toward Road",
    "Milepost Road", "MP", "IS?", "New MP", "MA", "Crash ID", "Date",
    "T", "C", "F", "L", "S", "Type", "Dir", "Comment", "Latitude", "Longitude",
]
#: Raw fiche field index -> target column letter. The raw row carries 16 fields
#: because "Miles / Dir From" is one header over two data columns; splitting
#: them into C and D is the whole point of the column setup.
_FIELD_TO_COL = {0: 1, 1: 2, 2: 3, 3: 4, 4: 5, 5: 6, 6: 7, 7: 8,
                 8: 11, 9: 12, 10: 13, 11: 14, 12: 15, 13: 16, 14: 17, 15: 18}
_COL_T, _COL_CRASH_ID = 14, 12                   # N, L
_COL_TYPE, _COL_DIR, _COL_LAT, _COL_LON = 19, 20, 22, 23      # S, T, V, W
_COL_V1, _COL_V2, _COL_PAIR = 25, 26, 27         # Y, Z, AA (X left blank)

#: DetailedFiche column letters: Crash ID, Latitude, Longitude.
_DF_ID, _DF_LAT, _DF_LON = "J", "Q", "R"

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


def fiche_data_rows(rows) -> list:
    """Only the crash rows, with everything else dropped.

    Removed: the title block, the County/Division header block, the Road Name /
    Road Code table, every "Page 1 of 13" footer, every repeated ``Muni. Code``
    header block, and the trailing legend. What survives is one 16-field row per
    crash. (The Original Fiche sheet in a delivered workbook keeps all of that
    clutter because it is a raw paste; this is the working sheet, which does
    not.)
    """
    out, started = [], False
    for row in rows:
        cells = [str(c or "").strip() for c in row]
        flat = " ".join(cells)
        if any(c.replace("\n", " ").strip().startswith("Muni.") for c in cells):
            started = True                       # a header block, of any page
            continue
        if not started or "Page " in flat or flat.startswith("Legend"):
            continue
        if len(cells) < 16 or not cells[9].isdigit():
            continue                             # not a crash row
        out.append(cells[:16])
    return out


def _fiche_formulas(r: int) -> dict:
    """The formula cells for one working row, keyed by column index.

    Type is a VLOOKUP into the Index sheet. Dir is the movement pair, built
    from the two vehicle directions the Initial Study records on the "Unit"
    lines below each crash: MATCH the crash ID, step down one row for vehicle
    1 and two for vehicle 2, and read the Dir column. The ISNUMBER guard on
    vehicle 2 is what stops a single-vehicle crash from picking up the NEXT
    crash's row. Every one is wrapped in IFERROR because most fiche crashes are
    not in the initial study at all and would otherwise show #N/A.
    """
    iv = f"INDEX('{SHEET_INITIAL}'!K:K, MATCH(L{r}, '{SHEET_INITIAL}'!B:B, 0)"
    return {
        _COL_TYPE: f"=IFERROR(VLOOKUP(N{r},{SHEET_INDEX}!$A$1:$B$26,2,FALSE),\"\")",
        _COL_DIR: f"=AA{r}",
        _COL_LAT: f"=IFERROR(INDEX({SHEET_DETAILED}!{_DF_LAT}:{_DF_LAT},"
                  f"MATCH(L{r},{SHEET_DETAILED}!{_DF_ID}:{_DF_ID},0)),\"\")",
        _COL_LON: f"=IFERROR(INDEX({SHEET_DETAILED}!{_DF_LON}:{_DF_LON},"
                  f"MATCH(L{r},{SHEET_DETAILED}!{_DF_ID}:{_DF_ID},0)),\"\")",
        _COL_V1: f'=IFERROR(IF(AND({iv}+1)<>0,{iv}+1)<>""),{iv}+1),""),"")',
        _COL_V2: f'=IFERROR(IF(AND({iv}+2)<>0,{iv}+2)<>"",'
                 f'NOT(ISNUMBER({iv}+2)))),{iv}+2),"-"),"-")',
        _COL_PAIR: f'=IF(S{r}="RE", Y{r} & "BT/" & IF(Z{r} <> "-", Z{r} & "BT", ""),'
                   f' IF(OR(S{r}="LTDR", S{r}="LTSR"), Y{r} & "BL" & IF(Z{r} <> "-", "/" & Z{r} & "BT", ""),'
                   f' IF(OR(S{r}="RTDR", S{r}="RTSR"), Y{r} & "BR" & IF(Z{r} <> "-", "/" & Z{r} & "BT", ""),'
                   f' IF(Z{r} <> "-", Y{r} & "BT/" & Z{r} & "BT", Y{r} & "BT"))))',
    }


def _write_formatted_fiche(ws, data_rows) -> int:
    """Header, then one row per crash sorted by milepost."""
    for c, name in enumerate(FICHE_COLUMNS, start=1):
        cell = ws.cell(row=1, column=c, value=name)
        cell.font = Font(bold=True)
        cell.alignment = Alignment(wrap_text=True, vertical="bottom")

    def sort_key(cells):
        """Milepost Road, then Milepost, then From Road (G, H, E)."""
        try:
            mp = (0, float(cells[7]))
        except ValueError:
            mp = (1, 0.0)                        # unparseable sorts last
        return (str(cells[6] or ""), mp, str(cells[4] or ""))
    # 999.999 means "never mileposted" and lands at the end on its own value.
    for i, cells in enumerate(sorted(data_rows, key=sort_key), start=2):
        for field, col in _FIELD_TO_COL.items():
            v = coerce(cells[field])
            if v is not None:
                ws.cell(row=i, column=col, value=v)
        for col, formula in _fiche_formulas(i).items():
            ws.cell(row=i, column=col, value=formula)
    ws.freeze_panes = "A2"
    format_dates(ws)
    autofit_columns(ws)
    return len(data_rows) + 1


def build_fiche_workbook(out_path, fiche_csv, initial_study_csv=None,
                         initial_id_txt=None, detailed_fiche_csv=None,
                         study="") -> dict:
    """Write the study workbook. Returns a per-sheet row count."""
    wb = Workbook()
    counts = {}
    sheet_fiche = f"{study}_Fiche" if study else "Fiche"

    ws = wb.active
    ws.title = sheet_fiche
    fiche_rows = _read_csv_rows(fiche_csv)
    counts[sheet_fiche] = _write_formatted_fiche(ws, fiche_data_rows(fiche_rows))
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

    iw = wb.create_sheet(SHEET_INDEX)
    for i, (code, name) in enumerate(sorted(T_CODES.items()), start=1):
        iw.cell(row=i, column=1, value=code)
        iw.cell(row=i, column=2, value=name)
    counts[SHEET_INDEX] = len(T_CODES)

    if initial_study_csv is not None:
        counts[SHEET_INITIAL] = _write_rows(
            wb.create_sheet(SHEET_INITIAL), _read_csv_rows(initial_study_csv))
    if detailed_fiche_csv is not None:
        counts[SHEET_DETAILED] = _write_rows(
            wb.create_sheet(SHEET_DETAILED), _read_csv_rows(detailed_fiche_csv))

    wb.save(out_path)
    return counts


# --------------------------------------------------------------------------- #
# presentation
# --------------------------------------------------------------------------- #
#: Widest a column is allowed to get. A road cell occasionally holds a full
#: address ("*LCL 1226 E DIXIE DR") and one of those must not stretch the
#: column past every ordinary road name in it.
MAX_WIDTH = 16
#: Columns worth more room, by header.
WIDE = {"Comment": 30, "Date": 11, "Crash ID": 11}
#: Formula cells have no cached value to measure, so their width comes from
#: what the formula is known to produce: "animal", "SBL/NBT", "-82.12736".
FORMULA_WIDTH = {"Type": 9, "Dir": 10, "Latitude": 10, "Longitude": 11}

DATE_FORMAT = "m/d/yyyy"


def _rendered(value, fmt: str) -> int:
    if value is None:
        return 0
    if isinstance(value, datetime):
        return 10 if fmt == DATE_FORMAT else len(str(value))
    if hasattr(value, "hour") and not hasattr(value, "year"):
        return 8                                     # a time
    return max((len(part) for part in str(value).split("\n")), default=0)


def autofit_columns(ws, max_width: int = MAX_WIDTH, last_row=None) -> dict:
    """Narrow every column to its content, capped so one long cell cannot win.

    Formula cells are sized from what the formula produces rather than from the
    formula text, which is many times longer than any value it returns.
    ``last_row`` limits the measurement, for sheets whose lower rows are a
    summary block whose long labels must spill rather than set widths.
    """
    headers = {c: str(ws.cell(row=1, column=c).value or "")
               for c in range(1, ws.max_column + 1)}
    stop = last_row or ws.max_row
    widths = {}
    for c in range(1, ws.max_column + 1):
        head = headers[c]
        cap = WIDE.get(head, max_width)
        best = _rendered(head, "")
        for r in range(1, stop + 1):
            cell = ws.cell(row=r, column=c)
            v = cell.value
            if isinstance(v, str) and v.startswith("="):
                best = max(best, FORMULA_WIDTH.get(head, 10))
            else:
                best = max(best, _rendered(v, cell.number_format))
        if best:
            widths[get_column_letter(c)] = min(best + 1.5, cap)
    for letter, w in widths.items():
        ws.column_dimensions[letter].width = w
    return widths


def format_dates(ws, header: str = "Date", fmt: str = DATE_FORMAT) -> int:
    """Date only, no time, on the named column."""
    cols = [c for c in range(1, ws.max_column + 1)
            if str(ws.cell(row=1, column=c).value or "").strip() == header]
    n = 0
    for c in cols:
        for r in range(2, ws.max_row + 1):
            cell = ws.cell(row=r, column=c)
            if isinstance(cell.value, datetime):
                cell.number_format = fmt
                n += 1
    return n
