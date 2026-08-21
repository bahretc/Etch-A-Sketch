"""PII redaction tests: planner logic (synthetic word boxes) plus a true
end-to-end proof: render a synthetic DMV-349-style page, redact it, re-OCR it,
and assert the PII is unreadable while ZIP codes and crash IDs survive."""
import os
import shutil
import subprocess

import pytest

from safety_eval.redact import (Redaction, Word, plan_redactions, redact_file)

HAVE_TESSERACT = shutil.which("tesseract") is not None
needs_ocr = pytest.mark.skipif(not HAVE_TESSERACT, reason="tesseract not installed")

_FONTS = [
    "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf",
    "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf",
]


def W(text, left, top, w=60, h=20, page=0, line=(0, 0, 0)):
    return Word(text=text, left=left, top=top, width=w, height=h,
                page=page, line_id=line)


# --- planner ---------------------------------------------------------------
def test_label_same_line_redacts_value_not_label():
    words = [W("Name:", 10, 10, line=(0, 0, 1)),
             W("John", 90, 10, line=(0, 0, 1)),
             W("Smith", 160, 10, line=(0, 0, 1))]
    boxes = plan_redactions(words)
    assert len(boxes) == 1
    b = boxes[0]
    assert b.left >= 80            # label itself stays visible
    assert b.reason == "label:name"


def test_caption_above_value_redacts_next_line():
    words = [W("Address", 10, 10, line=(0, 0, 1)),
             W("123", 10, 40, line=(0, 0, 2)),
             W("Main", 60, 40, line=(0, 0, 2)),
             W("St", 120, 40, line=(0, 0, 2))]
    boxes = plan_redactions(words)
    assert any(b.reason.startswith("label:address") for b in boxes)
    covered = [b for b in boxes if b.top >= 30]
    assert covered, "value line under the caption must be covered"


def test_zip_is_preserved_by_default():
    words = [W("Address:", 10, 10, line=(0, 0, 1)),
             W("123", 100, 10, line=(0, 0, 1)),
             W("Main", 160, 10, line=(0, 0, 1)),
             W("St", 230, 10, line=(0, 0, 1)),
             W("27591", 300, 10, line=(0, 0, 1)),
             W("more", 380, 10, line=(0, 0, 1))]
    boxes = plan_redactions(words, keep_zip=True)
    # the zip splits the redaction; no box may cover x range of the zip word
    for b in boxes:
        assert not (b.left <= 310 and b.right >= 350), "zip must stay visible"
    # but the street part is covered
    assert any(b.left <= 105 and b.right >= 240 for b in boxes)


def test_zip_redacted_when_disabled():
    words = [W("Address:", 10, 10, line=(0, 0, 1)),
             W("27591", 100, 10, line=(0, 0, 1))]
    boxes = plan_redactions(words, keep_zip=False)
    assert any(b.left <= 100 and b.right >= 160 for b in boxes)


def test_street_address_without_label():
    """Inside the occupants' block, an uncaptioned address is still covered."""
    words = [W("4407", 10, 10, line=(0, 0, 1)),
             W("Buffalo", 80, 10, line=(0, 0, 1)),
             W("Rd", 160, 10, line=(0, 0, 1))]
    boxes = plan_redactions(words, identity_rects=[(0, 0, 10_000, 200)])
    assert boxes and boxes[0].reason == "street-address"


def test_crash_id_never_redacted():
    words = [W("Name:", 10, 10, line=(0, 0, 1)),
             W("105904161", 90, 10, line=(0, 0, 1))]
    boxes = plan_redactions(words)
    assert boxes == []


def test_phone_number_redacted():
    words = [W("919-555-1234", 10, 10, line=(0, 0, 1))]
    boxes = plan_redactions(words)
    assert boxes and boxes[0].reason == "phone"


# --- end to end ------------------------------------------------------------
def _font(size):
    from PIL import ImageFont
    for path in _FONTS:
        if os.path.exists(path):
            return ImageFont.truetype(path, size)
    return ImageFont.load_default()


@needs_ocr
def test_end_to_end_redaction(tmp_path):
    from PIL import Image, ImageDraw

    img = Image.new("RGB", (1400, 700), "white")
    d = ImageDraw.Draw(img)
    f = _font(34)
    d.text((60, 60), "Crash ID 105904161  County JOHNSTON", font=f, fill="black")
    d.text((60, 160), "Driver Name: Jonathan Smithfield", font=f, fill="black")
    d.text((60, 260), "Address: 4407 Buffalo Rd", font=f, fill="black")
    d.text((60, 360), "Wendell NC 27591", font=f, fill="black")
    d.text((60, 460), "Phone: 919-555-1234", font=f, fill="black")
    src = str(tmp_path / "report.png")
    img.save(src)

    out = str(tmp_path / "redacted.pdf")
    report = redact_file(src, out)
    assert report.boxes >= 2
    assert os.path.exists(out)

    # rasterize the output and re-OCR: PII gone, zip + crash id remain
    from safety_eval.redact import ocr_words, pdf_to_images
    pages = pdf_to_images(out, str(tmp_path), dpi=200)
    text = " ".join(w.text for w in ocr_words(pages[0]))
    assert "Smithfield" not in text
    assert "Buffalo" not in text
    assert "Wendell" not in text      # city line under the address is covered
    assert "555-1234" not in text
    assert "27591" in text            # zip survives
    assert "105904161" in text        # crash id survives


#: An identity zone covering the whole toy page, for tests that exercise the
#: address/phone/VIN pattern rules. Those rules are scoped to the occupants'
#: boxes; see test_narrative_address_is_not_redacted for why.
WHOLE_PAGE = [(0, 0, 10_000, 10_000)]


def test_city_line_under_street_address_redacted_keeping_zip():
    words = [W("4407", 10, 10, line=(0, 0, 1)),
             W("Buffalo", 80, 10, line=(0, 0, 1)),
             W("Rd", 170, 10, line=(0, 0, 1)),
             W("Wendell", 10, 40, w=80, line=(0, 0, 2)),
             W("NC", 100, 40, w=30, line=(0, 0, 2)),
             W("27591", 160, 40, line=(0, 0, 2))]
    boxes = plan_redactions(words, identity_rects=WHOLE_PAGE)
    reasons = {b.reason for b in boxes}
    assert "street-address" in reasons
    assert "address-continuation" in reasons
    # zip on the city line stays visible
    for b in boxes:
        if b.reason == "address-continuation":
            assert b.right < 160


def test_narrative_address_is_not_redacted():
    """The redactor covers the PEOPLE, not the crash location.

    An engineer re-mileposts by seeing where the report actually places the
    crash, and their own note for that is "placed at address". Blacking a
    street address in the narrative or location block removes the evidence the
    review exists to weigh. Measured cost of getting this wrong: the assist
    proposed RE on 0 of 16 real RE rows (docs/11).
    """
    words = [W("Vehicle", 10, 300, w=70, line=(0, 0, 9)),
             W("1", 90, 300, line=(0, 0, 9)),
             W("struck", 110, 300, w=60, line=(0, 0, 9)),
             W("pole", 180, 300, w=40, line=(0, 0, 9)),
             W("at", 230, 300, w=20, line=(0, 0, 9)),
             W("4407", 260, 300, line=(0, 0, 9)),
             W("Buffalo", 320, 300, w=70, line=(0, 0, 9)),
             W("Rd", 400, 300, line=(0, 0, 9))]
    identity = [(0, 0, 10_000, 200)]           # header block only
    boxes = plan_redactions(words, identity_rects=identity)
    assert not boxes, [b.reason for b in boxes]


def test_pattern_rules_do_not_fire_without_zones():
    """No registration means no known identity block, so no pattern guessing.

    Captioned PII is still covered by the label rules and the persons-table
    band, which key on the form's own captions.
    """
    words = [W("4407", 10, 10, line=(0, 0, 1)),
             W("Buffalo", 80, 10, line=(0, 0, 1)),
             W("Rd", 170, 10, line=(0, 0, 1))]
    assert plan_redactions(words) == []


def test_verifier_shares_the_planner_scope():
    """Otherwise it reports the crash location as a leak and blocks the page."""
    from safety_eval.redact import _residual_groups
    words = [W("4407", 260, 300, line=(0, 0, 9)),
             W("Buffalo", 320, 300, w=70, line=(0, 0, 9)),
             W("Rd", 400, 300, line=(0, 0, 9))]
    assert list(_residual_groups(words, True, [(0, 0, 10_000, 200)])) == []
    assert list(_residual_groups(words, True, WHOLE_PAGE))


# --- study-road address exemption (local_roads) ----------------------------
def _driver_block_address(road=("Tom", "Boyd")):
    """A driver-identity row: name left, '1518 <road> Rd' to its right."""
    a, b = road
    return [W("John", 20, 100, line=(0, 0, 3)),
            W("Smith", 90, 100, line=(0, 0, 3)),
            W("1518", 300, 100, line=(0, 0, 3)),
            W(a, 370, 100, line=(0, 0, 3)),
            W(b, 440, 100, line=(0, 0, 3)),
            W("Rd", 510, 100, line=(0, 0, 3))]


DRIVER_ZONE = [(0, 50, 10_000, 200)]


def test_local_road_address_words_matches_span_only():
    from safety_eval.redact import local_address_words
    words = _driver_block_address()
    kept = local_address_words(words, ["TOM BOYD"], DRIVER_ZONE)
    assert sorted(w.text for w in kept) == ["1518", "Boyd", "Rd", "Tom"]


def test_local_road_address_survives_planning_but_name_does_not():
    """The planner carves the kept span out of its own boxes, and the zone
    band (which is what actually covers an uncaptioned name in the driver
    block) splits around the kept words, leaving the name covered."""
    from safety_eval import form_geometry as fg
    from safety_eval.redact import local_address_words
    words = _driver_block_address()
    kept = local_address_words(words, ["TOM BOYD"], DRIVER_ZONE)
    boxes = plan_redactions(words, identity_rects=DRIVER_ZONE,
                            local_keep=kept)
    for b in boxes:                      # no box may cover the address span
        assert not (b.left <= 310 and b.right >= 520), b
    holes = [(w.left, w.top, w.right, w.bottom) for w in kept]
    pieces = fg.rect_minus(DRIVER_ZONE[0], holes)

    def covered(x, y=110):
        return any(x0 <= x <= x1 and y0 <= y <= y1
                   for x0, y0, x1, y1 in pieces)
    assert covered(50) and covered(120)          # the name stays covered
    assert not covered(380) and not covered(460)  # the address shows


def test_other_roads_stay_covered_with_local_roads_set():
    from safety_eval.redact import local_address_words
    words = _driver_block_address(road=("Buffalo", "Creek"))
    kept = local_address_words(words, ["TOM BOYD"], DRIVER_ZONE)
    assert kept == []


def test_no_exemption_outside_the_driver_owner_zones():
    """A persons-table address on the study road stays covered: the table
    lists occupants, not the driver/owner the engineer asked to keep."""
    from safety_eval.redact import local_address_words
    words = _driver_block_address()
    kept = local_address_words(words, ["TOM BOYD"], [(0, 500, 10_000, 900)])
    assert kept == []


def test_verifier_shares_the_local_road_exemption():
    from safety_eval.redact import _residual_groups
    words = [W("1518", 300, 100, line=(0, 0, 3)),
             W("Tom", 370, 100, line=(0, 0, 3)),
             W("Boyd", 440, 100, line=(0, 0, 3)),
             W("Rd", 510, 100, line=(0, 0, 3))]
    # without the exemption: flagged as a surviving street address
    assert list(_residual_groups(words, True, DRIVER_ZONE))
    # with it: kept by design, not a finding
    assert list(_residual_groups(words, True, DRIVER_ZONE,
                                 local_roads=["TOM BOYD"],
                                 addr_rects=DRIVER_ZONE)) == []


def test_ocr_timeout_env(monkeypatch):
    from safety_eval.redact import _ocr_timeout
    monkeypatch.delenv("SAFETY_EVAL_OCR_TIMEOUT", raising=False)
    assert _ocr_timeout() == 120
    monkeypatch.setenv("SAFETY_EVAL_OCR_TIMEOUT", "600")
    assert _ocr_timeout() == 600
    monkeypatch.setenv("SAFETY_EVAL_OCR_TIMEOUT", "bogus")
    assert _ocr_timeout() == 120


# --- charge-line names ------------------------------------------------------
def test_charge_line_covers_the_name_and_keeps_the_charge():
    """The offense text is evidence (ran stop sign vs failed to yield);
    the person beside it is not. Real leak: a name survived on a charge
    line whose caption OCR lost (600504376 p60)."""
    words = [W("Charged:", 10, 10, w=70, line=(0, 0, 1)),
             W("DALTON", 90, 10, line=(0, 0, 1)),
             W("PRUITT", 160, 10, line=(0, 0, 1)),
             W("FAILURE", 240, 10, line=(0, 0, 1)),
             W("TO", 310, 10, w=25, line=(0, 0, 1)),
             W("YIELD", 345, 10, line=(0, 0, 1))]
    boxes = plan_redactions(words)
    assert [b.reason for b in boxes] == ["charge-line-name"]
    b = boxes[0]
    assert b.left <= 95 and b.right >= 215        # both name words covered
    assert b.right < 240, b                       # the charge text is clear


def test_charge_line_with_only_offense_text_is_untouched():
    words = [W("Charge:", 10, 10, w=60, line=(0, 0, 1)),
             W("EXCEEDING", 80, 10, w=90, line=(0, 0, 1)),
             W("SAFE", 180, 10, line=(0, 0, 1)),
             W("SPEED", 250, 10, line=(0, 0, 1))]
    assert plan_redactions(words) == []


def test_charge_rule_ignores_ordinary_narrative_lines():
    words = [W("Vehicle", 10, 10, w=70, line=(0, 0, 1)),
             W("1", 90, 10, w=15, line=(0, 0, 1)),
             W("struck", 110, 10, line=(0, 0, 1)),
             W("DALTON", 180, 10, line=(0, 0, 1))]
    # no charge context on the line: this rule stays out of it
    from safety_eval.redact import _charge_line_names, _norm
    assert _charge_line_names(words, [_norm(w.text) for w in words]) is None


def test_verifier_flags_a_surviving_charge_line_name():
    from safety_eval.redact import _residual_groups
    words = [W("Charged:", 10, 10, w=70, line=(0, 0, 1)),
             W("DALTON", 90, 10, line=(0, 0, 1)),
             W("RAN", 170, 10, w=35, line=(0, 0, 1)),
             W("STOP", 215, 10, line=(0, 0, 1)),
             W("SIGN", 280, 10, line=(0, 0, 1))]
    found = list(_residual_groups(words, True, None))
    assert [r for _, r in found] == ["charge-line name survived"]
    assert [w.text for w in found[0][0]] == ["DALTON"]
