"""The Streamlit shell, driven headlessly (streamlit.testing.v1.AppTest).

These are behaviour tests for the UI wiring: every study type renders
without an exception, the tabs a study type cannot use are not shown, and
the widgets each flow depends on exist. Upload-driven runs are exercised at
the library level (test_hsip.py, test_fiche_workbook.py); AppTest cannot
fill a file_uploader.
"""
import pathlib

import pytest

st = pytest.importorskip("streamlit")
from streamlit.testing.v1 import AppTest  # noqa: E402

#: The launcher is the supported entry point (package-relative app code
#: cannot run as a bare script), so it is also what the tests execute.
_LAUNCHER = str(pathlib.Path(__file__).resolve().parent.parent
                / "streamlit_app.py")


def _app(study_type=None):
    at = AppTest.from_file(_LAUNCHER)
    at.run(timeout=30)
    if study_type:
        at.sidebar.selectbox[0].set_value(study_type)
        at.run(timeout=30)
    assert not at.exception, at.exception
    return at


def _tab_labels(at):
    return [t.label for t in at.tabs]


def test_the_default_study_type_is_hsip_and_shows_the_warrant_tab():
    at = _app()
    labels = _tab_labels(at)
    assert labels[0] == "Fiche Workbook"
    assert "HSIP Warrants" in labels
    assert "Evaluation Workbook" not in labels


def test_an_evaluation_gets_the_workbook_tab_and_no_warrants():
    """docs/12: an Evaluation must never see a warrant screen."""
    at = _app("evaluation")
    labels = _tab_labels(at)
    assert "Evaluation Workbook" in labels
    assert "HSIP Warrants" not in labels


def test_a_fatal_analysis_gets_only_the_shared_core():
    at = _app("fatal")
    labels = _tab_labels(at)
    assert labels == ["Fiche Workbook", "Redact Crash Reports",
                      "Review Queue"]


def test_every_study_type_renders_without_an_exception():
    for key in ("hsip", "evaluation", "fatal"):
        _app(key)


def test_the_hsip_tab_offers_section_and_intersection():
    at = _app("hsip")
    radios = {r.label: r for r in at.radio}
    assert "Analysis" in radios
    assert radios["Analysis"].options == ["Section (strip)", "Intersection"]
    # The section form is the default: facility + limits present.
    assert any(s.label == "Facility" for s in at.selectbox)
    # Switching to intersection swaps in the context radio.
    radios["Analysis"].set_value("Intersection")
    at.run(timeout=30)
    assert not at.exception
    labels = {r.label for r in at.radio}
    assert "Context" in labels


def test_the_fiche_tab_asks_for_the_four_exports_and_the_screen_inputs():
    at = _app("hsip")
    inputs = {t.label for t in at.text_input}
    assert "Study number" in inputs and "Study route" in inputs
    numbers = {n.label for n in at.number_input}
    assert {"MP begin", "MP end"} <= numbers


def test_the_animal_rule_is_stated_for_hsip_only():
    """The sidebar states the study-type behaviour in words, not colour."""
    at = _app("hsip")
    texts = " ".join(getattr(el, "value", "") or "" for el in at.sidebar.info)
    assert "animal crashes become DEL" in texts
    at = _app("evaluation")
    assert not [el for el in at.sidebar.info
                if "animal" in (getattr(el, "value", "") or "")]
