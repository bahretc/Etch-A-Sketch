"""The three kinds of NCDOT crash study, and what differs between them.

Fatal Crash Analyses, HSIP Package Analyses, and Evaluations share the whole
fiche and crash-review core: the same TEAAS exports, the same working sheet,
the same IS / RE / ADD / DEL / NIS vocabulary, the same report review. Only a
few things branch, and this module is the branch, so the difference lives in
one place instead of being remembered at each call site.

What actually differs:

* **Warrants.** Only an HSIP package asks whether a location warrants a
  project (docs/12). An evaluation measures a treatment that is already built;
  a fatal analysis investigates one crash.
* **Animal crashes.** On an HSIP section or intersection analysis they are
  **deleted**, not merely set aside: status DEL, out of the study. The 2024
  Overview removes them from the section warrant maths, and the working
  practice removes them from the study entirely, which is stronger and simpler
  to defend. Verified on study 41000079305: 12 of 17 DEL rows are animal
  crashes and no animal survives into IS/RE/ADD.
  An evaluation keeps them, because a before/after comparison of a treatment
  that never targeted deer still has to account for every crash in the section.
"""
from __future__ import annotations

from dataclasses import dataclass

FATAL = "fatal"
HSIP = "hsip"
EVALUATION = "evaluation"


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

#: What the app offers at set-up, in the order it offers it.
ORDER = (HSIP, EVALUATION, FATAL)


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
