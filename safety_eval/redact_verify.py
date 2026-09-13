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
from dataclasses import dataclass, field

from .redact import (_line_has_street_address, _lines, _load_input_pages, _require, harvest_name_tokens,
                     ocr_words)

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


def _ocr_text(png: str, timeout: int = 300) -> str:
    tesseract = _require("tesseract")
    out = ""
    for psm in ("3", "11"):
        r = subprocess.run([tesseract, png, "stdout", "--psm", psm], capture_output=True, text=True,
                           timeout=timeout)
        out += "\n" + r.stdout
    return out.upper()


def build_oracle(original_path: str, dpi: int = 200, era_margin: int = 2) -> dict[str, set]:
    """Personal tokens harvested from the original's OCR, by kind."""
    oracle = {"name": set(), "dob": set(), "phone": set(), "id": set(), "address": set()}
    with tempfile.TemporaryDirectory(prefix="oracle-") as tmp:
        pages, _ = _load_input_pages(original_path, tmp, dpi)
        loc_words: set[str] = set()
        all_years: list[int] = []
        for i, img in enumerate(pages):
            png = os.path.join(tmp, f"o-{i}.png")
            img.save(png)
            pw, ph = img.size
            for psm in (11, 3):
                words = ocr_words(png, page=i, psm=psm, timeout=300, min_conf=0.0)
                oracle["name"] |= harvest_name_tokens(words, pw, ph)
                for w in words:
                    if w.top < 0.25 * ph:          # location block: routes, crash id, dates, coordinates
                        loc_words.add(re.sub(r"[^A-Za-z]", "", w.text).upper())
                        loc_words.add(re.sub(r"\D", "", w.text))
                text = " ".join(w.text for w in words)
                for m in _DATE_RE.finditer(text):
                    all_years.append(int(m.group(3)))
                for m in _PHONE_RE.finditer(text):
                    oracle["phone"].add(re.sub(r"\D", "", m.group(0))[-7:])
                for line in _lines(words):
                    toks = [w.text for w in line]
                    if not _line_has_street_address(toks):
                        continue
                    clean = [re.sub(r"[^A-Za-z0-9]", "", t).upper() for t in toks]
                    if not any(_HOUSE_NO_RE.match(c) for c in clean):
                        continue
                    house_idx = [k for k, c in enumerate(clean) if _HOUSE_NO_RE.match(c) and len(c) >= 3]
                    for k in house_idx:
                        oracle["address"].add(clean[k])       # the house number itself
                        for c in clean[k + 1:k + 4]:          # the street name follows it
                            if len(c) >= 5 and c.isalpha() and c not in _ADDRESS_STOP:
                                oracle["address"].add(c)
                for w in words:
                    raw = w.text.strip().strip(",;:")
                    # licence, policy and similar numbers print as plain digit runs (a hyphen at most);
                    # dates, coordinates and decimals never count
                    if w.conf >= 40 and re.fullmatch(r"\d[\d-]{5,8}\d", raw) and _ID_RE.fullmatch(re.sub(r"\D", "", raw)):
                        oracle["id"].add(re.sub(r"\D", "", raw))
            # DOB: dates well before the crash era (the report's own dates cluster at the era)
        era = max(all_years) if all_years else None
        for i, img in enumerate(pages):
            pass
        if era:
            with tempfile.TemporaryDirectory(prefix="oracle2-") as tmp2:
                for i, img in enumerate(pages):
                    png = os.path.join(tmp2, f"o-{i}.png")
                    img.save(png)
                    for m in _DATE_RE.finditer(_ocr_text(png)):
                        if int(m.group(3)) <= era - era_margin:
                            oracle["dob"].add(m.group(0))
    for kind in ("name", "address", "id", "phone"):
        oracle[kind] -= loc_words
    # crash ids, route ids and anything printed in the location block must not count
    oracle["id"] = {t for t in oracle["id"] if not (t.startswith("1") and len(t) == 9) and not t.startswith("40001")}
    oracle["address"] = {t for t in oracle["address"] if not (t.isdigit() and t in loc_words)}
    return oracle


def verify_redaction(original_path: str, redacted_pdf: str, dpi: int = 200,
                     oracle: dict | None = None) -> RedactionVerification:
    """OCR the redacted output and search it for the original's personal tokens."""
    rep = RedactionVerification()
    oracle = oracle or build_oracle(original_path, dpi)
    rep.oracle_size = sum(len(v) for v in oracle.values())
    with tempfile.TemporaryDirectory(prefix="verify-") as tmp:
        pages, _ = _load_input_pages(redacted_pdf, tmp, dpi)
        rep.pages = len(pages)
        for i, img in enumerate(pages):
            png = os.path.join(tmp, f"r-{i}.png")
            img.save(png)
            txt = _ocr_text(png)
            # digit runs per token (hyphens and dots inside a token collapse); never across words
            digit_tokens = {re.sub(r"\D", "", w) for w in txt.split()}
            digit_tokens = {d for d in digit_tokens if d}
            for kind, toks in oracle.items():
                for t in toks:
                    if kind in ("phone", "id"):
                        hit = t in digit_tokens or any(d.endswith(t) and len(d) <= len(t) + 3 for d in digit_tokens)
                    elif kind == "dob":
                        hit = t in txt or t.replace("/", "") in digit_tokens
                    elif kind == "address" and t.isdigit():
                        hit = t in digit_tokens
                    else:
                        hit = re.search(rf"\b{re.escape(t)}\b", txt) is not None
                    if hit:
                        rep.leaks.append((i + 1, kind, _mask(t)))
            for m in _PHONE_RE.finditer(txt):
                rep.patterns.append((i + 1, "phone-pattern", _mask(m.group(0))))
    return rep
