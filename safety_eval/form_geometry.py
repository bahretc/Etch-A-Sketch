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

#: The ZIP value boxes of the driver and owner blocks, per unit column
#: (template coordinates, measured on the Rev. 1/2009 form and confirmed on
#: two different reports). Position is what makes a hyphenless ZIP+4 safe to
#: keep: a nine digit run HERE is a ZIP, while a nine digit run in the D.L.
#: box is a licence number and stays covered.
DMV349_ZIP_FIELDS: tuple[Zone, ...] = (
    Zone("zip-unit1-driver", 0.392, 0.300, 0.482, 0.317),
    Zone("zip-unit2-driver", 0.830, 0.300, 0.925, 0.317),
    Zone("zip-unit1-owner", 0.392, 0.485, 0.482, 0.502),
    Zone("zip-unit2-owner", 0.830, 0.485, 0.925, 0.502),
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


_ZIP5_RE = re.compile(r"^\d{5}(?:-\d{4})?$")
_ZIP9_RE = re.compile(r"^\d{9}$")
_STATES = {
    "AL", "AK", "AZ", "AR", "CA", "CO", "CT", "DE", "FL", "GA", "HI", "ID",
    "IL", "IN", "IA", "KS", "KY", "LA", "ME", "MD", "MA", "MI", "MN", "MS",
    "MO", "MT", "NE", "NV", "NH", "NJ", "NM", "NY", "NC", "ND", "OH", "OK",
    "OR", "PA", "RI", "SC", "SD", "TN", "TX", "UT", "VT", "VA", "WA", "WV",
    "WI", "WY", "DC",
}


def zip_words(words, rect=None, row_tol: int | None = None) -> list:
    """ZIP tokens (optionally inside ``rect``), which are deliberately KEPT.

    A ZIP locates the crash without identifying anyone, so it survives even
    when the block around it is covered. Only the unambiguous forms qualify:
    five digits, or five plus four with the hyphen.

    A bare nine digit run is NOT treated as a hyphenless ZIP+4. It reads the
    same as a driver licence number, and this form prints "D.L. State NC"
    right beside the licence, so any "digits next to a state abbreviation"
    rule preserves licence numbers as if they were ZIPs. Leaving a hyphenless
    ZIP+4 covered loses a little geography; the other way round leaks PII.
    """
    pool = [w for w in words if rect is None or _in_rect(w, rect)]
    return [w for w in pool
            if _ZIP5_RE.match(w.text.strip().strip(".,;:"))]


def zip_field_words(words, width: int, height: int,
                    reg: tuple[float, float]) -> list:
    """Digits sitting in a ZIP value box of the form.

    This is the positional counterpart to :func:`zip_words`: inside a ZIP
    field, a nine digit run is a hyphenless ZIP+4 and is kept, because a
    licence number of the same shape lives in a different box entirely. Only
    the digit tokens are returned, never the rectangle, so a mis-registered
    page can expose nothing but numbers it actually found there.
    """
    out = []
    for _z, rect in zone_rects(width, height, reg, DMV349_ZIP_FIELDS):
        for w in words:
            t = w.text.strip().strip(".,;:")
            if _in_rect(w, rect) and (_ZIP5_RE.match(t) or _ZIP9_RE.match(t)):
                out.append(w)
    return out


def rect_minus(rect, holes, pad: int = 2) -> list[tuple[int, int, int, int]]:
    """``rect`` split into sub-rectangles that avoid every hole.

    Used so a covered zone still shows its ZIP: the band containing the ZIP is
    emitted as a piece to its left and a piece to its right.
    """
    x0, y0, x1, y1 = rect
    holes = sorted((h for h in holes if h[1] < y1 and h[3] > y0),
                   key=lambda h: h[1])
    if not holes:
        return [rect] if x1 > x0 and y1 > y0 else []
    out: list[tuple[int, int, int, int]] = []
    cursor = y0
    for hx0, hy0, hx1, hy1 in holes:
        top, bottom = max(y0, hy0 - pad), min(y1, hy1 + pad)
        if top > cursor:
            out.append((x0, cursor, x1, top))
        left = max(x0, hx0 - pad)
        if left > x0:
            out.append((x0, top, left, bottom))
        right = min(x1, hx1 + pad)
        if right < x1:
            out.append((right, top, x1, bottom))
        cursor = max(cursor, bottom)
    if cursor < y1:
        out.append((x0, cursor, x1, y1))
    return [r for r in out if r[2] > r[0] and r[3] > r[1]]


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


def local_address_words(words, width: int, height: int,
                        reg: tuple[float, float], roads: set[str]) -> list:
    """Address tokens inside a covered zone that name the study roadway.

    An address is PII when it says where someone lives. An address that
    says the crash happened in front of a house on the study road is
    location, and covering it throws away the thing a reviewer needs to
    place the crash. So a row inside an identity zone survives when it
    carries a road the report's own header calls out: the same vocabulary
    that already stops one report's street blacking out another report's
    municipality.
    """
    if not roads:
        return []
    zones = [rect for z, rect in zone_rects(width, height, reg)
             if z.harvest]
    inside = [w for w in words if any(_in_rect(w, r) for r in zones)]
    rows: list[list] = []
    for w in sorted(inside, key=lambda w: (w.top, w.left)):
        tol = max(6, w.height)
        for row in rows:
            if abs((row[0].top + row[0].height / 2)
                   - (w.top + w.height / 2)) <= tol:
                row.append(w)
                break
        else:
            rows.append([w])
    keep = []
    for row in rows:
        text = {w.text.strip().strip(".,;:").upper() for w in row}
        if text & roads:
            keep.extend(row)
    return keep


def scrub_targets(words, names: set[str]) -> list:
    """Words anywhere on a page that match a harvested name."""
    if not names:
        return []
    return [w for w in words
            if w.text.strip().strip(".,;:").upper() in names]
