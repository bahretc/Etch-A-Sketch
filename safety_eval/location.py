"""Resolve where a crash happened, from the DMV-349 location block.

The location block is a set of labelled fields, not prose, and each field means
one thing:

    Crash occurred [In|Near] <municipality>  or <D1> Miles <dir> outside municipality
    on <on_road>            Highway Number, or Highway, Street: <street>
    ## from <from_road>     <D2> Miles <dir>   (0 ft-intersection)
    toward <toward_road>    Latitude / Longitude / Altitude

D1 is a distance from a municipality; D2 is a distance from an intersecting
route. Neither one is a milepost, and nothing on the form is. Reading either as
a milepost is a guess, and a drafting layer must never have to guess: it is
handed a resolved location and told how it was obtained.

Resolution order, best evidence first:

1. **Coordinates.** When the report's Latitude/Longitude boxes are filled and
   route shape points are available, the milepost comes from projecting the
   point onto the route and interpolating between the surrounding shape points.
2. **Distance from an intersecting route.** With a features report (the NCDOT
   route inventory of intersections and their mileposts), the milepost is
   ``MP(from_road) +/- D2``. The sign does not need a route convention: the
   form also names the road the crash lies TOWARD, so the direction of
   increasing milepost is read off the pair itself, and the result is checked
   to fall between the two.
3. **Street address.** Resolvable to a route and milepost only with a
   geocoder; without one the address is carried through as-is with no milepost,
   which is honest rather than approximate.
4. **Distance from a municipality.** Locates the crash to a town, not a point.
   Never converted to a milepost.

The fiche already carries the milepost the study was built on. This module does
not duplicate it: it resolves independently and then **verifies**, because a
disagreement is a finding. In a section analysis a coded milepost that the
report contradicts is exactly the RE determination (docs/03).
"""
from __future__ import annotations

import csv
import math
import os
import re
import shutil
import subprocess
from dataclasses import dataclass, field

#: Compass directions as unit vectors, for interpreting "0.80 Miles N".
_COMPASS = {"N": (0.0, 1.0), "S": (0.0, -1.0), "E": (1.0, 0.0),
            "W": (-1.0, 0.0), "NE": (0.7071, 0.7071), "NW": (-0.7071, 0.7071),
            "SE": (0.7071, -0.7071), "SW": (-0.7071, -0.7071)}

#: Mileposts agreeing within this are the same location (fiche mileposts are
#: recorded to 0.01 mi, and a report distance is read to 0.01 mi).
MP_TOLERANCE = 0.06


@dataclass
class ReportLocation:
    """The location block of one DMV-349, field by field."""
    on_road: str = ""
    from_road: str = ""
    toward_road: str = ""
    street: str = ""                     # "Highway Number, or Highway, Street"
    municipality: str = ""
    in_municipality: bool | None = None  # In vs Near checkbox
    dist_from_municipality: float | None = None
    dir_from_municipality: str = ""
    dist_from_intersection: float | None = None
    dir_from_intersection: str = ""
    at_intersection: bool = False        # the "0 ft-intersection" marker
    latitude: float | None = None
    longitude: float | None = None
    county: str = ""

    @property
    def has_coordinates(self) -> bool:
        return self.latitude is not None and self.longitude is not None


@dataclass
class ResolvedLocation:
    """Where the crash was, and how that was established."""
    milepost: float | None = None
    method: str = "unresolved"           # coordinates | features | address | municipality
    latitude: float | None = None
    longitude: float | None = None
    route: str = ""
    confidence: str = "low"              # low | medium | high
    notes: list = field(default_factory=list)
    fiche_milepost: float | None = None
    agrees_with_fiche: bool | None = None

    def summary(self) -> str:
        """One plain line for a prompt or a reviewer."""
        if self.milepost is not None:
            base = f"{self.route or 'route'} milepost {self.milepost:.2f}"
        elif self.has_point:
            base = f"{self.latitude:.5f}, {self.longitude:.5f}"
        else:
            base = "not resolved to a point"
        out = f"{base} (from {self.method})"
        if self.agrees_with_fiche is False and self.fiche_milepost is not None:
            out += (f"; DISAGREES with the coded milepost "
                    f"{self.fiche_milepost:.2f}")
        elif self.agrees_with_fiche:
            out += "; agrees with the coded milepost"
        return out

    @property
    def has_point(self) -> bool:
        return self.latitude is not None and self.longitude is not None


# --------------------------------------------------------------------------- #
# the features report (route inventory)
# --------------------------------------------------------------------------- #
@dataclass
class FeatureInventory:
    """Mileposts of features along routes, from the NCDOT features report.

    ``features[route][feature_name] = milepost`` and, when the report carries
    geometry, ``shape[route] = [(milepost, lat, lon), ...]`` in milepost order.
    """
    features: dict = field(default_factory=dict)
    shape: dict = field(default_factory=dict)
    route_names: dict = field(default_factory=dict)   # canonical -> as printed

    @classmethod
    def from_csv(cls, path: str) -> "FeatureInventory":
        """Load ``route,feature,milepost[,latitude,longitude]`` rows."""
        inv = cls()
        with open(path, newline="", encoding="utf-8-sig") as fh:
            for row in csv.DictReader(fh):
                key = {k.strip().lower(): (v or "").strip()
                       for k, v in row.items() if k}
                route = normalize_route(key.get("route", ""))
                name = key.get("feature", "")
                try:
                    mp = float(key.get("milepost", ""))
                except ValueError:
                    continue
                if not route:
                    continue
                if name:
                    inv.features.setdefault(route, {}).setdefault(
                        normalize_route(name), []).append(mp)
                lat, lon = key.get("latitude", ""), key.get("longitude", "")
                if lat and lon:
                    try:
                        inv.shape.setdefault(route, []).append(
                            (mp, float(lat), float(lon)))
                    except ValueError:
                        pass
        for pts in inv.shape.values():
            pts.sort()
        return inv

    @classmethod
    def from_features_report(cls, text: str, route: str | None = None
                             ) -> "FeatureInventory":
        """Parse a TEAAS "Features Report" (the NCDOT route inventory).

        One report covers one county/route and lists every feature along it::

            GREENE 20000013 0.0            18.381
            1.993 40001132 SR 1132 At grade intersection, 4 legs 0.000 South and East
            2.983 40001142 SR 1142 At grade intersection, 3 legs 0.000 South and East

        Columns are milepost, route id, feature name, feature type, distance to
        the next feature, direction, and a loop flag. Features share a milepost
        when several legs meet there, and named streets, county lines
        (``CL-``), municipal limits (``ML-``) and structures appear alongside
        numbered routes; all of them are indexed, because a crash is located
        from whatever the report names.
        """
        inv = cls()
        route_name = route or _route_from_header(text)
        key = normalize_route(route_name)
        if not key:
            return inv
        for line in text.splitlines():
            parsed = _parse_feature_row(line)
            if parsed is None:
                continue
            mp, name = parsed
            existing = inv.features.setdefault(key, {})
            existing.setdefault(normalize_route(name), []).append(mp)
            inv.route_names.setdefault(key, route_name.strip())
        return inv

    def mileposts_of(self, route: str, feature: str) -> list:
        """Every milepost this feature appears at, ascending.

        A name is not unique along a route: the real US 13 report has NC 58 at
        MP 7.383 and again at 8.553, CHASE at 7.941 and 8.086, and Snow Hill's
        municipal limits at both ends of the town. This is the features-report
        form of the trap docs/03 records for cross streets, so every milepost
        is kept and the caller decides.
        """
        got = self.features.get(normalize_route(route), {}).get(
            normalize_route(feature))
        if got is None:
            return []
        if isinstance(got, (int, float)):     # hand-built inventories
            return [float(got)]
        return sorted(set(got))

    @classmethod
    def from_files(cls, paths) -> "FeatureInventory":
        """Load the features reports supplied for this evaluation.

        The engineer provides them per analysis, one per study route, in
        whatever form they were exported: the TEAAS Features Report as a PDF
        or a text dump, or a ``route,feature,milepost`` CSV. Several are merged
        into one inventory, because a study names more than one route (the road
        the crash is on, and the roads it is measured from and toward).
        """
        if isinstance(paths, (str, os.PathLike)):
            paths = [paths]
        merged = cls()
        for path in paths:
            path = str(path)
            low = path.lower()
            if low.endswith(".csv"):
                part = cls.from_csv(path)
            else:
                text = (_pdf_text(path) if low.endswith(".pdf")
                        else open(path, encoding="utf-8", errors="replace").read())
                part = cls.from_features_report(text)
            for route, feats in part.features.items():
                dest = merged.features.setdefault(route, {})
                for name, mps in feats.items():
                    dest.setdefault(name, []).extend(mps)
            for route, pts in part.shape.items():
                merged.shape.setdefault(route, []).extend(pts)
            merged.route_names.update(part.route_names)
        for pts in merged.shape.values():
            pts.sort()
        return merged

    def milepost_of(self, route: str, feature: str) -> float | None:
        """The feature's milepost, or None when the name is not unique."""
        mps = self.mileposts_of(route, feature)
        return mps[0] if len(mps) == 1 else None


_ROUTE_CLEAN_RE = re.compile(r"[^A-Z0-9]+")
#: a features-report data row: milepost, route id, then the feature
_FEATURE_ROW_RE = re.compile(r"^\s*(\d+\.\d{1,3})\s+([A-Z0-9]{4,})\s+(.+?)\s*$")
#: feature type phrases that terminate the name
_FEATURE_TYPE_RE = re.compile(
    r"\b(At grade intersection.*|Structure\b.*|Interchange.*|Ramp\b.*)$", re.I)
#: the report header names the county and the route id it covers
_HEADER_RE = re.compile(r"^\s*([A-Z][A-Z .\'-]+?)\s+(\d{8})\s+\d+\.\d+", re.M)
#: route id prefixes (docs/09): 2 = US, 3 = NC, 4 = SR
_ID_PREFIX = {"2": "US", "3": "NC", "4": "SR"}


def _route_from_header(text: str) -> str:
    """'GREENE 20000013 0.0 18.381' -> 'US 13'."""
    m = _HEADER_RE.search(text)
    if not m:
        return ""
    rid = m.group(2)
    prefix = _ID_PREFIX.get(rid[0])
    if not prefix:
        return ""
    number = rid[1:].lstrip("0") or "0"
    return f"{prefix} {number}"


def _parse_feature_row(line: str):
    """One data row -> (milepost, feature name), or None."""
    m = _FEATURE_ROW_RE.match(line)
    if not m:
        return None
    mp = float(m.group(1))
    rest = m.group(3)
    t = _FEATURE_TYPE_RE.search(rest)
    name = (rest[:t.start()] if t else rest).strip()
    if not t:
        # county lines, municipal limits: "CL-WAYNE 0.123 North and East"
        name = re.split(r"\s+\d+\.\d{1,3}\s", name)[0].strip()
    name = re.sub(r"\s+(North|South)\s+and\s+(East|West).*$", "", name).strip()
    return (mp, name) if name else None


def normalize_route(name: str) -> str:
    """'SR 1132', 'sr-1132', 'SR1132 (Plank Rd)' -> 'SR1132'.

    Route names arrive from three sources (the report, the fiche and the
    features report) with different spacing, punctuation and trailing common
    names, so they are compared in a canonical form.
    """
    if not name:
        return ""
    text = name.upper().split("(")[0]
    return _ROUTE_CLEAN_RE.sub("", text)


def _pdf_text(path: str) -> str:
    """Text of a features-report PDF (poppler; the reports have a text layer)."""
    exe = shutil.which("pdftotext")
    if exe:
        out = subprocess.run([exe, "-layout", path, "-"], capture_output=True,
                             text=True, timeout=120)
        if out.returncode == 0 and out.stdout.strip():
            return out.stdout
    try:
        from pypdf import PdfReader
    except ImportError as exc:                      # noqa: BLE001 - explain
        raise RuntimeError(
            f"cannot read {path}: install poppler (pdftotext) or pypdf") from exc
    return "\n".join((pg.extract_text() or "") for pg in PdfReader(path).pages)


# --------------------------------------------------------------------------- #
# geometry helpers
# --------------------------------------------------------------------------- #
def haversine_mi(lat1: float, lon1: float, lat2: float, lon2: float) -> float:
    r_mi = 3958.7613
    p1, p2 = math.radians(lat1), math.radians(lat2)
    dp, dl = math.radians(lat2 - lat1), math.radians(lon2 - lon1)
    a = math.sin(dp / 2) ** 2 + math.cos(p1) * math.cos(p2) * math.sin(dl / 2) ** 2
    return 2 * r_mi * math.asin(math.sqrt(a))


def interpolate_milepost(points, lat: float, lon: float):
    """Milepost of the point on a route polyline nearest ``(lat, lon)``.

    ``points`` are ``(milepost, lat, lon)`` in milepost order. Each segment is
    treated as a straight line in local scale, the point is projected onto it,
    and the milepost is interpolated by the projection's position along the
    segment. Returns ``(milepost, offset_miles)``; the offset is how far the
    crash sits from the route, which is what says whether the match is
    believable.
    """
    if not points:
        return None, None
    if len(points) == 1:
        mp, plat, plon = points[0]
        return mp, haversine_mi(lat, lon, plat, plon)
    best = (None, None, float("inf"))
    cos_lat = math.cos(math.radians(lat)) or 1e-9
    for (mp1, la1, lo1), (mp2, la2, lo2) in zip(points, points[1:]):
        # local planar coordinates in miles
        ax, ay = (lo1 - lon) * 69.172 * cos_lat, (la1 - lat) * 69.0547
        bx, by = (lo2 - lon) * 69.172 * cos_lat, (la2 - lat) * 69.0547
        dx, dy = bx - ax, by - ay
        seg2 = dx * dx + dy * dy
        t = 0.0 if seg2 <= 1e-12 else max(0.0, min(1.0,
                                                   -(ax * dx + ay * dy) / seg2))
        px, py = ax + t * dx, ay + t * dy
        dist = math.hypot(px, py)
        if dist < best[2]:
            best = (mp1 + (mp2 - mp1) * t, t, dist)
    return best[0], best[2]


# --------------------------------------------------------------------------- #
# geocoding a street reference
# --------------------------------------------------------------------------- #
class Geocoder:
    """Turns a street reference into a point.

    A protocol, not an implementation: NCDOT work runs on machines with no
    outbound access, and an address guessed from a name is worse than no
    address at all. Supply whatever the office already trusts (the ArcGIS
    locator, a county address point layer) by implementing ``geocode``.
    """

    def geocode(self, street: str, municipality: str = "",
                county: str = "", state: str = "NC"):
        """Return ``(lat, lon)`` or None."""
        raise NotImplementedError


class GazetteerGeocoder(Geocoder):
    """Offline lookup from an address point file already on disk.

    ``address,latitude,longitude[,municipality,county]``. Matching is on the
    normalized street text, narrowed by municipality and county when the file
    carries them, so "MAIN ST" in two towns does not collide.
    """

    def __init__(self, rows=None):
        self._rows = rows or {}

    @classmethod
    def from_csv(cls, path: str) -> "GazetteerGeocoder":
        rows: dict = {}
        with open(path, newline="", encoding="utf-8-sig") as fh:
            for row in csv.DictReader(fh):
                r = {k.strip().lower(): (v or "").strip()
                     for k, v in row.items() if k}
                try:
                    pt = (float(r.get("latitude", "")), float(r.get("longitude", "")))
                except ValueError:
                    continue
                key = (_addr_key(r.get("address", "")),
                       _addr_key(r.get("municipality", "")),
                       _addr_key(r.get("county", "")))
                rows[key] = pt
        return cls(rows)

    def geocode(self, street: str, municipality: str = "",
                county: str = "", state: str = "NC"):
        a = _addr_key(street)
        if not a:
            return None
        for key in ((a, _addr_key(municipality), _addr_key(county)),
                    (a, _addr_key(municipality), ""),
                    (a, "", _addr_key(county)),
                    (a, "", "")):
            if key in self._rows:
                return self._rows[key]
        return None


def _addr_key(text: str) -> str:
    return re.sub(r"[^A-Z0-9]+", " ", (text or "").upper()).strip()


# --------------------------------------------------------------------------- #
# resolution
# --------------------------------------------------------------------------- #
def _disambiguate(from_candidates, toward_candidates, distance, tolerance):
    """Pick the (from, toward) pair the stated distance can actually fit.

    A feature name repeated along a route is only ambiguous until the road the
    crash lies TOWARD is considered: the crash must sit between the two, so the
    pair whose separation covers the distance is the one meant. Pairs that
    cannot fit are discarded, and a tie leaves both as None rather than
    guessing.
    """
    if not from_candidates:
        return None, None
    # Unambiguous names need no disambiguation, and must NOT be filtered by
    # the distance: resolve() reports a distance that overshoots the named
    # road as the inconsistency it is, which is more useful than silence.
    if len(from_candidates) == 1 and len(toward_candidates) <= 1:
        return (from_candidates[0],
                toward_candidates[0] if toward_candidates else None)
    if not toward_candidates:
        return (from_candidates[0], None) if len(from_candidates) == 1 \
            else (None, None)
    d = distance or 0.0
    viable = [(f, t) for f in from_candidates for t in toward_candidates
              if abs(t - f) + tolerance >= d and f != t]
    if len(viable) == 1:
        return viable[0]
    if viable:
        # several fit: prefer the closest pair, but only when it is a clear
        # winner, otherwise refuse
        viable.sort(key=lambda ft: abs(ft[1] - ft[0]))
        if len(viable) == 1 or abs(viable[0][1] - viable[0][0]) < \
                abs(viable[1][1] - viable[1][0]) - tolerance:
            return viable[0]
    return None, None


def resolve(loc: ReportLocation, inventory: FeatureInventory | None = None,
            fiche_milepost: float | None = None,
            tolerance: float = MP_TOLERANCE,
            max_offset_mi: float = 0.25,
            geocoder: "Geocoder | None" = None) -> ResolvedLocation:
    """Best available location for one report; never guesses a milepost."""
    inv = inventory or FeatureInventory()
    route = normalize_route(loc.on_road)
    res = ResolvedLocation(route=loc.on_road.strip(), fiche_milepost=fiche_milepost)

    # 1. coordinates, interpolated onto the route when geometry is available
    if loc.has_coordinates:
        res.latitude, res.longitude = loc.latitude, loc.longitude
        res.method, res.confidence = "coordinates", "medium"
        pts = inv.shape.get(route) or []
        mp, offset = interpolate_milepost(pts, loc.latitude, loc.longitude)
        if mp is not None:
            if offset is not None and offset > max_offset_mi:
                res.notes.append(
                    f"coordinates sit {offset:.2f} mi off {loc.on_road}; "
                    "point may belong to another route")
                res.confidence = "low"
            else:
                res.milepost = round(mp, 2)
                res.confidence = "high"
                res.notes.append(
                    f"milepost interpolated from route geometry"
                    + (f", {offset*5280:.0f} ft off centreline"
                       if offset is not None else ""))
        else:
            res.notes.append("no route geometry available to convert the "
                             "coordinates to a milepost")
    # 2. distance from an intersecting route, signed by the road named "toward"
    if res.milepost is None and loc.dist_from_intersection is not None \
            and loc.from_road:
        from_candidates = inv.mileposts_of(route, loc.from_road)
        toward_candidates = inv.mileposts_of(route, loc.toward_road) \
            if loc.toward_road else []
        mp_from, mp_toward = _disambiguate(
            from_candidates, toward_candidates,
            loc.dist_from_intersection, tolerance)
        if mp_from is None and len(from_candidates) > 1:
            res.notes.append(
                f"{loc.from_road} appears at {len(from_candidates)} mileposts "
                f"on {loc.on_road} ({', '.join(f'{m:.2f}' for m in from_candidates)})"
                " and the report does not say which; milepost not resolved")
            res.method, res.confidence = "features", "low"
        if mp_from is None:
            res.notes.append(
                f"{loc.from_road} is not in the features report for "
                f"{loc.on_road}; distance cannot be converted to a milepost")
        else:
            d = loc.dist_from_intersection
            if loc.at_intersection or d == 0:
                res.milepost, res.method, res.confidence = (
                    round(mp_from, 2), "features", "high")
                res.notes.append(f"at the {loc.from_road} intersection")
            elif mp_toward is not None:
                sign = 1.0 if mp_toward >= mp_from else -1.0
                span = abs(mp_toward - mp_from)
                mp = mp_from + sign * d
                res.method = "features"
                if d > span + tolerance:
                    res.notes.append(
                        f"{d:.2f} mi from {loc.from_road} overshoots "
                        f"{loc.toward_road} ({span:.2f} mi away); distance and "
                        "the named roads disagree")
                    res.confidence = "low"
                    res.milepost = round(mp, 2)
                else:
                    res.milepost, res.confidence = round(mp, 2), "high"
                    res.notes.append(
                        f"MP({loc.from_road})={mp_from:.2f} "
                        f"{'+' if sign > 0 else '-'} {d:.2f} mi toward "
                        f"{loc.toward_road}")
            else:
                res.notes.append(
                    f"{loc.toward_road or 'the road toward'} is not in the "
                    "features report, so the direction of increasing milepost "
                    "is unknown; milepost not resolved")
                res.method, res.confidence = "features", "low"
    # 3. a street address: geocoded when a locator is supplied, and then put
    #    through the same interpolation the report's own coordinates use
    if res.milepost is None and not res.has_point and loc.street:
        res.method = "address"
        point = None
        if geocoder is not None:
            try:
                point = geocoder.geocode(loc.street, loc.municipality,
                                         loc.county)
            except Exception as exc:                # noqa: BLE001 - report it
                res.notes.append(f"geocoder failed: {exc}")
        if point is None:
            res.notes.append(
                f"street reference {loc.street!r}; no geocoder result, so it "
                "is not placed on a route")
        else:
            res.latitude, res.longitude = point
            res.confidence = "medium"
            res.notes.append(f"{loc.street!r} geocoded")
            mp, offset = interpolate_milepost(inv.shape.get(route) or [],
                                              *point)
            if mp is None:
                res.notes.append("no route geometry to convert the geocoded "
                                 "point to a milepost")
            elif offset is not None and offset > max_offset_mi:
                res.notes.append(
                    f"geocoded point sits {offset:.2f} mi off {loc.on_road}; "
                    "not converted to a milepost")
                res.confidence = "low"
            else:
                res.milepost, res.confidence = round(mp, 2), "medium"
                res.notes.append("milepost interpolated from the geocoded "
                                 "point (weaker than report coordinates)")
    # 4. municipality distance locates a town, never a milepost
    if res.milepost is None and not res.has_point and not loc.street:
        if loc.municipality:
            res.method = "municipality"
            where = "in" if loc.in_municipality else "near"
            res.notes.append(
                f"{where} {loc.municipality}"
                + (f", {loc.dist_from_municipality:.2f} mi "
                   f"{loc.dir_from_municipality}".rstrip()
                   if loc.dist_from_municipality is not None else "")
                + "; a municipality distance is not a milepost")
        else:
            res.notes.append("location block carries nothing resolvable")

    if fiche_milepost is not None and res.milepost is not None:
        res.agrees_with_fiche = abs(res.milepost - fiche_milepost) <= tolerance
        if not res.agrees_with_fiche:
            res.notes.append(
                f"resolved MP {res.milepost:.2f} vs coded {fiche_milepost:.2f}: "
                f"off by {abs(res.milepost - fiche_milepost):.2f} mi. In a "
                "section analysis a coded milepost the report contradicts is "
                "the RE case (docs/03)")
    return res


# --------------------------------------------------------------------------- #
# reading the location block off the page
# --------------------------------------------------------------------------- #
#: x bands of the location block, as fractions of page width (measured on the
#: Rev. 1/2009 form and confirmed on two reports).
_LB_ROUTE_X = (0.070, 0.245)        # "on <route>" and "from <route>"
_LB_TOWARD_X = (0.475, 0.735)       # "toward <route>"
_LB_PLACE_X = (0.240, 0.600)        # municipality name
_LB_DIST_X = (0.600, 0.735)         # both "N Miles" boxes
_LB_COORD_X = (0.815, 0.995)        # Latitude / Longitude value lines

_NUM_RE = re.compile(r"^\d{1,3}\.\d{1,2}$")
#: a route designator and its number, tolerating the caption running into the
#: value ("onUS 13") and the lost space ("SR1132")
_ROUTE_IN_TEXT = re.compile(
    r"(?:^|[^A-Za-z]|ON|FROM|ROM|TOWARDS?)(US|NC|SR|I|SC|VA|TN|GA)"
    r"[\s-]*(\d{1,5})\b")
_LEAD_RE = re.compile(r"^(?:on|from|rom|toward|towards|##|#)\b[\s.]*", re.I)
_ROUTE_TOKEN_RE = re.compile(r"^(?:US|NC|SR|I|SC|VA|TN|GA)$", re.I)


def _route_number(text: str) -> str:
    """'onUS 13' -> 'US 13'; '' when the text names no numbered route."""
    raw = (text or "").strip()
    # OCR runs the caption straight into the value ("onUS 13"), which leaves a
    # letter in front of the designator and defeats a plain word boundary
    probe = re.sub(r"^(?:ON|FROM|ROM|TOWARDS?)(?=[A-Z])", " ", raw.upper())
    m = _ROUTE_IN_TEXT.search(probe)
    return f"{m.group(1)} {m.group(2)}" if m else ""


def _clean_route(text: str) -> str:
    """'onUS 13' -> 'US 13'; 'rom SR1132' -> 'SR 1132'; '0 US 13' -> 'US 13'.

    A numbered route is pulled out by pattern, which drops whatever caption or
    stray mark OCR attached to it. Text with no route number is a street name
    and is returned with only the caption words removed.
    """
    numbered = _route_number(text)
    if numbered:
        return numbered
    t = _LEAD_RE.sub("", (text or "").strip())
    return " ".join(t.split())


def read_location_block(words, width: int, height: int) -> ReportLocation:
    """Extract the DMV-349 location block by position.

    Rows are anchored on the form's own printed captions rather than on fixed
    vertical boxes: the two distance fields sit at the same x and only a few
    thousandths of page height apart, so "outside municipality" and
    "(0 ft-Intersection)" are what tell them apart. Anything OCR cannot read is
    left as None; nothing here infers a value.
    """
    from .redact import _visual_rows

    loc = ReportLocation()
    rows = [r for r in _visual_rows(words)
            if 0.10 <= (r[0].top + r[0].height / 2) / max(height, 1) <= 0.30]

    def xs(w):
        return w.left / width, (w.left + w.width) / width

    def in_band(w, band):
        cx = (w.left + w.width / 2) / width
        return band[0] <= cx <= band[1]

    def joined(row, band):
        return " ".join(w.text for w in row if in_band(w, band)).strip()

    def number(row):
        for w in row:
            if in_band(w, _LB_DIST_X) and _NUM_RE.match(w.text.strip()):
                return float(w.text.strip())
        return None

    def has(row, *needles):
        blob = " ".join(w.text for w in row).lower().replace(" ", "")
        return any(n in blob for n in needles)

    def is_routey(row):
        """A row that names a NUMBERED route on the left: the street-name
        fallback would otherwise match any caption text in the band."""
        return bool(_route_number(joined(row, _LB_ROUTE_X)))

    row_a = next((r for r in rows if has(r, "municipality")
                  and not has(r, "intersection")), None)
    row_c = next((r for r in rows if has(r, "toward")), None)
    # row B is the remaining row that names a route on the left: the
    # "(0 ft-Intersection)" caption often lands on its own OCR line, so it
    # cannot be used to find the row that carries the value
    row_b = next((r for r in rows
                  if r is not row_a and r is not row_c and is_routey(r)), None)

    for row in rows:
        if row is row_a:
            place = joined(row, _LB_PLACE_X)
            place = re.sub(r"^(?:near|in)\b[\s.]*", "", place, flags=re.I)
            place = re.sub(r"\b(?:municipality|or)\b", "", place,
                           flags=re.I).strip(" .,")
            if place:
                loc.municipality = place
            loc.in_municipality = has(row, "xin", "[x]in")
            loc.dist_from_municipality = number(row)
        # row B: "on <route> ... <D2> Miles ... (0 ft-Intersection)"
        elif row is row_b:
            route = _clean_route(joined(row, _LB_ROUTE_X))
            if route:
                loc.on_road = route
            loc.dist_from_intersection = number(row)
            if loc.dist_from_intersection in (0.0, None) and has(row, "(0"):
                loc.at_intersection = loc.dist_from_intersection == 0.0
        # row C: "## from <route>   toward <route>"
        elif row is row_c:
            frm = _clean_route(joined(row, _LB_ROUTE_X))
            if frm:
                loc.from_road = frm
            tw = joined(row, _LB_TOWARD_X)
            tw = _clean_route(re.sub(r"^.*?toward[s]?\b", "", tw, flags=re.I)
                              or tw)
            if tw:
                loc.toward_road = tw
        # coordinates: the caption sits left of its value line
        if has(row, "latitude") or has(row, "longitude"):
            val = joined(row, _LB_COORD_X)
            m = re.search(r"-?\d{1,3}\.\d{3,}", val)
            if m:
                if has(row, "latitude"):
                    loc.latitude = float(m.group())
                else:
                    loc.longitude = float(m.group())

    if not loc.on_road:
        # OCR sometimes merges the municipality row into the route row, so the
        # route was consumed as row A. The road the crash is ON is still the
        # first numbered route in the left band above the from/toward row.
        for row in rows:
            if row is row_c:
                break
            route = _route_number(joined(row, _LB_ROUTE_X))
            if route:
                loc.on_road = route
                break
    return loc


# ---------------------------------------------------------------------------
# fiche coordinate quality
# ---------------------------------------------------------------------------

def coordinate_consistency(rows, max_dmp: float = 1.5,
                           min_dmp: float = 0.0) -> dict:
    """How far the DetailedFiche coordinates and coded mileposts disagree.

    ``rows`` is an iterable of ``(coded_mp, latitude, longitude, source)``, all
    on one route.  For each pair of crashes within ``max_dmp`` miles of each
    other by coded milepost, the straight-line distance between their
    coordinates is compared against the difference in their mileposts.  Over a
    short baseline a road is locally straight, so the two should agree; the gap
    is coordinate error and coded-milepost error combined.

    This deliberately fits no route geometry and needs no features report.  An
    earlier attempt that fitted a route through the crash points themselves
    measured the quality of that fit rather than the coordinates (docs/11).

    Results are bucketed by the fiche's ``Source`` column, because coordinates
    taken off the report (``DMV349``, ``DMV349CLEANED``) and coordinates from
    research feeds (``ITRE_*``, ``HSRC_*``) are not the same thing.

    Returns ``{bucket: {"n", "median_ft", "p90_ft", "max_ft", "gaps_ft"}}``.
    The number to beat is the size of a real remilepost, whose median on
    04-15-39049 was 634 ft: a method whose own noise is larger than the
    correction it is looking for cannot find that correction.
    """
    usable = [(float(mp), float(lat), float(lon), str(src or ""))
              for mp, lat, lon, src in rows
              if mp is not None and lat is not None and lon is not None
              and float(mp) < 999]

    buckets: dict[str, list[float]] = {}
    for i, a in enumerate(usable):
        for b in usable[i + 1:]:
            dmp = abs(a[0] - b[0])
            if not (min_dmp <= dmp <= max_dmp):
                continue
            ground_ft = haversine_mi(a[1], a[2], b[1], b[2]) * 5280.0
            gap = abs(ground_ft - dmp * 5280.0)
            key = ("report" if a[3].startswith("DMV349") and b[3].startswith("DMV349")
                   else "other")
            buckets.setdefault(key, []).append(gap)

    out = {}
    for key, gaps in buckets.items():
        gaps.sort()
        out[key] = {
            "n": len(gaps),
            "median_ft": _quantile(gaps, 0.5),
            "p90_ft": _quantile(gaps, 0.9),
            "max_ft": gaps[-1],
            "gaps_ft": gaps,
        }
    return out


def _quantile(sorted_values, q: float) -> float:
    """Linear-interpolated quantile, so an even-length median is the true one."""
    if not sorted_values:
        raise ValueError("no values")
    if len(sorted_values) == 1:
        return sorted_values[0]
    pos = q * (len(sorted_values) - 1)
    lo = int(pos)
    hi = min(lo + 1, len(sorted_values) - 1)
    return sorted_values[lo] + (pos - lo) * (sorted_values[hi] - sorted_values[lo])
