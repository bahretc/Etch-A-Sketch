"""Date Range Calculator: derive before / construction / after study periods.

Mirrors the 'Evaluation Set-up' logic in the Section Evaluation Workbook:

* The **construction** period is the window the countermeasure was being built.
* The **before** period ends the day construction starts.
* The **after** period begins the day after construction ends.
* If only a construction length (months) is known, it is centered such that the
  before and after periods are of comparable length within the study window.
"""
from __future__ import annotations

from datetime import date, timedelta

from .config import Config
from .models import Assignment, Period


def _add_months(d: date, months: int) -> date:
    m = d.month - 1 + months
    year = d.year + m // 12
    month = m % 12 + 1
    # clamp day to end of month
    day = min(d.day, [31, 29 if year % 4 == 0 and (year % 100 != 0 or year % 400 == 0)
                      else 28, 31, 30, 31, 30, 31, 31, 30, 31, 30, 31][month - 1])
    return date(year, month, day)


def build_periods(assignment: Assignment, cfg: Config) -> dict[str, Period]:
    """Return {'before': Period, 'construction': Period, 'after': Period}.

    Requires ``study_start`` and ``study_end``.  Construction can be given as an
    explicit start/end, or as a month count (centered), or defaulted from config.
    """
    if not assignment.study_start or not assignment.study_end:
        raise ValueError("Assignment requires study_start and study_end dates.")

    start, end = assignment.study_start, assignment.study_end
    c_start = assignment.construction_start
    c_end = assignment.construction_end

    if c_start and c_end:
        pass
    elif c_start and assignment.construction_months:
        c_end = _add_months(c_start, assignment.construction_months)
    elif c_end and assignment.construction_months:
        c_start = _add_months(c_end, -assignment.construction_months)
    else:
        months = assignment.construction_months or cfg.methodology["default_construction_months"]
        # center the construction window in the study span
        total_days = (end - start).days
        mid = start + timedelta(days=total_days // 2)
        c_start = _add_months(mid, -(months // 2))
        c_end = _add_months(c_start, months)

    before = Period("before", start, c_start - timedelta(days=1))
    construction = Period("construction", c_start, c_end)
    after = Period("after", c_end + timedelta(days=1), end)
    return {"before": before, "construction": construction, "after": after}
