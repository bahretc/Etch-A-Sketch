"""The study criteria: one sheet per study type and analysis, grounded in
the docs pack and the worked study folders, rendered for the CLI, the
Overview page and docs/15."""
import datetime as dt
import pathlib
import re

import pytest

from safety_eval import criteria as cr
from safety_eval import study_type as st


def test_the_catalogue_covers_every_type_and_analysis_once():
    sheets = cr.all_criteria()
    keys = [(c.study_type, c.analysis, c.context) for c in sheets]
    assert keys == [
        ("hsip", "section", None), ("hsip", "intersection", "urban"),
        ("hsip", "intersection", "rural"), ("hsip", "bikeped", None),
        ("evaluation", "intersection", None), ("evaluation", "section", None),
        ("fatal", "section", None), ("fatal", "intersection", None)]
    assert len(set(keys)) == len(keys)


def test_period_lengths_follow_docs_12():
    """5 years for a fatal analysis and an HSIP section, 5 urban / 10 rural
    for an HSIP intersection, 10 for bike/ped; an evaluation's come from the
    assignment."""
    assert cr.period_years("fatal") == 5
    assert cr.period_years("fatal", "intersection") == 5
    assert cr.period_years("hsip", "section") == 5
    assert cr.period_years("hsip", "intersection", "urban") == 5
    assert cr.period_years("hsip", "intersection", "rural") == 10
    assert cr.period_years("hsip", "intersection") is None
    assert cr.period_years("hsip", "bikeped") == 10
    assert cr.period_years("evaluation") is None
    assert cr.period_years("evaluation", "section") is None


def test_the_analysis_period_is_anchored_on_the_month_end():
    """260722124BA: TEAAS data through August 2026 -> 9/1/2021 to 8/31/2026;
    41000079736's rural pull -> 9/1/2016; 260508015AA through June 2026 ->
    7/1/2021 to 6/30/2026. A mid-month currency date steps back to the
    previous complete month."""
    assert cr.analysis_period(dt.date(2026, 8, 31), 5) == (
        dt.date(2021, 9, 1), dt.date(2026, 8, 31))
    assert cr.analysis_period(dt.date(2026, 8, 31), 10) == (
        dt.date(2016, 9, 1), dt.date(2026, 8, 31))
    assert cr.analysis_period(dt.date(2026, 6, 30), 5) == (
        dt.date(2021, 7, 1), dt.date(2026, 6, 30))
    assert cr.analysis_period(dt.date(2026, 9, 15), 5) == (
        dt.date(2021, 9, 1), dt.date(2026, 8, 31))
    # a leap-day month end works too
    assert cr.analysis_period(dt.date(2028, 2, 29), 5) == (
        dt.date(2023, 3, 1), dt.date(2028, 2, 29))
    with pytest.raises(ValueError):
        cr.analysis_period(dt.date(2026, 8, 31), 0)


def test_the_y_line_and_statuses_follow_the_analysis_shape():
    sec = cr.for_study("fatal", "section")
    assert sec.yline_ft is None
    assert sec.review_statuses == ("IS", "RE", "ADD", "DEL", "NIS")
    junction = cr.for_study("evaluation", "intersection")
    assert junction.yline_ft == 150
    assert junction.review_statuses == ("IS", "ADD", "DEL", "NIS")
    assert cr.for_study("hsip", "bikeped").yline_ft == 300


def test_only_hsip_packages_carry_warrants_and_the_context_picks_the_set():
    assert cr.for_study("fatal").warrants == ()
    assert cr.for_study("evaluation").warrants == ()
    assert cr.for_study("hsip", "section").warrants == (
        "F-1", "F-2", "F-3", "F-4", "N-1", "N-2", "N-3", "N-4")
    urban = cr.for_study("hsip", "intersection", "urban")
    rural = cr.for_study("hsip", "intersection", "rural")
    assert urban.warrants == ("I-1u", "I-2u", "I-3u", "I-4u", "I-3")
    assert rural.warrants == ("I-1r", "I-2r", "I-3r", "I-4r", "I-3")
    assert urban.years == 5 and rural.years == 10
    # the sheet without a context still names every intersection warrant
    assert len(cr.for_study("hsip", "intersection").warrants) == 9


def test_a_context_belongs_to_an_hsip_intersection_only():
    with pytest.raises(ValueError, match="urban or rural"):
        cr.for_study("fatal", "section", "rural")
    with pytest.raises(ValueError, match="urban or rural"):
        cr.for_study("hsip", "intersection", "suburban")
    with pytest.raises(ValueError, match="not Bike/Ped"):
        cr.for_study("evaluation", "bikeped")
    assert cr.for_study("hsip", "intersection", " Rural ").context == "rural"


def test_the_rules_that_differ_between_the_study_types_are_stated():
    """The facts docs/12 and study_type hang off a type, in words, with a
    source on every rule."""
    def topics(c):
        return {x.topic: x for x in c.criteria}
    fatal = topics(cr.for_study("fatal"))
    hsip = topics(cr.for_study("hsip", "intersection", "rural"))
    ev = topics(cr.for_study("evaluation"))
    assert "flagged, not reviewed" in fatal["Crash scope"].rule
    assert "deleted (status DEL)" in hsip["Crash scope"].rule
    assert "animal crashes included" in ev["Crash scope"].rule
    assert fatal["Warrants"].rule.startswith("None")
    assert ev["Warrants"].rule.startswith("None")
    assert "10 years" in hsip["Analysis period"].rule
    assert "2024" in hsip["Intersection warrants"].rule
    assert "never 2020" in ev["AADT"].rule
    assert "Save As PDF" in ev["One pager"].rule
    for sheet in cr.all_criteria():
        for rule in sheet.criteria:
            assert rule.source, (sheet.title, rule.topic)
            assert rule.rule.endswith("."), (sheet.title, rule.topic)


def test_inputs_name_workspace_roles_and_required_ones_lead():
    from safety_eval.workspace import ROLES
    for sheet in cr.all_criteria():
        for inp in sheet.inputs:
            assert inp.role in ROLES, (sheet.title, inp.role)
            assert inp.label == ROLES[inp.role][0]
    fatal = cr.for_study("fatal")
    assert fatal.inputs[0].role == "fatal_slip" and fatal.inputs[0].required
    ev_sec = cr.for_study("evaluation", "section")
    assert {i.role for i in ev_sec.required_inputs()} >= {
        "before_ids", "after_ids", "before_mp", "after_mp"}
    assert "before_mp" not in {i.role for i in cr.for_study("evaluation").inputs}


def test_public_documents_are_marked_and_teaas_only_outputs_are_named():
    ev = cr.for_study("evaluation")
    assert [d.name for d in ev.deliverables if d.public] == [
        "One pager", "Complete Evaluation PDF and Web PDF"]
    for key in ("fatal", "hsip"):
        hows = [d.how for d in cr.for_study(key).deliverables]
        assert "TEAAS only" in hows, key


def test_check_params_says_in_words_what_the_study_still_owes():
    rural = cr.for_study("hsip", "intersection", "rural")
    assert cr.check_params(rural, {"center_lat": 35.2, "center_lon": -81.5}) == []
    nocontext = cr.for_study("hsip", "intersection")
    notes = cr.check_params(nocontext, {})
    assert any("urban or rural" in n for n in notes)
    assert any("coordinates" in n for n in notes)
    sec = cr.for_study("fatal", "section")
    assert any("mileposts" in n for n in cr.check_params(sec, {}))
    assert any("below the end" in n for n in
               cr.check_params(sec, {"mp_lo": 2.0, "mp_hi": 1.0}))
    ok = {"mp_lo": 0.025, "mp_hi": 0.205,
          "period_begin": "2021-09-01", "period_end": "2026-08-31"}
    assert cr.check_params(sec, ok) == []
    wrong = dict(ok, period_begin="2022-01-01")
    assert any("spans" in n for n in cr.check_params(sec, wrong))
    off_anchor = dict(ok, period_begin="2021-09-16", period_end="2026-09-15")
    assert any("month end" in n for n in cr.check_params(sec, off_anchor))
    assert any("5-year pull" in n for n in cr.check_params(sec, {"years": 10,
                                                                "mp_lo": 1, "mp_hi": 2}))
    assert any("y-line" in n for n in cr.check_params(
        cr.for_study("evaluation"), {"yline_ft": 350, "center_lat": 1, "center_lon": 2}))


def test_for_workspace_reads_type_analysis_and_context(tmp_path, monkeypatch):
    from safety_eval import workspace as wsm
    monkeypatch.setenv(wsm.ENV_BASE, str(tmp_path / "studies"))
    ws = wsm.Workspace.create("41000079736", study_type="hsip",
                              analysis="intersection")
    assert cr.for_workspace(ws).context is None
    ws.set_params(context="rural")
    c = cr.for_workspace(ws)
    assert (c.context, c.years) == ("rural", 10)
    # a context recorded on a study that has none is ignored, not an error
    ws2 = wsm.Workspace.create("260722124BA", study_type="fatal",
                               analysis="section")
    ws2.set_params(context="rural")
    assert cr.for_workspace(ws2).context is None


def test_rendering_is_plain_style_and_round_trips_to_dict():
    text = cr.markdown_catalogue()
    assert "—" not in text and "–" not in text   # docs/05
    assert text.count("\n## ") == 8
    for sheet in cr.all_criteria():
        d = cr.to_dict(sheet)
        assert d["title"] == sheet.title
        assert d["inputs"][0]["label"] == sheet.inputs[0].label
        md = cr.to_markdown(sheet)
        assert md.startswith(f"# {sheet.title}\n")
        assert "| Topic | Rule | Source | Applied by |" in md


def test_docs_15_is_the_rendered_catalogue():
    """docs/15 is generated; regenerating it must change nothing."""
    doc = pathlib.Path(__file__).resolve().parent.parent / "docs" / "15-study-criteria.md"
    assert doc.exists(), "run: safety-eval criteria --all --out docs/15-study-criteria.md"
    assert doc.read_text(encoding="utf-8") == cr.markdown_catalogue()


def test_the_cli_prints_a_sheet_and_checks_a_study(tmp_path, monkeypatch, capsys):
    from safety_eval import workspace as wsm
    from safety_eval.cli import main
    assert main(["criteria", "--type", "hsip", "--analysis", "intersection",
                 "--context", "rural"]) == 0
    out = capsys.readouterr().out
    assert out.startswith("# HSIP Package Analysis, intersection (rural)")
    assert "I-1r" in out and "10 years" in out
    assert main(["criteria", "--type", "fatal", "--json"]) == 0
    import json
    d = json.loads(capsys.readouterr().out)
    assert d["years"] == 5 and d["study_type"] == "fatal"
    monkeypatch.setenv(wsm.ENV_BASE, str(tmp_path / "studies"))
    wsm.Workspace.create("41000079736", study_type="hsip", analysis="intersection")
    assert main(["criteria", "--study", "41000079736"]) == 1
    out = capsys.readouterr().out
    assert "Still owed" in out and "urban or rural" in out
    out_file = tmp_path / "all.md"
    assert main(["criteria", "--all", "--out", str(out_file)]) == 0
    assert out_file.read_text(encoding="utf-8") == cr.markdown_catalogue()
