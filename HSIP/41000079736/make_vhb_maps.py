#!/usr/bin/env python3
"""Location Map and Area Map for study 41000079736 in the layout of the TSU/VHB package maps
(see the 4100007xxxx_LocationMap.pdf / _AreaMap.pdf examples): letter landscape, map frame with a thin black border,
NC county inset top-left with the study county in red, north arrow + scale box bottom-left, footer with WO Number,
PH Number, NCDOT Division, Study Area, Lat/Long and a data-source line. Basemaps: Esri World Imagery (area map) and
OpenStreetMap rendered in grey (location map); county outlines from the NCDOT County_Boundary feature service.
Outputs: maps/41000079736_LocationMap.pdf/.png and maps/41000079736_AreaMap.pdf/.png
"""
import json, math
from pathlib import Path
import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
from matplotlib import font_manager
from matplotlib.patches import Circle, Rectangle, Polygon, FancyBboxPatch, Ellipse
from PIL import Image, ImageOps
import make_maps as M

HERE = Path(__file__).resolve().parent; OUT = HERE / "maps"
WO, PH, DIV = "41000079736", "TSUINT716412", "12"
LAT, LON = M.LAT, M.LON
STUDY_AREA = ["NC 180/NC 226 (S Post Rd) at SR 1103", "(Pleasant Dr/Pleasant Hill Church Rd)", "in Cleveland County"]
COUNTY = "CLEVELAND"
PW, PH_IN = 11.0, 8.5                      # letter landscape, inches
FRAME = (0.22, 1.52, 10.78, 8.32)          # map frame: x0, y0, x1, y1 (inches, origin bottom-left)
for cand in ("Carlito", "Liberation Sans", "DejaVu Sans"):
    if any(f.name == cand for f in font_manager.fontManager.ttflist): FONT = cand; break
plt.rcParams["font.family"] = FONT; plt.rcParams["pdf.fonttype"] = 42


def page():
    fig = plt.figure(figsize=(PW, PH_IN))
    fw, fh = FRAME[2] - FRAME[0], FRAME[3] - FRAME[1]
    ax = fig.add_axes([FRAME[0] / PW, FRAME[1] / PH_IN, fw / PW, fh / PH_IN]); ax.set_axis_off()
    return fig, ax, fw, fh


def frame_border(fig):
    fig.add_artist(Rectangle((FRAME[0] / PW, FRAME[1] / PH_IN), (FRAME[2] - FRAME[0]) / PW, (FRAME[3] - FRAME[1]) / PH_IN,
                             transform=fig.transFigure, fill=False, ec="k", lw=1.0, zorder=20))


def inset(fig):
    """NC counties, study county in red, white box at the top-left of the frame"""
    geo = json.loads((OUT / ".tiles" / "nc_counties.geojson").read_text())
    w, h = 2.35, 0.95
    ax = fig.add_axes([(FRAME[0] + 0.02) / PW, (FRAME[3] - h - 0.02) / PH_IN, w / PW, h / PH_IN], zorder=25)
    ax.set_xticks([]); ax.set_yticks([]); ax.set_facecolor("white")
    for s in ax.spines.values(): s.set_linewidth(0.8)
    for f in geo["features"]:
        name = f["properties"]["NAME"].upper()
        for poly in f["geometry"]["coordinates"]:
            ring = poly[0]
            ax.add_patch(Polygon(ring, closed=True, fc=("#e00000" if name == COUNTY else "white"), ec="#777", lw=0.35, zorder=2))
    ax.set_xlim(-84.4, -75.4); ax.set_ylim(33.75, 36.7); ax.set_aspect(1 / math.cos(math.radians(35.3)))


def north_scale(fig, ax, mpp, units):
    """white box bottom-left of the frame: north arrow in a black disc + alternating scale bar ('feet' or 'miles')"""
    fw = FRAME[2] - FRAME[0]
    x0, x1 = ax.get_xlim(); m_per_in = abs(x1 - x0) * mpp / fw          # map metres per page inch
    if units == "feet": segs, lab, unit_m = [0, 300, 600], ["0", "300", "600"], 0.3048
    else: segs, lab, unit_m = [0, 0.5, 1, 2], ["0", "0.5", "1", "2"], 1609.344
    bar = segs[-1] * unit_m / m_per_in                                   # bar length, inches
    sx, h = 0.58, 0.48; w = sx + bar + 0.55
    bx = fig.add_axes([(FRAME[0] + 0.02) / PW, (FRAME[1] + 0.02) / PH_IN, w / PW, h / PH_IN], zorder=25)
    bx.set_xlim(0, w); bx.set_ylim(0, h); bx.set_xticks([]); bx.set_yticks([]); bx.set_facecolor("white")
    for s in bx.spines.values(): s.set_linewidth(0.8)
    bx.add_patch(Circle((0.27, h / 2), 0.17, fc="k", ec="k", zorder=3))
    bx.add_patch(Polygon([(0.27, h / 2 + 0.13), (0.19, h / 2 - 0.10), (0.27, h / 2 - 0.04), (0.35, h / 2 - 0.10)], fc="white", ec="white", zorder=4))
    bx.text(0.27, h / 2 - 0.16, "N", ha="center", va="center", fontsize=5, color="white", fontweight="bold", zorder=5)
    y = 0.17
    for i in range(len(segs) - 1):
        a, b = segs[i] * unit_m / m_per_in, segs[i + 1] * unit_m / m_per_in
        bx.add_patch(Rectangle((sx + a, y), b - a, 0.07, fc=("k" if i % 2 == 0 else "white"), ec="k", lw=0.6, zorder=3))
    for sg, l in zip(segs, lab): bx.text(sx + sg * unit_m / m_per_in, y + 0.11, l, ha="center", va="bottom", fontsize=6.5)
    bx.text(sx + bar + 0.06, y + 0.035, "Feet" if units == "feet" else "Miles", ha="left", va="center", fontsize=6.5)


def footer(fig, source):
    L, R = 0.25, PW - 0.25
    rows = [("WO Number", f" {WO}"), ("PH Number", f" {PH}"), ("NCDOT Division", f" {DIV}")]
    for i, (k, v) in enumerate(rows):
        y = (1.22 - i * 0.30) / PH_IN
        t = fig.text(L / PW, y, k, fontsize=11, fontweight="bold", va="center", ha="left")
        fig.canvas.draw(); bb = t.get_window_extent().transformed(fig.transFigure.inverted())
        fig.text(bb.x1, y, v, fontsize=11, va="center", ha="left")
    fig.text(0.5, 1.22 / PH_IN, "Study Area", fontsize=11, fontweight="bold", ha="center", va="center")
    for i, line in enumerate(STUDY_AREA):
        fig.text(0.5, (0.92 - i * 0.26) / PH_IN, line, fontsize=11, ha="center", va="center")
    for i, (k, v) in enumerate((("Lat", f"  {LAT:.6f}"), ("Long", f" {LON:.6f}"))):
        y = (1.22 - i * 0.30) / PH_IN
        fig.text((R - 1.0) / PW, y, k, fontsize=11, fontweight="bold", va="center", ha="right")
        fig.text((R - 1.0) / PW, y, v, fontsize=11, va="center", ha="left")
    fig.text(0.1 / PW, 0.09 / PH_IN, f"Data Source: {source}", fontsize=7.5, style="italic", ha="left", va="center", color="#333")


def halo_text(ax, x, y, s, rot=0, size=8, color="k", weight="normal"):
    import matplotlib.patheffects as pe
    ax.text(x, y, s, rotation=rot, rotation_mode="anchor", ha="center", va="center", fontsize=size, color=color, fontweight=weight, zorder=12,
            path_effects=[pe.withStroke(linewidth=2.5, foreground="white")])


def nc_shield(ax, x, y, num, size=16):
    ax.add_patch(Polygon([(x, y - size), (x + size, y), (x, y + size), (x - size, y)], closed=True, fc="k", ec="white", lw=1.0, zorder=12))
    ax.text(x, y, num, ha="center", va="center", fontsize=6.5, color="white", fontweight="bold", zorder=13)


def red_ring(ax, x, y, r):
    ax.add_patch(Circle((x, y), r, fill=False, ec="#e00000", lw=3.2, zorder=14))


# ---------------------------------------------------------------- Location Map
def location_map():
    fig, ax, fw, fh = page()
    half_w = 11500.0; half_h = half_w * fh / fw
    im, to_px, mpp = M.basemap(M.OSM, 12, half_w, half_h)
    g = ImageOps.grayscale(im); im = Image.blend(g.convert("RGB"), Image.new("RGB", g.size, "white"), 0.22)   # grey, lightened
    ax.imshow(im); ax.set_xlim(0, im.width); ax.set_ylim(im.height, 0)
    x, y = to_px(LAT, LON); red_ring(ax, x, y, 0.15 * im.width / fw)
    frame_border(fig); inset(fig); north_scale(fig, ax, mpp, "miles")
    footer(fig, "NCDOT, OpenStreetMap contributors, VHB")
    fig.savefig(OUT / "41000079736_LocationMap.pdf"); fig.savefig(OUT / "41000079736_LocationMap.png", dpi=150); plt.close(fig)


# ---------------------------------------------------------------- Area Map
def area_map():
    fig, ax, fw, fh = page()
    half_w = 540.0; half_h = half_w * fh / fw
    im, to_px, mpp = M.basemap(M.ESRI_IMG, 17, half_w, half_h)
    ax.imshow(im); ax.set_xlim(0, im.width); ax.set_ylim(im.height, 0)
    ppi = im.width / fw                                           # image px per page inch
    x, y = to_px(LAT, LON); red_ring(ax, x, y, 0.15 * ppi)
    def along(bearing, d_m):
        return to_px(LAT + d_m * math.cos(math.radians(bearing)) / 111320, LON + d_m * math.sin(math.radians(bearing)) / (111320 * math.cos(math.radians(LAT))))
    # callout
    cx, cy = along(300, 260)
    ax.annotate("Crash Location: NC 180/NC 226 at SR 1103", xy=(x - 0.12 * ppi, y - 0.08 * ppi), xytext=(cx, cy), fontsize=8, ha="center", va="center", zorder=15,
                bbox=dict(boxstyle="square,pad=0.45", fc="white", ec="k", lw=0.8), arrowprops=dict(arrowstyle="-", color="k", lw=0.8, shrinkA=0, shrinkB=0))
    # route shields and street names along the legs
    for bearing in (M.BEAR_MAIN, M.BEAR_MAIN + 180):
        sx, sy = along(bearing, 300); nc_shield(ax, sx - 11, sy, "180", 15); nc_shield(ax, sx + 13, sy, "226", 15)
        nx, ny = along(bearing, 190); halo_text(ax, nx, ny, "S Post Rd", rot=90 - M.BEAR_MAIN, size=7.5)
    for bearing, name in ((M.BEAR_SIDE, "Pleasant Dr (SR 1103)"), (M.BEAR_SIDE + 180, "Pleasant Hill Church Rd (SR 1103)")):
        nx, ny = along(bearing, 300); halo_text(ax, nx, ny, name, rot=90 - M.BEAR_SIDE + (180 if bearing > 180 else 0) + (0 if bearing > 180 else 180), size=7.5)
    frame_border(fig); inset(fig); north_scale(fig, ax, mpp, "feet")
    footer(fig, "NCDOT, Esri World Imagery, VHB")
    fig.savefig(OUT / "41000079736_AreaMap.pdf"); fig.savefig(OUT / "41000079736_AreaMap.png", dpi=150); plt.close(fig)


if __name__ == "__main__":
    location_map(); area_map(); print("wrote", OUT / "41000079736_LocationMap.pdf", OUT / "41000079736_AreaMap.pdf", "font", FONT)
