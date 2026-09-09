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


# --- v2 planner: geometry bands, section 32, token patterns ----------------
def test_band_covers_value_even_when_ocr_missed_it():
    # handwriting case: only the printed caption OCRs; the value area right
    # of/below it must still be covered by the band
    words = [W("Driver", 100, 200, w=50, h=14),
             W("filler", 900, 900)]
    boxes = plan_redactions(words, page_width=1700, page_height=2200)
    bands = [b for b in boxes if b.reason == "band:name"]
    assert bands, "caption alone must produce a band"
    b = bands[0]
    assert b.right >= 100 + int(0.40 * 1700)
    assert b.bottom > 214, "band must cover the value row"
    assert b.top < 200, "band must reach above the caption for tall values"


def test_band_fires_on_caption_glued_to_value():
    # tesseract often merges caption and value: "OwnerJALEAH"
    words = [W("OwnerJALEAH", 100, 200, w=200, h=20)]
    boxes = plan_redactions(words, page_width=1700, page_height=2200)
    assert any(b.reason == "band:name" for b in boxes)


def test_band_clips_at_zip_caption():
    words = [W("Address", 100, 200, w=60, h=14),
             W("Zip", 500, 200, w=30, h=14)]
    boxes = plan_redactions(words, page_width=1700, page_height=2200)
    addr = [b for b in boxes if b.reason == "band:address"]
    assert addr and addr[0].right <= 498, "band must stop before the Zip box"


def test_zip4_run_on_is_partially_redacted():
    # 9-digit ZIP+4 (e.g. 283526345) is NOT a crash id and its +4 must go
    words = [W("283526345", 100, 100, w=90, h=20)]
    boxes = plan_redactions(words, page_width=1700, page_height=2200)
    z = [b for b in boxes if b.reason == "zip+4"]
    assert z, "ZIP+4 run-on must be redacted"
    assert z[0].left > 130, "the 5-digit prefix stays visible"


def test_crash_and_document_ids_still_protected():
    words = [W("107822778", 100, 100, w=90, h=20),
             W("600504078", 100, 140, w=90, h=20)]
    boxes = plan_redactions(words, page_width=1700, page_height=2200)
    assert boxes == []


def test_long_digit_runs_redacted():
    # DL numbers (7-8 digits) and policy numbers (10+ digits)
    words = [W("21758723", 100, 100, w=80, h=20),
             W("11408502130", 100, 140, w=110, h=20)]
    boxes = plan_redactions(words, page_width=1700, page_height=2200)
    assert len(boxes) == 2


def test_section32_table_columns_covered():
    words = [W("Names", 700, 1600, w=60, h=16),
             W("Addresses", 780, 1600, w=90, h=16),
             W("EMS", 200, 2100, w=40, h=16)]
    boxes = plan_redactions(words, page_width=1700, page_height=2200)
    reasons = {b.reason for b in boxes}
    assert "section32:dob" in reasons and "section32:names" in reasons
    names = next(b for b in boxes if b.reason == "section32:names")
    assert names.top >= 1616 and names.bottom <= 2100
    assert names.left >= int(0.35 * 1700)
