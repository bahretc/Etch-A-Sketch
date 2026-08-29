"""Print the evaluation 1-pager to PDF and assemble the Web report.

The delivered "{project} Web.pdf" is two letter-portrait pages: the
'1 page results' sheet printed fit-to-one-page over print area B2:L72
(the saved print area of the completed workbooks), then the standard
2020-data disclaimer page. "Complete Evaluation.pdf" adds the TEAAS
Intersection Analysis Reports for the before and after periods, which
are TEAAS output and are appended when the engineer supplies them.

The sheet is printed through LibreOffice's UNO bridge so the workbook
file on disk is never modified: the document is loaded in memory, the
page style set (letter portrait, fit to one page, centered, the
completed workbooks' margins), a handful of rows expanded the way the
engineer sizes them before printing (merged cells do not auto-fit),
and ONLY the print-range selection exported. Requires python3-uno and
libreoffice-calc.
"""
from __future__ import annotations

import os
import re
import subprocess
import time

RESULTS_SHEET = "1 page results - 1 Target"
PRINT_RANGE = "B2:L72"

#: Rows the engineer expands before printing, in 1/100 mm: the
#: countermeasure block, the Target Crashes list, the Map/Satellite
#: column, and the Items for Discussion cell. Keys are 1-based rows.
ROW_HEIGHTS = {**{r: 920 for r in range(18, 23)},
               **{r: 430 for r in range(33, 39)},
               **{r: 900 for r in range(40, 57)},
               58: 4800}

_UNO_PORT = 2002


def _page_count(pdf: str) -> int:
    from pypdf import PdfReader
    return len(PdfReader(pdf).pages)


def saved_print_range(workbook: str, sheet: str = RESULTS_SHEET,
                      default: str = PRINT_RANGE) -> str:
    """The sheet's saved Print_Area as a plain range (e.g. B2:L73).

    Read rather than assumed: the Items cell grows by whole rows when a
    long discussion needs them, and the print area grows with it.
    """
    import zipfile
    with zipfile.ZipFile(workbook) as z:
        wb = z.read("xl/workbook.xml").decode("utf-8")
    m = re.search(r'<definedName name="_xlnm.Print_Area"[^>]*>\''
                  + re.escape(sheet) + r"'!([^<]+)</definedName>", wb)
    return m.group(1).replace("$", "") if m else default


def saved_scale(workbook: str, sheet: str = RESULTS_SHEET,
                default: int = 64) -> int:
    """The sheet's saved print scale (pageSetup), the engineer's choice."""
    import zipfile
    with zipfile.ZipFile(workbook) as z:
        wb = z.read("xl/workbook.xml").decode("utf-8")
        rels = dict(re.findall(r'Id="(rId\d+)" [^>]*Target="([^"]+)"',
                    z.read("xl/_rels/workbook.xml.rels").decode("utf-8")))
        for name, rid in re.findall(
                r'<sheet [^>]*?name="([^"]+)"[^>]*?r:id="(rId\d+)"', wb):
            if name.replace("&amp;", "&") == sheet:
                target = rels[rid].lstrip("/")
                if not target.startswith("xl/"):
                    target = "xl/" + target
                m = re.search(r'<pageSetup[^>]*?scale="(\d+)"',
                              z.read(target).decode("utf-8"))
                return int(m.group(1)) if m else default
    return default


def export_onepager(workbook: str, out_pdf: str,
                    sheet: str = RESULTS_SHEET,
                    cell_range: str | None = None,
                    row_heights: dict | None = None,
                    scale: int | None = None,
                    fit_to_page: bool = False,
                    timeout: int = 120) -> str:
    """Export one sheet's print range to a one-page PDF, in memory.

    The print runs at the workbook's saved scale, the way the engineer's
    own Web PDFs are produced, re-applied through the page style because
    LibreOffice drops the file's saved print scale on OOXML import. If
    the result spills past one page (LibreOffice measures columns a
    shade wider than Excel), the scale steps down a point at a time
    until it fits, and only as a last resort falls back to
    fit-sheet-on-one-page. ``scale`` forces an exact percentage.

    Column widths depend on the workbook default font (Calibri): the
    metric-compatible Carlito face (fonts-crosextra-carlito) must be
    installed or every column prints ~20% wide and the right edge clips.
    """
    import uno
    from com.sun.star.beans import PropertyValue

    if cell_range is None:
        cell_range = saved_print_range(workbook, sheet)
    forced = scale is not None
    if scale is None:
        scale = saved_scale(workbook, sheet)

    proc = subprocess.Popen(
        ["soffice", "--headless", "--norestore", "--invisible",
         f"--accept=socket,host=127.0.0.1,port={_UNO_PORT};urp;"],
        stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    try:
        local = uno.getComponentContext()
        resolver = local.ServiceManager.createInstanceWithContext(
            "com.sun.star.bridge.UnoUrlResolver", local)
        ctx = None
        deadline = time.time() + timeout
        while time.time() < deadline:
            try:
                ctx = resolver.resolve(
                    f"uno:socket,host=127.0.0.1,port={_UNO_PORT};urp;"
                    "StarOffice.ComponentContext")
                break
            except Exception:
                time.sleep(0.5)
        if ctx is None:
            raise RuntimeError("could not reach the LibreOffice listener")
        desktop = ctx.ServiceManager.createInstanceWithContext(
            "com.sun.star.frame.Desktop", ctx)

        def P(name, value):
            p = PropertyValue()
            p.Name, p.Value = name, value
            return p

        doc = desktop.loadComponentFromURL(
            uno.systemPathToFileUrl(os.path.abspath(workbook)), "_blank", 0,
            (P("Hidden", True),))
        try:
            sh = doc.Sheets.getByName(sheet)
            cells = sh.getCellRangeByName(cell_range)
            style = doc.StyleFamilies.getByName("PageStyles").getByName(
                sh.PageStyle)
            # margins and centering come from the workbook (the template
            # ships 0.25/0.5in with center-on-page both ways)
            style.HeaderIsOn = style.FooterIsOn = False
            for row, ht in (row_heights or {}).items():
                sh.Rows.getByIndex(row - 1).Height = ht
            fdata = uno.Any("[]com.sun.star.beans.PropertyValue",
                            (P("Selection", cells),))

            def export(sc):
                if sc is None:
                    style.ScaleToPages = 1
                else:
                    style.ScaleToPages = 0
                    style.PageScale = sc
                doc.storeToURL(
                    uno.systemPathToFileUrl(os.path.abspath(out_pdf)),
                    (P("FilterName", "calc_pdf_Export"),
                     P("FilterData", fdata)))
                return _page_count(out_pdf)

            if scale is None:
                export(None)
            else:
                tries = [scale] if forced else                     [scale, scale - 1, scale - 2, None]
                for sc in tries:
                    if export(sc) == 1 or sc is None or forced:
                        break
        finally:
            doc.close(False)
    finally:
        proc.terminate()
    return out_pdf


def measure_map_region(onepager_pdf: str,
                       x0: float | None = None, x1: float | None = None):
    """The empty Map/Satellite box on the printed page, in PDF points.

    Measured off the print itself (between the 'Map/Satellite Views'
    header and the 'Items for Discussion' heading, spanning from the
    header's left edge to the printed content's right edge) because the
    print scale moves whenever content lengths change, so no fixed
    coordinates survive an edit.
    """
    out = subprocess.run(["pdftotext", "-bbox", onepager_pdf, "-"],
                         capture_output=True, text=True, check=True)
    words = re.findall(
        r'<word xMin="([\d.]+)" yMin="([\d.]+)" xMax="([\d.]+)" '
        r'yMax="([\d.]+)">([^<]+)</word>', out.stdout)

    def find(seq):
        for i in range(len(words)):
            if [w[4] for w in words[i:i + len(seq)]] == seq:
                return words[i:i + len(seq)]
        return None

    hdr = find(["Map/Satellite", "Views"])
    items = find(["Items", "for", "Discussion"])
    if not hdr or not items:
        raise RuntimeError("could not locate the Map/Satellite region")
    if x0 is None:
        x0 = float(hdr[0][0])
    if x1 is None:
        x1 = max(float(w[2]) for w in words)
    return x0, float(hdr[0][3]) + 5, x1, float(items[0][1]) - 8


def overlay_map(onepager_pdf: str, image_png: str, out_pdf: str) -> str:
    """Place the annotated aerial into the Map/Satellite box."""
    from PIL import Image
    from pypdf import PdfReader, PdfWriter
    from reportlab.pdfgen import canvas

    x0, ytop, x1, ybot = measure_map_region(onepager_pdf)
    with Image.open(image_png) as im:
        iw, ih = im.size
    s = min((x1 - x0) / iw, (ybot - ytop) / ih)
    w, h = iw * s, ih * s
    x = x0 + (x1 - x0 - w) / 2
    ov = out_pdf + ".overlay.tmp"
    c = canvas.Canvas(ov, pagesize=(612, 792))
    c.drawImage(image_png, x, 792 - ytop - h, width=w, height=h)
    c.save()
    writer = PdfWriter(clone_from=onepager_pdf)
    writer.pages[0].merge_page(PdfReader(ov).pages[0])
    with open(out_pdf, "wb") as fh:
        writer.write(fh)
    os.unlink(ov)
    return out_pdf


def assemble(parts: list[str], out_pdf: str) -> str:
    """Concatenate report parts (1-pager, disclaimer, TEAAS reports)."""
    from pypdf import PdfReader, PdfWriter
    writer = PdfWriter()
    for part in parts:
        for page in PdfReader(part).pages:
            writer.add_page(page)
    with open(out_pdf, "wb") as fh:
        writer.write(fh)
    return out_pdf
