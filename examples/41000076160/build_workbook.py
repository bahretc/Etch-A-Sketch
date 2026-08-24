"""Rebuild the 41000076160 evaluation workbook end to end.

Runs the fill-template pipeline (Before/After, set-up, results sheet
with the completed-workbook formatting pass), then writes the Original
Fiche (with DetailedFiche coordinates), the reviewed Filtered Fiche,
and the Binned Crashes sheet in the engineer's own layout from the
completed SS-6002AD workbook: columns A-T ending in Type / Dir /
Comment, the Dir pair leading with the at-fault unit, and the terse
comment voice (failed to yield, ran stop sign, >150'). Recalculates
once through LibreOffice, verifies template integrity, and installs
the result into the example folder.
"""
import csv
import json
import os
import subprocess
import sys
from datetime import date

sys.path.insert(0, "/home/user/Etch-A-Sketch")

from safety_eval.binned_sheet import _fmt  # noqa: E402
from safety_eval.fiche_parser import parse_fiche  # noqa: E402
from safety_eval.filtered_sheet import SHEET, populate_original_sheet  # noqa: E402
from safety_eval.xlsx_patch import (  # noqa: E402
    recalc, render_row, replace_sheet_rows, verify_integrity)

EX = "/home/user/Etch-A-Sketch/examples/41000076160"
SP = ("/tmp/claude-0/-home-user-Etch-A-Sketch/"
      "4d83860a-51f4-5f7b-a60e-765168dfbb13/scratchpad/build76160")
TEMPLATE = f"{EX}/629f05da-Intersection_Evaluation_Workbook__1018223.xlsx"
FINAL = f"{EX}/Intersection Evaluation Workbook - 10-18-223 (W-5710AM).xlsx"
os.makedirs(SP, exist_ok=True)

#: The engineer's sheet layout (completed SS-6002AD): fiche columns,
#: then Type / Dir / Comment.
HEADER = {"A": "Muni.\nCode", "B": "On Road", "C": "Miles",
          "D": "Dir\nFrom", "E": "From Road", "F": "Toward Road",
          "G": "Milepost Road", "H": "MP", "I": "IS?", "J": "MA",
          "K": "Crash ID", "L": "Date", "M": "T", "N": "C", "O": "F",
          "P": "L", "Q": "S", "R": "Type", "S": "Dir", "T": "Comment"}

BEFORE = (date(2016, 4, 1), date(2021, 3, 31))
CONSTRUCTION = (date(2021, 4, 1), date(2021, 6, 30))
AFTER = (date(2021, 7, 1), date(2026, 6, 30))

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


def crash_cells(crash, det):
    """One data row in the engineer's layout."""
    det = det or {}
    return {
        "A": crash.muni_code or None, "B": crash.on_road or None,
        "C": crash.miles, "D": crash.dir_from or None,
        "E": crash.from_road or None, "F": crash.toward_road or None,
        "G": crash.milepost_road or None, "H": crash.mp,
        "I": det.get("status"), "J": crash.ma or None,
        "K": (int(crash.crash_id) if crash.crash_id.isdigit()
              else crash.crash_id),
        "L": _fmt(crash.date) if crash.date else None,
        "M": crash.t, "N": crash.c, "O": crash.f, "P": crash.l,
        "Q": crash.s or None, "R": det.get("type") or None,
        "S": det.get("dir") or None, "T": det.get("comment") or None,
    }


def write_blocks(src, dst, sheet, blocks):
    parts = [render_row(1, dict(HEADER))]
    row = 2
    counts = {}
    for title, crashes in blocks:
        parts.append(render_row(row, {"A": title}))
        row += 1
        for crash in crashes:
            parts.append(render_row(
                row, crash_cells(crash, dets.get(crash.crash_id))))
            row += 1
        counts[title] = len(crashes)
    replace_sheet_rows(src, dst, sheet, "".join(parts), from_row=1)
    return counts


# -- Filtered Fiche: review coverage blocks
def by_status(key):
    return [c for c in fiche if dets.get(c.crash_id, {}).get("status") == key]


not_reviewed = [c for c in fiche if c.crash_id not in dets]
counts = write_blocks(
    f"{SP}/eval_orig.xlsx", f"{SP}/eval_ff.xlsx", SHEET,
    [("IN STUDY", by_status("IS")),
     ("ADDED TO STUDY", by_status("ADD")),
     ("NOT IN STUDY - REPORT REVIEWED", by_status("NIS")),
     ("NOT IN STUDY - REPORT NOT REVIEWED", not_reviewed)])
print("filtered fiche blocks:", counts)


# -- Binned Crashes: study crashes per period, then the NIS coverage
def in_window(crash, lo, hi):
    return crash.date is not None and lo <= crash.date <= hi


study = by_status("IS") + by_status("ADD")
study.sort(key=lambda c: c.date or date.min)


def banner(label, lo, hi):
    return (f"{label} ({lo.strftime('%m/%d/%y')} - "
            f"{hi.strftime('%m/%d/%y')})")


counts = write_blocks(
    f"{SP}/eval_ff.xlsx", f"{SP}/eval_final.xlsx", "Binned Crashes",
    [(banner("Before Period", *BEFORE),
      [c for c in study if in_window(c, *BEFORE)]),
     (banner("Construction Period", *CONSTRUCTION),
      [c for c in study if in_window(c, *CONSTRUCTION)]),
     (banner("After Period", *AFTER),
      [c for c in study if in_window(c, *AFTER)]),
     ("NOT IN STUDY - REPORT REVIEWED", by_status("NIS")),
     ("NOT IN STUDY - REPORT NOT REVIEWED", not_reviewed)])
print("binned blocks:", counts)

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
