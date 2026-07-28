"""Regression tests for PII that survived redaction on a real DMV-349.

Found 2026-07 on an actual report: the persons table ("Names and Addresses
for All Persons") kept every name and street address in the clear because the
caption is PLURAL and the label rules only matched the singular. These tests
use synthetic word boxes; no real report content is used.
"""
from safety_eval.redact import (Word, _is_persons_header, _label_key,
                                plan_redactions, residual_pii,
                                verify_redaction, RedactionIncomplete)


def _line(texts, top, page=1):
    """Build a row of Words at one vertical position."""
    out, x = [], 10
    for t in texts:
        out.append(Word(text=t, left=x, top=top, width=12 * len(t), height=12,
                        page=page))
        x += 12 * len(t) + 8
    return out


def test_plural_captions_match_singular_labels():
    assert _label_key("Names") == "name"
    assert _label_key("Addresses") == "address"
    assert _label_key("Name") == "name"


def test_persons_header_detected():
    assert _is_persons_header(["names", "and", "addresses", "for", "all",
                               "persons"])
    assert not _is_persons_header(["vehicle", "make", "year"])


def test_persons_table_rows_are_redacted():
    """The regression: rows several lines below the caption must be covered."""
    words = []
    words += _line(["Names", "and", "Addresses", "for", "All", "Persons"], 100)
    words += _line(["A", "1", "1", "NOT", "TOWED"], 130)
    words += _line(["C", "1", "2", "JANE", "DOE", "12", "MAPLE", "ST"], 160)
    words += _line(["D", "1", "3", "JOHN", "ROE", "9", "OAK", "RD"], 190)
    reds = plan_redactions(words, keep_zip=True)
    reasons = {r.reason for r in reds}
    assert "persons-table" in reasons
    covered_tops = {(r.top, r.bottom) for r in reds
                    if r.reason == "persons-table"}
    # the two name/address rows are inside redacted bands
    for top in (160, 190):
        assert any(t <= top <= b for t, b in covered_tops), f"row {top} leaked"


def test_verifier_flags_surviving_street_address(tmp_path):
    """residual_pii works off OCR of the OUTPUT; here we exercise the rule
    directly through plan-free detection by feeding a synthetic 'redacted'
    page whose address survived."""
    from safety_eval.redact import _residual_groups
    words = _line(["1074", "MOUNT", "CARMEL", "RD"], 50)
    found = list(_residual_groups(words, keep_zip=True))
    assert found and "street-address" in found[0][1]


def test_verify_redaction_raises_message_has_no_pii():
    from safety_eval.redact import _residual_groups
    words = _line(["55", "ELM", "ST"], 40)
    groups = list(_residual_groups(words, keep_zip=True))
    assert groups
    # the finding records a reason, never the text
    reason = groups[0][1]
    assert "ELM" not in reason and "55" not in reason
