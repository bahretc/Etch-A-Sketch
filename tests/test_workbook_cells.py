"""workbook_cells: colour, value and shared-string patches keep the docs/06 gate."""
import os
import zipfile
from xml.dom import minidom

import openpyxl
import pytest

from safety_eval.workbook_cells import CellPatch, apply_cell_patches, cell_colours
from safety_eval.xlsx_patch import verify_integrity

TEMPLATE = "templates/Intersection Evaluation Workbook - 2023-12-04.xlsx"
pytestmark = pytest.mark.skipif(not os.path.exists(TEMPLATE), reason="template not present")


def test_colour_value_and_text_patches(tmp_path):
    out = str(tmp_path / "p.xlsx")
    log = apply_cell_patches(TEMPLATE, out, [
        CellPatch("Evaluation Set-up", "L21", value=4100, colour="red"),
        CellPatch("Evaluation Set-up", "M21", value=2200, colour="black"),
        CellPatch("1 page results - 1 Target", "D9", text="SR 1001 (Sikes Mill Road) at SR 1617"),
    ])
    assert len(log) == 5
    assert verify_integrity(TEMPLATE, out).ok
    assert cell_colours(out, "Evaluation Set-up", ["L21", "M21"]) == {"L21": "red", "M21": "black"}
    wb = openpyxl.load_workbook(out)
    assert wb["Evaluation Set-up"]["L21"].value == 4100
    assert wb["1 page results - 1 Target"]["D9"].value == "SR 1001 (Sikes Mill Road) at SR 1617"
    with zipfile.ZipFile(out) as z:
        for n in ("xl/styles.xml", "xl/sharedStrings.xml"):
            minidom.parseString(z.read(n))


def test_formula_cells_are_refused(tmp_path):
    with pytest.raises(ValueError):
        apply_cell_patches(TEMPLATE, str(tmp_path / "x.xlsx"),
                           [CellPatch("Evaluation Set-up", "N21", value=1)])


def test_missing_cell_and_sheet(tmp_path):
    with pytest.raises(KeyError):
        apply_cell_patches(TEMPLATE, str(tmp_path / "x.xlsx"), [CellPatch("Nope", "A1", value=1)])
    with pytest.raises(KeyError):
        apply_cell_patches(TEMPLATE, str(tmp_path / "x.xlsx"),
                           [CellPatch("Evaluation Set-up", "ZZ999", value=1)])


def test_recolouring_reuses_styles(tmp_path):
    """Two cells recoloured the same way share one new cellXfs entry."""
    out = str(tmp_path / "p.xlsx")
    apply_cell_patches(TEMPLATE, out, [CellPatch("Evaluation Set-up", "L21", colour="red"),
                                       CellPatch("Evaluation Set-up", "L22", colour="red")])
    with zipfile.ZipFile(TEMPLATE) as a, zipfile.ZipFile(out) as b:
        import re
        n0 = int(re.search(r'<cellXfs count="(\d+)"', a.read("xl/styles.xml").decode()).group(1))
        n1 = int(re.search(r'<cellXfs count="(\d+)"', b.read("xl/styles.xml").decode()).group(1))
    assert n1 - n0 <= 1
