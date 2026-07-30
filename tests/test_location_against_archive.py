"""Resolver checked against a real reviewed evaluation (04-15-39049).

The example workbook carries 2,315 rows with the engineer's own determinations,
and examples/features holds the SR 1003 features report they were located from.
This pins the two findings from that comparison: the resolver reproduces the
coded milepost, and a disagreement does NOT indicate the engineer remileposted.
"""
import os
import statistics

import pytest

from safety_eval.location import FeatureInventory, ReportLocation, resolve
from safety_eval.review_queue import load_review_sheet

WB = "examples/04-15-39049/Section Evaluation Workbook - 04-15-39049.xlsx"
FEATURES = "examples/features/SR1003_Johnston_FeaturesReport.txt"
pytestmark = pytest.mark.skipif(
    not (os.path.exists(WB) and os.path.exists(FEATURES)),
    reason="example evaluation or its features report is not present")


def _num(v):
    try:
        return float(str(v).strip())
    except (TypeError, ValueError):
        return None


@pytest.fixture(scope="module")
def resolved():
    inv = FeatureInventory.from_features_report(open(FEATURES).read())
    out = []
    for r in load_review_sheet(WB).rows:
        f = r.fields
        if str(f.get("on_road", "")).strip() != "SR 1003":
            continue
        coded, miles = _num(f.get("mp")), _num(f.get("miles"))
        frm = str(f.get("from_road") or "").strip()
        if coded is None or miles is None or not frm:
            continue
        rl = resolve(ReportLocation(
            on_road="SR 1003", from_road=frm,
            toward_road=str(f.get("toward_road") or "").strip(),
            dist_from_intersection=miles), inv, fiche_milepost=coded)
        if rl.milepost is not None:
            out.append(((r.status or "?").split("-")[0], rl.milepost, coded,
                        r.new_mp))
    return out


def test_resolver_reproduces_the_coded_milepost(resolved):
    assert len(resolved) > 1200, "most rows should resolve"
    diffs = [abs(mp - coded) for _s, mp, coded, _n in resolved]
    assert statistics.median(diffs) < 0.02
    within = sum(1 for d in diffs if d <= 0.06) / len(diffs)
    assert within > 0.95


def test_disagreement_does_not_indicate_an_RE(resolved):
    """TEAAS derives the coded milepost from the same fields, so the resolver
    reproduces it on RE rows too. RE has to come from the report."""
    re_rows = [(mp, coded) for s, mp, coded, _n in resolved if s == "RE"]
    others = [abs(mp - coded) for s, mp, coded, _n in resolved if s != "RE"]
    assert len(re_rows) > 50
    re_diffs = [abs(mp - coded) for mp, coded in re_rows]
    # RE rows are no further from the coded milepost than anything else
    assert statistics.median(re_diffs) <= statistics.median(others) + 0.01


def test_resolver_does_not_reproduce_the_engineers_correction(resolved):
    """The corrected milepost comes from the report, not from the fiche."""
    pairs = [(mp, new) for s, mp, _c, new in resolved
             if s == "RE" and new is not None]
    assert len(pairs) > 50
    hit = sum(1 for mp, new in pairs if abs(mp - new) <= 0.06) / len(pairs)
    assert hit < 0.25, "if this rises, the fiche gained an independent milepost"
