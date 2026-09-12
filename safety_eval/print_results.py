"""Print the results page and bind the deliverable PDFs (docs/02, docs/06).

The Excel print of the results sheet is the reference. LibreOffice reproduces
it when two things hold:

* the workbook's Normal font (Calibri) has a metric compatible substitute
  installed (Carlito); without it every column is wider, fit to page drops
  from 62% to about 54% and the page comes out short and wide;
* Excel's 5 px column padding is added to the print copy's column widths
  (LibreOffice omits it), which brings the printed width within 0.01 in of
  Excel's.

The page is exported with the embedded aerial at native resolution, located
by its text markers, and bound with pikepdf: Complete Evaluation = results
page + disclaimer + TEAAS reports; Web = results page + disclaimer.
"""
from __future__ import annotations

import json
import os
import re
import shutil
import subprocess
import tempfile
import zipfile
from dataclasses import dataclass, field
from datetime import datetime

from .xlsx_patch import sheet_files

RESULTS_MARKERS = ("Safety Project Evaluation", "Map/Satellite")
COLUMN_PADDING_CHARS = 0.476     # measured: brings LO within 0.01 in of Excel


@dataclass
class PrintReport:
    pdf: str
    page_index: int               # 1 based page in the full export
    pages_total: int
    warnings: list = field(default_factory=list)


def soffice_path() -> str | None:
    return shutil.which("soffice") or shutil.which("libreoffice")


def fonts_report() -> dict[str, bool]:
    """Which metric compatible fonts are installed (fontconfig)."""
    fc = shutil.which("fc-list")
    if not fc:
        return {"carlito": False, "liberation_serif": False, "fc-list": False}
    out = subprocess.run([fc, ":", "family"], capture_output=True, text=True).stdout.lower()
    return {"carlito": "carlito" in out, "liberation_serif": "liberation serif" in out,
            "fc-list": True}


def _pad_columns(workbook_in: str, workbook_out: str, sheet: str, pad: float) -> None:
    names = sheet_files(workbook_in)
    target = names[sheet]
    with zipfile.ZipFile(workbook_in) as src, zipfile.ZipFile(workbook_out, "w", zipfile.ZIP_DEFLATED) as out:
        for info in src.infolist():
            data = src.read(info.filename)
            if info.filename == target:
                s = data.decode("utf-8")
                s = re.sub(r'(<col [^>]*width=")([\d.]+)(")',
                           lambda m: f"{m.group(1)}{float(m.group(2)) + pad:.6f}{m.group(3)}", s)
                data = s.encode("utf-8")
            out.writestr(info, data)


def _export_filter(lossless: bool, quality: int) -> str:
    opts = {"ReduceImageResolution": {"type": "boolean", "value": "false"},
            "UseLosslessCompression": {"type": "boolean", "value": "true" if lossless else "false"}}
    if not lossless:
        opts["Quality"] = {"type": "long", "value": str(quality)}
    return "pdf:calc_pdf_Export:" + json.dumps(opts)


def pdf_page_texts(pdf: str) -> list[str]:
    pdftotext = shutil.which("pdftotext")
    if not pdftotext:
        raise RuntimeError("pdftotext (poppler-utils) is required to locate the results page")
    txt = subprocess.run([pdftotext, "-layout", pdf, "-"], capture_output=True, text=True).stdout
    pages = txt.split("\f")
    if pages and not pages[-1].strip():
        pages = pages[:-1]
    return pages


def extract_page(pdf_in: str, page_index: int, pdf_out: str) -> None:
    import pikepdf

    with pikepdf.open(pdf_in) as src, pikepdf.new() as dst:
        dst.pages.append(src.pages[page_index - 1])
        dst.save(pdf_out)


def print_sheet(workbook: str, out_pdf: str, sheet: str = "1 page results - 1 Target",
                markers: tuple = RESULTS_MARKERS, column_padding: float = COLUMN_PADDING_CHARS,
                lossless: bool = False, jpeg_quality: int = 92, timeout: int = 300) -> PrintReport:
    """Print ``sheet`` of ``workbook`` to a one page PDF at ``out_pdf``."""
    soffice = soffice_path()
    if not soffice:
        raise RuntimeError("LibreOffice (soffice) is not installed; print the page from Excel instead")
    warnings = []
    fr = fonts_report()
    if not fr.get("carlito"):
        warnings.append("Carlito (Calibri metric match) is not installed: column widths and the "
                        "fit-to-page scale will differ from the Excel print. Install fonts-crosextra-carlito.")
    if not fr.get("liberation_serif"):
        warnings.append("Liberation Serif is not installed; Times New Roman text will use a fallback font.")
    with tempfile.TemporaryDirectory(prefix="print-") as tmp:
        copy = os.path.join(tmp, "print.xlsx")
        _pad_columns(workbook, copy, sheet, column_padding)
        profile = os.path.join(tmp, "profile")
        subprocess.run([soffice, "--headless", "--norestore", f"-env:UserInstallation=file://{profile}",
                        "--convert-to", _export_filter(lossless, jpeg_quality), "--outdir", tmp, copy],
                       check=True, capture_output=True, timeout=timeout)
        full = os.path.join(tmp, "print.pdf")
        if not os.path.exists(full):
            raise RuntimeError("LibreOffice produced no PDF")
        pages = pdf_page_texts(full)
        hits = [i + 1 for i, p in enumerate(pages) if all(m in p for m in markers)]
        if not hits:
            raise RuntimeError(f"No page of the export contains the markers {markers}")
        extract_page(full, hits[0], out_pdf)
        return PrintReport(pdf=out_pdf, page_index=hits[0], pages_total=len(pages), warnings=warnings)


def assemble_deliverables(page1: str, disclaimer: str | None, appendices: list[str],
                          complete_out: str | None, web_out: str | None,
                          title: str = "Safety Project Evaluation", author: str = "VHB") -> dict:
    """Bind the deliverables with pikepdf; unused resources dropped, Info set."""
    import pikepdf

    def _bind(parts: list[str], out: str) -> int:
        with pikepdf.new() as dst:
            for p in parts:
                if not p:
                    continue
                with pikepdf.open(p) as src:
                    dst.pages.extend(src.pages)
            dst.remove_unreferenced_resources()
            with dst.open_metadata() as meta:
                meta["dc:title"] = title
                meta["dc:creator"] = [author]
            dst.docinfo["/Title"] = title
            dst.docinfo["/Author"] = author
            dst.docinfo["/Creator"] = "NCDOT Intersection Evaluation Workbook"
            dst.docinfo["/CreationDate"] = pikepdf.String(datetime.now().strftime("D:%Y%m%d%H%M%S"))
            n = len(dst.pages)
            dst.save(out)
        return n

    out = {}
    if complete_out:
        out["complete_pages"] = _bind([page1, disclaimer, *appendices], complete_out)
    if web_out:
        out["web_pages"] = _bind([page1, disclaimer], web_out)
    return out


def render_png(pdf: str, out_prefix: str, dpi: int = 150, page: int = 1) -> str:
    pdftoppm = shutil.which("pdftoppm")
    if not pdftoppm:
        raise RuntimeError("pdftoppm (poppler-utils) is required to render pages")
    subprocess.run([pdftoppm, "-r", str(dpi), "-f", str(page), "-l", str(page), "-png",
                    "-singlefile", pdf, out_prefix], check=True, capture_output=True)
    return out_prefix + ".png"


def ink_extents_inches(png: str, dpi: int = 150, threshold: int = 200) -> dict:
    """Left/top/right/bottom margins and content size, for comparing a
    LibreOffice print with the Excel print of the same page."""
    from PIL import Image

    im = Image.open(png).convert("L")
    mask = im.point(lambda p: 255 if p < threshold else 0)
    bbox = mask.getbbox()
    if not bbox:
        return {}
    x0, y0, x1, y1 = bbox
    return {"left": x0 / dpi, "top": y0 / dpi, "right": (im.width - x1) / dpi,
            "bottom": (im.height - y1) / dpi, "width": (x1 - x0) / dpi, "height": (y1 - y0) / dpi}


def embedded_images(pdf: str, page: int = 1) -> list[dict]:
    """Images drawn on a page (width, height, filter) via pikepdf."""
    import pikepdf

    out = []
    with pikepdf.open(pdf) as doc:
        pg = doc.pages[page - 1]
        xobjs = pg.Resources.get("/XObject", {})
        for name, obj in xobjs.items():
            if obj.get("/Subtype") == "/Image":
                filt = obj.get("/Filter")
                out.append({"name": str(name), "width": int(obj.Width), "height": int(obj.Height),
                            "filter": str(filt) if filt is not None else None})
    return out
