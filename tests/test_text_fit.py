"""Text fitting: the engineer sizes the font to the cell, never the cell
to the font. Measurements are validated against his own completed
workbooks, where the size he chose is known."""
import os
import re
import zipfile

import pytest

from safety_eval.text_fit import (box_size_pt, column_width_pt, fit_font_size,
                                  rows_needed, sheet_geometry, wrapped_lines)

HERE = os.path.dirname(__file__)
TEMPLATE = os.path.join(
    HERE, "..", "templates", "Intersection Evaluation Workbook - 2023-12-04.xlsx")
COMPLETED = os.path.join(
    HERE, "..", "examples", "SS-6002AD",
    "Intersection Evaluation Workbook - 02-20-62356 (TIP #SS-6002AD) "
    "1 of 2.xlsx")
SHEET = "1 page results - 1 Target"

needs_pil = pytest.mark.skipif(
    __import__("importlib").util.find_spec("PIL") is None,
    reason="pillow not installed")
needs_completed = pytest.mark.skipif(
    not os.path.exists(COMPLETED), reason="completed example not present")


def _sheet_xml(path, sheet=SHEET):
    from safety_eval.xlsx_patch import sheet_files
    with zipfile.ZipFile(path) as z:
        return z.read(sheet_files(path)[sheet]).decode("utf-8")


def test_column_width_matches_excels_own_conversion():
    # 8.43 characters is Excel's default column: 64 px, 48 pt
    assert column_width_pt(8.43) == pytest.approx(48.0, abs=0.8)
    assert column_width_pt(15.0) == pytest.approx(82.5, abs=1.0)


@needs_completed
def test_sheet_geometry_expands_grouped_column_ranges():
    """<col min=4 max=6> covers D, E and F; a per-column read misses two."""
    widths, heights = sheet_geometry(_sheet_xml(COMPLETED))
    assert {"D", "E", "F"} <= set(widths)
    assert widths["D"] == widths["E"] == widths["F"]
    assert heights[57] == 18.0 and heights[58] == 15.0


@needs_completed
def test_box_size_is_the_sum_of_its_cells():
    xml = _sheet_xml(COMPLETED)
    width, height = box_size_pt(xml, "C58:K62")
    assert height == 75.0                      # 5 rows on the 15pt pitch
    assert 780 < width < 800                   # C..K across the printed page


@needs_pil
def test_wrapped_lines_counts_hard_breaks_and_wrapping():
    text = "one\ntwo three"
    assert wrapped_lines(text, 11.0, 400.0) == 2
    long = " ".join(["word"] * 60)
    assert wrapped_lines(long, 11.0, 200.0) > 3
    assert wrapped_lines(long, 6.0, 200.0) < wrapped_lines(long, 11.0, 200.0)


@needs_pil
def test_fit_picks_the_largest_size_that_fits():
    text = "\n".join(["• " + "word " * 30] * 4)
    size, lines, need = fit_font_size(text, 400.0, 120.0)
    assert size is not None and need <= 120.0
    bigger = [s for s in (11.0, 10.5, 10.0, 9.5, 9.0) if s > size]
    for s in bigger:
        n = wrapped_lines(text, s, 400.0)
        assert n * 1.15 * s > 120.0            # nothing larger would fit


@needs_pil
def test_fit_reports_failure_instead_of_clipping():
    text = "\n".join(["• " + "word " * 40] * 12)
    size, lines, need = fit_font_size(text, 300.0, 40.0)
    assert size is None and need > 40.0


@needs_pil
@needs_completed
def test_model_reproduces_the_engineers_own_font_choice():
    """SS-6002AD holds its 432-char Items block at 11pt in 5 rows."""
    import html

    xml = _sheet_xml(COMPLETED)
    with zipfile.ZipFile(COMPLETED) as z:
        ss = re.findall(r"<si>(.*?)</si>",
                        z.read("xl/sharedStrings.xml").decode(), re.S)
    m = re.search(r'<c r="C58"[^>]*t="s"[^>]*><v>(\d+)</v>', xml)
    text = html.unescape(re.sub(r"<[^>]+>", "", ss[int(m.group(1))]))
    text = text.replace("\r\n", "\n")
    width, height = box_size_pt(xml, "C58:K62")
    size, lines, need = fit_font_size(text, width, height)
    assert size == 11.0                        # the size he actually used
    assert need <= height


@needs_pil
def test_rows_needed_is_whole_rows_of_the_sheet_pitch():
    text = "\n".join(["• " + "word " * 30] * 6)
    rows = rows_needed(text, 9.0, 400.0)
    assert rows >= 1 and rows == int(rows)
