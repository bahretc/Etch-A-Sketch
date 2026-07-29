"""DMV-349 field geometry: redact by where a field IS, not by reading its caption.

Caption-driven redaction fails exactly where it matters: when the scan garbles
the caption, the value beside it survives (observed on a real report, where a
date of birth, a licence number and a city stayed legible while their captions
OCR'd to noise). Pattern rules cannot rescue those, because a house number and
a route number are the same shape, and blacking one blacks the crash location.

The form itself is the missing information. The NC DMV-349 (Rev. 1/2009) is a
fixed layout, so the driver block, owner block, insurance line and persons
table always sit in the same place relative to the page. This module:

1. **registers** a scanned page against the template, by finding a few caption
   anchors whose nominal positions are known and fitting the vertical mapping
   (scans differ in margin and scale, rarely in field order);
2. redacts PII **zones** outright, regardless of what OCR made of the captions;
3. **harvests** the person names out of those zones before they are covered,
   then **scrubs** those exact strings anywhere else they appear.

Step 3 is what makes the narrative usable. The narrative is the single most
useful part of the report for deciding where a crash happened, so blacking it
wholesale defeats the review; scrubbing the harvested names leaves the account
intact ("Vehicle 1 was traveling north on NC 42") while removing the people.

Zones are expressed as fractions of page width and height, so they work at any
DPI. Anything not listed is KEPT: the crash ID, date, county, time, location
block, coded field grid, diagram and narrative all stay legible.
"""
from __future__ import annotations

import re
from dataclasses import dataclass

#: Nominal vertical positions (fraction of page height) of caption anchors on
#: the DMV-349 front page, measured from the Rev. 1/2009 layout. Used to fit
#: the page registration; a scan only has to show two of them.
_ANCHORS = {
    "location": 0.155,
    "owner": 0.445,
    "names": 0.735,
    "injured": 0.965,
}

#: Words whose presence marks a front page (the back page carries the diagram
#: and narrative and has no header box).
_FRONT_MARKERS = ("dmv-349", "units", "involved", "patrol")


@dataclass(frozen=True)
class Zone:
    """A rectangle of the form, in template coordinates (fractions)."""
    name: str
    x0: float
    y0: float
    x1: float
    y1: float
    harvest: bool = False        # collect person names from this zone


#: PII zones of the DMV-349 front page. Left and right unit columns are listed
#: separately where the row also carries coded crash data that must survive.
DMV349_FRONT: tuple[Zone, ...] = (
    # driver identity: name, address, city rows for both units
    Zone("driver-identity", 0.05, 0.235, 1.00, 0.325, harvest=True),
    # licence / DL / DOB: left and right value boxes only, so the
    # Vision / Physical Condition / DL Restrictions codes beside them survive
    Zone("unit1-licence", 0.05, 0.325, 0.185, 0.400),
    Zone("unit2-licence", 0.49, 0.325, 0.625, 0.400),
    # owner identity block
    Zone("owner-identity", 0.05, 0.430, 1.00, 0.505, harvest=True),
    # plate and VIN
    Zone("plate-vin", 0.05, 0.505, 1.00, 0.545),
    # insurance company and policy number
    Zone("insurance", 0.05, 0.595, 0.470, 0.640),
    Zone("insurance-2", 0.49, 0.595, 1.00, 0.640),
    # commercial carrier name and address
    Zone("carrier", 0.05, 0.640, 1.00, 0.700),
    # persons table: keep the coded columns at the left, cover names/addresses
    Zone("persons-table", 0.105, 0.720, 1.00, 0.930, harvest=True),
    # bottom name line and injured-taken-to facilities
    Zone("bottom-names", 0.05, 0.930, 1.00, 1.000, harvest=True),
)

_CAPTIONISH = {
    "name", "names", "address", "addresses", "city", "state", "zip", "driver",
    "owner", "first", "middle", "last", "same", "as", "plate", "vin", "dob",
    "license", "licence", "insurance", "company", "policy", "unit", "vehicle",
    "make", "year", "style", "type", "damage", "estimated", "tad", "no",
    "yes", "not", "towed", "by", "to", "of", "for", "all", "persons", "see",
    "above", "use", "check", "blocks", "if", "same", "drv", "ped", "etc",
    "injured", "taken", "ems", "treatment", "facility", "and", "town", "city",
}
_WORD_RE = re.compile(r"^[A-Za-z][A-Za-z'\-]{2,}$")


def _norm(t: str) -> str:
    return re.sub(r"[^A-Za-z0-9]", "", t).lower()


def is_front_page(words) -> bool:
    """True when the page shows the DMV-349 header (fields are laid out)."""
    seen = {_norm(w.text) for w in words}
    return sum(1 for m in _FRONT_MARKERS if m.replace("-", "") in seen) >= 2


def register(words, height: int) -> tuple[float, float]:
    """Fit observed_y = scale * template_y + offset from caption anchors.

    Returns ``(scale, offset)`` in fractions of page height; the identity
    ``(1.0, 0.0)`` when fewer than two anchors are legible, which keeps the
    nominal layout rather than guessing.
    """
    seen: dict[str, float] = {}
    for w in words:
        key = _norm(w.text)
        for anchor in _ANCHORS:
            if key.startswith(anchor) and anchor not in seen:
                seen[anchor] = (w.top + w.height / 2) / max(height, 1)
    if len(seen) < 2:
        return 1.0, 0.0
    xs = [_ANCHORS[a] for a in seen]
    ys = [seen[a] for a in seen]
    n = len(xs)
    mx, my = sum(xs) / n, sum(ys) / n
    denom = sum((x - mx) ** 2 for x in xs)
    if denom <= 1e-9:
        return 1.0, 0.0
    scale = sum((x - mx) * (y - my) for x, y in zip(xs, ys)) / denom
    if not 0.6 <= scale <= 1.6:          # implausible fit; keep nominal
        return 1.0, 0.0
    return scale, my - scale * mx


def zone_rects(width: int, height: int, reg: tuple[float, float],
               zones=DMV349_FRONT) -> list[tuple[Zone, tuple[int, int, int, int]]]:
    """Zones mapped to pixel rectangles on this page."""
    scale, offset = reg
    out = []
    for z in zones:
        top = (z.y0 * scale + offset) * height
        bottom = (z.y1 * scale + offset) * height
        out.append((z, (int(z.x0 * width), int(max(0, top)),
                        int(z.x1 * width), int(min(height, bottom)))))
    return out


def _in_rect(w, rect) -> bool:
    cx, cy = w.left + w.width / 2, w.top + w.height / 2
    return rect[0] <= cx <= rect[2] and rect[1] <= cy <= rect[3]


def harvest_names(words, width: int, height: int,
                  reg: tuple[float, float]) -> set[str]:
    """Person-name tokens sitting in the identity zones.

    Harvested BEFORE the zones are covered, so the same strings can be removed
    from the narrative on other pages, which is the only way to keep a
    narrative readable and still take the people out of it.
    """
    found: set[str] = set()
    for z, rect in zone_rects(width, height, reg):
        if not z.harvest:
            continue
        for w in words:
            t = w.text.strip().strip(".,;:")
            if _in_rect(w, rect) and _WORD_RE.match(t) \
                    and _norm(t) not in _CAPTIONISH:
                found.add(t.upper())
    return found


#: the header and location blocks sit above the first identity zone; every
#: word in that band is crash geography (county, municipality, route names),
#: never a person, and must survive scrubbing.
LOCATION_BAND = 0.22


def location_vocabulary(words, height: int) -> set[str]:
    """Words from the header and location band: places, never people.

    A binder holds many reports, and one driver's street can be another
    crash's municipality ("SNOW HILL"). Without this guard, harvesting a name
    from one report blacks out the location of another.
    """
    out: set[str] = set()
    for w in words:
        if (w.top + w.height / 2) / max(height, 1) <= LOCATION_BAND:
            t = w.text.strip().strip(".,;:")
            if _WORD_RE.match(t):
                out.add(t.upper())
    return out


def scrub_targets(words, names: set[str]) -> list:
    """Words anywhere on a page that match a harvested name."""
    if not names:
        return []
    return [w for w in words
            if w.text.strip().strip(".,;:").upper() in names]
