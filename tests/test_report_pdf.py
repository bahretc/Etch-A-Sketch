"""Report-PDF assembly tests: the pure parts (region measurement, map
overlay, page concatenation) run against synthetic PDFs; the UNO print
itself needs a running LibreOffice and is exercised by the CLI, not
here. The print range is pinned to the completed workbooks' saved
Print_Area."""
import os
import re
import shutil
import zipfile

import pytest

from safety_eval.report_pdf import (PRINT_RANGE, RESULTS_SHEET, ROW_HEIGHTS,
                                    assemble, measure_map_region, overlay_map)

HERE = os.path.dirname(__file__)
COMPLETED = os.path.join(
    HERE, "..", "examples", "SS-6002AD",
    "Intersection Evaluation Workbook - 02-20-62356 (TIP #SS-6002AD) "
    "1 of 2.xlsx")

needs_pdftotext = pytest.mark.skipif(
    shutil.which("pdftotext") is None, reason="pdftotext not installed")
needs_completed = pytest.mark.skipif(
    not os.path.exists(COMPLETED), reason="completed example not present")


def _fake_onepager(path):
    """A letter page carrying the two headings the measurer anchors on."""
    reportlab = pytest.importorskip("reportlab")  # noqa: F841
    from reportlab.pdfgen import canvas

    c = canvas.Canvas(path, pagesize=(612, 792))
    # y here is from the bottom; the measurer reports from the top
    c.drawString(300, 792 - 400, "Map/Satellite Views")
    c.drawString(60, 792 - 700, "Items for Discussion")
    c.save()
    return path


@needs_pdftotext
def test_measure_map_region_finds_the_box(tmp_path):
    pdf = _fake_onepager(str(tmp_path / "one.pdf"))
    x0, ytop, x1, ybot = measure_map_region(pdf)
    # x0 hugs the heading's left edge; x1 the widest printed word
    assert 295 < x0 < 305
    assert x1 > x0 + 50
    # region starts just below the header and stops above the Items head
    assert 395 < ytop < 415
    assert 675 < ybot < 695
    assert ybot - ytop > 250
    # explicit overrides still win
    ex0, _, ex1, _ = measure_map_region(pdf, x0=296.0, x1=577.0)
    assert (ex0, ex1) == (296.0, 577.0)


@needs_pdftotext
def test_measure_map_region_without_the_headings(tmp_path):
    reportlab = pytest.importorskip("reportlab")  # noqa: F841
    from reportlab.pdfgen import canvas

    pdf = str(tmp_path / "blank.pdf")
    c = canvas.Canvas(pdf, pagesize=(612, 792))
    c.drawString(60, 700, "nothing to anchor on")
    c.save()
    with pytest.raises(RuntimeError):
        measure_map_region(pdf)


@needs_pdftotext
def test_overlay_map_keeps_one_page(tmp_path):
    Image = pytest.importorskip("PIL.Image")
    pytest.importorskip("pypdf")
    pdf = _fake_onepager(str(tmp_path / "one.pdf"))
    png = str(tmp_path / "map.png")
    Image.new("RGB", (768, 550), (40, 90, 40)).save(png)
    out = overlay_map(pdf, png, str(tmp_path / "with_map.pdf"))
    from pypdf import PdfReader
    assert len(PdfReader(out).pages) == 1
    assert not os.path.exists(out + ".overlay.tmp")


def test_assemble_concatenates_in_order(tmp_path):
    pytest.importorskip("pypdf")
    reportlab = pytest.importorskip("reportlab")  # noqa: F841
    from reportlab.pdfgen import canvas

    from pypdf import PdfReader

    parts = []
    for i, n in enumerate((1, 2)):
        p = str(tmp_path / f"p{i}.pdf")
        c = canvas.Canvas(p, pagesize=(612, 792))
        for _ in range(n):
            c.drawString(72, 720, f"part {i}")
            c.showPage()
        c.save()
        parts.append(p)
    out = assemble(parts, str(tmp_path / "out.pdf"))
    assert len(PdfReader(out).pages) == 3


@needs_completed
def test_print_range_matches_the_completed_workbooks():
    """The exported range is the deliverables' saved Print_Area."""
    with zipfile.ZipFile(COMPLETED) as z:
        wb = z.read("xl/workbook.xml").decode("utf-8", "replace")
    areas = re.findall(r"<definedName name=\"_xlnm.Print_Area\"[^>]*>"
                       r"([^<]+)</definedName>", wb)
    assert f"'{RESULTS_SHEET}'!$B$2:$L$72" in areas
    assert PRINT_RANGE == "B2:L72"


def test_row_heights_cover_the_engineer_sized_blocks():
    """Countermeasures, Target list, map column, Items cell."""
    assert all(ROW_HEIGHTS[r] == 920 for r in range(18, 23))
    assert all(ROW_HEIGHTS[r] == 430 for r in range(33, 39))
    assert all(ROW_HEIGHTS[r] == 900 for r in range(40, 57))
    assert ROW_HEIGHTS[58] == 4800
    assert set(ROW_HEIGHTS) == (set(range(18, 23)) | set(range(33, 39))
                                | set(range(40, 57)) | {58})
