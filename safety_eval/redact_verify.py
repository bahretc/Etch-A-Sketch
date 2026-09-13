"""Independent verification of a redacted crash report (docs/07 phase 3).

:func:`redact_file` decides what to black out from the OCR of the original.
This module checks the OUTPUT the same way a reviewer would: it OCRs the
redacted pages (two tesseract modes), builds an oracle of personal tokens
from the original (names inside the driver/owner/witness bands, dates of
birth, phone numbers, licence and policy numbers, street addresses) and
searches the redacted text for any of them. The result is a verification
record with masked tokens only; the PII itself never leaves the process.

A clean verification is what the redaction certificate in the package
notes rests on; a leak is reported with the page so the engineer can fix
the scan or the planner before anything is shared.
"""
from __future__ import annotations

import os
import re
import subprocess
import tempfile
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass, field

from .redact import (_NAME_HARVEST_STOP, _band_boxes, _line_has_street_address, _lines, _load_input_pages,
                     _median_height, _require, _sub_caption_boxes, ocr_words)

_NAME_STOP = _NAME_HARVEST_STOP | {"SAME", "NONE", "NULL", "SELF", "OWNER", "DRIVER", "MALE", "FEMALE", "WHITE",
                                   "BLACK", "OTHER", "HOME", "WORK", "CELL", "NAME", "FIRST", "LAST", "MIDDLE"}

# form vocabulary and generic words that appear on every DMV-349; never PII
_ADDRESS_STOP = {
    "NORTH", "SOUTH", "EAST", "WEST", "ROAD", "STREET", "DRIVE", "LANE", "HIGHWAY", "AVENUE", "CIRCLE",
    "COURT", "BOULEVARD", "TRAIL", "PLACE", "ROUTE", "TRAILER", "TRAILERS", "TRAFFIC", "PARKED",
    "NARRATIVE", "TRAVELING", "RIGHT", "LEFT", "NATIONAL", "PAPERS", "REPORTABLE", "NONREPORTABLE",
    "NONCONTACT", "VEHICLE", "DRIVER", "OWNER", "ADDRESS", "PHONE", "NUMBER", "STATE", "CITY", "COUNTY",
    "MILES", "FEET", "INTERSECTION", "APPROX", "UNKNOWN", "SAME", "ABOVE", "BELOW", "TOTAL", "DATE",
    "TIME", "NORTHBOUND", "SOUTHBOUND", "EASTBOUND", "WESTBOUND", "APARTMENT", "SUITE", "MOBILE",
}
_HOUSE_NO_RE = re.compile(r"^\d{2,6}[A-Z]?$")

_DATE_RE = re.compile(r"\b(0?[1-9]|1[0-2])/(0?[1-9]|[12]\d|3[01])/((?:19|20)\d{2})\b")
_PHONE_RE = re.compile(r"\(?\d{3}\)?[\s.-]?\d{3}[\s.-]\d{4}")
_ID_RE = re.compile(r"\b\d{7,9}\b")


def _mask(tok: str) -> str:
    if len(tok) <= 3:
        return "*" * len(tok)
    return tok[:2] + "*" * (len(tok) - 2)


@dataclass
class RedactionVerification:
    pages: int = 0
    oracle_size: int = 0
    leaks: list = field(default_factory=list)      # (page, kind, masked token)
    patterns: list = field(default_factory=list)   # (page, kind, masked text) generic hits
    warnings: list = field(default_factory=list)

    @property
    def clean(self) -> bool:
        return not self.leaks and not self.patterns

    def summary(self) -> str:
        if self.clean:
            return (f"Verified clean: {self.pages} page(s) re-read by OCR, {self.oracle_size} personal "
                    "tokens from the original searched, none found, no phone or date-of-birth patterns remain.")
        return (f"{len(self.leaks)} oracle hit(s) and {len(self.patterns)} pattern hit(s) on "
                f"{sorted({p for p, _, _ in self.leaks + self.patterns})}; see details.")


OCR_TIMEOUT = 900
WORKERS = max(1, (os.cpu_count() or 2) // 2)


def _ocr_text(png: str, timeout: int = OCR_TIMEOUT) -> str:
    tesseract = _require("tesseract")
    out = ""
    for psm in ("3", "11"):
        r = subprocess.run([tesseract, png, "stdout", "--psm", psm], capture_output=True, text=True,
                           timeout=timeout, env={**os.environ, "OMP_THREAD_LIMIT": "1"})
        out += "\n" + r.stdout
    return out.upper()


def _band_names(words, pw: int, ph: int) -> set[str]:
    """Name tokens inside the driver/owner/witness bands; four letter tokens
    only when OCR is confident (short low confidence tokens are fragments)."""
    rects = [b for b in _band_boxes(words, pw, ph) if b.reason == "band:name"]
    rects += _sub_caption_boxes(words, pw, ph)
    out: set[str] = set()
    for w in words:
        t = re.sub(r"[^A-Za-z]", "", w.text).upper()
        # printed names come back at high confidence; low confidence short tokens are
        # fragments or misread captions ("Typer" for "Type/")
        if len(t) < 4 or t in _NAME_STOP or w.conf < 50 or (len(t) == 4 and w.conf < 60):
            continue
        cx, cy = w.left + w.width // 2, w.top + w.height // 2
        if any(r.left <= cx <= r.right and r.top <= cy <= r.bottom for r in rects):
            out.add(t)
    return out


def _oracle_page(png: str, i: int, pw: int, ph: int) -> dict:
    out = {"name": set(), "phone": set(), "address": set(), "id": set(), "loc": set(), "years": [], "all": set()}
    for psm in (11, 3):
        words = ocr_words(png, page=i, psm=psm, timeout=OCR_TIMEOUT, min_conf=0.0)
        out["name"] |= _band_names(words, pw, ph)
        for w in words:                    # every token on the page, for the form-vocabulary rule
            out["all"].add(re.sub(r"[^A-Za-z]", "", w.text).upper())
            out["all"].add(re.sub(r"\D", "", w.text))
        for w in words:
            if w.top < 0.25 * ph:          # location block: routes, crash id, dates, coordinates
                out["loc"].add(re.sub(r"[^A-Za-z]", "", w.text).upper())
                out["loc"].add(re.sub(r"\D", "", w.text))
        text = " ".join(w.text for w in words)
        for m in _DATE_RE.finditer(text):
            out["years"].append(int(m.group(3)))
        for m in _PHONE_RE.finditer(text):
            out["phone"].add(re.sub(r"\D", "", m.group(0))[-7:])
        med_h = _median_height(words) or 1
        for line in _lines(words):
            toks = [w.text for w in line]
            if not _line_has_street_address(toks):
                continue
            clean = [re.sub(r"[^A-Za-z0-9]", "", t).upper() for t in toks]
            # typed values are body height; the form's tiny field numerals ("39 Results") are not
            house_idx = [k for k, c in enumerate(clean)
                         if _HOUSE_NO_RE.match(c) and len(c) >= 3 and line[k].height >= 0.7 * med_h]
            for k in house_idx:
                out["address"].add(clean[k])       # the house number itself
                for c in clean[k + 1:k + 4]:          # the street name follows it
                    if len(c) >= 5 and c.isalpha() and c not in _ADDRESS_STOP:
                        out["address"].add(c)
        for line in _lines(words):
            # citation numbers on the charges line are not personal identifiers and stay visible
            if any(re.sub(r"[^A-Za-z]", "", w.text).upper().startswith(("CHARGE", "CITATION")) for w in line):
                continue
            for w in line:
                raw = w.text.strip().strip(",;:")
                # licence, policy and similar numbers print as plain digit runs (a hyphen at most);
                # dates, coordinates and decimals never count
                if w.conf >= 40 and re.fullmatch(r"\d[\d-]{5,8}\d", raw) and _ID_RE.fullmatch(re.sub(r"\D", "", raw)):
                    out["id"].add(re.sub(r"\D", "", raw))
    # date of birth: on THIS page, any date three or more years before the page's own era
    # (a binder holds reports from several years; the document era would flag old crash dates)
    dates = [m.group(0) for m in _DATE_RE.finditer(_ocr_text(png))]
    years = [int(d.split("/")[-1]) for d in dates] + out["years"]
    era = max(years) if years else None
    out["dob"] = {d for d in dates if era and int(d.split("/")[-1]) <= era - 3}
    return out


def build_oracle(original_path: str, dpi: int = 200, workers: int = WORKERS, keep_zip: bool = True) -> dict[str, set]:
    """Personal tokens harvested from the original's OCR, by kind (pages OCRed in parallel)."""
    oracle = {"name": set(), "dob": set(), "phone": set(), "id": set(), "address": set()}
    with tempfile.TemporaryDirectory(prefix="oracle-") as tmp:
        pages, _ = _load_input_pages(original_path, tmp, dpi)
        jobs = []
        for i, img in enumerate(pages):
            png = os.path.join(tmp, f"o-{i}.png")
            img.save(png)
            jobs.append((png, i, img.size[0], img.size[1]))
        with ThreadPoolExecutor(max_workers=workers) as ex:
            results = list(ex.map(lambda j: _oracle_page(*j), jobs))
    loc_words: set[str] = set()
    for r in results:
        for kind in ("name", "phone", "address", "id", "dob"):
            oracle[kind] |= r[kind]
        loc_words |= r["loc"]
    # a token printed on many pages of the original is form vocabulary (a caption, the form
    # number, a checkbox label), not a person: nobody's name recurs across a whole binder
    # a person's name or address sits on the pages of one report (four at most); anything
    # on more pages than that is a caption or a checkbox label repeated on every form
    limit = 4
    for kind in ("name", "address"):
        oracle[kind] = {t for t in oracle[kind] if sum(1 for r in results if t in r["all"]) <= limit}
    if keep_zip:      # five digit ZIP codes stay visible by design (NC ZIPs 27000 to 28999)
        oracle["address"] = {t for t in oracle["address"] if not (t.isdigit() and len(t) == 5 and t[:2] in ("27", "28"))}
    for kind in ("name", "address", "id", "phone"):
        oracle[kind] -= loc_words
    # crash ids, route ids and anything printed in the location block must not count
    oracle["id"] = {t for t in oracle["id"] if not (t.startswith("1") and len(t) == 9) and not t.startswith("40001")}
    oracle["address"] = {t for t in oracle["address"] if not (t.isdigit() and t in loc_words)}
    return oracle


def _verify_page(png: str, i: int, oracle: dict) -> tuple[list, list]:
    leaks, patterns = [], []
    txt = _ocr_text(png)
    # digit runs per token (hyphens and dots inside a token collapse); never across words
    digit_tokens = {re.sub(r"\D", "", w) for w in txt.split()}
    digit_tokens = {d for d in digit_tokens if d}
    # house numbers print as bare digits; "3.12" (a milepost) or "9:12" (a time) are not 312
    bare_digit_tokens = {w.strip(",.;:()") for w in txt.split() if w.strip(",.;:()").isdigit()}
    for kind, toks in oracle.items():
        for t in toks:
            if kind in ("phone", "id"):
                hit = t in digit_tokens or any(d.endswith(t) and len(d) <= len(t) + 3 for d in digit_tokens)
            elif kind == "dob":
                hit = t in txt or t.replace("/", "") in digit_tokens
            elif kind == "address" and t.isdigit():
                hit = t in bare_digit_tokens
            else:
                hit = re.search(rf"\b{re.escape(t)}\b", txt) is not None
            if hit:
                leaks.append((i + 1, kind, _mask(t)))
    for m in _PHONE_RE.finditer(txt):
        patterns.append((i + 1, "phone-pattern", _mask(m.group(0))))
    return leaks, patterns


def verify_redaction(original_path: str, redacted_pdf: str, dpi: int = 200,
                     oracle: dict | None = None, workers: int = WORKERS, keep_zip: bool = True) -> RedactionVerification:
    """OCR the redacted output (pages in parallel) and search it for the original's personal tokens."""
    rep = RedactionVerification()
    oracle = oracle or build_oracle(original_path, dpi, workers=workers, keep_zip=keep_zip)
    rep.oracle_size = sum(len(v) for v in oracle.values())
    with tempfile.TemporaryDirectory(prefix="verify-") as tmp:
        pages, _ = _load_input_pages(redacted_pdf, tmp, dpi)
        rep.pages = len(pages)
        jobs = []
        for i, img in enumerate(pages):
            png = os.path.join(tmp, f"r-{i}.png")
            img.save(png)
            jobs.append((png, i))
        with ThreadPoolExecutor(max_workers=workers) as ex:
            for leaks, patterns in ex.map(lambda j: _verify_page(j[0], j[1], oracle), jobs):
                rep.leaks += leaks
                rep.patterns += patterns
    rep.leaks.sort()
    rep.patterns.sort()
    return rep
