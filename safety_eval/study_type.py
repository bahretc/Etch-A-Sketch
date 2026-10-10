"""The three kinds of NCDOT crash study, what differs between them, and the
analysis each one looks at (an intersection, a section, or a bike/ped
intersection).

Fatal Crash Analyses, HSIP Package Analyses, and Evaluations share the whole
fiche and crash-review core: the same TEAAS exports, the same working sheet,
the same IS / RE / ADD / DEL / NIS vocabulary, the same report review. Only a
few things branch, and this module is the branch, so the difference lives in
one place instead of being remembered at each call site.

What actually differs between the study types:

* **Warrants.** Only an HSIP package asks whether a location warrants a
  project (docs/12). An evaluation measures a treatment that is already built;
  a fatal analysis investigates one crash.
* **Animal crashes.** On an HSIP section or intersection analysis they are
  **deleted**, not merely set aside: status DEL, out of the study. The HSIP
  warrant text (2026 as in 2024) removes them from the section warrant maths,
  and the working practice removes them from the study entirely, which is
  stronger and simpler to defend. Verified on study 41000079305: 12 of 17 DEL
  rows are animal crashes and no animal survives into IS/RE/ADD.
  An evaluation keeps them, because a before/after comparison of a treatment
  that never targeted deer still has to account for every crash in the section.

What differs between the analyses (CLAUDE.md rule 5): an **intersection**
analysis is road-combination-dependent and pulls crashes inside a y-line
around one junction; a **section** analysis is milepost-dependent and pulls a
strip of one route. A **bike/ped intersection** analysis is the HSIP
package's third shape: bicycle and pedestrian crashes only, always a 10-year
intersection pull with a 300 ft y-line, drawn on an aerial exhibit rather
than a schematic (docs/12). The study carries its analysis on the manifest
beside its type, so every page starts from the same answer.
"""
from __future__ import annotations

from dataclasses import dataclass

FATAL = "fatal"
HSIP = "hsip"
EVALUATION = "evaluation"

INTERSECTION = "intersection"
SECTION = "section"
BIKEPED = "bikeped"


@dataclass(frozen=True)
class StudyType:
    """One study type and the behaviour that hangs off it."""
    key: str
    label: str
    #: Run the HSIP warrant screen (docs/12).
    runs_warrants: bool
    #: Animal crashes are DEL rather than reviewed.
    deletes_animals: bool
    description: str

    def __str__(self) -> str:
        return self.label

    @property
    def analyses(self) -> tuple:
        """The analysis kinds this study type offers, in the order offered."""
        return ANALYSES[self.key]

    @property
    def default_analysis(self) -> str:
        return ANALYSES[self.key][0]


@dataclass(frozen=True)
class AnalysisKind:
    """What the study looks at, and the few facts that hang off it."""
    key: str
    label: str
    #: The site vocabulary of the package maps and the fatal checklist:
    #: ``"strip"`` for a section, ``"intersection"`` for the two others.
    site: str
    #: The TEAAS y-line, in feet, for an intersection pull; None for a strip.
    yline_ft: int | None
    #: A study period the analysis fixes (bike/ped: 10 years); None when the
    #: period comes from the assignment or the NCDOT HSIP GIS instead.
    years: int | None
    description: str

    def __str__(self) -> str:
        return self.label

    @property
    def is_intersection(self) -> bool:
        """True for both intersection shapes; False for a section."""
        return self.site == "intersection"


STUDY_TYPES = {
    FATAL: StudyType(
        key=FATAL, label="Fatal Crash Analysis",
        runs_warrants=False, deletes_animals=False,
        description="Investigates one fatal crash. Field investigation "
                    "workbook and fatal crash slips; no warrant test."),
    HSIP: StudyType(
        key=HSIP, label="HSIP Package Analysis",
        runs_warrants=True, deletes_animals=True,
        description="Asks whether a location warrants a project. Runs the "
                    "section or intersection warrants; animal crashes are "
                    "deleted from the study."),
    EVALUATION: StudyType(
        key=EVALUATION, label="Evaluation",
        runs_warrants=False, deletes_animals=False,
        description="Before/after evaluation of a treatment already built. "
                    "Produces the NCDOT Evaluation Workbook; every crash in "
                    "the section is accounted for, animals included."),
}

ANALYSIS_KINDS = {
    INTERSECTION: AnalysisKind(
        key=INTERSECTION, label="Intersection", site="intersection",
        yline_ft=150, years=None,
        description="One junction: a TEAAS intersection analysis over the "
                    "road combinations with a 150 ft y-line; the junction "
                    "collision diagram."),
    SECTION: AnalysisKind(
        key=SECTION, label="Section", site="strip",
        yline_ft=None, years=None,
        description="A strip of one route between mileposts: a TEAAS strip "
                    "analysis; the strip collision diagram."),
    BIKEPED: AnalysisKind(
        key=BIKEPED, label="Bike/Ped Intersection", site="intersection",
        yline_ft=300, years=10,
        description="Bicycle and pedestrian crashes only at one junction: "
                    "a 10-year TEAAS intersection analysis with a 300 ft "
                    "y-line, drawn on an aerial exhibit (docs/12)."),
}

#: The analyses each study type offers, in the order offered; the first is
#: the default for a new study. Bike/ped is an HSIP package shape only.
ANALYSES = {
    FATAL: (SECTION, INTERSECTION),
    HSIP: (SECTION, INTERSECTION, BIKEPED),
    EVALUATION: (INTERSECTION, SECTION),
}

#: What the app offers at set-up, in the order it offers it.
ORDER = (HSIP, EVALUATION, FATAL)

#: Older vocabularies for an analysis, accepted anywhere a key is accepted:
#: the package-maps ``site`` values and the collision diagram layout kinds.
_ANALYSIS_ALIASES = {
    "strip": SECTION, "section (strip)": SECTION,
    "junction": INTERSECTION,
    "bike/ped": BIKEPED, "bike-ped": BIKEPED, "bike_ped": BIKEPED,
    "bikeped intersection": BIKEPED, "bike/ped (aerial)": BIKEPED,
}


def get(key) -> StudyType:
    """Look up a study type, accepting a key, a label, or a StudyType."""
    if isinstance(key, StudyType):
        return key
    text = str(key or "").strip().lower()
    if text in STUDY_TYPES:
        return STUDY_TYPES[text]
    for st in STUDY_TYPES.values():
        if text == st.label.lower():
            return st
    raise ValueError(
        f"unknown study type {key!r}; expected one of {sorted(STUDY_TYPES)}")


def choices() -> list:
    """``[(key, label), ...]`` for a CLI argument or a UI selector."""
    return [(k, STUDY_TYPES[k].label) for k in ORDER]


def get_analysis(key) -> AnalysisKind:
    """Look up an analysis kind, accepting a key, a label, an older alias
    (``strip``, ``junction``, ``bike/ped``) or an AnalysisKind."""
    if isinstance(key, AnalysisKind):
        return key
    text = str(key or "").strip().lower()
    if text in ANALYSIS_KINDS:
        return ANALYSIS_KINDS[text]
    if text in _ANALYSIS_ALIASES:
        return ANALYSIS_KINDS[_ANALYSIS_ALIASES[text]]
    for kind in ANALYSIS_KINDS.values():
        if text == kind.label.lower():
            return kind
    raise ValueError(
        f"unknown analysis {key!r}; expected one of {sorted(ANALYSIS_KINDS)}")


def analyses_for(study_type) -> tuple:
    """The analysis keys a study type offers, in the order offered."""
    return get(study_type).analyses


def default_analysis(study_type) -> str:
    """The analysis a new study of this type gets when none is chosen."""
    return get(study_type).default_analysis


def check_analysis(study_type, analysis) -> str:
    """Normalise ``analysis`` for ``study_type``; raises ValueError when the
    study type does not offer it (a bike/ped evaluation, say)."""
    kind = get(study_type)
    key = get_analysis(analysis).key
    if key not in kind.analyses:
        offered = " or ".join(ANALYSIS_KINDS[k].label for k in kind.analyses)
        raise ValueError(
            f"{kind.label} studies are {offered} analyses, not "
            f"{ANALYSIS_KINDS[key].label}")
    return key


def analysis_choices(study_type) -> list:
    """``[(key, label), ...]`` of the analyses a study type offers."""
    return [(k, ANALYSIS_KINDS[k].label) for k in analyses_for(study_type)]
