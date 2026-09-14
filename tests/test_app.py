"""Streamlit app renders every page headlessly (streamlit.testing)."""
import os

import pytest

st_testing = pytest.importorskip("streamlit.testing.v1")


@pytest.fixture
def app(monkeypatch):
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
    monkeypatch.delenv("ANTHROPIC_AUTH_TOKEN", raising=False)
    script = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "safety_eval", "app.py")
    at = st_testing.AppTest.from_file(script, default_timeout=120)
    at.run()
    return at


def test_all_tabs_render(app):
    assert not app.exception
    assert app.title[0].value == "NCDOT HSIP Safety Evaluations"
    labels = [t.label for t in app.tabs]
    assert labels == ["Home", "Build Evaluation", "AADT and Set-up", "Map Block", "Collision Diagram",
                      "Print and Assemble", "QA Checks", "Redact Crash Reports", "Review Filtered Fiche",
                      "Finish Package", "Assistant"]


def test_assistant_explains_missing_key(app):
    infos = [i.value for i in app.info]
    assert any("ANTHROPIC_API_KEY" in v for v in infos)


def test_aadt_page_builds_table_from_manual_values(app):
    app.text_input(key="man_leg1").set_value("2017:4100,2019:4500,2021:3500")
    app.text_input(key="man_leg2").set_value("2016:2200,2018:3100,2022:2100,2024:3200,2025:3200")
    app.text_input(key="man_leg4").set_value("2016:1600,2022:1200,2024:1900,2025:1900")
    app.selectbox(key="as_leg3").set_value("leg4")
    app.run()
    assert not app.exception
    codes = [c.value for c in app.code]
    assert any("4100 black" in c for c in codes)
    writes = [m.value for m in app.markdown] + [t.value for t in app.text]
    assert any("prints 5,300" in v for v in writes) or any("5,300" in v for v in writes)


def test_print_page_reports_toolchain(app):
    assert app.selectbox(key="pr_sheet").value == "1 page results - 1 Target"
