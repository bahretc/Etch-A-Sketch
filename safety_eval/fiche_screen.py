"""Screen the working fiche sheet: which crashes need a report pulled.

Step 2 of a review. The Initial Study already says which crashes TEAAS placed
inside the study limits; those are IS. The open question is the rest of the
fiche: a crash coded outside the limits may still have happened inside them,
and the only way to know is to read its report. This decides which reports are
worth pulling, and colours the evidence it used so the engineer can check it.

The evidence is the pair of roads the fiche names for every crash: the road it
is measured FROM and the road it is measured TOWARD. Each resolves to a
milepost on the study route through the Features Report, and the two together
bracket where the crash can be:

* either cell green, or the two cells a different colour -> the crash can fall
  inside the limits, so the report gets pulled: **?**
* both cells the same colour -> **NIS**, no report needed

Blue against yellow is the case worth naming: the two roads sit on opposite
sides of the study, so whatever lies between them crosses it.

Colour records the same judgement cell by cell, so a reviewer can see why:

* **light green**  the feature is inside the study limits
* **light blue**   north or east of them (higher milepost)
* **light yellow** south or west of them (lower milepost)

Two things that look like details and are not:

1. **There are two mile-marker series on US 74.** Marker 62 sits at MP 3.638
   and marker 162 at MP 9.696, six miles apart, because the numbering restarts
   where US 74 joins I 26. Matching "*MILE 62" loosely against "162" would move
   a crash six miles.
2. **A crash on a cross street is placed by where that street meets the study
   route**, not by its own milepost. A crash on NC 9 at NC 9's MP 0.4 is at
   US 74 MP 14.455, which is inside these limits; NC 108 crashes are at US 74
   MP 10.125 and are not.
"""
from __future__ import annotations

import re
import subprocess

from openpyxl.styles import Font, PatternFill

from . import study_type as _st
from openpyxl.utils import get_column_letter

from .fiche_workbook import (T_CODES, autofit_columns,
                             format_dates)

#: Inside the limits, north/east of them, south/west of them.
FILL_IN = PatternFill("solid", fgColor="C6EFCE")
FILL_NE = PatternFill("solid", fgColor="BDD7EE")
FILL_SW = PatternFill("solid", fgColor="FFEB9C")

STATUS_ORDER = {"IS": 0, "?": 1, "ADD": 1, "RE": 1, "DEL": 2, "NIS": 3}

#: The decoded Type of an animal crash (docs/09 T code 17).
ANIMAL_TYPE = "animal"

#: The banner that opens the unreviewed block, and its grey. A6A6A6 is Excel's
#: "White, Background 1, Darker 35%", which is what the delivered workbook uses
#: on this exact row (SS-6002AD Filtered Fiche row 41, theme 0 tint -0.35).
#: Black bold on it stays legible.
BANNER_TEXT = "NOT IN STUDY - REPORT NOT REVIEWED"
FILL_BANNER = PatternFill("solid", fgColor="A6A6A6")

_MP_RE = re.compile(r"\s*(\d+\.\d{3})\s+(\S+)\s+(.*)")


def parse_features_report(path: str) -> dict:
    """Features Report PDF -> ``{feature name: [milepost, ...]}``.

    Mile markers are keyed the way the fiche writes them, ``*MILE 166``, and
    keep their own milepost rather than being derived from the number, because
    the number restarts partway along the route.
    """
    text = subprocess.run(["pdftotext", "-layout", path, "-"],
                          capture_output=True, text=True, check=True).stdout
    out: dict = {}
    for line in text.splitlines():
        m = _MP_RE.match(line)
        if not m:
            continue
        mp, fid, rest = float(m.group(1)), m.group(2), m.group(3)
        if "Mile Marker" in rest:
            try:
                name = f"*MILE {float(fid):.0f}"
            except ValueError:
                continue
        else:
            name = re.split(r"\s{2,}", rest.strip())[0].strip()
            if not name or name == "Structure":
                continue
        out.setdefault(name, [])
        if mp not in out[name]:
            out[name].append(mp)
    return out


def normalize_feature(text) -> str:
    """A fiche From/Toward cell as the Features Report names it."""
    s = re.sub(r"\s+", " ", str(text or "")).strip().upper()
    if not s:
        return ""
    m = re.match(r"^\*?MILE\s*(\d+(?:\.\d+)?)$", s)
    if m:
        return f"*MILE {float(m.group(1)):.0f}"
    s = re.sub(r"^\*(LCL|PVA)\s+", "", s)        # a local street or driveway
    return s


def classify(name, features: dict, lo: float, hi: float):
    """``(bucket, milepost)`` for one From/Toward cell.

    bucket is "in", "ne", "sw", or None when the feature is not on the study
    route at all and therefore says nothing about where the crash was.
    """
    key = normalize_feature(name)
    mps = features.get(key)
    if not mps:
        return None, None
    if any(lo <= mp <= hi for mp in mps):
        return "in", min(mps, key=lambda m: abs(m - (lo + hi) / 2))
    mp = min(mps, key=lambda m: min(abs(m - lo), abs(m - hi)))
    return ("ne" if mp > hi else "sw"), mp


def needs_review(from_road, toward_road, on_road, features, lo, hi,
                 route="US 74") -> str:
    """"?" if a report is worth pulling for this crash, else "NIS".

    The rule is the colour, and nothing else (engineer, 2026-08):

    * **a green cell** - the crash is measured off a feature inside the study
      limits, so it may well be in the study.
    * **two different colours** - blue against yellow means the pair brackets
      the limits, so the crash can fall between them and land inside.
    * the same colour on both sides -> NIS. Both endpoints lie the same way, so
      nothing between them reaches the study.

    Deliberately NOT filtered by the coded milepost. The fiche also gives a
    distance, and crash 108018739 is measured 6.000 miles west of MILE 167,
    putting its coded milepost four miles clear of the limits. But that
    distance is the officer's, and checking whether it is right is precisely
    what the report review is FOR, so a milepost derived from it cannot be used
    to skip the review.
    """
    on = normalize_feature(on_road)
    if on and on != route.upper():
        # A cross-street crash sits where that street meets the study route.
        bucket, _ = classify(on_road, features, lo, hi)
        return "?" if bucket == "in" else "NIS"
    buckets = [classify(r, features, lo, hi)[0] for r in (from_road, toward_road)]
    if "in" in buckets:
        return "?"                          # green
    known = [b for b in buckets if b]
    if len(known) == 2 and known[0] != known[1]:
        return "?"                          # blue against yellow
    if len(known) < 2:
        return "?"                          # unresolved: nothing rules it out
    return "NIS"


def screen_sheet(ws, features: dict, lo: float, hi: float, initial_ids,
                 route: str = "US 74", col=None, study="evaluation") -> dict:
    """Fill IS?, colour the From/Toward cells, and sort. Returns a tally.

    ``study`` is the study type (``study_type``). On an HSIP package the animal
    crashes come out as DEL before anything else is decided, which is the
    working practice and is stronger than the 2024 Overview's rule of merely
    dropping them from the warrant arithmetic.
    """
    kind = _st.get(study)
    col = col or {"on": 2, "from": 5, "toward": 6, "mproad": 7, "mp": 8,
                  "is": 9, "id": 12, "t": 14}
    col.setdefault("t", 14)
    initial = {int(c) for c in initial_ids}
    tally = {"IS": 0, "?": 0, "NIS": 0, "DEL": 0}

    rows = []
    for r in range(2, ws.max_row + 1):
        cid = ws.cell(row=r, column=col["id"]).value
        if cid is None:
            continue
        on = ws.cell(row=r, column=col["on"]).value
        fr = ws.cell(row=r, column=col["from"]).value
        tw = ws.cell(row=r, column=col["toward"]).value
        t = ws.cell(row=r, column=col["t"]).value
        if kind.deletes_animals and T_CODES.get(t) == ANIMAL_TYPE:
            status = "DEL"          # out of the study, not merely set aside
        elif cid in initial:
            status = "IS"
        else:
            status = needs_review(fr, tw, on, features, lo, hi, route)
        tally[status] += 1
        buckets = {}
        if not normalize_feature(on) or normalize_feature(on) == route.upper():
            for which, key in (("from", "from"), ("toward", "toward")):
                b, _ = classify(ws.cell(row=r, column=col[key]).value,
                                features, lo, hi)
                buckets[key] = b
        values = [ws.cell(row=r, column=c).value
                  for c in range(1, ws.max_column + 1)]
        values[col["is"] - 1] = status
        # IS? leads; beneath it the sheet keeps its own order, G/H/E
        # (Milepost Road, Milepost, From Road).
        rows.append(((STATUS_ORDER[status],
                      str(ws.cell(row=r, column=col["mproad"]).value or ""),
                      _mp_key(ws.cell(row=r, column=col["mp"]).value),
                      str(ws.cell(row=r, column=col["from"]).value or "")),
                     values, buckets))

    rows.sort(key=lambda t: t[0])
    fills = {"in": FILL_IN, "ne": FILL_NE, "sw": FILL_SW}
    for i, (_, values, buckets) in enumerate(rows, start=2):
        for c, v in enumerate(values, start=1):
            cell = ws.cell(row=i, column=c)
            cell.value = _reanchor(v, i)
            cell.fill = PatternFill()
        for key in ("from", "toward"):
            fill = fills.get(buckets.get(key))
            if fill is not None:
                ws.cell(row=i, column=col[key]).fill = fill
    format_dates(ws)
    autofit_columns(ws)          # before the banner: its 34-character text is
    _insert_banner(ws, rows)     # a heading, not content, no width
    # No conditional formatting on this sheet, ever: its extent goes stale the
    # moment a determination moves. The Warrant sheet is the highlight's home.
    return tally


def _insert_banner(ws, rows) -> int:
    """A blank row after the last "?", then the unreviewed banner.

    The delivered workbook does the same: SS-6002AD Filtered Fiche has a blank
    row above each of its banner rows.
    """
    last_q = None
    for i, (key, _, _) in enumerate(rows, start=2):
        if key[0] == STATUS_ORDER["?"]:
            last_q = i
    if last_q is None:                    # nothing to review, banner goes on top
        last_q = 1 + sum(1 for k, _, _ in rows if k[0] == STATUS_ORDER["IS"])
    ws.insert_rows(last_q + 1, amount=2)
    banner = last_q + 2
    # insert_rows copies the style of the row above, so the blank row would
    # inherit the green/blue/yellow fill from the From/Toward cells over it.
    for c in range(1, ws.max_column + 1):
        ws.cell(row=last_q + 1, column=c).fill = PatternFill()
    ws.cell(row=banner, column=1, value=BANNER_TEXT)
    for c in range(1, ws.max_column + 1):
        cell = ws.cell(row=banner, column=c)
        cell.fill = FILL_BANNER
        cell.font = Font(bold=True)
    # insert_rows does not repoint formulas, so the NIS block needs re-anchoring
    for r in range(banner + 1, ws.max_row + 1):
        for c in range(1, ws.max_column + 1):
            cell = ws.cell(row=r, column=c)
            cell.value = _reanchor(cell.value, r)
    return banner


def _mp_key(mp):
    try:
        return float(mp)
    except (TypeError, ValueError):
        return float("inf")


_ROW_REF = re.compile(r"(?<=[A-Z$])(\d+)(?![\d(])")


def _reanchor(value, row: int):
    """Repoint a formula's relative row references after the sort moved it.

    Every formula on this sheet refers only to its own row, so rewriting the
    row number is the whole job. Absolute ranges ($A$1:$B$26) keep their rows
    because the digits there follow a "$".
    """
    if not isinstance(value, str) or not value.startswith("="):
        return value
    return re.sub(r"(?<![$\d])([A-Z]{1,2})(\d+)(?![\d(])",
                  lambda m: f"{m.group(1)}{row}", value)


# --------------------------------------------------------------------------- #
# moving rows without destroying the sheet
# --------------------------------------------------------------------------- #
def _capture_row(ws, r: int, ncol: int) -> list:
    from copy import copy
    out = []
    for c in range(1, ncol + 1):
        cell = ws.cell(row=r, column=c)
        out.append([cell.value, copy(cell.font), copy(cell.fill),
                    copy(cell.border), copy(cell.alignment),
                    cell.number_format, copy(cell.protection)])
    return out


def _write_row(ws, r: int, data: list) -> None:
    for c, (v, font, fill, border, align, numfmt, prot) in enumerate(data, 1):
        cell = ws.cell(row=r, column=c)
        cell.value = _reanchor(v, r)
        cell.font, cell.fill, cell.border = font, fill, border
        cell.alignment, cell.number_format, cell.protection = align, numfmt, prot


def cut_and_paste_row(ws, src_row: int, insert_before: int) -> int:
    """Move one whole row the way Excel cut-and-insert does.

    Values, fills, fonts, number formats and formulas travel TOGETHER, and the
    row's self-referencing formulas are re-anchored to where it lands. This
    exists because a values-only re-sort once scrambled an engineer's reviewed
    fiche: every colour, date format, group header and blank separator stayed
    at its old address while the data moved out from under it. Whole rows move
    as units or not at all.

    Returns the row the data landed on. Call :func:`reanchor_sheet` after a
    batch of moves, since every insert and delete shifts the rows below it.
    """
    data = _capture_row(ws, src_row, ws.max_column)
    ws.delete_rows(src_row)
    at = insert_before - 1 if src_row < insert_before else insert_before
    ws.insert_rows(at)
    _write_row(ws, at, data)
    return at


def reanchor_sheet(ws) -> int:
    """Repoint every self-row formula to its current row, sheet-wide."""
    n = 0
    for r in range(2, ws.max_row + 1):
        for c in range(1, ws.max_column + 1):
            cell = ws.cell(row=r, column=c)
            if isinstance(cell.value, str) and cell.value.startswith("="):
                fixed = _reanchor(cell.value, r)
                if fixed != cell.value:
                    cell.value = fixed
                    n += 1
    return n
