"""The completed-workbook formatting pass and its xlsx_patch primitives,
verified against the shipped intersection template (rule 8: addresses come
from the real file, not the docs)."""
import os
import re
import zipfile
from datetime import date

import pytest

from safety_eval.results_sheet import (ResultsData, build_results_edits,
                                       format_results_sheet,
                                       populate_results_sheet)
from safety_eval.xlsx_patch import (KEEP_VALUE, CellEdit, SheetPatcher,
                                    add_merge, clone_style, replace_merge,
                                    set_page_scale, set_row_height,
                                    sheet_files, verify_integrity)

HERE = os.path.dirname(__file__)
TEMPLATE = os.path.join(
    HERE, "..", "templates", "Intersection Evaluation Workbook - 2023-12-04.xlsx")
needs_template = pytest.mark.skipif(
    not os.path.exists(TEMPLATE), reason="template not present")

SHEET = "1 page results - 1 Target"


def _sheet_xml(path, sheet=SHEET):
    with zipfile.ZipFile(path) as z:
        return z.read(sheet_files(path)[sheet]).decode("utf-8")


# ---------------------------------------------------------------- primitives

def test_set_row_height_survives_customheight_attribute():
    xml = ('<row r="39" s="92" customFormat="1" ht="18" customHeight="1">'
           "<c r=\"A39\"/></row>")
    out = set_row_height(xml, 39, 15)
    assert 'ht="15"' in out and 'customHeight="1"' in out
    assert "customHeig " not in out          # ht= inside customHeight= bug
    assert 'customFormat="1"' in out


def test_add_and_replace_merge():
    xml = ('<mergeCells count="1"><mergeCell ref="C58:K65"/></mergeCells>')
    out = add_merge(xml, "H40:K40")
    assert '<mergeCell ref="H40:K40"/>' in out
    assert 'count="2"' in out
    assert add_merge(out, "H40:K40") == out          # idempotent
    out = replace_merge(out, "C58:K65", "C58:K66")
    assert '<mergeCell ref="C58:K66"/>' in out
    assert "C58:K65" not in out


def test_set_page_scale():
    xml = '<pageSetup scale="67" orientation="portrait"/>'
    assert 'scale="64"' in set_page_scale(xml, 64)
    xml = '<pageSetup orientation="portrait"/>'
    assert 'scale="61"' in set_page_scale(xml, 61)


def test_clone_style_appends_font_and_xf():
    styles = ('<styleSheet><fonts count="1"><font><sz val="11"/>'
              '<name val="Times New Roman"/></font></fonts>'
              '<cellXfs count="2">'
              '<xf numFmtId="0" fontId="0" borderId="5"/>'
              '<xf numFmtId="0" fontId="0" borderId="7">'
              '<alignment horizontal="center"/></xf>'
              "</cellXfs></styleSheet>")
    out, idx = clone_style(styles, 1, font_size=8, halign="left",
                           valign="center", wrap=True)
    assert idx == 2
    assert '<sz val="8"/>' in out and '<fonts count="2"' in out
    assert '<cellXfs count="3"' in out
    new_xf = re.findall(r"<xf\b[^>]*?/>|<xf\b[^>]*?>.*?</xf>", out, re.S)[-1]
    assert 'fontId="1"' in new_xf and 'borderId="7"' in new_xf
    assert ('horizontal="left"' in new_xf and 'vertical="center"' in new_xf
            and 'wrapText="1"' in new_xf)


def test_clone_style_regex_handles_selfclosing_runs():
    """A run of self-closing xfs must not swallow its neighbours."""
    styles = ('<styleSheet><fonts count="1"><font><sz val="11"/></font>'
              "</fonts><cellXfs count=\"3\">"
              '<xf numFmtId="0" fontId="0"/><xf numFmtId="0" fontId="0"/>'
              '<xf numFmtId="0" fontId="0"><alignment wrapText="1"/></xf>'
              "</cellXfs></styleSheet>")
    out, idx = clone_style(styles, 2, shrink=True)
    assert idx == 3
    assert 'shrinkToFit="1"' in out


def test_keep_value_edit_changes_style_only():
    xml = ('<sheetData><row r="38"><c r="H38" s="151" t="inlineStr">'
           "<is><t>label</t></is></c></row></sheetData>")
    p = SheetPatcher(xml)
    p.apply([CellEdit("H38", KEEP_VALUE, style="150")])
    assert 's="150"' in p.xml and "<t>label</t>" in p.xml


# ------------------------------------------------------------- format pass

@needs_template
def test_format_pass_moves_the_heading_and_completes_the_ai_row(tmp_path):
    data = ResultsData(
        countermeasures=("Convert intersection to All-Way STOP Control "
                         "(AWSC), including:\n   • On approaches, "
                         "signs\n      - Details of the work performed"),
        target_crashes="Frontal impact crashes.",
        items_for_discussion=["First bullet.", "Second bullet."],
        additional_info=[],
        prepared_date=date(2026, 8, 21),
        project_development={"start": date(2013, 6, 1),
                             "end": date(2018, 5, 31),
                             "counts": {"total": 19, "fatal": 0, "a": 1,
                                        "b": 7, "c": 6, "pdo": 5}},
    )
    out = str(tmp_path / "formatted.xlsx")
    populate_results_sheet(TEMPLATE, out, data)
    assert verify_integrity(TEMPLATE, out).ok
    xml = _sheet_xml(out)

    tpl_xml = _sheet_xml(TEMPLATE)
    old = re.search(r'<c r="H(\d+)"[^>]*t="s"><v>(\d+)</v></c>', tpl_xml)
    # the heading moved down one row, leaving the spacer empty
    hdr_rows = {}
    for m in re.finditer(r'<c r="H(\d+)"[^>]*>(?:<is><t[^>]*>([^<]*)</t>'
                         r"</is>)?", xml):
        if m.group(2) == "Map/Satellite Views":
            hdr_rows[int(m.group(1))] = m.group(2)
    assert len(hdr_rows) == 1
    row = next(iter(hdr_rows))
    assert f'<mergeCell ref="H{row}:K{row}"/>' in xml
    assert re.search(rf'<row r="{row}"[^>]*ht="18"', xml)
    assert re.search(rf'<row r="{row - 1}"[^>]*ht="15"', xml)

    # the last Additional Information row got the live percent formula
    last = row - 2
    assert re.search(rf'<c r="K{last}"[^>]*><f>IFERROR\(\(J{last}-I{last}\)'
                     rf"/I{last},", xml)

    # Project Development: real dates, helper counts, per-year formulas
    assert re.search(r'<c r="D47"[^>]*><v>41426</v></c>', xml)
    assert re.search(r'<c r="O57"[^>]*><v>19</v></c>', xml)
    assert "O57/ROUND(YEARFRAC($D$47,$D$48),2)" in xml
    assert "YEARFRAC(D47,D48,1)" in xml          # the Years text formula

    # prepared date as a serial
    assert re.search(r'<c r="I71"[^>]*><v>46255</v></c>', xml)


@needs_template
def test_format_pass_left_aligns_the_bullet_blocks(tmp_path):
    data = ResultsData(
        countermeasures="Line one\n   • bullet\n      - sub",
        target_crashes="List:\n• item",
    )
    out = str(tmp_path / "aligned.xlsx")
    populate_results_sheet(TEMPLATE, out, data)
    xml = _sheet_xml(out)
    with zipfile.ZipFile(out) as z:
        styles = z.read("xl/styles.xml").decode("utf-8")
    xfs = re.search(r"<cellXfs.*</cellXfs>", styles, re.S).group(0)
    xf_list = re.findall(r"<xf\b[^>]*?/>|<xf\b[^>]*?>.*?</xf>", xfs, re.S)

    def style_of(text_start):
        m = re.search(r'<c r="([A-Z]+\d+)" s="(\d+)" t="inlineStr">'
                      rf'<is><t[^>]*>{text_start}', xml)
        return xf_list[int(m.group(2))]

    cm = style_of("Line one")
    assert 'horizontal="left"' in cm and 'wrapText="1"' in cm
    tc = style_of("List:")
    assert 'horizontal="left"' in tc


@needs_template
def test_saved_scale_reads_the_page_setup(tmp_path):
    from safety_eval.report_pdf import saved_scale
    data = ResultsData(items_for_discussion=["One bullet."])
    out = str(tmp_path / "scaled.xlsx")
    populate_results_sheet(TEMPLATE, out, data)
    assert 55 <= saved_scale(out) <= 64


# ------------------------------------------------- native grid invariants

@needs_template
def test_row_heights_and_spacer_survive_a_long_items_block(tmp_path):
    """The engineer never stretches a row and never takes the blank row
    above 'Data Prepared For:'; a long block grows the cell by whole rows."""
    # 14 wrapped lines, like a real long discussion: too tall for the
    # native 8-row cell at any size the engineer uses, so the cell grows
    long_items = (["• " + ("word " * 44)] * 5) + (["• " + ("word " * 15)] * 4)
    data = ResultsData(items_for_discussion=long_items,
                       countermeasures="Convert intersection to AWSC.")
    out = str(tmp_path / "long.xlsx")
    notes = populate_results_sheet(TEMPLATE, out, data)
    assert verify_integrity(TEMPLATE, out).ok
    xml = _sheet_xml(out)
    tpl = _sheet_xml(TEMPLATE)

    def heights(x):
        out = {}
        for r, attrs in re.findall(r'<row r="(\d+)"([^>]*)>', x):
            m = re.search(r'ht="([\d.]+)"', attrs)
            out[int(r)] = float(m.group(1)) if m else 15.0
        return out

    hb, ha = heights(tpl), heights(xml)
    assert {h for r, h in ha.items() if 56 <= r <= 70} <= {15.0, 18.0}
    assert all(ha[r] == 15.0 for r in range(58, 66))

    items = [m for m in re.findall(r'<mergeCell ref="([^"]+)"/>', xml)
             if m.startswith("C58:")]
    assert items, "Items merge missing"
    last = int(re.search(r":([A-Z]+)(\d+)", items[0]).group(2))
    footer_row = None
    for m in re.finditer(r'<c r="C(\d+)"[^>]*t="inlineStr"[^>]*>'
                         r'<is><t[^>]*>([^<]*)</t>', xml):
        if m.group(2).startswith("Data Prepared For"):
            footer_row = int(m.group(1))
    if footer_row:                      # blank spacer row is mandatory
        assert footer_row - last >= 2
    assert any("grown by" in n for n in notes)


@needs_template
def test_short_items_block_leaves_the_template_untouched(tmp_path):
    data = ResultsData(items_for_discussion=["• One short bullet."])
    out = str(tmp_path / "short.xlsx")
    notes = populate_results_sheet(TEMPLATE, out, data)
    xml, tpl = _sheet_xml(out), _sheet_xml(TEMPLATE)
    assert '<mergeCell ref="C58:K65"/>' in xml          # native merge kept
    assert not any("grown" in n for n in notes)
    for r in range(56, 72):                            # native heights kept
        a = re.search(rf'<row r="{r}"[^>]*ht="([\d.]+)"', xml)
        b = re.search(rf'<row r="{r}"[^>]*ht="([\d.]+)"', tpl)
        assert (a and b) and a.group(1) == b.group(1)


@needs_template
def test_items_font_is_sized_down_to_fit_not_the_cell_up(tmp_path):
    """Two blocks of different length land at different font sizes in the
    same cell."""
    import zipfile

    def items_size(path):
        x = _sheet_xml(path)
        m = re.search(r'<c r="C58"(?: s="(\d+)")?', x)
        with zipfile.ZipFile(path) as z:
            st = z.read("xl/styles.xml").decode()
        xfs = re.findall(r"<xf\b[^>]*?/>|<xf\b[^>]*?>.*?</xf>",
                         re.search(r"<cellXfs.*</cellXfs>", st, re.S).group(0),
                         re.S)
        fid = int(re.search(r'fontId="(\d+)"', xfs[int(m.group(1))]).group(1))
        fonts = re.findall(r"<font>.*?</font>|<font/>",
                           re.search(r"<fonts.*</fonts>", st, re.S).group(0),
                           re.S)
        return float(re.search(r'<sz val="([\d.]+)"', fonts[fid]).group(1))

    short = str(tmp_path / "a.xlsx")
    populate_results_sheet(TEMPLATE, short,
                           ResultsData(items_for_discussion=["• Short."]))
    dense = str(tmp_path / "b.xlsx")
    populate_results_sheet(
        TEMPLATE, dense,
        ResultsData(items_for_discussion=["• " + "word " * 45
                                          for _ in range(6)]))
    assert items_size(short) == 11.0
    assert items_size(dense) < items_size(short)


@needs_template
def test_grown_items_cell_extends_the_saved_print_area(tmp_path):
    from safety_eval.report_pdf import saved_print_range
    long_items = (["• " + ("word " * 44)] * 5) + \
        (["• " + ("word " * 15)] * 4)
    out = str(tmp_path / "grown.xlsx")
    populate_results_sheet(TEMPLATE, out,
                           ResultsData(items_for_discussion=long_items))
    grown = saved_print_range(out)
    native = saved_print_range(TEMPLATE)
    assert int(re.search(r"(\d+)$", grown).group(1)) > \
        int(re.search(r"(\d+)$", native).group(1))


@needs_template
def test_print_area_ends_on_the_box_bottom_border_row(tmp_path):
    """The template ships Print_Area one row short of the report box's
    heavy bottom border (B2:L71 vs border row 72); the completed
    workbooks hand-correct it so the box prints closed."""
    from safety_eval.report_pdf import saved_print_range
    from safety_eval.results_sheet import _box_bottom_row

    with zipfile.ZipFile(TEMPLATE) as z:
        xml = z.read(sheet_files(TEMPLATE)[SHEET]).decode()
        styles = z.read("xl/styles.xml").decode()
    assert _box_bottom_row(xml, styles) == 72

    out = str(tmp_path / "plain.xlsx")
    populate_results_sheet(TEMPLATE, out,
                           ResultsData(items_for_discussion=["• Short."]))
    assert saved_print_range(out).endswith("72")


@needs_template
def test_grown_page_keeps_the_template_margins(tmp_path):
    """Row-inserted pages keep the template's 0.25/0.5in margins and
    center-on-page flags -- the SS-6001P / SS-6010AG convention from
    the corpus scan -- so every Web PDF prints with the same look."""
    long_items = (["• " + ("word " * 44)] * 5) + \
        (["• " + ("word " * 15)] * 4)
    out = str(tmp_path / "grown.xlsx")
    populate_results_sheet(TEMPLATE, out,
                           ResultsData(items_for_discussion=long_items))
    xml = _sheet_xml(out)
    m = re.search(r"<pageMargins [^/]*/>", xml)
    assert 'left="0.25"' in m.group(0) and 'top="0.5"' in m.group(0)
    po = re.search(r"<printOptions[^/]*/>", xml)
    assert 'horizontalCentered="1"' in po.group(0)
    assert 'verticalCentered="1"' in po.group(0)
