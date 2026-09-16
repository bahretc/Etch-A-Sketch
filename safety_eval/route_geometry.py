"""Route centerline geometry: mileposts, curves and grades for a strip site.

The NCDOT AADT traffic segmentation layer carries the route geometry with
BeginMP and EndMP per segment, so chaining the segments of one RouteID and
spreading each segment's milepost span along its length gives a centerline
that is calibrated to the milepost system TEAAS uses. On US 311 (study
260307016EA) the result agreed with the TEAAS features report junctions
within 0.01 mile.

From that centerline:

* ``mp_to_ll`` and ``snap`` convert between mileposts and coordinates, which
  is what the location check (docs/03) uses to turn report coordinates and
  geocoded addresses into mileposts.
* ``horizontal_curves`` finds the curves (PC, PI, PT, radius, deflection)
  from heading change along the line.
* ``elevation_profile`` samples the USGS 3DEP 1 m bare-earth model along the
  line and ``vertical_features`` picks out crests and sags with grades;
  ``sight_distance`` walks the profile for a rough line of sight.
* ``feature_pairs`` turns those into ``(text, milepost)`` lines for the TEAAS
  feature inclusion import (``teaas.write_feature_list``).

Everything is an estimate from public data for the engineer to check; the
docstrings say what each number is good to.
"""
from __future__ import annotations

import json
import math
import statistics
import urllib.parse
import urllib.request
from dataclasses import dataclass, field

from .aadt_arcgis import SEGMENTS_URL, AadtServiceError
from .location import haversine_mi

EPQS_URL = "https://epqs.nationalmap.gov/v1/json"
FT_PER_MI = 5280.0
#: Feet per degree of latitude; longitude scales by cos(latitude). Used by
#: the local flat-earth frames here and in package_maps.
FT_PER_DEG_LAT = 364000.0
_UA = {"User-Agent": "safety-eval route-geometry"}


def route_id(road_code: str | int, county_code: str | int) -> str:
    """The AADT layer RouteID: TEAAS road code + zero-padded county code.

    US 311 (20000311) in Forsyth (34) is ``20000311034``.
    """
    return f"{int(road_code):08d}{int(county_code):03d}"


def _hav_mi(a: tuple[float, float], b: tuple[float, float]) -> float:
    """Great-circle distance in miles between (lat, lon) pairs."""
    return haversine_mi(a[0], a[1], b[0], b[1])


@dataclass
class Centerline:
    """A milepost-calibrated polyline: ``chain`` is ``[(mp, lat, lon), ...]``
    in increasing milepost order."""
    chain: list = field(default_factory=list)
    route_id: str = ""
    source: str = ""

    @property
    def mp_min(self) -> float:
        return self.chain[0][0]

    @property
    def mp_max(self) -> float:
        return self.chain[-1][0]

    def mp_to_ll(self, mp: float) -> tuple[float, float]:
        """(lat, lon) at a milepost, interpolated along the chain."""
        ch = self.chain
        if mp <= ch[0][0]:
            return ch[0][1], ch[0][2]
        for i in range(1, len(ch)):
            if ch[i][0] >= mp:
                m0, a0, o0 = ch[i - 1]
                m1, a1, o1 = ch[i]
                t = (mp - m0) / (m1 - m0) if m1 > m0 else 0.0
                return (round(a0 + t * (a1 - a0), 6),
                        round(o0 + t * (o1 - o0), 6))
        return ch[-1][1], ch[-1][2]

    def snap(self, lat: float, lon: float) -> tuple[float, int]:
        """(milepost, offset_ft) of the nearest point on the centerline.

        A large offset means the coordinate is not on this road (the slip
        for 260307016EA sat 274 ft off in the trees; report coordinates
        are usually within 30 ft).
        """
        k = FT_PER_DEG_LAT
        kx = k * math.cos(math.radians(lat))
        best_mp, best_d = self.chain[0][0], float("inf")
        ch = self.chain
        for i in range(1, len(ch)):
            m0, a0, o0 = ch[i - 1]
            m1, a1, o1 = ch[i]
            x0, y0 = (o0 - lon) * kx, (a0 - lat) * k
            x1, y1 = (o1 - lon) * kx, (a1 - lat) * k
            dx, dy = x1 - x0, y1 - y0
            l2 = dx * dx + dy * dy
            t = 0.0 if l2 == 0 else max(0.0, min(1.0, -(x0 * dx + y0 * dy) / l2))
            d = math.hypot(x0 + t * dx, y0 + t * dy)
            if d < best_d:
                best_d, best_mp = d, m0 + t * (m1 - m0)
        return round(best_mp, 3), int(round(best_d))

    def polyline(self, lo: float | None = None, hi: float | None = None,
                 places: int = 6) -> list:
        """``[[lat, lon], ...]`` between two mileposts (whole line by default),
        with interpolated end points so the ends land exactly on the limits."""
        if lo is None and hi is None:
            return [[round(a, places), round(o, places)]
                    for _, a, o in self.chain]
        lo = self.mp_min if lo is None else lo
        hi = self.mp_max if hi is None else hi
        pts = [list(self.mp_to_ll(lo))]
        pts += [[round(a, places), round(o, places)]
                for m, a, o in self.chain if lo < m < hi]
        pts.append(list(self.mp_to_ll(hi)))
        return pts

    def resample(self, lo: float, hi: float, step_ft: float = 25.0) -> list:
        """Points every ``step_ft`` along the line between two mileposts, as
        ``[(mp, x_ft, y_ft)]`` in a local east/north frame."""
        lat0 = self.mp_to_ll((lo + hi) / 2)[0]
        k = FT_PER_DEG_LAT
        kx = k * math.cos(math.radians(lat0))
        pts = [(m, (o - self.chain[0][2]) * kx, (a - lat0) * k)
               for m, a, o in self.chain if lo - 0.3 <= m <= hi + 0.3]
        out, acc = [], 0.0
        for i in range(1, len(pts)):
            mp0, x0, y0 = pts[i - 1]
            mp1, x1, y1 = pts[i]
            seg = math.hypot(x1 - x0, y1 - y0)
            if not out:
                out.append(pts[i - 1])
            s = step_ft - acc
            while s < seg:
                t = s / seg
                out.append((mp0 + t * (mp1 - mp0), x0 + t * (x1 - x0),
                            y0 + t * (y1 - y0)))
                s += step_ft
            acc = seg - (s - step_ft)
        return out


def fetch_segments(route_id: str, service_url: str = SEGMENTS_URL,
                   timeout: int = 90) -> dict:
    """The traffic segments of one RouteID as a GeoJSON FeatureCollection."""
    params = {"where": f"RouteID='{route_id}'", "outFields": "*",
              "returnGeometry": "true", "outSR": 4326, "f": "geojson"}
    url = f"{service_url}/query?{urllib.parse.urlencode(params)}"
    try:
        with urllib.request.urlopen(urllib.request.Request(url, headers=_UA),
                                    timeout=timeout) as fh:
            payload = json.loads(fh.read().decode("utf-8"))
    except Exception as exc:  # noqa: BLE001
        raise AadtServiceError(
            f"Could not fetch traffic segments for RouteID {route_id} from "
            f"{service_url}: {exc}") from exc
    if "error" in payload:
        raise AadtServiceError(f"segments query failed: {payload['error']}")
    return payload


def centerline_from_segments(collection: dict, route_id: str = "",
                             begin_key: str = "BeginMP",
                             end_key: str = "EndMP") -> Centerline:
    """Chain the segment LineStrings in milepost order and calibrate each
    to its BeginMP..EndMP span by distance along the line."""
    feats = [f for f in collection.get("features", [])
             if not route_id or str(f["properties"].get("RouteID")) == route_id]
    feats.sort(key=lambda f: float(f["properties"][begin_key]))
    chain: list = []
    for f in feats:
        p = f["properties"]
        geom = f["geometry"]
        parts = ([geom["coordinates"]] if geom["type"] == "LineString"
                 else geom["coordinates"])
        coords = [pt for part in parts for pt in part]
        if len(coords) < 2:
            continue
        if chain:
            # digitizing direction is not guaranteed to follow the measure:
            # keep the end that continues from the previous segment first
            last = (chain[-1][1], chain[-1][2])
            if (_hav_mi(last, (coords[-1][1], coords[-1][0]))
                    < _hav_mi(last, (coords[0][1], coords[0][0]))):
                coords = list(reversed(coords))
        d = [0.0]
        for i in range(1, len(coords)):
            d.append(d[-1] + _hav_mi((coords[i - 1][1], coords[i - 1][0]),
                                     (coords[i][1], coords[i][0])))
        b, e = float(p[begin_key]), float(p[end_key])
        for i, (lon, lat) in enumerate(coords):
            mp = b + (e - b) * (d[i] / d[-1] if d[-1] else 0)
            if chain and abs(chain[-1][0] - mp) < 1e-9:
                continue
            chain.append((mp, lat, lon))
    if len(chain) < 2:
        raise ValueError("no usable segment geometry for the route")
    return Centerline(chain=chain, route_id=route_id, source="NCDOT AADT segments")


def load_centerline(route_id: str, cache_path: str | None = None,
                    service_url: str = SEGMENTS_URL) -> Centerline:
    """Centerline for a RouteID, from the cached GeoJSON when present."""
    import os
    if cache_path and os.path.exists(cache_path):
        with open(cache_path, encoding="utf-8") as fh:
            coll = json.load(fh)
    else:
        coll = fetch_segments(route_id, service_url=service_url)
        if cache_path:
            os.makedirs(os.path.dirname(os.path.abspath(cache_path)),
                        exist_ok=True)
            with open(cache_path, "w", encoding="utf-8") as fh:
                json.dump(coll, fh)
    return centerline_from_segments(coll, route_id=route_id)


# ------------------------------------------------------------ horizontal
@dataclass
class Curve:
    pc: float
    pi: float
    pt: float
    radius_ft: float
    delta_deg: float
    direction: str          # "LT" or "RT" for increasing milepost travel
    length_ft: float


def _circle_radius(xs: list, ys: list) -> float:
    """Kasa algebraic circle fit; radius in the points' units."""
    mx, my = statistics.mean(xs), statistics.mean(ys)
    u = [x - mx for x in xs]
    v = [y - my for y in ys]
    suu = sum(a * a for a in u)
    svv = sum(b * b for b in v)
    suv = sum(a * b for a, b in zip(u, v))
    suuu = sum(a ** 3 for a in u)
    svvv = sum(b ** 3 for b in v)
    suvv = sum(a * b * b for a, b in zip(u, v))
    svuu = sum(b * a * a for a, b in zip(u, v))
    det = suu * svv - suv * suv
    if abs(det) < 1e-9:
        return float("inf")
    uc = ((suuu + suvv) * svv - (svvv + svuu) * suv) / (2 * det)
    vc = ((svvv + svuu) * suu - (suuu + suvv) * suv) / (2 * det)
    return math.sqrt(uc * uc + vc * vc + (suu + svv) / len(xs))


def horizontal_curves(cl: Centerline, lo: float, hi: float,
                      step_ft: float = 25.0, window_pts: int = 3,
                      max_radius_ft: float = 2500.0,
                      min_length_ft: float = 150.0,
                      min_delta_deg: float = 5.0) -> list[Curve]:
    """Curves between two mileposts from heading change along the line.

    A curve is a run where the local radius (heading change over about
    150 ft) is under ``max_radius_ft``, at least ``min_length_ft`` long and
    turning at least ``min_delta_deg``; PC and PT are the run ends, PI the
    midpoint, radius from a circle fit of the run. Limits are good to
    about two steps (50 ft) on the mapped centerline.
    """
    res = cl.resample(lo, hi, step_ft)
    n = len(res)
    if n < 2 * window_pts + 3:
        return []

    def heading(a, b):
        return math.atan2(b[2] - a[2], b[1] - a[1])

    curv = []
    for i in range(n):
        a = res[max(0, i - window_pts)]
        b = res[min(n - 1, i + window_pts)]
        h1 = heading(res[max(0, i - 2 * window_pts)], a)
        h2 = heading(b, res[min(n - 1, i + 2 * window_pts)])
        dh = (h2 - h1 + math.pi) % (2 * math.pi) - math.pi
        # the two chord midpoints sit 3 window widths apart along the line
        arc = 3 * window_pts * step_ft
        curv.append(dh / arc)
    runs, cur = [], None
    for i in range(n):
        r = abs(1 / curv[i]) if curv[i] else float("inf")
        if r < max_radius_ft:
            cur = [i, i] if cur is None else [cur[0], i]
        elif cur and i - cur[1] > 4:
            runs.append(cur)
            cur = None
    if cur:
        runs.append(cur)
    out = []
    for a, b in runs:
        length = (b - a) * step_ft
        if length < min_length_ft:
            continue
        seg = res[a:b + 1]
        radius = _circle_radius([p[1] for p in seg], [p[2] for p in seg])
        total = sum(curv[a:b + 1]) * step_ft
        # deflection from the tangent headings either side of the run, which
        # the windowed curvature under-reads at the run ends
        w = 2 * window_pts
        h_in = heading(res[max(0, a - w)], res[a])
        h_out = heading(res[b], res[min(n - 1, b + w)])
        delta = abs(math.degrees((h_out - h_in + math.pi) % (2 * math.pi)
                                 - math.pi))
        if delta < min_delta_deg:
            continue
        if not (lo - 1e-9 <= res[a][0] <= hi + 1e-9
                or lo - 1e-9 <= res[b][0] <= hi + 1e-9):
            continue
        out.append(Curve(pc=round(res[a][0], 3),
                         pi=round((res[a][0] + res[b][0]) / 2, 3),
                         pt=round(res[b][0], 3), radius_ft=round(radius),
                         delta_deg=round(delta), direction="RT" if total < 0
                         else "LT", length_ft=round(length)))
    return out


# -------------------------------------------------------------- vertical
def epqs_elevation_ft(lat: float, lon: float, timeout: int = 30) -> float:
    """Elevation in feet from the USGS 3DEP point query service."""
    qs = urllib.parse.urlencode({"x": f"{lon:.6f}", "y": f"{lat:.6f}",
                                 "units": "Feet", "wkid": 4326,
                                 "includeDate": "false"})
    with urllib.request.urlopen(urllib.request.Request(
            f"{EPQS_URL}?{qs}", headers=_UA), timeout=timeout) as fh:
        return float(json.loads(fh.read().decode("utf-8"))["value"])


def elevation_profile(cl: Centerline, lo: float, hi: float,
                      step_mi: float = 0.01, fetch=epqs_elevation_ft,
                      workers: int = 6) -> list:
    """``[(mp, lat, lon, elev_ft)]`` every ``step_mi`` along the line.

    ``fetch(lat, lon)`` is called per sample (the USGS service by default;
    tests pass a function). Samples that fail three times carry ``None``.
    """
    import concurrent.futures as cf
    samples = []
    mp = lo
    while mp <= hi + 1e-9:
        lat, lon = cl.mp_to_ll(mp)
        samples.append((round(mp, 4), lat, lon))
        mp += step_mi

    def one(s):
        for _ in range(3):
            try:
                return (*s, fetch(s[1], s[2]))
            except Exception:  # noqa: BLE001 - retry, then None
                continue
        return (*s, None)
    with cf.ThreadPoolExecutor(workers) as ex:
        return list(ex.map(one, samples))


@dataclass
class VerticalFeature:
    kind: str               # "CREST" or "SAG"
    mp: float
    elev_ft: float
    prominence_ft: float
    grade_in_pct: float     # approaching with increasing milepost
    grade_out_pct: float


def vertical_features(profile: list, min_prominence_ft: float = 6.0,
                      smooth_pts: int = 2, grade_pts: int = 8) -> list:
    """Crests and sags on a profile, with the grades either side.

    The profile is smoothed with a short moving average (five samples at
    0.01 mile is about 260 ft) before the extrema are picked; prominence is
    the height above (or depth below) the neighbouring minima (maxima)
    within 0.15 mile.
    """
    pts = [p for p in profile if p[3] is not None]
    if len(pts) < 2 * smooth_pts + 3:
        return []
    mp = [p[0] for p in pts]
    z = [p[3] for p in pts]
    zs = [statistics.mean(z[max(0, i - smooth_pts):i + smooth_pts + 1])
          for i in range(len(z))]

    def grade(i0, i1):
        run = (mp[i1] - mp[i0]) * FT_PER_MI
        return 100 * (zs[i1] - zs[i0]) / run if run else 0.0
    out = []
    for i in range(2, len(zs) - 2):
        win = zs[max(0, i - 15):i + 16]
        gi = grade(max(0, i - grade_pts), i)
        go = grade(i, min(len(mp) - 1, i + grade_pts))
        if zs[i] >= max(zs[i - 2:i]) and zs[i] > max(zs[i + 1:i + 3]):
            prom = zs[i] - min(win)
            if prom >= min_prominence_ft:
                out.append(VerticalFeature("CREST", round(mp[i], 2),
                                           round(zs[i]), round(prom),
                                           round(gi, 1), round(go, 1)))
        elif zs[i] <= min(zs[i - 2:i]) and zs[i] < min(zs[i + 1:i + 3]):
            prom = max(win) - zs[i]
            if prom >= min_prominence_ft:
                out.append(VerticalFeature("SAG", round(mp[i], 2),
                                           round(zs[i]), round(prom),
                                           round(gi, 1), round(go, 1)))
    return out


def sight_distance(profile: list, at_mp: float, direction: int = 1,
                   eye_ft: float = 3.5, object_ft: float = 2.0) -> float:
    """Rough sight distance (ft) from ``at_mp`` looking in ``direction``
    (+1 increasing milepost, -1 decreasing) over the bare-earth profile,
    driver eye 3.5 ft and object 2.0 ft (AASHTO stopping sight distance
    heights). Resolution is the profile step, so treat it as an estimate.
    """
    pts = [p for p in profile if p[3] is not None]
    if not pts:
        return 0.0
    i_eye = min(range(len(pts)), key=lambda i: abs(pts[i][0] - at_mp))
    xe, ze = pts[i_eye][0] * FT_PER_MI, pts[i_eye][3] + eye_ft
    best = 0.0
    j = i_eye + direction
    while 0 <= j < len(pts):
        xt, zt = pts[j][0] * FT_PER_MI, pts[j][3] + object_ft
        clear = True
        k = i_eye + direction
        while k != j:
            xk = pts[k][0] * FT_PER_MI
            zline = ze + (zt - ze) * (xk - xe) / (xt - xe)
            if pts[k][3] > zline:
                clear = False
                break
            k += direction
        if not clear:
            break
        best = abs(xt - xe)
        j += direction
    return round(best)


# ----------------------------------------------------------- feature list
def feature_pairs(curves: list, verticals: list, lo: float | None = None,
                  hi: float | None = None) -> list:
    """``(text, milepost)`` rows for the TEAAS feature inclusion import:
    CURVE n PC / PI / PT and CREST n / SAG n, inside the limits when given.
    Text stays under the 20 character TEAAS cap."""
    rows = []
    for n, c in enumerate(curves, start=1):
        for tag, mp in (("PC", c.pc), ("PI", c.pi), ("PT", c.pt)):
            rows.append((f"CURVE {n} {tag}", mp))
    nc = ns = 0
    for v in verticals:
        if v.kind == "CREST":
            nc += 1
            rows.append((f"CREST {nc}", v.mp))
        else:
            ns += 1
            rows.append((f"SAG {ns}", v.mp))
    if lo is not None or hi is not None:
        rows = [(t, m) for t, m in rows
                if (lo is None or m >= lo - 1e-9)
                and (hi is None or m <= hi + 1e-9)]
    return rows


def features_markdown(curves: list, verticals: list) -> str:
    """A short table of the derived features for the engineer's notes."""
    lines = ["| Feature | MP | Detail |", "|---|---|---|"]
    for n, c in enumerate(curves, start=1):
        lines.append(f"| Curve {n} | PC {c.pc:.3f}, PI {c.pi:.3f}, PT {c.pt:.3f} "
                     f"| R about {c.radius_ft:,.0f} ft, {c.delta_deg:.0f} deg, "
                     f"{c.length_ft:,.0f} ft, turns {c.direction} with "
                     f"increasing MP |")
    for v in verticals:
        lines.append(f"| {v.kind.title()} | {v.mp:.2f} | elev {v.elev_ft:.0f} ft, "
                     f"grades {v.grade_in_pct:+.1f}% / {v.grade_out_pct:+.1f}% |")
    return "\n".join(lines)
