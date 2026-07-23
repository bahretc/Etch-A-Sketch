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
