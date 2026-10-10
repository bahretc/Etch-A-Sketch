"""Report figures in the TSU fatal-crash-analysis layout (landscape letter, title strip, legend, scale bar, north arrow).

Figure 1  Area Map      light line map, study limits band, crash callout, municipal and county boundaries
Figure 2  Location Map  aerial of the section, study limits band, crash callout, route shields
Figure 3  Crash Map     aerial with the initial-study crashes and the fiche review candidates (numbered)
"""
from __future__ import annotations

import json
import math
import os
import textwrap

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
import matplotlib.patheffects as pe
from matplotlib.lines import Line2D
from matplotlib.patches import Circle, Polygon, Rectangle, FancyBboxPatch, RegularPolygon

from .geo import FT_PER_MILE, TILE_SOURCES, TileCache, lonlat_to_pixel, meters_per_pixel, stitch
from .maps import PRIORITY_STYLE, crash_points
from .screen import Screened, Study

TILE_SOURCES["lightgray"] = {
    "url": "https://server.arcgisonline.com/ArcGIS/rest/services/Canvas/World_Light_Gray_Base/MapServer/tile/{z}/{y}/{x}",
    "attribution": "Esri World Light Gray Canvas (Esri, HERE, Garmin, OpenStreetMap contributors)",
    "max_zoom": 16,
}
TILE_SOURCES["lightgray_ref"] = {
    "url": "https://server.arcgisonline.com/ArcGIS/rest/services/Canvas/World_Light_Gray_Reference/MapServer/tile/{z}/{y}/{x}",
    "attribution": "Esri",
    "max_zoom": 16,
}
TILE_SOURCES["positron"] = {
    "url": "https://a.basemaps.cartocdn.com/light_all/{z}/{x}/{y}.png",
    "attribution": "CARTO, OpenStreetMap contributors",
    "max_zoom": 19,
}
RED = "#d0021b"
PURPLE = "#b48ad8"
FONT = "DejaVu Sans"


def _fit_bbox(bbox, z, aspect, west_bias=0.5, south_bias=0.5):
    """Expand bbox (min_lon, min_lat, max_lon, max_lat) so its Web Mercator pixel extent has the given aspect."""
    from .geo import pixel_to_lonlat
    x0, y1 = lonlat_to_pixel(bbox[0], bbox[1], z)
    x1, y0 = lonlat_to_pixel(bbox[2], bbox[3], z)
    w, h = x1 - x0, y1 - y0
    if w / h < aspect:
        extra = h * aspect - w
        x0 -= extra * west_bias; x1 += extra * (1 - west_bias)
    else:
        extra = w / aspect - h
        y1 += extra * south_bias; y0 -= extra * (1 - south_bias)
    lon0, lat1 = pixel_to_lonlat(x0, y1, z)
    lon1, lat0 = pixel_to_lonlat(x1, y0, z)
    return (lon0, lat1, lon1, lat0)


def _lighten(img, amount):
    """Desaturate and lighten a basemap so overlays stand out (0 = unchanged, 1 = white)."""
    from PIL import Image, ImageOps
    g = ImageOps.grayscale(img).convert("RGB")
    return Image.blend(g, Image.new("RGB", g.size, (255, 255, 255)), amount)


def _composite_overlay(cache, source, bbox, z, base):
    """Paste transparent label tiles (PNG with alpha) over a stitched base image."""
    import io
    from PIL import Image
    from .geo import tile_range
    x0, y0, x1, y1 = tile_range(bbox, z)
    out = base.convert("RGBA")
    for tx in range(x0, x1 + 1):
        for ty in range(y0, y1 + 1):
            data = cache.get(source, z, tx, ty)
            if data:
                try:
                    t = Image.open(io.BytesIO(data)).convert("RGBA")
                    out.alpha_composite(t, ((tx - x0) * 256, (ty - y0) * 256))
                except Exception:
                    pass
    return out.convert("RGB")


class Figure:
    """A map figure in the report frame: map panel with border, legend, scale bar, north arrow, title strip."""

    def __init__(self, cache: TileCache, source: str, bbox, z: int, dpi: int = 200, overlay: str | None = None,
                 west_bias: float = 0.5, south_bias: float = 0.5, lighten: float = 0.0):
        self.cache, self.source, self.z = cache, source, z
        self.fig = plt.figure(figsize=(11, 8.5), dpi=dpi)
        self.fig.patch.set_facecolor("white")
        # frame in figure fractions
        self.L, self.R, self.T, self.B = 0.035, 0.965, 0.965, 0.035
        self.strip_h = 0.115
        self.ax = self.fig.add_axes([self.L, self.B + self.strip_h, self.R - self.L, self.T - self.B - self.strip_h])
        aspect = ((self.R - self.L) * 11.0) / ((self.T - self.B - self.strip_h) * 8.5)
        bbox = _fit_bbox(bbox, z, aspect, west_bias, south_bias)
        self.bbox = bbox
        img, (px0, py0) = stitch(cache, source, bbox, z)
        if overlay:
            img = _composite_overlay(cache, overlay, bbox, z, img)
        if lighten:
            img = _lighten(img, lighten)
        w, h = img.size
        self.ax.imshow(img, extent=(px0, px0 + w, py0 + h, py0), interpolation="bilinear", zorder=0)
        x0, y1 = lonlat_to_pixel(bbox[0], bbox[1], z)
        x1, y0 = lonlat_to_pixel(bbox[2], bbox[3], z)
        self.ax.set_xlim(x0, x1); self.ax.set_ylim(y1, y0)
        self.ax.set_xticks([]); self.ax.set_yticks([])
        for sp in self.ax.spines.values():
            sp.set_edgecolor("black"); sp.set_linewidth(1.2)
        self.xlim, self.ylim = (x0, x1), (y0, y1)
        self.center_lat = (bbox[1] + bbox[3]) / 2
        self.ft_per_px = meters_per_pixel(self.center_lat, z) * 3.28084
        self.fig.canvas.draw()
        bb = self.ax.get_window_extent()
        self.pt_per_px = (bb.width / (x1 - x0)) * 72.0 / dpi   # display points per world pixel

    # ----------------------------------------------------------- coordinates
    def px(self, lat, lon):
        return lonlat_to_pixel(lon, lat, self.z)

    def frac(self, fx, fy):
        """map-axes fraction -> world pixel coordinates"""
        return self.xlim[0] + (self.xlim[1] - self.xlim[0]) * fx, self.ylim[1] - (self.ylim[1] - self.ylim[0]) * fy

    def pts_to_px(self, pts):
        return pts / self.pt_per_px

    # ----------------------------------------------------------- drawing helpers
    def polyline(self, latlons, **kw):
        xs, ys = zip(*[self.px(a, b) for a, b in latlons])
        return self.ax.plot(xs, ys, **kw)

    def polygon_from_geojson(self, geom, **kw):
        rings = []
        if geom["type"] == "Polygon":
            rings = [geom["coordinates"][0]]
        elif geom["type"] == "MultiPolygon":
            rings = [p[0] for p in geom["coordinates"]]
        for ring in rings:
            xs, ys = zip(*[self.px(lat, lon) for lon, lat in ring])
            self.ax.plot(xs, ys, **kw)

    def label(self, lat, lon, text, dx=0, dy=0, halo="white", color="black", size=7.5, **kw):
        x, y = self.px(lat, lon)
        kw.setdefault("ha", "center"); kw.setdefault("va", "center"); kw.setdefault("zorder", 40)
        return self.ax.text(x + dx, y + dy, text, fontsize=size, color=color, family=FONT,
                            path_effects=[pe.withStroke(linewidth=2.5, foreground=halo)] if halo else None, **kw)

    def crash_circle(self, lat, lon, radius_pt=9):
        x, y = self.px(lat, lon)
        r = self.pts_to_px(radius_pt)
        self._circle_pt = radius_pt
        self.ax.add_patch(Circle((x, y), r, fill=False, ec=RED, lw=2.2, zorder=35))
        return x, y, r

    def callout(self, lat, lon, lines, box_frac, title="Crash Location:"):
        """White box with red border at box_frac (axes fraction of its center) and a leader to the point."""
        x, y = self.px(lat, lon)
        bx, by = self.frac(*box_frac)
        txt = title + "\n" + "\n".join(lines)
        t = self.ax.text(bx, by, txt, fontsize=7.5, family=FONT, ha="center", va="center", zorder=46, linespacing=1.35,
                         bbox=dict(boxstyle="square,pad=0.6", fc="white", ec=RED, lw=1.4))
        # bold-underlined title: overlay the title line separately
        self.fig.canvas.draw()
        bbox = t.get_window_extent().transformed(self.ax.transData.inverted())
        tx = bx
        ty = bbox.y1 - (bbox.y1 - bbox.y0) * 0.5 / (len(lines) + 1)
        t.set_text("\n" + "\n".join(lines))
        self.ax.text(tx, ty, title, fontsize=7.5, family=FONT, fontweight="bold", ha="center", va="center", zorder=47)
        self.ax.plot([tx, tx], [ty + (bbox.y1 - bbox.y0) * 0.08, ty + (bbox.y1 - bbox.y0) * 0.08], lw=0)  # no-op keeps limits
        # leader from the nearest box edge to the circle edge
        ex = min(max(x, bbox.x0), bbox.x1); ey = min(max(y, bbox.y0), bbox.y1)
        r = self.pts_to_px(getattr(self, "_circle_pt", 9))
        d = math.hypot(x - ex, y - ey) or 1.0
        self.ax.plot([ex, x - (x - ex) / d * r], [ey, y - (y - ey) / d * r], color=RED, lw=1.3, zorder=45)

    def north_arrow(self, fx=0.965, fy=0.965):
        x, y = self.frac(fx, fy)
        h = self.pts_to_px(26)
        tri = Polygon([(x, y - h * 0.05), (x - h * 0.28, y + h * 0.75), (x, y + h * 0.5), (x + h * 0.28, y + h * 0.75)],
                      closed=True, fc="black", ec="black", zorder=50)
        self.ax.add_patch(tri)
        self.ax.text(x, y - h * 0.2, "N", ha="center", va="bottom", fontsize=9, fontweight="bold", family=FONT, zorder=50)

    def scale_bar(self, total_ft, unit, fx=0.985, fy=0.03, divisions=2):
        """Alternating black/white bar; right-aligned at fx, bottom at fy."""
        w = total_ft / self.ft_per_px
        x1, y = self.frac(fx, fy)
        x0 = x1 - w
        h = self.pts_to_px(4)
        self.ax.add_patch(Rectangle((x0 - self.pts_to_px(6), y - self.pts_to_px(14)), w + self.pts_to_px(12), self.pts_to_px(26),
                                    fc="white", ec="none", alpha=0.85, zorder=48))
        for i in range(divisions):
            self.ax.add_patch(Rectangle((x0 + w * i / divisions, y - h), w / divisions, h,
                                        fc="black" if i % 2 == 0 else "white", ec="black", lw=0.8, zorder=49))
        for i in range(divisions + 1):
            v = total_ft * i / divisions
            lab = f"{v / FT_PER_MILE:g}" if unit == "Miles" else f"{v:,.0f}"
            self.ax.text(x0 + w * i / divisions, y - h - self.pts_to_px(2), lab, ha="center", va="bottom", fontsize=6.5, family=FONT, zorder=50)
        self.ax.text(x1 + self.pts_to_px(10), y - h / 2, unit, ha="left", va="center", fontsize=6.5, family=FONT, zorder=50)

    def legend(self, items, fx=0.985, fy=0.085, title="Legend"):
        """items: list of (handle, label). Anchored bottom-right at the axes fraction."""
        from matplotlib.font_manager import FontProperties
        lg = self.ax.legend(handles=[h for h, _ in items], labels=[l for _, l in items], title=title, loc="lower right",
                            bbox_to_anchor=(fx, fy), framealpha=1.0, edgecolor="black", fancybox=False, borderpad=0.8,
                            labelspacing=0.8, handlelength=2.2, prop=FontProperties(family=FONT, size=7.2),
                            title_fontproperties=FontProperties(family=FONT, size=8.2, weight="bold"))
        lg.get_frame().set_linewidth(1.0)
        lg.set_zorder(60)

    def title_strip(self, cfg, fig_no, fig_title, mp_text, boundaries=None):
        f = cfg["figures"]
        L, R, B = self.L, self.R, self.B
        H = self.strip_h - 0.012
        ax = self.fig.add_axes([L, B, R - L, H]); ax.set_xlim(0, 1); ax.set_ylim(0, 1); ax.axis("off")
        ax.add_patch(Rectangle((0, 0), 1, 1, fill=False, ec="black", lw=1.2, transform=ax.transAxes))
        # column edges (fractions of the strip width)
        cols = [0.0, 0.17, 0.30, 0.64, 0.76, 0.87, 1.0]
        for c in cols[1:-1]:
            ax.plot([c, c], [0, 1], color="black", lw=1.0)
        # cell 1: prepared for
        ax.text(cols[0] + 0.085, 0.5, f.get("prepared_for", ""), ha="center", va="center", fontsize=8, family=FONT, linespacing=1.4)
        # cell 2: county thumbnail
        if boundaries:
            self._county_thumb(ax, boundaries, (cols[1], cols[2]), cfg["county"].title() + " County")
        # cell 3: slip + description
        ax.text((cols[2] + cols[3]) / 2, 0.80, f"Slip No. {f['slip_no']}", ha="center", va="center", fontsize=8.5, fontweight="bold", family=FONT)
        ax.text((cols[2] + cols[3]) / 2, 0.40, "\n".join(f["description_lines"]), ha="center", va="center", fontsize=7.3, family=FONT, linespacing=1.4)
        # cell 4: lat / long
        fat = cfg["fatal"]
        ax.plot([cols[3], cols[4]], [0.5, 0.5], color="black", lw=0.8)
        ax.text((cols[3] + cols[4]) / 2, 0.75, f"Latitude:\n{fat['lat']}", ha="center", va="center", fontsize=7.3, family=FONT, linespacing=1.3)
        ax.text((cols[3] + cols[4]) / 2, 0.25, f"Longitude:\n{fat['lon']}", ha="center", va="center", fontsize=7.3, family=FONT, linespacing=1.3)
        # cell 5: milepost / division
        ax.plot([cols[4], cols[5]], [0.5, 0.5], color="black", lw=0.8)
        ax.text((cols[4] + cols[5]) / 2, 0.75, f"Milepost:\n{mp_text}", ha="center", va="center", fontsize=7.3, family=FONT, linespacing=1.3)
        ax.text((cols[4] + cols[5]) / 2, 0.25, f"Division:\n{cfg['division']}", ha="center", va="center", fontsize=7.3, family=FONT, linespacing=1.3)
        # cell 6: figure no / title / date
        ax.text((cols[5] + cols[6]) / 2, 0.72, f"Figure No. {fig_no}", ha="center", va="center", fontsize=8.5, fontweight="bold", family=FONT)
        ax.text((cols[5] + cols[6]) / 2, 0.45, fig_title, ha="center", va="center", fontsize=7.5, family=FONT)
        ax.text((cols[5] + cols[6]) / 2, 0.20, f.get("date_label", ""), ha="center", va="center", fontsize=6.8, family=FONT)
        # attribution line under the strip
        self.fig.text(L, B - 0.012, "Basemap: " + TILE_SOURCES[self.source]["attribution"] + ". Boundaries and centerline: OpenStreetMap. Crash data: NCDOT TEAAS and DMV-349 reports.",
                      fontsize=5.5, color="#444", va="center", family=FONT)

    def _county_thumb(self, ax, boundaries, xr, county_name):
        """Small NC outline with the county filled, drawn in the strip cell."""
        nc = boundaries["north_carolina"]; co = boundaries["brunswick_county"]
        def rings(g):
            return [g["coordinates"][0]] if g["type"] == "Polygon" else [p[0] for p in g["coordinates"]]
        allpts = [p for r in rings(nc) for p in r]
        lons = [p[0] for p in allpts]; lats = [p[1] for p in allpts]
        mnx, mxx, mny, mxy = min(lons), max(lons), min(lats), max(lats)
        cx = (xr[0] + xr[1]) / 2
        W = (xr[1] - xr[0]) * 0.9
        asp = (mxy - mny) / (mxx - mnx) * 1.0 / math.cos(math.radians(35.5))
        strip_aspect = (self.fig.get_figheight() * (self.strip_h - 0.012)) / (self.fig.get_figwidth() * (self.R - self.L))
        Hh = W * asp / strip_aspect
        if Hh > 0.55:
            Hh = 0.55; W = Hh * strip_aspect / asp
        def tx(lon, lat):
            return cx - W / 2 + (lon - mnx) / (mxx - mnx) * W, 0.62 - Hh / 2 + (lat - mny) / (mxy - mny) * Hh
        for r in rings(nc):
            ax.add_patch(Polygon([tx(*p) for p in r], closed=True, fc="#f2f2f2", ec="#555", lw=0.5))
        for r in rings(co):
            ax.add_patch(Polygon([tx(*p) for p in r], closed=True, fc=RED, ec=RED, lw=0.5))
        ax.text(cx, 0.17, county_name, ha="center", va="center", fontsize=7, family=FONT)

    def save(self, path_png, path_pdf=None):
        self.fig.savefig(path_png, dpi=self.fig.dpi, facecolor="white")
        if path_pdf:
            self.fig.savefig(path_pdf, facecolor="white")
        plt.close(self.fig)


# ---------------------------------------------------------------------- shared overlays

def _limits_band(F: Figure, study: Study, lw_pt=9, alpha=0.75, zorder=20):
    pl = study.centerline
    sec = pl.slice(study.begin_mp * FT_PER_MILE, study.end_mp * FT_PER_MILE)
    F.polyline(sec, color=PURPLE, lw=lw_pt, alpha=alpha, zorder=zorder, solid_capstyle="butt")


def _shield(F: Figure, lat, lon, number, bus=False, size_pt=13):
    x, y = F.px(lat, lon)
    r = F.pts_to_px(size_pt)
    F.ax.add_patch(RegularPolygon((x, y), 4, radius=r, orientation=0, fc="white", ec="black", lw=1.1, zorder=42))
    F.ax.text(x, y, number, ha="center", va="center", fontsize=6.5, fontweight="bold", family=FONT, zorder=43)
    if bus:
        F.ax.text(x, y - r - F.pts_to_px(3), "BUS", ha="center", va="bottom", fontsize=5.5, fontweight="bold", family=FONT, zorder=43,
                  bbox=dict(boxstyle="square,pad=0.15", fc="white", ec="black", lw=0.6))


def _road_labels(F: Figure, cfg, shields=True, names=True, bus=True):
    for rl in cfg["figures"].get("road_labels", []):
        if rl.get("shield"):
            if shields and (bus or not rl.get("bus")):
                _shield(F, rl["lat"], rl["lon"], rl["shield"], bus=rl.get("bus", False))
        elif names:
            F.label(rl["lat"], rl["lon"], rl["text"], rotation=rl.get("rot", 0), size=7, color="black", halo="white")


def _load_boundaries(study: Study):
    p = study.cfg.get("inputs", {}).get("boundaries")
    if not p:
        return None
    with open(os.path.join(study.root, p)) as f:
        return json.load(f)


# ---------------------------------------------------------------------- figures

def figure_area_map(study: Study, cache: TileCache, out_png, out_pdf):
    cfg = study.cfg
    bbox = tuple(cfg["figures"]["area_bbox"])
    F = Figure(cache, "streets", bbox, 14, lighten=0.42)
    bd = _load_boundaries(study)
    if bd:
        F.polygon_from_geojson(bd["brunswick_county"], color="#e6d800", lw=2.2, ls=(0, (4, 2)), zorder=12)
        for name, g in bd["municipalities"].items():
            F.polygon_from_geojson(g, color="#666666", lw=1.6, ls=(0, (1, 1.5)), zorder=12)
    _limits_band(F, study, lw_pt=10, alpha=0.8)
    fat = cfg["fatal"]
    F.crash_circle(fat["lat"], fat["lon"], radius_pt=10)
    F.callout(fat["lat"], fat["lon"], cfg["figures"]["crash_callout"], box_frac=(0.30, 0.56))
    F.north_arrow()
    handles = [
        (Line2D([0], [0], marker="o", color="w", mfc="none", mec=RED, mew=2, ms=11), "Study Crash Location"),
        (Line2D([0], [0], color=PURPLE, lw=7, alpha=0.8), "Crash Analysis Study Limits"),
        (Line2D([0], [0], color="#666666", lw=1.6, ls=(0, (1, 1.5))), "Municipal Boundary"),
        (Line2D([0], [0], color="#e6d800", lw=2.2, ls=(0, (4, 2))), "County Boundary"),
    ]
    F.legend(handles, fx=0.985, fy=0.10)
    F.scale_bar(FT_PER_MILE * 1.0, "Miles", fx=0.955, fy=0.035, divisions=2)
    F.title_strip(cfg, 1, "Area Map", f"{fat['mp']:.3f}", bd)
    F.save(out_png, out_pdf)


def figure_location_map(study: Study, cache: TileCache, out_png, out_pdf, z=18):
    cfg = study.cfg
    from .maps import _section_bbox
    bbox = _section_bbox(study, pad_ft=420, mp_pad=0.05)
    F = Figure(cache, "imagery", bbox, z, west_bias=0.45, south_bias=0.5)
    pl = study.centerline
    F.polyline(pl.pts, color="white", lw=2.0, alpha=0.55, zorder=15)
    _limits_band(F, study, lw_pt=9, alpha=0.7)
    # limit ticks and labels
    for mp, name, which in ((study.begin_mp, cfg["limits"]["begin_desc"], "Begin"), (study.end_mp, cfg["limits"]["end_desc"], "End")):
        p = pl.point_at_mi(mp)
        brg = math.radians(pl.bearing_at(mp * FT_PER_MILE))
        nx, ny = math.cos(brg), math.sin(brg)
        x, y = F.px(*p)
        Lh = F.pts_to_px(9)
        F.ax.plot([x - nx * Lh, x + nx * Lh], [y - ny * Lh, y + ny * Lh], color=PURPLE, lw=3.5, zorder=22)
        F.ax.text(x - nx * F.pts_to_px(14), y - ny * F.pts_to_px(14), f"{which} study limits\nMP {mp:.3f}\n{name}", fontsize=6.5, family=FONT,
                  ha="right", va="center", color="white", zorder=41, linespacing=1.3,
                  path_effects=[pe.withStroke(linewidth=2.5, foreground="black")])
    # features
    for f in cfg.get("features", []):
        if f.get("limit") or "lat" not in f or "CHARROS" in " ".join(f.get("fiche_names", [])).upper() or f["mp"] == 0:
            continue
        x, y = F.px(f["lat"], f["lon"])
        F.ax.plot(x, y, marker="o", ms=4, mfc="white", mec="black", zorder=30)
        side = f.get("label_side", "E")
        dx = F.pts_to_px(6) * (1 if side == "E" else -1)
        F.label(f["lat"], f["lon"], f["short"], dx=dx, ha="left" if side == "E" else "right", size=6.8, color="white", halo="black")
    _road_labels(F, cfg)
    fat = cfg["fatal"]
    F.crash_circle(fat["lat"], fat["lon"], radius_pt=11)
    F.callout(fat["lat"], fat["lon"], cfg["figures"]["crash_callout"], box_frac=(0.74, 0.74))
    F.north_arrow()
    handles = [
        (Line2D([0], [0], marker="o", color="w", mfc="none", mec=RED, mew=2, ms=11), "Study Crash Location"),
        (Line2D([0], [0], color=PURPLE, lw=7, alpha=0.75), "Crash Analysis Study Limits"),
        (Line2D([0], [0], marker="o", color="w", mfc="white", mec="black", ms=5), "Side street / driveway (milepost in the workbook)"),
    ]
    F.legend(handles, fx=0.985, fy=0.10)
    F.scale_bar(400, "Feet", fx=0.955, fy=0.035, divisions=2)
    F.title_strip(cfg, 2, "Location Map", f"{fat['mp']:.3f}", _load_boundaries(study))
    F.save(out_png, out_pdf)


def figure_crash_map(study: Study, screened: list[Screened], cache: TileCache, out_png, out_pdf, z=18, decisions=None):
    """Numbered crash map. decisions: optional {crash_id: {"decision": .., "mp": .., "lat":.., "lon":..}} after the report review."""
    cfg = study.cfg
    from .maps import _section_bbox
    bbox = list(_section_bbox(study, pad_ft=330, mp_pad=0.04))
    bbox[1] -= 420 / 364567.2          # room for the key panel below the section
    bbox = tuple(bbox)
    F = Figure(cache, "imagery", bbox, z, west_bias=0.7, south_bias=0.7)
    pl = study.centerline
    F.polyline(pl.pts, color="white", lw=2.0, alpha=0.55, zorder=15)
    _limits_band(F, study, lw_pt=9, alpha=0.6)
    for mp, which in ((study.begin_mp, "Begin"), (study.end_mp, "End")):
        p = pl.point_at_mi(mp)
        brg = math.radians(pl.bearing_at(mp * FT_PER_MILE))
        nx, ny = math.cos(brg), math.sin(brg)
        x, y = F.px(*p)
        Lh = F.pts_to_px(9)
        F.ax.plot([x - nx * Lh, x + nx * Lh], [y - ny * Lh, y + ny * Lh], color=PURPLE, lw=3.5, zorder=22)
        F.ax.text(x - nx * F.pts_to_px(13), y - ny * F.pts_to_px(13), f"{which} MP {mp:.3f}", fontsize=6.5, family=FONT, ha="right", va="center",
                  color="white", zorder=41, path_effects=[pe.withStroke(linewidth=2.5, foreground="black")])
    for f in cfg.get("features", []):
        if f.get("limit") or "lat" not in f or "CHARROS" in " ".join(f.get("fiche_names", [])).upper() or f["mp"] == 0:
            continue
        side = f.get("label_side", "E")
        dx = F.pts_to_px(5) * (1 if side == "E" else -1)
        F.label(f["lat"], f["lon"], f["short"], dx=dx, ha="left" if side == "E" else "right", size=6.3, color="#dddddd", halo="black")
    _road_labels(F, cfg, names=False, bus=False)
    pts = crash_points(study, screened)
    styles = dict(PRIORITY_STYLE)
    if decisions:
        # restyle by decision
        styles = {"IS": {"label": "In study (IS)", "color": "#1f77b4"}, "ADD": {"label": "Added to study (ADD)", "color": "#d62728"},
                  "DEL": {"label": "Deleted from study (DEL)", "color": "#ff7f0e"}, "NIS": {"label": "Not in study (NIS)", "color": "#bdbdbd"}}
        for p in pts:
            d = decisions.get(str(p["crash_id"])) or decisions.get(p["crash_id"])
            if d:
                p["priority"] = d["decision"]
                if d.get("lat") and d.get("lon"):
                    p["lat"], p["lon"] = d["lat"], d["lon"]; p["basis"] = "report location"
                elif d.get("mp") is not None and d["mp"] >= 0:
                    p["lat"], p["lon"] = pl.point_at_mi(d["mp"]); p["basis"] = f"report MP {d['mp']:.3f}"
                p["mp_along"] = pl.project((p["lat"], p["lon"])).along_mi
    sep = F.pts_to_px(15)
    x0, x1 = F.xlim; y0, y1 = F.ylim
    margin = sep
    placed = []
    def free(ax_, ay_):
        if not (x0 + margin < ax_ < x1 - margin and y0 + margin < ay_ < y1 - margin):
            return False
        return all(math.hypot(ax_ - qx, ay_ - qy) >= sep for qx, qy in placed)
    for p in sorted(pts, key=lambda q: (q["priority"] != 0 and q["priority"] != "IS", q["mp_along"])):
        x, y = F.px(p["lat"], p["lon"])
        brg = math.radians(pl.bearing_at(p["mp_along"] * FT_PER_MILE))
        perp = math.atan2(math.sin(brg), math.cos(brg))
        lx, ly = x, y
        if not free(lx, ly):
            found = False
            for ring in range(1, 9):
                for da in (0, 180, 45, 225, 135, 315, 90, 270, 22, 202, 158, 338, 68, 248, 112, 292):
                    a = perp + math.radians(da)
                    cx, cy = x + math.cos(a) * sep * ring, y + math.sin(a) * sep * ring
                    if free(cx, cy):
                        lx, ly, found = cx, cy, True; break
                if found:
                    break
        placed.append((lx, ly))
        st = styles[p["priority"]]
        if (lx, ly) != (x, y):
            F.ax.plot([x, lx], [y, ly], color="white", lw=0.9, zorder=24)
            F.ax.plot(x, y, marker=".", ms=4, color="white", zorder=25)
        if p["fatal"]:
            F.ax.plot(lx, ly, marker="*", ms=17, mfc="#ffd400", mec="black", mew=1.0, zorder=30)
        else:
            F.ax.plot(lx, ly, marker="o", ms=12.5, mfc=st["color"], mec="black", mew=0.9, zorder=28)
        dark = p["priority"] in (3, 5, 0, "IS", "NIS") or p["fatal"]
        F.ax.text(lx, ly, str(p["n"]), ha="center", va="center", fontsize=6.2, fontweight="bold", family=FONT,
                  color="black" if dark else "white", zorder=31)
    fat = cfg["fatal"]
    # key panel (lower left) listing the crashes
    lines = []
    order = [0, 1, 2, 3, 4, 5] if not decisions else ["IS", "ADD", "DEL", "NIS"]
    for k in order:
        grp = [p for p in pts if p["priority"] == k]
        if not grp:
            continue
        lines.append(("hdr", styles[k]["color"], styles[k]["label"]))
        for p in grp:
            mp = f"  MP {p['mp']:.3f}" if p.get("mp") is not None else ""
            lines.append(("row", None, f"{p['n']:>2}  {p['crash_id']}  {p['date']}  {p['type']:<5} {p['severity']}{mp}"))
    # two columns
    ncol = 2
    per = math.ceil(len(lines) / ncol)
    cols_ = [lines[i * per:(i + 1) * per] for i in range(ncol)]
    px_, py_ = F.frac(0.012, 0.012)
    lh = F.pts_to_px(8.2)
    Hh = lh * (per + 2.0)
    colw = F.pts_to_px(195)
    Ww = colw * ncol + F.pts_to_px(10)
    F.ax.add_patch(Rectangle((px_, py_ - Hh), Ww, Hh, fc="white", ec="black", lw=0.8, alpha=0.95, zorder=58))
    F.ax.text(px_ + F.pts_to_px(5), py_ - Hh + lh * 0.9, "Crashes shown (numbers follow the Review IDs sheet; K fatal, B/C injury, O no injury)",
              fontsize=6.3, fontweight="bold", family=FONT, va="center", zorder=59)
    for ci, col in enumerate(cols_):
        yy = py_ - Hh + lh * 2.0
        cx0 = px_ + F.pts_to_px(5) + colw * ci
        for kind, color, text in col:
            if kind == "hdr":
                F.ax.plot(cx0 + F.pts_to_px(4), yy, marker="o", ms=5, mfc=color, mec="black", zorder=59)
                F.ax.text(cx0 + F.pts_to_px(10), yy, text, fontsize=5.9, fontweight="bold", family=FONT, va="center", zorder=59)
            else:
                F.ax.text(cx0 + F.pts_to_px(10), yy, text, fontsize=5.4, family="DejaVu Sans Mono", va="center", zorder=59)
            yy += lh
    F.north_arrow()
    handles = [(Line2D([0], [0], marker="*", color="w", mfc="#ffd400", mec="black", ms=12), "Fatal crash (slip 260722124BA)"),
               (Line2D([0], [0], color=PURPLE, lw=7, alpha=0.6), "Crash Analysis Study Limits")]
    for k in order:
        if any(p["priority"] == k for p in pts):
            handles.append((Line2D([0], [0], marker="o", color="w", mfc=styles[k]["color"], mec="black", ms=9), styles[k]["label"]))
    F.legend(handles, fx=0.985, fy=0.10)
    F.scale_bar(400, "Feet", fx=0.955, fy=0.035, divisions=2)
    F.title_strip(cfg, 3, "Crash Map", f"{fat['mp']:.3f}", _load_boundaries(study))
    F.save(out_png, out_pdf)


def build_figures(study: Study, screened: list[Screened], out_dir: str, tile_cache_dir: str, decisions=None) -> list[str]:
    cache = TileCache(tile_cache_dir)
    sid = study.study_id
    paths = []
    for name, fn in (("Figure1_AreaMap", lambda a, b: figure_area_map(study, cache, a, b)),
                     ("Figure2_LocationMap", lambda a, b: figure_location_map(study, cache, a, b)),
                     ("Figure3_CrashMap", lambda a, b: figure_crash_map(study, screened, cache, a, b, decisions=decisions))):
        png = os.path.join(out_dir, f"{sid}_{name}.png"); pdf = os.path.join(out_dir, f"{sid}_{name}.pdf")
        fn(png, pdf); paths += [png, pdf]
    return paths
