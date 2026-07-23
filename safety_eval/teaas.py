"""Parsers for TEAAS text exports (docs/07).

Currently implemented:

* **Crash ID List** (5-column pipe-delimited), e.g.::

    CRASH ID|ON RD CD|SVRTY|DATE|TYPE|
    105366208|30000091|5|01/22/2018 08:50|30|

  SVRTY is the numeric severity code (1=K, 2=A, 3=B, 4=C, 5=PDO), confirmed
  against the SS-6002AD example by cross-checking the Intersection Analysis
  Report injury columns.  TYPE is the crash-type T-code (docs/09).

The 43-column Detailed Crash ID List parser is future work (no fixture yet).
"""
from __future__ import annotations

from datetime import datetime

from .config import Config
from .models import Crash


def parse_import_list(source: str) -> dict[str, float]:
    """Parse a TEAAS milepost import file: ``crash_id|<tab>milepost`` per line.

    (The ``*_Import.txt`` files feed the Final MP column of Section workbook
    Before/After sheets; confirmed against examples/04-15-39049.)
    """
    text = source
    if "\n" not in source and len(source) < 400:
        with open(source, encoding="utf-8", errors="replace") as fh:
            text = fh.read()
    out: dict[str, float] = {}
    for line in text.splitlines():
        parts = [p.strip() for p in line.strip().split("|")]
        if len(parts) >= 2 and parts[0].isdigit():
            try:
                out[parts[0]] = float(parts[1])
            except ValueError:
                continue
    return out


def enrich_from_fiche(crashes: list[Crash], fiche_crashes: list[Crash]) -> int:
    """Fill C/F/L (and any missing T/S/date) from parsed fiche rows by Crash ID.

    The 5-column Crash ID List carries only T and SVRTY; the fiche row has the
    full T C F L S coding. Returns the number of crashes enriched.
    """
    by_id = {c.crash_id: c for c in fiche_crashes}
    n = 0
    for crash in crashes:
        src = by_id.get(crash.crash_id)
        if src is None:
            continue
        n += 1
        for attr in ("c", "f", "l"):
            if getattr(crash, attr) is None:
                setattr(crash, attr, getattr(src, attr))
        if crash.t is None:
            crash.t = src.t
        if not crash.s:
            crash.s = src.s
        if crash.date is None:
            crash.date = src.date
        if crash.mp is None:
            crash.mp = src.mp
    return n


def parse_crash_id_list(source: str, cfg: Config | None = None) -> list[Crash]:
    """Parse a TEAAS 5-column Crash ID List export (path or raw text)."""
    cfg = cfg or Config.load()
    numeric = {int(k): v for k, v in
               cfg.data["severity"].get("numeric_codes", {}).items()}
    text = source
    if "\n" not in source and len(source) < 400:
        with open(source, encoding="utf-8", errors="replace") as fh:
            text = fh.read()

    crashes: list[Crash] = []
    for line in text.splitlines():
        line = line.strip()
        if not line or line.upper().startswith("CRASH ID"):
            continue
        parts = [p.strip() for p in line.split("|")]
        if len(parts) < 5 or not parts[0].isdigit():
            continue
        crash_id, road_code, svrty, date_raw, type_raw = parts[:5]
        dt = None
        for fmt in ("%m/%d/%Y %H:%M", "%m/%d/%Y"):
            try:
                dt = datetime.strptime(date_raw, fmt)
                break
            except ValueError:
                continue
        crashes.append(Crash(
            crash_id=crash_id,
            date=dt.date() if dt else None,
            on_road=road_code,
            t=int(type_raw) if type_raw.isdigit() else None,
            s=numeric.get(int(svrty), "") if svrty.isdigit() else "",
        ))
    return crashes
