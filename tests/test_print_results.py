"""print_results: LibreOffice print of the results page and PDF binding."""
import os
import shutil

import pytest

from safety_eval.print_results import (assemble_deliverables, embedded_images, fonts_report,
                                       ink_extents_inches, pdf_page_texts, print_sheet, render_png,
                                       soffice_path)

TEMPLATE = "templates/Intersection Evaluation Workbook - 2023-12-04.xlsx"
needs_lo = pytest.mark.skipif(not (soffice_path() and shutil.which("pdftotext") and os.path.exists(TEMPLATE)),
                              reason="LibreOffice, poppler or the template missing")


def test_fonts_report_keys():
    fr = fonts_report()
    assert {"carlito", "liberation_serif"} <= set(fr)


@needs_lo
def test_print_bind_and_measure(tmp_path):
    page1 = str(tmp_path / "page1.pdf")
    rep = print_sheet(TEMPLATE, page1, timeout=600)
    assert rep.page_index >= 1 and len(pdf_page_texts(page1)) == 1
    assert "Safety Project Evaluation" in pdf_page_texts(page1)[0]
    ce, web = str(tmp_path / "ce.pdf"), str(tmp_path / "web.pdf")
    out = assemble_deliverables(page1, None, [page1], ce, web, title="T", author="A")
    assert out == {"complete_pages": 2, "web_pages": 1}
    import pikepdf
    with pikepdf.open(web) as pdf:
        assert str(pdf.docinfo["/Title"]) == "T" and str(pdf.docinfo["/Author"]) == "A"
    if shutil.which("pdftoppm"):
        png = render_png(page1, str(tmp_path / "p1"))
        ext = ink_extents_inches(png)
        assert 0.2 < ext["left"] < 1.0 and 9.0 < ext["height"] < 10.2
    assert isinstance(embedded_images(page1), list)
