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

#: Wet road condition and dark light condition, in fiche C and L codes.
#: From the warrants workbook, which is authoritative over the reading I first
#: took off the working sheet's conditional formatting:
#:   wet   COUNTIFS(C, ">=2", C, "<=3")   -> 2 AND 3, not 2 alone
#:   dark  COUNTIFS(L, ">=4", L, "<=6")   -> 4, 5 AND 6, not 4 and 5
#: The conditional formatting on the working sheet is narrower than the warrant
#: on both counts, so a cell can be unhighlighted and still count.
WET_CODES = {2, 3}
DARK_CODES = {4, 5, 6}

#: Sideswipe SAME direction, OFF by default. The Overview's ROR list has
#: Sideswipe OPPOSITE Direction (SSOD) and not this. The workbook adds a row
#: "Sideswipe Same* (use SSSD)" with the note "*multi-lane only" AND LEAVES ITS
#: ABBREVIATION CELL (AB9) BLANK, inside the MATCH range $AB$2:$AB$10. A blank
#: key matches nothing, so SSSD does not count until an engineer types it in.
#: Hence multilane=False everywhere by default; passing True is that opt-in.
#: On study 41000079305 the difference is F-2 at 82.1% against 89.7%.
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
    at_intersection: bool = False          # unused; N-4 uses the type
    severity: str = ""                     # KABCO, for the EPDO weighting
    date: object = None                    # datetime.date, for the recency tests

    @property
    def is_animal(self) -> bool:
        return self.crash_type in EXCLUDED_TYPES

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
    warrants: list = field(default_factory=list)

    @property
    def met(self) -> list:
        return [w for w in self.warrants if w.met]


def screen_section(crashes, length_mi: float, facility: str = "freeway",
                   multilane: bool = False, strict: bool = True
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
    # The workbook tests STRICTLY greater than: 30 crashes does not clear a
    # minimum of 30. The Overview's prose ("a minimum number ... are met")
    # reads as >=. strict=True follows the workbook, which is what NCDOT runs.
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
                         meets_minimums=meets, warrants=out)


def format_screen(s: SectionScreen) -> str:
    """A plain report, docs/05 style."""
    lines = [
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

#: Frontal Impact crash types. These are also the intersection crash types the
#: section N-4 base subtracts, plus Head-on.
FI_TYPES = {"angle", "LTDR", "LTSR", "RTDR", "RTSR", "U-Turn", "head-on",
            "Head-on", "Angle", "LTDR, Y-line"}

#: Urban looks back 2 years for its recency test, rural 3.
RECENCY_YEARS = {"urban": 2, "rural": 3}

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
    warrants: list = field(default_factory=list)

    @property
    def met(self) -> list:
        return [w for w in self.warrants if w.met]


def _epdo(severity) -> float | None:
    return EPDO.get(str(severity or "").strip().upper())


def _mean(values) -> float:
    vals = [v for v in values if v is not None]
    return round(sum(vals) / len(vals), 2) if vals else 0.0


def screen_intersection(crashes, context: str = "urban", end_date=None
                        ) -> IntersectionScreen:
    """Run the intersection warrants for one location.

    ``context`` is "urban" or "rural"; they differ in every threshold and in
    the length of the recency window (2 years against 3).

    ``end_date`` is the analysis end date, which the recency tests count back
    from. Without it the most recent crash date is used, which is what an
    engineer means by "the last year" when no cutoff was stated.
    """
    if context not in RECENCY_YEARS:
        raise ValueError('context must be "urban" or "rural"')
    kept = [c for c in crashes if not c.is_animal]
    total = len(kept)
    if not total:
        raise ValueError("no crashes to screen")

    dates = [c.date for c in kept if c.date is not None]
    end = end_date or (max(dates) if dates else None)

    fi = [c for c in kept if c.crash_type in FI_TYPES]
    fi_share = rounded_share(len(fi), total)
    fi_sev = _mean(_epdo(c.severity) for c in fi)
    tot_sev = _mean(_epdo(c.severity) for c in kept)

    def within(years):
        if end is None:
            return 0
        cut = end.replace(year=end.year - years)
        return sum(1 for c in kept if c.date is not None and cut <= c.date <= end)

    years = RECENCY_YEARS[context]
    r1, rn = within(1), within(years)
    night = sum(1 for c in kept if c.is_dark)
    # K and A frontal-impact crashes in the last 5 years: the workbook counts
    # rows where the EPDO-FI column equals 76.8, which is K or A on an FI type.
    ka = 0
    if end is not None:
        cut5 = end.replace(year=end.year - 5)
        ka = sum(1 for c in fi
                 if c.date is not None and cut5 <= c.date <= end
                 and _epdo(c.severity) == 76.8)

    s = IntersectionScreen(
        context=context, total=total, fi=len(fi), fi_share=fi_share,
        fi_severity=fi_sev, total_severity=tot_sev,
        recent_1yr=r1, recent_1yr_share=rounded_share(r1, total),
        recent_n=rn, recent_n_share=rounded_share(rn, total),
        recency_years=years,
        night=night, night_share=rounded_share(night, total), ka_fi_5yr=ka)

    def add(name, met, count, base, threshold, desc):
        s.warrants.append(WarrantResult(warrant=name, description=desc,
                                        threshold=threshold, count=count,
                                        total=base, met=met))

    if context == "urban":
        add("I-1u", s.recent_n_share >= 0.25 and (
                (s.fi >= 12 and s.fi_share >= 0.55)
                or (s.total >= 35 and s.fi_share >= 0.35 and s.fi_severity >= 6)),
            s.fi, s.total, 0.55, "Frontal Impact")
        add("I-2u", s.total >= 25 and s.recent_1yr_share >= 0.38,
            s.recent_1yr, s.total, 0.38, "Recent Crashes")
        add("I-3u", s.total >= 25 and s.total_severity >= 6
            and s.recent_n_share >= 0.40, s.recent_n, s.total, 0.40, "Severity")
        add("I-4u", s.recent_n_share >= 0.25 and s.night >= 12
            and s.night_share >= 0.40, s.night, s.total, 0.40, "Night Location")
    else:
        add("I-1r", s.recent_n_share >= 0.20 and s.fi >= 9
            and s.fi_share >= 0.60, s.fi, s.total, 0.60, "Frontal Impact")
        add("I-2r", s.total >= 20 and s.recent_1yr_share >= 0.32,
            s.recent_1yr, s.total, 0.32, "Recent Crashes")
        add("I-3r", s.total >= 20 and s.total_severity >= 9
            and s.recent_n_share >= 0.30, s.recent_n, s.total, 0.30, "Severity")
        add("I-4r", s.recent_n_share >= 0.20 and s.night >= 10
            and s.night_share >= 0.46, s.night, s.total, 0.46, "Night Location")
    # I-3 applies in both contexts and is a count, not a share.
    add("I-3", s.ka_fi_5yr >= 3, s.ka_fi_5yr, 3, 0.0,
        "Chronic K and A Frontal Impact")
    return s


def format_intersection(s: IntersectionScreen) -> str:
    lines = [
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
                  strict: bool = True) -> list:
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
                                    multilane=multilane, strict=strict)
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
                    min_length: float = MIN_SECTION_MI, strict: bool = True
                    ) -> dict:
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
                               strict=strict)
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
                            min_length=min_length, strict=strict)
    ceiling = best_achievable(placed, section.facility, multilane=multilane,
                              min_length=min_length, strict=strict)
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
