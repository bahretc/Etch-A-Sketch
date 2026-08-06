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
