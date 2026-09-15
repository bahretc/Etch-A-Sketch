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


def test_field_number_beside_caption_still_covers_the_next_line():
    """'86 Type/Owner' left only a field number beside the caption, which
    took the value-before branch and never armed next-line coverage; the
    property owner's name below survived (600504376 p12/p20)."""
    words = [W("86", 10, 10, w=25, line=(0, 0, 1)),
             W("Owner", 45, 10, w=55, line=(0, 0, 1)),
             W("MAILBOX-LINDSAY", 12, 40, w=170, line=(0, 0, 2)),
             W("BENFIELD", 190, 40, w=90, line=(0, 0, 2))]
    boxes = plan_redactions(words)
    below = [b for b in boxes if b.top >= 30]
    assert below, [b.reason for b in boxes]
    assert any(b.left <= 15 and b.right >= 275 for b in below), below


def test_study_road_tokens_never_scrub_as_names():
    from safety_eval.redact import _road_token_seqs
    vocab = {t for seq in _road_token_seqs(["SIKES MILL", "TOM BOYD"])
             for t in seq}
    assert vocab == {"SIKES", "MILL", "TOM", "BOYD"}


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


# --- v3 hardening: fuzzy captions, era dates, name scrub -------------------
def test_fuzzy_caption_matches_degraded_scan():
    from safety_eval.redact import _match_anchor
    assert _match_anchor("drlver") is not None    # misread i -> l
    assert _match_anchor("owher") is not None
    assert _match_anchor("random") is None


def test_dob_aged_dates_redacted_but_crash_dates_kept():
    # era = 2025 (crash + received date); DOBs are years older
    words = [W("04/05/2025", 100, 100, w=120, h=20),
             W("04/11/2025", 100, 140, w=120, h=20),
             W("09/12/2007", 100, 400, w=120, h=20),
             W("10/20/1976", 100, 440, w=120, h=20)]
    boxes = plan_redactions(words, page_width=1700, page_height=2200)
    aged = [b for b in boxes if b.reason == "dob-aged-date"]
    assert len(aged) == 2
    assert all(b.top >= 390 for b in aged), "crash-era dates must stay"


def test_known_names_scrubbed_everywhere():
    words = [W("VEHICLE", 100, 900, w=80, h=20),
             W("SWETT", 200, 900, w=60, h=20),
             W("OVERTURNED", 280, 900, w=110, h=20)]
    boxes = plan_redactions(words, page_width=1700, page_height=2200,
                            known_names={"SWETT"})
    named = [b for b in boxes if b.reason == "known-name"]
    assert len(named) == 1 and named[0].left <= 200 <= named[0].right


def test_harvest_collects_names_from_bands_only():
    from safety_eval.redact import harvest_name_tokens
    words = [W("Driver", 100, 200, w=50, h=14),
             W("JEREMY", 180, 200, w=70, h=20),
             W("SWETT", 270, 200, w=60, h=20),
             W("First", 180, 224, w=40, h=10),
             W("ROBESON", 900, 100, w=90, h=20)]   # outside any band
    names = harvest_name_tokens(words, 1700, 2200)
    assert "JEREMY" in names and "SWETT" in names
    assert "ROBESON" not in names
    assert "FIRST" not in names                     # caption stoplist


def test_subcaption_row_covers_name_above_it():
    # "Dnver" (misread caption) + typed name, with First/Middle below
    words = [W("Dnver", 187, 75, w=60, h=14),
             W("JEREMY", 259, 65, w=90, h=22),
             W("SWETT", 638, 61, w=80, h=22),
             W("First", 324, 87, w=40, h=10),
             W("Middle", 474, 87, w=50, h=10)]
    boxes = plan_redactions(words, page_width=1024, page_height=1350)
    subs = [b for b in boxes if b.reason == "name-above-subcaption"]
    assert subs, "First/Middle row must anchor a band over the name row"
    b = subs[0]
    assert b.left <= 259 and b.right >= 638 + 80
    assert b.top <= 61 and b.bottom >= 85
    # and the dist-2 fuzzy anchor now also catches "Dnver" itself
    assert any(x.reason == "band:name" for x in boxes)


def test_harvest_includes_structurally_found_names():
    from safety_eval.redact import harvest_name_tokens
    words = [W("Dnver", 187, 75, w=60, h=14),
             W("JEREMY", 259, 65, w=90, h=22),
             W("First", 324, 87, w=40, h=10),
             W("Middle", 474, 87, w=50, h=10)]
    assert "JEREMY" in harvest_name_tokens(words, 1024, 1350)


@needs_ocr
def test_ocr_words_survive_stray_quote_glyph(tmp_path):
    # a lone " glyph must not make csv swallow the rest of the TSV
    from PIL import Image, ImageDraw
    from safety_eval.redact import ocr_words
    img = Image.new("RGB", (900, 300), "white")
    d = ImageDraw.Draw(img)
    f = _font(30)
    d.text((40, 40), '"FAULT " 11409384563', font=f, fill="black")
    d.text((40, 140), "Names and Addresses for All Persons", font=f, fill="black")
    p = str(tmp_path / "q.png")
    img.save(p)
    words = ocr_words(p, psm=3)
    texts = {w.text for w in words}
    assert any("Addresses" in t for t in texts), texts
    assert all("\t" not in w.text for w in words)
