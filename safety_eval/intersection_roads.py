"""Fiche roads and intersection road combinations (docs/03 rule 5, docs/09).

An intersection analysis is road-combination-dependent: TEAAS finds a crash
only when its coded road pair matches an entered combination inside the
Y-line. Two different lists come out of the same leg description:

* **Fiche roads** are the wide net for the fiche pull: every leg road plus
  the defensive suffix variants a coder might have used (a US route number
  present at the junction goes in as plain, ALT, BYP and BUS), plus any
  extra spellings the engineer supplies. A crash sitting on a
  defensive-only road shows in the fiche but not the analysis, which is
  exactly what makes it an ADD candidate at review.
* **Combinations** are the real geometry only: each cross-leg road paired
  with each mainline road. Side streets that merely end at the mainline
  never intersect each other, so cross x cross pairs are not generated,
  and same-street pairs (US 19 x PATTON AVE) never are.

Road codes follow docs/09: class digit (1 interstate, 2 US, 3 NC, 4
secondary), then for US routes a suffix digit (0 plain, 1 ALT, 2 BYP,
9 BUS), then the zero-padded route number: US 74ALT = 21000074,
SR 1319 = 40001319. Local street names carry county-assigned 5-prefix
codes that only the TEAAS road search can give, so they render with the
code left for the engineer to fill. Suffixed non-US routes (an NC 24ALT)
have no observed code convention and are flagged to verify rather than
guessed.

**Naming:** no space between the route number and ALT, BUS or BYP
(US 74ALT, never "US 74 ALT"), matching the TEAAS road table.
"""
from __future__ import annotations

import re
from dataclasses import dataclass

ROUTE_RE = re.compile(
    r"^\s*(I|US|NC|SR)[\s-]*0*(\d+)\s*[- ]?\s*(ALT|BUS|BYP)?\s*$", re.I)

CLASS_DIGIT = {"I": "1", "US": "2", "NC": "3", "SR": "4"}
US_SUFFIX_DIGIT = {"": "0", "ALT": "1", "BYP": "2", "BUS": "9"}
US_SUFFIXES = ("", "ALT", "BYP", "BUS")

SEARCH_NOTE = "code from the TEAAS road search"
VERIFY_NOTE = "no observed code convention; verify in TEAAS"


@dataclass(frozen=True)
class Road:
    """One road as TEAAS knows it: canonical name, code when derivable."""
    name: str                     # canonical: "US 74ALT", "SR 1319", "PATTON AVE"
    code: str | None = None       # 8-digit TEAAS road code, or None
    source: str = "leg"           # leg | defensive | extra
    note: str = ""

    def __str__(self) -> str:
        return self.name


def parse_road(text: str, source: str = "leg") -> Road:
    """A road as typed -> canonical :class:`Road`.

    Accepts the suffix with or without a space ("US 74 ALT", "US 74ALT",
    "us 74-alt") and always renders it attached. Anything that is not a
    route reads as a local street name, uppercased, code from the road
    search.
    """
    m = ROUTE_RE.match(text)
    if not m:
        name = " ".join(text.split()).upper()
        if not name:
            raise ValueError("empty road name")
        return Road(name, None, source, SEARCH_NOTE)
    cls, num, suffix = m.group(1).upper(), m.group(2), (m.group(3) or "").upper()
    name = f"{cls} {int(num)}{suffix}"
    if cls == "US":
        code = "2" + US_SUFFIX_DIGIT[suffix] + f"{int(num):06d}"
    elif suffix:
        return Road(name, None, source, VERIFY_NOTE)
    else:
        code = CLASS_DIGIT[cls] + "0" + f"{int(num):06d}"
    return Road(name, code, source)


def leg_group(names) -> list[Road]:
    """Parse one leg's names, keeping order, dropping duplicates."""
    out, seen = [], set()
    for n in names:
        r = parse_road(str(n))
        if r.name not in seen:
            seen.add(r.name)
            out.append(r)
    return out


def defensive_roads(groups: list[list[Road]]) -> list[Road]:
    """Every US suffix form not already a leg, for each US number present.

    A coder who drops or swaps a suffix produces one of these; they go in
    the fiche pull so the crash surfaces, and stay out of the
    combinations because they are not the junction's geometry.
    """
    present = {r.name for g in groups for r in g}
    numbers = []
    for g in groups:
        for r in g:
            m = ROUTE_RE.match(r.name)
            if m and m.group(1).upper() == "US" and int(m.group(2)) not in numbers:
                numbers.append(int(m.group(2)))
    out = []
    for num in numbers:
        for suffix in US_SUFFIXES:
            name = f"US {num}{suffix}"
            if name not in present:
                out.append(Road(name, "2" + US_SUFFIX_DIGIT[suffix]
                                + f"{num:06d}", "defensive",
                                "in case the fiche coded it this way"))
    return out


def fiche_roads(mainline: list[Road], crosses: list[list[Road]],
                extra=()) -> list[Road]:
    """The wide net: legs, then defensive variants, then extra spellings."""
    groups = [mainline] + list(crosses)
    out = [r for g in groups for r in g]
    out += defensive_roads(groups)
    seen = {r.name for r in out}
    for n in extra:
        r = parse_road(str(n), source="extra")
        if r.name not in seen:
            seen.add(r.name)
            out.append(r)
    return out


def combinations(mainline: list[Road],
                 crosses: list[list[Road]]) -> list[tuple[Road, Road]]:
    """Each cross-leg road x each mainline road; nothing else.

    Side streets end at the mainline and never intersect one another, so
    no cross x cross pair is generated, and no same-street pair either.
    """
    return [(c, m) for group in crosses for c in group for m in mainline]


def render(mainline: list[Road], crosses: list[list[Road]],
           extra=()) -> str:
    """Both lists as plain text for entry into TEAAS."""
    roads = fiche_roads(mainline, crosses, extra)
    combos = combinations(mainline, crosses)
    lines = ["FICHE ROADS"]
    for r in roads:
        code = r.code or "________"
        tag = "" if r.source == "leg" else f"  [{r.source}]"
        note = f"  ({r.note})" if r.note else ""
        lines.append(f"  {r.name:<18} {code}{tag}{note}")
    lines += ["", f"INTERSECTION COMBINATIONS ({len(combos)})"]
    for c, m in combos:
        lines.append(f"  {c.name:<18} x  {m.name}")
    return "\n".join(lines)
