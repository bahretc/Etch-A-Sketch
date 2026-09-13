"""PDF text extraction / OCR for the TEAAS fiche PDF.

This is a **pluggable front-end**.  The core analysis engine never imports this
module; it is only reached when the input is a PDF.  Extraction is attempted in
increasing order of cost:

1. ``pdfplumber`` text layer  — for digitally-generated fiche PDFs.
2. ``pypdf`` text layer       — lightweight fallback.
3. OCR (``pytesseract`` on ``pdf2image`` renders) — for scanned/printed fiche.

Each backend is imported lazily so a missing/broken dependency only fails the
PDF path, never ``import safety_eval``.
"""
from __future__ import annotations

import contextlib
import os


@contextlib.contextmanager
def _suppress_native_stderr():
    """Silence fd-level stderr (e.g. Rust panic backtraces from broken native deps)."""
    saved = os.dup(2)
    devnull = os.open(os.devnull, os.O_WRONLY)
    try:
        os.dup2(devnull, 2)
        yield
    finally:
        os.dup2(saved, 2)
        os.close(devnull)
        os.close(saved)


class OcrUnavailable(RuntimeError):
    """Raised when no PDF/OCR backend could be used."""


def extract_pdf_text(path: str) -> str:
    """Return the best-effort text of a fiche PDF."""
    errors: list[str] = []

    for backend in (_via_pdfplumber, _via_pypdf, _via_ocr):
        try:
            text = backend(path)
            if text and text.strip():
                return text
        except BaseException as exc:  # noqa: BLE001 - native backends can panic
            errors.append(f"{backend.__name__}: {exc}")

    raise OcrUnavailable(
        "Could not extract text from PDF. Tried:\n  " + "\n  ".join(errors)
        + "\nInstall one of: pdfplumber, pypdf, or pytesseract+pdf2image."
    )


def _via_pdfplumber(path: str) -> str:
    import pdfplumber  # lazy

    out: list[str] = []
    with pdfplumber.open(path) as pdf:
        for page in pdf.pages:
            # prefer table extraction (fiche is tabular), fall back to raw text
            for table in page.extract_tables() or []:
                for row in table:
                    out.append(" | ".join((c or "").strip() for c in row))
            out.append(page.extract_text() or "")
    return "\n".join(out)


def _via_pypdf(path: str) -> str:
    from pypdf import PdfReader  # lazy

    reader = PdfReader(path)
    return "\n".join(page.extract_text() or "" for page in reader.pages)


def _via_ocr(path: str) -> str:
    import pytesseract  # lazy
    from pdf2image import convert_from_path  # lazy

    out: list[str] = []
    for image in convert_from_path(path, dpi=300):
        out.append(pytesseract.image_to_string(image))
    return "\n".join(out)


def available_backends() -> dict[str, bool]:
    """Report which OCR/PDF backends are importable in this environment."""
    status: dict[str, bool] = {}
    for name in ("pdfplumber", "pypdf", "pytesseract", "pdf2image"):
        try:
            with _suppress_native_stderr():
                __import__(name)
            status[name] = True
        except BaseException:  # noqa: BLE001 - native backends can panic on import
            status[name] = False
    return status
