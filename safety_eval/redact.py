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
import glob
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
    conf: float = 100.0             # tesseract confidence, 0-100

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
#: captions appear in the plural on the DMV-349 persons table ("Names and
#: Addresses for All Persons"); matching only the singular skipped that whole
#: table, leaving names and street addresses in the clear (found on a real
#: report, 2026-07).
_LABEL_WORDS |= {w + "s" for w in _LABEL_WORDS}
_LABEL_WORDS |= {w + "es" for w in ("address",)}
#: the persons table lists one name + street address per row for several rows,
#: far below its caption, so the single "value sits on the next line" rule can
#: never reach them; rows are covered as a band up to the next caption.
_PERSONS_BAND_MAX = 14
#: OCR reads a page differently at different rasterizations, and a viewer may
#: render the output smaller than it was redacted at, so each convergence pass
#: re-reads the redacted page at several scales and covers the union.
_RECHECK_SCALES = (1.0, 0.75, 0.5)
#: dpi the shipped PDF is re-rendered at for the output probe; matches what
#: reviewers and ``binder.render_crash_pages`` use.
_VERIFY_DPI = 150
_PERSONS_END_WORDS = {"injured", "taken", "ems", "treatment", "facility",
                      "investigating", "officer", "signature"}

#: tesseract can be pathologically slow on some hosts (a trivial page taking
#: tens of seconds), and a binder run multiplies that by hundreds of pages.
#: The per-page ceiling is env-tunable so a slow host can be given room (or
#: failed fast) without editing code. Benchmark tesseract on a trivial image
#: before blaming the pipeline.
def _ocr_timeout() -> int:
    try:
        return int(os.environ.get("SAFETY_EVAL_OCR_TIMEOUT", "120"))
    except ValueError:
        return 120


def _label_key(token: str) -> str:
    """Normalized token, singularized so plural captions match.

    Both plural forms occur on the DMV-349 persons table: 'Names' (+s) and
    'Addresses' (+es).
    """
    t = _norm(token)
    if len(t) > 4 and t.endswith("es") and t[:-2] in _LABEL_WORDS:
        return t[:-2]
    if len(t) > 3 and t.endswith("s") and t[:-1] in _LABEL_WORDS:
        return t[:-1]
    return t


def _is_persons_header(norm_tokens: list[str]) -> bool:
    """The 'Names and Addresses for All Persons' table caption."""
    s = set(norm_tokens)
    has_name = bool(s & {"name", "names"})
    has_addr = bool(s & {"address", "addresses"})
    return has_name and has_addr and bool(s & {"persons", "person", "all"})

#: Lines that talk about who was charged. The DMV-349 charge rows repeat a
#: person's name next to the offense text, and a garbled caption or a name
#: the front-page harvest missed left one legible on a real report
#: (600504376 page 60, found 8/20/2026).
_CHARGE_CONTEXT = {"charge", "charged", "charges", "citation", "cited",
                   "violation", "violations"}
#: NC offense phrasing that may appear as the charge text itself and must
#: stay readable (it is evidence: ran stop sign vs failed to yield is what
#: the review needs). Anything alphabetic on a charge line that is not in
#: this vocabulary is treated as a name and covered; unknown words fail
#: closed.
_CHARGE_WORDS = {
    "failure", "fail", "failed", "yield", "right", "way", "stop", "sign",
    "signal", "red", "light", "ran", "run", "running", "speed", "speeding",
    "exceeding", "safe", "excessive", "reckless", "driving", "careless",
    "unsafe", "movement", "left", "center", "centerline", "improper",
    "turn", "turning", "backing", "passing", "following", "too", "closely",
    "dwi", "dui", "impaired", "alcohol", "open", "container", "license",
    "licence", "operators", "revoked", "suspended", "registration",
    "insurance", "seat", "belt", "none", "reduce", "reduced", "control",
    "vehicle", "lane", "zone", "work", "misdemeanor", "infraction",
    "pending", "yes", "no", "not", "posted", "statute", "chapter",
    # connective words so a readable charge does not end up pockmarked
    "with", "was", "were", "the", "and", "for", "any", "other", "due",
    "care", "caution", "roadway", "highway", "street", "appear",
    "comply", "expired", "inspection", "operator",
}

_ZIP_RE = re.compile(r"^\d{5}(?:-\d{4})?$")
# full numbers, and the 7-digit local form scans often show when the area
# code sits in its own box ("252 ... 214-8149")
_PHONE_RE = re.compile(r"^(?:\(?\d{3}\)?[-. ]?\d{3}[-. ]?\d{4}|\d{3}[-.]\d{4})$")
_ZIP5_RE = re.compile(r"^\d{5}$")
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
# 17-char VIN (no I/O/Q); matched anywhere because the left-column caption is
# often lost by OCR, leaving the bare VIN on the row
_VIN_RE = re.compile(r"^[A-HJ-NPR-Z0-9]{17}$")
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


def _street_span(line):
    """Just the 'number ... suffix' words of an address, not the whole line.

    Whole-line coverage was safe when the address block was the only place a
    street could appear, but narratives name roads too ("came to rest off
    MOUNT CARMEL CHURCH RD"), and blacking those lines destroys the account
    the reviewer needs. The identity blocks are covered by form geometry now,
    so this rule only has to remove the address itself.
    """
    tokens = [w.text for w in line]
    for i, tok in enumerate(tokens):
        if tok.isdigit() and not _CRASH_ID_RE.match(tok) and len(tok) <= 6:
            for j in range(i + 1, min(i + 5, len(tokens))):
                if tokens[j].upper().strip(".,") in _STREET_SUFFIXES:
                    return line[i:j + 1]
    return []


def _charge_line_names(line, norm) -> list | None:
    """Name-looking words of a charge line, or None when it is not one.

    A line counts as a charge line when it carries charge-context
    vocabulary. On it, every alphabetic token of three or more letters
    that is not offense phrasing, a form caption, or the context word
    itself is covered as a name. Empty list: a charge line with nothing
    to cover ("Charged: failure to yield").
    """
    if not set(norm) & _CHARGE_CONTEXT:
        return None
    out = []
    for w in line:
        t = _norm(w.text)
        if (t in _CHARGE_CONTEXT or t in _CHARGE_WORDS
                or t in _LABEL_WORDS or len(t) < 3
                or not any(ch.isalpha() for ch in w.text)
                or any(ch.isdigit() for ch in w.text)):
            continue
        out.append(w)
    return out


def _inside(word: Word, rects) -> bool:
    """Is a word's centre inside any of these pixel rectangles?"""
    cx = (word.left + word.right) / 2
    cy = (word.top + word.bottom) / 2
    return any(x0 <= cx <= x1 and y0 <= cy <= y1 for x0, y0, x1, y1 in rects)


def _road_token_seqs(roads) -> set[tuple[str, ...]]:
    """Study road names as normalized token tuples ('TOM BOYD' -> (TOM, BOYD))."""
    out: set[tuple[str, ...]] = set()
    for r in roads or ():
        toks = tuple(t for t in re.split(r"[^A-Za-z0-9]+", str(r).upper()) if t)
        if toks:
            out.add(toks)
    return out


def local_address_words(words: list[Word], roads,
                        addr_rects) -> list[Word]:
    """Driver/owner address words on a STUDY road, deliberately KEPT.

    A person whose address is the study road is evidence: it explains a
    driveway crash, resolves a "backed from private drive" location, and ties
    an at-address diagram to a milepost. So when the engineer supplies the
    study road names, an address row inside the driver or owner identity
    block that names one of those roads keeps its street span (house number,
    road tokens, street suffix) while the rest of the block stays covered.

    Scope is deliberately narrow: only the driver-identity and owner-identity
    zones (``addr_rects``), never the persons table (occupants, including
    minors), and only the matched span, because a visual row crosses both
    unit columns and the other driver's address must not ride along.
    """
    seqs = _road_token_seqs(roads)
    if not seqs or not addr_rects:
        return []
    keep: list[Word] = []
    for row in _visual_rows(words):
        inz = [w for w in row if _inside(w, addr_rects)]
        if not inz:
            continue
        toks = [w.text.strip().strip(".,;:").upper() for w in inz]
        spans: list[tuple[int, int]] = []
        for seq in seqs:
            n = len(seq)
            for i in range(len(toks) - n + 1):
                if tuple(toks[i:i + n]) != seq:
                    continue
                j0, j1 = i, i + n
                if j0 > 0 and toks[j0 - 1].isdigit() and len(toks[j0 - 1]) <= 6:
                    j0 -= 1
                if j1 < len(toks) and toks[j1] in _STREET_SUFFIXES:
                    j1 += 1
                spans.append((j0, j1))
        for j0, j1 in spans:
            keep.extend(inz[j0:j1])
    return keep


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
                _edit_distance_at_most(tok, key, 1 if len(key) < 6 else 2):
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
        # sitting to the right of the anchor inside the band. Only a
        # confident "Zip" may shrink a band - preserving visibility demands
        # confidence, adding coverage does not.
        for z in zips:
            if z.conf < 40:
                continue
            if a.left < z.left < right and top <= z.top <= bottom:
                right = min(right, z.left - 2)
        if right > a.left:
            out.append(Redaction(a.page, max(0, a.left - pad), top,
                                 right, bottom, f"band:{kind}"))
    return out


def _sub_caption_boxes(words: list[Word], page_w: int, page_h: int,
                       pad: int = 4) -> list[Redaction]:
    """Structural anchor: on the DMV-349 the typed name row sits directly
    ABOVE a "First   Middle   Last   Suffix" sub-caption row. When the
    Driver/Owner caption itself is misread beyond fuzzy reach ("Dnver"),
    this row still locates the name."""
    med_h = _median_height(words)
    firsts = [w for w in words
              if _edit_distance_at_most(_norm(w.text), "first", 1)]
    mids = [w for w in words
            if _edit_distance_at_most(_norm(w.text), "middle", 1)]
    out: list[Redaction] = []
    for f in firsts:
        for m in mids:
            if m.left > f.left and abs(m.top - f.top) <= 1.5 * med_h \
                    and m.left - f.left < 0.35 * page_w:
                h_eff = max(f.height, med_h)
                out.append(Redaction(
                    f.page,
                    max(0, f.left - int(0.10 * page_w)),
                    max(0, f.top - int(3.0 * h_eff)),
                    min(page_w, m.left + int(0.30 * page_w)),
                    max(0, f.top - 2),
                    "name-above-subcaption"))
                break
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
            if keep_zip and w.conf >= 40:
                box(w, "zip+4", left=w.left + int(0.50 * w.width))
            else:
                box(w, "zip+4")
        elif _DIGITS9_RE.match(t):
            # partial keep (5-digit prefix) only for a confident read
            if keep_zip and t.startswith("2") and w.conf >= 40:
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
    rects += _sub_caption_boxes(words, page_w, page_h)
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


def plan_redactions(words: list[Word], keep_zip: bool = True, pad: int = 3,
                    identity_rects=None, local_keep=(),
                    page_width: int | None = None,
                    page_height: int | None = None,
                    known_names: set[str] | None = None) -> list[Redaction]:
    """Decide what to black out.

    What this is FOR: the identifying information of the people involved in
    the crash, and nothing else. The diagram, the narrative, the On Road /
    From Road / Toward Road fields, the coded grid and the location block are
    evidence, and blacking any of them out destroys the thing the review is
    for. ZIP codes stay by request.

    Rules:

    * A line containing a PII field label: everything AFTER the label on that
      line, plus the entire NEXT line when the label line holds no value
      (DMV-349 boxes put the caption above the handwritten/typed value).
    * The persons-table band under its caption, which is all names and
      addresses by construction.
    * A charge line: the offense text stays (it is evidence), the charged
      person's name is covered.
    * Street-address, phone and VIN PATTERNS only where the people's data
      lives: inside ``identity_rects`` (from ``form_geometry.zone_rects``).
      These fired page-wide once, which blacked out addresses in the narrative
      and location block -- exactly the artifact an engineer uses to
      re-milepost a crash ("placed at address"). An uncaptioned street name
      outside the identity block is a road, not a person.
    * Caption-anchored geometry bands over every Driver/Owner/Witness/
      Address/DOB/DL/Phone/Policy caption (they cover handwriting OCR cannot
      read), the name row above a First/Middle sub-caption, and the
      section-32 names-and-addresses table (DOB and name/address columns).
      These are sized from ``page_width`` and ``page_height``, estimated
      from the words when the caller does not know the page.
    * Token patterns: phone numbers, 7-8 and 10-14 digit DL/policy numbers,
      ZIP+4 (only the +4 part; the 5-digit ZIP stays) and dates two or more
      years older than the report era (a DOB whose caption OCR lost).
    * ``known_names`` (harvested from the identity bands, see
      :func:`harvest_name_tokens`) are covered wherever they appear,
      narrative included.
    * ZIP-looking tokens are carved OUT of any planned box when ``keep_zip``.
    * Crash IDs (10x/60x 9-digit) are never redacted.
    * ``local_keep`` words (study-road addresses from
      :func:`local_address_words`) are carved out the same way ZIPs are,
      geometry bands included.
    """
    if page_width is None:
        page_width = max((w.right for w in words), default=0) + 10
    if page_height is None:
        page_height = max((w.bottom for w in words), default=0) + 10
    zones = list(identity_rects or ())
    kept_ids = {id(w) for w in local_keep}
    lines = _visual_rows(words)
    planned: list[tuple[list[Word], str]] = []
    redact_next_line_of: dict[tuple, str] = {}
    address_continues_from: int | None = None
    persons_band_until: int = -1

    for idx, line in enumerate(lines):
        tokens = [w.text for w in line]
        norm = [_norm(t) for t in tokens]

        # persons table: every row under the caption carries a name and a
        # street address, so cover the band until the next form caption
        if idx <= persons_band_until:
            if set(norm) & _PERSONS_END_WORDS:
                persons_band_until = -1
            elif any(len(t) >= 3 and any(c.isalpha() for c in t)
                     for t in tokens):
                planned.append((line, "persons-table"))
                continue
        if _is_persons_header(norm):
            persons_band_until = idx + _PERSONS_BAND_MAX
            continue

        # a charge line: the offense text stays (it is evidence), and any
        # other alphabetic token is treated as the charged person's name.
        # This does not lean on the caption or the harvest, both of which
        # failed on a real page; unknown words fail closed.
        sus = _charge_line_names(line, norm)
        if sus is not None:
            if sus:
                planned.append((sus, "charge-line-name"))
            continue

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
        for i, tok in enumerate(tokens):
            key = _label_key(tok)
            for kind, keys in _LABELS.items():
                if key in keys:
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
                if all(len(_norm(w.text)) <= 2 or _norm(w.text).isdigit()
                       for w in before_words):
                    # nothing but a form field number sat beside the caption
                    # ("86 Type/Owner"), so the value lives on the following
                    # line; without this the property owner's name survived
                    # (600504376 pages 12 and 20)
                    redact_next_line_of[("pending", idx + 1)] = \
                        f"label:{label_kind}(below)"
            else:
                # caption-only line: value sits on the following line
                redact_next_line_of[("pending", idx + 1)] = f"label:{label_kind}(below)"
            if label_kind == "address":
                address_continues_from = idx + 1
            continue

        # Pattern rules are a backstop for a caption the OCR lost, so they run
        # only where the people's data is. Outside the identity zones a
        # "number + street suffix" is the crash location, not an occupant.
        span = _street_span(line)
        if span and zones and all(_inside(w, zones) for w in span):
            planned.append((span, "street-address"))
            address_continues_from = idx + 1
            continue

        for w in line:
            if zones and not _inside(w, zones):
                continue
            if _PHONE_RE.match(w.text.strip()):
                planned.append(([w], "phone"))
            elif _VIN_RE.match(w.text.strip()) and \
                    not w.text.strip().isdigit():
                planned.append(([w], "vin-pattern"))

    out: list[Redaction] = []
    for group, reason in planned:
        segments = _split_keeping_zip(group, keep_zip, kept_ids)
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

    # geometry layers (caption bands, the row above a First/Middle
    # sub-caption, section 32) and the token patterns. The words that stay
    # visible by design, a confident ZIP and the study-road address the
    # engineer asked for, are carved out of the bands the same way the zone
    # rectangles are split in redact_file.
    geo = (_band_boxes(words, page_width, page_height)
           + _sub_caption_boxes(words, page_width, page_height)
           + _section32_boxes(words, page_width, page_height))
    holes = [(w.left, w.top, w.right, w.bottom) for w in local_keep]
    if keep_zip:
        holes += [(w.left, w.top, w.right, w.bottom) for w in words
                  if _ZIP5_RE.match(w.text.strip().strip(".,;:"))
                  and w.conf >= 40]
    out.extend(_carve(geo, holes))
    out.extend(_token_boxes(words, keep_zip))
    if known_names:
        for w in words:
            t = re.sub(r"[^A-Za-z]", "", w.text).upper()
            if len(t) >= 4 and t in known_names:
                out.append(Redaction(w.page, max(0, w.left - pad),
                                     max(0, w.top - pad), w.right + pad,
                                     w.bottom + pad, "known-name"))
    return out


def _carve(boxes: list[Redaction], holes) -> list[Redaction]:
    """Split geometry boxes around the words that stay visible."""
    if not holes:
        return list(boxes)
    from .form_geometry import rect_minus

    out: list[Redaction] = []
    for b in boxes:
        page_holes = [h for h in holes
                      if h[0] < b.right and h[2] > b.left
                      and h[1] < b.bottom and h[3] > b.top]
        if not page_holes:
            out.append(b)
            continue
        for x0, y0, x1, y1 in rect_minus((b.left, b.top, b.right, b.bottom),
                                         page_holes):
            out.append(Redaction(b.page, x0, y0, x1, y1, b.reason))
    return out


def _split_keeping_zip(group: list[Word], keep_zip: bool,
                       kept_ids=frozenset()) -> list[list[Word]]:
    """Split a planned group around the words that stay visible.

    Splitting, not filtering: a persons-row group is boxed by min/max extent,
    so merely dropping a kept word from the middle would leave it covered by
    the box spanning its neighbours.
    """
    segments: list[list[Word]] = []
    current: list[Word] = []
    for w in group:
        # carving a hole to keep a ZIP visible demands a confident read
        if ((keep_zip and _ZIP_RE.match(w.text.strip()) and w.conf >= 40)
                or id(w) in kept_ids):
            if current:
                segments.append(current)
                current = []
            continue                      # stays visible
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


def ocr_words(image_path: str, page: int = 0, timeout: int | None = None,
              min_conf: float = 30.0, psm: int = 11) -> list[Word]:
    """OCR one page image into word boxes via tesseract TSV.

    ``timeout`` defaults to SAFETY_EVAL_OCR_TIMEOUT (seconds, default 120),
    read at call time so a long process or a test can adjust it. ``psm`` is
    the tesseract page segmentation mode: 11 (sparse, the default) finds
    isolated form values, 3 (page) reads flowing text and the tiny captions
    sparse mode drops.
    """
    tesseract = _require("tesseract")
    # one OpenMP thread per tesseract process: the callers parallelise across
    # pages, and oversubscribed OMP threads make every page many times slower
    env = {**os.environ, "OMP_THREAD_LIMIT": "1"}
    proc = subprocess.run(
        [tesseract, image_path, "stdout", "--psm", str(psm), "tsv"],
        capture_output=True, text=True,
        timeout=timeout if timeout is not None else _ocr_timeout(),
        check=True, env=env)
    words: list[Word] = []
    # QUOTE_NONE is load-bearing: tesseract TSV never quotes, and default
    # csv quoting makes a stray OCR'd " glyph swallow every following row
    # into one mega-token that hides names from the planner
    reader = csv.DictReader(io.StringIO(proc.stdout), delimiter="\t",
                            quoting=csv.QUOTE_NONE)
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
            conf=conf,
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


def _open_image(path: str):
    from PIL import Image
    return Image.open(path)


def _groups_to_boxes(groups, keep_zip: bool, pad: int = 3,
                     kept_ids=frozenset()) -> list[Redaction]:
    """Word groups -> boxes, preserving ZIPs and crash IDs (as planning does)."""
    out: list[Redaction] = []
    for group, reason in groups:
        for seg in _split_keeping_zip(group, keep_zip, kept_ids):
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


def redact_file(input_path: str, output_path: str, keep_zip: bool = True,
                dpi: int = 200, passes: int = 3,
                local_roads=None) -> RedactionReport:
    """Redact a crash-report file into an image-only PDF.

    One pass leaves whatever that pass's OCR did not resolve, and OCR results
    change with the raster scale. ``passes`` therefore re-reads the REDACTED
    page (at several scales) and finally the written PDF rendered the way a
    consumer renders it, covering anything the verifier can still read. The
    planner and the verifier share their predicates, so what the verifier can
    find, the redactor covers.

    ``local_roads``: study road names; a driver or owner address on one of
    them stays readable (see :func:`local_address_words`).

    Returns an audit report (counts and reasons only; the PII itself is never
    echoed anywhere).
    """
    from PIL import ImageDraw

    from . import form_geometry as fg

    report = RedactionReport()
    with tempfile.TemporaryDirectory(prefix="redact-") as tmp:
        pages, bilevel = _load_input_pages(input_path, tmp, dpi)
        report.pages = len(pages)

        # Phase 1: read every page, register the front pages against the
        # DMV-349 layout and harvest the person names out of the identity
        # zones BEFORE anything is covered. The names are what lets the
        # narrative stay readable with the people taken out of it.
        #
        # Two OCR passes per page: sparse mode (psm 11) finds isolated form
        # values, page mode (psm 3) reads flowing text and the tiny captions
        # sparse mode drops. Zero confidence floor: a real caption can come
        # back at conf 1 (p39 "Owner" did) and losing it loses the whole
        # band; noise words only ever ADD redaction, and anything that
        # preserves visibility (ZIP and study-road keeps) demands conf >= 40
        # on its own.
        page_words: list[list] = []
        page_words_full: list[list] = []
        page_reg: list[tuple[float, float] | None] = []
        # A binder holds several reports. Names are scoped to the report they
        # were harvested from, so one driver's surname cannot black out
        # another crash's text; place names from any header or location block
        # are never scrubbed at all.
        page_names: list[set] = []
        page_band_names: list[set] = []
        protected: set[str] = set()
        loc_words: set[str] = set()
        current: set[str] | None = None
        band_current: set[str] = set()
        for i, img in enumerate(pages):
            page_png = os.path.join(tmp, f"ocr-{i}.png")
            img.save(page_png)
            words = ocr_words(page_png, page=i, psm=11, min_conf=0.0)
            words_page = ocr_words(page_png, page=i, psm=3, min_conf=0.0)
            page_words.append(words)
            page_words_full.append(words_page)
            if not words and not words_page:
                report.warnings.append(
                    f"page {i + 1}: no OCR text found; verify manually")
            protected |= fg.location_vocabulary(words, img.height)
            reg = None
            if words and fg.is_front_page(words):
                reg = fg.register(words, img.height)
                current = fg.harvest_names(words, img.width, img.height, reg)
                band_current = set()
            page_reg.append(reg)
            page_names.append(current or set())
            # caption-band harvest: the names sitting in the Driver/Owner/
            # Witness bands, scrubbed wherever they recur in the report
            band_current |= harvest_name_tokens(words, img.width, img.height)
            band_current |= harvest_name_tokens(words_page, img.width,
                                                img.height)
            page_band_names.append(band_current)
            # the DMV-349 location block (municipality, routes) sits in the
            # top fifth of the form; anything appearing there is a place
            # word, and scrubbing it would black the crash location on
            # every page (e.g. SPRINGS from a RED SPRINGS home address)
            for w in words + words_page:
                if w.top < 0.20 * img.height:
                    loc_words.add(re.sub(r"[^A-Za-z]", "", w.text).upper())
        # the engineer's study roads are places, never people: a driver who
        # shares a surname with the road must not black the road's name out
        # of narratives and location lines ("SIKES MILL RD", observed)
        protected |= {t for seq in _road_token_seqs(local_roads or ())
                      for t in seq}
        page_names = [n - protected for n in page_names]
        page_band_names = [n - protected - loc_words for n in page_band_names]
        harvested = len(set().union(*page_names, *page_band_names)) \
            if page_names else 0
        if harvested:
            report.by_reason["harvested-names"] = harvested

        out_pages = []
        page_zone_rects: list[list] = []
        page_addr_rects: list[list] = []
        for i, img in enumerate(pages):
            words = page_words[i]
            words_page = page_words_full[i]
            # Where the occupants' data sits on THIS page. The address, phone
            # and VIN pattern rules are scoped to it, so the narrative, the
            # location block and the coded grid are never touched by them.
            zoned = (fg.zone_rects(img.width, img.height, page_reg[i])
                     if page_reg[i] is not None else [])
            ident = [r for _, r in zoned]
            addr_rects = [r for z, r in zoned
                          if z.name in ("driver-identity", "owner-identity")]
            page_zone_rects.append(ident)
            page_addr_rects.append(addr_rects)
            local_keep = local_address_words(words, local_roads, addr_rects)
            local_keep_page = local_address_words(words_page, local_roads,
                                                  addr_rects)
            if local_keep:
                report.by_reason["local-address-kept"] = (
                    report.by_reason.get("local-address-kept", 0)
                    + len(local_keep))
            # plan each OCR pass separately (line grouping differs)
            boxes = plan_redactions(words, keep_zip=keep_zip,
                                    identity_rects=ident,
                                    local_keep=local_keep,
                                    page_width=img.width,
                                    page_height=img.height,
                                    known_names=page_band_names[i])
            boxes += plan_redactions(words_page, keep_zip=keep_zip,
                                     identity_rects=ident,
                                     local_keep=local_keep_page,
                                     page_width=img.width,
                                     page_height=img.height,
                                     known_names=page_band_names[i])
            # geometry zones: cover the identity blocks by position, whatever
            # OCR made of their captions
            if page_reg[i] is not None:
                # ZIPs are kept even inside a covered zone (they locate the
                # crash without identifying anyone), so each zone is split
                # around the ZIP tokens that fall in it.
                # ZIP holes are found once per page, not per zone: an
                # address row can straddle a zone boundary, and a ZIP must
                # survive whichever zone happens to cover it. Only a
                # confident read may open a hole.
                zip_keep = ([w for w in
                             fg.zip_words(words)
                             + fg.zip_field_words(words, img.width,
                                                  img.height, page_reg[i])
                             if w.conf >= 40]
                            if keep_zip else [])
                zip_holes = [(w.left, w.top, w.right, w.bottom)
                             for w in zip_keep + local_keep + local_keep_page]
                for z, rect in fg.zone_rects(img.width, img.height,
                                             page_reg[i]):
                    holes = zip_holes
                    for piece in fg.rect_minus(rect, holes):
                        boxes.append(Redaction(
                            page=i, left=piece[0], top=piece[1],
                            right=piece[2], bottom=piece[3],
                            reason=f"zone:{z.name}"))
            # scrub harvested names anywhere they appear, narrative included
            for w in (fg.scrub_targets(words, page_names[i])
                      + fg.scrub_targets(words_page, page_names[i])):
                boxes.append(Redaction(
                    page=i, left=max(0, w.left - 2), top=max(0, w.top - 2),
                    right=w.right + 2, bottom=w.bottom + 2,
                    reason="name-in-text"))
            draw = ImageDraw.Draw(img)
            for b in boxes:
                draw.rectangle([b.left, b.top, b.right, b.bottom],
                               fill="black")
                report.boxes += 1
                report.by_reason[b.reason] = report.by_reason.get(b.reason, 0) + 1
            # convergence: cover what the verifier can still read, probing
            # several scales because OCR is scale sensitive
            for extra in range(max(0, passes - 1)):
                again: list[Redaction] = []
                for scale in _RECHECK_SCALES:
                    probe = img if scale == 1.0 else img.resize(
                        (max(1, int(img.width * scale)),
                         max(1, int(img.height * scale))))
                    rp = os.path.join(tmp, f"recheck-{i}-{extra}-{scale}.png")
                    probe.save(rp)
                    # the probe is resampled, so the identity zones must be
                    # too, or the scope would drift off the boxes it guards
                    zs = ([(int(x0 * scale), int(y0 * scale),
                            int(x1 * scale), int(y1 * scale))
                           for x0, y0, x1, y1 in ident]
                          if scale != 1.0 else ident)
                    azs = ([(int(x0 * scale), int(y0 * scale),
                             int(x1 * scale), int(y1 * scale))
                            for x0, y0, x1, y1 in addr_rects]
                           if scale != 1.0 else addr_rects)
                    for b in _groups_to_boxes(
                            _residual_groups(ocr_words(rp, page=i), keep_zip,
                                             zs, local_roads=local_roads,
                                             addr_rects=azs),
                            keep_zip):
                        again.append(b if scale == 1.0 else Redaction(
                            page=b.page, left=int(b.left / scale),
                            top=int(b.top / scale), right=int(b.right / scale),
                            bottom=int(b.bottom / scale), reason=b.reason))
                if not again:
                    break
                draw = ImageDraw.Draw(img)
                for b in again:
                    draw.rectangle([b.left, b.top, b.right, b.bottom],
                                   fill="black")
                    report.boxes += 1
                    key = f"residual:{b.reason}"
                    report.by_reason[key] = report.by_reason.get(key, 0) + 1
            out_pages.append(img)

        def _write() -> None:
            # bilevel scans stay bilevel: burned boxes are pure black, and
            # an RGB save inflates a 50-page binder past 20 MB
            saved = ([p.convert("1") for p in out_pages] if bilevel
                     else out_pages)
            first, rest = saved[0], saved[1:]
            first.save(output_path, format="PDF", save_all=True,
                       append_images=rest, resolution=dpi)

        _write()
        # final closure: rasterizing the PDF is not the same as resizing in
        # memory, so probe the artifact we actually ship
        for _ in range(max(0, passes - 1)):
            probe_dir = os.path.join(tmp, "probe")
            shutil.rmtree(probe_dir, ignore_errors=True)
            os.makedirs(probe_dir, exist_ok=True)
            try:
                subprocess.run([_require("pdftoppm"), "-png", "-r",
                                str(_VERIFY_DPI), output_path,
                                os.path.join(probe_dir, "v")],
                               check=True, capture_output=True, timeout=600)
            except (subprocess.SubprocessError, RuntimeError, OSError):
                break
            renders = sorted(glob.glob(os.path.join(probe_dir, "v*.png")))
            # the shipped PDF is rasterized at _VERIFY_DPI, so rescale the
            # zones from the working dpi to keep the same scope
            k = _VERIFY_DPI / float(dpi or _VERIFY_DPI)
            probe_zones = [[(int(x0 * k), int(y0 * k), int(x1 * k), int(y1 * k))
                            for x0, y0, x1, y1 in z] for z in page_zone_rects]
            probe_addr = [[(int(x0 * k), int(y0 * k), int(x1 * k), int(y1 * k))
                           for x0, y0, x1, y1 in z] for z in page_addr_rects]
            found = residual_pii(renders, keep_zip=keep_zip,
                                 identity_rects=probe_zones,
                                 local_roads=local_roads,
                                 addr_rects=probe_addr)
            if not found:
                break
            for f in found:
                if not 1 <= f.page <= len(out_pages):
                    continue
                img = out_pages[f.page - 1]
                with _open_image(renders[f.page - 1]) as r:
                    sx, sy = img.width / r.width, img.height / r.height
                ImageDraw.Draw(img).rectangle(
                    [int(f.left * sx), int(f.top * sy),
                     int(f.right * sx), int(f.bottom * sy)], fill="black")
                report.boxes += 1
                key = f"output-probe:{f.reason}"
                report.by_reason[key] = report.by_reason.get(key, 0) + 1
            _write()
        else:
            if passes > 1:
                report.warnings.append(
                    "output still shows PII after the probe passes; verify "
                    "manually before release")
    return report


# --------------------------------------------------------------------------- #
# post-redaction verification (fail closed)
# --------------------------------------------------------------------------- #
@dataclass
class ResidualFinding:
    """A PII-looking region that SURVIVED redaction. Carries no text: the
    whole point is not to copy the value anywhere."""
    page: int
    reason: str
    left: int
    top: int
    right: int
    bottom: int


def residual_pii(image_paths: list[str], keep_zip: bool = True,
                 identity_rects=None, local_roads=None,
                 addr_rects=None) -> list[ResidualFinding]:
    """Re-OCR redacted page images and report PII that is still legible.

    Redaction is OCR-driven, so a caption the OCR misses leaves its value in
    the clear (observed on a real DMV-349: the plural 'Names and Addresses'
    caption). This is the check that catches that class of miss before a page
    reaches a human or a model. Findings carry coordinates and a reason only,
    never the offending text.

    The verifier shares the planner's scope, or it would report the crash
    location in the narrative as a leak and block a page that is correctly
    redacted. ``identity_rects`` is per page; pass None for a page whose
    layout could not be registered.
    """
    out: list[ResidualFinding] = []
    for page_no, path in enumerate(image_paths, 1):
        words = ocr_words(path, page=page_no)
        rects = None
        if identity_rects:
            rects = (identity_rects[page_no - 1]
                     if page_no - 1 < len(identity_rects) else None)
        arects = None
        if addr_rects:
            arects = (addr_rects[page_no - 1]
                      if page_no - 1 < len(addr_rects) else None)
        for group, reason in _residual_groups(words, keep_zip, rects,
                                              local_roads=local_roads,
                                              addr_rects=arects):
            left = min(w.left for w in group)
            top = min(w.top for w in group)
            right = max(w.left + w.width for w in group)
            bottom = max(w.top + w.height for w in group)
            out.append(ResidualFinding(page_no, reason, left, top,
                                       right, bottom))
    return out


def _residual_groups(words: list[Word], keep_zip: bool, identity_rects=None,
                     local_roads=None, addr_rects=None):
    """Lines of a redacted page that still look like PII.

    Scoped exactly like ``plan_redactions``: a street address or phone number
    only counts as residual PII where the occupants' data lives. A street name
    in the narrative is the crash location, and a driver or owner address on a
    study road (``local_roads`` within ``addr_rects``) is kept by design, so
    neither is a finding.
    """
    zones = list(identity_rects or ())
    kept = ({id(w) for w in local_address_words(words, local_roads,
                                                addr_rects or ())}
            if local_roads else set())
    for line in _visual_rows(words):
        tokens = [w.text for w in line]
        norm = [_norm(t) for t in tokens]
        sus = _charge_line_names(line, norm)
        if sus is not None:
            if sus:
                yield sus, "charge-line name survived"
            continue
        span = _street_span(line)
        if span and zones and all(_inside(w, zones) for w in span):
            span = [w for w in span if id(w) not in kept]
            if span:
                yield span, "street-address survived"
            continue
        if _looks_like_city_line(tokens) and not keep_zip:
            yield line, "city/state/zip survived"
            continue
        for w in line:
            if zones and not _inside(w, zones):
                continue
            t = w.text.strip()
            if _PHONE_RE.match(t):
                yield [w], "phone survived"
            elif _VIN_RE.match(t) and not t.isdigit():
                yield [w], "vin survived"
        # a date sitting next to a date-of-birth caption
        if set(norm) & set(_LABELS["dob"]):
            for w in line:
                if _DATE_RE.match(w.text.strip()):
                    yield [w], "date beside a DOB caption survived"


def verify_redaction(image_paths: list[str], keep_zip: bool = True,
                     local_roads=None, addr_rects=None) -> None:
    """Raise if any PII survived redaction (fail closed).

    Call before a redacted page is shown to a reviewer or sent to a model.
    """
    findings = residual_pii(image_paths, keep_zip=keep_zip,
                            local_roads=local_roads, addr_rects=addr_rects)
    if findings:
        counts: dict[str, int] = {}
        for f in findings:
            counts[f.reason] = counts.get(f.reason, 0) + 1
        raise RedactionIncomplete(
            "Redaction verification failed; PII is still legible: "
            + ", ".join(f"{k} x{v}" for k, v in sorted(counts.items()))
            + ". Review the page manually; do not release it.")


class RedactionIncomplete(RuntimeError):
    """Raised when a redacted page still shows PII."""
