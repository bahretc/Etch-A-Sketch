"""Before/after crash analysis, rates, and countermeasure effectiveness."""
from __future__ import annotations

from .config import Config
from .models import Assignment, Crash, EvaluationResult, Period, PeriodStats


def epdo(counts: dict, cfg: Config) -> float:
    """EPDO = sum(weight_letter * count_letter).

    docs/04: EPDO = 76.8*(K+A) + 8.4*(B+C) + 1.0*PDO (active NCDOT weights).
    ``counts`` maps severity letters to counts, e.g. {'K':1,'A':3,'B':2,...}.
    """
    return sum(cfg.epdo_weight(letter) * n for letter, n in counts.items())


def severity_index(counts: dict, cfg: Config) -> float | None:
    """Severity Index = EPDO / total crashes (docs/04)."""
    total = sum(counts.values())
    return epdo(counts, cfg) / total if total else None


def _period_stats(
    name: str,
    period: Period,
    crashes: list[Crash],
    aadt: float | None,
    targets: list[str],
    cfg: Config,
) -> PeriodStats:
    st = PeriodStats(period=name, years=period.years, aadt=aadt)
    st.by_severity = {letter: 0 for letter in cfg.severity_order}
    st.by_target = {t: 0 for t in targets}
    for crash in crashes:
        if not crash.in_study or crash.period != name:
            continue
        st.total += 1
        sev = (crash.s or "").upper()
        if sev in st.by_severity:
            st.by_severity[sev] += 1
        if sev in cfg.injury_letters:
            st.injuries += 1
        if sev == "K":
            st.fatalities += 1
        st.epdo += cfg.epdo_weight(sev) if sev else 0
        for t in crash.target_types:
            if t in st.by_target:
                st.by_target[t] += 1
    return st


def crash_rate(total: int, years: float, aadt: float | None, length_mi: float | None,
               intersection: bool) -> float | None:
    """Segment rate = crashes per 100M vehicle-miles; intersection = per MEV."""
    if not aadt or years <= 0:
        return None
    if intersection:
        million_entering = aadt * 365.25 * years / 1_000_000
        return total / million_entering if million_entering else None
    if not length_mi:
        return None
    hundred_mvm = aadt * 365.25 * years * length_mi / 100_000_000
    return total / hundred_mvm if hundred_mvm else None


def before_after(result: EvaluationResult, cfg: Config) -> dict:
    """Compute naive before/after effectiveness, adjusted for time & traffic.

    expected_after = before * (after_years / before_years) * (aadt_after / aadt_before)
    percent_reduction = (expected_after - observed_after) / expected_after * 100
    """
    b = result.stats.get("before")
    a = result.stats.get("after")
    if not b or not a:
        return {}
    meth = cfg.methodology
    out: dict = {}

    def _reduction(before_n: int, after_n: int) -> dict:
        factor = 1.0
        if meth.get("adjust_for_time") and b.years > 0:
            factor *= a.years / b.years
        if meth.get("adjust_for_traffic") and b.aadt and a.aadt:
            factor *= a.aadt / b.aadt
        expected = before_n * factor
        pct = ((expected - after_n) / expected * 100) if expected else None
        return {
            "before": before_n,
            "after": after_n,
            "expected_after": round(expected, 2),
            "adjustment_factor": round(factor, 4),
            "reduction_pct": round(pct, 1) if pct is not None else None,
        }

    out["total"] = _reduction(b.total, a.total)
    out["by_severity"] = {
        letter: _reduction(b.by_severity.get(letter, 0), a.by_severity.get(letter, 0))
        for letter in cfg.severity_order
    }
    out["injuries"] = _reduction(b.injuries, a.injuries)
    out["fatalities"] = _reduction(b.fatalities, a.fatalities)
    out["by_target"] = {
        t: _reduction(b.by_target.get(t, 0), a.by_target.get(t, 0))
        for t in b.by_target
    }
    length = result.assignment.length_miles
    if length is None and result.assignment.section_begin_mp is not None \
            and result.assignment.section_end_mp is not None:
        length = abs(result.assignment.section_end_mp - result.assignment.section_begin_mp)
    intersection = result.assignment.intersection_study
    out["rates"] = {
        "before": crash_rate(b.total, b.years, b.aadt, length, intersection),
        "after": crash_rate(a.total, a.years, a.aadt, length, intersection),
    }
    if out["rates"]["before"] and out["rates"]["after"]:
        rb, ra = out["rates"]["before"], out["rates"]["after"]
        out["rate_reduction_pct"] = round((rb - ra) / rb * 100, 1)
    return out


def evaluate(
    crashes: list[Crash],
    assignment: Assignment,
    periods: dict[str, Period],
    cfg: Config,
) -> EvaluationResult:
    targets = assignment.target_crash_types or list(cfg.target_definitions.keys())
    stats = {
        name: _period_stats(
            name, periods[name], crashes,
            assignment.aadt_before if name == "before"
            else assignment.aadt_after if name == "after" else None,
            targets, cfg,
        )
        for name in periods
    }
    result = EvaluationResult(
        assignment=assignment, periods=periods, stats=stats, crashes=crashes,
    )
    result.before_after = before_after(result, cfg)

    # data-quality warnings
    no_date = sum(1 for c in crashes if c.date is None)
    no_mp = sum(1 for c in crashes if c.mp is None)
    unclassified = sum(
        1 for c in crashes if c.in_study and c.period is None and c.date is not None
    )
    if no_date:
        result.warnings.append(f"{no_date} crash(es) had no parseable date.")
    if no_mp:
        result.warnings.append(f"{no_mp} crash(es) had no milepost (in-study undetermined).")
    if unclassified:
        result.warnings.append(
            f"{unclassified} in-study crash(es) fell in no study period "
            "(check study/construction dates)."
        )
    return result
