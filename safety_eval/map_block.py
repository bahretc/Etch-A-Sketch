"""Map/Satellite Views block for the results page (team format, docs/02).

The completed workbooks (SS-6002AD and later) fill the block with one aerial
of the junction, a small location map inset in a corner, a white bordered
serif text box beside each leg reading

    Route (Name)
    speed limit
    AADT (Year)
    N vpd (year)

a north arrow, and the imagery credit. This module composes that image from
an aerial and a location map the engineer supplies (Nearmap, county GIS, or
the Esri World Imagery export fetched by :func:`fetch_esri_world_imagery`),
checks that nothing overlaps, and embeds it in the results sheet as a
oneCellAnchor picture without touching any other drawing part (docs/06).

Leg AADT labels should come from the Evaluation Set-up row of the after
representative year (the SS-6002AD precedent), see :mod:`aadt_table`.
"""
from __future__ import annotations

import io
import math
import os
import re
import shutil
import urllib.parse
import urllib.request
import zipfile
from dataclasses import dataclass, field

from .xlsx_patch import sheet_files

EMU_PER_PX = 9525
_FONT_DIRS = ("/usr/share/fonts/truetype/liberation", "/usr/share/fonts/truetype/dejavu",
              "C:/Windows/Fonts", "/Library/Fonts")
_SERIF = ("LiberationSerif-Regular.ttf", "times.ttf", "Times New Roman.ttf", "DejaVuSerif.ttf")
_SERIF_BOLD = ("LiberationSerif-Bold.ttf", "timesbd.ttf", "DejaVuSerif-Bold.ttf")


def _find_font(names) -> str | None:
    for d in _FONT_DIRS:
        for n in names:
            p = os.path.join(d, n)
            if os.path.exists(p):
                return p
    return None


@dataclass
class LegLabel:
    """A text box beside one leg. ``direction`` is the leg's direction from the
    junction in image pixels (x right, y down); ``side`` picks which side of the
    leg the box sits on (+1 or -1); ``distance`` and ``offset`` are along and
    across the leg, in output pixels."""
    lines: list[str]
    direction: tuple[float, float]
    distance: float = 420.0
    side: int = 1
    offset: float = 150.0


@dataclass
class BlockSpec:
    width: int = 1626
    height: int = 962
    font_size: int = 40
    pad: int = 14
    border: int = 3
    inset_size: int = 340
    inset_corner: str | None = None       # TL/TR/BL/BR or None for auto
    credit: str | None = None
    north_arrow: bool = True


@dataclass
class BlockLayout:
    boxes: dict = field(default_factory=dict)   # name -> (x0, y0, x1, y1)
    inset_corner: str | None = None
    clashes: list = field(default_factory=list)


def leg_label_lines(route: str, name: str | None, speed_mph: int | None,
                    aadt: int, year: int) -> list[str]:
    head = f"{route} ({name})" if name else route
    lines = [head]
    if speed_mph:
        lines.append(f"{speed_mph} mph")
    lines += ["AADT (Year)", f"{aadt:,} vpd ({year})"]
    return lines


def crop_around(image, center: tuple[int, int], size: tuple[int, int]):
    """Crop ``size`` pixels around ``center`` (clamped to the image)."""
    w, h = size
    cx, cy = center
    x0 = max(0, min(image.width - w, cx - w // 2))
    y0 = max(0, min(image.height - h, cy - h // 2))
    return image.crop((x0, y0, x0 + w, y0 + h))


def _unit(v):
    n = math.hypot(*v) or 1.0
    return (v[0] / n, v[1] / n)


def _overlap(a, b) -> bool:
    return not (a[2] < b[0] or b[2] < a[0] or a[3] < b[1] or b[3] < a[1])


def _leg_crosses(rect, junction, direction, length: float) -> bool:
    """Does the ray from the junction along ``direction`` enter ``rect``?"""
    ux, uy = _unit(direction)
    for t in range(0, int(length), 8):
        x, y = junction[0] + ux * t, junction[1] + uy * t
        if rect[0] <= x <= rect[2] and rect[1] <= y <= rect[3]:
            return True
    return False


def compose_map_block(aerial, junction: tuple[int, int], legs: list[LegLabel],
                      inset=None, spec: BlockSpec | None = None):
    """Return (PIL image, BlockLayout). ``aerial`` is already cropped to the
    block aspect and centred on the junction; ``junction`` is in aerial pixels."""
    from PIL import Image, ImageDraw, ImageFont

    spec = spec or BlockSpec()
    W, H = spec.width, spec.height
    sx, sy = W / aerial.width, H / aerial.height
    img = aerial.convert("RGB").resize((W, H), Image.LANCZOS)
    J = (junction[0] * sx, junction[1] * sy)
    draw = ImageDraw.Draw(img)
    serif = _find_font(_SERIF)
    bold = _find_font(_SERIF_BOLD) or serif
    font = ImageFont.truetype(serif, spec.font_size) if serif else ImageFont.load_default()
    layout = BlockLayout()
    diag = math.hypot(W, H)

    # inset in the first corner no leg passes through
    if inset is not None:
        s = spec.inset_size
        m = 14
        corners = {"TL": (m, m, m + s, m + s), "TR": (W - m - s, m, W - m, m + s),
                   "BL": (m, H - m - s, m + s, H - m), "BR": (W - m - s, H - m - s, W - m, H - m)}
        order = [spec.inset_corner] if spec.inset_corner else ["TR", "TL", "BL", "BR"]
        chosen = None
        for c in order:
            r = corners[c]
            if not any(_leg_crosses(r, J, lg.direction, diag) for lg in legs):
                chosen = c
                break
        chosen = chosen or order[0]
        r = corners[chosen]
        ins = inset.convert("RGB").resize((s, s), Image.LANCZOS)
        img.paste(ins, (r[0], r[1]))
        draw.rectangle((r[0] - 2, r[1] - 2, r[2] + 1, r[3] + 1), outline="white", width=3)
        draw.rectangle((r[0] - 4, r[1] - 4, r[2] + 3, r[3] + 3), outline="black", width=1)
        layout.boxes["inset"] = (r[0] - 4, r[1] - 4, r[2] + 3, r[3] + 3)
        layout.inset_corner = chosen

    def box_rect(lg: LegLabel, extra: float):
        ux, uy = _unit(lg.direction)
        px, py = uy * lg.side, -ux * lg.side
        cx = J[0] + ux * (lg.distance + extra) + px * lg.offset
        cy = J[1] + uy * (lg.distance + extra) + py * lg.offset
        bw = int(max(draw.textlength(t, font=font) for t in lg.lines)) + 2 * spec.pad
        lh = spec.font_size + 8
        bh = lh * len(lg.lines) + 2 * spec.pad
        x0 = int(min(max(cx - bw / 2, 4), W - bw - 4))
        y0 = int(min(max(cy - bh / 2, 4), H - bh - 4))
        return (x0, y0, x0 + bw, y0 + bh), lh

    placed = dict(layout.boxes)
    for i, lg in enumerate(legs):
        rect, lh = box_rect(lg, 0)
        for extra in (0, 40, 80, 120, 160, -40, -80):
            rect, lh = box_rect(lg, extra)
            if not any(_overlap(rect, r) for r in placed.values()):
                break
        draw.rectangle(rect, fill="white", outline="black", width=spec.border)
        for k, t in enumerate(lg.lines):
            draw.text(((rect[0] + rect[2]) / 2, rect[1] + spec.pad + k * lh), t,
                      font=font, fill="black", anchor="ma")
        placed[f"leg{i + 1}"] = rect
    layout.boxes.update(placed)

    if spec.north_arrow:
        nx, ny = W - 70, H - 150
        draw.polygon([(nx, ny - 60), (nx - 22, ny + 10), (nx, ny - 8), (nx + 22, ny + 10)],
                     fill="white", outline="black")
        nfont = ImageFont.truetype(bold, 44) if bold else font
        draw.text((nx, ny + 18), "N", font=nfont, fill="white", stroke_width=3,
                  stroke_fill="black", anchor="ma")
        layout.boxes["north"] = (nx - 30, ny - 66, nx + 30, ny + 70)
    if spec.credit:
        cfont = ImageFont.truetype(serif, 30) if serif else font
        cw = int(draw.textlength(spec.credit, font=cfont))
        # credit goes in whichever top corner the inset did not take
        x = 14 if layout.inset_corner != "TL" else W - 14 - cw
        draw.text((x, 12), spec.credit, font=cfont, fill="white", stroke_width=3,
                  stroke_fill="black", anchor="la")
        layout.boxes["credit"] = (x, 12, x + cw, 46)

    names = list(layout.boxes)
    layout.clashes = [(a, b) for i, a in enumerate(names) for b in names[i + 1:]
                      if _overlap(layout.boxes[a], layout.boxes[b])]
    return img, layout


# --------------------------------------------------------------------------- #
# imagery
# --------------------------------------------------------------------------- #
ESRI_EXPORT = ("https://services.arcgisonline.com/ArcGIS/rest/services/"
               "World_Imagery/MapServer/export")


def fetch_esri_world_imagery(lat: float, lon: float, width: int = 1626,
                             height: int = 962, ground_width_m: float = 520.0,
                             timeout: int = 60):
    """Esri World Imagery export around a point (docs/07). Returns a PIL image.
    The engineer's own imagery (Nearmap) is preferred when available."""
    from PIL import Image

    m_per_deg_lat = 111320.0
    m_per_deg_lon = 111320.0 * math.cos(math.radians(lat))
    half_w = ground_width_m / 2
    half_h = half_w * height / width
    bbox = (lon - half_w / m_per_deg_lon, lat - half_h / m_per_deg_lat,
            lon + half_w / m_per_deg_lon, lat + half_h / m_per_deg_lat)
    params = {"bbox": ",".join(f"{v:.7f}" for v in bbox), "bboxSR": 4326,
              "imageSR": 4326, "size": f"{width},{height}", "format": "png",
              "f": "image"}
    req = urllib.request.Request(ESRI_EXPORT + "?" + urllib.parse.urlencode(params),
                                 headers={"User-Agent": "safety-eval/0.1"})
    with urllib.request.urlopen(req, timeout=timeout) as resp:
        return Image.open(io.BytesIO(resp.read())).convert("RGB")


# --------------------------------------------------------------------------- #
# workbook embedding
# --------------------------------------------------------------------------- #
def cell_to_index(ref: str) -> tuple[int, int]:
    """'H41' -> (7, 40) zero based (col, row)."""
    m = re.match(r"([A-Z]+)(\d+)$", ref)
    col = 0
    for ch in m.group(1):
        col = col * 26 + ord(ch) - 64
    return col - 1, int(m.group(2)) - 1


def block_extent_px(workbook: str, sheet: str, top_left: str, bottom_right: str,
                    char_px: float = 7.0) -> tuple[int, int]:
    """Pixel size of a cell range from the sheet's column widths and row heights
    (Excel: px = width*7+5 for Calibri 11; rows in points at 96 dpi)."""
    names = sheet_files(workbook)
    with zipfile.ZipFile(workbook) as z:
        xml = z.read(names[sheet]).decode("utf-8")
    c0, r0 = cell_to_index(top_left)
    c1, r1 = cell_to_index(bottom_right)
    fmt = re.search(r"<sheetFormatPr[^>]*/>", xml)
    def_w = float(re.search(r'defaultColWidth="([\d.]+)"', fmt.group(0)).group(1)) if fmt and "defaultColWidth" in fmt.group(0) else 8.43
    def_h = float(re.search(r'defaultRowHeight="([\d.]+)"', fmt.group(0)).group(1)) if fmt and "defaultRowHeight" in fmt.group(0) else 15.0
    widths = {}
    for m in re.finditer(r"<col [^>]*/>", xml):
        a = m.group(0)
        lo, hi = int(re.search(r'min="(\d+)"', a).group(1)), int(re.search(r'max="(\d+)"', a).group(1))
        w = re.search(r'width="([\d.]+)"', a)
        for c in range(lo, min(hi, 200) + 1):
            widths[c - 1] = float(w.group(1)) if w else def_w
    heights = {}
    for m in re.finditer(r'<row r="(\d+)"([^>]*)>', xml):
        h = re.search(r'ht="([\d.]+)"', m.group(2))
        if h:
            heights[int(m.group(1)) - 1] = float(h.group(1))
    wpx = sum(int(widths.get(c, def_w) * char_px + 5) for c in range(c0, c1 + 1))
    hpx = sum(heights.get(r, def_h) * 96 / 72 for r in range(r0, r1 + 1))
    return int(wpx), int(hpx)


def fit_within(image_size: tuple[int, int], box: tuple[int, int],
               margin: float = 0.985) -> tuple[int, int]:
    scale = min(box[0] / image_size[0], box[1] / image_size[1]) * margin
    return int(image_size[0] * scale), int(image_size[1] * scale)


_DRAWING_NS = ('xmlns:xdr="http://schemas.openxmlformats.org/drawingml/2006/spreadsheetDrawing" '
               'xmlns:a="http://schemas.openxmlformats.org/drawingml/2006/main"')
_R_NS = "http://schemas.openxmlformats.org/officeDocument/2006/relationships"
_REL_IMAGE = _R_NS + "/image"
_REL_DRAWING = _R_NS + "/drawing"
_CT_DRAWING = "application/vnd.openxmlformats-officedocument.drawing+xml"


def _anchor_xml(col: int, row: int, cx: int, cy: int, pic_id: int, name: str, rid: str,
                off_emu: int = 19050) -> str:
    return (f'<xdr:oneCellAnchor><xdr:from><xdr:col>{col}</xdr:col><xdr:colOff>{off_emu}</xdr:colOff>'
            f'<xdr:row>{row}</xdr:row><xdr:rowOff>{off_emu}</xdr:rowOff></xdr:from>'
            f'<xdr:ext cx="{cx}" cy="{cy}"/><xdr:pic><xdr:nvPicPr><xdr:cNvPr id="{pic_id}" name="{name}"/>'
            f'<xdr:cNvPicPr><a:picLocks noChangeAspect="1"/></xdr:cNvPicPr></xdr:nvPicPr>'
            f'<xdr:blipFill><a:blip xmlns:r="{_R_NS}" r:embed="{rid}"/><a:stretch><a:fillRect/></a:stretch>'
            f'</xdr:blipFill><xdr:spPr><a:xfrm><a:off x="0" y="0"/><a:ext cx="{cx}" cy="{cy}"/></a:xfrm>'
            f'<a:prstGeom prst="rect"><a:avLst/></a:prstGeom></xdr:spPr></xdr:pic><xdr:clientData/>'
            f'</xdr:oneCellAnchor>')


def _next_rid(rels_xml: str) -> str:
    ids = [int(x) for x in re.findall(r'Id="rId(\d+)"', rels_xml)]
    return f"rId{max(ids, default=0) + 1}"


def _next_member(parts: dict, pattern: str) -> tuple[int, str]:
    n = 1
    while pattern.format(n) in parts:
        n += 1
    return n, pattern.format(n)


def embed_picture(workbook_in: str, workbook_out: str, sheet: str, image_path: str,
                  anchor_cell: str, size_px: tuple[int, int],
                  name: str = "Map and Aerial", replace_same_name: bool = True) -> dict:
    """Embed ``image_path`` as a oneCellAnchor picture on ``sheet``.

    The sheet's existing drawing part is extended when it has one (the results
    sheets do); otherwise a drawing part, its relationships and the content
    type override are created. Every other member is copied byte for byte.
    Returns a dict describing the parts touched.
    """
    names = sheet_files(workbook_in)
    if sheet not in names:
        raise KeyError(f"Sheet not in workbook: {sheet!r}")
    sheet_file = names[sheet]
    with zipfile.ZipFile(workbook_in) as z:
        infos = z.infolist()
        parts = {i.filename: z.read(i.filename) for i in infos}
    order = [i.filename for i in infos]
    touched = {}

    ext = os.path.splitext(image_path)[1].lower().lstrip(".") or "png"
    with open(image_path, "rb") as fh:
        img_bytes = fh.read()
    _, media_name = _next_member(parts, "xl/media/image{}." + ext)
    parts[media_name] = img_bytes
    order.append(media_name)
    touched["media"] = media_name

    sheet_xml = parts[sheet_file].decode("utf-8")
    sheet_rels_name = sheet_file.replace("worksheets/", "worksheets/_rels/") + ".rels"
    sheet_rels = parts.get(sheet_rels_name, b"").decode("utf-8") if sheet_rels_name in parts else ""
    dm = re.search(r'<drawing r:id="(rId\d+)"\s*/>', sheet_xml)
    if dm:
        rid = dm.group(1)
        tm = re.search(rf'<Relationship [^>]*Id="{rid}"[^>]*/>', sheet_rels).group(0)
        target = re.search(r'Target="([^"]+)"', tm).group(1)
        drawing_name = "xl/" + target.replace("../", "") if target.startswith("../") else target.lstrip("/")
        if not drawing_name.startswith("xl/"):
            drawing_name = "xl/" + drawing_name
    else:
        n, drawing_name = _next_member(parts, "xl/drawings/drawing{}.xml")
        parts[drawing_name] = (f'<?xml version="1.0" encoding="UTF-8" standalone="yes"?>\n'
                               f'<xdr:wsDr {_DRAWING_NS}></xdr:wsDr>').encode("utf-8")
        order.append(drawing_name)
        if not sheet_rels:
            sheet_rels = ('<?xml version="1.0" encoding="UTF-8" standalone="yes"?>\n'
                          '<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships">'
                          '</Relationships>')
            order.append(sheet_rels_name)
        rid = _next_rid(sheet_rels)
        sheet_rels = sheet_rels.replace(
            "</Relationships>",
            f'<Relationship Id="{rid}" Type="{_REL_DRAWING}" Target="../drawings/{os.path.basename(drawing_name)}"/></Relationships>')
        parts[sheet_rels_name] = sheet_rels.encode("utf-8")
        tag = f'<drawing r:id="{rid}"/>'
        if "xmlns:r=" not in sheet_xml[: sheet_xml.index(">", sheet_xml.index("<worksheet")) + 1]:
            sheet_xml = sheet_xml.replace("<worksheet", f'<worksheet xmlns:r="{_R_NS}"', 1)
        later = re.search(r"<(legacyDrawing|legacyDrawingHF|picture|oleObjects|controls|webPublishItems|tableParts|extLst)\b", sheet_xml)
        pos = later.start() if later else sheet_xml.index("</worksheet>")
        sheet_xml = sheet_xml[:pos] + tag + sheet_xml[pos:]
        parts[sheet_file] = sheet_xml.encode("utf-8")
        ct = parts["[Content_Types].xml"].decode("utf-8")
        ct = ct.replace("</Types>", f'<Override PartName="/{drawing_name}" ContentType="{_CT_DRAWING}"/></Types>')
        parts["[Content_Types].xml"] = ct.encode("utf-8")
        touched["drawing_created"] = drawing_name

    ct = parts["[Content_Types].xml"].decode("utf-8")
    if f'Extension="{ext}"' not in ct:
        mime = {"png": "image/png", "jpg": "image/jpeg", "jpeg": "image/jpeg"}.get(ext, f"image/{ext}")
        ct = ct.replace("<Default ", f'<Default Extension="{ext}" ContentType="{mime}"/><Default ', 1)
        parts["[Content_Types].xml"] = ct.encode("utf-8")

    drawing_rels_name = drawing_name.replace("drawings/", "drawings/_rels/") + ".rels"
    drels = parts.get(drawing_rels_name, b"").decode("utf-8") if drawing_rels_name in parts else (
        '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>\n'
        '<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships"></Relationships>')
    if drawing_rels_name not in parts:
        order.append(drawing_rels_name)
    img_rid = _next_rid(drels)
    drels = drels.replace("</Relationships>",
                          f'<Relationship Id="{img_rid}" Type="{_REL_IMAGE}" Target="../media/{os.path.basename(media_name)}"/></Relationships>')
    parts[drawing_rels_name] = drels.encode("utf-8")

    dxml = parts[drawing_name].decode("utf-8")
    if replace_same_name:
        dxml = re.sub(rf'<xdr:(oneCellAnchor|twoCellAnchor)>(?:(?!</xdr:\1>).)*?name="{re.escape(name)}".*?</xdr:\1>',
                      "", dxml, flags=re.S)
    ids = [int(x) for x in re.findall(r'<xdr:cNvPr id="(\d+)"', dxml)]
    col, row = cell_to_index(anchor_cell)
    anchor = _anchor_xml(col, row, size_px[0] * EMU_PER_PX, size_px[1] * EMU_PER_PX,
                         max(ids, default=1) + 1, name, img_rid)
    dxml = dxml.replace("</xdr:wsDr>", anchor + "</xdr:wsDr>")
    parts[drawing_name] = dxml.encode("utf-8")
    touched["drawing"] = drawing_name

    tmp = workbook_out + ".tmp"
    with zipfile.ZipFile(tmp, "w", zipfile.ZIP_DEFLATED) as out:
        for fname in order:
            out.writestr(fname, parts[fname])
    shutil.move(tmp, workbook_out)
    return touched
