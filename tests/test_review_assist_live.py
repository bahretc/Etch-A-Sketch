"""Live API-shape check for the review assist. Skipped unless a key is set.

The offline suite (tests/test_review_assist.py) injects a fake client, so it
proves the parsing and the docs/03 guards but says nothing about whether the
Messages API still accepts the request we build.  A structured-output or vision
parameter can be renamed upstream and every offline test stays green.

This test sends ONE request built by ``build_request`` and checks it is
accepted and comes back conforming to the schema.  No crash-report imagery is
used: the page is a blank synthetic image, so nothing sensitive leaves the
machine and the determination itself is meaningless (a blank page should come
back low-confidence and needs_manual, which is asserted).

Run with:  ANTHROPIC_API_KEY=... pytest tests/test_review_assist_live.py
"""
import os

import pytest

from safety_eval.review_assist import (DEFAULT_MAX_TOKENS, DEFAULT_MODEL,
                                       StudyContext, assist, build_request)
from safety_eval.review_queue import ReviewRow

pytestmark = pytest.mark.skipif(not os.environ.get("ANTHROPIC_API_KEY"),
                                reason="no ANTHROPIC_API_KEY; live check skipped")

Image = pytest.importorskip("PIL.Image")

ROW = ReviewRow(crash_id="105451449", row=5,
                fields={"t": 2, "crash_type": "Rear End", "mp": 17.7,
                        "on_road": "SR 1003"})
CTX = StudyContext(name="SR 1003 from SR 1716 to SR 2638",
                   analysis_type="section", buffer_ft=150, fiche_milepost=17.7)


def _blank_page():
    return [Image.new("RGB", (850, 1100), "white")]


def test_request_shape_is_what_the_api_expects():
    """Pins the structured-output shape: output_config.format json_schema."""
    p = build_request(ROW, CTX, _blank_page(), "decide")
    fmt = p["output_config"]["format"]
    assert fmt["type"] == "json_schema"
    # strict mode requires both, or the API rejects the schema
    assert fmt["schema"]["additionalProperties"] is False
    assert fmt["schema"]["required"]
    assert [b["type"] for b in p["messages"][0]["content"]] == ["text", "image"]


def test_live_decide_call_is_accepted_and_conforms():
    anthropic = pytest.importorskip("anthropic")

    r = assist(ROW, CTX, _blank_page(), mode="decide",
               client=anthropic.Anthropic(), redacted=True)
    assert not r.validation_problems, r.validation_problems
    assert r.proposed_status in ("IS", "RE", "ADD", "DEL", "NIS")
    assert r.confidence in ("low", "medium", "high")
    # a blank page resolves nothing, so the guards must catch it
    assert r.needs_manual


def test_live_call_leaves_token_headroom():
    """max_tokens must cover thinking plus the answer, not just the answer."""
    anthropic = pytest.importorskip("anthropic")

    p = build_request(ROW, CTX, _blank_page(), "decide")
    resp = anthropic.Anthropic().messages.create(**p)
    assert resp.stop_reason != "max_tokens", (
        f"truncated at {p['max_tokens']} tokens; raise DEFAULT_MAX_TOKENS")
    assert resp.usage.output_tokens < DEFAULT_MAX_TOKENS * 0.5, (
        f"{resp.usage.output_tokens} of {DEFAULT_MAX_TOKENS} used on a BLANK "
        f"page; a real report has far more to read")


def test_default_model_is_a_current_id():
    """Guards against a stale or invented model string."""
    assert DEFAULT_MODEL in ("claude-opus-5", "claude-opus-4-8",
                             "claude-sonnet-5")
