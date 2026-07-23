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
    words = [W("4407", 10, 10, line=(0, 0, 1)),
             W("Buffalo", 80, 10, line=(0, 0, 1)),
             W("Rd", 160, 10, line=(0, 0, 1))]
    boxes = plan_redactions(words)
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


def test_city_line_under_street_address_redacted_keeping_zip():
    words = [W("4407", 10, 10, line=(0, 0, 1)),
             W("Buffalo", 80, 10, line=(0, 0, 1)),
             W("Rd", 170, 10, line=(0, 0, 1)),
             W("Wendell", 10, 40, w=80, line=(0, 0, 2)),
             W("NC", 100, 40, w=30, line=(0, 0, 2)),
             W("27591", 160, 40, line=(0, 0, 2))]
    boxes = plan_redactions(words)
    reasons = {b.reason for b in boxes}
    assert "street-address" in reasons
    assert "address-continuation" in reasons
    # zip on the city line stays visible
    for b in boxes:
        if b.reason == "address-continuation":
            assert b.right < 160
