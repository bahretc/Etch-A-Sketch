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
from dataclasses import dataclass

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


_STREET_SUFFIX = re.compile(
    r"\s+(AVE|AVENUE|RD|ROAD|ST|STREET|DR|DRIVE|LN|LANE|PL|PLACE|BLVD|"
    r"BOULEVARD|CT|COURT|WAY|PKWY|PARKWAY|HWY|HIGHWAY|CIR|CIRCLE|TRL|"
    r"TRAIL|TER|TERRACE|LOOP|EXT)$")


def lookup_feature(name, features: dict):
    """The feature's mileposts, matching a fiche street the way the
    Features Report names it: ``*LCL TAMPA AVE`` finds ``TAMPA``."""
    key = normalize_feature(name)
    mps = features.get(key)
    if not mps and key:
        mps = features.get(_STREET_SUFFIX.sub("", key))
    return mps or None


def _leg_name(raw) -> str | None:
    """A fiche On/From/Toward cell as a junction leg name, or None when it
    is a numbered address (``*LCL 120 PATTON AVE``), which places the crash
    by geocoding, not by the road it is on. ``PVA PATTON AVE`` is a
    driveway on Patton and reads as PATTON."""
    s = normalize_feature(raw)
    s = re.sub(r"^\*\w*\s*", "", s)
    s = re.sub(r"^PVA\s+", "", s)
    if not s or re.match(r"^\d", s):
        return None
    return _STREET_SUFFIX.sub("", s)


def classify(name, features: dict, lo: float, hi: float, near=None):
    """``(bucket, milepost)`` for one From/Toward cell.

    bucket is "in", "ne", "sw", or None when the feature is not on the study
    route at all and therefore says nothing about where the crash was.

    ``near``: when a feature name repeats along the route (HAYWOOD meets
    US 19 at 9.651 and again at 10.157) and the row is mileposted on that
    route, the instance TEAAS measured from is the one nearest the coded
    milepost, so only that one is judged. This reads TEAAS's placement of
    the reference feature, not the officer's distance. Without ``near``
    every instance counts, and any one inside the limits is "in".
    """
    mps = lookup_feature(name, features)
    if not mps:
        return None, None
    if near is not None and len(mps) > 1:
        mps = [min(mps, key=lambda m: abs(m - near))]
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
                 route: str = "US 74", col=None, study="evaluation",
                 off_lrs_nis: bool = False) -> dict:
    """Fill IS?, colour the From/Toward cells, and sort. Returns a tally.

    ``off_lrs_nis``: on a strip study a row ON the study route whose Milepost
    Road is a different linear reference (US 311 mileposted on "I 74 WB
    COUPLET", a concurrent freeway section miles away) can never fall in the
    route's milepost window, so it is NIS without a review. This is not the
    coded distance (which is never used to skip a review, docs/03); it is
    the road the milepost is measured on. Off by default; the engineer turns
    it on per study (docs/03, 2026-09).

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
        # DEL exists only inside the Initial Study branch (docs/03): an
        # animal crash the study never contained is NIS, final, unreviewed -
        # animals are not considered on an HSIP study, so it neither joins
        # the study (never ADD) nor earns a "?". Marking it DEL would put an
        # off-branch status on 100+ rows of a real corridor fiche.
        animal = kind.deletes_animals and T_CODES.get(t) == ANIMAL_TYPE
        mproad = normalize_feature(ws.cell(row=r, column=col["mproad"]).value)
        off_lrs = (off_lrs_nis and mproad and mproad != route.upper()
                   and normalize_feature(on) == route.upper())
        if cid in initial:
            status = "DEL" if animal else "IS"
        elif animal or off_lrs:
            status = "NIS"
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

    _finish_sheet(ws, rows, col)
    return tally


def _finish_sheet(ws, rows, col) -> None:
    """Write the classified rows back sorted IS / ? / NIS, colour the
    From/Toward cells, format, and place the unreviewed banner."""
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


# --------------------------------------------------------------------------- #
# the intersection screen (docs/03: 150 ft rule, road-combination-dependent)
# --------------------------------------------------------------------------- #
@dataclass
class LegScreen:
    """One mileposted leg of the intersection.

    ``route`` is the Milepost Road as the fiche writes it ("US 19");
    ``aliases`` are the other On Road names for the same pavement ("US 23",
    "US 74ALT", "PATTON"), which the strip rule would otherwise mistake for
    cross streets; ``features`` is that route's Features Report and
    ``lo``/``hi`` the junction milepost plus and minus the Y-line.
    """
    route: str
    features: dict
    lo: float
    hi: float
    aliases: tuple = ()

    def names(self) -> set:
        return {normalize_feature(self.route)} | {normalize_feature(a)
                                                  for a in self.aliases}


def screen_intersection_sheet(ws, legs: list, initial_ids, col=None,
                              study: str = "fatal", coords: dict | None = None,
                              junction: tuple | None = None,
                              radius_mi: float = 0.1,
                              off_lrs_nis: bool = False,
                              cross_names=()) -> tuple[dict, dict]:
    """Fill IS?, colour, sort and banner an intersection fiche sheet.

    A wide-net fiche (every leg road, countywide) is screened leg by leg:

    * a row mileposted on a leg, or coded On one of its aliases, is placed
      by the colour rule against THAT leg's Features Report and window
      (green or a bracket -> ?, both sides the same -> NIS);
    * a row coded On a real cross street of a leg sits where that street
      meets the leg (the strip rule), so it is ? only when that meeting is
      inside the window;
    * a row on no screened leg is ? when its On/From/Toward names touch two
      different legs of this junction, because that pair IS one of the
      study's road combinations; otherwise nothing places it.

    What nothing places is **unresolved**. With ``coords`` (crash id ->
    (lat, lon), the DetailedFiche coordinates, engineer-sanctioned for
    deciding which reports to pull) and the ``junction`` point, an
    unresolved row further than ``radius_mi`` is NIS and one inside it is
    ?; with no coordinate it stays ?, since nothing rules it out. The coded
    distance is never used (docs/03).

    ``off_lrs_nis`` is the docs/03 off-LRS rule for an intersection: a row
    mileposted on a linear reference that is none of the ``legs`` (PATTON
    downtown when the junction is on US 19's mileposting; I 240) cannot be
    at the junction, so it is NIS without a review. This is the road the
    milepost is measured on, never the coded distance. Off by default; the
    engineer turns it on per study. ``cross_names`` are junction legs with
    no mileposting of their own (ORMAND, HANOVER), so that a row naming one
    of them together with another leg counts as a road combination.

    Returns ``(tally, reasons)``; ``reasons`` maps crash id to
    ``(status, why)`` so the engineer can see every call.
    """
    from .location import haversine_mi

    kind = _st.get(study)
    col = col or {"on": 2, "from": 5, "toward": 6, "mproad": 7, "mp": 8,
                  "is": 9, "id": 12, "t": 14}
    initial = {int(c) for c in initial_ids}
    by_route = {normalize_feature(lg.route): lg for lg in legs}
    by_alias = {}
    for lg in legs:
        for a in lg.names():
            by_alias.setdefault(a, lg)
    groups = [lg.names() for lg in legs]
    groups += [{normalize_feature(n)} for n in cross_names]
    tally = {"IS": 0, "?": 0, "NIS": 0, "DEL": 0}
    reasons: dict = {}
    rows = []

    def _touches(names) -> int:
        return sum(1 for g in groups if names & g)

    for r in range(2, ws.max_row + 1):
        cid = ws.cell(row=r, column=col["id"]).value
        if cid is None:
            continue
        on = normalize_feature(ws.cell(row=r, column=col["on"]).value)
        fr_raw = ws.cell(row=r, column=col["from"]).value
        tw_raw = ws.cell(row=r, column=col["toward"]).value
        fr, tw = normalize_feature(fr_raw), normalize_feature(tw_raw)
        mproad = normalize_feature(ws.cell(row=r, column=col["mproad"]).value)
        t = ws.cell(row=r, column=col["t"]).value
        animal = T_CODES.get(t) == ANIMAL_TYPE
        buckets: dict = {}
        try:
            icid = int(str(cid).strip())
        except ValueError:
            icid = None

        if icid in initial:
            status, why = (("DEL", "animal, initial study")
                           if animal and kind.deletes_animals
                           else ("IS", "initial study"))
        elif animal:
            status, why = "NIS", "animal"
        else:
            mp = _mp_key(ws.cell(row=r, column=col["mp"]).value)
            mileposted = bool(mproad) and mp < 999
            on_key = _leg_name(on)
            leg = by_route.get(mproad) or (by_alias.get(on_key)
                                           if on_key else None)
            status, why = None, ""
            if off_lrs_nis and mileposted and mproad not in by_route:
                status, why = ("NIS", f"mileposted on {mproad}, which does "
                                      "not reach the junction")
            elif leg is not None:
                # a repeated feature name is judged at the instance TEAAS
                # measured from, when the row is mileposted on this leg
                near = mp if (mileposted and mproad == normalize_feature(
                    leg.route)) else None
                on_route = (not on) or (on_key in leg.names()
                                        if on_key else False)
                if on_route:
                    b = {k: classify(v, leg.features, leg.lo, leg.hi,
                                     near=near)[0]
                         for k, v in (("from", fr_raw), ("toward", tw_raw))}
                    buckets = b
                    known = [x for x in b.values() if x]
                    if "in" in known:
                        status, why = "?", f"measured off the junction on {leg.route}"
                    elif len(known) == 2 and known[0] != known[1]:
                        status, why = "?", f"From/Toward bracket the junction on {leg.route}"
                    elif len(known) == 2:
                        status, why = "NIS", f"both features the same side on {leg.route}"
                elif on_key:
                    # a crash on a cross street sits where that street meets
                    # the leg: by the Features Report, else by TEAAS's
                    # milepost of that meeting when the row carries one
                    b, _ = classify(on, leg.features, leg.lo, leg.hi,
                                    near=near)
                    if b is None and near is not None:
                        b = "in" if leg.lo <= near <= leg.hi else "out"
                    if b == "in":
                        status, why = "?", f"{on} meets {leg.route} at the junction"
                    elif b:
                        status, why = "NIS", f"{on} meets {leg.route} away from the junction"
            if status is None:
                keys = {k for k in (on_key, _leg_name(fr), _leg_name(tw)) if k}
                touched = _touches(keys)
                if touched >= 2:
                    status, why = "?", "names two legs of the junction"
                elif touched == 1 and on_key and not any(
                        on_key in g for g in groups):
                    # On a street that is no leg of this junction, measured
                    # off one leg: the crash is at that street's own meeting
                    # with the leg, somewhere else
                    status, why = ("NIS", f"on {on}, a side street off the "
                                          "leg it references")
            if status is None:
                d = None
                if coords and junction and icid in coords:
                    lat, lon = coords[icid]
                    d = haversine_mi(lat, lon, junction[0], junction[1])
                if d is None:
                    status, why = "?", "unresolved, no coordinate"
                elif d > radius_mi:
                    status, why = "NIS", f"coordinates {d * 5280:.0f} ft from the junction"
                else:
                    status, why = "?", f"coordinates {d * 5280:.0f} ft from the junction"

        tally[status] += 1
        reasons[str(cid)] = (status, why)
        values = [ws.cell(row=r, column=c).value
                  for c in range(1, ws.max_column + 1)]
        values[col["is"] - 1] = status
        rows.append(((STATUS_ORDER[status],
                      str(ws.cell(row=r, column=col["mproad"]).value or ""),
                      _mp_key(ws.cell(row=r, column=col["mp"]).value),
                      str(ws.cell(row=r, column=col["from"]).value or "")),
                     values, buckets))

    _finish_sheet(ws, rows, col)
    return tally, reasons


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


# --------------------------------------------------------------------------- #
# applying the engineer's review: the reviewed-workbook layout
# --------------------------------------------------------------------------- #
#: The reviewed working sheet's blocks, in order, exactly as the engineer's
#: own 41000079305 workbook lays them out: banner + rows per status, one
#: blank row between blocks. "?" holds mid-review saves (crashes still
#: awaiting their report); NIS splits by whether the report was reviewed.
REVIEW_BLOCKS = (
    ("IS", "IN STUDY"),
    ("RE", "REMILEPOSTED"),
    ("ADD", "ADDED TO STUDY"),
    ("DEL", "DELETED FROM STUDY"),
    ("?", "REPORT REVIEW REQUIRED"),
    ("NIS-R", "NOT IN STUDY - REPORT REVIEWED"),
    ("NIS", BANNER_TEXT),
)
#: Banner fills matching the engineer's workbook: theme accent for the study
#: blocks, light grey for reviewed NIS, darker grey for never-reviewed.
_BANNER_THEME = {"IS": (6, 0.40), "RE": (6, 0.40), "ADD": (6, 0.40),
                 "DEL": (6, 0.40), "?": (6, 0.40),
                 "NIS-R": (0, -0.15), "NIS": (0, -0.35)}
def _write_block_banner(ws, r: int, key: str, title: str) -> None:
    """A block heading reads as one band, so its fill runs the full row."""
    from openpyxl.styles import Color, Font, PatternFill
    cell = ws.cell(row=r, column=1, value=title)
    cell.font = Font(bold=True)
    theme, tint = _BANNER_THEME[key]
    fill = PatternFill("solid", fgColor=Color(theme=theme, tint=tint))
    header = [c for c in range(1, ws.max_column + 1)
              if ws.cell(row=1, column=c).value not in (None, "")]
    for c in range(1, (max(header) if header else ws.max_column) + 1):
        ws.cell(row=r, column=c).fill = fill


def apply_hsip_review(workbook_in: str, workbook_out: str, determinations,
                      sheet: str | None = None,
                      analysis_type: str = "section",
                      initial_ids=None) -> dict:
    """Write the engineer's determinations and regroup the working sheet.

    Output is the reviewed-workbook layout of the engineer's own 41000079305
    fiche: one banner per status block, rows keeping their original Milepost
    Road / MP / From Road order INSIDE every block, one blank row between
    blocks, reviewed NIS separated from never-reviewed NIS. Every row moves
    whole - values, formulas, fills, number formats - and formulas are
    re-anchored afterwards, which is the lesson the destroyed fiche sheet
    taught (docs/02).

    ``determinations`` carry crash_id, status, optional new_mp and comment
    (``review_queue.Determination`` or anything with those attributes). Each
    is validated against the branch vocabulary first (docs/03), with Initial
    Study membership when ``initial_ids`` is given; NOTHING is written while
    any determination is off-branch. A crash determined here counts as
    reviewed, so its NIS lands in the reviewed block, and NIS rows already
    sitting above the never-reviewed banner keep that standing on a re-save.
    Returns ``{block key: rows}``.
    """
    import openpyxl

    from .hsip import fiche_sheet_name, guard_no_drawings
    from .review_queue import validate_determination

    guard_no_drawings(workbook_in)
    wb = openpyxl.load_workbook(workbook_in)
    ws = wb[sheet or fiche_sheet_name(wb)]
    col = {"status": 9, "new_mp": 10, "id": 12, "comment": 21}

    initial = ({int(i) for i in initial_ids}
               if initial_ids is not None else None)
    problems_all = []
    for det in determinations:
        in_init = (int(det.crash_id) in initial) if initial is not None \
            else None
        problems = validate_determination(det, analysis_type,
                                          in_initial_study=in_init)
        if problems:
            problems_all.append(f"crash {det.crash_id}: "
                                + " ".join(problems))
    if problems_all:
        raise ValueError("refusing to write the review; "
                         + " | ".join(problems_all))
    dets = {str(d.crash_id).strip(): d for d in determinations}

    # An initial-study crash that TEAAS pulled from a road outside the fiche
    # roads has no row here (its ID sheet Fiche? reads NO). It is reviewed
    # like any other, so it gets a row built from the ID and Initial Study
    # sheets first (docs/03, engineer 2026-09, crash 108397584).
    on_sheet = {str(ws.cell(row=r, column=col["id"]).value).strip()
                for r in range(2, ws.max_row + 1)
                if ws.cell(row=r, column=col["id"]).value is not None}
    for cid_s, det in dets.items():
        if cid_s in on_sheet or not cid_s.isdigit():
            continue
        if initial is not None and int(cid_s) not in initial:
            continue
        if add_initial_study_row(wb, ws, cid_s, route=None) is None:
            continue                    # not an initial-study crash: ignored
        comment = getattr(det, "comment", "") or ""
        if not comment.lower().startswith("in initial study"):
            det.comment = "in initial study, not fiche; " + comment

    # Pass 1: apply the edits, then capture every crash row in sheet order.
    # Banners and blanks are not captured; the rebuild lays fresh ones.
    ncol = ws.max_column
    rows = []
    reviewed_prior: set = set()
    seen_unreviewed_banner = False
    for r in range(2, ws.max_row + 1):
        cid = ws.cell(row=r, column=col["id"]).value
        if cid is None:
            first = next((ws.cell(row=r, column=c).value
                          for c in range(1, ncol + 1)
                          if ws.cell(row=r, column=c).value not in (None, "")),
                         None)
            if isinstance(first, str) and first.strip() == BANNER_TEXT:
                seen_unreviewed_banner = True
            continue
        cid_s = str(cid).strip()
        det = dets.get(cid_s)
        if det is not None:
            ws.cell(row=r, column=col["status"], value=det.status)
            if getattr(det, "new_mp", None) is not None:
                ws.cell(row=r, column=col["new_mp"],
                        value=float(det.new_mp))
            comment = getattr(det, "comment", None)
            if comment:
                old = ws.cell(row=r, column=col["comment"]).value
                text = (f"{old}; {comment}"
                        if old and str(old).strip()
                        and str(old).strip() != str(comment).strip()
                        else comment)
                ws.cell(row=r, column=col["comment"], value=text)
        status = str(ws.cell(row=r, column=col["status"]).value or "").strip()
        if status == "NIS" and not seen_unreviewed_banner:
            reviewed_prior.add(cid_s)
        rows.append((cid_s, status, _capture_row(ws, r, ncol)))

    known = {key for key, _ in REVIEW_BLOCKS}
    bad = sorted({s for _, s, _ in rows if s and s not in known
                  and s != "NIS"})
    if bad:
        raise ValueError(f"unknown status(es) on the sheet: {bad}")

    # Pass 2: rebuild the data area as banner-headed blocks.
    if ws.max_row > 1:
        ws.delete_rows(2, ws.max_row - 1)
    blocks: dict = {key: [] for key, _ in REVIEW_BLOCKS}
    for cid_s, status, cap in rows:
        if status == "NIS":
            key = ("NIS-R" if cid_s in dets or cid_s in reviewed_prior
                   else "NIS")
        else:
            key = status or "?"
        blocks[key].append(cap)
    r, tally, first_block = 2, {}, True
    for key, title in REVIEW_BLOCKS:
        members = blocks[key]
        if not members:
            continue
        if not first_block:
            r += 1                                  # blank separator
        first_block = False
        _write_block_banner(ws, r, key, title)
        r += 1
        for cap in members:
            _write_row(ws, r, cap)
            r += 1
        tally[key] = len(members)
    reanchor_sheet(ws)
    wb.save(workbook_out)
    return tally


_SEVERITY_LETTER = {1: "K", 2: "A", 3: "B", 4: "C", 5: "O"}


def add_initial_study_row(wb, ws, crash_id: str, route: str | None = None):
    """Append a fiche row for an initial-study crash that is not on the
    fiche, from the ID sheet (road code, severity, date, time, T) and the
    Initial Study sheet (milepost, road surface, light). Returns the row,
    or None when the crash is not in the ID sheet's pasted export (then it
    is not an initial-study crash and nothing is written).

    The From / Toward cells stay blank and On Road carries the road code
    when no name is known; the engineer fills them from the report. The
    Type / Dir / Latitude / Longitude formulas are copied from the row
    above and re-anchored.
    """
    import datetime as _dt

    from .fiche_workbook import SHEET_ID, SHEET_INITIAL
    cid = str(crash_id).strip()
    road_code = sev = tcode = date = time = None
    found = False
    if SHEET_ID in wb.sheetnames:
        ids = wb[SHEET_ID]
        for r in range(2, ids.max_row + 1):
            if str(ids.cell(row=r, column=8).value or "").strip() == cid:
                found = True
                road_code = ids.cell(row=r, column=9).value
                sev = ids.cell(row=r, column=10).value
                date = ids.cell(row=r, column=11).value
                time = ids.cell(row=r, column=12).value
                tcode = ids.cell(row=r, column=13).value
                break
    if not found:
        return None
    mp = surface = light = mproad = None
    if SHEET_INITIAL in wb.sheetnames:
        ini = wb[SHEET_INITIAL]
        for r in range(1, ini.max_row + 1):
            if (mp is None
                    and str(ini.cell(row=r, column=2).value or "").strip() == cid):
                mp = ini.cell(row=r, column=3).value
                surface = ini.cell(row=r, column=12).value
                light = ini.cell(row=r, column=13).value
            v = ini.cell(row=r, column=1).value
            if v == "Strip Road" and mproad is None:
                mproad = ini.cell(row=r + 2, column=1).value
    new = ws.max_row + 1
    tmpl = next((r for r in range(ws.max_row, 1, -1)
                 if ws.cell(row=r, column=12).value is not None), None)
    if tmpl:
        for c in range(1, ws.max_column + 1):
            t = ws.cell(row=tmpl, column=c)
            n = ws.cell(row=new, column=c)
            v = t.value
            n.value = _reanchor(v, new) if isinstance(v, str) and v.startswith("=") else None
            n.number_format = t.number_format
    values = {1: 0, 2: str(road_code) if road_code is not None else "",
              7: route or mproad or "", 8: _num(mp), 12: int(cid),
              14: _num(tcode), 15: _num(surface), 16: 0, 17: _num(light),
              18: _SEVERITY_LETTER.get(_num(sev), "")}
    if isinstance(date, _dt.datetime):
        values[13] = date
    elif isinstance(date, _dt.date):
        values[13] = _dt.datetime(date.year, date.month, date.day)
    elif date:
        try:
            values[13] = _dt.datetime.strptime(str(date)[:10], "%m/%d/%Y")
        except ValueError:
            values[13] = str(date)
    for c, v in values.items():
        ws.cell(row=new, column=c, value=v)
    return new


def _num(v):
    try:
        f = float(str(v).strip())
    except (TypeError, ValueError):
        return None
    return int(f) if f.is_integer() else f
