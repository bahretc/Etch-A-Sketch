#!/usr/bin/env python3
"""NCDOT HSIP intersection warrant check for study 41000079736 (10-year rural study, 9/1/2016 - 8/31/2026).

Scenarios: (A) crashes as submitted in the TEAAS analysis; (B) every crash the reviewer deleted added back;
(C) only the deleted rear-end and fixed-object crashes added back.
Warrants per NCDOT HSIP Safety Warrants (2024 / 2026 editions; rural intersection warrants are identical in both).
"""
import csv, datetime as dt
from pathlib import Path
import openpyxl

HERE = Path(__file__).resolve().parent
END = dt.date(2026, 8, 31)
LAST1, LAST3, LAST5 = dt.date(2025, 9, 1), dt.date(2023, 9, 1), dt.date(2021, 9, 1)
KA_CF, BC_CF = 76.8, 8.4                       # TEAAS / HSIP EPDO coefficients
FRONTAL = {23, 24, 25, 26, 27, 30}             # LT same, LT diff, RT same, RT diff, head on, angle
NAMES = {17: "Animal", 19: "Fixed object", 21: "Rear end, slow/stop", 23: "Left turn, same rdwy", 24: "Left turn, diff rdwy",
         25: "Right turn, same rdwy", 26: "Right turn, diff rdwy", 28: "Sideswipe, same dir", 29: "Sideswipe, opp dir", 30: "Angle"}
TYPE_CODE = {"ANGLE": 30, "LEFT TURN, DIFFERENT ROADWAYS": 24, "LEFT TURN, SAME ROADWAY": 23, "RIGHT TURN, DIFFERENT ROADWAYS": 26,
             "RIGHT TURN, SAME ROADWAY": 25, "REAR END, SLOW OR STOP": 21, "FIXED OBJECT": 19, "ANIMAL": 17, "HEAD ON": 27}


def submitted():
    out = []
    with open(HERE / "data" / "41000079736_CrashAnalysis10yr_29crashes.csv", newline="") as f:
        for r in csv.DictReader(f):
            sev = next((k for k in "KABC" if int(r[k]) > 0), "O")
            out.append(dict(id=int(r["CrashID"]), date=dt.datetime.strptime(r["Date"], "%m/%d/%Y").date(), type=TYPE_CODE[r["Type"]],
                            sev=sev, night=r["Light"] in ("4", "5", "6"), src="submitted"))
    return out


def deleted():
    out = []
    for fn in ("41000079736_FicheFirst5.xlsx", "41000079736_Fiche.xlsx"):
        ws = openpyxl.load_workbook(HERE / "data" / fn, read_only=True, data_only=True).worksheets[0]
        rows = ws.iter_rows(values_only=True); hdr = [str(h).replace("\n", " ") for h in next(rows)]
        ix = {h: i for i, h in enumerate(hdr)}
        for r in rows:
            if r[ix["IS?"]] == "DEL":
                out.append(dict(id=int(r[ix["Crash ID"]]), date=r[ix["Date"]].date(), type=int(r[ix["T"]]), sev=r[ix["S"]] or "O",
                                night=int(r[ix["L"]]) in (4, 5, 6), src="deleted"))
    return sorted(out, key=lambda c: c["date"])


def check(crashes, label):
    n = len(crashes); fr = [c for c in crashes if c["type"] in FRONTAL]
    l1 = sum(c["date"] >= LAST1 for c in crashes); l3 = sum(c["date"] >= LAST3 for c in crashes)
    night = sum(c["night"] for c in crashes)
    ka = sum(c["sev"] in "KA" for c in crashes); bc = sum(c["sev"] in "BC" for c in crashes); pdo = n - ka - bc
    si = (ka * KA_CF + bc * BC_CF + pdo) / n
    ka_front5 = sum(c["sev"] in "KA" and c["type"] in FRONTAL and c["date"] >= LAST5 for c in crashes)
    res = {
        "I-1r Frontal Impact Rural (9+ frontal, 60% frontal, 20% in last 3 yr)":
            (len(fr) >= 9 and len(fr) / n >= .60 and l3 / n >= .20, f"{len(fr)} frontal ({100*len(fr)/n:.0f}%), {l3}/{n} ({100*l3/n:.0f}%) last 3 yr"),
        "I-2r Last Year Increase Rural (20+ crashes, 32% in last yr)":
            (n >= 20 and l1 / n >= .32, f"{n} crashes, {l1} ({100*l1/n:.0f}%) in 9/2025-8/2026"),
        "I-3r Frequency w/ Severity Index Rural (20+ crashes, SI 9.0, 30% in last 3 yr)":
            (n >= 20 and si >= 9.0 and l3 / n >= .30, f"{n} crashes, SI {si:.2f}, {100*l3/n:.0f}% last 3 yr"),
        "I-3 Fatal and Severe Injury (3+ K/A frontal in last 5 yr)":
            (ka_front5 >= 3, f"{ka_front5} K/A frontal crashes since 9/2021"),
        "I-4r Night Location Rural (10+ night, 46% night, 20% in last 3 yr)":
            (night >= 10 and night / n >= .46 and l3 / n >= .20, f"{night} night ({100*night/n:.0f}%)"),
    }
    print(f"\n=== {label}: {n} crashes, {ka} K/A, {bc} B/C, {pdo} PDO, EPDO {ka*KA_CF+bc*BC_CF+pdo:.1f}, SI {si:.2f}")
    for w, (ok, detail) in res.items():
        print(f"  {'MET    ' if ok else 'not met'}  {w}\n            {detail}")
    return res


def main():
    sub, dele = submitted(), deleted()
    print("Deleted crashes (reviewer 'DEL' in the fiche workbooks):")
    for c in dele:
        print(f"  {c['id']}  {c['date']}  {NAMES.get(c['type'], c['type']):22} {c['sev']:3} {'night' if c['night'] else 'day'}")
    check(sub, "A. As submitted (29 crashes)")
    check(sub + dele, "B. All deleted crashes added back")
    check(sub + [c for c in dele if c["type"] in (19, 21)], "C. Only deleted rear-end / fixed-object crashes added back")


if __name__ == "__main__":
    main()
