"""Offline tests for the LLM review-assist (no live API; injected fake client)."""
import json
import types

import pytest

from safety_eval.review_queue import ReviewRow
from safety_eval import review_assist as ra
from safety_eval.review_assist import StudyContext, assist, _decide_schema

Image = pytest.importorskip("PIL.Image")

CTX = StudyContext(name="NC 42 at SR 1007", analysis_type="intersection",
                   buffer_ft=150, study_point=(35.6042, -79.1071), prescreen_ft=41)
ROW = ReviewRow(crash_id="106421887", row=5,
                fields={"t": 2, "crash_type": "Angle", "mp": 8.10, "on_road": "NC 42"})
ANIMAL = ReviewRow(crash_id="106547120", row=9, fields={"t": 17, "crash_type": "Animal"})


def _pages():
    return [Image.new("RGB", (40, 60), "white")]


class FakeClient:
    """Stands in for anthropic.Anthropic(); records the request, returns text."""
    def __init__(self, text, stop=None):
        self._text, self._stop, self.calls, self.kw = text, stop, 0, None
        self.messages = self

    def create(self, **kw):
        self.calls += 1
        self.kw = kw
        blk = types.SimpleNamespace(type="text", text=self._text)
        return types.SimpleNamespace(content=[blk], stop_reason=self._stop)


class RaiseClient:
    def __init__(self):
        self.messages = self

    def create(self, **kw):
        raise AssertionError("the API must not be called on this path")


def test_animal_short_circuits_without_api():
    r = assist(ANIMAL, CTX, _pages(), mode="decide", client=RaiseClient(), redacted=True)
    assert r.flags == ["animal-skip"]
    assert r.proposed_status is None and not r.needs_manual


def test_missing_report_needs_manual_without_api():
    r = assist(ROW, CTX, [], mode="prepare", client=RaiseClient(), redacted=True)
    assert r.needs_manual and "no-report" in r.flags


def test_refuses_unredacted_pages():
    with pytest.raises(ValueError):
        assist(ROW, CTX, _pages(), mode="decide", client=RaiseClient(), redacted=False)


def test_bad_mode_rejected():
    with pytest.raises(ValueError):
        assist(ROW, CTX, [], mode="guess", client=RaiseClient(), redacted=True)


def test_decide_schema_vocab_by_analysis_type():
    assert _decide_schema("intersection")["properties"]["proposed_status"]["enum"] == \
        ["IS", "ADD", "DEL", "NIS"]
    assert "RE" in _decide_schema("section")["properties"]["proposed_status"]["enum"]


def test_decide_happy_path_and_request_shape():
    text = json.dumps({
        "where_occurred": "the study intersection", "at_study_location": True,
        "proposed_status": "IS", "new_mp": None, "comment": "per coords",
        "confidence": "high",
        "evidence": ["diagram shows NB NC 42 struck by EB SR 1007 in the box"]})
    fc = FakeClient(text)
    r = assist(ROW, CTX, _pages(), mode="decide", client=fc, redacted=True)
    assert fc.calls == 1
    assert r.proposed_status == "IS" and not r.validation_problems and not r.needs_manual
    det = r.as_determination()
    assert det is not None and det.status == "IS" and det.comment == "per coords"
    content = fc.kw["messages"][0]["content"]
    assert any(b.get("type") == "image" for b in content)   # redacted image sent
    assert fc.kw["output_config"]["format"]["schema"]["properties"][
        "proposed_status"]["enum"] == ["IS", "ADD", "DEL", "NIS"]


def test_decide_invalid_status_is_flagged():
    # RE in an intersection analysis is a docs/03 data error
    text = json.dumps({
        "where_occurred": "x", "at_study_location": True, "proposed_status": "RE",
        "comment": "c", "confidence": "high", "evidence": ["e"]})
    r = assist(ROW, CTX, _pages(), mode="decide", client=FakeClient(text), redacted=True)
    assert r.validation_problems and r.needs_manual


def test_low_confidence_forces_manual():
    text = json.dumps({
        "where_occurred": "unclear", "at_study_location": False,
        "proposed_status": "NIS", "comment": "diagram illegible", "confidence": "low",
        "evidence": ["blurred diagram"]})
    r = assist(ROW, CTX, _pages(), mode="decide", client=FakeClient(text), redacted=True)
    assert r.needs_manual


def test_prepare_makes_no_call_on_status():
    text = json.dumps({
        "diagram_summary": "NB vs EB in the intersection box",
        "narrative_summary": "failure to yield at the stop",
        "report_location": "NC 42 / SR 1007 per front-page coords",
        "distance_assessment": "~40 ft from centre, inside the 150 ft buffer",
        "applicable_rule": "Intersection 150 ft rule (docs/03)",
        "draft_comment": "per coords", "candidate_statuses": ["IS", "ADD"],
        "flags": []})
    r = assist(ROW, CTX, _pages(), mode="prepare", client=FakeClient(text), redacted=True)
    assert r.proposed_status is None
    assert r.diagram_summary and r.candidate_statuses == ["IS", "ADD"]
    assert r.comment == "per coords"


def test_refusal_needs_manual():
    r = assist(ROW, CTX, _pages(), mode="decide",
               client=FakeClient("", stop="refusal"), redacted=True)
    assert r.needs_manual and "refusal" in r.flags


def test_new_mp_is_dropped_on_a_non_RE_status():
    """New MP is the RE field; a milepost must not ride along on an IS row."""
    text = json.dumps({
        "where_occurred": "US 13 MP 8.10", "at_study_location": True,
        "proposed_status": "IS", "new_mp": 8.1, "comment": "within the section",
        "confidence": "high", "evidence": ["resolved from the features report"]})
    ctx = StudyContext(analysis_type="section")
    r = assist(ROW, ctx, _pages(), mode="decide",
               client=FakeClient(text), redacted=True)
    assert r.proposed_status == "IS" and r.new_mp is None
    assert any("New MP" in f for f in r.flags)
    assert r.as_determination().new_mp is None


def test_new_mp_is_kept_on_RE():
    text = json.dumps({
        "where_occurred": "US 13 MP 8.10", "at_study_location": True,
        "proposed_status": "RE", "new_mp": 8.1,
        "comment": "remileposted from the features report",
        "confidence": "high", "evidence": ["MP(SR 1132) + 0.80"]})
    ctx = StudyContext(analysis_type="section")
    r = assist(ROW, ctx, _pages(), mode="decide",
               client=FakeClient(text), redacted=True)
    assert r.proposed_status == "RE" and r.new_mp == 8.1
    assert not r.validation_problems
