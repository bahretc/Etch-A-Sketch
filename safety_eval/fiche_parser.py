"""Parse a TEAAS 'Fiche Report' into structured :class:`Crash` records.

Two input shapes are supported:

* **CSV** — the ``*_Fiche.csv`` export (header row then one crash per row).
* **TEAAS text** — the raw text of the printed fiche (e.g. from OCR of the PDF),
  which repeats a column header on every page and is interrupted by page
  markers like ``3/17/2020  Page 2 of 16``.  Rows are detected by the presence
  of a 9-digit Crash ID followed by an ``m/d/Y`` date.
"""
from __future__ import annotations

import csv
import io
import re
from datetime import date, datetime
from typing import Iterable

from .models import Crash

# canonical field -> accepted header spellings (lowercased, stripped)
_HEADER_ALIASES = {
    "muni_code": {"muni. code", "muni code", "municode"},
    "on_road": {"on road", "onroad"},
    "miles": {"miles", "miles  /  dir from", "miles / dir from"},
    "dir_from": {"dir from", "dirfrom", "dir"},
    "from_road": {"from road"},
    "toward_road": {"toward road"},
    "milepost_road": {"milepost road"},
    "mp": {"mp"},
    "ma": {"ma"},
    "crash_id": {"crash id", "crashid"},
    "date": {"date"},
    "t": {"t"}, "c": {"c"}, "f": {"f"}, "l": {"l"}, "s": {"s"},
    "comments": {"comments", "comment"},
    "final_mp": {"final mp"},
    "is_flag": {"is?", "is"},
}

_CRASH_ROW_RE = re.compile(r"\b(\d{9})\b[\s|,]+(\d{1,2}/\d{1,2}/\d{4})")


def _parse_date(raw: str) -> date | None:
    raw = (raw or "").strip()
    if not raw:
        return None
    for fmt in ("%m/%d/%Y", "%m/%d/%y", "%Y-%m-%d"):
        try:
            return datetime.strptime(raw, fmt).date()
        except ValueError:
            continue
    return None


def _to_float(raw) -> float | None:
    if raw is None:
        return None
    raw = str(raw).replace(",", "").strip()
    if raw == "":
        return None
    try:
        return float(raw)
    except ValueError:
        return None


def _to_int(raw) -> int | None:
    v = _to_float(raw)
    return int(v) if v is not None else None


def _build_header_map(header: list[str]) -> dict[int, str]:
    """Map column index -> canonical field name.

    TEAAS CSV headers can embed newlines inside quoted cells ("Muni.\\nCode")
    and combine "Miles  /  Dir\\nFrom" into ONE header cell that spans TWO data
    columns (miles, dir); the map expands it and shifts subsequent columns.
    """
    mapping: dict[int, str] = {}
    offset = 0
    for idx, name in enumerate(header):
        key = re.sub(r"\s+", " ", (name or "")).strip().strip('"').lower()
        col = idx + offset
        if re.fullmatch(r"miles\s*/\s*dir(\s+from)?", key):
            mapping[col] = "miles"
            mapping[col + 1] = "dir_from"
            offset += 1
            continue
        for canon, aliases in _HEADER_ALIASES.items():
            if key in aliases and canon not in mapping.values():
                mapping[col] = canon
                break
    return mapping


def _row_to_crash(cells: list[str], hmap: dict[int, str]) -> Crash | None:
    rec: dict[str, str] = {}
    for idx, canon in hmap.items():
        if idx < len(cells):
            rec[canon] = (cells[idx] or "").strip()
    cid = rec.get("crash_id", "").strip()
    if not re.fullmatch(r"\d{6,10}", cid):
        return None
    return Crash(
        crash_id=cid,
        date=_parse_date(rec.get("date", "")),
        muni_code=rec.get("muni_code", ""),
        on_road=rec.get("on_road", ""),
        miles=_to_float(rec.get("miles")),
        dir_from=rec.get("dir_from", ""),
        from_road=rec.get("from_road", ""),
        toward_road=rec.get("toward_road", ""),
        milepost_road=rec.get("milepost_road", ""),
        mp=_to_float(rec.get("mp")),
        ma=rec.get("ma", ""),
        t=_to_int(rec.get("t")),
        c=_to_int(rec.get("c")),
        f=_to_int(rec.get("f")),
        l=_to_int(rec.get("l")),
        s=(rec.get("s", "") or "").strip().upper(),
        comments=rec.get("comments", ""),
    )


def parse_csv(text: str) -> list[Crash]:
    """Parse the ``*_Fiche.csv`` export."""
    reader = list(csv.reader(io.StringIO(text)))
    if not reader:
        return []
    # find the header row (first row containing 'Crash ID')
    header_idx = None
    for i, row in enumerate(reader):
        if any((c or "").strip().strip('"').lower() in _HEADER_ALIASES["crash_id"] for c in row):
            header_idx = i
            break
    if header_idx is None:
        header_idx = 0
    hmap = _build_header_map(reader[header_idx])
    crashes: list[Crash] = []
    seen: set[str] = set()
    for row in reader[header_idx + 1:]:
        crash = _row_to_crash(row, hmap)
        if crash and crash.crash_id not in seen:
            seen.add(crash.crash_id)
            crashes.append(crash)
    return crashes


def parse_teaas_text(text: str) -> list[Crash]:
    """Parse raw TEAAS fiche text (e.g. OCR output of the printed report).

    The header is repeated per page; we detect it and reuse the column mapping,
    skipping page-marker lines.
    """
    lines = text.splitlines()
    hmap: dict[int, str] | None = None
    crashes: list[Crash] = []
    seen: set[str] = set()
    for line in lines:
        low = line.lower()
        if "crash id" in low and ("on road" in low or "muni" in low):
            # header line — split on 2+ spaces or pipes/commas
            hmap = _build_header_map(_split_cols(line))
            continue
        if re.search(r"page\s+\d+\s+of\s+\d+", low):
            continue
        if not _CRASH_ROW_RE.search(line):
            continue
        if hmap is None:
            # fall back to positional parse against the known TEAAS order
            hmap = _POSITIONAL_TEAAS
        crash = _row_to_crash(_split_cols(line), hmap)
        if crash and crash.crash_id not in seen:
            seen.add(crash.crash_id)
            crashes.append(crash)
    return crashes


def _split_cols(line: str) -> list[str]:
    if "|" in line:
        return [c.strip() for c in line.split("|")]
    if "," in line and line.count(",") >= 5:
        return next(csv.reader([line]))
    return re.split(r"\s{2,}", line.strip())


# positional fallback for headerless TEAAS text, in printed column order
_POSITIONAL_TEAAS = {
    0: "muni_code", 1: "on_road", 2: "miles", 3: "dir_from", 4: "from_road",
    5: "toward_road", 6: "milepost_road", 7: "mp", 8: "ma", 9: "crash_id",
    10: "date", 11: "t", 12: "c", 13: "f", 14: "l", 15: "s",
}


def parse_fiche(source: str | Iterable[str], fmt: str = "auto") -> list[Crash]:
    """Parse a fiche from a file path or raw text.

    ``fmt`` is one of ``auto`` | ``csv`` | ``teaas`` | ``pdf``.
    """
    text = _read_source(source, fmt)
    if fmt == "csv":
        return parse_csv(text)
    if fmt == "teaas":
        return parse_teaas_text(text)
    # auto-detect
    head = "\n".join(text.splitlines()[:5]).lower()
    if head.count(",") > head.count("|") and "crash id" in head:
        return parse_csv(text)
    csv_result = parse_csv(text)
    if csv_result:
        return csv_result
    return parse_teaas_text(text)


def _read_source(source, fmt: str) -> str:
    if isinstance(source, str) and ("\n" not in source) and len(source) < 400:
        # treat as a path
        if fmt == "pdf" or source.lower().endswith(".pdf"):
            from .ocr import extract_pdf_text
            return extract_pdf_text(source)
        with open(source, encoding="utf-8", errors="replace") as fh:
            return fh.read()
    if isinstance(source, str):
        return source
    return "\n".join(source)
