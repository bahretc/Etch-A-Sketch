"""Classify crashes: in-study/out-of-study, study period, and target crash types."""
from __future__ import annotations

from .config import Config
from .models import Assignment, Crash, Period


# --------------------------------------------------------------------------- #
# In-study / out-of-study
# --------------------------------------------------------------------------- #
def classify_in_study(crash: Crash, assignment: Assignment, cfg: Config) -> bool:
    """Decide whether a crash falls within the study section.

    A crash is in-study when its milepost lies within the section limits.
    Intersection crashes (mp == sentinel) are included only for intersection
    studies. Crashes with no usable milepost are left for manual review.
    """
    if assignment.section_begin_mp is None or assignment.section_end_mp is None:
        return True  # no limits provided -> keep everything, flag later
    lo = min(assignment.section_begin_mp, assignment.section_end_mp)
    hi = max(assignment.section_begin_mp, assignment.section_end_mp)

    if crash.mp is None:
        return False
    if abs(crash.mp - cfg.mp_sentinel) < 1e-6:
        return assignment.intersection_study
    return lo - 1e-9 <= crash.mp <= hi + 1e-9


# --------------------------------------------------------------------------- #
# Study period bucketing
# --------------------------------------------------------------------------- #
def assign_period(crash: Crash, periods: dict[str, Period]) -> str | None:
    if crash.date is None:
        return None
    for name in ("before", "construction", "after"):
        p = periods.get(name)
        if p and p.start <= crash.date <= p.end:
            return name
    return None


# --------------------------------------------------------------------------- #
# Target crash type classification
# --------------------------------------------------------------------------- #
def _matches_target(crash: Crash, definition: dict, cfg: Config) -> bool:
    type_code = crash.coded(cfg.role_letter("crash_type"))
    road_code = crash.coded(cfg.role_letter("road_surface"))
    light_code = crash.coded(cfg.role_letter("light"))

    if "type_group" in definition:
        if type_code is None or type_code not in cfg.crash_type_group(definition["type_group"]):
            return False
    if definition.get("road_surface") == "wet":
        if road_code is None or road_code not in cfg.wet_codes:
            return False
    if definition.get("light") == "night":
        if light_code is None or light_code not in cfg.night_codes:
            return False
    if definition.get("truck"):
        if type_code is None or type_code not in cfg.truck_codes:
            return False
    return True


def classify_targets(crash: Crash, target_names: list[str], cfg: Config) -> list[str]:
    """Return the subset of requested target names that this crash matches."""
    hits: list[str] = []
    defs = cfg.target_definitions
    for name in target_names:
        definition = defs.get(name)
        if definition and _matches_target(crash, definition, cfg):
            hits.append(name)
    return hits


def classify_all(
    crashes: list[Crash],
    assignment: Assignment,
    periods: dict[str, Period],
    cfg: Config,
) -> None:
    """Populate ``in_study``, ``period`` and ``target_types`` on each crash in place."""
    targets = assignment.target_crash_types or list(cfg.target_definitions.keys())
    for crash in crashes:
        crash.in_study = classify_in_study(crash, assignment, cfg)
        crash.period = assign_period(crash, periods)
        crash.target_types = classify_targets(crash, targets, cfg)
