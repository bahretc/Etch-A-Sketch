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

* one of them inside the study limits, AND the coded milepost within ``band``
  of those limits -> the crash could be in the study, so the report gets
  pulled: **?**
* otherwise **NIS**, no report needed

Naming a study feature is not on its own enough, because the fiche also gives
the DISTANCE from it. Crash 108416549 is measured 5.000 miles east of NC 9: it
names a feature inside the limits and sits five miles clear of them. ``band``
is how much milepost error the review is willing to entertain, and it is the
engineer's call rather than a fact; 0.5 mi is the default.

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

from openpyxl.styles import PatternFill

#: Inside the limits, north/east of them, south/west of them.
FILL_IN = PatternFill("solid", fgColor="C6EFCE")
FILL_NE = PatternFill("solid", fgColor="BDD7EE")
FILL_SW = PatternFill("solid", fgColor="FFEB9C")

STATUS_ORDER = {"IS": 0, "?": 1, "NIS": 2}

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
                 route="US 74", coded_mp=None, band=0.5) -> str:
    """"?" if a report is worth pulling for this crash, else "NIS".

    ``band`` is how far outside the limits a coded milepost may sit and still
    be worth checking. A green cell alone is not enough: crash 108416549 is
    measured 5.000 miles east of NC 9, so it names a study feature and is
    nowhere near the study. The band is the milepost error the review is
    willing to entertain, and it is the engineer's call, not a fact.
    """
    on = normalize_feature(on_road)
    if on and on != route.upper():
        # A cross-street crash sits where that street meets the study route.
        bucket, _ = classify(on_road, features, lo, hi)
        return "?" if bucket == "in" else "NIS"
    marks = [classify(r, features, lo, hi) for r in (from_road, toward_road)]
    near = (coded_mp is None or coded_mp == 999.999
            or lo - band <= coded_mp <= hi + band)
    if any(bucket == "in" for bucket, _ in marks) and near:
        return "?"          # names a study feature AND is coded near the limits
    # A bracket that merely straddles the limits is NOT enough. Crash 108018739
    # is measured 6.000 miles west of MILE 167, which puts it at MP 8.655; its
    # other endpoint, MILE 163, sits below the limits, so the pair straddles
    # them while the crash itself is four miles clear. The Miles field already
    # pinned it, and the coded milepost agrees.
    if not any(mp is not None for _, mp in marks):
        return "?"          # nothing resolved, so nothing rules it out
    return "NIS"


def screen_sheet(ws, features: dict, lo: float, hi: float, initial_ids,
                 route: str = "US 74", col=None, band: float = 0.5) -> dict:
    """Fill IS?, colour the From/Toward cells, and sort. Returns a tally."""
    col = col or {"on": 2, "from": 5, "toward": 6, "mproad": 7, "mp": 8,
                  "is": 9, "id": 12}
    initial = {int(c) for c in initial_ids}
    tally = {"IS": 0, "?": 0, "NIS": 0}

    rows = []
    for r in range(2, ws.max_row + 1):
        cid = ws.cell(row=r, column=col["id"]).value
        if cid is None:
            continue
        on = ws.cell(row=r, column=col["on"]).value
        fr = ws.cell(row=r, column=col["from"]).value
        tw = ws.cell(row=r, column=col["toward"]).value
        status = ("IS" if cid in initial
                  else needs_review(fr, tw, on, features, lo, hi, route,
                                    coded_mp=_mp_key(ws.cell(row=r, column=col["mp"]).value),
                                    band=band))
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
    return tally


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
