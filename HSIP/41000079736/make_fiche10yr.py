#!/usr/bin/env python3
"""Combine the two TEAAS fiche workbooks (9/1/2016-8/31/2021 and 9/1/2021-8/31/2026) into one 10-year fiche workbook laid
out like the package FicheReport workbooks (41000077748/77751): labelled sections IN STUDY, IN STUDY - ADDED, NOT IN STUDY -
DELETED, NOT IN STUDY - REVIEWED (IS? = NIS-R, with a comment), NOT IN STUDY - NOT REVIEWED; a Comments column; the ID and
Index sheets merged."""
import copy, csv, datetime
from pathlib import Path
from openpyxl import load_workbook, Workbook
from openpyxl.styles import PatternFill, Font
from openpyxl.styles.colors import Color

HERE = Path(__file__).resolve().parent
A = HERE / "data" / "41000079736_FicheFirst5.xlsx"     # 9/1/2016 - 8/31/2021
B = HERE / "data" / "41000079736_Fiche.xlsx"           # 9/1/2021 - 8/31/2026
OUT = HERE / "41000079736_Fiche10yr.xlsx"
LABEL_FILL = PatternFill("solid", fgColor=Color(theme=3, tint=0.749992370372631))   # the grey label rows of the package workbooks
TYPE = {17: "Animal collision", 19: "Object collision", 21: "Rear end", 22: "Rear end", 23: "Left turn (same roadway)",
        24: "Left turn (different roadways)", 25: "Right turn (same roadway)", 26: "Right turn (different roadways)", 27: "Head on",
        28: "Sideswipe (same direction)", 29: "Sideswipe (opposite direction)", 30: "Angle", 31: "Backing"}
# report-review outcomes recorded in the fiche workbooks (ADD / DEL) and the review list (review/review_ids.txt)
ADD_NOTE = {"106808749": "Referenced SR 1103 MP 3.019 (0.1 mi W of SR 2205); added after report review",
            "107960640": "Unmileposted (On Road = From Road = SR 1103); DMV-349 coordinates 170 ft from the intersection; added after report review"}

def copy_style(src, dst):
    dst.font = copy.copy(src.font); dst.fill = copy.copy(src.fill); dst.border = copy.copy(src.border)
    dst.alignment = copy.copy(src.alignment); dst.number_format = src.number_format

wa, wb = load_workbook(A), load_workbook(B)
ma, mb = wa.worksheets[0], wb.worksheets[0]
assert [c.value for c in ma[1]][:17] == [c.value for c in mb[1]][:17], "fiche headers differ"
cands = {r["Crash ID"]: r for r in csv.DictReader(open(HERE / "review" / "review_candidates.csv"))}
reviewed = [l.split()[0] for l in open(HERE / "review" / "review_ids.txt") if l.strip() and l.split()[0].isdigit()]

out = Workbook(); ws = out.active; ws.title = "41000079736_Fiche10yr"
for c in mb[1]:
    d = ws.cell(1, c.column, c.value); copy_style(c, d); d.font = Font(name=c.font.name, sz=c.font.sz, bold=True)
ws.cell(1, 18, "Comments").font = Font(name=mb["A1"].font.name, sz=11, bold=True)
ws.row_dimensions[1].height = mb.row_dimensions[1].height
for col, dim in mb.column_dimensions.items():
    if dim.width: ws.column_dimensions[col].width = dim.width
ws.column_dimensions["R"].width = 60

rows = []                                              # (crash id, period, source row)
for sheet, period in ((mb, "2021-2026"), (ma, "2016-2021")):
    for r in sheet.iter_rows(min_row=2):
        if r[10].value is not None: rows.append((str(r[10].value).strip(), period, r))
seen = set(); uniq = []
for cid, period, r in rows:
    if cid not in seen: seen.add(cid); uniq.append((cid, period, r))
def status(r): return (r[8].value or "").strip().upper()
def date(r): return r[11].value if isinstance(r[11].value, datetime.datetime) else datetime.datetime.max
def comment(cid, r):
    st = status(r); t = r[12].value
    if st == "ADD": return ADD_NOTE.get(cid, "Added after report review")
    if st == "DEL": return f"{TYPE.get(t, 'Type ' + str(t))}; not intersection related (deleted after report review)"
    if cid in reviewed:
        c = cands.get(cid, {}); where = ""
        if c.get("Dist_ft"): where = f"; DMV-349 coordinates {c['Dist_ft']} ft from the intersection"
        elif c.get("MP_offset_ft"): where = f"; milepost {int(float(c['MP_offset_ft'])):+d} ft from the intersection"
        return f"{TYPE.get(t, c.get('Type_desc', ''))}{where}; report reviewed, not intersection related"
    return None
sections = [("IN STUDY", [x for x in uniq if status(x[2]) == "IS"], None),
            ("IN STUDY - REMILEPOSTED", [x for x in uniq if status(x[2]) == "RE"], None),
            ("IN STUDY - ADDED", [x for x in uniq if status(x[2]) == "ADD"], None),
            ("NOT IN STUDY - DELETED", [x for x in uniq if status(x[2]) == "DEL"], None),
            ("NOT IN STUDY - REVIEWED", [x for x in uniq if status(x[2]) not in ("IS", "RE", "ADD", "DEL") and x[0] in reviewed], "NIS-R"),
            ("NOT IN STUDY - NOT REVIEWED", [x for x in uniq if status(x[2]) not in ("IS", "RE", "ADD", "DEL") and x[0] not in reviewed], None)]
n = 1; counts = {}
for label, items, override in sections:
    if not items and label == "IN STUDY - REMILEPOSTED": continue
    n += 1; c = ws.cell(n, 1, label); c.fill = LABEL_FILL; c.font = Font(name=mb["A1"].font.name, sz=11)
    if label != "NOT IN STUDY - NOT REVIEWED": items = sorted(items, key=lambda x: date(x[2]))   # the unreviewed rows keep the fiche order
    for cid, period, r in items:
        n += 1
        for cc in r[:17]:
            d = ws.cell(n, cc.column, cc.value); copy_style(cc, d)
        if override: ws.cell(n, 9, override)
        ws.cell(n, 18, comment(cid, r))
    counts[label] = len(items)
print("sections:", counts, "| total", sum(counts.values()))

# ID sheet (union) and Index sheet
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
idx = out.create_sheet("Index")
for r in wb["Index"].iter_rows():
    for c in r: idx.cell(c.row, c.column, c.value)
out.save(OUT); print("wrote", OUT)
