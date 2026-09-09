"""PII redaction for uploaded crash reports (DMV-349 scans).

When crash reports are uploaded for fiche review, personally identifying
information must be redacted before the reviewer sees them: names, street
addresses, dates of birth, phone numbers, and driver license numbers.
ZIP codes are deliberately KEPT (they help locate the crash without
identifying a person). Crash IDs are never redacted (the page index and
review workflow key on them).

Pipeline:
    PDF -> page images (poppler ``pdftoppm``)  [or TIFF/PNG/JPG input]
        -> OCR word boxes (``tesseract`` TSV, two passes: page and sparse)
        -> redaction plan (label bands + section-32 region + token patterns
           + legacy line rules, ZIP-preserving)
        -> black boxes burned into the page image (PIL)
        -> image-only PDF output (NO text layer, so nothing can leak)

Why geometry bands and not OCR line structure: on the DMV-349 the field
captions ("Driver", "Address", "DOB") are tiny machine print while the values
are typed or handwritten in the box beside/below them. Sparse-mode OCR puts
caption and value in different text blocks, so "redact the rest of the line"
finds nothing - that failure leaked names on a real binder. Captions are
printed, so they OCR reliably even when the value is handwriting OCR cannot
read; a band anchored on the caption covers the value AREA regardless of
whether the value itself was recognized.

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
             "occupant", "pedestrian"),
    "address": ("address", "street"),
    "dob": ("birth", "dob"),
    "phone": ("phone", "telephone"),
    "license": ("license", "dl#", "dl", "cdl"),
}
_LABEL_WORDS = {w for group in _LABELS.values() for w in group}

_ZIP_RE = re.compile(r"^\d{5}(?:-\d{4})?$")
_ZIP5_RE = re.compile(r"^\d{5}$")
_PHONE_RE = re.compile(r"^\(?\d{3}\)?[-. ]?\d{3}[-. ]?\d{4}$")
_PHONE_TAIL_RE = re.compile(r"^\d{3}[-.]\d{4}$")
_DATE_RE = re.compile(r"^\d{1,2}[/-]\d{1,2}[/-]\d{2,4}$")
_STREET_SUFFIXES = (
    "ST", "STREET", "RD", "ROAD", "AVE", "AVENUE", "DR", "DRIVE", "LN",
    "LANE", "CT", "COURT", "HWY", "HIGHWAY", "BLVD", "CIR", "CIRCLE", "PL",
    "PLACE", "WAY", "TRL", "TRAIL", "PKWY", "LOOP",
)
# TEAAS crash IDs start 10x; DMV document numbers start 60x. A bare ^\d{9}$
# also matches 9-digit ZIP+4 strings (e.g. 283526345), which must NOT be
# protected - that mistake kept ZIP+4 values visible on a real binder.
_CRASH_ID_RE = re.compile(r"^(?:1\d{8}|60\d{7})$")
# DL and policy/account numbers: 7-8 or 10-14 digit runs (9-digit runs get
# their own crash-id / ZIP+4 handling below)
_DIGITS7_8_RE = re.compile(r"^\d{7,8}$|^\d{10,14}$")
_DIGITS9_RE = re.compile(r"^\d{9}$")
_ZIP4_DASH_RE = re.compile(r"^\d{5}-\d{4}$")

# Geometry bands anchored on printed field captions. Per kind:
# (width as fraction of page width, height as multiple of row height).
# Bands start at the caption and extend right/down over the value box.
_BAND_ANCHORS = {
    "driver": ("name", 0.42, 1.9),
    "owner": ("name", 0.42, 1.9),
    "insured": ("name", 0.42, 1.9),
    "witness": ("name", 0.42, 2.8),
    "witnesses": ("name", 0.42, 2.8),
    "passenger": ("name", 0.42, 2.8),
    "address": ("address", 0.42, 1.6),
    "dob": ("dob", 0.17, 1.6),
    "birth": ("dob", 0.17, 1.6),
    "dl#": ("license", 0.17, 1.6),
    "dl": ("license", 0.17, 1.6),
    "cdl": ("license", 0.17, 1.6),
    "phone": ("phone", 0.32, 2.6),
    "telephone": ("phone", 0.32, 2.6),
    "policy": ("policy", 0.22, 1.6),
}


def _norm(token: str) -> str:
    return re.sub(r"[^A-Za-z0-9#/-]", "", token).lower()


def _lines(words: list[Word]) -> list[list[Word]]:
    by_line: dict[tuple, list[Word]] = {}
    for w in words:
        by_line.setdefault((w.page,) + w.line_id, []).append(w)
    out = [sorted(ws, key=lambda w: w.left) for ws in by_line.values()]
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


def _median_height(words: list[Word]) -> int:
    hs = sorted(w.height for w in words)
    return hs[len(hs) // 2] if hs else 20


def _edit_distance_at_most(a: str, b: str, k: int) -> bool:
    """True when levenshtein(a, b) <= k (small k; early exit)."""
    if abs(len(a) - len(b)) > k:
        return False
    prev = list(range(len(b) + 1))
    for i, ca in enumerate(a, 1):
        cur = [i]
        for j, cb in enumerate(b, 1):
            cur.append(min(prev[j] + 1, cur[-1] + 1,
                           prev[j - 1] + (ca != cb)))
        if min(cur) > k:
            return False
        prev = cur
    return prev[-1] <= k


def _match_anchor(tok: str):
    """Match an OCR token against the caption anchors: exact, glued prefix
    ("OwnerJALEAH"), or fuzzy (degraded scans misread small print)."""
    spec = _BAND_ANCHORS.get(tok)
    if spec:
        return spec
    for key, s in _BAND_ANCHORS.items():
        if len(key) >= 5 and tok.startswith(key):
            return s
    for key, s in _BAND_ANCHORS.items():
        if len(key) >= 5 and len(tok) >= 4 and \
                _edit_distance_at_most(tok, key, 1):
            return s
    return None


def _band_boxes(words: list[Word], page_w: int, page_h: int,
                pad: int = 4) -> list[Redaction]:
    """Caption-anchored field bands (see module docstring)."""
    med_h = _median_height(words)
    zips = [w for w in words if _norm(w.text) == "zip"]
    out: list[Redaction] = []
    for a in words:
        spec = _match_anchor(_norm(a.text))
        if not spec:
            continue
        kind, w_frac, h_mult = spec
        h_eff = max(a.height, med_h)
        # typed values are taller than the tiny caption, so the band must
        # reach above the caption's own top or ascenders stay readable
        top = max(0, a.top - max(pad, int(0.8 * h_eff)))
        if kind == "phone":
            # "Driver's Phone Numbers" is a stacked caption; the H (home)
            # number row sits one row ABOVE the "Phone" word.
            top = max(0, a.top - int(1.4 * h_eff))
        bottom = min(page_h, a.top + int(h_mult * h_eff))
        right = min(page_w, a.left + int(w_frac * page_w))
        # keep the form's dedicated Zip box visible: clip at a "Zip" caption
        # sitting to the right of the anchor inside the band
        for z in zips:
            if a.left < z.left < right and top <= z.top <= bottom:
                right = min(right, z.left - 2)
        if right > a.left:
            out.append(Redaction(a.page, max(0, a.left - pad), top,
                                 right, bottom, f"band:{kind}"))
    return out


def _section32_boxes(words: list[Word], page_w: int,
                     page_h: int) -> list[Redaction]:
    """DMV-349 section 32, 'Names and Addresses for All Persons': a table
    whose rows carry name, DOB, and home address for every occupant and
    witness. The coded columns (seat position, injury, etc.) are crash data
    and stay visible; the DOB column and the name/address column are covered
    wholesale (handwriting-safe)."""
    med_h = _median_height(words)
    # header anchor: a token fuzzy-matching the distinctive words of
    # "Names and Addresses for All Persons" (degraded scans misread them),
    # in the lower half of the page where section 32 lives. Distance 1 only:
    # distance 2 would swallow every plain "Address" caption.
    cands = [w for w in words
             if w.top > 0.5 * page_h
             and (_edit_distance_at_most(_norm(w.text), "addresses", 1)
                  or _edit_distance_at_most(_norm(w.text), "persons", 1))]
    if not cands:
        return []
    header = min(cands, key=lambda w: w.top)
    ems = [w.top for w in words
           if w.page == header.page and _norm(w.text) == "ems"
           and w.top > header.top + 2 * med_h]
    bottom = min(min(ems) - 2 if ems else page_h,
                 header.top + int(0.26 * page_h), page_h)
    top = header.bottom + 2
    if bottom <= top:
        return []
    return [
        Redaction(header.page, int(0.125 * page_w), top,
                  int(0.25 * page_w), bottom, "section32:dob"),
        Redaction(header.page, int(0.40 * page_w), top,
                  int(0.95 * page_w), bottom, "section32:names"),
    ]


def _token_boxes(words: list[Word], keep_zip: bool,
                 pad: int = 3) -> list[Redaction]:
    """Pattern layer over individual tokens: phone numbers, 7-8 digit
    DL/policy numbers, ZIP+4 (the +4 narrows to a block face, so only the
    5-digit prefix stays visible), and DOB-aged dates.

    Date-of-birth net: the legitimate dates on a DMV-349 (crash date, DMV
    received date) all sit within a year of each other, while any DOB is
    years older. Per page, take the newest 4-digit year among date tokens
    as the report era and redact every date 2+ years older - this catches
    DOBs even when the tiny "DOB" caption fails to OCR on a poor scan."""
    out: list[Redaction] = []

    date_re = re.compile(r"^\d{1,2}[/-]\d{1,2}[/-](\d{4})$")
    years = []
    for w in words:
        m = date_re.match(w.text.strip().strip(",.;:"))
        if m:
            years.append(int(m.group(1)))
    era = max(years) if years else None

    def box(w: Word, reason: str, left: int | None = None) -> None:
        out.append(Redaction(w.page, max(0, (w.left if left is None else left) - pad),
                             max(0, w.top - pad), w.right + pad,
                             w.bottom + pad, reason))

    for w in words:
        t = w.text.strip().strip(",.;:")
        if not t or _CRASH_ID_RE.match(t):
            continue
        if _PHONE_RE.match(t) or _PHONE_TAIL_RE.match(t):
            box(w, "phone")
        elif _DIGITS7_8_RE.match(t):
            box(w, "digits7-8")
        elif _ZIP4_DASH_RE.match(t):
            if keep_zip:
                box(w, "zip+4", left=w.left + int(0.50 * w.width))
            else:
                box(w, "zip+4")
        elif _DIGITS9_RE.match(t):
            if keep_zip and t.startswith("2"):     # NC-region ZIP+4 run-on
                box(w, "zip+4", left=w.left + int(0.52 * w.width))
            else:
                box(w, "digits9")
        elif era is not None:
            m = date_re.match(t)
            if m and int(m.group(1)) <= era - 2:
                box(w, "dob-aged-date")
    return out


# form caption noise that lands inside name bands; never treat as a name
_NAME_HARVEST_STOP = {
    "FIRST", "MIDDLE", "LAST", "SUFFIX", "NAME", "NAMES", "SAME", "DRIVER",
    "DRIVERS", "OWNER", "WITNESS", "WITNESSES", "PASSENGER", "INSURED",
    "ADDRESS", "ADDRESSES", "STREET", "CITY", "STATE", "PHONE", "NUMBERS",
    "LICENSE", "CLASS", "VEHICLE", "PEDESTRIAN", "COMMERCIAL", "TOWED",
    "DESTINATON", "DESTINATION", "ABOVE", "UNIT", "YES", "NULL",
}


def harvest_name_tokens(words: list[Word], page_w: int,
                        page_h: int) -> set[str]:
    """Collect the name tokens sitting inside Driver/Owner/Witness bands so
    they can be scrubbed EVERYWHERE in the document - narratives repeat the
    driver's surname in plain prose with no caption nearby."""
    rects = [b for b in _band_boxes(words, page_w, page_h)
             if b.reason == "band:name"]
    out: set[str] = set()
    for w in words:
        t = re.sub(r"[^A-Za-z]", "", w.text).upper()
        if len(t) < 4 or t in _NAME_HARVEST_STOP:
            continue
        cx, cy = w.left + w.width // 2, w.top + w.height // 2
        if any(r.left <= cx <= r.right and r.top <= cy <= r.bottom
               for r in rects):
            out.add(t)
    return out


def plan_redactions(words: list[Word], keep_zip: bool = True,
                    pad: int = 3, page_width: int | None = None,
                    page_height: int | None = None,
                    known_names: set[str] | None = None) -> list[Redaction]:
    """Decide what to black out.

    Rules (conservative: over-redact rather than leak):

    * Caption-anchored geometry bands over every Driver/Owner/Witness/
      Address/DOB/DL/Phone/Policy field (covers handwriting OCR cannot read).
    * The section-32 names-and-addresses table (DOB + name/address columns).
    * Token patterns: phone numbers, 7-8 digit DL/policy numbers, ZIP+4
      (only the +4 part; the 5-digit ZIP stays).
    * Legacy line rules: everything AFTER a PII label on its line, plus the
      entire NEXT line when the label line holds no value; whole lines that
      look like a street address; city/state continuation lines.
    * ZIP-looking tokens are carved OUT of line-rule boxes when ``keep_zip``.
    * Crash IDs (10x/60x 9-digit) are never redacted.
    """
    if page_width is None:
        page_width = max((w.right for w in words), default=0) + 10
    if page_height is None:
        page_height = max((w.bottom for w in words), default=0) + 10
    lines = _lines(words)
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
            if value_words:
                planned.append((value_words, f"label:{label_kind}"))
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

    out.extend(_band_boxes(words, page_width, page_height))
    out.extend(_section32_boxes(words, page_width, page_height))
    out.extend(_token_boxes(words, keep_zip))
    if known_names:
        for w in words:
            t = re.sub(r"[^A-Za-z]", "", w.text).upper()
            if len(t) >= 4 and t in known_names:
                out.append(Redaction(w.page, max(0, w.left - pad),
                                     max(0, w.top - pad), w.right + pad,
                                     w.bottom + pad, "known-name"))
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
              min_conf: float = 30.0, psm: int = 11) -> list[Word]:
    """OCR one page image into word boxes via tesseract TSV."""
    tesseract = _require("tesseract")
    proc = subprocess.run(
        [tesseract, image_path, "stdout", "--psm", str(psm), "tsv"],
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


def _load_input_pages(path: str, workdir: str, dpi: int) -> tuple[list, bool]:
    """Return (PIL images, source_was_bilevel) for a PDF, multi-frame TIFF,
    or single image."""
    from PIL import Image, ImageSequence

    ext = os.path.splitext(path)[1].lower()
    if ext == ".pdf":
        return [Image.open(p).convert("RGB")
                for p in pdf_to_images(path, workdir, dpi)], False
    img = Image.open(path)
    pages, bilevel = [], True
    for frame in ImageSequence.Iterator(img):
        bilevel = bilevel and frame.mode == "1"
        pages.append(frame.convert("RGB"))
    return pages, bilevel


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
        pages, bilevel = _load_input_pages(input_path, tmp, dpi)
        report.pages = len(pages)
        # pass 1: OCR every page twice. Sparse mode (psm 11) finds isolated
        # form values, page mode (psm 3) reads flowing text and tiny captions
        # sparse mode drops. Low confidence floor: on degraded scans the
        # caption anchors come back at conf 15-30, and dropping them loses
        # whole bands; noise words only ever ADD redaction.
        ocr: list[tuple[list[Word], list[Word]]] = []
        names: set[str] = set()
        for i, img in enumerate(pages):
            page_png = os.path.join(tmp, f"ocr-{i}.png")
            img.save(page_png)
            words_sparse = ocr_words(page_png, page=i, psm=11, timeout=300,
                                     min_conf=15.0)
            words_page = ocr_words(page_png, page=i, psm=3, timeout=300,
                                   min_conf=15.0)
            if not words_sparse and not words_page:
                report.warnings.append(
                    f"page {i + 1}: no OCR text found; verify manually")
            ocr.append((words_sparse, words_page))
            pw, ph = img.size
            names |= harvest_name_tokens(words_sparse, pw, ph)
            names |= harvest_name_tokens(words_page, pw, ph)

        # pass 2: plan (each OCR pass separately; line grouping differs) and
        # draw, scrubbing every harvested name document-wide
        out_pages = []
        for i, img in enumerate(pages):
            words_sparse, words_page = ocr[i]
            pw, ph = img.size
            boxes = (plan_redactions(words_sparse, keep_zip=keep_zip,
                                     page_width=pw, page_height=ph,
                                     known_names=names)
                     + plan_redactions(words_page, keep_zip=keep_zip,
                                       page_width=pw, page_height=ph,
                                       known_names=names))
            draw = ImageDraw.Draw(img)
            for b in boxes:
                draw.rectangle([b.left, b.top, b.right, b.bottom],
                               fill="black")
                report.boxes += 1
                report.by_reason[b.reason] = report.by_reason.get(b.reason, 0) + 1
            out_pages.append(img)
        if bilevel:
            # bilevel scans stay bilevel: burned boxes are pure black, and
            # an RGB save inflates a 50-page binder past 20 MB
            out_pages = [p.convert("1") for p in out_pages]
        first, rest = out_pages[0], out_pages[1:]
        first.save(output_path, format="PDF", save_all=True,
                   append_images=rest, resolution=dpi)
    return report
