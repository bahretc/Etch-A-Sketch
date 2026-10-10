"""Report figures in the fatal-crash-analysis layout used in the Traffic Safety Unit study folders.

Figure 1  Area Map      white line map from NCDOT road centerlines (SR numbers, route shields), water, municipal and
                        county boundaries, study limits band, crash callout
Figure 2  Location Map  aerial close-up of the crash with the route shields and the crash callout
Figure 3  Crash Map     aerial with the initial-study crashes and the fiche review candidates (numbered)
AADT Map                stand-alone AADT station map in the Traffic Engineering "AADT Map" layout

The frame, title strip, legend, scale bar and north arrow follow the 2026 slip-number series examples
(<slip>_Area Map.pdf, <slip>_Location Map.pdf).
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
from matplotlib.patches import Circle, Patch, Polygon, Rectangle, RegularPolygon, FancyBboxPatch

from .geo import FT_PER_MILE, TILE_SOURCES, TileCache, lonlat_to_pixel, meters_per_pixel, pixel_to_lonlat, stitch
from .maps import DECISION_STYLE, PRIORITY_STYLE, crash_points
from .screen import Screened, Study

RED = "#a4161a"          # crash circle / callout border
PINK = "#fbe3e6"         # callout fill
PURPLE = "#d4b5ea"       # study limits band
BLUE = "#1f5fbf"         # county fill in the strip thumbnail
FONT = "Carlito"         # metric twin of Calibri; the examples use Segoe UI
DATA_DIR = os.path.join(os.path.dirname(__file__), "data")

ROAD_STYLE = {           # NCDOT RoadNC centerline classes
    "primary": dict(color="#555555", lw=1.7),
    "secondary": dict(color="#7d7d7d", lw=1.1),
    "other_system": dict(color="#9a9a9a", lw=0.8),
    "non_system": dict(color="#b7b7b7", lw=0.55),
}


def _fit_bbox(bbox, z, aspect, west_bias=0.5, south_bias=0.5):
    """Expand bbox (min_lon, min_lat, max_lon, max_lat) so its Web Mercator pixel extent has the given aspect."""
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


def _bbox_from_center(lat, lon, width_ft, height_ft):
    dlat = height_ft / 2 / 364567.2
    dlon = width_ft / 2 / (364567.2 * math.cos(math.radians(lat)))
    return (lon - dlon, lat - dlat, lon + dlon, lat + dlat)


def _rings(geom):
    if geom["type"] == "Polygon":
        return [geom["coordinates"][0]]
    if geom["type"] == "MultiPolygon":
        return [p[0] for p in geom["coordinates"]]
    return []


def _lines(geom):
    if geom["type"] == "LineString":
        return [geom["coordinates"]]
    if geom["type"] == "MultiLineString":
        return list(geom["coordinates"])
    return []


class Figure:
    """A map figure in the report frame: map panel with border, legend, scale bar, north arrow, title strip."""

    def __init__(self, cache: TileCache, source: str | None, bbox, z: int, dpi: int = 200,
                 west_bias: float = 0.5, south_bias: float = 0.5, strip: bool = True, title_gap: float = 0.0, layout: str = "vhb"):
        self.cache, self.source, self.z = cache, source, z
        self.layout = layout
        self.fig = plt.figure(figsize=(11, 8.5), dpi=dpi)
        self.fig.patch.set_facecolor("white")
        if layout == "vhb":
            # map panel over a white information block (WO / PH / Division, Study Area, Lat / Long, logo)
            self.L, self.R, self.T, self.B = 0.018, 0.982, 0.985 - title_gap, 0.018
            self.strip_h = 0.160 if strip else 0.0
        else:
            self.L, self.R, self.T, self.B = 0.022, 0.978, 0.972 - title_gap, 0.028
            self.strip_h = 0.100 if strip else 0.0
        self.ax = self.fig.add_axes([self.L, self.B + self.strip_h, self.R - self.L, self.T - self.B - self.strip_h])
        aspect = ((self.R - self.L) * 11.0) / ((self.T - self.B - self.strip_h) * 8.5)
        bbox = _fit_bbox(bbox, z, aspect, west_bias, south_bias)
        self.bbox = bbox
        x0, y1 = lonlat_to_pixel(bbox[0], bbox[1], z)
        x1, y0 = lonlat_to_pixel(bbox[2], bbox[3], z)
        if source:
            img, (px0, py0) = stitch(cache, source, bbox, z)
            w, h = img.size
            self.ax.imshow(img, extent=(px0, px0 + w, py0 + h, py0), interpolation="bilinear", zorder=0)
        self.ax.set_facecolor("white")
        self.ax.set_xlim(x0, x1); self.ax.set_ylim(y1, y0)
        self.ax.set_xticks([]); self.ax.set_yticks([])
        for sp in self.ax.spines.values():
            sp.set_edgecolor("black"); sp.set_linewidth(1.3); sp.set_zorder(70)
        self.xlim, self.ylim = (x0, x1), (y0, y1)
        self.center_lat = (bbox[1] + bbox[3]) / 2
        self.ft_per_px = meters_per_pixel(self.center_lat, z) * 3.28084
        self.fig.canvas.draw()
        bb = self.ax.get_window_extent()
        self.pt_per_px = (bb.width / (x1 - x0)) * 72.0 / dpi   # display points per world pixel
        self._circle_pt = 9

    # ----------------------------------------------------------- coordinates
    def px(self, lat, lon):
        return lonlat_to_pixel(lon, lat, self.z)

    def frac(self, fx, fy):
        """map-axes fraction -> world pixel coordinates"""
        return self.xlim[0] + (self.xlim[1] - self.xlim[0]) * fx, self.ylim[1] - (self.ylim[1] - self.ylim[0]) * fy

    def pts_to_px(self, pts):
        return pts / self.pt_per_px

    def inside(self, lat, lon, margin_frac=0.0):
        lon0, lat0, lon1, lat1 = self.bbox
        mx = (lon1 - lon0) * margin_frac; my = (lat1 - lat0) * margin_frac
        return lon0 + mx <= lon <= lon1 - mx and lat0 + my <= lat <= lat1 - my

    # ----------------------------------------------------------- drawing helpers
    def polyline(self, latlons, **kw):
        xs, ys = zip(*[self.px(a, b) for a, b in latlons])
        return self.ax.plot(xs, ys, **kw)

    def fill_geojson(self, geom, **kw):
        for ring in _rings(geom):
            pts = [self.px(lat, lon) for lon, lat in ring]
            self.ax.add_patch(Polygon(pts, closed=True, **kw))

    def polygon_from_geojson(self, geom, **kw):
        for ring in _rings(geom):
            xs, ys = zip(*[self.px(lat, lon) for lon, lat in ring])
            self.ax.plot(xs, ys, **kw)

    def lines_from_geojson(self, geom, **kw):
        for line in _lines(geom):
            xs, ys = zip(*[self.px(lat, lon) for lon, lat in line])
            self.ax.plot(xs, ys, **kw)

    def label(self, lat, lon, text, dx=0, dy=0, halo="white", color="black", size=7.5, **kw):
        x, y = self.px(lat, lon)
        kw.setdefault("ha", "center"); kw.setdefault("va", "center"); kw.setdefault("zorder", 40); kw.setdefault("clip_on", True)
        kw.setdefault("family", FONT)
        return self.ax.text(x + dx, y + dy, text, fontsize=size, color=color,
                            path_effects=[pe.withStroke(linewidth=2.6, foreground=halo)] if halo else None, **kw)

    def crash_circle(self, lat, lon, radius_pt=10, color=RED, lw=2.4):
        x, y = self.px(lat, lon)
        r = self.pts_to_px(radius_pt)
        self._circle_pt = radius_pt
        self.ax.add_patch(Circle((x, y), r, fill=False, ec=color, lw=lw, zorder=35))
        return x, y, r

    def callout(self, lat, lon, lines, box_frac, title="Crash Location:", size=9.0):
        """Pink box with a red border at box_frac (axes fraction of its center) and a leader to the circle edge."""
        x, y = self.px(lat, lon)
        bx, by = self.frac(*box_frac)
        txt = title + "\n" + "\n".join(lines)
        t = self.ax.text(bx, by, txt, fontsize=size, family=FONT, ha="center", va="center", zorder=46, linespacing=1.35,
                         bbox=dict(boxstyle="square,pad=0.55", fc=PINK, ec=RED, lw=1.5))
        self.fig.canvas.draw()
        bbox = t.get_window_extent().transformed(self.ax.transData.inverted())
        ty = bbox.y1 - (bbox.y1 - bbox.y0) * 0.5 / (len(lines) + 1)
        t.set_text("\n" + "\n".join(lines))
        tt = self.ax.text(bx, ty, title, fontsize=size, family=FONT, fontweight="bold", ha="center", va="center", zorder=47)
        self.fig.canvas.draw()
        tb = tt.get_window_extent().transformed(self.ax.transData.inverted())
        uy = tb.y1 + (tb.y1 - tb.y0) * 0.10          # pixel y grows downward: y1 is the bottom edge
        self.ax.plot([tb.x0, tb.x1], [uy, uy], color="black", lw=0.8, zorder=47)
        ex = min(max(x, bbox.x0), bbox.x1); ey = min(max(y, bbox.y0), bbox.y1)
        r = self.pts_to_px(self._circle_pt)
        d = math.hypot(x - ex, y - ey) or 1.0
        self.ax.plot([ex, x - (x - ex) / d * r], [ey, y - (y - ey) / d * r], color=RED, lw=1.5, zorder=45)

    def north_arrow(self, fx=0.985, fy=0.985):
        """Boxed north arrow: 'N' over a black arrow, top-right."""
        x1, y0 = self.frac(fx, fy)
        w, h = self.pts_to_px(22), self.pts_to_px(44)
        self.ax.add_patch(Rectangle((x1 - w, y0), w, h, fc="white", ec="#333333", lw=0.8, zorder=50))
        cx = x1 - w / 2
        self.ax.text(cx, y0 + h * 0.20, "N", ha="center", va="center", fontsize=7.5, family=FONT, zorder=51)
        a0, a1 = y0 + h * 0.36, y0 + h * 0.92
        aw = w * 0.30
        tri = Polygon([(cx, a0), (cx - aw, a1), (cx, a1 - h * 0.14), (cx + aw, a1)], closed=True, fc="black", ec="black", zorder=51)
        self.ax.add_patch(tri)

    def scale_bar(self, total_ft, unit, fx=0.985, fy=0.012, divisions=4, labels=None, anchor="right"):
        """Boxed bar, alternating black/white segments, labels above, unit at the right; anchored at fx (right or left edge)."""
        w = total_ft / self.ft_per_px
        pad = self.pts_to_px(7)
        unit_w = self.pts_to_px(26)
        x1, yb = self.frac(fx, fy)
        bx0 = x1 - w - 2 * pad - unit_w if anchor == "right" else x1
        bh = self.pts_to_px(28)
        self.ax.add_patch(Rectangle((bx0, yb - bh), w + 2 * pad + unit_w, bh, fc="white", ec="#333333", lw=0.8, zorder=48))
        x0 = bx0 + pad
        y = yb - self.pts_to_px(8)
        h = self.pts_to_px(5)
        for i in range(divisions):
            self.ax.add_patch(Rectangle((x0 + w * i / divisions, y - h), w / divisions, h,
                                        fc="black" if i % 2 == 0 else "white", ec="black", lw=0.7, zorder=49))
        if labels is None:
            labels = {0: "0", divisions // 2: None, divisions: None}
            for k in (divisions // 2, divisions):
                v = total_ft * k / divisions
                labels[k] = f"{v / FT_PER_MILE:g}" if unit == "Miles" else f"{v:,.0f}"
        for k, lab in labels.items():
            self.ax.text(x0 + w * k / divisions, y - h - self.pts_to_px(2), lab, ha="center", va="bottom", fontsize=6.3, family=FONT, zorder=50)
        self.ax.text(x0 + w + self.pts_to_px(5), y - h / 2, unit, ha="left", va="center", fontsize=6.3, family=FONT, zorder=50)

    def legend(self, items, fx=0.985, fy=0.085, title="Legend", loc="lower right"):
        """items: list of (handle, label). Anchored at the axes fraction."""
        from matplotlib.font_manager import FontProperties
        lg = self.ax.legend(handles=[h for h, _ in items], labels=[l for _, l in items], title=title, loc=loc,
                            bbox_to_anchor=(fx, fy), framealpha=1.0, edgecolor="black", fancybox=False, borderpad=0.9,
                            labelspacing=0.9, handlelength=2.4, handletextpad=0.9, prop=FontProperties(family=FONT, size=9.2),
                            title_fontproperties=FontProperties(family=FONT, size=10.5, weight="bold"))
        lg.get_frame().set_linewidth(1.0)
        lg.set_zorder(60)
        return lg

    # ----------------------------------------------------------- VHB layout pieces
    def crash_ring(self, lat, lon, radius_pt=13, lw=4.2, color="#e8141c"):
        x, y = self.px(lat, lon)
        r = self.pts_to_px(radius_pt)
        self._circle_pt = radius_pt
        self.ax.add_patch(Circle((x, y), r, fill=False, ec=color, lw=lw, zorder=36))
        return x, y, r

    def vhb_callout(self, lat, lon, text, box_frac, size=9.5):
        """White box, black border, black arrow to the ring edge."""
        x, y = self.px(lat, lon)
        bx, by = self.frac(*box_frac)
        t = self.ax.text(bx, by, text, fontsize=size, family=FONT, ha="center", va="center", zorder=46, linespacing=1.3,
                         bbox=dict(boxstyle="square,pad=0.5", fc="white", ec="black", lw=1.0))
        self.fig.canvas.draw()
        e = t.get_window_extent().transformed(self.ax.transData.inverted())
        ex = min(max(x, e.x0), e.x1); ey = min(max(y, e.y0), e.y1)
        r = self.pts_to_px(self._circle_pt + 2)
        d = math.hypot(x - ex, y - ey) or 1.0
        self.ax.annotate("", xy=(x - (x - ex) / d * r, y - (y - ey) / d * r), xytext=(ex, ey),
                         arrowprops=dict(arrowstyle="-|>", color="black", lw=1.2, mutation_scale=11), zorder=45)

    def inset_county(self, county, w_frac=0.205, h_frac=0.105):
        """North Carolina county map in a white box at the top-left of the map panel; the study county in red."""
        p = os.path.join(DATA_DIR, "nc_counties.json")
        if not os.path.exists(p):
            return
        with open(p) as fh:
            counties = json.load(fh)["features"]
        pos = self.ax.get_position()
        iw, ih = (pos.x1 - pos.x0) * w_frac, (pos.y1 - pos.y0) * h_frac
        iax = self.fig.add_axes([pos.x0 + 0.004, pos.y1 - ih - 0.004, iw, ih])
        iax.set_xticks([]); iax.set_yticks([])
        for sp in iax.spines.values():
            sp.set_linewidth(0.9)
        iax.set_facecolor("white")
        target = county.strip().upper()
        for ft in counties:
            is_t = (ft["properties"].get("CountyName") or "").strip().upper() == target
            for r in _rings(ft["geometry"]):
                xs = [q[0] * math.cos(math.radians(35.5)) for q in r]; ys = [q[1] for q in r]
                iax.add_patch(Polygon(list(zip(xs, ys)), closed=True, fc="#e02020" if is_t else "white", ec="#555555", lw=0.35, zorder=3 if is_t else 2))
        allpts = [q for ft in counties for r in _rings(ft["geometry"]) for q in r]
        xs = [q[0] * math.cos(math.radians(35.5)) for q in allpts]; ys = [q[1] for q in allpts]
        padx = (max(xs) - min(xs)) * 0.03; pady = (max(ys) - min(ys)) * 0.06
        iax.set_xlim(min(xs) - padx, max(xs) + padx); iax.set_ylim(min(ys) - pady, max(ys) + pady)
        iax.set_aspect("auto")
        iax.set_zorder(80)

    def scale_bar_vhb(self, total_ft, unit, ticks, labels, fx=0.012, fy=0.012):
        """Bottom-left white box: round north icon, then an alternating bar with labels above the ticks."""
        w = total_ft / self.ft_per_px
        x0b, yb = self.frac(fx, fy)
        pad = self.pts_to_px(8)
        icon = self.pts_to_px(26)
        bh = self.pts_to_px(34)
        Ww = icon + pad * 3 + w + self.pts_to_px(34)
        self.ax.add_patch(Rectangle((x0b, yb - bh), Ww, bh, fc="white", ec="black", lw=0.8, zorder=48))
        cx, cy = x0b + pad + icon / 2, yb - bh / 2
        rr = icon / 2
        self.ax.add_patch(Circle((cx, cy), rr, fc="black", ec="black", zorder=49))
        a = rr * 0.72
        self.ax.add_patch(Polygon([(cx, cy - a), (cx - a * 0.55, cy + a * 0.55), (cx, cy + a * 0.2), (cx + a * 0.55, cy + a * 0.55)], closed=True, fc="white", ec="white", zorder=50))
        self.ax.text(cx, cy + a * 0.32, "N", ha="center", va="center", fontsize=5.5, fontweight="bold", family=FONT, color="black", zorder=51)
        x0 = x0b + pad * 2 + icon
        y = yb - self.pts_to_px(9)
        h = self.pts_to_px(5)
        for i in range(len(ticks) - 1):
            self.ax.add_patch(Rectangle((x0 + w * ticks[i], y - h), w * (ticks[i + 1] - ticks[i]), h,
                                        fc="black" if i % 2 == 0 else "white", ec="black", lw=0.7, zorder=49))
        for t, lab in zip(ticks, labels):
            self.ax.text(x0 + w * t, y - h - self.pts_to_px(2.5), lab, ha="center", va="bottom", fontsize=7.5, family=FONT, zorder=50)
        self.ax.text(x0 + w + self.pts_to_px(8), y - h / 2, unit, ha="left", va="center", fontsize=7.5, family=FONT, zorder=50)

    def vhb_block(self, cfg, extra_source=""):
        """Information block under the map: WO / PH / Division, Study Area, Lat / Long, VHB logo, data source."""
        f = cfg["figures"]
        fig = self.fig
        L, R, B = self.L, self.R, self.B
        top = B + self.strip_h
        y1, y2, y3 = top - 0.030, top - 0.068, top - 0.106
        # left column
        lines = f.get("info_lines", [["Slip Number", f.get("slip_no", "")], ["NCDOT Division", str(cfg.get("division", ""))]])
        ys = [y1, y2, y3]
        for (lab, val), yy in zip(lines, ys):
            t = fig.text(L + 0.012, yy, lab + " ", fontsize=11.5, fontweight="bold", family=FONT, va="center", ha="left")
            fig.canvas.draw()
            e = t.get_window_extent().transformed(fig.transFigure.inverted())
            fig.text(e.x1, yy, val, fontsize=11.5, family=FONT, va="center", ha="left")
        # center
        cx = (L + R) / 2 + 0.03
        fig.text(cx, y1, "Study Area", fontsize=11.5, fontweight="bold", family=FONT, va="center", ha="center")
        sa = f.get("study_area_lines", f.get("description_lines", []))
        for i, ln in enumerate(sa[:2]):
            fig.text(cx, [y2, y3][i], ln, fontsize=11, family=FONT, va="center", ha="center")
        # right column
        fat = cfg["fatal"]
        rx = R - 0.105
        for lab, val, yy in (("Lat", f"{fat['lat']}", y1), ("Long", f"{fat['lon']}", y2)):
            fig.text(rx, yy, lab, fontsize=11.5, fontweight="bold", family=FONT, va="center", ha="right")
            fig.text(rx + 0.012, yy, val, fontsize=11.5, family=FONT, va="center", ha="left")
        logo = os.path.join(DATA_DIR, "vhb_logo.png")
        if os.path.exists(logo):
            img = plt.imread(logo)
            lw_in, lh_in = 1.05, 1.05 * img.shape[0] / img.shape[1]
            lax = fig.add_axes([R - lw_in / 11.0, B, lw_in / 11.0, lh_in / 8.5]); lax.axis("off")
            lax.imshow(img, interpolation="lanczos")
        src = "Data Source: NCDOT, NC OneMap" + (", " + extra_source if extra_source else "") + ", VHB"
        fig.text(L + 0.012, B + 0.006, src, fontsize=7, style="italic", family=FONT, color="#555555", va="bottom", ha="left")

    # ----------------------------------------------------------- title strip
    def title_strip(self, cfg, fig_no, fig_title, mp_text, extra_note=""):
        f = cfg["figures"]
        L, R, B = self.L, self.R, self.B
        H = self.strip_h - 0.006
        ax = self.fig.add_axes([L, B, R - L, H]); ax.set_xlim(0, 1); ax.set_ylim(0, 1); ax.axis("off")
        ax.add_patch(Rectangle((0, 0), 1, 1, fill=False, ec="black", lw=1.3, transform=ax.transAxes, zorder=5))
        cols = [0.0, 0.085, 0.215, 0.37, 0.68, 0.78, 0.875, 1.0]
        for c in cols[1:-1]:
            ax.plot([c, c], [0, 1], color="black", lw=1.0, zorder=5)
        strip_w_in, strip_h_in = 11.0 * (R - L), 8.5 * H
        # cell 1: NCDOT seal
        seal = os.path.join(DATA_DIR, "ncdot_seal.png")
        if os.path.exists(seal):
            img = plt.imread(seal)
            cell_w_in = strip_w_in * (cols[1] - cols[0])
            side_in = min(cell_w_in, strip_h_in) * 0.84
            cx = (cols[0] + cols[1]) / 2
            ax.imshow(img, extent=(cx - side_in / strip_w_in / 2, cx + side_in / strip_w_in / 2, 0.5 - side_in / strip_h_in / 2, 0.5 + side_in / strip_h_in / 2),
                      aspect="auto", zorder=3, interpolation="lanczos")
        # cell 2: prepared by
        lines = f.get("prepared_by_lines", ["Traffic Safety Unit", "Mobility and Safety Division"])
        cx = (cols[1] + cols[2]) / 2
        ax.text(cx, 0.60, lines[0], ha="center", va="center", fontsize=11.5, fontweight="bold", family=FONT, color="#1b3a6b")
        if len(lines) > 1:
            ax.text(cx, 0.32, "\n".join(lines[1:]), ha="center", va="center", fontsize=7.2, family=FONT, color="#333333", linespacing=1.3)
        # cell 3: county thumbnail
        self._county_thumb(ax, cfg["county"], (cols[2], cols[3]), strip_w_in, strip_h_in)
        # cell 4: slip + description
        cx = (cols[3] + cols[4]) / 2
        ax.text(cx, 0.82, f"Slip No. {f['slip_no']}", ha="center", va="center", fontsize=10, fontweight="bold", family=FONT)
        ax.text(cx, 0.40, "\n".join(f["description_lines"]), ha="center", va="center", fontsize=8.6, family=FONT, linespacing=1.4)
        # cell 5: lat / long
        fat = cfg["fatal"]
        for (c0, c1), top, bottom in (((cols[4], cols[5]), ("Latitude:", f"{fat['lat']}"), ("Longitude:", f"{fat['lon']}")),
                                      ((cols[5], cols[6]), ("Milepost:", mp_text), ("Division:", f"{cfg['division']}"))):
            ax.plot([c0, c1], [0.5, 0.5], color="black", lw=0.9, zorder=5)
            cx = (c0 + c1) / 2
            ax.text(cx, 0.82, top[0], ha="center", va="center", fontsize=9, fontweight="bold", family=FONT)
            ax.text(cx, 0.63, top[1], ha="center", va="center", fontsize=8.3, family=FONT)
            ax.text(cx, 0.35, bottom[0], ha="center", va="center", fontsize=9, fontweight="bold", family=FONT)
            ax.text(cx, 0.15, bottom[1], ha="center", va="center", fontsize=8.3, family=FONT)
        # cell 7: figure no / title / date
        cx = (cols[6] + cols[7]) / 2
        ax.text(cx, 0.76, f"Figure No. {fig_no}", ha="center", va="center", fontsize=10.5, fontweight="bold", family=FONT)
        ax.text(cx, 0.47, fig_title, ha="center", va="center", fontsize=9.2, family=FONT)
        ax.text(cx, 0.20, f.get("date_label", ""), ha="center", va="center", fontsize=7.6, family=FONT)
        # attribution line under the strip
        note = "Sources: " + (TILE_SOURCES[self.source]["attribution"] + "; " if self.source else "") + \
               "NCDOT RoadNC centerlines, municipal and county boundaries; NC OneMap hydrography; crash data from NCDOT TEAAS and DMV-349 reports."
        if extra_note:
            note += " " + extra_note
        for i, ln in enumerate(textwrap.wrap(note, 230)[:2]):
            self.fig.text(L, B - 0.010 - 0.010 * i, ln, fontsize=5.2, color="#555555", va="center", family=FONT)

    def _county_thumb(self, ax, county, xr, strip_w_in, strip_h_in):
        """North Carolina with all county outlines, the study county filled blue, and a keyed label."""
        p = os.path.join(DATA_DIR, "nc_counties.json")
        if not os.path.exists(p):
            return
        with open(p) as fh:
            counties = json.load(fh)["features"]
        allpts = [pt for ft in counties for r in _rings(ft["geometry"]) for pt in r]
        lons = [q[0] for q in allpts]; lats = [q[1] for q in allpts]
        mnx, mxx, mny, mxy = min(lons), max(lons), min(lats), max(lats)
        cell_w_in = strip_w_in * (xr[1] - xr[0])
        W_in = cell_w_in * 0.88
        asp = (mxy - mny) / ((mxx - mnx) * math.cos(math.radians(35.5)))
        H_in = W_in * asp
        if H_in > strip_h_in * 0.58:
            H_in = strip_h_in * 0.58; W_in = H_in / asp
        cx = (xr[0] + xr[1]) / 2
        cy = 0.60
        W = W_in / strip_w_in; Hh = H_in / strip_h_in
        def tx(lon, lat):
            return cx - W / 2 + (lon - mnx) / (mxx - mnx) * W, cy - Hh / 2 + (lat - mny) / (mxy - mny) * Hh
        target = county.strip().upper()
        for ft in counties:
            is_t = (ft["properties"].get("CountyName") or "").strip().upper() == target
            for r in _rings(ft["geometry"]):
                ax.add_patch(Polygon([tx(*q) for q in r], closed=True, fc=BLUE if is_t else "#f4f4f4", ec="#6f6f6f", lw=0.35, zorder=4 if is_t else 3))
        kx = cx - W / 2
        ax.add_patch(Rectangle((kx, 0.11), 0.016, 0.11, fc=BLUE, ec="black", lw=0.4, zorder=4))
        ax.text(kx + 0.022, 0.165, f"{county.strip().title()} County", ha="left", va="center", fontsize=7.6, family=FONT)

    def save(self, path_png, path_pdf=None):
        self.fig.savefig(path_png, dpi=self.fig.dpi, facecolor="white")
        if path_pdf:
            self.fig.savefig(path_pdf, facecolor="white")
        plt.close(self.fig)


# ---------------------------------------------------------------------- shared overlays

def _limits_band(F: Figure, study: Study, lw_pt=9, alpha=0.95, zorder=20, color=PURPLE):
    pl = study.centerline
    sec = pl.slice(study.begin_mp * FT_PER_MILE, study.end_mp * FT_PER_MILE)
    F.polyline(sec, color=color, lw=lw_pt, alpha=alpha, zorder=zorder, solid_capstyle="round")


def _shield(F: Figure, lat, lon, number, kind="NC", bus=False, size_pt=13):
    """NC diamond or US shield with the route number; BUS tab above when bus."""
    x, y = F.px(lat, lon)
    r = F.pts_to_px(size_pt)
    if kind == "US":
        w, h = r * 1.5, r * 1.6
        pts = [(x - w / 2, y - h / 2), (x + w / 2, y - h / 2), (x + w / 2, y + h * 0.05), (x + w * 0.35, y + h / 2),
               (x, y + h * 0.42), (x - w * 0.35, y + h / 2), (x - w / 2, y + h * 0.05)]
        F.ax.add_patch(Polygon(pts, closed=True, fc="white", ec="black", lw=1.1, zorder=42))
    else:
        F.ax.add_patch(RegularPolygon((x, y), 4, radius=r, orientation=0, fc="white", ec="black", lw=1.1, zorder=42))
    F.ax.text(x, y, number, ha="center", va="center", fontsize=7, fontweight="bold", family=FONT, zorder=43)
    if bus:
        F.ax.text(x, y - r - F.pts_to_px(2.5), "BUS", ha="center", va="bottom", fontsize=5.3, fontweight="bold", family=FONT, zorder=43,
                  bbox=dict(boxstyle="square,pad=0.15", fc="white", ec="black", lw=0.6))


def _shield_from_cfg(F: Figure, rl):
    kind = "US" if rl.get("text", "").upper().startswith("US") else "NC"
    _shield(F, rl["lat"], rl["lon"], rl["shield"], kind=kind, bus=rl.get("bus", False))


def _road_labels(F: Figure, cfg, shields=True, names=True, bus=True, key="road_labels"):
    for rl in cfg["figures"].get(key, []):
        if rl.get("shield"):
            if shields and (bus or not rl.get("bus")):
                _shield_from_cfg(F, rl)
        elif names:
            F.label(rl["lat"], rl["lon"], rl["text"], rotation=rl.get("rot", 0), size=7, color="black", halo="white")


def _load_basemap(study: Study):
    p = study.cfg.get("inputs", {}).get("basemap")
    if not p:
        return None
    with open(os.path.join(study.root, p)) as f:
        return json.load(f)


def _draw_vector_basemap(F: Figure, bm, road_scale=1.0, water=True):
    """White line map: water, then roads by NCDOT class."""
    if water:
        for ft in bm.get("waterbodies", {}).get("features", []):
            F.fill_geojson(ft["geometry"], fc="#cfe1f3", ec="#93b7dc", lw=0.6, zorder=2)
        for ft in bm.get("streams", {}).get("features", []):
            F.lines_from_geojson(ft["geometry"], color="#93b7dc", lw=0.5, zorder=3)
    for ft in bm["roads"]["features"]:
        st = ROAD_STYLE.get(ft["properties"].get("layer", "non_system"), ROAD_STYLE["non_system"])
        F.lines_from_geojson(ft["geometry"], color=st["color"], lw=st["lw"] * road_scale, zorder=8 if ft["properties"].get("layer") == "non_system" else 9,
                             solid_capstyle="round")


def _inview_midpoint(F: Figure, geom, margin=0.04):
    """Longest in-view run of a line geometry -> (lat, lon, bearing_deg) at its middle, or None."""
    best = None
    for line in _lines(geom):
        pts = [(lat, lon) for lon, lat in line if F.inside(lat, lon, margin)]
        if len(pts) < 2:
            continue
        cum = [0.0]
        for a, b in zip(pts, pts[1:]):
            cum.append(cum[-1] + math.hypot((b[0] - a[0]) * 364567.2, (b[1] - a[1]) * 364567.2 * math.cos(math.radians(a[0]))))
        if best is None or cum[-1] > best[0]:
            half = cum[-1] / 2
            for i in range(1, len(cum)):
                if cum[i] >= half:
                    a, b = pts[i - 1], pts[i]
                    t = (half - cum[i - 1]) / (cum[i] - cum[i - 1] or 1)
                    lat = a[0] + (b[0] - a[0]) * t; lon = a[1] + (b[1] - a[1]) * t
                    brg = math.degrees(math.atan2((b[1] - a[1]) * math.cos(math.radians(lat)), b[0] - a[0]))
                    best = (cum[-1], lat, lon, brg)
                    break
    return None if best is None else best[1:]


def _sr_number_labels(F: Figure, bm, cfg, size=7.6, min_sep_pt=26):
    """One label per secondary route (its SR number) at the middle of its longest in-view piece; config can pin or skip."""
    pins = cfg["figures"].get("sr_labels", {})
    skip = set(str(s) for s in cfg["figures"].get("sr_labels_skip", []))
    by_route = {}
    for ft in bm["roads"]["features"]:
        pr = ft["properties"]
        if pr.get("layer") != "secondary" or not pr.get("RouteNumber"):
            continue
        by_route.setdefault(str(pr["RouteNumber"]), []).append(ft["geometry"])
    placed = []
    for num in sorted(by_route):
        if num in skip:
            continue
        if num in pins:
            lat, lon = pins[num]["lat"], pins[num]["lon"]
        else:
            cands = [m for m in (_inview_midpoint(F, g) for g in by_route[num]) if m]
            if not cands:
                continue
            # the piece with the longest in-view run is first in cands order of geometry; pick the one farthest from other labels
            lat, lon, brg = max(cands, key=lambda m: min([math.hypot(*(F.px(m[0], m[1])[k] - p[k] for k in (0, 1))) for p in placed] or [1e9]))
        x, y = F.px(lat, lon)
        if any(math.hypot(x - qx, y - qy) < F.pts_to_px(min_sep_pt) for qx, qy in placed):
            continue
        placed.append((x, y))
        F.ax.text(x, y - F.pts_to_px(5), num, fontsize=size, family=FONT, color="#4a4a4a", ha="center", va="bottom", zorder=40, clip_on=True,
                  path_effects=[pe.withStroke(linewidth=2.6, foreground="white")])


def _primary_shields(F: Figure, bm, cfg):
    """Route shields for the primary routes in view: config positions when given, else auto along the longest in-view piece."""
    pins = cfg["figures"].get("area_shields")
    if pins:
        for rl in pins:
            _shield_from_cfg(F, rl)
        return
    groups = {}
    for ft in bm["roads"]["features"]:
        pr = ft["properties"]
        if pr.get("layer") != "primary":
            continue
        groups.setdefault(pr.get("RouteName", ""), []).append(ft["geometry"])
    for name, geoms in groups.items():
        kind = "US" if name.startswith("US") else "NC"
        num = "".join(ch for ch in name.split("-")[-1] if ch.isdigit())
        bus = "BUS" in name
        cands = [m for m in (_inview_midpoint(F, g, 0.06) for g in geoms) if m]
        if cands:
            lat, lon, _ = cands[0]
            _shield(F, lat, lon, num, kind=kind, bus=bus)


def _municipalities(F: Figure, bm, cfg):
    labels = cfg["figures"].get("municipality_labels", {})
    for ft in bm.get("municipalities", {}).get("features", []):
        pr = ft["properties"]
        name = pr.get("MunicipalBoundaryName", "")
        F.fill_geojson(ft["geometry"], fc="#e9e9e9", ec="none", alpha=0.8, zorder=4)
        F.polygon_from_geojson(ft["geometry"], color="#666666", lw=1.0, ls=(0, (4, 1.6, 1, 1.6)), zorder=12)
        lab = labels.get(name)
        if lab is None or lab.get("hide"):
            continue
        pop = pr.get("CensusPopulation")
        txt = name.upper() + (f"\nPop. {int(pop):,}" if pop else "")
        F.ax.text(*F.px(lab["lat"], lab["lon"]), txt, fontsize=lab.get("size", 10), fontweight="bold", family=FONT, color="#555555",
                  ha=lab.get("ha", "center"), va=lab.get("va", "center"), zorder=41, linespacing=1.15, clip_on=True,
                  path_effects=[pe.withStroke(linewidth=2.6, foreground="white")])


def _county_line(F: Figure, bm):
    g = bm.get("county", {}).get("features", [])
    for ft in g:
        F.polygon_from_geojson(ft["geometry"], color="#3a3a3a", lw=2.4, zorder=13)
        F.polygon_from_geojson(ft["geometry"], color="#f7ea00", lw=2.4, ls=(0, (5, 4)), zorder=14)


# ---------------------------------------------------------------------- figures

def _vhb_roads(F: Figure, bm, water=True):
    """Gray canvas road map: local roads light, state roads dark, primary routes heavy black."""
    F.ax.set_facecolor("#e4e4e4")
    F.ax.add_patch(Rectangle((F.xlim[0], F.ylim[0]), F.xlim[1] - F.xlim[0], F.ylim[1] - F.ylim[0], fc="#e4e4e4", ec="none", zorder=0))
    if water:
        for ft in bm.get("waterbodies", {}).get("features", []):
            F.fill_geojson(ft["geometry"], fc="#cdd9e5", ec="#b5c6d6", lw=0.5, zorder=2)
    style = {"primary": dict(color="#1a1a1a", lw=2.8), "secondary": dict(color="#3f3f3f", lw=1.4),
             "other_system": dict(color="#8a8a8a", lw=0.9), "non_system": dict(color="#ffffff", lw=0.9)}
    for ft in bm["roads"]["features"]:
        st = style.get(ft["properties"].get("layer", "non_system"), style["non_system"])
        F.lines_from_geojson(ft["geometry"], color=st["color"], lw=st["lw"], zorder=8 if ft["properties"].get("layer") == "non_system" else 9,
                             solid_capstyle="round")


def _city_labels(F: Figure, bm, cfg):
    labels = cfg["figures"].get("municipality_labels", {})
    for ft in bm.get("municipalities", {}).get("features", []):
        name = ft["properties"].get("MunicipalBoundaryName", "")
        lab = labels.get(name)
        if lab is None or lab.get("hide"):
            continue
        F.ax.text(*F.px(lab["lat"], lab["lon"]), name, fontsize=lab.get("size", 9.5), family=FONT, color="#2b2b2b",
                  ha=lab.get("ha", "center"), va=lab.get("va", "center"), zorder=41, clip_on=True,
                  path_effects=[pe.withStroke(linewidth=2.2, foreground="#e4e4e4")])


def figure_area_map(study: Study, cache: TileCache, out_png, out_pdf):
    cfg = study.cfg
    bbox = tuple(cfg["figures"]["area_bbox"])
    bm = _load_basemap(study)
    F = Figure(cache, None if bm else "streets", bbox, 14)
    fat = cfg["fatal"]
    if bm:
        _vhb_roads(F, bm)
        _city_labels(F, bm, cfg)
        _primary_shields(F, bm, cfg)
    F.crash_ring(fat["lat"], fat["lon"], radius_pt=14, lw=4.5)
    F.inset_county(cfg["county"])
    F.scale_bar_vhb(FT_PER_MILE * 2.0, "Miles", [0, 0.25, 0.5, 1.0], ["0", "0.5", "1", "2"])
    F.vhb_block(cfg)
    F.save(out_png, out_pdf)


def figure_location_map(study: Study, cache: TileCache, out_png, out_pdf, z=19):
    """Aerial of the whole study section with the crash ring and callout."""
    cfg = study.cfg
    fat = cfg["fatal"]
    from .maps import _section_bbox
    bbox = _section_bbox(study, pad_ft=cfg["figures"].get("location_pad_ft", 300), mp_pad=0.03)
    F = Figure(cache, "imagery", bbox, z)
    pl = study.centerline
    if cfg["figures"].get("location_limits", True):
        _limits_band(F, study, lw_pt=10, alpha=0.55)
        for mp, which in ((study.begin_mp, "Begin"), (study.end_mp, "End")):
            p = pl.point_at_mi(mp)
            brg = math.radians(pl.bearing_at(mp * FT_PER_MILE))
            nx, ny = math.cos(brg), math.sin(brg)
            x, y = F.px(*p)
            F.ax.text(x - nx * F.pts_to_px(12), y - ny * F.pts_to_px(12), f"{which} study section\nMP {mp:.3f}", fontsize=8, family=FONT, ha="right", va="center",
                      color="white", zorder=41, linespacing=1.25, path_effects=[pe.withStroke(linewidth=2.6, foreground="black")])
    for rl in cfg["figures"].get("location_shields", cfg["figures"].get("road_labels", [])):
        if rl.get("shield") and F.inside(rl["lat"], rl["lon"], 0.03):
            _shield_from_cfg(F, rl)
    F.crash_ring(fat["lat"], fat["lon"], radius_pt=13, lw=4.2)
    F.vhb_callout(fat["lat"], fat["lon"], cfg["figures"].get("vhb_callout", "Crash Location"), tuple(cfg["figures"].get("location_callout_frac", (0.25, 0.70))))
    F.inset_county(cfg["county"])
    F.scale_bar_vhb(500, "Feet", [0, 0.25, 0.5, 1.0], ["0", "", "250", "500"])
    F.vhb_block(cfg, extra_source="Esri World Imagery")
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
    _limits_band(F, study, lw_pt=9, alpha=0.7)
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
    for rl in cfg["figures"].get("location_shields", cfg["figures"].get("road_labels", [])):
        if rl.get("shield") and F.inside(rl["lat"], rl["lon"], 0.03):
            _shield_from_cfg(F, rl)
    pts = crash_points(study, screened, decisions)
    styles = DECISION_STYLE if decisions else dict(PRIORITY_STYLE)
    lon0, lat0, lon1, lat1 = F.bbox
    for p in pts:
        p["offmap"] = p["lat"] is None or not (lon0 <= p["lon"] <= lon1 and lat0 <= p["lat"] <= lat1)
    pts_on = [p for p in pts if not p["offmap"]]
    sep = F.pts_to_px(15)
    x0, x1 = F.xlim; y0, y1 = F.ylim
    margin = sep
    placed = []
    def free(ax_, ay_):
        if not (x0 + margin < ax_ < x1 - margin and y0 + margin < ay_ < y1 - margin):
            return False
        return all(math.hypot(ax_ - qx, ay_ - qy) >= sep for qx, qy in placed)
    for p in sorted(pts_on, key=lambda q: (q["priority"] != 0 and q["priority"] != "IS", q["mp_along"])):
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
                  color="black" if dark or p["fatal"] else "white", zorder=31)
    # key panel (lower left) listing the crashes
    lines = []
    order = [0, 1, 2, 3, 4, 5] if not decisions else ["IS", "ADD", "DEL", "NIS"]
    for k in order:
        grp = [p for p in pts if p["priority"] == k]
        if not grp:
            continue
        lines.append(("hdr", styles[k]["color"], styles[k]["label"]))
        for p in grp:
            if p.get("report_mp") is not None:
                mp = f"  MP {p['report_mp']:.3f}"
            else:
                mp = f"  MP {p['mp']:.3f}" if p.get("mp") is not None else ""
            tail = "  off map" if p.get("offmap") else ""
            lines.append(("row", None, f"{p['n']:>2}  {p['crash_id']}  {p['date']}  {p['type']:<5} {p['severity']}{mp}{tail}"))
    ncol = 2
    per = math.ceil(len(lines) / ncol)
    cols_ = [lines[i * per:(i + 1) * per] for i in range(ncol)]
    px_, py_ = F.frac(0.012, 0.012)
    lh = F.pts_to_px(8.2)
    Hh = lh * (per + 2.0)
    colw = F.pts_to_px(195)
    Ww = colw * ncol + F.pts_to_px(10)
    F.ax.add_patch(Rectangle((px_, py_ - Hh), Ww, Hh, fc="white", ec="black", lw=0.8, alpha=0.95, zorder=58))
    F.ax.text(px_ + F.pts_to_px(5), py_ - Hh + lh * 0.9, ("Crashes shown (numbers follow the Review IDs sheet; K fatal, B/C injury, O no injury" + ("; MP from the DMV-349 report)" if decisions else ")")),
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
    handles = [(Line2D([0], [0], marker="*", color="w", mfc="#ffd400", mec="black", ms=13), f"Fatal crash (slip {cfg['figures']['slip_no']})"),
               (Line2D([0], [0], color=PURPLE, lw=9, alpha=0.9, solid_capstyle="round"), "Crash Analysis Study Limits")]
    for k in order:
        if any(p["priority"] == k for p in pts):
            handles.append((Line2D([0], [0], marker="o", color="w", mfc=styles[k]["color"], mec="black", ms=10), styles[k]["label"]))
    F.legend(handles, fx=0.985, fy=0.085)
    F.inset_county(cfg["county"])
    F.scale_bar_vhb(500, "Feet", [0, 0.25, 0.5, 1.0], ["0", "", "250", "500"], fx=0.012, fy=0.60)
    F.vhb_block(cfg, extra_source="Esri World Imagery")
    F.save(out_png, out_pdf)


# ---------------------------------------------------------------------- AADT map (Traffic Engineering "AADT Map" layout)

AADT_BLUE = "#1f4fd6"
AADT_YELLOW = "#ffffc8"
AADT_CALLOUT = "#cfe3ff"


def _compass_rose(F: Figure, fx=0.985, fy=0.012, size_pt=46):
    """Boxed compass rose with N/E/S/W, bottom-right."""
    x1, yb = F.frac(fx, fy)
    s = F.pts_to_px(size_pt)
    bx0, by0 = x1 - s, yb - s
    F.ax.add_patch(FancyBboxPatch((bx0, by0), s, s, boxstyle="round,pad=0,rounding_size=%f" % F.pts_to_px(3), fc="white", ec="#333333", lw=0.8, zorder=50))
    cx, cy = bx0 + s / 2, by0 + s / 2
    R = s * 0.30; r = R * 0.38
    for k in range(8):
        a0 = math.radians(k * 45); a1 = math.radians(k * 45 + 22.5); a2 = math.radians(k * 45 - 22.5)
        rr = R if k % 2 == 0 else R * 0.62
        tri = [(cx + rr * math.sin(a0), cy - rr * math.cos(a0)), (cx + r * math.sin(a1), cy - r * math.cos(a1)), (cx, cy)]
        F.ax.add_patch(Polygon(tri, closed=True, fc="black" if k % 2 == 0 else "#777777", ec="none", zorder=51))
        tri2 = [(cx + rr * math.sin(a0), cy - rr * math.cos(a0)), (cx + r * math.sin(a2), cy - r * math.cos(a2)), (cx, cy)]
        F.ax.add_patch(Polygon(tri2, closed=True, fc="white", ec="#444444", lw=0.3, zorder=51))
    for lab, (dx, dy) in {"N": (0, -1), "E": (1, 0), "S": (0, 1), "W": (-1, 0)}.items():
        F.ax.text(cx + dx * s * 0.40, cy + dy * s * 0.40, lab, ha="center", va="center", fontsize=6.2, family="Liberation Sans", zorder=52)


def _aadt_station_box(F: Figure, stn, lab, county=""):
    """Blue station dot and a full-data box (the AADT viewer fields: LocationID, COUNTY, RTE_CLS, ROUTE, LOCATION, AADT_<year> ...)."""
    x, y = F.px(stn["lat"], stn["lon"])
    F.ax.plot(x, y, marker="o", ms=6, mfc=AADT_BLUE, mec="white", mew=0.8, zorder=44)
    route = stn.get("route", "")
    cls = "Secondary Routes" if route.startswith("SR") or route.startswith("4000") else "Primary Routes"
    loc = (stn.get("location") or "").upper()
    rows = [("LocationID", stn["id"]), ("COUNTY", county.upper()), ("RTE_CLS", cls), ("ROUTE", route), ("LOCATION", loc if len(loc) <= 34 else loc[:32] + "…")]
    years = sorted(stn["aadt"], key=int)
    rows += [(f"AADT_{yv}", f"{stn['aadt'][yv]:,}") for yv in years]
    lh = F.pts_to_px(6.2)
    kw = F.pts_to_px(46)
    bw = F.pts_to_px(lab.get("w", 150))
    bh = lh * (len(rows) + 0.8)
    bx, by = F.frac(lab["bx"], lab["by"])          # box center in axes fractions
    X0, Y0 = bx - bw / 2, by - bh / 2
    F.ax.add_patch(Rectangle((X0, Y0), bw, bh, fc="#f4f4f4", ec="#444444", lw=0.8, zorder=45, alpha=0.97))
    for i, (k, v) in enumerate(rows):
        yy = Y0 + lh * (i + 0.9)
        F.ax.text(X0 + F.pts_to_px(4), yy, k, fontsize=5.0, family="Liberation Sans", color="#555555", va="center", zorder=47)
        F.ax.text(X0 + F.pts_to_px(4) + kw, yy, v, fontsize=5.0, family="Liberation Sans", color="#111111", va="center", zorder=47,
                  fontweight="bold" if k.startswith("AADT_") and yv_latest(years) == k[5:] else "normal")
    ex = min(max(x, X0), X0 + bw); ey = min(max(y, Y0), Y0 + bh)
    F.ax.annotate("", xy=(x, y), xytext=(ex, ey), arrowprops=dict(arrowstyle="-|>", color=AADT_BLUE, lw=1.3, mutation_scale=10), zorder=46)


def yv_latest(years):
    return years[-1] if years else ""


def _aadt_callout(F: Figure, text, box_frac, anchor=None, size=7.6):
    bx, by = F.frac(*box_frac)
    t = F.ax.text(bx, by, text, fontsize=size, family="Liberation Sans", fontweight="bold", ha="center", va="center", zorder=49, linespacing=1.35,
                  bbox=dict(boxstyle="square,pad=0.6", fc=AADT_CALLOUT, ec="#2b4a7a", lw=1.0))
    if anchor:
        F.fig.canvas.draw()
        e = t.get_window_extent().transformed(F.ax.transData.inverted())
        x, y = F.px(*anchor)
        ex = min(max(x, e.x0), e.x1); ey = min(max(y, e.y0), e.y1)
        F.ax.annotate("", xy=(x, y), xytext=(ex, ey), arrowprops=dict(arrowstyle="-|>", color=AADT_BLUE, lw=1.4, mutation_scale=10), zorder=48)


def figure_aadt_map(study: Study, cache: TileCache, out_png, out_pdf, z: int = 16):
    """Stand-alone AADT map: NCDOT road lines, the study route dashed yellow, stations with their latest counts."""
    cfg = study.cfg
    fat = cfg["fatal"]
    with open(os.path.join(study.root, cfg["inputs"]["aadt"])) as f:
        aadt = json.load(f)
    bm = _load_basemap(study)
    bbox = tuple(cfg["figures"]["aadt_bbox"])
    F = Figure(cache, None, bbox, z, strip=False, title_gap=0.04)
    if bm:
        _draw_vector_basemap(F, bm, road_scale=1.4, water=True)
        # study route in dashed yellow over the gray line
        route_names = set(cfg["figures"].get("aadt_route_names", [cfg["route"].get("ncdot_name", "")]))
        for ft in bm["roads"]["features"]:
            if ft["properties"].get("RouteName") in route_names:
                F.lines_from_geojson(ft["geometry"], color="#f5d800", lw=2.6, ls=(0, (6, 3)), zorder=11)
    # road names in the yellow-with-dark-halo style
    for rl in cfg["figures"].get("aadt_road_names", []):
        F.ax.text(*F.px(rl["lat"], rl["lon"]), rl["text"], fontsize=6.4, family="Liberation Sans", fontweight="bold", color="#ffe600",
                  ha="center", va="center", rotation=rl.get("rot", 0), zorder=40, clip_on=True, linespacing=1.1,
                  path_effects=[pe.withStroke(linewidth=2.2, foreground="#222222")])
    # study location
    F.crash_circle(fat["lat"], fat["lon"], radius_pt=10, color=AADT_BLUE, lw=2.6)
    # stations
    labels = cfg["figures"].get("aadt_labels", {})
    shown = []
    for stn in aadt["stations"]:
        if stn["id"] in labels and labels[stn["id"]].get("hide"):
            continue
        if not F.inside(stn["lat"], stn["lon"], 0.02):
            continue
        shown.append(stn)
        _aadt_station_box(F, stn, labels.get(stn["id"], {"bx": 0.5, "by": 0.5}), county=cfg.get("county", ""))
    for co in cfg["figures"].get("aadt_callouts", []):
        _aadt_callout(F, co["text"], tuple(co["box_frac"]), anchor=(co["lat"], co["lon"]) if "lat" in co else None)
    _compass_rose(F)
    F.scale_bar(cfg["figures"].get("aadt_scale_ft", 2000), "Feet", fx=0.015, fy=0.012, divisions=4, anchor="left")
    title = f"Slip No. {cfg['figures']['slip_no']} AADT Map ({fat['lat']}, {fat['lon']})"
    F.fig.text(F.L, F.T + 0.010, title, fontsize=12.5, fontweight="bold", family="Liberation Sans", va="bottom")
    src = "AADT: " + aadt.get("source", "") + ". Roads: NCDOT RoadNC centerlines. TEAAS strip analysis ADT used for the study: " + f"{cfg.get('adt', 0):,}."
    for i, ln in enumerate(textwrap.wrap(src, 200)[:2]):
        F.fig.text(F.L, F.B - 0.010 - 0.010 * i, ln, fontsize=5.4, color="#555555", va="center", family="Liberation Sans")
    F.save(out_png, out_pdf)


def build_figures(study: Study, screened: list[Screened], out_dir: str, tile_cache_dir: str, decisions=None) -> list[str]:
    cache = TileCache(tile_cache_dir)
    sid = study.study_id
    paths = []
    # file names follow the study folders: <id>_AreaMap, <id>_LocationMap, <id>_CrashMap, <id>_AADTMap
    figs = [("AreaMap", lambda a, b: figure_area_map(study, cache, a, b)),
            ("LocationMap", lambda a, b: figure_location_map(study, cache, a, b)),
            ("CrashMap", lambda a, b: figure_crash_map(study, screened, cache, a, b, decisions=decisions))]
    if "aadt" in study.cfg.get("inputs", {}):
        figs.append(("AADTMap", lambda a, b: figure_aadt_map(study, cache, a, b)))
    for name, fn in figs:
        png = os.path.join(out_dir, f"{sid}_{name}.png"); pdf = os.path.join(out_dir, f"{sid}_{name}.pdf")
        fn(png, pdf); paths += [png, pdf]
    return paths
