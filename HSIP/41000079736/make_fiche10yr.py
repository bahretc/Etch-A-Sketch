#!/usr/bin/env python3
"""Combine the two TEAAS fiche workbooks (9/1/2016-8/31/2021 and 9/1/2021-8/31/2026) into one 10-year fiche workbook
with the same layout: main sheet (in-study rows first, then the rest in fiche order), ID sheet (union), Index sheet."""
import copy, datetime
from pathlib import Path
from openpyxl import load_workbook, Workbook
from openpyxl.utils import get_column_letter

HERE = Path(__file__).resolve().parent
A = HERE / "data" / "41000079736_FicheFirst5.xlsx"     # 9/1/2016 - 8/31/2021
B = HERE / "data" / "41000079736_Fiche.xlsx"           # 9/1/2021 - 8/31/2026
OUT = HERE / "41000079736_Fiche10yr.xlsx"
IN_STUDY = ("IS", "ADD", "DEL")

def copy_style(src, dst):
    dst.font = copy.copy(src.font); dst.fill = copy.copy(src.fill); dst.border = copy.copy(src.border)
    dst.alignment = copy.copy(src.alignment); dst.number_format = src.number_format

wa, wb = load_workbook(A), load_workbook(B)
ma, mb = wa.worksheets[0], wb.worksheets[0]
assert [c.value for c in ma[1]][:17] == [c.value for c in mb[1]][:17], "fiche headers differ"
out = Workbook(); ws = out.active; ws.title = "41000079736_Fiche10yr"

# header row (from the 5-yr workbook)
for c in mb[1]:
    d = ws.cell(1, c.column, c.value); copy_style(c, d)
ws.row_dimensions[1].height = mb.row_dimensions[1].height
for col, dim in mb.column_dimensions.items():
    if dim.width: ws.column_dimensions[col].width = dim.width

def rows(sheet, period):
    for r in sheet.iter_rows(min_row=2):
        if r[10].value is None: continue                      # no Crash ID -> blank line
        yield period, r

# in-study rows first (both periods, newest period first as in the source sheets), then everything else in source order
src = list(rows(mb, "2021-2026")) + list(rows(ma, "2016-2021"))
ordered = [x for x in src if (x[1][8].value or "").strip().upper() in IN_STUDY] + \
          [x for x in src if (x[1][8].value or "").strip().upper() not in IN_STUDY]
seen = set(); n = 1
for period, r in ordered:
    cid = str(r[10].value).strip()
    if cid in seen: continue
    seen.add(cid); n += 1
    for c in r[:17]:
        d = ws.cell(n, c.column, c.value); copy_style(c, d)
    ws.cell(n, 18, f'=IF(M{n}=17,"animal","")')               # column R as in the source workbooks
    copy_style(r[17], ws.cell(n, 18))
print(f"main sheet: {n - 1} crashes ({sum(1 for p, r in ordered if (r[8].value or '').strip().upper() in IN_STUDY)} in-study rows first)")

# ID sheet: union of both (A = fiche IDs, B = in-study IDs, C/D formulas; H..N crash list)
ia, ib = wa["ID"], wb["ID"]; ids = out.create_sheet("ID")
for c in ib[1]: ids.cell(1, c.column, c.value)
colA, colB, crash = [], [], {}
for sh in (ib, ia):
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
print(f"ID sheet: {len(colA)} fiche IDs, {len(colB)} in-study IDs, {len(crash)} crash rows")

# Index sheet
idx = out.create_sheet("Index")
for r in wb["Index"].iter_rows():
    for c in r: idx.cell(c.row, c.column, c.value)
out.save(OUT); print("wrote", OUT)
