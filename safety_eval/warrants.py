"""NCDOT HSIP warrants (2026 HSIP Warrants, March 2026; 2024 reproducible).

Three kinds of study share this crash-analysis core: Fatal Crash Analyses,
HSIP Package Analyses, and Evaluations. Only the HSIP packages ask whether a
location *warrants* a project, and that question is this module.

The thresholds are the ones NCDOT's Traffic Safety Systems Section published
as "2026 HSIP Warrants" (March 2026). The 2024 HSIP Overview (May 2024) is
kept as edition "2024" so an earlier study can be reproduced; the two differ
in four urban intersection thresholds and nothing else (INTERSECTION_
THRESHOLDS), and the 2026 text adds three warrants the 2024 Overview did not
have: BP-1 (non-motorist intersection), MB-1 (non-motorist midblock) and
B-1 (bridge).

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
numerator. The text is explicit: they were removed "to assist in
identifying target crash locations", because deer crashes on rural routes are
not something a countermeasure addresses. So they come out of the total, out
of the rate, and out of every percentage.
"""
from __future__ import annotations

from dataclasses import dataclass, field

from .fiche_workbook import T_CODES

#: The editions of the NCDOT warrant text this module can run. The app runs
#: DEFAULT_EDITION; the earlier edition stays reachable so a study screened
#: under it can be reproduced.
EDITIONS = ("2024", "2026")
DEFAULT_EDITION = "2026"
EDITION_NAMES = {"2024": "2024 HSIP Overview (May 2024)",
                 "2026": "2026 HSIP Warrants (March 2026)"}


def check_edition(edition) -> str:
    """The edition as its key, or ValueError when it is not one we hold."""
    key = str(edition).strip()
    if key not in EDITIONS:
        raise ValueError(
            f"edition must be one of {', '.join(EDITIONS)}, not {edition!r}")
    return key


#: T codes that count as run-off-road for F-1, F-2, N-1, N-2 and B-1. The
#: text lists: Run Off Road (right, left or straight), Fixed Object,
#: Overturn/Rollover, Sideswipe Opposite Direction, Parked Motor Vehicle,
#: Head On. ROR-T and PMV are easy to leave out by eye and both belong.
ROR_TYPES = {"ROR-R", "ROR-L", "ROR-T", "FO", "overturn", "SSOD", "PMV",
             "head-on"}

#: Excluded from the section analysis entirely (HSIP warrant text, Section
#: Warrants; also B-1).
EXCLUDED_TYPES = {"animal"}

#: Wet road condition and dark light condition, in fiche C and L codes.
#: From the warrants workbook, which is authoritative over the reading I first
#: took off the working sheet's conditional formatting:
#:   wet   COUNTIFS(C, ">=2", C, "<=3")   -> 2 AND 3, not 2 alone
#:   dark  COUNTIFS(L, ">=4", L, "<=6")   -> 4, 5 AND 6, not 4 and 5
#: The conditional formatting on the working sheet is narrower than the warrant
#: on both counts, so a cell can be unhighlighted and still count.
WET_CODES = {2, 3}
DARK_CODES = {4, 5, 6}

#: Sideswipe SAME direction, OFF by default. The published ROR list (2024
#: Overview and 2026 text alike) has Sideswipe OPPOSITE Direction (SSOD) and
#: not this. The workbook adds a row "Sideswipe Same* (use SSSD)" with the
#: note "*multi-lane only" AND LEAVES ITS ABBREVIATION CELL (AB9) BLANK,
#: inside the MATCH range $AB$2:$AB$10. A blank key matches nothing, so SSSD
#: does not count until an engineer types it in. Hence multilane=False
#: everywhere by default; passing True is that opt-in. On study 41000079305
#: the difference is F-2 at 82.1% against 89.7%.
MULTILANE_ROR_TYPES = {"SSSD"}

#: Crash types that are intersection crashes, for the N-4 base. The workbook
#: derives non-intersection crashes as total minus these, rather than from a
#: flag: Angle, LTDR, LTSR, RTDR, RTSR, U-Turn and the Y-line variant.
INTERSECTION_TYPES = {"angle", "LTDR", "LTSR", "RTDR", "RTSR", "U-Turn",
                      "LTDR, Y-line"}

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
    #: Intersection related, as MB-1 reads it. The caller sets this from the
    #: fiche F code (Roadway Feature) or from the report review; nothing in
    #: this module derives it. N-4 does not use it: its base comes off the
    #: crash type, as the warrants workbook does.
    at_intersection: bool = False
    severity: str = ""                     # KABCO, for the EPDO weighting
    date: object = None                    # datetime.date, for the recency tests

    @property
    def is_animal(self) -> bool:
        return self.crash_type in EXCLUDED_TYPES

    @property
    def is_nonmotorist(self) -> bool:
        return self.crash_type in NONMOTORIST_TYPES

    def is_ror(self, multilane: bool = False) -> bool:
        if self.crash_type in ROR_TYPES:
            return True
        return multilane and self.crash_type in MULTILANE_ROR_TYPES

    @property
    def at_intersection_type(self) -> bool:
        return self.crash_type in INTERSECTION_TYPES

    @property
    def is_wet(self) -> bool:
        return self.road_condition in WET_CODES

    @property
    def is_dark(self) -> bool:
        return self.light_condition in DARK_CODES


#: The workbook rounds every share to two decimals BEFORE the >= test:
#: ROUND(U10/U6, 2) >= 0.35. So 51.6% rounds to 52% and meets a 52% threshold.
#: This is not a presentation choice, it is the test, and it matters at the
#: margin: it is the difference between F-4 met and not met on study
#: 41000079305. The thresholds are published as whole percents, so testing at
#: whole-percent precision is the consistent reading.
SHARE_PLACES = 2


def rounded_share(count: int, base: int, places: int = SHARE_PLACES) -> float:
    """The share as the warrant tests it."""
    return round(count / base, places) if base else 0.0


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
        """As tested: rounded to whole percent, like the workbook."""
        return rounded_share(self.count, self.total)

    @property
    def exact_share(self) -> float:
        """Unrounded, for a reader who wants to see the margin."""
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
    edition: str = DEFAULT_EDITION
    warrants: list = field(default_factory=list)

    @property
    def met(self) -> list:
        return [w for w in self.warrants if w.met]


def screen_section(crashes, length_mi: float, facility: str = "freeway",
                   multilane: bool = False, strict: bool = True,
                   edition: str = DEFAULT_EDITION) -> SectionScreen:
    """Run the section warrants for one location.

    ``crashes`` are the in-study crashes (IS + RE + ADD) for the 5-year
    analysis period. ``facility`` keys into FACILITY_MINIMUMS. ``edition``
    is recorded on the screen; the section thresholds are the same in the
    2024 and 2026 texts, so it changes no answer.
    """
    edition = check_edition(edition)
    if facility not in FACILITY_MINIMUMS:
        raise ValueError(f"facility must be one of {sorted(FACILITY_MINIMUMS)}")
    if length_mi <= 0:
        raise ValueError("section length must be positive")

    animals = [c for c in crashes if c.is_animal]
    kept = [c for c in crashes if not c.is_animal]
    total = len(kept)
    rate = total / length_mi
    min_total, min_rate = FACILITY_MINIMUMS[facility]
    # The workbook tests STRICTLY greater than: 30 crashes does not clear a
    # minimum of 30. The prose of both editions ("a minimum number ... are
    # met") reads as >=. strict=True follows the workbook, which is what NCDOT
    # runs.
    meets = ((total > min_total and rate > min_rate) if strict
             else (total >= min_total and rate >= min_rate))

    klass = "freeway" if facility == "freeway" else "nonfreeway"
    out = []
    for name, (fac, threshold, desc) in SECTION_WARRANTS.items():
        if fac != klass:
            continue
        if name in ("F-1", "N-1"):
            n = sum(1 for c in kept if c.is_ror(multilane) and c.is_wet)
            base = total
        elif name in ("F-2", "N-2"):
            n = sum(1 for c in kept if c.is_ror(multilane))
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
            ni = [c for c in kept if not c.at_intersection_type]
            n, base = sum(1 for c in ni if c.is_ror(multilane) and c.is_dark), len(ni)
        share = rounded_share(n, base)
        out.append(WarrantResult(
            warrant=name, description=desc, threshold=threshold, count=n,
            total=base, met=meets and share >= threshold,
            note="" if meets else "minimums not met"))

    return SectionScreen(facility=facility, length_mi=length_mi, total=total,
                         animal_excluded=len(animals), rate=rate,
                         min_total=min_total, min_rate=min_rate,
                         meets_minimums=meets, edition=edition, warrants=out)


def format_screen(s: SectionScreen) -> str:
    """A plain report, docs/05 style."""
    lines = [
        f"Edition: {EDITION_NAMES[s.edition]}",
        f"Facility: {s.facility}   Length: {s.length_mi:.3f} mi",
        f"Total crashes: {s.total}"
        + (f"   (animal crashes excluded: {s.animal_excluded})"
           if s.animal_excluded else ""),
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


# --------------------------------------------------------------------------- #
# intersection warrants (workbook sheets IU / IR)
# --------------------------------------------------------------------------- #
#: EPDO weights by KABCO severity (CLAUDE.md; workbook $W$2:$X$6).
EPDO = {"K": 76.8, "A": 76.8, "B": 8.4, "C": 8.4, "O": 1.0}

#: Frontal Impact crash types. The 2026 text lists four families: Angle, Left
#: Turn (same or different roads), Right Turn (same or different roads), Head
#: On. The match keys are the decoded types the NCDOT warrants workbook uses
#: on its IU and IR sheets, which also carry U-Turn and the Y-line variant of
#: LTDR; both are kept. These are also the intersection crash types the
#: section N-4 base subtracts, plus Head-on.
FI_TYPES = {"angle", "LTDR", "LTSR", "RTDR", "RTSR", "U-Turn", "head-on",
            "Head-on", "Angle", "LTDR, Y-line"}

#: Crashes involving non-motorists, as decoded crash types: T 14 and T 15 in
#: fiche_workbook.T_CODES ("pedestrian" and "cyclist"). BP-1 and MB-1 count
#: these.
NONMOTORIST_TYPES = {T_CODES[14], T_CODES[15]}

#: Urban looks back 2 years for its recency test, rural 3.
RECENCY_YEARS = {"urban": 2, "rural": 3}

#: The crash pull NCDOT runs for an intersection analysis: 5 years urban,
#: 10 years rural. The HSIP GIS is the source of the pull and of the
#: urban/rural call itself (City reads RURAL or names the municipality);
#: see docs/12. The recency windows above are unchanged by the pull length.
STUDY_PERIOD_YEARS = {"urban": 5, "rural": 10}


def period_note(crashes, context: str, end_date=None) -> str | None:
    """A sentence when the crash data span does not look like the study
    period NCDOT pulls for this context, or None when it does.

    Advisory only: it never changes the screen. The span is measured from
    the earliest crash to ``end_date`` (or the latest crash), and up to nine
    months of slack is allowed, since a pull can sit anywhere inside its
    period and quiet corridors have no crash on the boundary dates.
    """
    expected = STUDY_PERIOD_YEARS.get(context)
    dates = [c.date for c in crashes if c.date is not None]
    if expected is None or len(dates) < 2:
        return None
    end = end_date or max(dates)
    span = (end - min(dates)).days / 365.25
    if abs(span - expected) <= 0.75:
        return None
    return (f"the crash data spans {span:.1f} years but a {context} "
            f"intersection analysis is pulled as {expected} years "
            "(urban 5 / rural 10, per the NCDOT HSIP GIS; docs/12). "
            "Check the fiche pull period before relying on the screen.")


def pull_note(crashes, years: int = 10) -> str | None:
    """A sentence when the crash data span is not the ``years`` the 10-year
    warrants (B-1, MB-1) are written for, or None when it is.

    Advisory only, like :func:`period_note`. The span is the latest crash
    date less the earliest, with the same nine months of slack. A section
    run supplies the 5-year section pull, on which a count short of the
    minimum is not settled: the other five years could add crashes.
    """
    dates = [c.date for c in crashes if c.date is not None]
    if len(dates) < 2:
        return None
    span = (max(dates) - min(dates)).days / 365.25
    if abs(span - years) <= 0.75:
        return None
    return (f"The reviewed rows span {span:.1f} years; B-1 and MB-1 are "
            f"{years}-year warrants, so a count short of the minimum is not "
            f"settled until a {years}-year pull is screened.")

#: Intersection warrant thresholds, one table per edition and context. Every
#: number is the published one; the test that combines them is in
#: :func:`screen_intersection`. Keys: ``recent`` is the share of crashes in
#: the recency window (RECENCY_YEARS) that I-1 and I-4 require; ``i1a`` is
#: path (a) of I-1, (min frontal impacts, min frontal share); ``i1b`` is
#: path (b), urban only, (min total, min frontal share, min frontal impact
#: severity index), None where the text has no such path; ``i2`` is (min
#: total, min share in the last year); ``i3`` is (min total, min severity
#: index, min share in the recency window); ``i4`` is (min night crashes,
#: min night share); ``ka_fi`` is I-3, the K or A frontal impacts in the
#: last 5 years, both contexts.
_RURAL = {                      # I-1r to I-4r: unchanged 2024 to 2026
    "recent": 0.20, "i1a": (9, 0.60), "i1b": None, "i2": (20, 0.32),
    "i3": (20, 9.0, 0.30), "i4": (10, 0.46), "ka_fi": 3,
}
INTERSECTION_THRESHOLDS = {
    "2024": {
        "urban": {"recent": 0.25, "i1a": (12, 0.55), "i1b": (35, 0.35, 6.0),
                  "i2": (25, 0.38), "i3": (25, 6.0, 0.40), "i4": (12, 0.40),
                  "ka_fi": 3},
        "rural": _RURAL,
    },
    "2026": {
        # The four changes from 2024: I-1u (a) frontal share 55% to 60%,
        # I-2u last-year share 38% to 40%, I-3u severity index 6.0 to 6.5,
        # I-4u night share 40% to 45%.
        "urban": {"recent": 0.25, "i1a": (12, 0.60), "i1b": (35, 0.35, 6.0),
                  "i2": (25, 0.40), "i3": (25, 6.5, 0.40), "i4": (12, 0.45),
                  "ka_fi": 3},
        "rural": _RURAL,
    },
}

#: Every intersection warrant, as (context, description). The test itself is
#: in :func:`screen_intersection` because several combine three quantities.
INTERSECTION_WARRANTS = {
    "I-1u": ("urban", "Frontal Impact"),
    "I-2u": ("urban", "Recent Crashes"),
    "I-3u": ("urban", "Severity"),
    "I-4u": ("urban", "Night Location"),
    "I-1r": ("rural", "Frontal Impact"),
    "I-2r": ("rural", "Recent Crashes"),
    "I-3r": ("rural", "Severity"),
    "I-4r": ("rural", "Night Location"),
    "I-3": ("both", "Chronic K and A Frontal Impact"),
}


@dataclass
class IntersectionScreen:
    context: str
    total: int
    fi: int
    fi_share: float
    fi_severity: float
    total_severity: float
    recent_1yr: int
    recent_1yr_share: float
    recent_n: int
    recent_n_share: float
    recency_years: int
    night: int
    night_share: float
    ka_fi_5yr: int
    edition: str = DEFAULT_EDITION
    warrants: list = field(default_factory=list)

    @property
    def met(self) -> list:
        return [w for w in self.warrants if w.met]


def _epdo(severity) -> float | None:
    return EPDO.get(str(severity or "").strip().upper())


def _mean(values) -> float:
    vals = [v for v in values if v is not None]
    return round(sum(vals) / len(vals), 2) if vals else 0.0


def _window_end(crashes, end_date=None):
    """The date the recency windows count back from: ``end_date`` when the
    caller states one, else the most recent crash date, else None."""
    dates = [c.date for c in crashes if c.date is not None]
    return end_date or (max(dates) if dates else None)


def _in_window(crashes, end, years: int) -> list:
    """The crashes dated inside the ``years`` ending on ``end``, inclusive.
    A crash with no date is never inside a window; with no end there is no
    window."""
    if end is None:
        return []
    try:
        cut = end.replace(year=end.year - years)
    except ValueError:              # February 29 with no such day that year
        cut = end.replace(year=end.year - years, day=28)
    return [c for c in crashes if c.date is not None and cut <= c.date <= end]


def screen_intersection(crashes, context: str = "urban", end_date=None,
                        edition: str = DEFAULT_EDITION) -> IntersectionScreen:
    """Run the intersection warrants for one location.

    ``context`` is "urban" or "rural"; they differ in every threshold and in
    the length of the recency window (2 years against 3).

    ``end_date`` is the analysis end date, which the recency tests count back
    from. Without it the most recent crash date is used, which is what an
    engineer means by "the last year" when no cutoff was stated.

    ``edition`` picks the threshold table (EDITIONS; the default is the one
    the app runs). The rural thresholds are the same in both; the four urban
    differences are in INTERSECTION_THRESHOLDS.
    """
    edition = check_edition(edition)
    if context not in RECENCY_YEARS:
        raise ValueError('context must be "urban" or "rural"')
    kept = [c for c in crashes if not c.is_animal]
    total = len(kept)
    if not total:
        raise ValueError("no crashes to screen")

    end = _window_end(kept, end_date)

    fi = [c for c in kept if c.crash_type in FI_TYPES]
    fi_share = rounded_share(len(fi), total)
    fi_sev = _mean(_epdo(c.severity) for c in fi)
    tot_sev = _mean(_epdo(c.severity) for c in kept)

    years = RECENCY_YEARS[context]
    r1, rn = len(_in_window(kept, end, 1)), len(_in_window(kept, end, years))
    night = sum(1 for c in kept if c.is_dark)
    # K and A frontal-impact crashes in the last 5 years: the workbook counts
    # rows where the EPDO-FI column equals 76.8, which is K or A on an FI type.
    ka = sum(1 for c in _in_window(fi, end, 5) if _epdo(c.severity) == 76.8)

    s = IntersectionScreen(
        context=context, total=total, fi=len(fi), fi_share=fi_share,
        fi_severity=fi_sev, total_severity=tot_sev,
        recent_1yr=r1, recent_1yr_share=rounded_share(r1, total),
        recent_n=rn, recent_n_share=rounded_share(rn, total),
        recency_years=years,
        night=night, night_share=rounded_share(night, total), ka_fi_5yr=ka,
        edition=edition)

    def add(name, met, count, base, threshold):
        s.warrants.append(WarrantResult(
            warrant=name, description=INTERSECTION_WARRANTS[name][1],
            threshold=threshold, count=count, total=base, met=met))

    t = INTERSECTION_THRESHOLDS[edition][context]
    sfx = "u" if context == "urban" else "r"
    fi_min, fi_min_share = t["i1a"]
    path_a = s.fi >= fi_min and s.fi_share >= fi_min_share
    path_b = False
    if t["i1b"] is not None:
        b_total, b_share, b_severity = t["i1b"]
        path_b = (s.total >= b_total and s.fi_share >= b_share
                  and s.fi_severity >= b_severity)
    add(f"I-1{sfx}", s.recent_n_share >= t["recent"] and (path_a or path_b),
        s.fi, s.total, fi_min_share)
    n2, share2 = t["i2"]
    add(f"I-2{sfx}", s.total >= n2 and s.recent_1yr_share >= share2,
        s.recent_1yr, s.total, share2)
    n3, severity3, share3 = t["i3"]
    add(f"I-3{sfx}", s.total >= n3 and s.total_severity >= severity3
        and s.recent_n_share >= share3, s.recent_n, s.total, share3)
    n4, share4 = t["i4"]
    add(f"I-4{sfx}", s.recent_n_share >= t["recent"] and s.night >= n4
        and s.night_share >= share4, s.night, s.total, share4)
    # I-3 applies in both contexts and is a count, not a share.
    add("I-3", s.ka_fi_5yr >= t["ka_fi"], s.ka_fi_5yr, t["ka_fi"], 0.0)
    return s


def format_intersection(s: IntersectionScreen) -> str:
    lines = [
        f"Edition: {EDITION_NAMES[s.edition]}",
        f"Context: {s.context}   Total crashes: {s.total}",
        f"Frontal Impact: {s.fi} ({s.fi_share:.1%}), severity {s.fi_severity}",
        f"Total severity: {s.total_severity}",
        f"Last 1 year: {s.recent_1yr} ({s.recent_1yr_share:.1%})",
        f"Last {s.recency_years} years: {s.recent_n} ({s.recent_n_share:.1%})",
        f"Night: {s.night} ({s.night_share:.1%})",
        f"K and A frontal-impact crashes, last 5 years: {s.ka_fi_5yr}",
        "",
    ]
    for w in s.warrants:
        lines.append(f"  {w.warrant:<5} {w.description:<32} "
                     f"{'MET' if w.met else 'not met'}")
    return "\n".join(lines)


# --------------------------------------------------------------------------- #
# non-motorist and bridge warrants (new in the 2026 text)
# --------------------------------------------------------------------------- #
#: The edition these three warrants come from. They have no 2024 form, so
#: the screens below carry this edition and take none.
NEW_WARRANTS_EDITION = "2026"

#: BP-1, Non-Motorist Intersection Warrant, Chronic Location. Path (a): at
#: least ``a_min_10yr`` crashes involving non-motorists in the last 10 years
#: AND at least ``a_share_5yr`` of those in the last 5 years. Path (b): at
#: least ``b_min_5yr`` in the last 5 years.
BP1_THRESHOLDS = {"a_min_10yr": 4, "a_share_5yr": 0.50, "b_min_5yr": 3}

#: MB-1, Non-Motorist Midblock Warrant, Chronic Location: at least
#: ``min_10yr`` non-intersection related crashes involving non-motorists in
#: the last 10 years.
MB1_THRESHOLDS = {"min_10yr": 4}

#: B-1, Bridge Warrant, Chronic Location: at least ``min_ror_10yr`` run off
#: road crashes in the last 10 years AND at least ``ror_share`` of all
#: crashes run off road. 2-lane roadways only; animal crashes excluded; the
#: ROR list is ROR_TYPES, the same six families the section warrants use.
B1_THRESHOLDS = {"min_ror_10yr": 5, "ror_share": 0.50}


@dataclass
class NonmotoristScreen:
    """BP-1 or MB-1 for one location: the non-motorist crashes and the
    recency counts the warrant tests."""
    warrant: str                  # "BP-1" or "MB-1"
    total: int                    # crashes screened, every type
    nonmotorist: int              # of them, involving a non-motorist (MB-1:
    #                             # midblock ones only)
    last_10yr: int
    last_5yr: int
    last_5yr_share: float         # of the non-motorist crashes in the last 10
    at_intersection: int = 0      # MB-1: non-motorist crashes left out as
    #                             # intersection related
    edition: str = NEW_WARRANTS_EDITION
    warrants: list = field(default_factory=list)

    @property
    def met(self) -> list:
        return [w for w in self.warrants if w.met]


def _nonmotorist_screen(warrant: str, crashes, counted, end) -> NonmotoristScreen:
    ten = _in_window(counted, end, 10)
    five = _in_window(counted, end, 5)
    return NonmotoristScreen(
        warrant=warrant, total=len(crashes), nonmotorist=len(counted),
        last_10yr=len(ten), last_5yr=len(five),
        last_5yr_share=rounded_share(len(five), len(ten)))


def screen_nonmotorist_intersection(crashes, end_date=None
                                    ) -> NonmotoristScreen:
    """BP-1, the non-motorist intersection warrant, for one location.

    ``crashes`` are the in-analysis crashes at the intersection; only those
    whose decoded type is in NONMOTORIST_TYPES count. The two windows count
    back from ``end_date``, or from the most recent crash when none is
    given, exactly as :func:`screen_intersection` does. Path (a)'s share is
    tested rounded, like every other share here.
    """
    end = _window_end(crashes, end_date)
    counted = [c for c in crashes if c.is_nonmotorist]
    s = _nonmotorist_screen("BP-1", crashes, counted, end)
    t = BP1_THRESHOLDS
    path_a = (s.last_10yr >= t["a_min_10yr"]
              and s.last_5yr_share >= t["a_share_5yr"])
    path_b = s.last_5yr >= t["b_min_5yr"]
    paths = [p for p, ok in (("(a)", path_a), ("(b)", path_b)) if ok]
    note = ""
    if paths:
        note = "met by path " + " and ".join(paths)
    s.warrants.append(WarrantResult(
        warrant="BP-1", description="Chronic Location, non-motorist",
        threshold=t["a_share_5yr"], count=s.last_5yr, total=s.last_10yr,
        met=path_a or path_b, note=note))
    return s


def screen_nonmotorist_midblock(crashes, end_date=None) -> NonmotoristScreen:
    """MB-1, the non-motorist midblock warrant, for one location.

    Counts the crashes whose decoded type is in NONMOTORIST_TYPES and whose
    ``at_intersection`` flag is False, in the last 10 years back from
    ``end_date`` or the most recent crash. "Non-intersection related" is
    that flag and nothing else: this module never derives it, because a
    pedestrian or cyclist crash type says nothing about where the crash
    happened (N-4's type-based base cannot serve). The caller sets it from
    the fiche F code (Roadway Feature) or from the report review; the
    screen reports how many non-motorist crashes it left out on the flag.
    """
    end = _window_end(crashes, end_date)
    nonmotorist = [c for c in crashes if c.is_nonmotorist]
    counted = [c for c in nonmotorist if not c.at_intersection]
    s = _nonmotorist_screen("MB-1", crashes, counted, end)
    s.at_intersection = len(nonmotorist) - len(counted)
    need = MB1_THRESHOLDS["min_10yr"]
    # A count, not a share, like I-3: the base is the minimum.
    s.warrants.append(WarrantResult(
        warrant="MB-1", description="Chronic Location, non-motorist midblock",
        threshold=0.0, count=s.last_10yr, total=need, met=s.last_10yr >= need))
    return s


def format_nonmotorist(s: NonmotoristScreen) -> str:
    """A plain report of BP-1 or MB-1, docs/05 style."""
    what = ("Crashes involving non-motorists, not intersection related"
            if s.warrant == "MB-1" else "Crashes involving non-motorists")
    lines = [
        f"Edition: {EDITION_NAMES[s.edition]}",
        f"Warrant {s.warrant}   Crashes screened: {s.total}",
        f"{what}: {s.nonmotorist}"
        + (f"   (left out as intersection related: {s.at_intersection})"
           if s.warrant == "MB-1" else ""),
        f"Last 10 years: {s.last_10yr}   Last 5 years: {s.last_5yr} "
        f"({s.last_5yr_share:.1%} of the last 10)",
        "",
    ]
    for w in s.warrants:
        lines.append(f"  {w.warrant:<5} {w.description:<40} "
                     f"{'MET' if w.met else 'not met'}"
                     + (f"  ({w.note})" if w.note else ""))
    return "\n".join(lines)


@dataclass
class BridgeScreen:
    """B-1 for one location."""
    total: int                    # crashes screened, animal crashes out
    animal_excluded: int
    ror: int                      # run off road crashes among them
    ror_10yr: int                 # of those, in the last 10 years
    ror_share: float              # ror / total, rounded as tested
    edition: str = NEW_WARRANTS_EDITION
    warrants: list = field(default_factory=list)

    @property
    def met(self) -> list:
        return [w for w in self.warrants if w.met]


def screen_bridge(crashes, two_lane: bool, end_date=None) -> BridgeScreen:
    """B-1, the bridge warrant, for one location.

    The text applies it to 2-lane roadways only, so ``two_lane`` must be
    True; False is refused rather than screened. Animal crashes leave the
    analysis as they do for the section warrants. Run off road is
    ROR_TYPES. The crash count is tested over the last 10 years back from
    ``end_date`` or the most recent crash; the share is run off road
    crashes over all crashes supplied. The warrant is written for a 10-year
    pull; on a 5-year section pull both the count and the share are
    provisional, and the CLI and the page say so.
    """
    if not two_lane:
        raise ValueError(
            "B-1 applies to 2-lane roadways only (2026 HSIP Warrants); this "
            "location is not one, so the bridge warrant is not run")
    kept = [c for c in crashes if not c.is_animal]
    ror = [c for c in kept if c.is_ror()]
    end = _window_end(kept, end_date)
    t = B1_THRESHOLDS
    s = BridgeScreen(
        total=len(kept), animal_excluded=len(crashes) - len(kept),
        ror=len(ror), ror_10yr=len(_in_window(ror, end, 10)),
        ror_share=rounded_share(len(ror), len(kept)))
    s.warrants.append(WarrantResult(
        warrant="B-1", description="Chronic Location, bridge run off road",
        threshold=t["ror_share"], count=s.ror, total=s.total,
        met=s.ror_10yr >= t["min_ror_10yr"] and s.ror_share >= t["ror_share"]))
    return s


def format_bridge(s: BridgeScreen) -> str:
    """A plain report of B-1, docs/05 style."""
    lines = [
        f"Edition: {EDITION_NAMES[s.edition]}",
        f"Warrant B-1 (2-lane roadway)   Total crashes: {s.total}"
        + (f"   (animal crashes excluded: {s.animal_excluded})"
           if s.animal_excluded else ""),
        f"Run off road: {s.ror} ({s.ror_share:.1%}), "
        f"{s.ror_10yr} in the last 10 years "
        f"(needs {B1_THRESHOLDS['min_ror_10yr']} and "
        f"{B1_THRESHOLDS['ror_share']:.0%})",
        "",
    ]
    for w in s.warrants:
        lines.append(f"  {w.warrant:<5} {w.description:<40} "
                     f"{'MET' if w.met else 'not met'}")
    return "\n".join(lines)


# --------------------------------------------------------------------------- #
# scanning for a section that warrants
# --------------------------------------------------------------------------- #
#: A section shorter than this is not a project, whatever its crash rate. Ten
#: crashes in 0.02 mi is 500 per mile and clears every rate minimum trivially,
#: which is arithmetic rather than engineering.
MIN_SECTION_MI = 0.10


@dataclass
class Window:
    lo: float
    hi: float
    screen: SectionScreen

    @property
    def length(self) -> float:
        return self.hi - self.lo

    @property
    def names(self) -> list:
        return [w.warrant for w in self.screen.met]


def scan_sections(placed, facility: str = "freeway", multilane: bool = False,
                  min_length: float = MIN_SECTION_MI, pad: float = 0.0,
                  strict: bool = True, edition: str = DEFAULT_EDITION) -> list:
    """Every sub-section that meets a warrant, longest first.

    ``placed`` are ``(milepost, Crash)`` pairs. Candidate boundaries are the
    crash mileposts themselves, because a boundary anywhere between two
    crashes gives the same crash set as the boundary at the crash: only the
    length changes, and a shorter length can only help the rate. So the
    tightest window around any crash set is the one bounded BY that set, and
    scanning the crash mileposts finds every distinct answer.

    ``pad`` widens each window at both ends, for the case where an engineer
    wants the section to reach a feature rather than stop at the last crash.
    """
    # key on the milepost alone: crashes routinely share one, and a Crash is
    # not orderable, so a plain tuple sort raises the moment two tie.
    rows = sorted(((float(mp), c) for mp, c in placed if mp is not None),
                  key=lambda t: t[0])
    if not rows:
        return []
    bounds = sorted({mp for mp, _ in rows})
    out = []
    for i, lo in enumerate(bounds):
        for hi in bounds[i:]:
            length = hi - lo + 2 * pad
            if length < min_length:
                continue
            inside = [c for mp, c in rows if lo <= mp <= hi]
            if not inside:
                continue
            screen = screen_section(inside, length, facility,
                                    multilane=multilane, strict=strict,
                                    edition=edition)
            if screen.met:
                out.append(Window(lo - pad, hi + pad, screen))
    # Longest first: a longer section that still warrants is the better project.
    out.sort(key=lambda w: (-w.length, -w.screen.total))
    return out


def best_windows(windows, limit: int = 10) -> list:
    """Drop windows wholly contained in a longer one that meets the same set."""
    kept = []
    for w in windows:
        if any(k.lo <= w.lo and w.hi <= k.hi and set(w.names) <= set(k.names)
               for k in kept):
            continue
        kept.append(w)
        if len(kept) >= limit:
            break
    return kept


def best_achievable(placed, facility: str = "freeway", multilane: bool = False,
                    min_length: float = MIN_SECTION_MI, strict: bool = True,
                    edition: str = DEFAULT_EDITION) -> dict:
    """The closest ANY sub-section gets to each warrant.

    Answers the question a bare list of warranting windows does not: for the
    warrants that were NOT met, was it close, and where? A warrant missed by
    one crash is worth a second look at the determinations; a warrant missed
    because the corridor has no wet crashes at all is settled and should not
    be revisited.

    Returns ``{warrant: (share, lo, hi, count, base, threshold)}`` over windows
    that clear the minimums.
    """
    rows = sorted(((float(mp), c) for mp, c in placed if mp is not None),
                  key=lambda t: t[0])
    bounds = sorted({mp for mp, _ in rows})
    best: dict = {}
    for i, lo in enumerate(bounds):
        for hi in bounds[i:]:
            if hi - lo < min_length:
                continue
            inside = [c for mp, c in rows if lo <= mp <= hi]
            if not inside:
                continue
            s = screen_section(inside, hi - lo, facility, multilane=multilane,
                               strict=strict, edition=edition)
            if not s.meets_minimums:
                continue
            for w in s.warrants:
                if w.warrant not in best or w.share > best[w.warrant][0]:
                    best[w.warrant] = (w.share, lo, hi, w.count, w.total,
                                       w.threshold)
    return best


@dataclass(frozen=True)
class Finding:
    """One conclusion per warrant: the answer, not the window list."""
    warrant: str
    description: str
    threshold: float
    status: str                       # "section", "subsection", or "none"
    section_share: float              # the share over the full study section
    widest: Window | None = None      # for "subsection": the longest window
    tightest: Window | None = None    # and the shortest
    best_share: float | None = None   # for "none": the ceiling, when any
    best_span: tuple | None = None    # window clears the minimums; (lo, hi)


def _window_share(win: Window, code: str) -> float:
    return next(w.share for w in win.screen.warrants if w.warrant == code)


def subsection_findings(placed, section: SectionScreen,
                        multilane: bool = False,
                        min_length: float = MIN_SECTION_MI,
                        strict: bool = True) -> list:
    """One finding per warrant, which is what a reader actually asks.

    The raw scan answers a different question: every span that warrants. On a
    real corridor those spans overlap heavily and the list reads as the same
    window six times. The per-warrant questions are: met over the whole
    section? met only in a sub-section, and then which (the widest, because a
    longer section that still warrants is the better project, and the
    tightest, because it names the cluster)? or out of reach everywhere, and
    then how close did any sub-section get?
    """
    windows = scan_sections(placed, section.facility, multilane=multilane,
                            min_length=min_length, strict=strict,
                            edition=section.edition)
    ceiling = best_achievable(placed, section.facility, multilane=multilane,
                              min_length=min_length, strict=strict,
                              edition=section.edition)
    out = []
    for w in section.warrants:
        meeting = [win for win in windows if w.warrant in win.names]
        if w.met:
            out.append(Finding(w.warrant, w.description, w.threshold,
                               "section", w.share))
        elif meeting:
            out.append(Finding(w.warrant, w.description, w.threshold,
                               "subsection", w.share,
                               widest=max(meeting, key=lambda x: x.length),
                               tightest=min(meeting, key=lambda x: x.length)))
        else:
            c = ceiling.get(w.warrant)
            out.append(Finding(w.warrant, w.description, w.threshold, "none",
                               w.share,
                               best_share=c[0] if c else None,
                               best_span=(c[1], c[2]) if c else None))
    return out


def format_finding(f: Finding) -> str:
    """The finding as one plain sentence, docs/05 style."""
    head = f"{f.warrant} {f.description} ({f.threshold:.0%})"
    if f.status == "section":
        return f"{head}: met over the full section at {f.section_share:.0%}."
    if f.status == "subsection":
        wide = (f"MP {f.widest.lo:.3f} to {f.widest.hi:.3f} at "
                f"{_window_share(f.widest, f.warrant):.0%}")
        if f.widest is f.tightest:
            return f"{head}: met only in one sub-section, {wide}."
        tight = (f"MP {f.tightest.lo:.3f} to {f.tightest.hi:.3f} at "
                 f"{_window_share(f.tightest, f.warrant):.0%}")
        return (f"{head}: met only in a sub-section; widest {wide}, "
                f"tightest {tight}.")
    if f.best_share is None:
        return f"{head}: not met; no sub-section clears the facility minimums."
    return (f"{head}: not met in any sub-section; the best is "
            f"{f.best_share:.0%} between MP {f.best_span[0]:.3f} and "
            f"{f.best_span[1]:.3f}.")
