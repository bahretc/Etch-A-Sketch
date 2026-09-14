"""Tests for the safety-evaluation pipeline."""
import os
from datetime import date

import pytest

from safety_eval.analysis import crash_rate, epdo, evaluate, severity_index
from safety_eval.assignment import load_assignment
from safety_eval.classify import classify_all
from safety_eval.config import Config
from safety_eval.fiche_parser import parse_csv, parse_fiche, parse_teaas_text
from safety_eval.models import Assignment
from safety_eval.periods import build_periods
from safety_eval.pipeline import run

HERE = os.path.dirname(__file__)
EX = os.path.join(HERE, "..", "examples")
FICHE = os.path.join(EX, "example_fiche.csv")
ASSIGN = os.path.join(EX, "example_assignment.yaml")


@pytest.fixture
def cfg():
    return Config.load()


@pytest.fixture
def assignment():
    return load_assignment(ASSIGN)


# --- parsing ---------------------------------------------------------------
def test_parse_csv_counts():
    with open(FICHE) as fh:
        crashes = parse_csv(fh.read())
    assert len(crashes) == 12
    c0 = crashes[0]
    assert c0.crash_id == "105868662"
    assert c0.date == date(2019, 5, 19)
    assert c0.mp == 0.006
    assert c0.t == 2 and c0.s == "C"


def test_parse_auto_detects_csv():
    assert len(parse_fiche(FICHE)) == 12


def test_parse_teaas_text_positional():
    text = (
        "Muni. Code | On Road | Miles | Dir From | From Road | Toward Road | "
        "Milepost Road | MP | MA | Crash ID | Date | T | C | F | L | S\n"
        "601 | CAROLINA BEACH | 0.006 | W | A | B | CAROLINA BEACH | 0.006 |  | "
        "105868662 | 5/19/2019 | 2 | 1 | 2 | 4 | C\n"
        "3/17/2020 | Page 2 of 16\n"
    )
    crashes = parse_teaas_text(text)
    assert len(crashes) == 1
    assert crashes[0].crash_id == "105868662"


# --- periods ---------------------------------------------------------------
def test_build_periods(assignment, cfg):
    periods = build_periods(assignment, cfg)
    assert periods["before"].start == date(2016, 10, 1)
    assert periods["before"].end == date(2021, 3, 31)
    assert periods["construction"].start == date(2021, 4, 1)
    assert periods["construction"].end == date(2021, 10, 31)
    assert periods["after"].start == date(2021, 11, 1)
    assert periods["after"].end == date(2026, 4, 30)


def test_periods_require_dates(cfg):
    with pytest.raises(ValueError):
        build_periods(Assignment(), cfg)


# --- classification --------------------------------------------------------
def test_in_study_filters_by_mp_and_period(assignment, cfg):
    crashes = parse_fiche(FICHE)
    periods = build_periods(assignment, cfg)
    classify_all(crashes, assignment, periods, cfg)
    by_id = {c.crash_id: c for c in crashes}
    # off-section road at MP 5.0 -> out of study
    assert by_id["105999999"].in_study is False
    # in-section crash before construction -> 'before'
    assert by_id["105868662"].in_study is True
    assert by_id["105868662"].period == "before"
    # after-construction crash
    assert by_id["107054917"].period == "after"


def test_target_classification(assignment, cfg):
    crashes = parse_fiche(FICHE)
    periods = build_periods(assignment, cfg)
    classify_all(crashes, assignment, periods, cfg)
    by_id = {c.crash_id: c for c in crashes}
    # T=2 (ROR-L, docs/09), wet road code 2, night light 4 -> LD Type2 + Wet + Night
    ld = by_id["105868662"]
    assert "Lane Departure (Type 2)" in ld.target_types
    assert "Wet" in ld.target_types
    assert "Night" in ld.target_types
    # T=30 (angle, docs/09), dry, day -> none of the selected LD/wet/night targets
    assert by_id["107026892"].target_types == []


# --- analysis --------------------------------------------------------------
def test_evaluate_before_after(assignment, cfg):
    result = run(FICHE, assignment, cfg)
    b = result.stats["before"]
    a = result.stats["after"]
    assert b.total >= 1 and a.total >= 1
    ba = result.before_after
    assert "reduction_pct" in ba["total"]
    # expected_after uses time & AADT adjustment
    factor = ba["total"]["adjustment_factor"]
    assert factor > 0


def test_crash_rate_segment():
    r = crash_rate(total=10, years=5, aadt=8000, length_mi=0.1, intersection=False)
    assert r is not None and r > 0


def test_crash_rate_needs_aadt():
    assert crash_rate(10, 5, None, 0.1, False) is None


# --- known-value methodology tests (docs/04) -------------------------------
def test_epdo_weights_are_ncdot(cfg):
    # docs/04 hard rule: K/A = 76.8, B/C = 8.4, PDO = 1.0
    assert cfg.epdo_weight("K") == 76.8
    assert cfg.epdo_weight("A") == 76.8
    assert cfg.epdo_weight("B") == 8.4
    assert cfg.epdo_weight("C") == 8.4
    assert cfg.epdo_weight("O") == 1.0


def test_epdo_known_value_372_2(cfg):
    # docs/04 reference target EPDO = 372.2 (TEAAS Ch. 15 example).
    # 76.8*(K+A) + 8.4*(B+C) + 1.0*PDO with K+A=4, B+C=5, PDO=23 -> 372.2
    counts = {"K": 1, "A": 3, "B": 2, "C": 3, "O": 23}
    assert round(epdo(counts, cfg), 1) == 372.2


def test_severity_index(cfg):
    counts = {"K": 1, "A": 3, "B": 2, "C": 3, "O": 23}
    assert round(severity_index(counts, cfg), 4) == round(372.2 / 32, 4)


def test_frontal_impact_set(cfg):
    # docs/08, docs/09: LTSR, LTDR, RTSR, RTDR, head-on, angle
    assert cfg.crash_type_group("frontal_impact") == {23, 24, 25, 26, 27, 30}


def test_no_em_dash_in_report(assignment, cfg):
    from safety_eval.report import render_markdown
    md = render_markdown(run(FICHE, assignment, cfg), cfg)
    assert "—" not in md  # em dash
    assert "–" not in md  # en dash


def test_severity_and_injury_counts(assignment, cfg):
    result = run(FICHE, assignment, cfg)
    total_k = sum(s.fatalities for s in result.stats.values())
    assert total_k >= 1  # one K crash in the sample (in construction period)


# --- config ----------------------------------------------------------------
def test_config_roles_default():
    cfg = Config.load()
    assert cfg.role_letter("crash_type") == "T"
    assert cfg.role_letter("severity") == "S"
    assert "K" in cfg.severity_order


def test_config_override(tmp_path):
    override = tmp_path / "ov.yaml"
    override.write_text("column_roles:\n  crash_type: C\n")
    cfg = Config.load(str(override))
    assert cfg.role_letter("crash_type") == "C"
    # untouched keys still present
    assert cfg.role_letter("severity") == "S"
