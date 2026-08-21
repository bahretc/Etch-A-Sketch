"""Rebuild the 41000076160 evaluation workbook end to end.

Runs the fill-template pipeline (Before/After, set-up, results sheet
with the completed-workbook formatting pass), then writes the Original
Fiche (with DetailedFiche coordinates) and the reviewed Filtered Fiche
banner blocks, recalculates once through LibreOffice, verifies template
integrity, and installs the result into the example folder.
"""
import csv
import json
import os
import subprocess
import sys

sys.path.insert(0, "/home/user/Etch-A-Sketch")

from safety_eval.binned_sheet import _HEADERS, _fmt  # noqa: E402
from safety_eval.fiche_parser import parse_fiche  # noqa: E402
from safety_eval.filtered_sheet import SHEET, populate_original_sheet  # noqa: E402
from safety_eval.xlsx_patch import (  # noqa: E402
    recalc, render_row, replace_sheet_rows, sheet_row_styles,
    verify_integrity)

EX = "/home/user/Etch-A-Sketch/examples/41000076160"
SP = ("/tmp/claude-0/-home-user-Etch-A-Sketch/"
      "4d83860a-51f4-5f7b-a60e-765168dfbb13/scratchpad/build76160")
TEMPLATE = f"{EX}/629f05da-Intersection_Evaluation_Workbook__1018223.xlsx"
FINAL = f"{EX}/Intersection Evaluation Workbook - 10-18-223 (W-5710AM).xlsx"
os.makedirs(SP, exist_ok=True)

subprocess.run(
    [sys.executable, "-m", "safety_eval.cli", "fill-template",
     "--template", TEMPLATE,
     "--before", f"{EX}/Before_ID.txt", "--after", f"{EX}/After_ID.txt",
     "--fiche", f"{EX}/OriginalFiche.csv", "--setup", f"{EX}/setup.yaml",
     "--results", f"{EX}/results.yaml", "--target1", "Frontal Impact",
     "--output", f"{SP}/eval.xlsx"],
    cwd="/home/user/Etch-A-Sketch", check=True)

fiche = parse_fiche(f"{EX}/OriginalFiche.csv")
coords = {}
with open(f"{EX}/DetailedFiche.csv", newline="", encoding="utf-8-sig") as fh:
    for row in csv.DictReader(fh):
        cid = (row.get("Crash ID") or "").strip()
        la = (row.get("Latitude") or "").strip()
        lo = (row.get("Longitude") or "").strip()
        if cid and la and lo:
            coords[cid] = (float(la), float(lo),
                           (row.get("Source") or "").strip() or None)
n = populate_original_sheet(f"{SP}/eval.xlsx", f"{SP}/eval_orig.xlsx",
                            fiche, coords)
print("original fiche rows:", n, "coords:", len(coords))

dets = {}
with open(f"{EX}/review_determinations.jsonl", encoding="utf-8") as fh:
    for line in fh:
        d = json.loads(line)
        dets[d["crash_id"]] = d

BLOCKS = (
    ("IS", "IN STUDY"),
    ("ADD", "ADDED TO STUDY"),
    ("NIS", "NOT IN STUDY - REPORT REVIEWED"),
    (None, "NOT IN STUDY - REPORT NOT REVIEWED"),
)
styles = sheet_row_styles(TEMPLATE, SHEET, 3)
parts = [render_row(1, dict(_HEADERS))]
row, counts = 2, {}
for key, title in BLOCKS:
    parts.append(render_row(row, {"A": title}))
    row += 1
    ncab = 0
    for crash in fiche:
        det = dets.get(crash.crash_id)
        if key is None:
            if det is not None:
                continue
            status, comment = None, None
        else:
            if det is None or det["status"] != key:
                continue
            status, comment = det["status"], det.get("comment")
        parts.append(render_row(row, {
            "A": crash.muni_code or None, "B": crash.on_road or None,
            "C": crash.miles, "D": crash.dir_from or None,
            "E": crash.from_road or None, "F": crash.toward_road or None,
            "G": crash.milepost_road or None, "H": crash.mp,
            "I": status, "J": None, "K": crash.ma or None,
            "L": (int(crash.crash_id) if crash.crash_id.isdigit()
                  else crash.crash_id),
            "M": _fmt(crash.date) if crash.date else None,
            "N": crash.t, "O": crash.c, "P": crash.f, "Q": crash.l,
            "R": crash.s or None, "S": comment,
        }, styles))
        row += 1
        ncab += 1
    counts[title] = ncab
print("blocks:", counts)
replace_sheet_rows(f"{SP}/eval_orig.xlsx", f"{SP}/eval_final.xlsx", SHEET,
                   "".join(parts), from_row=1)

ok = recalc(f"{SP}/eval_final.xlsx")
print("recalc:", ok)
if not ok:
    raise SystemExit("recalc failed; reinstall libreoffice-calc/-core")
rep = verify_integrity(TEMPLATE, f"{SP}/eval_final.xlsx")
print("integrity:", rep)
if not rep.ok:
    raise SystemExit(f"integrity failed: {rep.problems}")
import shutil
shutil.copy(f"{SP}/eval_final.xlsx", FINAL)
print("installed:", FINAL)
