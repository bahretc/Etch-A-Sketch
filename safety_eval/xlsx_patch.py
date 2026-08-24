"""Template-preserving Excel writes per docs/06 (MANDATORY rules).

NCDOT deliverable workbooks contain drawings, images, merged cells, and defined
styles that openpyxl resave corrupts.  Writes therefore happen by direct XML
manipulation inside the zip, on a copy of the pristine original:

* only the targeted ``xl/worksheets/sheetN.xml`` parts are rewritten;
* every other member (drawings, media, charts, styles, rels) is copied
  byte-for-byte;
* text is written as inline strings (consistently), so sharedStrings.xml is
  never touched;
* ``fullCalcOnLoad`` is set so Excel recalculates formula caches on open, and
  :func:`recalc` offers the single LibreOffice headless pass from docs/06;
* :func:`verify_integrity` is the acceptance gate: drawings and media must be
  byte-identical between template and output.
"""
from __future__ import annotations

import hashlib
import os
import re
import shutil
import subprocess
import tempfile
import zipfile
from dataclasses import dataclass, field
from datetime import date, datetime
from xml.sax.saxutils import escape

_EXCEL_EPOCH = date(1899, 12, 30)

#: Sentinel value for a style-only CellEdit: the cell's existing content
#: (value or formula) is kept and only the style index changes.
KEEP_VALUE = object()


def excel_serial(d: date | datetime) -> int:
    """Excel 1900 date-system serial for a date."""
    if isinstance(d, datetime):
        d = d.date()
    return (d - _EXCEL_EPOCH).days


@dataclass
class CellEdit:
    """One cell write: numeric, text (inline string), or blank (clear value).

    ``formula`` writes a live formula (rule 4: reviewers trace numbers to
    formulas); the cached value is left empty and fullCalcOnLoad plus the
    :func:`recalc` pass fill it in. ``style`` overrides the preserved style
    index, for cells whose template formatting is wrong for the content
    (e.g. the engineer left-aligns bulleted blocks the template centers).
    """
    ref: str                       # e.g. "A4"
    value: object = None           # int/float -> number; str -> inline string;
                                   # date -> serial number; None -> clear
    formula: str | None = None     # live formula text (no leading '=')
    style: str | None = None       # style index override (s= attribute)


def _col_of(ref: str) -> str:
    return re.match(r"([A-Z]+)", ref).group(1)


def _row_of(ref: str) -> int:
    return int(re.search(r"(\d+)$", ref).group(1))


def _col_index(col: str) -> int:
    n = 0
    for ch in col:
        n = n * 26 + (ord(ch) - 64)
    return n


def sheet_files(template: str) -> dict[str, str]:
    """Map sheet name -> zip member path (e.g. 'xl/worksheets/sheet7.xml')."""
    with zipfile.ZipFile(template) as z:
        wb = z.read("xl/workbook.xml").decode("utf-8")
        rels = z.read("xl/_rels/workbook.xml.rels").decode("utf-8")
    # attribute order varies by writer (openpyxl puts Target before Id)
    rid_to_target: dict[str, str] = {}
    for rel in re.findall(r"<Relationship\b[^>]*>", rels):
        rid = re.search(r'\bId="(rId\d+)"', rel)
        target = re.search(r'\bTarget="([^"]+)"', rel)
        if rid and target:
            rid_to_target[rid.group(1)] = target.group(1)
    out: dict[str, str] = {}
    # attributes can precede name= (openpyxl writes xmlns:r first)
    for name, rid in re.findall(
            r'<sheet\b[^>]*?name="([^"]+)"[^>]*?r:id="(rId\d+)"', wb):
        target = rid_to_target[rid]
        if target.startswith("/"):
            # absolute package path (openpyxl writes /xl/worksheets/sheetN.xml)
            target = target.lstrip("/")
        elif not target.startswith("xl/"):
            target = "xl/" + target
        out[name.replace("&amp;", "&")] = target
    return out


def _cell_xml(ref: str, value, style: str | None,
              formula: str | None = None) -> str:
    s_attr = f' s="{style}"' if style else ""
    if formula is not None:
        return f'<c r="{ref}"{s_attr}><f>{escape(formula)}</f></c>'
    if value is None:
        return f'<c r="{ref}"{s_attr}/>'
    if isinstance(value, (date, datetime)):
        return f'<c r="{ref}"{s_attr}><v>{excel_serial(value)}</v></c>'
    if isinstance(value, bool):
        return f'<c r="{ref}"{s_attr} t="b"><v>{int(value)}</v></c>'
    if isinstance(value, (int, float)):
        v = repr(value) if isinstance(value, float) else str(value)
        return f'<c r="{ref}"{s_attr}><v>{v}</v></c>'
    text = escape(str(value))
    raw = str(value)
    space = (' xml:space="preserve"'
             if raw != raw.strip() or "\n" in raw else "")
    return f'<c r="{ref}"{s_attr} t="inlineStr"><is><t{space}>{text}</t></is></c>'


class SheetPatcher:
    """Applies :class:`CellEdit` lists to one worksheet's XML.

    Existing cells keep their style index (``s=``); brand-new cells borrow the
    style of the same column in ``style_row`` (default: the first edited row's
    existing template formatting, typically data row 4).
    """

    def __init__(self, xml: str, style_row: int | None = None):
        self.xml = xml
        self.style_row = style_row
        self._style_cache: dict[str, str | None] = {}

    def _existing_cell(self, ref: str) -> re.Match | None:
        return re.search(
            rf'<c r="{ref}"(?:[^>/]*)(?:/>|>.*?</c>)', self.xml, re.S)

    def _style_of(self, ref: str) -> str | None:
        m = self._existing_cell(ref)
        if m:
            sm = re.search(r'\bs="(\d+)"', m.group(0))
            if sm:
                return sm.group(1)
        col = _col_of(ref)
        if col in self._style_cache:
            return self._style_cache[col]
        style = None
        if self.style_row:
            m = self._existing_cell(f"{col}{self.style_row}")
            if m:
                sm = re.search(r'\bs="(\d+)"', m.group(0))
                style = sm.group(1) if sm else None
        self._style_cache[col] = style
        return style

    def apply(self, edits: list[CellEdit]) -> None:
        by_row: dict[int, list[CellEdit]] = {}
        for e in edits:
            by_row.setdefault(_row_of(e.ref), []).append(e)
        for row, row_edits in sorted(by_row.items()):
            self._apply_row(row, row_edits)

    def _apply_row(self, row: int, edits: list[CellEdit]) -> None:
        for e in edits:
            if e.value is KEEP_VALUE:
                style = e.style or self._style_of(e.ref)
                m = self._existing_cell(e.ref)
                if m:
                    cell = m.group(0)
                    if re.search(r'\bs="\d+"', cell):
                        cell = re.sub(r'\bs="\d+"', f's="{style}"', cell, 1)
                    else:
                        cell = cell.replace(f'<c r="{e.ref}"',
                                            f'<c r="{e.ref}" s="{style}"', 1)
                    self.xml = self.xml[: m.start()] + cell + self.xml[m.end():]
                    continue
                e = CellEdit(e.ref, None, style=e.style)   # absent: bare cell
            new = _cell_xml(e.ref, e.value, e.style or self._style_of(e.ref),
                            e.formula)
            m = self._existing_cell(e.ref)
            if m:
                self.xml = self.xml[: m.start()] + new + self.xml[m.end():]
                continue
            # insert into the row in column order (creating the row if needed)
            rm = re.search(rf'(<row r="{row}"[^>]*)(/>|>)', self.xml)
            if rm is None:
                # create the row before the first row with a higher number,
                # or before </sheetData>
                anchor = None
                for m2 in re.finditer(r'<row r="(\d+)"', self.xml):
                    if int(m2.group(1)) > row:
                        anchor = m2.start()
                        break
                if anchor is None:
                    anchor = self.xml.index("</sheetData>")
                self.xml = (self.xml[:anchor]
                            + f'<row r="{row}">{new}</row>'
                            + self.xml[anchor:])
                continue
            if rm.group(2) == "/>":
                # self-closing row -> expand
                open_tag = rm.group(1) + ">"
                self.xml = (self.xml[: rm.start()] + open_tag + new + "</row>"
                            + self.xml[rm.end():])
                continue
            # find insertion point among existing cells of this row
            row_end = self.xml.index("</row>", rm.end())
            row_body = self.xml[rm.end(): row_end]
            insert_at = row_end
            for cm in re.finditer(r'<c r="([A-Z]+)(\d+)"', row_body):
                if _col_index(cm.group(1)) > _col_index(_col_of(e.ref)):
                    insert_at = rm.end() + cm.start()
                    break
            self.xml = self.xml[:insert_at] + new + self.xml[insert_at:]


def set_row_height(xml: str, row: int, height: float) -> str:
    """Set one row's height (customHeight) in worksheet XML."""
    m = re.search(rf'<row r="{row}"([^>]*?)(/?)>', xml)
    if m is None:
        raise KeyError(f"row {row} not present in sheet XML")
    attrs = m.group(1)
    # \b keeps customHeight="1" intact (its tail would match ht="1")
    attrs = re.sub(r'\s*\bht="[\d.]+"', "", attrs)
    attrs = re.sub(r'\s*\bcustomHeight="1"', "", attrs)
    ht = f"{height:g}"
    new = f'<row r="{row}"{attrs} ht="{ht}" customHeight="1"{m.group(2)}>'
    return xml[: m.start()] + new + xml[m.end():]


def add_merge(xml: str, ref: str) -> str:
    """Add one merged range to worksheet XML (idempotent)."""
    if f'<mergeCell ref="{ref}"/>' in xml:
        return xml
    m = re.search(r'<mergeCells count="(\d+)">', xml)
    if m is None:
        raise KeyError("sheet has no mergeCells block")
    xml = (xml[: m.start()] + f'<mergeCells count="{int(m.group(1)) + 1}">'
           + xml[m.end():])
    return xml.replace("</mergeCells>",
                       f'<mergeCell ref="{ref}"/></mergeCells>', 1)


def insert_rows(xml: str, at: int, count: int) -> str:
    """Insert ``count`` blank rows before row ``at``, shifting what follows.

    Used only where the engineer himself grows a block: he inserts whole
    rows rather than changing row heights, so the printed grid keeps its
    15pt pitch and the blank row above the footer survives. Rows at or
    below ``at`` move down together with their merges, their conditional
    formatting ranges and the sheet dimension.

    Refuses when the shifted region holds a formula, whose row
    references would have to be rewritten as well.
    """
    if count <= 0:
        return xml

    row_re = re.compile(r'<row r="(\d+)"([^>]*?)(/>|>.*?</row>)', re.S)
    ref_re = re.compile(r'(\$?[A-Z]{1,3}\$?)(\d+)')

    def bump(match: re.Match) -> str:
        row = int(match.group(2))
        return (f"{match.group(1)}{row + count}" if row >= at
                else match.group(0))

    def shift_row(m: re.Match) -> str:
        row, attrs, body = int(m.group(1)), m.group(2), m.group(3)
        if row < at:
            return m.group(0)
        if re.search(r"<f[ />]", body):
            raise ValueError(
                f"cannot insert rows at {at}: row {row} holds a formula "
                "whose references would have to be rewritten")
        body = re.sub(r'(<c r="[A-Z]{1,3})(\d+)"',
                      lambda c: f'{c.group(1)}{int(c.group(2)) + count}"',
                      body)
        return f'<row r="{row + count}"{attrs}{body}'

    xml = row_re.sub(shift_row, xml)

    def shift_refs(text: str) -> str:
        return " ".join(ref_re.sub(bump, part) for part in text.split())

    xml = re.sub(r'<mergeCell ref="([^"]+)"/>',
                 lambda m: f'<mergeCell ref="{shift_refs(m.group(1))}"/>', xml)
    xml = re.sub(r'<conditionalFormatting sqref="([^"]+)"',
                 lambda m: f'<conditionalFormatting sqref="'
                           f'{shift_refs(m.group(1))}"', xml)
    xml = re.sub(r'<dimension ref="([^"]+)"/>',
                 lambda m: f'<dimension ref="{shift_refs(m.group(1))}"/>',
                 xml, count=1)
    return xml


def replace_merge(xml: str, old_ref: str, new_ref: str) -> str:
    """Change one merged range (e.g. extend the Items cell downward)."""
    tag = f'<mergeCell ref="{old_ref}"/>'
    if tag not in xml:
        raise KeyError(f"merge {old_ref} not present")
    return xml.replace(tag, f'<mergeCell ref="{new_ref}"/>', 1)


def set_print_area(workbook_xml: str, sheet: str, ref: str) -> str:
    """Point the sheet's saved Print_Area defined name at ``ref``."""
    pattern = re.compile(
        r"(<definedName name=\"_xlnm.Print_Area\"[^>]*>')"
        + re.escape(sheet) + r"('!)([^<]+)(</definedName>)")
    if not pattern.search(workbook_xml):
        raise KeyError(f"no Print_Area defined name for {sheet!r}")
    return pattern.sub(lambda m: m.group(1) + sheet + m.group(2) + ref
                       + m.group(4), workbook_xml, count=1)


def set_page_scale(xml: str, scale: int) -> str:
    """Set the saved print scale (pageSetup scale=...)."""
    m = re.search(r"<pageSetup [^>]*/>", xml)
    if m is None:
        raise KeyError("sheet has no pageSetup")
    tag = m.group(0)
    if 'scale="' in tag:
        tag = re.sub(r'scale="\d+"', f'scale="{scale}"', tag)
    else:
        tag = tag.replace("<pageSetup ", f'<pageSetup scale="{scale}" ', 1)
    return xml[: m.start()] + tag + xml[m.end():]


def clone_style(styles_xml: str, base_xf: int, *, font_size: float | None = None,
                halign: str | None = None, valign: str | None = None,
                wrap: bool | None = None,
                shrink: bool | None = None) -> tuple[str, int]:
    """Append a variant of cellXfs[base_xf] and return (new xml, new index).

    The variant keeps the base's border, fill and number format; only the
    font size (a same-family font is appended when none matches) and the
    alignment change. This is how the engineer's one-off cell formats
    (left-aligned bullet blocks, shrunken text) are reproduced without
    touching any existing style index.
    """
    xfs_m = re.search(r"<cellXfs count=\"(\d+)\">(.*)</cellXfs>",
                     styles_xml, re.S)
    # self-closing branch first: '>.*?</xf>' on a self-closing xf would
    # otherwise swallow every following xf up to the next paired closer
    xf_list = re.findall(r"<xf\b[^>]*?/>|<xf\b[^>]*?>.*?</xf>",
                         xfs_m.group(2), re.S)
    xf = xf_list[base_xf]

    if font_size is not None:
        base_font = int(re.search(r'fontId="(\d+)"', xf).group(1))
        fonts_m = re.search(r"<fonts count=\"(\d+)\"[^>]*>(.*?)</fonts>",
                           styles_xml, re.S)
        font_list = re.findall(r"<font>.*?</font>|<font/>", fonts_m.group(2),
                               re.S)
        fxml = font_list[base_font]
        new_font = re.sub(r'<sz val="[\d.]+"/>', f'<sz val="{font_size:g}"/>',
                          fxml)
        try:
            fid = font_list.index(new_font)
        except ValueError:
            fid = len(font_list)
            styles_xml = styles_xml.replace(
                fonts_m.group(0),
                fonts_m.group(0).replace(
                    "</fonts>", new_font + "</fonts>").replace(
                    f'<fonts count="{fonts_m.group(1)}"',
                    f'<fonts count="{int(fonts_m.group(1)) + 1}"', 1), 1)
        xf = re.sub(r'fontId="\d+"', f'fontId="{fid}"', xf)
        if 'applyFont=' not in xf:
            xf = xf.replace("<xf ", '<xf applyFont="1" ', 1)

    if (halign is not None or valign is not None or wrap is not None
            or shrink is not None):
        a = {}
        am = re.search(r"<alignment([^/]*)/>", xf)
        if am:
            a = dict(re.findall(r'(\w+)="([^"]*)"', am.group(1)))
        if halign is not None:
            a["horizontal"] = halign
        if valign is not None:
            a["vertical"] = valign
        if wrap is not None:
            a["wrapText"] = "1" if wrap else "0"
        if shrink is not None:
            a["shrinkToFit"] = "1" if shrink else "0"
        tag = "<alignment " + " ".join(
            f'{k}="{v}"' for k, v in a.items()) + "/>"
        if am:
            xf = xf[: am.start()] + tag + xf[am.end():]
        elif xf.endswith("/>"):
            xf = xf[:-2] + ">" + tag + "</xf>"
        else:
            xf = xf.replace("</xf>", tag + "</xf>", 1)
        if 'applyAlignment=' not in xf:
            xf = xf.replace("<xf ", '<xf applyAlignment="1" ', 1)

    # re-find cellXfs (the fonts block above may have shifted offsets)
    xfs_m = re.search(r"<cellXfs count=\"(\d+)\">(.*)</cellXfs>",
                     styles_xml, re.S)
    new_index = len(xf_list)
    styles_xml = (styles_xml[: xfs_m.start()]
                  + f'<cellXfs count="{int(xfs_m.group(1)) + 1}">'
                  + xfs_m.group(2) + xf + "</cellXfs>"
                  + styles_xml[xfs_m.end():])
    return styles_xml, new_index


def xlsx_patch(path_in: str, path_out: str,
               edits: dict[str, list[CellEdit]],
               style_rows: dict[str, int] | None = None,
               full_calc_on_load: bool = True,
               row_heights: dict[str, dict[int, float]] | None = None,
               add_merges: dict[str, list[str]] | None = None,
               swap_merges: dict[str, dict[str, str]] | None = None,
               page_scale: dict[str, int] | None = None,
               grow_rows: dict[str, tuple[int, int]] | None = None,
               print_area: dict[str, str] | None = None,
               replace_members: dict[str, bytes] | None = None) -> None:
    """Apply per-sheet cell edits to a copy of ``path_in`` written at ``path_out``.

    ``edits`` maps sheet NAME -> list of CellEdit.  Every zip member that is not
    an edited worksheet (or workbook.xml when ``full_calc_on_load``) is copied
    byte-for-byte, preserving drawings, media, charts, styles, and rels.
    ``row_heights``, ``add_merges`` and ``page_scale`` apply the matching
    sheet-level adjustments per sheet name; ``replace_members`` swaps whole
    zip members (e.g. a styles.xml extended by :func:`clone_style`).
    """
    style_rows = style_rows or {}
    row_heights = row_heights or {}
    add_merges = add_merges or {}
    swap_merges = swap_merges or {}
    page_scale = page_scale or {}
    grow_rows = grow_rows or {}
    print_area = print_area or {}
    replace_members = replace_members or {}
    name_to_file = sheet_files(path_in)
    touched = (set(edits) | set(row_heights) | set(add_merges)
               | set(swap_merges) | set(page_scale) | set(grow_rows))
    unknown = touched - set(name_to_file)
    if unknown:
        raise KeyError(f"Sheets not in template: {sorted(unknown)}")
    file_ops = {name_to_file[n]: n for n in touched}

    with zipfile.ZipFile(path_in) as zin:
        members = zin.infolist()
        with zipfile.ZipFile(path_out, "w", zipfile.ZIP_DEFLATED) as zout:
            for info in members:
                data = zin.read(info.filename)
                if info.filename in replace_members:
                    data = replace_members[info.filename]
                if info.filename in file_ops:
                    sheet_name = file_ops[info.filename]
                    xml = data.decode("utf-8")
                    if sheet_name in grow_rows:
                        # rows first: everything below is renumbered, so
                        # edits and merges are given in final coordinates
                        at, n = grow_rows[sheet_name]
                        xml = insert_rows(xml, at, n)
                    sheet_edits = edits.get(sheet_name)
                    if sheet_edits:
                        patcher = SheetPatcher(
                            xml, style_row=style_rows.get(sheet_name))
                        patcher.apply(sheet_edits)
                        xml = patcher.xml
                    for row, ht in (row_heights.get(sheet_name) or {}).items():
                        xml = set_row_height(xml, row, ht)
                    for ref in add_merges.get(sheet_name) or []:
                        xml = add_merge(xml, ref)
                    for old, new in (swap_merges.get(sheet_name)
                                     or {}).items():
                        xml = replace_merge(xml, old, new)
                    if sheet_name in page_scale:
                        xml = set_page_scale(xml, page_scale[sheet_name])
                    data = xml.encode("utf-8")
                elif info.filename == "xl/workbook.xml" and (
                        full_calc_on_load or print_area):
                    text = data.decode("utf-8")
                    for sname, ref in print_area.items():
                        text = set_print_area(text, sname, ref)
                    if not full_calc_on_load:
                        pass
                    elif "fullCalcOnLoad" in text:
                        pass                      # already set (idempotent)
                    elif "<calcPr" in text:
                        text = re.sub(r"<calcPr ",
                                      '<calcPr fullCalcOnLoad="1" ', text, 1)
                    else:
                        text = text.replace(
                            "</workbook>",
                            '<calcPr fullCalcOnLoad="1"/></workbook>')
                    data = text.encode("utf-8")
                zout.writestr(info, data)


# LibreOffice profile seed: force full recalculation of OOXML files on load
# (OOXMLRecalcMode 0 = always). Without this, LO round-trips the file's STALE
# formula caches and the recalc pass silently does nothing.
_RECALC_XCU = """<?xml version="1.0" encoding="UTF-8"?>
<oor:items xmlns:oor="http://openoffice.org/2001/registry" \
xmlns:xs="http://www.w3.org/2001/XMLSchema">
 <item oor:path="/org.openoffice.Office.Calc/Formula/Load">\
<prop oor:name="OOXMLRecalcMode" oor:op="fuse"><value>0</value></prop></item>
</oor:items>
"""


def replace_sheet_rows(path_in: str, path_out: str, sheet: str,
                       rows_xml: str, from_row: int = 2,
                       full_calc_on_load: bool = True) -> None:
    """Replace a sheet's rows from ``from_row`` down with pre-rendered row XML.

    For bulk data sheets (thousands of rows) where per-cell patching would be
    quadratic. Rows below ``from_row`` are dropped and ``rows_xml`` is
    appended; rows above are preserved. Every other zip member is copied
    byte-for-byte, so the docs/06 integrity gate still applies.
    """
    name_to_file = sheet_files(path_in)
    if sheet not in name_to_file:
        raise KeyError(f"Sheet not in template: {sheet!r}")
    target = name_to_file[sheet]
    with zipfile.ZipFile(path_in) as zin:
        members = zin.infolist()
        with zipfile.ZipFile(path_out, "w", zipfile.ZIP_DEFLATED) as zout:
            for info in members:
                data = zin.read(info.filename)
                if info.filename == target:
                    xml = data.decode("utf-8")
                    # expand a self-closing (empty) sheetData first
                    xml = re.sub(r"<sheetData\s*/>",
                                 "<sheetData></sheetData>", xml, 1)
                    sd_start = xml.index("<sheetData")
                    sd_open_end = xml.index(">", sd_start) + 1
                    sd_close = xml.index("</sheetData>")
                    body = xml[sd_open_end:sd_close]
                    kept = []
                    for rm in re.finditer(r'<row r="(\d+)"[^>]*(?:/>|>.*?</row>)',
                                          body, re.S):
                        if int(rm.group(1)) < from_row:
                            kept.append(rm.group(0))
                    xml = (xml[:sd_open_end] + "".join(kept) + rows_xml
                           + xml[sd_close:])
                    # drop stale dimension (it may understate the new extent)
                    xml = re.sub(r'<dimension ref="[^"]*"/>', "", xml, 1)
                    data = xml.encode("utf-8")
                elif info.filename == "xl/workbook.xml" and full_calc_on_load:
                    text = data.decode("utf-8")
                    if "fullCalcOnLoad" not in text and "<calcPr" in text:
                        text = re.sub(r"<calcPr ",
                                      '<calcPr fullCalcOnLoad="1" ', text, 1)
                    data = text.encode("utf-8")
                zout.writestr(info, data)


def render_row(row: int, cells: dict[str, object],
               styles: dict[str, str] | None = None) -> str:
    """Render one ``<row>`` element; ``cells`` maps column letter -> value."""
    parts = []
    for col in sorted(cells, key=_col_index):
        value = cells[col]
        if value is None:
            continue
        style = (styles or {}).get(col)
        parts.append(_cell_xml(f"{col}{row}", value, style))
    return f'<row r="{row}">' + "".join(parts) + "</row>"


def sheet_row_styles(template: str, sheet: str, row: int) -> dict[str, str]:
    """Column letter -> style index for an existing template row (to inherit
    formatting when bulk-writing rows)."""
    name_to_file = sheet_files(template)
    with zipfile.ZipFile(template) as z:
        xml = z.read(name_to_file[sheet]).decode("utf-8")
    m = re.search(rf'<row r="{row}"[^>]*>(.*?)</row>', xml, re.S)
    if not m:
        return {}
    out: dict[str, str] = {}
    for cm in re.finditer(r'<c r="([A-Z]+)\d+"([^>]*)>', m.group(1)):
        sm = re.search(r'\bs="(\d+)"', cm.group(2))
        if sm:
            out[cm.group(1)] = sm.group(1)
    return out


def _lo_convert(path: str, timeout: int = 180) -> str | None:
    """Round-trip ``path`` through LibreOffice headless with recalc-on-load
    forced; returns the temp output path (caller owns the containing temp dir)
    or None on failure."""
    soffice = shutil.which("soffice") or shutil.which("libreoffice")
    if not soffice:
        return None
    tmp = tempfile.mkdtemp(prefix="recalc-")
    profile = os.path.join(tmp, "profile")
    outdir = os.path.join(tmp, "out")
    os.makedirs(outdir)
    os.makedirs(os.path.join(profile, "user"))
    with open(os.path.join(profile, "user", "registrymodifications.xcu"),
              "w") as fh:
        fh.write(_RECALC_XCU)
    try:
        subprocess.run(
            [soffice, "--headless", "--norestore",
             f"-env:UserInstallation=file://{profile}",
             "--convert-to", "xlsx", "--outdir", outdir, path],
            check=True, capture_output=True, timeout=timeout)
    except (subprocess.CalledProcessError, subprocess.TimeoutExpired):
        shutil.rmtree(tmp, ignore_errors=True)
        return None
    produced = [f for f in os.listdir(outdir) if f.endswith(".xlsx")]
    if not produced:
        shutil.rmtree(tmp, ignore_errors=True)
        return None
    return os.path.join(outdir, produced[0])


_CELL_RE = re.compile(
    r'<c r="([A-Z]+\d+)"((?:\s+[\w:]+="[^"]*")*)\s*(?:/>|>(.*?)</c>)', re.S)


def _cache_map(sheet_xml: str) -> dict[str, tuple[str | None, str | None]]:
    """ref -> (t attribute, inner <v> XML) for every cell in a sheet."""
    out: dict[str, tuple[str | None, str | None]] = {}
    for m in _CELL_RE.finditer(sheet_xml):
        ref, attrs, body = m.group(1), m.group(2) or "", m.group(3)
        tm = re.search(r'\bt="([^"]+)"', attrs)
        vm = re.search(r"<v>(.*?)</v>", body, re.S) if body else None
        out[ref] = (tm.group(1) if tm else None, vm.group(1) if vm else None)
    return out


def recalc(path: str, timeout: int = 180) -> bool:
    """One LibreOffice recalc pass that PRESERVES the patched file (docs/06).

    A naive ``--convert-to xlsx`` round-trip rewrites drawings XML and fails
    the byte-identical acceptance gate, so this is the "equivalent recalc
    script" variant: LibreOffice recomputes in a throwaway copy, and only the
    recalculated formula caches (``<v>`` and the cached-type ``t`` attribute)
    are transplanted back into the patched file's formula cells.  Drawings,
    media, styles, and rels remain exactly as :func:`xlsx_patch` wrote them.
    """
    converted = _lo_convert(path, timeout=timeout)
    if converted is None:
        return False
    try:
        ours = sheet_files(path)
        theirs = sheet_files(converted)
        with zipfile.ZipFile(converted) as zlo:
            lo_caches = {
                name: _cache_map(zlo.read(theirs[name]).decode("utf-8"))
                for name in ours if name in theirs
            }

        with zipfile.ZipFile(path) as zin:
            members = zin.infolist()
            payload = {i.filename: zin.read(i.filename) for i in members}

        file_of = {v: k for k, v in ours.items()}
        for fname, data in list(payload.items()):
            sheet_name = file_of.get(fname)
            if sheet_name is None or sheet_name not in lo_caches:
                continue
            caches = lo_caches[sheet_name]
            xml = data.decode("utf-8")

            def _refresh(m: re.Match) -> str:
                ref, attrs, body = m.group(1), m.group(2) or "", m.group(3)
                if not body or "<f" not in body:
                    return m.group(0)          # not a formula cell
                if ref not in caches:
                    return m.group(0)
                t_new, v_new = caches[ref]
                attrs_wo_t = re.sub(r'\s+t="[^"]*"', "", attrs)
                t_attr = f' t="{t_new}"' if t_new else ""
                f_part = re.search(r"<f\b.*?(?:/>|</f>)", body, re.S).group(0)
                v_part = f"<v>{v_new}</v>" if v_new is not None else ""
                return f'<c r="{ref}"{attrs_wo_t}{t_attr}>{f_part}{v_part}</c>'

            payload[fname] = _CELL_RE.sub(_refresh, xml).encode("utf-8")

        tmp_out = path + ".recalc.tmp"
        with zipfile.ZipFile(tmp_out, "w", zipfile.ZIP_DEFLATED) as zout:
            for info in members:
                zout.writestr(info, payload[info.filename])
        os.replace(tmp_out, path)
        return True
    finally:
        # temp dir is two levels above the produced file (mkdtemp/out/file)
        shutil.rmtree(os.path.dirname(os.path.dirname(converted)),
                      ignore_errors=True)


@dataclass
class IntegrityReport:
    ok: bool
    problems: list[str] = field(default_factory=list)
    checked_members: int = 0


def verify_integrity(original: str, output: str) -> IntegrityReport:
    """Acceptance gate per docs/06: drawings/media byte-identical, inventory equal."""
    rep = IntegrityReport(ok=True)

    def _load(path):
        with zipfile.ZipFile(path) as z:
            names = set(z.namelist())
            hashes = {n: hashlib.sha256(z.read(n)).hexdigest()
                      for n in names
                      if n.startswith(("xl/drawings/", "xl/media/",
                                       "xl/charts/"))}
            wb = z.read("xl/workbook.xml").decode("utf-8")
        sheets = re.findall(r"<sheet name=\"([^\"]+)\"", wb)
        defined = re.findall(r"<definedName name=\"([^\"]+)\"", wb)
        return names, hashes, sheets, defined

    names_a, hash_a, sheets_a, defined_a = _load(original)
    names_b, hash_b, sheets_b, defined_b = _load(output)
    rep.checked_members = len(hash_a)

    if set(hash_a) != set(hash_b):
        rep.ok = False
        rep.problems.append(
            f"drawings/media inventory differs: {sorted(set(hash_a) ^ set(hash_b))}")
    for n in sorted(set(hash_a) & set(hash_b)):
        if hash_a[n] != hash_b[n]:
            rep.ok = False
            rep.problems.append(f"byte mismatch: {n}")
    if sheets_a != sheets_b:
        rep.ok = False
        rep.problems.append(f"sheet list changed: {sheets_a} -> {sheets_b}")
    if defined_a != defined_b:
        rep.ok = False
        rep.problems.append("defined names changed")
    if names_a - names_b:
        rep.ok = False
        rep.problems.append(f"members missing from output: {sorted(names_a - names_b)}")
    return rep
