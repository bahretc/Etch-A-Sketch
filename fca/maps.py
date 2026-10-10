"""Study maps: static PNGs (matplotlib over stitched basemap tiles) and a self-contained Leaflet HTML."""
from __future__ import annotations

import base64
import json
import math
import os

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
from matplotlib.lines import Line2D
from matplotlib.patches import FancyBboxPatch

from .geo import (FT_PER_MILE, Polyline, TILE_SOURCES, TileCache, dist_ft, ft_per_deg_lon, FT_PER_DEG_LAT,
                  lonlat_to_pixel, meters_per_pixel, stitch, tile_range)
from .screen import Screened, Study, review_list
from .teaas import TYPE_NAMES, TYPE_LONG, SEVERITY_LONG

DECISION_STYLE = {
    "IS": {"label": "In study (IS)", "color": "#1f77b4"},
    "ADD": {"label": "Added to study (ADD)", "color": "#d62728"},
    "DEL": {"label": "Deleted from study (DEL)", "color": "#ff7f0e"},
    "NIS": {"label": "Not in study (NIS), report reviewed", "color": "#bdbdbd"},
}
PRIORITY_STYLE = {
    0: {"label": "In initial study", "color": "#1f77b4", "marker": "o"},
    1: {"label": "Likely ADD (locates inside the section)", "color": "#d62728", "marker": "o"},
    2: {"label": "Possible ADD (at a limit / by description)", "color": "#ff7f0e", "marker": "o"},
    3: {"label": "Window (just outside the limits)", "color": "#e6c300", "marker": "o"},
    4: {"label": "At the NC 179 intersection (likely NIS)", "color": "#9e9e9e", "marker": "o"},
    5: {"label": "Check (location by description only)", "color": "#ffffff", "marker": "o"},
}
SECTION_COLOR = "#ff2a2a"


# ------------------------------------------------------------------ crash placement

def crash_points(study: Study, screened: list[Screened], decisions: dict | None = None) -> list[dict]:
    """One dict per review-list crash with a plotted (lat, lon), how it was placed, and display fields.

    With decisions ({crash_id: {decision, mp, lat, lon, n, ...}} from a report review) the reviewed crashes are
    placed at the report location; a reviewed crash with no location on the route gets lat/lon None (off map).
    """
    pl = study.centerline
    out = []
    if decisions:
        items = [s for s in screened if s.row.crash_id in decisions]
        items.sort(key=lambda s: decisions[s.row.crash_id].get("n", 999))
        seq = [(decisions[s.row.crash_id].get("n", i), s) for i, s in enumerate(items, 1)]
    else:
        seq = list(enumerate(review_list(screened), 1))
    for n, s in seq:
        r = s.row
        d = study.detailed.get(r.crash_id)
        placed, basis = None, ""
        dec = decisions.get(r.crash_id) if decisions else None
        if dec and dec.get("lat") and dec.get("lon"):
            placed, basis = (dec["lat"], dec["lon"]), "report location (coordinates agree)"
        elif dec and dec.get("mp") is not None:
            placed, basis = pl.point_at_mi(dec["mp"]), f"report MP {dec['mp']:.3f} on the centerline"
        elif dec:
            placed, basis = None, "not on the study route per the report"
        elif s.dmv_mp is not None and s.latlon:
            placed, basis = s.latlon, f"{d.source} coordinates"
        elif s.in_initial and r.mp is not None and not r.unmileposted:
            placed, basis = pl.point_at_mi(r.mp), f"coded MP {r.mp:.3f} on the centerline"
        elif s.implied_mp is not None and "Between" in s.triggers:
            placed, basis = pl.point_at_mi(max(0.0, s.implied_mp)), f"MP {s.implied_mp:.3f} implied by the description"
        elif r.mp is not None and not r.unmileposted and r.mp_road == study.route_name:
            placed, basis = pl.point_at_mi(r.mp), f"coded MP {r.mp:.3f} on the centerline"
        elif s.implied_mp is not None:
            placed, basis = pl.point_at_mi(max(0.0, s.implied_mp)), f"MP {s.implied_mp:.3f} implied by the description"
        if placed is None and not dec:
            continue
        prio = dec["decision"] if dec else (0 if s.in_initial else s.priority)
        out.append({
            "n": n, "crash_id": r.crash_id, "date": r.date, "lat": placed[0] if placed else None,
            "lon": placed[1] if placed else None, "basis": basis,
            "priority": prio, "flag": s.flag, "trigger": s.trigger, "reason": s.reason,
            "decision": dec["decision"] if dec else None, "report_location": (dec or {}).get("location", ""),
            "report_mp": (dec or {}).get("mp"),
            "type": TYPE_NAMES.get(r.T, str(r.T)), "type_long": TYPE_LONG.get(r.T, str(r.T)),
            "severity": r.S or "O", "mp": None if r.unmileposted else r.mp, "on_road": r.on_road,
            "desc": f"{r.on_road} {r.miles if r.miles is not None else 0:g} mi {r.dir} from {r.from_road or '-'} toward {r.toward_road or '-'}".replace("  ", " "),
            "fatal": r.crash_id == study.cfg["fatal"]["crash_id"],
            "mp_along": pl.project(placed).along_mi if placed else None,
        })
    return out


# ------------------------------------------------------------------ static map helpers

class PngMap:
    def __init__(self, cache: TileCache, source: str, bbox, z: int, figsize=(11, 8.5), dpi=150, right_panel=0.0):
        self.cache, self.source, self.bbox, self.z = cache, source, bbox, z
        self.img, (self.px0, self.py0) = stitch(cache, source, bbox, z)
        self.fig = plt.figure(figsize=figsize, dpi=dpi)
        left, width = 0.02, 0.96 - right_panel
        self.ax = self.fig.add_axes([left, 0.07, width, 0.835])
        w, h = self.img.size
        self.ax.imshow(self.img, extent=(self.px0, self.px0 + w, self.py0 + h, self.py0), interpolation="bilinear")
        x0, y1 = lonlat_to_pixel(bbox[0], bbox[1], z)
        x1, y0 = lonlat_to_pixel(bbox[2], bbox[3], z)
        self.ax.set_xlim(x0, x1)
        self.ax.set_ylim(y1, y0)
        self.ax.set_xticks([]); self.ax.set_yticks([])
        for sp in self.ax.spines.values():
            sp.set_edgecolor("#333333")
        self.center_lat = (bbox[1] + bbox[3]) / 2
        self.ft_per_px = meters_per_pixel(self.center_lat, z) * 3.28084
        # how many display points one world pixel occupies (for sizing marker offsets)
        self.fig.canvas.draw()
        bb = self.ax.get_window_extent()
        self.screen_px_per_px = (bb.width / (x1 - x0)) * 72.0 / self.fig.dpi

    def px(self, lat: float, lon: float):
        return lonlat_to_pixel(lon, lat, self.z)

    def line(self, latlons, **kw):
        xs, ys = zip(*[self.px(a, b) for a, b in latlons])
        return self.ax.plot(xs, ys, **kw)

    def scalebar(self, ft: float, label: str, pos=(0.03, 0.04)):
        ax = self.ax
        x0, x1 = ax.get_xlim(); y1, y0 = ax.get_ylim()
        w = ft / self.ft_per_px
        bx = x0 + (x1 - x0) * pos[0]
        by = y1 - (y1 - y0) * pos[1]
        ax.add_patch(FancyBboxPatch((bx - 8, by - 26), w + 16, 36, boxstyle="round,pad=2", fc="white", ec="#333", alpha=0.9, zorder=50))
        ax.plot([bx, bx + w], [by, by], color="black", lw=3, zorder=51, solid_capstyle="butt")
        ax.plot([bx, bx], [by - 5, by + 5], color="black", lw=1.5, zorder=51)
        ax.plot([bx + w, bx + w], [by - 5, by + 5], color="black", lw=1.5, zorder=51)
        ax.text(bx + w / 2, by - 9, label, ha="center", va="bottom", fontsize=8, zorder=52)

    def north(self, pos=(0.96, 0.92)):
        ax = self.ax
        x0, x1 = ax.get_xlim(); y1, y0 = ax.get_ylim()
        x = x0 + (x1 - x0) * pos[0]; y = y1 - (y1 - y0) * pos[1]
        ax.annotate("", xy=(x, y - 40), xytext=(x, y), arrowprops=dict(arrowstyle="-|>", color="white", lw=4), zorder=50)
        ax.annotate("", xy=(x, y - 40), xytext=(x, y), arrowprops=dict(arrowstyle="-|>", color="black", lw=2), zorder=51)
        ax.text(x, y - 46, "N", ha="center", va="bottom", fontsize=11, fontweight="bold", color="black",
                bbox=dict(boxstyle="circle,pad=0.2", fc="white", ec="black"), zorder=52)

    def title(self, title: str, subtitle: str = ""):
        import textwrap
        self.fig.text(0.02, 0.968, title, fontsize=13, fontweight="bold", va="center")
        if subtitle:
            width = int(self.fig.get_figwidth() * 15)
            self.fig.text(0.02, 0.945, "\n".join(textwrap.wrap(subtitle, width)), fontsize=8.5, va="top", color="#333", linespacing=1.3)

    def attribution(self, extra: str = ""):
        txt = "Basemap: " + TILE_SOURCES[self.source]["attribution"] + ("  |  " + extra if extra else "")
        self.fig.text(0.02, 0.025, txt, fontsize=7, color="#444", va="center")

    def halo_text(self, lat, lon, text, dx=0, dy=0, **kw):
        import matplotlib.patheffects as pe
        x, y = self.px(lat, lon)
        kw.setdefault("fontsize", 8)
        kw.setdefault("color", "white")
        kw.setdefault("zorder", 40)
        return self.ax.text(x + dx, y + dy, text, path_effects=[pe.withStroke(linewidth=2.5, foreground="black")], **kw)

    def save(self, path: str):
        self.fig.savefig(path, dpi=self.fig.dpi, facecolor="white")
        plt.close(self.fig)


def _section_bbox(study: Study, pad_ft: float = 320.0, mp_pad: float = 0.03):
    pl = study.centerline
    pts = pl.slice(max(0.0, (study.begin_mp - mp_pad)) * FT_PER_MILE, (study.end_mp + mp_pad) * FT_PER_MILE)
    pts.append((study.cfg["intersection"]["lat"], study.cfg["intersection"]["lon"]))
    lats = [p[0] for p in pts]; lons = [p[1] for p in pts]
    lat0 = sum(lats) / len(lats)
    dlat = pad_ft / FT_PER_DEG_LAT; dlon = pad_ft / ft_per_deg_lon(lat0)
    return (min(lons) - dlon, min(lats) - dlat, max(lons) + dlon, max(lats) + dlat)


def _draw_section(m: PngMap, study: Study, lw=6, with_labels=True, feature_labels=True, label_gap=22):
    pl = study.centerline
    cfg = study.cfg
    b, e = study.begin_mp, study.end_mp
    sec = pl.slice(b * FT_PER_MILE, e * FT_PER_MILE)
    # route beyond the section, thin
    m.line(pl.pts, color="white", lw=lw * 0.6, alpha=0.6, zorder=10, solid_capstyle="round")
    m.line(sec, color="white", lw=lw + 4, zorder=11, solid_capstyle="round")
    m.line(sec, color=SECTION_COLOR, lw=lw, zorder=12, solid_capstyle="round")
    # limit ticks (perpendicular to the road) and labels on the east side
    for mp, name, which in ((b, cfg["limits"]["begin_desc"], "BEGIN"), (e, cfg["limits"]["end_desc"], "END")):
        p = pl.point_at_mi(mp)
        brg = math.radians(pl.bearing_at(mp * FT_PER_MILE))
        nx, ny = math.cos(brg), math.sin(brg)   # unit normal in pixel space (x east, y south)
        x, y = m.px(*p)
        L = 14
        m.ax.plot([x - nx * L, x + nx * L], [y - ny * L, y + ny * L], color="white", lw=5, zorder=13)
        m.ax.plot([x - nx * L, x + nx * L], [y - ny * L, y + ny * L], color=SECTION_COLOR, lw=2.5, zorder=14)
        if with_labels:
            ox, oy = (nx, ny) if nx >= 0 else (-nx, -ny)
            m.halo_text(p[0], p[1], f"{which} MP {mp:.3f}\n{name}", dx=ox * label_gap + 6, dy=oy * label_gap,
                        fontsize=8, fontweight="bold", ha="left", va="center", color="#fff2a8")
    if feature_labels:
        for f in cfg.get("features", []):
            if f.get("limit") or "lat" not in f:
                continue
            x, y = m.px(f["lat"], f["lon"])
            if "CHARROS" in " ".join(f.get("fiche_names", [])).upper():
                continue
            m.ax.plot(x, y, marker="o", ms=6, mfc="white", mec="black", zorder=20)
            side = f.get("label_side", "E")
            dx = {"E": 10, "W": -10, "N": 0, "S": 0}[side]
            dy = {"E": 0, "W": 0, "N": -12, "S": 12}[side]
            ha = {"E": "left", "W": "right", "N": "center", "S": "center"}[side]
            label = f["name"] if side != "W" else f["name"]
            m.halo_text(f["lat"], f["lon"], f"{label}\nMP {f['mp']:.3f}", dx=dx, dy=dy, ha=ha, va="center", fontsize=7.5)


def _draw_fatal(m: PngMap, study: Study, label=True):
    f = study.cfg["fatal"]
    x, y = m.px(f["lat"], f["lon"])
    m.ax.plot(x, y, marker="*", ms=22, mfc="#ffd400", mec="black", mew=1.2, zorder=30)
    if label:
        m.halo_text(f["lat"], f["lon"], f"Fatal crash {f['crash_id']}\n{f['date']} {f.get('time', '')}  MP {f['mp']:.3f}\nLos Nuevos Charros PVA",
                    dx=16, dy=-2, ha="left", va="center", fontsize=8, fontweight="bold", color="#ffd400")


# ------------------------------------------------------------------ the three PNG maps

def map_location(study: Study, cache: TileCache, out_path: str):
    cfg = study.cfg
    bbox = tuple(cfg["map"]["location_bbox"])
    m = PngMap(cache, "streets", bbox, 15, figsize=(11, 8.5))
    _draw_section(m, study, lw=7, with_labels=False, feature_labels=False)
    f = cfg["fatal"]
    x, y = m.px(f["lat"], f["lon"])
    m.ax.plot(x, y, marker="*", ms=20, mfc="#ffd400", mec="black", mew=1.2, zorder=30)
    lim = cfg["limits"]
    m.halo_text(f["lat"], f["lon"], f"Study section\n{cfg['route']['name']} ({cfg['route'].get('local_name', '')})\n"
                f"MP {lim['begin_mp']:.3f} to {lim['end_mp']:.3f}", dx=22, dy=-30, ha="left", va="center", fontsize=9,
                fontweight="bold", color="white")
    m.title(f"Fatal Crash Analysis {study.study_id} - Location map",
            f"{cfg['route']['name']} ({cfg['route'].get('local_name', '')}) in Calabash, {cfg['county'].title()} County, Division {cfg['division']}. "
            f"Fatal crash {f['crash_id']}, {f['date']} {f.get('time', '')} (star).")
    m.scalebar(FT_PER_MILE * 0.5, "0.5 mile")
    m.north()
    handles = [Line2D([0], [0], color=SECTION_COLOR, lw=5, label=f"Study section (MP {lim['begin_mp']:.3f} - {lim['end_mp']:.3f}, {lim.get('length_mi', 0):.2f} mi)"),
               Line2D([0], [0], marker="*", color="w", mfc="#ffd400", mec="black", ms=14, label="Fatal crash (slip coordinates)")]
    m.ax.legend(handles=handles, loc="lower right", fontsize=8, framealpha=0.92)
    m.attribution()
    m.save(out_path)


def map_section(study: Study, cache: TileCache, out_path: str, z: int = 19):
    cfg = study.cfg
    bbox = _section_bbox(study)
    m = PngMap(cache, "imagery", bbox, z, figsize=(11, 8.5))
    _draw_section(m, study, lw=6)
    _draw_fatal(m, study)
    i = cfg["intersection"]
    lim = cfg["limits"]
    m.title(f"Fatal Crash Analysis {study.study_id} - Study section",
            f"{cfg['route']['name']} ({cfg['route'].get('local_name', '')}) from the {lim['begin_desc']} (MP {lim['begin_mp']:.3f}) to {lim['end_desc']} "
            f"(MP {lim['end_mp']:.3f}), {lim.get('length_mi', 0):.2f} mi. Mileposts increase {cfg['route'].get('mp_increases', '')}; revised MPs per the TEAAS strip diagram.")
    m.scalebar(200, "200 ft")
    m.north()
    handles = [Line2D([0], [0], color=SECTION_COLOR, lw=5, label="Study section"),
               Line2D([0], [0], color="white", lw=3, alpha=0.8, label=f"{cfg['route']['name']} beyond the limits"),
               Line2D([0], [0], marker="o", color="w", mfc="white", mec="black", ms=7, label="Feature (side street) with milepost"),
               Line2D([0], [0], marker="*", color="w", mfc="#ffd400", mec="black", ms=14, label="Fatal crash (DMV-349 coordinates)")]
    m.ax.legend(handles=handles, loc="lower right", fontsize=8, framealpha=0.92)
    m.attribution("Centerline: OpenStreetMap")
    m.save(out_path)


def map_crashes(study: Study, screened: list[Screened], cache: TileCache, out_path: str, z: int = 19):
    cfg = study.cfg
    pts = crash_points(study, screened)
    bbox = _section_bbox(study, pad_ft=260)
    m = PngMap(cache, "imagery", bbox, z, figsize=(15, 9), right_panel=0.36)
    _draw_section(m, study, lw=6, with_labels=True, feature_labels=False, label_gap=120)
    # features as small ticks with short names
    for f in cfg.get("features", []):
        if f.get("limit") or "lat" not in f or "CHARROS" in " ".join(f.get("fiche_names", [])).upper():
            continue
        side = f.get("label_side", "E")
        dx = {"E": 8, "W": -8, "N": 0}[side]; ha = {"E": "left", "W": "right", "N": "center"}[side]
        dy = -10 if side == "N" else 0
        m.halo_text(f["lat"], f["lon"], f["short"], dx=dx, dy=dy, ha=ha, va="center", fontsize=7, color="#dddddd")
    # markers with collision avoidance: search rings around the true point, perpendicular to the road first,
    # and keep every marker inside the frame; the limit labels are blocked so markers do not sit on them
    pl = study.centerline
    sep = 34 / m.screen_px_per_px          # marker diameter (points) -> world pixels
    x0, x1 = m.ax.get_xlim(); y1, y0 = m.ax.get_ylim()
    margin = sep * 0.7
    blocked = []
    for mp in (study.begin_mp, study.end_mp):
        p = pl.point_at_mi(mp)
        brg = math.radians(pl.bearing_at(mp * FT_PER_MILE))
        nx, ny = math.cos(brg), math.sin(brg)
        ox, oy = (nx, ny) if nx >= 0 else (-nx, -ny)
        bx, by = m.px(*p)
        lx, ly = bx + ox * 120 + 6, by + oy * 120
        text_w = 300 / m.screen_px_per_px * 0.9
        for t in range(0, int(text_w), int(sep * 0.6)):
            blocked.append((lx + t, ly - sep * 0.3)); blocked.append((lx + t, ly + sep * 0.3))
    placed_px = []
    def free(px_, py_):
        if not (x0 + margin < px_ < x1 - margin and y0 + margin < py_ < y1 - margin):
            return False
        return all(math.hypot(px_ - qx, py_ - qy) >= sep for qx, qy in placed_px + blocked)
    for p in sorted(pts, key=lambda q: (q["priority"] != 0, q["mp_along"])):
        x, y = m.px(p["lat"], p["lon"])
        brg = math.radians(pl.bearing_at(p["mp_along"] * FT_PER_MILE))
        perp = math.atan2(math.sin(brg), math.cos(brg))     # angle of the unit normal in pixel space
        lx, ly = x, y
        if not free(lx, ly):
            found = False
            for ring in range(1, 8):
                for da in (0, 180, 45, 225, 135, 315, 90, 270, 22, 202, 158, 338, 68, 248, 112, 292):
                    a = perp + math.radians(da)
                    cx, cy = x + math.cos(a) * sep * ring, y + math.sin(a) * sep * ring
                    if free(cx, cy):
                        lx, ly, found = cx, cy, True
                        break
                if found:
                    break
        placed_px.append((lx, ly))
        st = PRIORITY_STYLE[p["priority"]]
        if (lx, ly) != (x, y):
            m.ax.plot([x, lx], [y, ly], color="white", lw=1.2, zorder=24)
            m.ax.plot(x, y, marker=".", ms=6, color="white", zorder=25)
        if p["fatal"]:
            m.ax.plot(lx, ly, marker="*", ms=24, mfc="#ffd400", mec="black", mew=1.2, zorder=30)
        else:
            m.ax.plot(lx, ly, marker="o", ms=15, mfc=st["color"], mec="black", mew=1.0, zorder=28,
                      alpha=1.0 if p["priority"] != 5 else 0.85)
        m.ax.text(lx, ly, str(p["n"]), ha="center", va="center", fontsize=7.5, fontweight="bold",
                  color="black" if p["priority"] in (3, 5, 0) or p["fatal"] else "white", zorder=31)
    lim = cfg["limits"]
    m.title(f"Fatal Crash Analysis {study.study_id} - Crash map (TEAAS strip crashes and fiche review candidates)",
            f"{cfg['route']['name']} ({cfg['route'].get('local_name', '')}) MP {lim['begin_mp']:.3f} to {lim['end_mp']:.3f}, {cfg['period']['begin']} to {cfg['period']['end']}. "
            f"Numbers match the Review IDs sheet order. Points sit at Detailed Fiche coordinates where available, otherwise on the centerline at the coded or implied milepost.")
    m.scalebar(200, "200 ft")
    m.north(pos=(0.95, 0.93))
    # right panel: list
    fig = m.fig
    panel = fig.add_axes([0.63, 0.07, 0.36, 0.835]); panel.axis("off")
    panel.set_xlim(0, 1); panel.set_ylim(0, 1)
    yy = 0.995
    panel.text(0.0, yy, "Crashes shown (number = Review IDs order)", fontsize=10, fontweight="bold", va="top"); yy -= 0.03
    for prio in (0, 1, 2, 3, 4, 5):
        grp = [p for p in pts if p["priority"] == prio]
        if not grp:
            continue
        st = PRIORITY_STYLE[prio]
        panel.plot([0.012], [yy - 0.009], marker="o", ms=9, mfc=st["color"], mec="black", clip_on=False)
        panel.text(0.035, yy, st["label"], fontsize=8.5, fontweight="bold", va="top"); yy -= 0.025
        for p in grp:
            line = f"{p['n']:>2}  {p['crash_id']}  {p['date']}  {p['type']:<5} {p['severity']}"
            if p["mp"] is not None:
                line += f"  MP {p['mp']:.3f}"
            panel.text(0.035, yy, line, fontsize=7.6, va="top", family="DejaVu Sans Mono"); yy -= 0.0165
            panel.text(0.062, yy, "at " + p["basis"], fontsize=6.3, va="top", color="#444"); yy -= 0.0145
        yy -= 0.006
    panel.text(0.0, yy - 0.004, "K fatal, B/C injury class, O property damage only; type codes per the TEAAS index.",
               fontsize=6.5, va="top", color="#444")
    m.attribution("Centerline: OpenStreetMap")
    m.save(out_path)


# ------------------------------------------------------------------ Leaflet HTML

def _embed_tiles(cache: TileCache, source: str, bbox, zooms) -> dict[str, str]:
    tiles = {}
    for z in zooms:
        x0, y0, x1, y1 = tile_range(bbox, z)
        for x in range(x0, x1 + 1):
            for y in range(y0, y1 + 1):
                data = cache.get(source, z, x, y)
                if data:
                    mime = "image/png" if data[:4] == b"\x89PNG" else "image/jpeg"
                    tiles[f"{z}/{x}/{y}"] = f"data:{mime};base64," + base64.b64encode(data).decode()
    return tiles


def map_html(study: Study, screened: list[Screened], cache: TileCache, out_path: str, decisions: dict | None = None):
    cfg = study.cfg
    here = os.path.dirname(__file__)
    with open(os.path.join(here, "vendor", "leaflet.js")) as f:
        leaflet_js = f.read()
    with open(os.path.join(here, "vendor", "leaflet.css")) as f:
        leaflet_css = f.read()
    pts = [p for p in crash_points(study, screened, decisions) if p["lat"] is not None]
    pl = study.centerline
    b, e = study.begin_mp, study.end_mp
    bbox = _section_bbox(study, pad_ft=900)
    tiles = _embed_tiles(cache, "imagery", bbox, [15, 16, 17, 18, 19])
    data = {
        "study": {k: cfg[k] for k in ("study_id", "title", "county", "division", "route", "limits", "period", "fatal", "intersection")},
        "section": pl.slice(b * FT_PER_MILE, e * FT_PER_MILE),
        "route": pl.pts,
        "begin": pl.point_at_mi(b), "end": pl.point_at_mi(e),
        "features": [f for f in cfg.get("features", []) if "lat" in f],
        "crashes": pts,
        "styles": DECISION_STYLE if decisions else PRIORITY_STYLE,
        "center": [cfg["fatal"]["lat"], cfg["fatal"]["lon"]],
        "attribution": TILE_SOURCES["imagery"]["attribution"],
        "streets_url": TILE_SOURCES["streets"]["url"].replace("{z}", "{z}").replace("{y}", "{y}").replace("{x}", "{x}"),
        "imagery_url": TILE_SOURCES["imagery"]["url"],
    }
    html = f"""<!doctype html>
<html lang="en"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width, initial-scale=1">
<title>{cfg['study_id']} crash map</title>
<style>{leaflet_css}</style>
<style>
 html,body{{margin:0;height:100%;font-family:system-ui,Segoe UI,Arial,sans-serif}}
 #map{{position:absolute;inset:0}}
 .legend{{background:rgba(255,255,255,.95);padding:8px 10px;border-radius:6px;box-shadow:0 1px 5px rgba(0,0,0,.4);font-size:12px;line-height:1.35;max-width:300px}}
 .legend h3{{margin:0 0 4px;font-size:13px}} .legend .sw{{display:inline-block;width:12px;height:12px;border-radius:50%;border:1px solid #000;vertical-align:middle;margin-right:5px}}
 .legend .ln{{display:inline-block;width:18px;height:5px;background:{SECTION_COLOR};vertical-align:middle;margin-right:5px}}
 .num{{color:#000;font-weight:700;font-size:10px;text-align:center;line-height:18px;width:18px;height:18px;border-radius:50%;border:1px solid #000;box-shadow:0 0 3px #000}}
 .popup b{{font-size:13px}} .popup .r{{color:#333;font-size:11px;margin-top:4px}}
 .lbl{{color:#fff;font-weight:600;font-size:11px;text-shadow:0 0 3px #000,0 0 3px #000,0 0 3px #000;white-space:nowrap}}
</style></head>
<body><div id="map"></div>
<script>{leaflet_js}</script>
<script>
const DATA = {json.dumps(data)};
const TILES = {json.dumps(tiles)};
const Embedded = L.TileLayer.extend({{
  getTileUrl: function(c) {{ const k = c.z + '/' + c.x + '/' + c.y; return TILES[k] || L.Util.template(DATA.imagery_url, {{z:c.z,x:c.x,y:c.y}}); }}
}});
const imagery = new Embedded('', {{maxZoom: 20, maxNativeZoom: 19, attribution: DATA.attribution}});
const streets = L.tileLayer(DATA.streets_url, {{maxZoom: 19, attribution: 'Esri World Street Map'}});
const map = L.map('map', {{center: DATA.center, zoom: 18, layers: [imagery]}});
L.control.scale({{imperial: true, metric: false}}).addTo(map);
const toLL = p => [p[0], p[1]];
const routeLine = L.polyline(DATA.route.map(toLL), {{color:'#fff', weight: 3, opacity: .7}});
const secLine = L.polyline(DATA.section.map(toLL), {{color:'{SECTION_COLOR}', weight: 7, opacity: .95}});
const lim = DATA.study.limits;
const limits = L.layerGroup([
  L.circleMarker(toLL(DATA.begin), {{radius: 7, color:'#fff', fillColor:'{SECTION_COLOR}', fillOpacity: 1, weight: 2}}).bindTooltip('BEGIN MP ' + lim.begin_mp.toFixed(3) + ' - ' + lim.begin_desc, {{permanent: true, direction: 'right', className: 'lbl'}}),
  L.circleMarker(toLL(DATA.end), {{radius: 7, color:'#fff', fillColor:'{SECTION_COLOR}', fillOpacity: 1, weight: 2}}).bindTooltip('END MP ' + lim.end_mp.toFixed(3) + ' - ' + lim.end_desc, {{permanent: true, direction: 'right', className: 'lbl'}})
]);
const feats = L.layerGroup(DATA.features.filter(f => !f.limit).map(f =>
  L.circleMarker([f.lat, f.lon], {{radius: 5, color:'#000', fillColor:'#fff', fillOpacity: 1, weight: 1}})
   .bindTooltip(f.name + ' (MP ' + f.mp.toFixed(3) + (f.inventory_mp ? ', inventory ' + f.inventory_mp.toFixed(3) : '') + ')', {{permanent: true, direction: (f.label_side === 'W' ? 'left' : f.label_side === 'N' ? 'top' : 'right'), className: 'lbl'}})));
function popup(c) {{
  return '<div class="popup"><b>' + (c.fatal ? 'FATAL ' : '') + 'Crash ' + c.crash_id + '</b> &nbsp;#' + c.n + '<br>' + c.date + ' &middot; ' + c.type_long + ' &middot; severity ' + c.severity +
    '<br>' + c.desc + (c.mp !== null ? ' (coded MP ' + c.mp.toFixed(3) + ')' : ' (MP 999.999)') +
    '<br><i>Plotted at: ' + c.basis + '</i><div class="r"><b>' + c.flag + ' / ' + c.trigger + '</b><br>' + c.reason + '</div></div>';
}}
const groups = {{}};
DATA.crashes.forEach(c => {{
  const st = DATA.styles[c.priority];
  const icon = L.divIcon({{className: '', html: '<div class="num" style="background:' + (c.fatal ? '#ffd400' : st.color) + ';color:' + ([3,5,0,'IS','NIS'].includes(c.priority) || c.fatal ? '#000' : '#fff') + '">' + c.n + '</div>', iconSize: [18, 18], iconAnchor: [9, 9]}});
  const mk = L.marker([c.lat, c.lon], {{icon}}).bindPopup(popup(c), {{maxWidth: 420}});
  (groups[c.priority] = groups[c.priority] || []).push(mk);
}});
const overlays = {{'Study section': L.layerGroup([routeLine, secLine, limits]).addTo(map), 'Features': feats.addTo(map)}};
Object.keys(DATA.styles).forEach(k => {{ if (groups[k]) overlays[DATA.styles[k].label] = L.layerGroup(groups[k]).addTo(map); }});
L.control.layers({{'Imagery (embedded, Esri)': imagery, 'Streets (online, Esri)': streets}}, overlays, {{collapsed: false}}).addTo(map);
const legend = L.control({{position: 'bottomleft'}});
legend.onAdd = function() {{
  const d = L.DomUtil.create('div', 'legend');
  let h = '<h3>' + DATA.study.study_id + ' - ' + DATA.study.route.name + ' (' + DATA.study.route.local_name + ')</h3>' +
    '<span class="ln"></span>Section MP ' + lim.begin_mp.toFixed(3) + ' to ' + lim.end_mp.toFixed(3) + ' (' + lim.begin_desc + ' to ' + lim.end_desc + ')<br>';
  Object.keys(DATA.styles).forEach(k => {{ if (groups[k]) h += '<span class="sw" style="background:' + DATA.styles[k].color + '"></span>' + DATA.styles[k].label + ' (' + groups[k].length + ')<br>'; }});
  h += '<div style="margin-top:4px;color:#444;font-size:11px">Numbers follow the Review IDs sheet. Click a marker for the crash and the screening reason. Imagery tiles are embedded for zoom 15-19 around the section.</div>';
  d.innerHTML = h; return d;
}};
legend.addTo(map);
</script></body></html>"""
    with open(out_path, "w") as f:
        f.write(html)


def build_maps(study: Study, screened: list[Screened], out_dir: str, tile_cache_dir: str) -> list[str]:
    cache = TileCache(tile_cache_dir)
    sid = study.study_id
    paths = []
    p = os.path.join(out_dir, f"{sid}_Map1_Location.png"); map_location(study, cache, p); paths.append(p)
    p = os.path.join(out_dir, f"{sid}_Map2_StudySection.png"); map_section(study, cache, p); paths.append(p)
    p = os.path.join(out_dir, f"{sid}_Map3_CrashMap.png"); map_crashes(study, screened, cache, p); paths.append(p)
    p = os.path.join(out_dir, f"{sid}_CrashMap.html"); map_html(study, screened, cache, p); paths.append(p)
    return paths
