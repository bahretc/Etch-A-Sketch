"""Core data models for the NCDOT safety-evaluation pipeline."""
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date
from typing import Optional


@dataclass
class Crash:
    """A single crash record parsed from a TEAAS fiche.

    The five coded columns are kept as raw values (``t``/``c``/``f``/``l``/``s``);
    semantic meaning is applied later via the column-role config so that no
    analysis code hard-codes which letter means what.
    """
    crash_id: str
    date: Optional[date] = None
    muni_code: str = ""
    on_road: str = ""
    miles: Optional[float] = None
    dir_from: str = ""
    from_road: str = ""
    toward_road: str = ""
    milepost_road: str = ""
    mp: Optional[float] = None
    ma: str = ""
    # raw coded columns, as printed on the fiche: T C F L S
    t: Optional[int] = None
    c: Optional[int] = None
    f: Optional[int] = None
    l: Optional[int] = None
    s: str = ""
    comments: str = ""

    # populated by the classifier
    in_study: Optional[bool] = None
    period: Optional[str] = None          # "before" | "construction" | "after" | None
    target_types: list[str] = field(default_factory=list)

    def coded(self, role_letter: str):
        """Return the raw value of a fiche column by its letter (T/C/F/L/S)."""
        return getattr(self, role_letter.lower())


@dataclass
class Assignment:
    """The 'initial study' scope: everything defined by the assignment/assumptions."""
    project_id: str = ""
    description: str = ""
    county: str = ""
    route: str = ""                       # primary study route name as on the fiche
    section_begin_mp: Optional[float] = None
    section_end_mp: Optional[float] = None
    intersection_study: bool = False      # segment vs. intersection evaluation
    length_miles: Optional[float] = None

    countermeasure: str = ""
    target_crash_types: list[str] = field(default_factory=list)

    # study window / periods
    study_start: Optional[date] = None
    study_end: Optional[date] = None
    construction_start: Optional[date] = None
    construction_end: Optional[date] = None
    construction_months: Optional[int] = None

    # traffic
    aadt_before: Optional[float] = None
    aadt_after: Optional[float] = None

    assumptions: list[str] = field(default_factory=list)
    notes: str = ""


@dataclass
class Period:
    name: str
    start: date
    end: date

    @property
    def days(self) -> int:
        return (self.end - self.start).days + 1

    @property
    def years(self) -> float:
        return self.days / 365.25


@dataclass
class PeriodStats:
    period: str
    years: float
    aadt: Optional[float]
    total: int = 0
    by_severity: dict = field(default_factory=dict)
    by_target: dict = field(default_factory=dict)
    injuries: int = 0
    fatalities: int = 0
    epdo: float = 0.0

    @property
    def crash_rate(self) -> Optional[float]:
        """Crashes per million vehicle-miles (segment) — needs aadt & length set externally."""
        return None  # computed in analysis where length is known


@dataclass
class EvaluationResult:
    assignment: Assignment
    periods: dict                         # name -> Period
    stats: dict                           # name -> PeriodStats
    crashes: list                         # list[Crash]
    before_after: dict = field(default_factory=dict)
    warnings: list[str] = field(default_factory=list)
