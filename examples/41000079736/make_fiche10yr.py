#!/usr/bin/env python3
"""Combine the two reviewed TEAAS fiche workbooks (9/1/2016-8/31/2021 and 9/1/2021-8/31/2026) into one 10-year fiche
workbook laid out like the package FicheReport workbooks (41000077748 / 41000077751):

  * blue header row (Muni. Code ... S, Comments), grey merged section labels IN STUDY, IN STUDY - ADDED,
    NOT IN STUDY - DELETED, NOT IN STUDY - REVIEWED, NOT IN STUDY - NOT REVIEWED;
  * IS? keeps the reviewer's IS / ADD / DEL; the NIS rows the reviewer placed above their "REPORT NOT REVIEWED" label
    become NIS-R (report reviewed), the rest stay NIS;
  * the reviewer's own comments (column R of the source workbooks) are carried over unchanged - text as text, the
    =IF(T=17,"animal","") flag re-pointed to its new row - nothing is added or reworded;
  * rows keep the reviewer's order, 2016-2021 workbook first; the ID and Index sheets are merged.
"""
import copy, datetime, re
from pathlib import Path
from openpyxl import load_workbook, Workbook
from openpyxl.styles import PatternFill, Font, Alignment, Border, Side
from openpyxl.styles.colors import Color

HERE = Path(__file__).resolve().parent
SOURCES = [HERE / "data" / "41000079736_FicheFirst5.xlsx",       # 9/1/2016 - 8/31/2021
           HERE / "data" / "41000079736_Fiche.xlsx"]             # 9/1/2021 - 8/31/2026
OUT = HERE / "41000079736_Fiche10yr.xlsx"
FONT = "Aptos Narrow"
HEADERS = ["Muni.\nCode", "On Road", "Miles", "Direction From", "From Road", "Toward Road", "Milepost Road", "MP", "IS?", "MA",
           "Crash ID", "Date", "T", "C", "F", "L", "S", "Comments"]
HEADER_FILL = PatternFill("solid", fgColor=Color(theme=4, tint=0.0))                      # accent 1 (blue) as in the examples
LABEL_FILL = PatternFill("solid", fgColor=Color(theme=3, tint=0.749992370372631))        # grey section labels of the examples
THIN = Side(style="thin")
ANIMAL = re.compile(r'^=IF\(M\d+=17,"animal",""\)$')
SECTIONS = ["IN STUDY", "IN STUDY - REMILEPOSTED", "IN STUDY - ADDED", "NOT IN STUDY - DELETED", "NOT IN STUDY - REVIEWED",
            "NOT IN STUDY - NOT REVIEWED"]
STATUS_SECTION = {"IS": "IN STUDY", "RE": "IN STUDY - REMILEPOSTED", "ADD": "IN STUDY - ADDED", "DEL": "NOT IN STUDY - DELETED"}


def read_source(path):
    """Yield (section, row cells) for every crash row, in the reviewer's order."""
    ws = load_workbook(path).worksheets[0]
    hdr = [c.value for c in ws[1]]
    assert hdr[:17] == ["Muni.\nCode", "On Road", "Miles", "Dir\nFrom", "From Road", "Toward Road", "Milepost Road", "MP", "IS?",
                        "MA", "Crash ID", "Date", "T", "C", "F", "L", "S"], f"{path.name}: unexpected fiche columns {hdr[:17]}"
    reviewed = True                                   # NIS rows above the reviewer's "REPORT NOT REVIEWED" label were reviewed
    for r in ws.iter_rows(min_row=2):
        a = r[0].value
        if isinstance(a, str) and "NOT REVIEWED" in a.upper():
            reviewed = False; continue
        if r[10].value is None:                       # blank or label row
            continue
        st = (r[8].value or "NIS").strip().upper()
        if st in STATUS_SECTION:
            yield STATUS_SECTION[st], r
        else:
            yield ("NOT IN STUDY - REVIEWED" if reviewed else "NOT IN STUDY - NOT REVIEWED"), r


books = [load_workbook(p) for p in SOURCES]
rows = {s: [] for s in SECTIONS}; seen = set(); dupes = 0
for path in SOURCES:
    for section, r in read_source(path):
        cid = str(r[10].value).strip()
        if cid in seen: dupes += 1; continue
        seen.add(cid); rows[section].append(r)

out = Workbook(); out.loaded_theme = books[1].loaded_theme          # same Office theme (Aptos, accent 1 = 156082) as the examples
ws = out.active; ws.title = "41000079736_Fiche10yr"
for i, h in enumerate(HEADERS, start=1):
    c = ws.cell(1, i, h); c.font = Font(name=FONT, sz=11, bold=True, color=Color(theme=0)); c.fill = copy.copy(HEADER_FILL)
    c.alignment = Alignment(wrap_text=True); c.border = Border(left=THIN, right=THIN, top=THIN, bottom=THIN)
ws.row_dimensions[1].height = 28.8
ws.column_dimensions["K"].width = 10.0; ws.column_dimensions["L"].width = 10.33203125; ws.column_dimensions["R"].width = 46.33203125

n = 1; counts = {}; kept_text = []
for section in SECTIONS:
    items = rows[section]
    if not items and section == "IN STUDY - REMILEPOSTED":
        continue
    n += 1; c = ws.cell(n, 1, section); c.fill = copy.copy(LABEL_FILL); c.font = Font(name=FONT, sz=11)
    ws.merge_cells(start_row=n, start_column=1, end_row=n, end_column=len(HEADERS))
    for r in items:
        n += 1
        for src in r[:17]:
            d = ws.cell(n, src.column, src.value); d.font = Font(name=FONT, sz=11); d.number_format = src.number_format
            if src.fill is not None and src.fill.fill_type == "solid": d.fill = copy.copy(src.fill)
        if section == "NOT IN STUDY - REVIEWED": ws.cell(n, 9, "NIS-R")
        com = r[17].value if len(r) > 17 else None                  # the reviewer's comment column
        if isinstance(com, str) and ANIMAL.match(com.replace(" ", "")):
            com = f'=IF(M{n}=17,"animal","")'
        elif com not in (None, ""):
            kept_text.append((str(r[10].value), com))
        if com not in (None, ""):
            d = ws.cell(n, 18, com); d.font = Font(name=FONT, sz=11)
    counts[section] = len(items)
print("sections:", counts, "| total", sum(counts.values()), "| duplicate IDs skipped:", dupes)
print("reviewer comments kept:", kept_text)

# ID sheet (union of both) and Index sheet
ids = out.create_sheet("ID"); ib, ia = books[1]["ID"], books[0]["ID"]
for c in ib[1]: ids.cell(1, c.column, c.value)
colA, colB, crash = [], [], {}
for sh in (ia, ib):
    for r in sh.iter_rows(min_row=2, values_only=True):
        if r[0] is not None and r[0] not in colA: colA.append(r[0])
        if r[1] is not None and r[1] not in colB: colB.append(r[1])
        if r[7] is not None and r[7] not in crash: crash[r[7]] = r[7:15]
for i, v in enumerate(colA, start=2):
    ids.cell(i, 1, v); ids.cell(i, 3, f'=IF(COUNTIF($B:$B,A{i})>0,"IS","NIS")'); ids.cell(i, 4, f'=IF(COUNTIF($A:$A,B{i})>0,"YES","NO")')
for i, v in enumerate(colB, start=2): ids.cell(i, 2, v)
for i, (k, vals) in enumerate(crash.items(), start=2):
    for j, v in enumerate(vals): ids.cell(i, 8 + j, v)
    ids.cell(i, 11).number_format = "mm-dd-yy"; ids.cell(i, 12).number_format = "h:mm:ss"
for col, dim in ib.column_dimensions.items():
    if dim.width: ids.column_dimensions[col].width = dim.width
idx = out.create_sheet("Index")
for r in books[1]["Index"].iter_rows():
    for c in r: idx.cell(c.row, c.column, c.value)
out.save(OUT); print("wrote", OUT)
