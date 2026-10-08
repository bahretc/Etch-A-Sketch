"""Geometry helpers: distances, polyline projection, Web Mercator tiles."""
from __future__ import annotations

import io
import math
import os
import time
import urllib.request
from dataclasses import dataclass

FT_PER_DEG_LAT = 364_567.2   # feet per degree of latitude (mean)
FT_PER_MILE = 5280.0

TILE_SOURCES = {
    "imagery": {
        "url": "https://server.arcgisonline.com/ArcGIS/rest/services/World_Imagery/MapServer/tile/{z}/{y}/{x}",
        "attribution": "Esri World Imagery (Esri, Maxar, Earthstar Geographics, USDA FSA, USGS)",
        "max_zoom": 19,
    },
    "streets": {
        "url": "https://server.arcgisonline.com/ArcGIS/rest/services/World_Street_Map/MapServer/tile/{z}/{y}/{x}",
        "attribution": "Esri World Street Map (Esri, HERE, Garmin, USGS, NGA)",
        "max_zoom": 19,
    },
    "osm": {
        "url": "https://tile.openstreetmap.org/{z}/{x}/{y}.png",
        "attribution": "OpenStreetMap contributors",
        "max_zoom": 19,
    },
}


def ft_per_deg_lon(lat: float) -> float:
    return FT_PER_DEG_LAT * math.cos(math.radians(lat))


def dist_ft(a: tuple[float, float], b: tuple[float, float]) -> float:
    """Flat-earth distance in feet between two (lat, lon) points (fine at site scale)."""
    lat0 = (a[0] + b[0]) / 2
    dy = (b[0] - a[0]) * FT_PER_DEG_LAT
    dx = (b[1] - a[1]) * ft_per_deg_lon(lat0)
    return math.hypot(dx, dy)


@dataclass
class Projection:
    along_ft: float      # distance along the polyline from its first vertex
    offset_ft: float     # perpendicular distance from the polyline
    seg: int             # index of the segment the point projects onto
    point: tuple[float, float]   # (lat, lon) of the foot of the perpendicular

    @property
    def along_mi(self) -> float:
        return self.along_ft / FT_PER_MILE


class Polyline:
    """A polyline of (lat, lon) vertices with cumulative distances in feet."""

    def __init__(self, latlons: list[tuple[float, float]]):
        self.pts = [tuple(p) for p in latlons]
        self.cum = [0.0]
        for a, b in zip(self.pts, self.pts[1:]):
            self.cum.append(self.cum[-1] + dist_ft(a, b))

    @property
    def length_ft(self) -> float:
        return self.cum[-1]

    def _local(self, origin, p):
        lat0 = origin[0]
        return ((p[1] - origin[1]) * ft_per_deg_lon(lat0), (p[0] - origin[0]) * FT_PER_DEG_LAT)

    def project(self, p: tuple[float, float]) -> Projection:
        best = None
        for i, (a, b) in enumerate(zip(self.pts, self.pts[1:])):
            ax, ay = 0.0, 0.0
            bx, by = self._local(a, b)
            px, py = self._local(a, p)
            seg_len2 = bx * bx + by * by
            t = 0.0 if seg_len2 == 0 else max(0.0, min(1.0, (px * bx + py * by) / seg_len2))
            fx, fy = ax + t * bx, ay + t * by
            off = math.hypot(px - fx, py - fy)
            if best is None or off < best[0]:
                foot = (a[0] + (b[0] - a[0]) * t, a[1] + (b[1] - a[1]) * t)
                best = (off, i, self.cum[i] + t * math.sqrt(seg_len2), foot)
        off, i, along, foot = best
        return Projection(along_ft=along, offset_ft=off, seg=i, point=foot)

    def point_at(self, along_ft: float) -> tuple[float, float]:
        """(lat, lon) at a distance along the polyline (clamped to its ends)."""
        along_ft = max(0.0, min(self.length_ft, along_ft))
        for i, (a, b) in enumerate(zip(self.pts, self.pts[1:])):
            if self.cum[i + 1] >= along_ft:
                seg = self.cum[i + 1] - self.cum[i]
                t = 0.0 if seg == 0 else (along_ft - self.cum[i]) / seg
                return (a[0] + (b[0] - a[0]) * t, a[1] + (b[1] - a[1]) * t)
        return self.pts[-1]

    def point_at_mi(self, mi: float) -> tuple[float, float]:
        return self.point_at(mi * FT_PER_MILE)

    def bearing_at(self, along_ft: float) -> float:
        """Bearing in degrees (0 = north, clockwise) of the segment at a distance along."""
        along_ft = max(0.0, min(self.length_ft - 1e-6, along_ft))
        for i, (a, b) in enumerate(zip(self.pts, self.pts[1:])):
            if self.cum[i + 1] >= along_ft:
                dx, dy = self._local(a, b)
                return math.degrees(math.atan2(dx, dy)) % 360
        return 0.0

    def slice(self, from_ft: float, to_ft: float) -> list[tuple[float, float]]:
        pts = [self.point_at(from_ft)]
        for i, p in enumerate(self.pts):
            if from_ft < self.cum[i] < to_ft:
                pts.append(p)
        pts.append(self.point_at(to_ft))
        return pts


# ---------------------------------------------------------------- Web Mercator

def lonlat_to_pixel(lon: float, lat: float, z: int) -> tuple[float, float]:
    n = 2 ** z * 256
    x = (lon + 180.0) / 360.0 * n
    lat_r = math.radians(lat)
    y = (1.0 - math.log(math.tan(lat_r) + 1 / math.cos(lat_r)) / math.pi) / 2.0 * n
    return x, y


def pixel_to_lonlat(x: float, y: float, z: int) -> tuple[float, float]:
    n = 2 ** z * 256
    lon = x / n * 360.0 - 180.0
    lat = math.degrees(math.atan(math.sinh(math.pi * (1 - 2 * y / n))))
    return lon, lat


def meters_per_pixel(lat: float, z: int) -> float:
    return 156543.03392 * math.cos(math.radians(lat)) / (2 ** z)


class TileCache:
    """Fetches and caches basemap tiles on disk."""

    def __init__(self, cache_dir: str, user_agent: str = "fca/0.1 (fatal crash analysis maps)"):
        self.cache_dir = cache_dir
        self.user_agent = user_agent
        os.makedirs(cache_dir, exist_ok=True)

    def path(self, source: str, z: int, x: int, y: int) -> str:
        return os.path.join(self.cache_dir, source, str(z), f"{x}_{y}.img")

    def get(self, source: str, z: int, x: int, y: int, retries: int = 3) -> bytes | None:
        p = self.path(source, z, x, y)
        if os.path.exists(p):
            with open(p, "rb") as f:
                return f.read()
        url = TILE_SOURCES[source]["url"].format(z=z, x=x, y=y)
        req = urllib.request.Request(url, headers={"User-Agent": self.user_agent})
        for attempt in range(retries):
            try:
                with urllib.request.urlopen(req, timeout=30) as r:
                    data = r.read()
                os.makedirs(os.path.dirname(p), exist_ok=True)
                with open(p, "wb") as f:
                    f.write(data)
                return data
            except Exception:
                time.sleep(1.5 * (attempt + 1))
        return None


def tile_range(bbox: tuple[float, float, float, float], z: int):
    """bbox = (min_lon, min_lat, max_lon, max_lat) -> (x0, y0, x1, y1) tile indexes inclusive."""
    x0, y1 = lonlat_to_pixel(bbox[0], bbox[1], z)
    x1, y0 = lonlat_to_pixel(bbox[2], bbox[3], z)
    return int(x0 // 256), int(y0 // 256), int(x1 // 256), int(y1 // 256)


def stitch(cache: TileCache, source: str, bbox, z: int):
    """Return (PIL image, (px0, py0)) covering bbox at zoom z; px0/py0 are world pixel offsets."""
    from PIL import Image
    x0, y0, x1, y1 = tile_range(bbox, z)
    img = Image.new("RGB", ((x1 - x0 + 1) * 256, (y1 - y0 + 1) * 256), (220, 220, 220))
    for tx in range(x0, x1 + 1):
        for ty in range(y0, y1 + 1):
            data = cache.get(source, z, tx, ty)
            if data:
                try:
                    tile = Image.open(io.BytesIO(data)).convert("RGB")
                    img.paste(tile, ((tx - x0) * 256, (ty - y0) * 256))
                except Exception:
                    pass
    return img, (x0 * 256, y0 * 256)
