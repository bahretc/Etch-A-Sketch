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
from matplotlib.transforms import Bbox
from matplotlib.patches import Circle, Rectangle, Polygon, FancyBboxPatch, Ellipse
from PIL import Image, ImageOps
import make_maps as M

HERE = Path(__file__).resolve().parent; OUT = HERE / "maps"
WO, PH, DIV = "41000079736", "TSUINT716412", "12"
LAT, LON = M.LAT, M.LON
STUDY_AREA = ["NC 180/NC 226 (S Post Rd) at SR 1103", "(Pleasant Dr/Pleasant Hill Church Rd)", "in Cleveland County"]
COUNTY = "CLEVELAND"
PW, PH_IN = 11.0, 8.5                      # letter landscape, inches
FRAME_DEFAULT = (0.22, 1.52, 10.78, 8.32)  # map frame: x0, y0, x1, y1 (inches, origin bottom-left)
FRAME = FRAME_DEFAULT
for cand in ("Carlito", "Liberation Sans", "DejaVu Sans"):
    if any(f.name == cand for f in font_manager.fontManager.ttflist): FONT = cand; break
plt.rcParams["font.family"] = FONT; plt.rcParams["pdf.fonttype"] = 42


def page(frame=FRAME_DEFAULT):
    global FRAME; FRAME = frame
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
    elif units == "feet2": segs, lab, unit_m = [0, 1000, 2000], ["0", "1,000", "2,000"], 0.3048
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
    bx.text(sx + bar + 0.06, y + 0.035, "Feet" if units.startswith("feet") else "Miles", ha="left", va="center", fontsize=6.5)


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
    fig.text(R / PW, 1.22 / PH_IN, "Lat, Long", fontsize=11, fontweight="bold", va="center", ha="right")
    fig.text(R / PW, 0.92 / PH_IN, f"{LAT:.6f}, {LON:.6f}", fontsize=11, va="center", ha="right")
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


# ---------------------------------------------------------------- AADT Map (station annual AADTs, relevant years boxed in red)
def aadt_map():
    import json as _json
    A = _json.loads((HERE / "aadt.json").read_text()); mid = A["entering_aadt"]["study_10yr_middle_year"]; yr = mid["year"]
    fig, ax, fw, fh = page((0.22, 1.52, 10.78, 8.02))
    half_h = 1100.0; half_w = half_h * fw / fh
    im, to_px, mpp = M.basemap(M.OSM, 16, half_w, half_h, lat=LAT - 0.0032)           # centred between the N and S stations
    g = ImageOps.grayscale(im); im = Image.blend(g.convert("RGB"), Image.new("RGB", g.size, "white"), 0.30)
    ax.imshow(im); ax.set_xlim(0, im.width); ax.set_ylim(im.height, 0)
    ppi = im.width / fw
    fig.text(FRAME[0] / PW, (FRAME[3] + 0.08) / PH_IN, f"Order {WO} PH {PH} AADT Map ({LAT:.6f}, {LON:.6f})", fontsize=12, fontweight="bold", ha="left", va="bottom")
    x, y = to_px(LAT, LON)
    ax.add_patch(Circle((x, y), 0.12 * ppi, fill=False, ec="#1f5fd0", lw=2.8, zorder=14))
    YEL, BLU = "#ffffc0", "#cfe6ff"
    def callout(px_xy, text_lines, anchor_in, fc, boxed=(), size=7.2, bold_first=False):
        """lines of text in a box (fc) whose top-left is anchor_in inches from the station point; red box around `boxed` lines;
        thin blue leader from the box edge to the point"""
        sx, sy = px_xy; bx, by = sx + anchor_in[0] * ppi, sy + anchor_in[1] * ppi
        lead = size * 1.55 / 72 * ppi                                               # line pitch in image px
        arts = []
        for i, line in enumerate(text_lines):
            kw = dict(fontsize=size, ha="left", va="top", zorder=16, fontweight=("bold" if bold_first and i == 0 else "normal"))
            if i in boxed: kw["bbox"] = dict(boxstyle="square,pad=0.15", fc="none", ec="#e00000", lw=1.1)
            arts.append(ax.text(bx, by + i * lead, line, **kw))
        fig.canvas.draw(); r = fig.canvas.get_renderer()
        bb = None
        for t in arts:
            e = t.get_window_extent(r).transformed(ax.transData.inverted()); bb = e if bb is None else Bbox.union([bb, e])
        pad = 0.05 * ppi
        x0, x1 = min(bb.x0, bb.x1) - pad, max(bb.x0, bb.x1) + pad; y0, y1 = min(bb.y0, bb.y1) - pad, max(bb.y0, bb.y1) + pad   # y grows downward
        ax.add_patch(Rectangle((x0, y0), x1 - x0, y1 - y0, fc=fc, ec="k", lw=0.7, zorder=15))
        cands = [(x0, y0), (x1, y0), (x0, y1), (x1, y1), ((x0 + x1) / 2, y0), ((x0 + x1) / 2, y1), (x0, (y0 + y1) / 2), (x1, (y0 + y1) / 2)]
        c = min(cands, key=lambda q: (q[0] - sx) ** 2 + (q[1] - sy) ** 2)
        ax.plot([c[0], sx], [c[1], sy], color="#1f5fd0", lw=1.0, zorder=14)
    # stations: annual AADTs, newest first; the middle-year count boxed, or the two counts an estimate was interpolated from
    offsets = {"N": (0.9, 0.1), "S": (0.6, -1.7), "NW": (-2.75, -1.45), "SE": (1.5, 0.6)}
    for key, leg in zip(M.LEG_KEYS, A["legs"]):
        sx, sy = to_px(leg["lat"], leg["lon"])
        ax.plot(sx, sy, "o", ms=6, color="#1f5fd0", mec="white", mew=0.8, zorder=13)
        years = sorted(leg["aadt"], reverse=True)
        lines = [f"Station {leg['station']}"] + [f"{y_} AADT = {leg['aadt'][y_]:,}" for y_ in years]
        if key in mid["estimated"]:
            lo = max(y_ for y_ in years if int(y_) < yr); hi = min(y_ for y_ in years if int(y_) > yr)
            boxed = {1 + years.index(lo), 1 + years.index(hi)}
        else:
            boxed = {1 + years.index(str(yr))}
        callout((sx, sy), lines, offsets[key], YEL, boxed=boxed, bold_first=True)
    # study callouts (blue)
    nw = A["legs"][2]; swx, swy = to_px(nw["lat"], nw["lon"])
    callout((swx, swy), [f"Interpolated between the 2018 and 2022 AADT", f"{yr} AADT = {mid['legs']['NW']:,} (estimate)"], (-2.75, -0.55), BLU, size=7.5)
    legs = mid["legs"]
    callout((x, y), ["Location of Intersection Study", "NC 180/NC 226 (S Post Road) at", "SR 1103 (Pleasant Drive/Pleasant Hill Church Road)", "",
                     f"{yr} Intersection ADT = ({legs['N']:,} + {legs['S']:,} + {legs['NW']:,} + {legs['SE']:,}) / 2 = {mid['entering']:,}",
                     "TEAAS study ADT 12,300 is within 5 % of this, so 12,300 is kept"], (1.5, -0.3), BLU, size=7.8, bold_first=True)
    # road names
    def along(bearing, d_m):
        return to_px(LAT + d_m * math.cos(math.radians(bearing)) / 111320, LON + d_m * math.sin(math.radians(bearing)) / (111320 * math.cos(math.radians(LAT))))
    for bearing, name, d in ((M.BEAR_MAIN, "S POST RD\n(NC 180/NC 226)", 420), (M.BEAR_MAIN + 180, "S POST RD\n(NC 180/NC 226)", 700),
                             (M.BEAR_SIDE, "PLEASANT DR\n(SR 1103)", 620), (M.BEAR_SIDE + 180, "PLEASANT HILL CHURCH RD\n(SR 1103)", 650)):
        lx, ly = along(bearing, d)
        ax.text(lx, ly, name, fontsize=6.5, ha="center", va="center", zorder=12, color="#5a4a00", fontweight="bold",
                bbox=dict(boxstyle="square,pad=0.25", fc=YEL, ec="none"))
    frame_border(fig); north_scale(fig, ax, mpp, "feet2")
    footer(fig, "NCDOT Traffic Survey Group AADT stations, OpenStreetMap contributors, VHB")
    fig.savefig(OUT / "41000079736_AADTMap.pdf"); fig.savefig(OUT / "41000079736_AADTMap.png", dpi=150); plt.close(fig)


if __name__ == "__main__":
    location_map(); area_map(); aadt_map(); print("wrote", OUT / "41000079736_LocationMap.pdf", OUT / "41000079736_AreaMap.pdf", "font", FONT)
