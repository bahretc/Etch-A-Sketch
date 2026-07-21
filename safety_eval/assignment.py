"""Load the 'initial study' / assignment from a YAML file.

A future enhancement can parse this directly from the assignment/assumptions
email (.msg/.eml); for now the human transcribes it once into a small YAML,
which also serves as the auditable record of study assumptions.
"""
from __future__ import annotations

from datetime import date, datetime

import yaml

from .models import Assignment


def _as_date(v) -> date | None:
    if v is None or v == "":
        return None
    if isinstance(v, date):
        return v
    if isinstance(v, datetime):
        return v.date()
    for fmt in ("%Y-%m-%d", "%m/%d/%Y", "%m/%d/%y"):
        try:
            return datetime.strptime(str(v).strip(), fmt).date()
        except ValueError:
            continue
    raise ValueError(f"Unrecognized date: {v!r}")


def load_assignment(path: str) -> Assignment:
    with open(path) as fh:
        d = yaml.safe_load(fh) or {}
    return Assignment(
        project_id=str(d.get("project_id", "")),
        description=str(d.get("description", "")),
        county=str(d.get("county", "")),
        route=str(d.get("route", "")),
        section_begin_mp=_num(d.get("section_begin_mp")),
        section_end_mp=_num(d.get("section_end_mp")),
        intersection_study=bool(d.get("intersection_study", False)),
        length_miles=_num(d.get("length_miles")),
        countermeasure=str(d.get("countermeasure", "")),
        target_crash_types=list(d.get("target_crash_types", []) or []),
        study_start=_as_date(d.get("study_start")),
        study_end=_as_date(d.get("study_end")),
        construction_start=_as_date(d.get("construction_start")),
        construction_end=_as_date(d.get("construction_end")),
        construction_months=_int(d.get("construction_months")),
        aadt_before=_num(d.get("aadt_before")),
        aadt_after=_num(d.get("aadt_after")),
        assumptions=list(d.get("assumptions", []) or []),
        notes=str(d.get("notes", "")),
    )


def _num(v):
    if v is None or v == "":
        return None
    return float(str(v).replace(",", ""))


def _int(v):
    n = _num(v)
    return int(n) if n is not None else None
