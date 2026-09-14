"""Small XML level cell patches that :mod:`xlsx_patch` does not cover (docs/06).

* font colour of a cell (clone its cellXfs entry with a recoloured font);
* text of a cell that holds a shared string (a new shared string is appended
  and the cell repointed, so any other cell using the old string is unchanged);
* a numeric value in a non formula cell.

Every other zip member is copied byte for byte. Formula cells are refused: the
caller is expected to run :func:`xlsx_patch.recalc` afterwards when patched
inputs feed formulas.
"""
from __future__ import annotations

import re
import shutil
import zipfile
from dataclasses import dataclass
from xml.sax.saxutils import escape

from .xlsx_patch import sheet_files

COLOUR_XML = {"red": '<color rgb="FFFF0000"/>', "black": '<color theme="1"/>'}


@dataclass
class CellPatch:
    sheet: str
    ref: str
    value: object = None          # int/float
    text: str | None = None       # string cell (shared string or inline)
    colour: str | None = None     # "red" | "black"


_CELL_RE = r'<c r="{ref}"((?:\s+[\w:]+="[^"]*")*)\s*(?:/>|>(.*?)</c>)'


def _recolor_font(font_xml: str, colour: str) -> str:
    body = re.sub(r"<color [^>]*/>", "", font_xml)
    if "<sz" in body:
        return re.sub(r"(<sz [^>]*/>)", r"\1" + COLOUR_XML[colour], body, count=1)
    return body.replace("<font>", "<font>" + COLOUR_XML[colour], 1)


class _Styles:
    def __init__(self, xml: str):
        self.xml = xml
        fm = re.search(r'<fonts count="(\d+)"([^>]*)>(.*?)</fonts>', xml, re.S)
        xm = re.search(r'<cellXfs count="(\d+)">(.*?)</cellXfs>', xml, re.S)
        self.fonts = re.findall(r"<font>.*?</font>|<font/>", fm.group(3), re.S)
        self.xfs = re.findall(r"<xf [^>]*/>|<xf [^>]*>.*?</xf>", xm.group(2), re.S)
        self._fonts_attrs = fm.group(2)
        if len(self.fonts) != int(fm.group(1)) or len(self.xfs) != int(xm.group(1)):
            raise ValueError("styles.xml font/cellXfs counts do not match content")

    def recoloured_xf(self, xf_index: int, colour: str) -> int:
        xf = self.xfs[xf_index]
        fid = int(re.search(r'fontId="(\d+)"', xf).group(1))
        new_font = _recolor_font(self.fonts[fid], colour)
        if new_font not in self.fonts:
            self.fonts.append(new_font)
        nfid = self.fonts.index(new_font)
        new_xf = re.sub(r'fontId="\d+"', f'fontId="{nfid}"', xf)
        if "applyFont" not in new_xf:
            new_xf = new_xf.replace("<xf ", '<xf applyFont="1" ', 1)
        if new_xf not in self.xfs:
            self.xfs.append(new_xf)
        return self.xfs.index(new_xf)

    def render(self) -> str:
        xml = re.sub(r'<fonts count="\d+"[^>]*>.*?</fonts>',
                     lambda m: f'<fonts count="{len(self.fonts)}"{self._fonts_attrs}>'
                               + "".join(self.fonts) + "</fonts>", self.xml, count=1, flags=re.S)
        xml = re.sub(r'<cellXfs count="\d+">.*?</cellXfs>',
                     lambda m: f'<cellXfs count="{len(self.xfs)}">' + "".join(self.xfs) + "</cellXfs>",
                     xml, count=1, flags=re.S)
        return xml


class _SharedStrings:
    def __init__(self, xml: str | None):
        self.xml = xml
        self.sis = re.findall(r"<si>.*?</si>", xml, re.S) if xml else []

    @staticmethod
    def text_of(si: str) -> str:
        return "".join(re.findall(r"<t[^>]*>(.*?)</t>", si, re.S))

    def index_for(self, text: str) -> int:
        esc = escape(text)
        for i, si in enumerate(self.sis):
            if self.text_of(si) == esc:
                return i
        preserve = ' xml:space="preserve"' if (text != text.strip() or "\n" in text) else ""
        self.sis.append(f"<si><t{preserve}>{esc}</t></si>")
        return len(self.sis) - 1

    def render(self) -> str:
        if self.xml is None:
            return None
        open_tag = re.search(r"<sst [^>]*>", self.xml).group(0)
        open_tag = re.sub(r'uniqueCount="\d+"', f'uniqueCount="{len(self.sis)}"', open_tag)
        return self.xml[: self.xml.index(re.search(r"<sst [^>]*>", self.xml).group(0))] \
            + open_tag + "".join(self.sis) + "</sst>"


def apply_cell_patches(path_in: str, path_out: str, patches: list[CellPatch]) -> list[str]:
    """Apply patches to a copy of ``path_in`` at ``path_out``; returns a log."""
    names = sheet_files(path_in)
    log: list[str] = []
    with zipfile.ZipFile(path_in) as z:
        infos = z.infolist()
        parts = {i.filename: z.read(i.filename) for i in infos}
    styles = _Styles(parts["xl/styles.xml"].decode("utf-8"))
    sst = _SharedStrings(parts["xl/sharedStrings.xml"].decode("utf-8")
                         if "xl/sharedStrings.xml" in parts else None)
    sheets: dict[str, str] = {}
    for p in patches:
        if p.sheet not in names:
            raise KeyError(f"Sheet not in workbook: {p.sheet!r}")
        fname = names[p.sheet]
        xml = sheets.get(fname) or parts[fname].decode("utf-8")
        m = re.search(_CELL_RE.format(ref=p.ref), xml, re.S)
        if not m:
            raise KeyError(f"{p.sheet}!{p.ref} does not exist in the sheet XML")
        attrs, body = m.group(1) or "", m.group(2) or ""
        if "<f" in body:
            raise ValueError(f"{p.sheet}!{p.ref} holds a formula; patch its inputs instead")
        if p.colour:
            sm = re.search(r' s="(\d+)"', attrs)
            ns = styles.recoloured_xf(int(sm.group(1)) if sm else 0, p.colour)
            attrs = re.sub(r' s="\d+"', f' s="{ns}"', attrs) if sm else attrs + f' s="{ns}"'
            log.append(f"{p.sheet}!{p.ref} colour {p.colour}")
        if p.text is not None:
            attrs = re.sub(r'\s+t="[^"]*"', "", attrs)
            if sst.xml is not None:
                n = sst.index_for(p.text)
                attrs += ' t="s"'
                body = f"<v>{n}</v>"
            else:
                preserve = ' xml:space="preserve"' if "\n" in p.text else ""
                attrs += ' t="inlineStr"'
                body = f"<is><t{preserve}>{escape(p.text)}</t></is>"
            log.append(f"{p.sheet}!{p.ref} text {p.text[:40]!r}")
        elif p.value is not None:
            attrs = re.sub(r'\s+t="[^"]*"', "", attrs)
            v = repr(p.value) if isinstance(p.value, float) else str(p.value)
            body = f"<v>{v}</v>"
            log.append(f"{p.sheet}!{p.ref} value {v}")
        xml = xml[: m.start()] + f'<c r="{p.ref}"{attrs}>{body}</c>' + xml[m.end():]
        sheets[fname] = xml
    parts["xl/styles.xml"] = styles.render().encode("utf-8")
    if sst.xml is not None:
        parts["xl/sharedStrings.xml"] = sst.render().encode("utf-8")
    for fname, xml in sheets.items():
        parts[fname] = xml.encode("utf-8")
    tmp = path_out + ".tmp"
    with zipfile.ZipFile(tmp, "w", zipfile.ZIP_DEFLATED) as out:
        for info in infos:
            out.writestr(info, parts[info.filename])
    shutil.move(tmp, path_out)
    return log


def cell_colours(path: str, sheet: str, refs: list[str]) -> dict[str, str | None]:
    """Font colour ("red" / "black" / None) of cells, read with openpyxl."""
    import openpyxl

    wb = openpyxl.load_workbook(path)
    ws = wb[sheet]
    out = {}
    for ref in refs:
        f = ws[ref].font.color
        if f is None:
            out[ref] = "black"
        elif f.type == "rgb" and str(f.rgb).upper().endswith("FF0000"):
            out[ref] = "red"
        elif f.type == "theme" and f.theme == 1:
            out[ref] = "black"
        else:
            out[ref] = None
    return out
