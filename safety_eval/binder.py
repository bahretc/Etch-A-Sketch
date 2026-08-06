"""DMV-349 binder page indexing and per-crash page retrieval (docs/07).

Scanned crash-report binders arrive as one or more PDF/TIFF files with no
text layer.  Each report's FRONT page carries the 9-digit crash ID in the
"Do not write in these spaces" header box at the TOP RIGHT of the DMV-349;
continuation pages (the back page's roadway/work-zone grid, narrative and
diagram supplements) do not.  The index is therefore built exactly as the
spec describes: rasterize at 150-200 DPI, crop the top-right of each page,
OCR with tesseract psm 6, and assign ID-less pages to the preceding ID.

Validated on the 600501348 sample binder (15 parts, ~1,600 pages): front
pages OCR to their crash ID; back pages attach as continuations, so
multi-sheet reports (supplementals) group under one crash.

Retrieval is engineer-facing and therefore PII-safe by construction:
``render_crash_pages`` runs the docs/07 redaction pass (``redact.py``) on
every page image before returning it.  Raw, un-redacted pages are never
handed to the review UI.

The index is a plain JSON document so it can be built once (it OCRs every
page) and reused across review sessions.
"""
from __future__ import annotations

import json
import os
import re
import subprocess
import tempfile
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass, field

from .redact import _require, ocr_words, pdf_to_images, plan_redactions

# Crash IDs on the fiche and TEAAS exports are 9-digit numbers.  The header
# crop also contains dates (slashes), the patrol-area code (letters) and DMV
# text, so a standalone 9-digit token is the ID.
_CRASH_ID_RE = re.compile(r"\b(\d{9})\b")

# Top-right fraction of the page holding the "Do not write in these spaces"
# box (fractions of width/height: left, top, right, bottom).
HEADER_CROP = (0.55, 0.0, 1.0, 0.20)
INDEX_VERSION = 1


@dataclass
class PageRef:
    """One physical page inside one binder file."""
    file: str          # binder file path as given at index time
    page: int          # 1-based page number within that file

    def key(self) -> tuple[str, int]:
        return (self.file, self.page)


@dataclass
class BinderIndex:
    """crash_id -> ordered pages, in binder order."""
    pages_by_crash: dict[str, list[PageRef]] = field(default_factory=dict)
    unassigned: list[PageRef] = field(default_factory=list)   # pages before the first ID
    files: list[str] = field(default_factory=list)
    dpi: int = 150
    warnings: list[str] = field(default_factory=list)

    def crash_ids(self) -> list[str]:
        return list(self.pages_by_crash)

    def pages_for(self, crash_id: str) -> list[PageRef]:
        return self.pages_by_crash.get(str(crash_id), [])

    def to_json(self) -> str:
        return json.dumps({
            "version": INDEX_VERSION,
            "dpi": self.dpi,
            "files": self.files,
            "unassigned": [[p.file, p.page] for p in self.unassigned],
            "warnings": self.warnings,
            "crashes": {cid: [[p.file, p.page] for p in refs]
                        for cid, refs in self.pages_by_crash.items()},
        }, indent=1)

    @classmethod
    def from_json(cls, text: str) -> "BinderIndex":
        d = json.loads(text)
        return cls(
            pages_by_crash={cid: [PageRef(f, p) for f, p in refs]
                            for cid, refs in d.get("crashes", {}).items()},
            unassigned=[PageRef(f, p) for f, p in d.get("unassigned", [])],
            files=d.get("files", []),
            dpi=d.get("dpi", 150),
            warnings=d.get("warnings", []),
        )

    def save(self, path: str) -> None:
        with open(path, "w", encoding="utf-8") as fh:
            fh.write(self.to_json())

    @classmethod
    def load(cls, path: str) -> "BinderIndex":
        with open(path, encoding="utf-8") as fh:
            return cls.from_json(fh.read())


# --------------------------------------------------------------------------- #
# building the index
# --------------------------------------------------------------------------- #
#: TEAAS binders arrive as multi-page Group 4 bilevel TIFF as often as PDF.
#: A letter page scanned at 1699 px wide is 200 dpi, which is what the header
#: OCR and the redaction pass are tuned for.
_TIFF_EXT = (".tif", ".tiff")
_TIFF_NATIVE_DPI = 200


def _is_tiff(path: str) -> bool:
    return path.lower().endswith(_TIFF_EXT)


def _page_count(path: str) -> int:
    if _is_tiff(path):
        from PIL import Image, ImageSequence
        with Image.open(path) as im:
            return sum(1 for _ in ImageSequence.Iterator(im))
    from pypdf import PdfReader
    return len(PdfReader(path).pages)


def _render_page(path: str, page: int, dpi: int, workdir: str) -> str:
    """Rasterize a single 1-based page to PNG; returns the image path."""
    out = os.path.join(workdir, f"pg-{os.getpid()}-{page}.png")

    if _is_tiff(path):
        # A TIFF's pixels are already fixed, so "dpi" here means resample the
        # native raster to that scale rather than rasterize at it.
        from PIL import Image
        with Image.open(path) as im:
            im.seek(page - 1)
            frame = im.convert("L")
            if dpi and dpi != _TIFF_NATIVE_DPI:
                scale = dpi / _TIFF_NATIVE_DPI
                frame = frame.resize(
                    (max(1, round(frame.width * scale)),
                     max(1, round(frame.height * scale))), Image.LANCZOS)
            frame.save(out)
        return out

    pdftoppm = _require("pdftoppm")
    prefix = os.path.join(workdir, f"pg-{os.getpid()}-{page}")
    subprocess.run(
        [pdftoppm, "-png", "-r", str(dpi), "-f", str(page), "-l", str(page),
         path, prefix],
        check=True, capture_output=True, timeout=120)
    outs = [f for f in os.listdir(workdir)
            if f.startswith(os.path.basename(prefix)) and f.endswith(".png")]
    if not outs:
        raise RuntimeError(f"pdftoppm produced no image for page {page}")
    return os.path.join(workdir, outs[0])


def read_header_id(image_path: str, crop=HEADER_CROP,
                   timeout: int = 300) -> str | None:
    """OCR the crash-ID header box of one page image (psm 6, top-right crop)."""
    from PIL import Image

    tesseract = _require("tesseract")
    with Image.open(image_path) as img:
        w, h = img.size
        box = (int(w * crop[0]), int(h * crop[1]),
               int(w * crop[2]), int(h * crop[3]))
        cropped = img.crop(box)
        crop_path = image_path + ".hdr.png"
        cropped.save(crop_path)
    # OMP_THREAD_LIMIT=1: one tesseract per worker thread; letting each spawn
    # its own OpenMP pool oversubscribes the CPU and stalls whole pages
    env = dict(os.environ, OMP_THREAD_LIMIT="1")
    try:
        proc = subprocess.run(
            [tesseract, crop_path, "stdout", "--psm", "6"],
            capture_output=True, text=True, timeout=timeout, check=True,
            env=env)
    finally:
        os.unlink(crop_path)
    ids = _CRASH_ID_RE.findall(proc.stdout)
    # the header box holds exactly one crash ID; several distinct 9-digit
    # tokens would mean we matched noise, so trust only a unanimous read
    uniq = set(ids)
    if len(uniq) == 1:
        return uniq.pop()
    return None


def index_binder(paths: list[str], dpi: int = 150, workers: int = 3,
                 progress=None) -> BinderIndex:
    """OCR-index scanned binder files.

    ``paths`` are indexed in the given order; multi-part binders must be
    passed in part order so continuation pages attach to the right report.
    ``progress(done, total)`` is called as pages complete.
    """
    idx = BinderIndex(files=list(paths), dpi=dpi)
    jobs: list[PageRef] = []
    for path in paths:
        for page in range(1, _page_count(path) + 1):
            jobs.append(PageRef(path, page))

    results: dict[tuple[str, int], str | None] = {}
    done = 0
    with tempfile.TemporaryDirectory(prefix="binder-idx-") as tmp:
        def _work(ref: PageRef) -> tuple[PageRef, str | None, str | None]:
            # a page whose render or OCR fails becomes a continuation page
            # (no ID) with a warning, never a dead run: the engineer sees the
            # warning and that crash's pages still group with its neighbours
            try:
                img = _render_page(ref.file, ref.page, dpi, tmp)
            except (subprocess.SubprocessError, RuntimeError, OSError) as exc:
                return ref, None, f"{ref.file} p{ref.page}: render failed ({exc})"
            try:
                return ref, read_header_id(img), None
            except (subprocess.SubprocessError, OSError) as exc:
                return ref, None, f"{ref.file} p{ref.page}: OCR failed ({exc})"
            finally:
                os.unlink(img)

        with ThreadPoolExecutor(max_workers=workers) as pool:
            for ref, cid, warning in pool.map(_work, jobs):
                results[ref.key()] = cid
                if warning:
                    idx.warnings.append(warning)
                done += 1
                if progress:
                    progress(done, len(jobs))

    current: str | None = None
    for ref in jobs:                       # binder order, not completion order
        cid = results.get(ref.key())
        if cid:
            current = cid
            idx.pages_by_crash.setdefault(cid, []).append(ref)
        elif current:
            idx.pages_by_crash[current].append(ref)
        else:
            idx.unassigned.append(ref)
    return idx


# --------------------------------------------------------------------------- #
# reconciliation against known crash IDs
# --------------------------------------------------------------------------- #
def _longest_common_run(a: str, b: str) -> int:
    best = 0
    for i in range(len(a)):
        for j in range(len(b)):
            k = 0
            while i + k < len(a) and j + k < len(b) and a[i + k] == b[j + k]:
                k += 1
            best = max(best, k)
    return best


def reconcile_index(index: BinderIndex, known_ids) -> dict[str, str]:
    """Suggest fixes for OCR-misread crash IDs.

    A cropped or blurred header digit makes the OCR read a shifted ID (seen
    on the 600501348 binder: true 108164536 printed with the leading 1 cut
    off read as 081645367).  For each indexed ID that is not a known crash,
    the known IDs with no report yet are searched for a unique candidate
    sharing a run of 7+ consecutive digits; matches are returned as
    ``{read_id: known_id}`` SUGGESTIONS for the engineer, never applied
    silently.
    """
    known = {str(k) for k in known_ids}
    unknown_reads = [cid for cid in index.pages_by_crash if cid not in known]
    missing = [k for k in known if k not in index.pages_by_crash]
    out: dict[str, str] = {}
    for read in unknown_reads:
        cands = [k for k in missing if _longest_common_run(read, k) >= 7]
        if len(cands) == 1:
            out[read] = cands[0]
    return out


def apply_reconciliation(index: BinderIndex,
                         suggestions: dict[str, str]) -> None:
    """Re-key accepted suggestions (in place) and note each in warnings."""
    for read, true_id in suggestions.items():
        if read in index.pages_by_crash and true_id not in index.pages_by_crash:
            index.pages_by_crash[true_id] = index.pages_by_crash.pop(read)
            index.warnings.append(
                f"crash {true_id}: header OCR read {read}; re-keyed per "
                "reconciliation")


# --------------------------------------------------------------------------- #
# redacted retrieval
# --------------------------------------------------------------------------- #
def render_crash_pages(index: BinderIndex, crash_id: str, dpi: int = 150,
                       keep_zip: bool = True, verify: bool = True) -> list:
    """Render a crash's pages as REDACTED PIL images (front page first).

    This is the path that feeds `review_assist`, so it runs the SAME hardened
    redaction as `redact.redact_file` rather than a private copy: multi-pass
    multi-scale convergence, cross-page name harvesting, and DMV-349 field
    geometry. It used to apply a single `plan_redactions` pass, which the
    hardening in `redact_file` never reached; measured on a real 47-report
    binder, that left residual PII on 28 of them (43 street addresses, 7 phone
    numbers, 2 dates beside a DOB caption).

    With ``verify`` set, the redacted pages are re-read and
    ``RedactionIncomplete`` is raised if anything legible survives. Failing
    closed is the point: a caller that gets pages back knows they are clean,
    and a caller that gets an exception must not fall back to raw imagery.
    """
    from PIL import Image, ImageSequence

    from .redact import redact_file, verify_redaction

    refs = index.pages_for(crash_id)
    if not refs:
        return []

    with tempfile.TemporaryDirectory(prefix="binder-get-") as tmp:
        # Stage this crash's raw pages as one document so the redactor can
        # harvest names across them; a name printed on page 1 is what lets it
        # be scrubbed out of the narrative on page 2.
        raw = [Image.open(_render_page(r.file, r.page, dpi, tmp)).convert("RGB")
               for r in refs]
        staged = os.path.join(tmp, f"{crash_id}-raw.tiff")
        raw[0].save(staged, save_all=True, append_images=raw[1:])
        for im in raw:
            im.close()

        redacted_pdf = os.path.join(tmp, f"{crash_id}-redacted.pdf")
        redact_file(staged, redacted_pdf, keep_zip=keep_zip, dpi=dpi)
        os.unlink(staged)                      # raw imagery does not linger

        pages, paths = [], []
        for i, p in enumerate(pdf_to_images(redacted_pdf, tmp, dpi)):
            pages.append(Image.open(p).convert("RGB"))
            paths.append(p)
        if verify:
            verify_redaction(paths, keep_zip=keep_zip)
        return [p.copy() for p in pages]


def export_crash_pdf(index: BinderIndex, crash_id: str, output: str,
                     dpi: int = 150, keep_zip: bool = True) -> int:
    """Write one crash's redacted pages to an image-only PDF; returns pages."""
    pages = render_crash_pages(index, crash_id, dpi=dpi, keep_zip=keep_zip)
    if not pages:
        raise KeyError(f"crash {crash_id} not in binder index")
    pages[0].save(output, format="PDF", save_all=True,
                  append_images=pages[1:], resolution=dpi)
    return len(pages)
