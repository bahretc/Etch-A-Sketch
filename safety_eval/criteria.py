"""Study criteria: what each of the three NCDOT crash studies requires.

NCDOT crash work is three study types (docs/12, :mod:`safety_eval.study_type`):
a **Fatal Crash Analysis**, an **HSIP Package Analysis** and an **Evaluation**.
They share the fiche and crash-review core, and they differ in what the
engineer has to settle before the first TEAAS pull: how long the analysis
period is and what anchors it, how the study limits are drawn, which crashes
are in scope, which warrants (if any) are tested, how the AADT is built, which
exports have to be in hand, and what has to come out the other end.

Those answers were spread over the docs pack, CLAUDE.md and the worked study
folders. This module puts them in one place as data, so that:

* ``safety-eval criteria`` prints the sheet for a study type, an analysis
  (intersection, section, bike/ped intersection) and, for an HSIP
  intersection, the urban or rural context; ``--all`` prints the catalogue
  that is docs/15;
* the Overview page shows the open study its criteria and says in words
  what is still missing (:func:`check_params`);
* the analysis period is computed one way everywhere
  (:func:`analysis_period`).

Every rule names its source (a docs file, a CLAUDE.md rule, a study number)
so a reviewer can trace it, and the tool that applies it when one does.
Nothing here is a new rule: where the pack is silent the entry says so.
Text follows docs/05: plain, no em or en dashes.
"""
from __future__ import annotations

import calendar
import datetime as dt
from dataclasses import asdict, dataclass

from . import study_type as st
from .warrants import (DARK_CODES, EPDO, FACILITY_MINIMUMS, INTERSECTION_WARRANTS,
                       SECTION_WARRANTS, WET_CODES)
from .workspace import ROLES

URBAN = "urban"
RURAL = "rural"
CONTEXTS = (URBAN, RURAL)

#: Analysis period lengths in years, by study type and analysis; an HSIP
#: intersection depends on the context (docs/12: 5 urban, 10 rural). An
#: Evaluation's periods come from the assignment and the Date Range
#: Calculator (docs/02), so it carries None.
PERIOD_YEARS = {
    (st.FATAL, st.SECTION): 5,
    (st.FATAL, st.INTERSECTION): 5,
    (st.HSIP, st.SECTION): 5,
    (st.HSIP, st.INTERSECTION, URBAN): 5,
    (st.HSIP, st.INTERSECTION, RURAL): 10,
    (st.HSIP, st.BIKEPED): 10,
    (st.EVALUATION, st.INTERSECTION): None,
    (st.EVALUATION, st.SECTION): None,
}

#: The review status vocabulary by analysis shape (docs/03): RE, the
#: re-milepost, exists only where there is a milepost to correct.
REVIEW_STATUSES = {
    "intersection": ("IS", "ADD", "DEL", "NIS"),
    "strip": ("IS", "RE", "ADD", "DEL", "NIS"),
}


@dataclass(frozen=True)
class Criterion:
    """One rule the study has to meet, with where it comes from."""
    topic: str
    rule: str
    source: str
    #: The command or page that applies the rule, when one does.
    tool: str = ""


@dataclass(frozen=True)
class Input:
    """One file the study needs, named by its workspace role."""
    role: str
    required: bool
    why: str

    @property
    def label(self) -> str:
        return ROLES[self.role][0] if self.role in ROLES else self.role


@dataclass(frozen=True)
class Deliverable:
    """One thing the study produces and how it is produced."""
    name: str
    how: str
    #: A public document (docs/05 and CLAUDE.md rule 11 apply in full).
    public: bool = False


@dataclass(frozen=True)
class StudyCriteria:
    study_type: str
    analysis: str
    context: str | None
    #: Analysis period length; None when the assignment sets the periods.
    years: int | None
    #: TEAAS y-line in feet for an intersection pull; None for a section.
    yline_ft: int | None
    review_statuses: tuple
    warrants: tuple
    criteria: tuple
    inputs: tuple
    deliverables: tuple

    @property
    def kind(self) -> st.StudyType:
        return st.STUDY_TYPES[self.study_type]

    @property
    def shape(self) -> st.AnalysisKind:
        return st.ANALYSIS_KINDS[self.analysis]

    @property
    def title(self) -> str:
        t = f"{self.kind.label}, {self.shape.label.lower()}"
        return f"{t} ({self.context})" if self.context else t

    @property
    def period_text(self) -> str:
        if self.years is None:
            return ("before and after periods from the assignment, through "
                    "the Date Range Calculator (docs/02)")
        return (f"{self.years} years ending on the last day of the most "
                "recent complete month of TEAAS data")

    @property
    def limits_text(self) -> str:
        if self.shape.is_intersection:
            return (f"crashes at or within the {self.yline_ft} ft y-line of "
                    "the study intersection, on every road code that "
                    "reaches it")
        return ("crashes mileposted on the study route between the begin "
                "and end mileposts")

    def required_inputs(self) -> list:
        return [i for i in self.inputs if i.required]


# --------------------------------------------------------------------------- #
# the analysis period
# --------------------------------------------------------------------------- #
def month_end(day: dt.date) -> dt.date:
    return day.replace(day=calendar.monthrange(day.year, day.month)[1])


def analysis_period(teaas_date: dt.date, years: int) -> tuple:
    """The ``(begin, end)`` of an N-year analysis period anchored on the
    TEAAS data currency date.

    The period ends on the last day of the most recent complete month of
    data (the currency date itself when it is a month end, else the month
    before) and begins on the first of the month N years earlier. Verified
    against three study folders: 260722124BA (9/1/2021 to 8/31/2026),
    260508015AA (7/1/2021 to 6/30/2026) and 41000079736 (9/1/2016 to
    8/31/2026 for the 10-year rural pull).
    """
    if years is None or years <= 0:
        raise ValueError("an analysis period needs a positive number of years")
    end = teaas_date if teaas_date == month_end(teaas_date) else (
        teaas_date.replace(day=1) - dt.timedelta(days=1))
    first_after = end + dt.timedelta(days=1)
    begin = first_after.replace(year=first_after.year - years)
    return begin, end


def period_years(study_type, analysis=None, context=None):
    """The analysis period length for a study, or None for an Evaluation."""
    kind = st.get(study_type)
    a_key = st.check_analysis(kind, analysis or kind.default_analysis)
    if kind.key == st.HSIP and a_key == st.INTERSECTION:
        if context not in CONTEXTS:
            return None
        return PERIOD_YEARS[(st.HSIP, st.INTERSECTION, context)]
    return PERIOD_YEARS[(kind.key, a_key)]


# --------------------------------------------------------------------------- #
# the criteria themselves
# --------------------------------------------------------------------------- #
def _epdo_text() -> str:
    return (f"KABCO from the S code; EPDO weights K and A {EPDO['K']}, "
            f"B and C {EPDO['B']}, PDO {EPDO['O']}; Severity Index = EPDO "
            "divided by crashes.")


def _common(shape: st.AnalysisKind) -> list:
    wet = ", ".join(str(c) for c in sorted(WET_CODES))
    dark = ", ".join(str(c) for c in sorted(DARK_CODES))
    rate = ("crashes per million entering vehicles (MEV): entering AADT x "
            "days / 1,000,000" if shape.is_intersection else
            "crashes per 100 million vehicle miles: AADT x miles x days / "
            "100,000,000")
    return [
        Criterion("Data source",
                  "Every crash comes from TEAAS: the Fiche Report, the "
                  "Detailed Fiche (the only export with coordinates), the "
                  "Strip or Intersection Analysis Report with its ID export, "
                  "and the Features Report for each route. TEAAS exports are "
                  "never fabricated, reconstructed or re-rendered; what can "
                  "only come from TEAAS is entered there by the engineer.",
                  "CLAUDE.md rule 9; docs/01; docs/13 section 7",
                  "Overview drop zone (intake)"),
        Criterion("Review branches",
                  "A crash's status branch is fixed by Initial Study "
                  "membership before its report is opened: in the Initial "
                  "Study it stays IS, becomes RE (section only) or DEL; not "
                  "in it, it is ADD or NIS. RE never becomes IS; DEL and NIS "
                  "are never interchanged. A crash with no DMV-349 in hand is "
                  "never IS, and a ? becomes NIS only after the diagram and "
                  "narrative confirm it. Animal crashes need no report review.",
                  "docs/03",
                  "Review Queue; apply-review (validate_determination)"),
        Criterion("Location evidence",
                  "Report coordinates and geocoded property addresses on the "
                  "report (mailboxes, driveways, bus stops) outrank the coded "
                  "distance; the coded milepost is never used to skip a "
                  "review. Every evidence-backed RE and ADD goes on the "
                  "TEAAS import list, however long it gets.",
                  "docs/03; docs/13 section 3",
                  "locate-check; import-list"),
        Criterion("Comments",
                  "Brief; state the evidence and the resulting milepost, "
                  "never a verdict on the source; nothing the row already "
                  "shows. Plain style, no em or en dashes.",
                  "docs/03; docs/05"),
        Criterion("Severity", _epdo_text(), "docs/04; CLAUDE.md rule 2"),
        Criterion("Wet and dark",
                  f"For the HSIP warrants wet is road condition C in {wet} "
                  f"and dark is light condition L in {dark} (the warrants "
                  "workbook). The Evaluation Workbook guidance counts wet as "
                  "C 2 to 6 and night as L 4 to 6; use the sheet's own "
                  "definition on the sheet it belongs to.",
                  "docs/12; safety_eval/config/ncdot_defaults.yaml"),
        Criterion("Rates", f"Exposure for a {shape.label.lower()}: {rate}.",
                  "docs/04"),
        Criterion("Redaction",
                  "Every DMV-349 is redacted before it is stored, shown or "
                  "sent to the review assist; ZIP codes and crash IDs are "
                  "kept; the output is OCR-verified against the original's "
                  "names, dates of birth, phone and licence numbers and "
                  "street addresses.",
                  "docs/11", "redact --verify; binder-index / binder-get"),
        Criterion("Writing",
                  "Plain and understated, no em dashes anywhere, no "
                  "flourishes; a roundabout is never a circle.",
                  "docs/05; CLAUDE.md rule 6", "qa (style gate)"),
    ]


def _limits(shape: st.AnalysisKind, yline_ft: int | None) -> list:
    if shape.key == st.BIKEPED:
        return [Criterion(
            "Study limits and scope",
            f"Bicycle and pedestrian crashes only (T 14 and 15) at or within "
            f"a {yline_ft} ft y-line of the intersection, always a 10-year "
            "pull, drawn on an aerial exhibit rather than a schematic "
            "(59X00239: 7/1/2011 to 6/30/2021).",
            "docs/12", "collision_diagram.render_bikeped")]
    if shape.is_intersection:
        return [Criterion(
            "Study limits",
            f"Crashes at or within the TEAAS y-line of the study "
            f"intersection, {yline_ft} ft on each leg; a leg's y-line is "
            "extended only with a stated reason (a realignment moved the "
            "tie-in: 05-08-203, 350 ft on the north leg). Intersection crash "
            "identification is road-combination dependent: the fiche is "
            "pulled on every road code that reaches the junction, and the "
            "Features Report confirms none was left out (41000079736: "
            "PLEASANT HILL 50024407 was missing from the pull).",
            "CLAUDE.md rule 5; docs/03; docs/09; examples/41000079736",
            "intersection-roads; Maps and Checks")]
    return [Criterion(
        "Study limits",
        "Crashes mileposted on the study route between the begin and end "
        "mileposts, placed through the Features Report. A crash on a cross "
        "street is placed where that street meets the route. Rows not "
        "mileposted (MP 999.999) that name the section's roads, rows whose "
        "From and Toward roads bracket the limits, rows whose Detailed Fiche "
        "coordinates fall inside the limits, and rows within 0.1 mi outside "
        "the limits are screened for review, never dropped on the coded "
        "distance. A row mileposted on another linear reference can be "
        "screened NIS when the engineer turns that rule on for the study.",
        "CLAUDE.md rule 5; docs/02; docs/03; docs/14",
        "fiche-workbook (colour screen); fca screen")]


def _fatal(shape: st.AnalysisKind, years: int) -> list:
    return [
        Criterion("Trigger",
                  "One fatal crash, assigned by a Crashweb Fatal Crash "
                  "Notification (the slip; numbers like 260722124BA). The "
                  "Regional Traffic Safety Engineer names the section or "
                  "intersection to study.",
                  "docs/01; docs/13 section 1; examples/260722124BA"),
        Criterion("Analysis period",
                  f"{years} years, ending on the last day of the most recent "
                  "complete month of TEAAS data and beginning the first of "
                  "the month five years earlier (260722124BA: 9/1/2021 to "
                  "8/31/2026; 260508015AA: 7/1/2021 to 6/30/2026). The fatal "
                  "crash falls inside it.",
                  "examples/260722124BA; Drive 260508015AA",
                  "criteria.analysis_period"),
        Criterion("Crash scope",
                  "Every crash in the limits. Animal crashes stay in the "
                  "total and are flagged, not reviewed. The fatal crash is "
                  "re-mileposted to the feature it sits at even when the "
                  "change is a few feet, so the fiche, the import list and "
                  "the maps agree.",
                  "docs/03; study_type (deletes_animals=False)"),
        Criterion("Screening",
                  "Initial Study crashes are IS (IS? when the milepost or "
                  "coordinates disagree with the limits); every other fiche "
                  "crash is ? when a trigger points at the site (In study, "
                  "IS-verify, Between, DMV, Combo, Window) and NIS otherwise. "
                  "The ? list is the report pull.",
                  "docs/02; docs/14", "fiche-workbook; fca screen"),
        Criterion("Report review",
                  "Pull the DMV-349 for every ? crash and every Initial Study "
                  "crash; run the location check (coded milepost against the "
                  "report coordinates and geocoded addresses on the route "
                  "centerline) before deciding; record each determination "
                  "(crash_id, status, new_mp, comment) and apply them to the "
                  "workbook; write the ADD and RE import list and the "
                  "feature list for TEAAS.",
                  "docs/03; docs/13 sections 3 and 4",
                  "locate-check; apply-review; import-list; route-features"),
        Criterion("AADT",
                  ("Section AADT for the middle year of the study period, "
                   "length-weighted over the sub-sections from NCDOT stations "
                   "and traffic segments; the Study Time Frame divides the "
                   "date span by 365 as the team's STRIP ADT sheet does."
                   if not shape.is_intersection else
                   "Entering AADT = sum of the leg AADTs / 2 for the middle "
                   "year of the study period from NCDOT station counts, "
                   "rounded to the nearest hundred.")
                  + " Minor and side road estimates round to the nearest "
                  "hundred.",
                  "docs/04; CLAUDE.md rule 7; examples/260307016EA",
                  "calc-aadt; aadt"),
        Criterion("Field investigation",
                  "Field Investigation File (Checklist, Sketch, Photos plus "
                  "the MUTCD reference sheets): investigator and date, "
                  "posted speed, speed data if collected, ball bank as "
                  "needed, existing signing and markings, the crash history "
                  "lines from the reviewed fiche and the strip summary. The "
                  "field observations are the engineer's to fill.",
                  "docs/01; docs/13 section 6; Drive 260508015AA",
                  "fatal-checklist; Field Investigation page (flag)"),
        Criterion("Figures",
                  "Figures 1 to 4 in the Traffic Safety Unit layout: Area "
                  "Map (county and municipal boundaries), Location Map "
                  "(aerial, study limits, side streets), Crash Map (reviewed "
                  "crashes numbered at their report locations, coloured by "
                  "decision) and AADT Map (traffic segments by AADT, "
                  "stations numbered with their count history); landscape "
                  "letter, title strip with the slip number, county "
                  "thumbnail, coordinates, milepost and division. The "
                  "package Location, Area and AADT maps are the alternative "
                  "format.",
                  "docs/14; docs/13 section 5",
                  "fca build; package-maps; Maps and Checks"),
        Criterion("Back to TEAAS",
                  "After the review the engineer enters the study criteria, "
                  "uploads the import list and the feature list, deletes "
                  "the DEL crashes and reruns; the rerun's ID export and "
                  "strip or intersection analysis (CSV and PDF) are the "
                  "deliverables the tool never writes.",
                  "CLAUDE.md rule 9; docs/13 section 7"),
        Criterion("Warrants", "None. A fatal analysis investigates one "
                  "crash; it does not ask whether the location warrants a "
                  "project.", "docs/12"),
    ]


def _hsip(shape: st.AnalysisKind, context: str | None, years: int | None
          ) -> list:
    out = [
        Criterion("Trigger",
                  "A location on NCDOT's ranked HSIP list (the NC "
                  "HSIP_INT_<year> layer of the HSIP GIS: Intersection ID "
                  "TSUINT..., Legacy PH, rank, county, city, routes and the "
                  "warrant flags behind the rank). The PH number goes in "
                  "every map footer.",
                  "docs/12", "package-maps (ph)"),
    ]
    if shape.key == st.INTERSECTION:
        out.append(Criterion(
            "Context",
            "Urban or rural from the HSIP GIS City field: a municipality "
            "name is urban, RURAL is rural. The context sets the pull "
            "length (5 years urban, 10 rural) and the warrant set (IU or "
            "IR sheet); the recency sub-tests (1 year; 2 years urban, 3 "
            "rural; K and A frontal impact in the last 5) always count "
            "back from the analysis end date."
            + ("" if context else " This study has no context recorded "
               "yet; set it before the pull."),
            "docs/12", "HSIP Warrants page (Context); criteria --context"))
    if years:
        out.append(Criterion(
            "Analysis period",
            f"{years} years, ending on the last day of the most recent "
            "complete month of TEAAS data and beginning the first of the "
            "month that many years earlier (41000079736, rural: 9/1/2016 "
            "to 8/31/2026; its 5-year urban check 9/1/2021 to 8/31/2026).",
            "docs/12; examples/41000079736", "criteria.analysis_period"))
    else:
        out.append(Criterion(
            "Analysis period",
            "5 years for an urban intersection, 10 for a rural one, "
            "anchored on the last day of the most recent complete month of "
            "TEAAS data; the context decides.",
            "docs/12", "criteria.analysis_period"))
    out.append(Criterion(
        "Crash scope",
        "Animal crashes are deleted (status DEL) and leave the total, the "
        "rate and every warrant share; the 2024 Overview removes them "
        "because a countermeasure does not address deer (41000079305: 12 of "
        "17 DEL rows are animal crashes)."
        + (" Bicycle and pedestrian crashes only." if shape.key == st.BIKEPED
           else ""),
        "docs/12; study_type (deletes_animals=True)",
        "fiche-workbook (DEL for animals)"))
    if shape.key == st.SECTION:
        mins = "; ".join(f"{k}: {t} total and {m} per mile"
                         for k, (t, m) in FACILITY_MINIMUMS.items())
        shares = "; ".join(f"{k} {d} {int(round(s * 100))} %"
                           for k, (_, s, d) in SECTION_WARRANTS.items())
        out.append(Criterion(
            "Section warrants",
            "Two tests in series over the 5-year period. First both "
            f"minimums, strictly greater than ({mins}). Then a pattern "
            f"share ({shares}). Run off road is eight types (ROR right, "
            "left and straight, fixed object, overturn, sideswipe opposite "
            "direction, parked motor vehicle, head on); sideswipe same "
            "direction counts only when the engineer opts in for a "
            "multilane section. Shares are rounded to whole percents before "
            "the test. N-4's base is the non-intersection crashes (total "
            "less angle, LTDR, LTSR, RTDR, RTSR and U-turn).",
            "docs/12 (2024 HSIP Overview, the warrants workbook)",
            "warrants; HSIP Warrants page; warrants.screen_section"))
    else:
        names = ", ".join(f"{k} ({d})" for k, (c, d) in
                          INTERSECTION_WARRANTS.items()
                          if context in (None, c) or c == "both")
        out.append(Criterion(
            "Intersection warrants",
            f"{names}. Frontal impact is angle, LTDR, LTSR, RTDR, RTSR, "
            "U-turn and head on; severity is the EPDO Severity Index. "
            "Urban: I-1u 25 % of crashes in the last 2 years and (12 or "
            "more frontal impacts at 55 % or more, or 35 or more crashes "
            "at 35 % frontal with frontal severity 6 or more); I-2u 25 or "
            "more crashes and 38 % in the last year; I-3u 25 or more "
            "crashes, severity 6 or more and 40 % in the last 2 years; "
            "I-4u 25 % in the last 2 years, 12 or more night crashes at "
            "40 %. Rural: I-1r 20 % in the last 3 years, 9 or more frontal "
            "impacts at 60 %; I-2r 20 or more crashes and 32 % in the last "
            "year; I-3r 20 or more crashes, severity 9 or more and 30 % in "
            "the last 3 years; I-4r 20 % in the last 3 years, 10 or more "
            "night crashes at 46 %. I-3 (both): 3 or more K or A frontal "
            "impact crashes in the last 5 years. These are the 2024 "
            "thresholds; the 41000079736 study notes cite 2026 urban values "
            "(I-1u 60 % frontal, I-2u 40 %, I-3u severity 6.5 and 40 %, "
            "I-4u 45 %) that are not yet confirmed against the 2026 "
            "Overview, so the screen runs the 2024 values until they are.",
            "docs/12 (2024 HSIP Overview); examples/41000079736/README.md",
            "warrants; HSIP Warrants page; warrants.screen_intersection"))
    if shape.is_intersection:
        out.append(Criterion(
            "AADT",
            "Entering AADT = sum of the leg AADTs / 2 for the middle year "
            "of the study period, from NCDOT Traffic Survey Group station "
            "counts. A leg with no count that year gets a straight-line "
            "estimate between its nearest earlier and later counts, rounded "
            "per the NCDOT/AASHTO rounding chart (nearest 10 below 100, 50 "
            "to 999, 100 to 9,999, 500 to 99,999, 1,000 above) and labelled "
            "(estimate) on the diagram; the entering AADT rounds to the "
            "nearest hundred (TEAAS Chapter 8). The CalculatedAADT template "
            "keeps the ADT used in the TEAAS study unless the calculated "
            "value differs by more than 5 %.",
            "examples/41000079736/README.md; docs/04",
            "aadt; calc-aadt (4-LEG INTERSECTION ADT); Maps and Checks"))
    else:
        out.append(Criterion(
            "AADT",
            "Length-weighted section AADT for the middle year of the study "
            "period from NCDOT stations and traffic segments (the STRIP ADT "
            "sheet); the study ADT is kept unless the calculated value "
            "differs by more than the sheet's tolerance.",
            "docs/04; examples/260307016EA", "calc-aadt"))
    out.append(Criterion(
        "Package maps",
        "Location Map, Area Map and ADT Map in the package format: letter "
        "landscape, NC county inset with the county in red, north arrow and "
        "scale, red ring at the site, footer with WO Number, PH Number, "
        "NCDOT Division, Study Area, Lat and Long on one line, the "
        "data-source line and the VHB logo. The ADT map is the NCDOT AADT "
        "Mapping Application view with the study stations' histories and "
        "the year used boxed.",
        "examples/41000079736/README.md; docs/13 section 5",
        "package-maps; Maps and Checks"))
    if shape.key == st.BIKEPED:
        out.append(Criterion(
            "Collision diagram",
            "An aerial exhibit: the crash cells pinned on a semi-transparent "
            "aerial from the reports, street lighting as orange dots, "
            "pedestrian signal heads as orange squares, four blue markers "
            "for the bike/ped findings (driver failure to yield, non "
            "crosswalk location, bike or ped contributing action, no "
            "sidewalk or bike lane), leg labels with AADT and speed, land "
            "uses boxed, a Notes box with the infrastructure history "
            "(59X00239).",
            "docs/12; examples/59X00239", "collision_diagram.render_bikeped"))
    elif shape.is_intersection:
        out.append(Criterion(
            "Collision diagram",
            "The Traffic Safety Unit sheet, 17 by 11 in: legend, title "
            "block, north needle, the junction at its true skew, stop bars, "
            "leg labels with AADT (middle year) and posted speed; one "
            "numbered cell per crash in TEAAS report order at the tail of "
            "the at-fault path, fault asterisk, road surface letter, impact "
            "speed dots, day or dark arrowhead, injury circle by KABCO, "
            "target (frontal impact) crashes in red; page 2 is the crash "
            "listing the numbers refer to. Data is the TEAAS "
            "CollisionDiagramData export.",
            "examples/41000079736/README.md; docs/07",
            "tsu-diagram; junction-diagram; collision-diagram"))
    else:
        out.append(Criterion(
            "Collision diagram",
            "The strip sheet: fan-out callouts along the section with "
            "leaders to the true milepost, the features named at their "
            "mileposts, from the reviewed crashes.",
            "docs/07", "collision-diagram; Strip Collision Diagram page"))
    out.append(Criterion(
        "Fiche checks",
        "Before the review: the Fiche Report and the Detailed Fiche carry "
        "the same crash IDs; every Initial Study crash is on the fiche (one "
        "pulled from a road outside the fiche roads gets its own row); the "
        "intersection mileposts derived from the Initial Study match the "
        "Features Reports; every road code that reaches the site is in the "
        "pull.",
        "docs/03; examples/41000079736/README.md",
        "fiche-workbook (ID sheet); intersection-roads"))
    out.append(Criterion(
        "Workbook layout",
        "The reviewed fiche in the package FicheReport layout: IN STUDY, IN "
        "STUDY - ADDED, NOT IN STUDY - DELETED, NOT IN STUDY - REVIEWED, "
        "NOT IN STUDY - NOT REVIEWED, the reviewer's comments kept, a "
        "Warrant sheet beside it with the engineer's overrides in yellow.",
        "docs/02; examples/41000079736 (Fiche10yr)",
        "fiche-workbook; warrants (Warrant sheet)"))
    out.append(Criterion(
        "Memo",
        "A crash pattern summary based on the collision diagram and the "
        "warrant analysis, in plain style; the TEAAS Crash Analysis report "
        "(CSV and PDF) comes only from TEAAS after the import list and "
        "deletions are entered.",
        "docs/05; CLAUDE.md rule 9; examples/41000079736"))
    return out


def _evaluation(shape: st.AnalysisKind) -> list:
    out = [
        Criterion("Trigger",
                  "An NCDOT assignment (Assignment #N on the email thread: "
                  "Order ID 41000..., Project ID like SS-6002M, TIP number) "
                  "naming the countermeasure, its completion date and the "
                  "location; the Master Evaluation Spreadsheet row is the "
                  "record. The newest copy of each Assignment block wins.",
                  "docs/01; CLAUDE.md rule 10", "parse-email"),
        Criterion("Template",
                  "Start from NCDOT's provided template workbook "
                  "(Intersection or Section Evaluation Workbook, the Split "
                  "Time Periods variants, the office Accessible .xlsm) and "
                  "follow its Step-by-Step Instructions to the letter. Paste "
                  "the TEAAS fiche parameters export into Parameters. Only "
                  "columns A to M of Before and After are written; the "
                  "template's formulas compute the rest. Never resave a "
                  "workbook with drawings in openpyxl: XML-level edits, one "
                  "LibreOffice recalc, drawings and media byte-identical.",
                  "CLAUDE.md rules 3, 4, 8, 10; docs/02; docs/06",
                  "fill-template; Evaluation Workbook page (verify_integrity)"),
        Criterion("Periods",
                  "The Date Range Calculator on Evaluation Set-up: the most "
                  "recent TEAAS date, then construction in whole months "
                  "(start rounds up to the 1st, end rounds down to month "
                  "end; 3 months unless dates or imagery say otherwise), "
                  "before and after equal unless the unequal option is "
                  "justified; years = days / 365.25. Construction crashes "
                  "are excluded from the comparison but reviewed and "
                  "mentioned in Items for Discussion. Every fiche crash "
                  "lands in exactly one bin: prior, before, construction, "
                  "after, NIS reviewed, NIS not reviewed.",
                  "docs/02; docs/03; docs/04",
                  "fill-template --setup; Binned Crashes"),
        Criterion("Target crashes",
                  "Target-1 and Target-2 from the Typical Target Crash Types "
                  "sheet for the countermeasure: frontal impact (LTSR, LTDR, "
                  "RTSR, RTDR, head on, angle) for all-way stops, signals, "
                  "roundabouts and realignments; VEWF counts only crashes "
                  "involving a treated-approach vehicle (angle, LTDR, RTDR); "
                  "turn lanes take rear ends or LTSR on the treated "
                  "approaches. Flagged Y in Target-1? and Target-2? on "
                  "Before and After; the definition is stated on the "
                  "results sheet.",
                  "docs/08; docs/03", "fill-template --target1/--target2"),
        Criterion("Crash scope",
                  "Every crash in the limits is accounted for, animal "
                  "crashes included: a before/after comparison of a "
                  "treatment that never targeted deer still carries them "
                  "as non-target crashes.",
                  "docs/12; study_type (deletes_animals=False)"),
        Criterion("AADT",
                  "The AADT Calculator on Evaluation Set-up: a count for "
                  "every year inside the periods; the representative year "
                  "is the last year in each period with actual collected "
                  "counts, never 2020; black for counted values, red for "
                  "interpolated, assumed or carried values; minor legs to "
                  "the nearest hundred; 5 or more legs and one-way roads "
                  "get entering volumes computed by hand.",
                  "docs/02; docs/04; CLAUDE.md rule 7",
                  "aadt-table; AADT and Set-up page"),
    ]
    if not shape.is_intersection:
        out.append(Criterion(
            "Lane departure and correctability",
            "Each lane departure crash is CL (crossed the centerline) or R "
            "(ran off its own side) by the first harmful event; side-street "
            "run-throughs are not study-route departures and lose the "
            "target flag everywhere it appears; a dual centerline and "
            "edgeline treatment counts a crash correctable if the first "
            "event crossed either line; wet crashes are correctable for "
            "resurfacing, icy and snowy are not; mechanical failure, "
            "medical events and avoidance manoeuvres are exempt.",
            "docs/03", "ledger"))
    out += [
        Criterion("Assumptions",
                  "Go to NCDOT inside the workbook (Assumptions sheet, "
                  "Evaluation Set-up, the map block with alt text), not as a "
                  "separate email; the email draft exists for teams that "
                  "still ask for one.",
                  "CLAUDE.md rule 10", "assumptions"),
        Criterion("One pager",
                  "A public document: never mentions TEAAS, the workbook, "
                  "the fiche or any internal tool; no exact crash times, and "
                  "dates only when they matter; every crash-type acronym "
                  "spelled out in the target text; the countermeasure's "
                  "specific components described; alt text on every image; "
                  "exported with Save As PDF (tagged), never Print to PDF.",
                  "CLAUDE.md rule 11; docs/05",
                  "report-pdf; print-results; qa (style and alt text)"),
        Criterion("QC",
                  "Recount before delivering: Filtered Fiche, Binned Crashes "
                  "and Before/After tallies agree exactly; the lane "
                  "departure ledger is consistent across every sheet; every "
                  "'N crashes' quoted in the text equals a computed tally; "
                  "the deterministic QA runs on the workbook and the PDFs, "
                  "then the package QA and the optional sweep.",
                  "docs/03; docs/13", "qc; qa; qa-sweep"),
        Criterion("Statistics",
                  "Annualized frequencies (count / period years) for total, "
                  "target and severity; change and percent change on the "
                  "annualized values when the periods differ; raw counts "
                  "shown as well when they are symmetric; rates per MEV or "
                  "per 100 MVM from the representative AADTs.",
                  "docs/04", "the template's formulas"),
        Criterion("Warrants", "None. An evaluation measures a treatment that "
                  "is already built.", "docs/12"),
    ]
    return out


# --------------------------------------------------------------------------- #
# inputs and deliverables
# --------------------------------------------------------------------------- #
_FICHE_CORE = (
    Input("fiche_csv", True, "the working sheet"),
    Input("detailed_fiche_csv", True, "coordinates for placing crashes"),
    Input("initial_study_csv", True, "the Initial Study sheet"),
    Input("initial_ids_txt", True, "marks the Initial Study crashes"),
    Input("features_report", True, "mileposts of every feature on the route"),
    Input("crash_report", True, "the report review (redacted on intake)"),
)


def _inputs(kind: st.StudyType, shape: st.AnalysisKind) -> tuple:
    if kind.key == st.FATAL:
        return (Input("fatal_slip", True, "the assignment: crash, site, division"),
                ) + _FICHE_CORE + (
                Input("centerline", False, "route geometry for the location check and maps"),
                Input("location_map", False, "a provided map for the field file"))
    if kind.key == st.HSIP:
        return _FICHE_CORE + (
            Input("collision_diagram_data", shape.key != st.SECTION,
                  "the TEAAS unit-level export the collision diagram is drawn from"),
            Input("binder_index", False, "an indexed DMV-349 binder"))
    inputs = (
        Input("before_ids", True, "TEAAS Before Crash ID list"),
        Input("after_ids", True, "TEAAS After Crash ID list"),
        Input("fiche_csv", True, "the Original Fiche for enrichment and the Filtered Fiche"),
        Input("detailed_fiche_csv", False, "coordinates for the Filtered Fiche"),
        Input("crash_report", True, "the report review of the ? rows"),
        Input("setup_yaml", False, "dates, representative years, AADT tables"),
        Input("results_yaml", False, "results sheet text"),
        Input("statuses_workbook", False, "a workbook with the reviewed Filtered Fiche"),
    )
    if not shape.is_intersection:
        inputs += (Input("before_mp", True, "Before milepost import"),
                   Input("after_mp", True, "After milepost import"),
                   Input("features_report", True, "mileposts for binning"))
    return inputs


def _deliverables(kind: st.StudyType, shape: st.AnalysisKind) -> tuple:
    if kind.key == st.FATAL:
        return (
            Deliverable("Fiche workbook, screened", "fiche-workbook; fca build; Fiche Workbook page"),
            Deliverable("Review IDs and redacted DMV-349s", "binder-index / binder-get; Redact Crash Reports page"),
            Deliverable("Location check", "locate-check; Maps and Checks page"),
            Deliverable("Reviewed fiche workbook", "apply-review; fca build (determinations.jsonl); Review Queue"),
            Deliverable("TEAAS import list (ADD and RE) and feature list", "import-list; route-features"),
            Deliverable("Figures 1 to 4: Area, Location, Crash and AADT maps", "fca build; package-maps"),
            Deliverable("CalculatedAADT workbook", "calc-aadt"),
            Deliverable("Field Investigation File", "fatal-checklist"),
            Deliverable("Report review and analysis memo", "fca build (ReportReview.md); the engineer's memo"),
            Deliverable("Rerun ID export and strip or intersection analysis", "TEAAS only"),
        )
    if kind.key == st.HSIP:
        return (
            Deliverable("Fiche workbook in the package FicheReport layout", "fiche-workbook; Fiche Workbook page"),
            Deliverable("Reviewed workbook with the Warrant sheet", "apply-review; warrants; Review Queue"),
            Deliverable("TEAAS import list (ADD and RE)", "import-list"),
            Deliverable("Warrant screen", "warrants; HSIP Warrants page"),
            Deliverable("Location, Area and ADT package maps", "package-maps; Maps and Checks page"),
            Deliverable("CalculatedAADT workbook", "calc-aadt; Maps and Checks page"),
            Deliverable("Collision diagram", "tsu-diagram / junction-diagram / collision-diagram"
                        if shape.key != st.BIKEPED else "collision_diagram.render_bikeped"),
            Deliverable("Crash pattern summary and warrant memo", "the engineer's memo (docs/05 style)"),
            Deliverable("TEAAS Crash Analysis report (CSV and PDF)", "TEAAS only"),
        )
    out = (
        Deliverable("Evaluation Workbook from the NCDOT template", "fill-template; Evaluation Workbook page"),
        Deliverable("Evaluation Set-up (periods, AADT table) and Assumptions", "aadt-table; AADT and Set-up page"),
        Deliverable("Map block with alt text", "map-block; Map Block page"),
    )
    if not shape.is_intersection:
        out += (Deliverable("Strip collision diagram", "collision-diagram; Strip Collision Diagram page"),)
    out += (
        Deliverable("Results text (Items for Discussion, Additional Information)", "draft-results; Report Text page"),
        Deliverable("One pager", "report-pdf; the template's One Pager sheet", public=True),
        Deliverable("Complete Evaluation PDF and Web PDF", "print-results; Print and Assemble page", public=True),
        Deliverable("QA log and certificate", "qa; qa-sweep; QA Checks page"),
        Deliverable("Finished package zip (no 'TIP #' in names)", "finish; Finish Package page"),
    )
    return out


# --------------------------------------------------------------------------- #
# assembly
# --------------------------------------------------------------------------- #
def for_study(study_type, analysis=None, context=None) -> StudyCriteria:
    """The criteria for a study type, its analysis and (HSIP intersection)
    its urban or rural context. An unknown type or analysis raises
    ValueError, as does a context on a study that has none."""
    kind = st.get(study_type)
    a_key = st.check_analysis(kind, analysis or kind.default_analysis)
    shape = st.ANALYSIS_KINDS[a_key]
    ctx = (str(context).strip().lower() or None) if context else None
    if ctx is not None and ctx not in CONTEXTS:
        raise ValueError(f"context must be urban or rural, not {context!r}")
    if ctx is not None and not (kind.key == st.HSIP and a_key == st.INTERSECTION):
        raise ValueError("only an HSIP intersection analysis takes an urban "
                         "or rural context")
    years = period_years(kind, a_key, ctx)
    yline = shape.yline_ft
    rules = _limits(shape, yline)
    if kind.key == st.FATAL:
        rules += _fatal(shape, years)
    elif kind.key == st.HSIP:
        rules += _hsip(shape, ctx, years)
    else:
        rules += _evaluation(shape)
    rules += _common(shape)
    warrants = ()
    if kind.runs_warrants:
        if a_key == st.SECTION:
            warrants = tuple(SECTION_WARRANTS)
        else:
            warrants = tuple(k for k, (c, _) in INTERSECTION_WARRANTS.items()
                             if ctx is None or c in (ctx, "both"))
    return StudyCriteria(
        study_type=kind.key, analysis=a_key, context=ctx, years=years,
        yline_ft=yline,
        review_statuses=REVIEW_STATUSES[shape.site],
        warrants=warrants, criteria=tuple(rules),
        inputs=_inputs(kind, shape), deliverables=_deliverables(kind, shape))


def for_workspace(ws) -> StudyCriteria:
    """The criteria of an open study: its type and analysis come off the
    manifest, the context off the ``context`` param when it is set."""
    ctx = ws.param("context")
    if not (ws.study_type == st.HSIP and ws.analysis == st.INTERSECTION):
        ctx = None
    return for_study(ws.study_type, ws.analysis, ctx)


def all_criteria() -> list:
    """Every sheet, in the order the app offers the study types."""
    out = []
    for key in st.ORDER:
        for a_key in st.analyses_for(key):
            if key == st.HSIP and a_key == st.INTERSECTION:
                out += [for_study(key, a_key, c) for c in CONTEXTS]
            else:
                out.append(for_study(key, a_key))
    return out


# --------------------------------------------------------------------------- #
# checking a study against its criteria
# --------------------------------------------------------------------------- #
def check_params(crit: StudyCriteria, params) -> list:
    """What the study's recorded params still owe its criteria, in words.

    Only what is present is checked: a missing period is not a finding
    (the pull may not have happened yet), a recorded period of the wrong
    length is. Returns an empty list when nothing is owed.
    """
    params = dict(params or {})
    notes = []
    shape = crit.shape
    if crit.study_type == st.HSIP and crit.analysis == st.INTERSECTION \
            and crit.context is None:
        notes.append("Set the context (urban or rural, from the HSIP GIS "
                     "City field): it decides the pull length, 5 or 10 "
                     "years, and the warrant set.")
    if not shape.is_intersection:
        lo, hi = params.get("mp_lo"), params.get("mp_hi")
        if lo in (None, "", 0) and hi in (None, "", 0):
            notes.append("Enter the begin and end mileposts of the section.")
        else:
            try:
                if float(lo) >= float(hi):
                    notes.append("The begin milepost must be below the end "
                                 f"milepost (got {lo} and {hi}).")
            except (TypeError, ValueError):
                notes.append("The mileposts must be numbers.")
    elif params.get("center_lat") in (None, "") \
            or params.get("center_lon") in (None, ""):
        notes.append("Record the intersection's coordinates (the map "
                     "footers and the distance screen use them).")
    y = params.get("yline_ft")
    if y not in (None, "") and crit.yline_ft is not None:
        try:
            if int(float(y)) != crit.yline_ft:
                notes.append(f"The y-line is recorded as {y} ft; the "
                             f"{crit.shape.label.lower()} pull is "
                             f"{crit.yline_ft} ft. Keep an extension only "
                             "with its reason on the Assumptions.")
        except (TypeError, ValueError):
            notes.append("The y-line must be a number of feet.")
    yrs = params.get("years")
    if yrs not in (None, "") and crit.years is not None:
        try:
            if abs(float(yrs) - crit.years) > 0.05:
                notes.append(f"The period is recorded as {yrs} years; this "
                             f"study is a {crit.years}-year pull.")
        except (TypeError, ValueError):
            notes.append("The period length must be a number of years.")
    begin, end = params.get("period_begin"), params.get("period_end")
    if begin and end and crit.years is not None:
        try:
            b = dt.date.fromisoformat(str(begin))
            e = dt.date.fromisoformat(str(end))
        except ValueError:
            notes.append("Period dates must be ISO dates (2021-09-01).")
        else:
            span = ((e - b).days + 1) / 365.25
            if abs(span - crit.years) > 0.05:
                notes.append(f"The recorded period {b} to {e} spans "
                             f"{span:.2f} years; this study is a "
                             f"{crit.years}-year pull.")
            exp_b, exp_e = analysis_period(e, crit.years)
            if e != month_end(e):
                notes.append(f"The period ends {e}, not on a month end; the "
                             "pull ends on the last day of the most recent "
                             "complete month of TEAAS data.")
            elif exp_b != b:
                notes.append(f"A {crit.years}-year pull ending {e} begins "
                             f"{exp_b}, not {b}.")
    return notes


# --------------------------------------------------------------------------- #
# rendering
# --------------------------------------------------------------------------- #
def to_dict(crit: StudyCriteria) -> dict:
    d = asdict(crit)
    d["title"] = crit.title
    d["period"] = crit.period_text
    d["limits"] = crit.limits_text
    for i, inp in enumerate(crit.inputs):
        d["inputs"][i]["label"] = inp.label
    return d


def _md_cell(text: str) -> str:
    return str(text).replace("|", "\\|").replace("\n", " ")


def to_markdown(crit: StudyCriteria, heading: str = "#") -> str:
    lines = [f"{heading} {crit.title}", ""]
    lines.append(f"- **Analysis period:** {crit.period_text}.")
    lines.append(f"- **Study limits:** {crit.limits_text}.")
    lines.append("- **Review statuses:** " + ", ".join(crit.review_statuses)
                 + ".")
    lines.append("- **Warrants:** " + (", ".join(crit.warrants) if crit.warrants
                                      else "none") + ".")
    lines += ["", f"{heading}# Criteria", "",
              "| Topic | Rule | Source | Applied by |", "|---|---|---|---|"]
    for c in crit.criteria:
        lines.append(f"| {_md_cell(c.topic)} | {_md_cell(c.rule)} | "
                     f"{_md_cell(c.source)} | {_md_cell(c.tool) or ' '} |")
    lines += ["", f"{heading}# Inputs", "",
              "| Input | Required | Why |", "|---|---|---|"]
    for i in crit.inputs:
        lines.append(f"| {_md_cell(i.label)} | {'yes' if i.required else 'optional'} "
                     f"| {_md_cell(i.why)} |")
    lines += ["", f"{heading}# Deliverables", "",
              "| Deliverable | How |", "|---|---|"]
    for d in crit.deliverables:
        pub = " (public document)" if d.public else ""
        lines.append(f"| {_md_cell(d.name)}{pub} | {_md_cell(d.how)} |")
    return "\n".join(lines) + "\n"


CATALOGUE_INTRO = """# 15 - Study criteria

Generated by `safety-eval criteria --all`; edit `safety_eval/criteria.py`,
not this file (a test keeps the two in step). One sheet per study type and
analysis, with the urban and rural HSIP intersection sheets apart because
their pull length and warrant set differ. Every rule names its source and
the command or page that applies it.
"""


def markdown_catalogue() -> str:
    parts = [CATALOGUE_INTRO]
    for crit in all_criteria():
        parts.append(to_markdown(crit, heading="##"))
    return "\n".join(parts)
