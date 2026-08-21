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


def export_onepager(workbook: str, out_pdf: str,
                    sheet: str = RESULTS_SHEET,
                    cell_range: str = PRINT_RANGE,
                    row_heights: dict | None = None,
                    timeout: int = 120) -> str:
    """Export one sheet's print range to a one-page PDF, in memory."""
    import uno
    from com.sun.star.beans import PropertyValue

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
            "file://" + os.path.abspath(workbook), "_blank", 0,
            (P("Hidden", True),))
        try:
            sh = doc.Sheets.getByName(sheet)
            cells = sh.getCellRangeByName(cell_range)
            style = doc.StyleFamilies.getByName("PageStyles").getByName(
                sh.PageStyle)
            style.ScaleToPages = 1
            style.CenterHorizontally = True
            style.CenterVertically = True
            style.LeftMargin = style.RightMargin = 635      # 0.25 in
            style.TopMargin = style.BottomMargin = 1270     # 0.5 in
            style.HeaderIsOn = style.FooterIsOn = False
            for row, ht in (row_heights if row_heights is not None
                            else ROW_HEIGHTS).items():
                sh.Rows.getByIndex(row - 1).Height = ht
            fdata = uno.Any("[]com.sun.star.beans.PropertyValue",
                            (P("Selection", cells),))
            doc.storeToURL("file://" + os.path.abspath(out_pdf),
                           (P("FilterName", "calc_pdf_Export"),
                            P("FilterData", fdata)))
        finally:
            doc.close(False)
    finally:
        proc.terminate()
    return out_pdf


def measure_map_region(onepager_pdf: str,
                       x0: float = 296.0, x1: float = 577.0):
    """The empty Map/Satellite box on the printed page, in PDF points.

    Measured off the print itself (between the 'Map/Satellite Views'
    header and the 'Items for Discussion' heading) because fit-to-page
    rescales the sheet whenever content lengths change, so no fixed
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
