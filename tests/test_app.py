"""The Streamlit shell, driven headlessly (streamlit.testing.v1.AppTest).

These are behaviour tests for the UI wiring: every study type renders
without an exception, the pages a study type cannot use are not offered in
the navigation, and the widgets each flow depends on exist. The app is a
st.navigation over the page shims in safety_eval/ui_pages/, so a test lands
on a page with ``switch_page`` on the shim's path. Upload-driven runs are
exercised at the library level (test_hsip.py, test_fiche_workbook.py);
AppTest cannot fill a file_uploader.
"""
import pathlib

import pytest

st = pytest.importorskip("streamlit")
from streamlit.testing.v1 import AppTest  # noqa: E402

from safety_eval.app import PAGE  # noqa: E402

#: The launcher is the supported entry point (package-relative app code
#: cannot run as a bare script), so it is also what the tests execute.
_LAUNCHER = str(pathlib.Path(__file__).resolve().parent.parent
                / "streamlit_app.py")


def _app(study_type=None, page=None):
    at = AppTest.from_file(_LAUNCHER)
    at.run(timeout=30)
    if study_type:
        at.sidebar.selectbox[0].set_value(study_type)
        at.run(timeout=30)
    if page:
        at.switch_page(PAGE[page])
        at.run(timeout=30)
    assert not at.exception, at.exception
    return at


def _nav_titles(at):
    return list(at.session_state["nav_titles"])


def test_the_default_study_type_is_hsip_and_offers_the_warrant_page():
    at = _app()
    titles = _nav_titles(at)
    assert titles[0] == "Overview"
    assert "Fiche Workbook" in titles
    assert "HSIP Warrants" in titles
    assert "Evaluation Workbook" not in titles


def test_an_evaluation_gets_the_deliverable_pages_and_no_warrants():
    """docs/12: an Evaluation must never see a warrant screen."""
    at = _app("evaluation")
    titles = _nav_titles(at)
    assert "Evaluation Workbook" in titles
    assert "Assumptions Email" in titles
    assert "HSIP Warrants" not in titles


def test_a_fatal_analysis_gets_only_the_shared_core():
    at = _app("fatal")
    assert _nav_titles(at) == ["Overview", "Fiche Workbook",
                               "Redact Crash Reports", "Review Queue"]


def test_every_study_type_renders_every_offered_page():
    pages_for = {"hsip": ["home", "fiche", "redact", "review", "warrants"],
                 "evaluation": ["home", "fiche", "redact", "review",
                                "evaluation", "assumptions"],
                 "fatal": ["home", "fiche", "redact", "review"]}
    for key, pages in pages_for.items():
        for page in pages:
            _app(key, page=page)


def test_the_home_page_walks_the_workflow_in_order():
    """The Overview page links the steps in workflow order, in words."""
    at = _app("evaluation", page="home")
    labels = [ln.label for ln in at.get("page_link")]
    assert any("fiche workbook" in lb.lower() for lb in labels)
    assert labels == sorted(labels, key=lambda lb: int(lb.split(".")[0]))
    assert any("assumptions email" in lb.lower() for lb in labels)


def test_the_warrants_page_offers_section_and_intersection():
    at = _app("hsip", page="warrants")
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


def test_the_fiche_page_asks_for_the_four_exports_and_the_screen_inputs():
    at = _app("hsip", page="fiche")
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


def test_the_review_page_carries_the_branch_and_sheet_inputs():
    """The fiche review needs Initial Study membership (branch narrowing,
    docs/03) and finds the working sheet by name when left blank."""
    at = _app("hsip", page="review")
    labels = {t.label for t in at.text_input}
    assert "TEAAS ID export (.txt path, recommended)" in labels
    assert "Review sheet name" in labels


def test_the_review_page_says_when_the_assist_is_not_ready(monkeypatch):
    """A missing key must read as a sentence in the settings, never a
    traceback (the assist is optional; the queue works without it)."""
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
    at = _app("hsip", page="review")
    captions = " ".join(getattr(el, "value", "") or "" for el in at.caption)
    assert "AI assist not ready" in captions
    assert "ANTHROPIC_API_KEY" in captions


# --------------------------------------------------------------------------- #
# the study workspace in the app (sidebar create/open, page defaults)
# --------------------------------------------------------------------------- #
def test_the_sidebar_offers_a_study_selector_defaulting_to_none(tmp_path,
                                                                monkeypatch):
    from safety_eval import workspace as wsm
    monkeypatch.setenv(wsm.ENV_BASE, str(tmp_path / "studies"))
    at = _app()
    picks = [s for s in at.sidebar.selectbox if s.label == "Study"]
    assert picks and picks[0].value == "(no study)"


def test_creating_a_study_in_the_sidebar_opens_it(tmp_path, monkeypatch):
    from safety_eval import workspace as wsm
    monkeypatch.setenv(wsm.ENV_BASE, str(tmp_path / "studies"))
    at = _app()
    at.sidebar.text_input(key="new_study").set_value("41000079305")
    next(b for b in at.sidebar.button
         if b.label == "Create study").click()
    at.run(timeout=30)
    assert not at.exception, at.exception
    pick = next(s for s in at.sidebar.selectbox if s.label == "Study")
    assert pick.value == "41000079305"
    assert wsm.list_studies() == ["41000079305"]
    # the study type chosen in the sidebar is recorded on the manifest
    assert wsm.Workspace.open("41000079305").study_type == "hsip"


def test_pages_default_from_the_open_study(tmp_path, monkeypatch):
    from safety_eval import workspace as wsm
    monkeypatch.setenv(wsm.ENV_BASE, str(tmp_path / "studies"))
    ws = wsm.Workspace.create("41000079305", study_type="hsip")
    import openpyxl
    wb_path = tmp_path / "41000079305_Fiche.xlsx"
    wbx = openpyxl.Workbook()
    wbx.active.title = "41000079305_Fiche"
    wbx.save(wb_path)
    ws.adopt_output("workbook", str(wb_path))
    ws.attach("initial_ids_txt", "ids.txt", b"1|2")
    ws.set_params(route="US 74", mp_lo=13.56, mp_hi=13.815)

    at = _app()
    pick = next(s for s in at.sidebar.selectbox if s.label == "Study")
    pick.set_value("41000079305")
    at.run(timeout=30)

    at.switch_page(PAGE["fiche"])
    at.run(timeout=30)
    assert not at.exception, at.exception
    assert next(t for t in at.text_input
                if t.label == "Study number").value == "41000079305"
    assert next(t for t in at.text_input
                if t.label == "Study route").value == "US 74"

    at.switch_page(PAGE["review"])
    at.run(timeout=30)
    assert not at.exception, at.exception
    values = {t.label: t.value for t in at.text_input}
    assert values["Workbook (.xlsx path)"].endswith("41000079305_Fiche.xlsx")
    assert values["TEAAS ID export (.txt path, recommended)"].endswith(
        "ids.txt")
    assert values["Study milepost range lo:hi (optional)"] == "13.56:13.815"

    at.switch_page(PAGE["warrants"])
    at.run(timeout=30)
    assert not at.exception, at.exception
    wb_radio = next(r for r in at.radio if r.label == "Workbook")
    assert "From study 41000079305" in wb_radio.options[0]
