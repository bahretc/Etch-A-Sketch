"""How current is TEAAS crash data right now?

NCDOT posts the answer on the TEAAS resource page ("TEAAS crash data is
now available through {Month Year}"). The engineer checks it before
starting any new analysis, because the after period of an evaluation or
the study period of an HSIP package must not run past the loaded data.
This module fetches and parses that line so the check can happen at the
top of every run instead of relying on memory.
"""
from __future__ import annotations

import html as _html
import re
import urllib.request

CURRENCY_URL = ("https://connect.ncdot.gov/resources/safety/Pages/"
                "TEAAS-Crash-Data-System.aspx")
_UA = {"User-Agent": "safety-eval teaas-currency check"}

_MONTHS = ("January", "February", "March", "April", "May", "June", "July",
           "August", "September", "October", "November", "December")


def parse_currency(page_html: str) -> str | None:
    """Pull ``"July 2026"`` out of the page text, or None if absent.

    The page separates month and year with a non-breaking space
    (``&#160;`` in the source), so entities are unescaped and all
    whitespace collapsed before matching.
    """
    text = _html.unescape(page_html)
    text = re.sub(r"\s+", " ", text)   # \s covers the non-breaking space
    m = re.search(r"available\s+through\s+("
                  + "|".join(_MONTHS) + r")\s+(\d{4})", text, re.IGNORECASE)
    if not m:
        return None
    month = m.group(1).capitalize()
    return f"{month} {m.group(2)}"


def current_data_month(timeout: float = 30) -> str:
    """Fetch the TEAAS page and return e.g. ``"July 2026"``."""
    req = urllib.request.Request(CURRENCY_URL, headers=_UA)
    with urllib.request.urlopen(req, timeout=timeout) as resp:
        page = resp.read().decode("utf-8", "replace")
    month = parse_currency(page)
    if month is None:
        raise RuntimeError(
            "The TEAAS page loaded but the 'available through' line was "
            f"not found; check {CURRENCY_URL} by hand.")
    return month
