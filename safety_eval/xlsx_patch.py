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


def excel_serial(d: date | datetime) -> int:
    """Excel 1900 date-system serial for a date."""
    if isinstance(d, datetime):
        d = d.date()
    return (d - _EXCEL_EPOCH).days


@dataclass
class CellEdit:
    """One cell write: numeric, text (inline string), or blank (clear value)."""
    ref: str                       # e.g. "A4"
    value: object = None           # int/float -> number; str -> inline string;
                                   # date -> serial number; None -> clear


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
    rid_to_target: dict[str, str] = {}
    for rel in re.findall(r"<Relationship [^>]*/>", rels):
        rid = re.search(r'\bId="(rId\d+)"', rel)
        tgt = re.search(r'\bTarget="([^"]+)"', rel)
        if rid and tgt:
            rid_to_target[rid.group(1)] = tgt.group(1)
    out: dict[str, str] = {}
    for sheet_tag in re.findall(r"<sheet [^>]*/>", wb):
        nm = re.search(r'\bname="([^"]+)"', sheet_tag)
        rm = re.search(r'\br:id="(rId\d+)"', sheet_tag)
        if not (nm and rm):
            continue
        name, rid = nm.group(1), rm.group(1)
        target = rid_to_target[rid]
        target = target.lstrip("/")
        if not target.startswith("xl/"):
            target = "xl/" + target
        out[name.replace("&amp;", "&")] = target
    return out


def _cell_xml(ref: str, value, style: str | None) -> str:
    s_attr = f' s="{style}"' if style else ""
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
            new = _cell_xml(e.ref, e.value, self._style_of(e.ref))
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


def xlsx_patch(path_in: str, path_out: str,
               edits: dict[str, list[CellEdit]],
               style_rows: dict[str, int] | None = None,
               full_calc_on_load: bool = True) -> None:
    """Apply per-sheet cell edits to a copy of ``path_in`` written at ``path_out``.

    ``edits`` maps sheet NAME -> list of CellEdit.  Every zip member that is not
    an edited worksheet (or workbook.xml when ``full_calc_on_load``) is copied
    byte-for-byte, preserving drawings, media, charts, styles, and rels.
    """
    style_rows = style_rows or {}
    name_to_file = sheet_files(path_in)
    unknown = set(edits) - set(name_to_file)
    if unknown:
        raise KeyError(f"Sheets not in template: {sorted(unknown)}")
    file_edits = {name_to_file[n]: (n, e) for n, e in edits.items()}

    with zipfile.ZipFile(path_in) as zin:
        members = zin.infolist()
        with zipfile.ZipFile(path_out, "w", zipfile.ZIP_DEFLATED) as zout:
            for info in members:
                data = zin.read(info.filename)
                if info.filename in file_edits:
                    sheet_name, sheet_edits = file_edits[info.filename]
                    patcher = SheetPatcher(
                        data.decode("utf-8"),
                        style_row=style_rows.get(sheet_name))
                    patcher.apply(sheet_edits)
                    data = patcher.xml.encode("utf-8")
                elif info.filename == "xl/workbook.xml" and full_calc_on_load:
                    text = data.decode("utf-8")
                    if "fullCalcOnLoad" in text:
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
