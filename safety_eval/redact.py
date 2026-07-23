"""PII redaction for uploaded crash reports (DMV-349 scans).

When crash reports are uploaded for fiche review, personally identifying
information must be redacted before the reviewer sees them: names, street
addresses, dates of birth, phone numbers, and driver license numbers.
ZIP codes are deliberately KEPT (they help locate the crash without
identifying a person). Crash IDs are never redacted (the page index and
review workflow key on them).

Pipeline:
    PDF -> page images (poppler ``pdftoppm``)  [or TIFF/PNG/JPG input]
        -> OCR word boxes (``tesseract`` TSV)
        -> redaction plan (label-driven + pattern-driven, ZIP-preserving)
        -> black boxes burned into the page image (PIL)
        -> image-only PDF output (NO text layer, so nothing can leak)

The output is rasterized on purpose: redacting a text-layer PDF by drawing
rectangles leaves the underlying text extractable; burning boxes into images
does not.

This is a screening aid, not a certification: OCR can miss handwriting or
poor scans, so the engineer remains responsible for a final visual check
(engineer-in-the-loop, docs/07). An audit summary (box counts and trigger
reasons per page, never the PII text itself) is returned for that review.
"""
from __future__ import annotations

import csv
import io
import os
import re
import shutil
import subprocess
import tempfile
from dataclasses import dataclass, field

# --------------------------------------------------------------------------- #
# words and geometry
# --------------------------------------------------------------------------- #


@dataclass
class Word:
    text: str
    left: int
    top: int
    width: int
    height: int
    page: int = 0
    line_id: tuple = (0, 0, 0)      # (block, par, line) from tesseract

    @property
    def right(self) -> int:
        return self.left + self.width

    @property
    def bottom(self) -> int:
        return self.top + self.height


@dataclass
class Redaction:
    page: int
    left: int
    top: int
    right: int
    bottom: int
    reason: str


# --------------------------------------------------------------------------- #
# PII patterns (labels are DMV-349 field captions; values follow or sit below)
# --------------------------------------------------------------------------- #
_LABELS = {
    "name": ("name", "driver", "owner", "insured", "witness", "passenger",
             "occupant", "pedestrian", "first", "middle", "last"),
    "address": ("address", "street"),
    # 'pop'/'do8'/'d08' are common OCR garblings of the DOB caption on scans
    "dob": ("birth", "dob", "pop", "do8", "d08"),
    "phone": ("phone", "telephone"),
    "license": ("license", "dl#", "dl", "cdl"),
    "vin": ("vin",),
    "plate": ("plate",),
}
_LABEL_WORDS = {w for group in _LABELS.values() for w in group}

_ZIP_RE = re.compile(r"^\d{5}(?:-\d{4})?$")
# full numbers, and the 7-digit local form scans often show when the area
# code sits in its own box ("252 ... 214-8149")
_PHONE_RE = re.compile(r"^(?:\(?\d{3}\)?[-. ]?\d{3}[-. ]?\d{4}|\d{3}[-.]\d{4})$")
_DATE_RE = re.compile(r"^\d{1,2}[/-]\d{1,2}[/-]\d{2,4}$")
_STREET_SUFFIXES = (
    "ST", "STREET", "RD", "ROAD", "AVE", "AVENUE", "DR", "DRIVE", "LN",
    "LANE", "CT", "COURT", "HWY", "HIGHWAY", "BLVD", "CIR", "CIRCLE", "PL",
    "PLACE", "WAY", "TRL", "TRAIL", "PKWY", "LOOP",
)
_CRASH_ID_RE = re.compile(r"^\d{9}$")
# 17-char VIN (no I/O/Q); matched anywhere because the left-column caption is
# often lost by OCR, leaving the bare VIN on the row
_VIN_RE = re.compile(r"^[A-HJ-NPR-Z0-9]{17}$")


def _norm(token: str) -> str:
    return re.sub(r"[^A-Za-z0-9#/-]", "", token).lower()


def _lines(words: list[Word]) -> list[list[Word]]:
    by_line: dict[tuple, list[Word]] = {}
    for w in words:
        by_line.setdefault((w.page,) + w.line_id, []).append(w)
    out = [sorted(ws, key=lambda w: w.left) for ws in by_line.values()]
    out.sort(key=lambda ws: (ws[0].page, ws[0].top, ws[0].left))
    return out


def _visual_rows(words: list[Word], factor: float = 0.6) -> list[list[Word]]:
    """Cluster words into visual rows by vertical position.

    Sparse-mode OCR on form scans often emits each boxed value as its own
    "line" even when it sits beside its caption (seen on the 600501348
    binder: Driver / SHONTA / MONEAK / GARDNER arrive as four lines at the
    same height, so a line-id based label rule misses the name).  Grouping
    by top coordinate reunites captions with their values.
    """
    out: list[list[Word]] = []
    for page in sorted({w.page for w in words}):
        pws = sorted((w for w in words if w.page == page),
                     key=lambda w: (w.top, w.left))
        row: list[Word] = []
        for w in pws:
            if row and abs(w.top - row[0].top) > factor * max(
                    w.height, row[0].height, 1):
                out.append(sorted(row, key=lambda x: x.left))
                row = []
            row.append(w)
        if row:
            out.append(sorted(row, key=lambda x: x.left))
    out.sort(key=lambda ws: (ws[0].page, ws[0].top, ws[0].left))
    return out


_STATE_ABBRS = {
    "AL", "AK", "AZ", "AR", "CA", "CO", "CT", "DE", "FL", "GA", "HI", "ID",
    "IL", "IN", "IA", "KS", "KY", "LA", "ME", "MD", "MA", "MI", "MN", "MS",
    "MO", "MT", "NE", "NV", "NH", "NJ", "NM", "NY", "NC", "ND", "OH", "OK",
    "OR", "PA", "RI", "SC", "SD", "TN", "TX", "UT", "VT", "VA", "WA", "WV",
    "WI", "WY", "DC",
}


def _looks_like_city_line(tokens: list[str]) -> bool:
    """A short line ending in a ZIP, or containing a state abbreviation and a
    ZIP: 'Wendell NC 27591'."""
    if not tokens or len(tokens) > 6:
        return False
    has_zip = any(_ZIP_RE.match(t.strip()) for t in tokens)
    has_state = any(t.strip().upper().strip(".,") in _STATE_ABBRS
                    for t in tokens)
    return has_zip and (has_state or len(tokens) <= 3)


def _line_has_street_address(tokens: list[str]) -> bool:
    for i, tok in enumerate(tokens):
        if tok.isdigit() and not _CRASH_ID_RE.match(tok) and len(tok) <= 6:
            rest = [t.upper().strip(".,") for t in tokens[i + 1: i + 5]]
            if any(sfx in rest for sfx in _STREET_SUFFIXES):
                return True
    return False


def plan_redactions(words: list[Word], keep_zip: bool = True,
                    pad: int = 3) -> list[Redaction]:
    """Decide what to black out.

    Rules (conservative: over-redact rather than leak):

    * A line containing a PII field label: everything AFTER the label on that
      line, plus the entire NEXT line when the label line holds no value
      (DMV-349 boxes put the caption above the handwritten/typed value).
    * A line that looks like a street address (number followed by a street
      suffix) is redacted wholly.
    * Standalone phone numbers and dates following a DOB label.
    * ZIP-looking tokens are carved OUT of any planned box when ``keep_zip``.
    * 9-digit crash IDs are never redacted.
    """
    lines = _visual_rows(words)
    planned: list[tuple[list[Word], str]] = []
    redact_next_line_of: dict[tuple, str] = {}
    address_continues_from: int | None = None

    for idx, line in enumerate(lines):
        tokens = [w.text for w in line]
        norm = [_norm(t) for t in tokens]

        # city/state/zip continuation line directly under an address line
        if address_continues_from == idx and _looks_like_city_line(tokens):
            planned.append((line, "address-continuation"))
            address_continues_from = None
            continue
        if address_continues_from is not None and address_continues_from < idx:
            address_continues_from = None

        # carried-over: caption line above a value box
        prev_reason = redact_next_line_of.pop(("pending", idx), None)
        if prev_reason:
            planned.append((line, prev_reason))
            if prev_reason.startswith("label:address"):
                address_continues_from = idx + 1
            continue

        label_pos = None
        label_kind = None
        for i, tok in enumerate(norm):
            for kind, keys in _LABELS.items():
                if tok in keys:
                    label_pos, label_kind = i, kind
                    break
            if label_pos is not None:
                break

        if label_pos is not None:
            value_words = [w for w in line[label_pos + 1:]
                           if _norm(w.text) not in _LABEL_WORDS]
            value_words = [w for w in value_words if w.text.strip()]
            before_words = [w for w in line[:label_pos]
                            if _norm(w.text) not in _LABEL_WORDS
                            and w.text.strip()]
            if value_words:
                planned.append((value_words, f"label:{label_kind}"))
                # on the DMV-349 the vehicle boxes put the value LEFT of the
                # surviving caption (unit-1 column), with unit-2 form text to
                # the right; cover both sides for those kinds
                if before_words and label_kind in ("vin", "plate"):
                    planned.append((before_words,
                                    f"label:{label_kind}(before)"))
            elif before_words:
                # boxed forms can lose the left-column caption to OCR, leaving
                # the value BEFORE the surviving caption on the row (seen with
                # VIN/plate on the 600501348 binder)
                planned.append((before_words, f"label:{label_kind}(before)"))
            else:
                # caption-only line: value sits on the following line
                redact_next_line_of[("pending", idx + 1)] = f"label:{label_kind}(below)"
            if label_kind == "address":
                address_continues_from = idx + 1
            continue

        if _line_has_street_address(tokens):
            planned.append((line, "street-address"))
            address_continues_from = idx + 1
            continue

        for w in line:
            if _PHONE_RE.match(w.text.strip()):
                planned.append(([w], "phone"))
            elif _VIN_RE.match(w.text.strip()) and \
                    not w.text.strip().isdigit():
                planned.append(([w], "vin-pattern"))

    out: list[Redaction] = []
    for group, reason in planned:
        segments = _split_keeping_zip(group, keep_zip)
        for seg in segments:
            seg = [w for w in seg if not _CRASH_ID_RE.match(w.text.strip())]
            if not seg:
                continue
            out.append(Redaction(
                page=seg[0].page,
                left=max(0, min(w.left for w in seg) - pad),
                top=max(0, min(w.top for w in seg) - pad),
                right=max(w.right for w in seg) + pad,
                bottom=max(w.bottom for w in seg) + pad,
                reason=reason,
            ))
    return out


def _split_keeping_zip(group: list[Word], keep_zip: bool) -> list[list[Word]]:
    if not keep_zip:
        return [group]
    segments: list[list[Word]] = []
    current: list[Word] = []
    for w in group:
        if _ZIP_RE.match(w.text.strip()):
            if current:
                segments.append(current)
                current = []
            continue                      # zip stays visible
        current.append(w)
    if current:
        segments.append(current)
    return segments


# --------------------------------------------------------------------------- #
# OCR and rendering (subprocess tesseract / poppler; PIL for drawing)
# --------------------------------------------------------------------------- #
class RedactionToolsMissing(RuntimeError):
    pass


def _require(binary: str) -> str:
    path = shutil.which(binary)
    if not path:
        raise RedactionToolsMissing(
            f"'{binary}' is required for crash-report redaction. Install "
            "tesseract-ocr and poppler-utils.")
    return path


def ocr_words(image_path: str, page: int = 0, timeout: int = 120,
              min_conf: float = 30.0) -> list[Word]:
    """OCR one page image into word boxes via tesseract TSV."""
    tesseract = _require("tesseract")
    proc = subprocess.run(
        [tesseract, image_path, "stdout", "--psm", "11", "tsv"],
        capture_output=True, text=True, timeout=timeout, check=True)
    words: list[Word] = []
    reader = csv.DictReader(io.StringIO(proc.stdout), delimiter="\t")
    for row in reader:
        text = (row.get("text") or "").strip()
        try:
            conf = float(row.get("conf", -1))
        except ValueError:
            conf = -1
        if not text or conf < min_conf:
            continue
        words.append(Word(
            text=text,
            left=int(row["left"]), top=int(row["top"]),
            width=int(row["width"]), height=int(row["height"]),
            page=page,
            line_id=(int(row["block_num"]), int(row["par_num"]),
                     int(row["line_num"])),
        ))
    return words


def pdf_to_images(pdf_path: str, workdir: str, dpi: int = 200) -> list[str]:
    """Rasterize a PDF to per-page PNGs with poppler."""
    pdftoppm = _require("pdftoppm")
    prefix = os.path.join(workdir, "page")
    subprocess.run([pdftoppm, "-png", "-r", str(dpi), pdf_path, prefix],
                   check=True, capture_output=True, timeout=600)
    return sorted(
        os.path.join(workdir, f) for f in os.listdir(workdir)
        if f.startswith("page") and f.endswith(".png"))


def _load_input_pages(path: str, workdir: str, dpi: int) -> list:
    """Return PIL images for a PDF, multi-frame TIFF, or single image."""
    from PIL import Image, ImageSequence

    ext = os.path.splitext(path)[1].lower()
    if ext == ".pdf":
        return [Image.open(p).convert("RGB")
                for p in pdf_to_images(path, workdir, dpi)]
    img = Image.open(path)
    return [frame.convert("RGB") for frame in ImageSequence.Iterator(img)]


@dataclass
class RedactionReport:
    pages: int = 0
    boxes: int = 0
    by_reason: dict = field(default_factory=dict)
    warnings: list = field(default_factory=list)


def redact_file(input_path: str, output_path: str, keep_zip: bool = True,
                dpi: int = 200) -> RedactionReport:
    """Redact a crash-report file into an image-only PDF.

    Returns an audit report (counts and reasons only; the PII itself is never
    echoed anywhere).
    """
    from PIL import ImageDraw

    report = RedactionReport()
    with tempfile.TemporaryDirectory(prefix="redact-") as tmp:
        pages = _load_input_pages(input_path, tmp, dpi)
        report.pages = len(pages)
        out_pages = []
        for i, img in enumerate(pages):
            page_png = os.path.join(tmp, f"ocr-{i}.png")
            img.save(page_png)
            words = ocr_words(page_png, page=i)
            if not words:
                report.warnings.append(
                    f"page {i + 1}: no OCR text found; verify manually")
            boxes = plan_redactions(words, keep_zip=keep_zip)
            draw = ImageDraw.Draw(img)
            for b in boxes:
                draw.rectangle([b.left, b.top, b.right, b.bottom],
                               fill="black")
                report.boxes += 1
                report.by_reason[b.reason] = report.by_reason.get(b.reason, 0) + 1
            out_pages.append(img)
        first, rest = out_pages[0], out_pages[1:]
        first.save(output_path, format="PDF", save_all=True,
                   append_images=rest, resolution=dpi)
    return report
