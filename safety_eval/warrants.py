"""NCDOT HSIP section warrants (2024 HSIP Overview, May 2024).

Three kinds of study share this crash-analysis core: Fatal Crash Analyses,
HSIP Package Analyses, and Evaluations. Only the HSIP packages ask whether a
location *warrants* a project, and that question is this module.

A section warrant is two tests in series. First the location has to be big
enough to be worth looking at, by total crashes AND by crashes per mile over
the 5-year analysis period:

    facility                     min total   min crashes/mile
    All Freeway Sections            30              30
    US Non-Freeway Route            20              40
    NC Non-Freeway Route            15              30
    SR Non-Freeway Route            12              24
    City Non-Freeway Street         20              40

Then a specific pattern has to dominate. Freeway warrants F-1 to F-4,
non-freeway N-1 to N-4, each a percentage of total crashes.

**Animal crashes are excluded from the whole analysis**, not just from the
numerator. The Overview is explicit: they were removed "to assist in
identifying target crash locations", because deer crashes on rural routes are
not something a countermeasure addresses. So they come out of the total, out
of the rate, and out of every percentage.
"""
from __future__ import annotations

from dataclasses import dataclass, field

#: T codes that count as run-off-road for F-1, F-2, N-1, N-2. The Overview
#: lists: Run Off Road (right, left or straight), Fixed Object,
#: Overturn/Rollover, Sideswipe Opposite Direction, Parked Motor Vehicle,
#: Head On. ROR-T and PMV are easy to leave out by eye and both belong.
ROR_TYPES = {"ROR-R", "ROR-L", "ROR-T", "FO", "overturn", "SSOD", "PMV",
             "head-on"}

#: Excluded from the section analysis entirely (Overview, Section Warrants).
EXCLUDED_TYPES = {"animal"}

#: Road-condition code meaning a wet surface, and light codes meaning dark.
#: Taken from the engineer's own conditional formatting on the working sheet:
#: C between 1.1 and 2.9 selects 2; L between 3.1 and 5.9 selects 4 and 5.
WET_CODES = {2}
DARK_CODES = {4, 5}

#: (minimum total crashes, minimum crashes per mile) by facility type.
FACILITY_MINIMUMS = {
    "freeway": (30, 30),
    "us": (20, 40),
    "nc": (15, 30),
    "sr": (12, 24),
    "city": (20, 40),
}

#: Warrant -> (facility class, what fraction of total crashes, description).
SECTION_WARRANTS = {
    "F-1": ("freeway", 0.48, "Run Off Road during Wet Road Conditions"),
    "F-2": ("freeway", 0.80, "Run Off Road"),
    "F-3": ("freeway", 0.55, "Wet Road Condition"),
    "F-4": ("freeway", 0.52, "Night Location"),
    "N-1": ("nonfreeway", 0.35, "Run Off Road during Wet Road Conditions"),
    "N-2": ("nonfreeway", 0.68, "Run Off Road"),
    "N-3": ("nonfreeway", 0.48, "Wet Road Condition"),
    "N-4": ("nonfreeway", 0.38, "Non-Intersection Night Location"),
}


@dataclass
class Crash:
    """The fields a section warrant looks at."""
    crash_id: str = ""
    crash_type: str = ""          # decoded Type, e.g. "ROR-L"
    road_condition: int | None = None      # C
    light_condition: int | None = None     # L
    at_intersection: bool = False          # for N-4 only

    @property
    def is_animal(self) -> bool:
        return self.crash_type in EXCLUDED_TYPES

    @property
    def is_ror(self) -> bool:
        return self.crash_type in ROR_TYPES

    @property
    def is_wet(self) -> bool:
        return self.road_condition in WET_CODES

    @property
    def is_dark(self) -> bool:
        return self.light_condition in DARK_CODES


@dataclass
class WarrantResult:
    warrant: str
    description: str
    threshold: float
    count: int
    total: int
    met: bool
    note: str = ""

    @property
    def share(self) -> float:
        return self.count / self.total if self.total else 0.0


@dataclass
class SectionScreen:
    """The whole answer for one section."""
    facility: str
    length_mi: float
    total: int
    animal_excluded: int
    rate: float
    min_total: int
    min_rate: int
    meets_minimums: bool
    warrants: list = field(default_factory=list)

    @property
    def met(self) -> list:
        return [w for w in self.warrants if w.met]


def screen_section(crashes, length_mi: float, facility: str = "freeway",
                   ) -> SectionScreen:
    """Run the section warrants for one location.

    ``crashes`` are the in-study crashes (IS + RE + ADD) for the 5-year
    analysis period. ``facility`` keys into FACILITY_MINIMUMS.
    """
    if facility not in FACILITY_MINIMUMS:
        raise ValueError(f"facility must be one of {sorted(FACILITY_MINIMUMS)}")
    if length_mi <= 0:
        raise ValueError("section length must be positive")

    animals = [c for c in crashes if c.is_animal]
    kept = [c for c in crashes if not c.is_animal]
    total = len(kept)
    rate = total / length_mi
    min_total, min_rate = FACILITY_MINIMUMS[facility]
    meets = total >= min_total and rate >= min_rate

    klass = "freeway" if facility == "freeway" else "nonfreeway"
    out = []
    for name, (fac, threshold, desc) in SECTION_WARRANTS.items():
        if fac != klass:
            continue
        if name in ("F-1", "N-1"):
            n = sum(1 for c in kept if c.is_ror and c.is_wet)
            base = total
        elif name in ("F-2", "N-2"):
            n = sum(1 for c in kept if c.is_ror)
            base = total
        elif name in ("F-3", "N-3"):
            n = sum(1 for c in kept if c.is_wet)
            base = total
        elif name == "F-4":
            n = sum(1 for c in kept if c.is_dark)
            base = total
        else:                                   # N-4
            # The only warrant whose base is not the total: non-intersection
            # crashes, and whose numerator is ROR crashes in the dark.
            ni = [c for c in kept if not c.at_intersection]
            n, base = sum(1 for c in ni if c.is_ror and c.is_dark), len(ni)
        share = n / base if base else 0.0
        out.append(WarrantResult(
            warrant=name, description=desc, threshold=threshold, count=n,
            total=base, met=meets and share >= threshold,
            note="" if meets else "minimums not met"))

    return SectionScreen(facility=facility, length_mi=length_mi, total=total,
                         animal_excluded=len(animals), rate=rate,
                         min_total=min_total, min_rate=min_rate,
                         meets_minimums=meets, warrants=out)


def format_screen(s: SectionScreen) -> str:
    """A plain report, docs/05 style."""
    lines = [
        f"Facility: {s.facility}   Length: {s.length_mi:.3f} mi",
        f"Total crashes: {s.total}   (animal crashes excluded: {s.animal_excluded})",
        f"Crashes per mile: {s.rate:.1f}",
        f"Minimums: {s.min_total} total and {s.min_rate} per mile -> "
        f"{'MET' if s.meets_minimums else 'NOT MET'}",
        "",
    ]
    for w in s.warrants:
        flag = "MET" if w.met else "not met"
        lines.append(f"  {w.warrant}  {w.description}")
        lines.append(f"        {w.count}/{w.total} = {w.share:.1%} "
                     f"(needs {w.threshold:.0%})  {flag}")
    return "\n".join(lines)
