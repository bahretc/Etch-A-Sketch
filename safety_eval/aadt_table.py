"""Evaluation Set-up AADT leg table from NCDOT station counts (docs/02, docs/04).

The Intersection Evaluation Workbook wants one AADT per leg per year for every
year in the study window. NCDOT counts each station on a two year cycle (odd or
even years), so most cells are estimates. The team convention (docs/02):

* black font: the value is an NCDOT published AADT for that year (a count, or
  a value the engineer accepts as published);
* red font: interpolated between counts, carried forward past the last count,
  carried back before the first, or assumed from another leg.

Minor (side) road estimates round to the nearest hundred (CLAUDE.md rule 7);
major road interpolations keep the 50 vpd granularity the completed workbooks
use. 2020 is never a representative year. The representative year of a period
is the last year in it that has a published value on any leg.

Nothing here writes to a workbook; :mod:`setup_sheet` takes the values and
:mod:`workbook_cells` applies the colours.
"""
from __future__ import annotations

from dataclasses import dataclass, field

BLACK, RED = "black", "red"
MINOR_ROUND = 100
MAJOR_ROUND = 50
EXCLUDED_REP_YEARS = (2020,)


@dataclass
class LegSeries:
    """Published values for one leg. ``assumed_from`` marks a leg with no
    station whose values copy another leg (every cell red)."""
    name: str                                   # leg1..leg4
    published: dict = field(default_factory=dict)   # {year: aadt} shown black
    is_minor: bool = False
    assumed_from: str | None = None
    round_to: int | None = None                 # override rounding

    @property
    def rounding(self) -> int:
        if self.round_to:
            return self.round_to
        return MINOR_ROUND if self.is_minor else MAJOR_ROUND


@dataclass
class LegCell:
    year: int
    value: int | None
    colour: str | None            # BLACK / RED / None (no value)
    source: str                   # published | interpolated | carried | assumed | none


def _round_half_up(x: float, step: int) -> int:
    q = x / step
    n = int(q)
    if q - n >= 0.5:
        n += 1
    return n * step


def fill_series(series: LegSeries, years: list[int],
                assumed_values: dict | None = None) -> dict[int, LegCell]:
    """Fill every year of ``years`` for one leg.

    ``assumed_values`` supplies the cells of the leg named in
    ``series.assumed_from`` (already filled); the result copies their values
    in red.
    """
    if series.assumed_from:
        out = {}
        for y in years:
            src = (assumed_values or {}).get(y)
            v = src.value if src else None
            out[y] = LegCell(y, v, RED if v is not None else None,
                             "assumed" if v is not None else "none")
        return out

    pub = {int(y): int(v) for y, v in series.published.items() if v is not None}
    if not pub:
        return {y: LegCell(y, None, None, "none") for y in years}
    pub_years = sorted(pub)
    step = series.rounding
    out: dict[int, LegCell] = {}
    for y in years:
        if y in pub:
            out[y] = LegCell(y, pub[y], BLACK, "published")
            continue
        before = [p for p in pub_years if p < y]
        after = [p for p in pub_years if p > y]
        if before and after:
            y0, y1 = before[-1], after[0]
            v = pub[y0] + (pub[y1] - pub[y0]) * (y - y0) / (y1 - y0)
            out[y] = LegCell(y, _round_half_up(v, step), RED, "interpolated")
        elif before:
            out[y] = LegCell(y, pub[before[-1]], RED, "carried")
        else:
            out[y] = LegCell(y, pub[after[0]], RED, "carried")
    return out


def intersection_table(legs: dict[str, LegSeries],
                       years: list[int]) -> dict[int, dict[str, LegCell]]:
    """{year: {leg: LegCell}} for all legs, resolving assumed legs last."""
    filled: dict[str, dict[int, LegCell]] = {}
    pending = dict(legs)
    # independent legs first
    for name, s in list(pending.items()):
        if not s.assumed_from:
            filled[name] = fill_series(s, years)
            del pending[name]
    for name, s in pending.items():
        src = filled.get(s.assumed_from)
        if src is None:
            raise ValueError(f"{name} assumed from unknown leg {s.assumed_from!r}")
        filled[name] = fill_series(s, years, assumed_values=src)
    return {y: {name: filled[name][y] for name in legs} for y in years}


def to_legs_by_year(table: dict[int, dict[str, LegCell]]) -> dict[int, dict[str, int]]:
    """Shape consumed by :class:`setup_sheet.SetupData.legs_by_year`."""
    out = {}
    for y, legs in table.items():
        row = {name: c.value for name, c in legs.items() if c.value is not None}
        if row:
            out[y] = row
    return out


def colours_by_year(table: dict[int, dict[str, LegCell]]) -> dict[int, dict[str, str]]:
    return {y: {name: c.colour for name, c in legs.items() if c.colour}
            for y, legs in table.items()}


def representative_year(table: dict[int, dict[str, LegCell]],
                        period_years: list[int],
                        exclude: tuple = EXCLUDED_REP_YEARS) -> int | None:
    """Last year of the period with a published value on any leg, never 2020."""
    for y in sorted(period_years, reverse=True):
        if y in exclude or y not in table:
            continue
        if any(c.source == "published" for c in table[y].values()):
            return y
    return None


def intersection_volume(table: dict[int, dict[str, LegCell]], year: int) -> dict:
    """Major average + minor average, and the ROUND(-2) the sheet prints."""
    legs = table[year]
    major = [legs[n].value for n in ("leg1", "leg2") if n in legs and legs[n].value is not None]
    minor = [legs[n].value for n in ("leg3", "leg4") if n in legs and legs[n].value is not None]
    major_avg = sum(major) / len(major) if major else 0.0
    minor_avg = sum(minor) / len(minor) if minor else 0.0
    total = major_avg + minor_avg
    return {"major": major_avg, "minor": minor_avg, "total": total,
            "rounded": _round_half_up(total, 100)}


def series_from_station(name: str, station_years: dict[int, int], *,
                        is_minor: bool = False,
                        years: list[int] | None = None) -> LegSeries:
    """Build a LegSeries from an :class:`aadt_arcgis.AadtStation` year map."""
    pub = {y: v for y, v in station_years.items()
           if v and (years is None or y in years)}
    return LegSeries(name=name, published=pub, is_minor=is_minor)


def describe(table: dict[int, dict[str, LegCell]]) -> str:
    """Plain text summary for logs and the assistant."""
    names = list(next(iter(table.values())).keys()) if table else []
    lines = ["year  " + "  ".join(f"{n:>14}" for n in names)]
    for y in sorted(table):
        cells = table[y]
        lines.append(f"{y}  " + "  ".join(
            f"{(str(c.value) if c.value is not None else '-'):>8} {c.colour or '':<5}"
            for c in (cells[n] for n in names)))
    return "\n".join(lines)
