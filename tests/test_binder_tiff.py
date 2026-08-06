"""Binder indexing over multi-page TIFF.

binder.py's docstring has always said "PDF/TIFF", but _page_count went
straight to pypdf and TIFF raised PdfStreamError. TEAAS binders arrive as
Group 4 bilevel TIFF at least as often as PDF, so this pins the support.
"""
import pytest

from safety_eval import binder

Image = pytest.importorskip("PIL.Image")


def _tiff(tmp_path, pages=3, size=(1699, 2199)):
    frames = []
    for i in range(pages):
        im = Image.new("L", size, 255)
        for y in range(60 + i * 3):                 # something per page to see
            for x in range(40):
                im.putpixel((100 + x, 100 + y), 0)
        frames.append(im.convert("1"))
    p = tmp_path / "binder.tif"
    frames[0].save(p, save_all=True, append_images=frames[1:],
                   compression="group4")
    return str(p)


def test_page_count_reads_a_multipage_tiff(tmp_path):
    assert binder._page_count(_tiff(tmp_path, pages=5)) == 5


def test_is_tiff_detects_both_extensions():
    assert binder._is_tiff("a.tif") and binder._is_tiff("A.TIFF")
    assert not binder._is_tiff("a.pdf")


def test_render_page_returns_a_png_of_the_requested_page(tmp_path):
    src = _tiff(tmp_path, pages=3)
    out = binder._render_page(src, 2, binder._TIFF_NATIVE_DPI, str(tmp_path))
    assert out.endswith(".png")
    with Image.open(out) as im:
        assert im.size == (1699, 2199)              # native, unresampled


def test_render_page_resamples_when_dpi_differs(tmp_path):
    """A TIFF's pixels are fixed, so dpi means rescale, not rasterize."""
    src = _tiff(tmp_path, pages=2)
    out = binder._render_page(src, 1, 100, str(tmp_path))
    with Image.open(out) as im:
        assert im.size == (850, 1100)               # half of 200 dpi native


def test_pages_are_distinct(tmp_path):
    """Guards a seek bug that would hand every page the first frame."""
    src = _tiff(tmp_path, pages=3)
    seen = []
    for pg in (1, 2, 3):
        out = binder._render_page(src, pg, binder._TIFF_NATIVE_DPI, str(tmp_path))
        with Image.open(out) as im:
            seen.append(sum(1 for px in im.convert("L").tobytes() if px < 128))
    assert len(set(seen)) == 3, seen


# ---------------------------------------------------------------------------
# render_crash_pages must not have its own weaker redactor
# ---------------------------------------------------------------------------

def test_render_crash_pages_uses_the_hardened_redactor(monkeypatch, tmp_path):
    """It used to apply a single plan_redactions pass of its own.

    The multi-pass, multi-scale convergence, the cross-page name harvest and
    the DMV-349 field geometry all live in redact.redact_file, and the private
    copy here never got them. Measured on a real 47-report binder, the private
    copy left residual PII on 28 of them. This pins that the shared path is
    what runs.
    """
    from safety_eval import binder as B

    idx = B.BinderIndex(pages_by_crash={"105451449": [B.PageRef("b.tif", 1)]})
    called = {}

    def fake_redact_file(src, dst, keep_zip=True, dpi=200, **kw):
        called["redact_file"] = True
        Image.new("RGB", (100, 130), "white").save(dst)
        return None

    monkeypatch.setattr(B, "_render_page",
                        lambda *a, **k: str(_png(tmp_path, "raw.png")))
    monkeypatch.setattr("safety_eval.redact.redact_file", fake_redact_file)
    monkeypatch.setattr("safety_eval.redact.verify_redaction",
                        lambda paths, keep_zip=True: called.setdefault("verified", True))
    monkeypatch.setattr(B, "pdf_to_images",
                        lambda pdf, wd, dpi: [str(_png(tmp_path, "out.png"))])

    B.render_crash_pages(idx, "105451449", dpi=200)
    assert called.get("redact_file"), "did not go through redact.redact_file"
    assert called.get("verified"), "did not verify before returning"


def test_render_crash_pages_fails_closed(monkeypatch, tmp_path):
    """A caller that gets pages back knows they are clean; otherwise it raises."""
    from safety_eval import binder as B
    from safety_eval.redact import RedactionIncomplete

    idx = B.BinderIndex(pages_by_crash={"105451449": [B.PageRef("b.tif", 1)]})
    monkeypatch.setattr(B, "_render_page",
                        lambda *a, **k: str(_png(tmp_path, "raw.png")))
    monkeypatch.setattr("safety_eval.redact.redact_file",
                        lambda src, dst, **kw: Image.new("RGB", (100, 130)).save(dst))
    monkeypatch.setattr(B, "pdf_to_images",
                        lambda pdf, wd, dpi: [str(_png(tmp_path, "out.png"))])

    def boom(paths, keep_zip=True):
        raise RedactionIncomplete("1 finding still legible")
    monkeypatch.setattr("safety_eval.redact.verify_redaction", boom)

    with pytest.raises(RedactionIncomplete):
        B.render_crash_pages(idx, "105451449", dpi=200)


def test_render_crash_pages_empty_for_unknown_crash():
    from safety_eval import binder as B
    assert B.render_crash_pages(B.BinderIndex(), "999999999") == []


def _png(tmp_path, name):
    p = tmp_path / name
    Image.new("RGB", (100, 130), "white").save(p)
    return p
