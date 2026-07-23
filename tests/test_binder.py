"""Binder page-index tests: JSON round-trip without OCR, plus an end-to-end
proof on a synthetic scanned binder: front pages carry the crash ID in the
top-right header box (as on the DMV-349), continuation pages do not, and the
index must group continuations under the preceding report and redact PII on
retrieval."""
import os
import shutil

import pytest

from safety_eval.binder import BinderIndex, PageRef

HAVE_OCR = shutil.which("tesseract") and shutil.which("pdftoppm")
needs_ocr = pytest.mark.skipif(not HAVE_OCR,
                               reason="tesseract/poppler not installed")

_FONTS = [
    "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf",
    "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf",
]


def _font(size):
    from PIL import ImageFont
    for path in _FONTS:
        if os.path.exists(path):
            return ImageFont.truetype(path, size)
    return ImageFont.load_default()


def test_index_json_round_trip(tmp_path):
    idx = BinderIndex(
        pages_by_crash={"105904161": [PageRef("b.pdf", 1), PageRef("b.pdf", 2)],
                        "106001234": [PageRef("b.pdf", 3)]},
        unassigned=[],
        files=["b.pdf"],
        dpi=150,
        warnings=["b.pdf p9: OCR failed (boom)"],
    )
    path = str(tmp_path / "idx.json")
    idx.save(path)
    back = BinderIndex.load(path)
    assert back.pages_by_crash["105904161"] == idx.pages_by_crash["105904161"]
    assert back.files == ["b.pdf"]
    assert back.dpi == 150
    assert back.warnings == idx.warnings
    assert back.pages_for("106001234") == [PageRef("b.pdf", 3)]
    assert back.pages_for("999999999") == []


def test_reconcile_suggests_unique_shifted_id():
    from safety_eval.binder import apply_reconciliation, reconcile_index

    # true 108164536 printed with the leading 1 cut off reads as 081645367
    idx = BinderIndex(pages_by_crash={
        "081645367": [PageRef("b.pdf", 33), PageRef("b.pdf", 34)],
        "105904161": [PageRef("b.pdf", 1)],
    })
    known = {"105904161", "108164536", "107000000"}
    suggestions = reconcile_index(idx, known)
    assert suggestions == {"081645367": "108164536"}

    apply_reconciliation(idx, suggestions)
    assert "081645367" not in idx.pages_by_crash
    assert [p.page for p in idx.pages_for("108164536")] == [33, 34]
    assert any("108164536" in w for w in idx.warnings)


def test_reconcile_ambiguous_or_distant_reads_left_alone():
    from safety_eval.binder import reconcile_index

    idx = BinderIndex(pages_by_crash={"099999999": [PageRef("b.pdf", 1)]})
    # nothing shares a 7-digit run: no suggestion
    assert reconcile_index(idx, {"105904161", "106001234"}) == {}
    # two candidates sharing a run: ambiguous, no suggestion
    idx2 = BinderIndex(pages_by_crash={"051234567": [PageRef("b.pdf", 1)]})
    assert reconcile_index(idx2, {"105123456", "205123456"}) == {}


def _front_page(crash_id, body_lines):
    """A DMV-349-style front page: header box top-right with the crash ID."""
    from PIL import Image, ImageDraw

    img = Image.new("RGB", (1700, 2200), "white")
    d = ImageDraw.Draw(img)
    f = _font(36)
    d.rectangle([1050, 60, 1650, 300], outline="black", width=3)
    d.text((1080, 90), "Do not write in these spaces", font=f, fill="black")
    d.text((1080, 160), crash_id, font=_font(44), fill="black")
    y = 420
    for line in body_lines:
        d.text((80, y), line, font=f, fill="black")
        y += 90
    return img


def _back_page():
    """A continuation page: roadway grid captions, no header crash ID."""
    from PIL import Image, ImageDraw

    img = Image.new("RGB", (1700, 2200), "white")
    d = ImageDraw.Draw(img)
    f = _font(36)
    d.text((80, 100), "ROADWAY INFO  WORK ZONE RELATED", font=f, fill="black")
    d.text((80, 200), "Road Feature 8   Road Character 1", font=f, fill="black")
    d.text((80, 300), "Narrative continues without a header box.",
           font=f, fill="black")
    return img


@pytest.fixture(scope="module")
def binder_pdf(tmp_path_factory):
    tmp = tmp_path_factory.mktemp("binder")
    pages = [
        _front_page("105904161", ["Driver Name: Jonathan Smithfield",
                                  "Address: 4407 Buffalo Rd",
                                  "Wendell NC 27591"]),
        _back_page(),
        _front_page("106001234", ["Driver Name: Maria Example",
                                  "Phone: 919-555-1234"]),
        _back_page(),
        _back_page(),
    ]
    path = str(tmp / "binder.pdf")
    pages[0].save(path, format="PDF", save_all=True, append_images=pages[1:],
                  resolution=150)
    return path


@needs_ocr
def test_index_groups_continuation_pages(binder_pdf):
    from safety_eval.binder import index_binder

    idx = index_binder([binder_pdf], dpi=150, workers=2)
    assert set(idx.pages_by_crash) == {"105904161", "106001234"}
    assert [p.page for p in idx.pages_for("105904161")] == [1, 2]
    assert [p.page for p in idx.pages_for("106001234")] == [3, 4, 5]
    assert idx.unassigned == []


@needs_ocr
def test_export_crash_pdf_is_redacted(binder_pdf, tmp_path):
    from safety_eval.binder import export_crash_pdf, index_binder
    from safety_eval.redact import ocr_words, pdf_to_images

    idx = index_binder([binder_pdf], dpi=150, workers=2)
    out = str(tmp_path / "crash.pdf")
    n = export_crash_pdf(idx, "105904161", out, dpi=150)
    assert n == 2

    pages = pdf_to_images(out, str(tmp_path), dpi=150)
    text = " ".join(w.text for p in pages for w in ocr_words(p))
    assert "105904161" in text          # crash id survives redaction
    assert "27591" in text              # zip survives
    assert "Smithfield" not in text     # name gone
    assert "Buffalo" not in text        # street gone

    with pytest.raises(KeyError):
        export_crash_pdf(idx, "999999999", str(tmp_path / "x.pdf"))
